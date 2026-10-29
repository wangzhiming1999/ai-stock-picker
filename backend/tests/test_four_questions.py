"""四问守卫的测试（calibers.four_questions）。

## 这层要防什么

`calibers` 登记的是**口径定义**，解决「这个数字是什么意思」。它挡不住另一类错误：
口径完全正确，但**样本量、分布形态、可成交性没交代**，数字照样会被读成能力。

真实踩过的三个例子（见 calibers.py 顶部注释）：
  · 同参数回测三次得 +28.20% / +14.37% / +30.94%，差异全来自「这次跑成了几只」
  · 涨停次日溢价收益大头在换手<5% 的**买不进**档（+3.31%），可成交档收窄到 +1%
  · 「月均 5%」达成率仅 17.6%、亏损窗口 39.2%、中位数只有 +4.1%

## 三态纪律（本文件最重要的一类断言）

`answered=False`（答不上来）必须与 `passed=False`（回答了但不通过）严格区分。
把它混成 False 会让「没有这项数据」看起来像「检查没过」—— 前端会给出
「已检查、发现失真」的假警报，而真实情况是根本没法检查。

更糟的反向错误：把「答不上来」折算成「通过」。那样四问守卫就变成了
「没数据 = 合格」的橡皮章，比没有守卫更坏。
"""
import pytest

from app.services import calibers


class TestTristate:
    """passed 必须是三态：True / False / None（答不上来）。"""

    def test_missing_data_is_none_not_false(self) -> None:
        """除 n 外的三项全缺数据时，必须 answered=False、passed=None。

        n 是唯一「永远答得上」的参数（传进来就算答了），所以这里用 n=50 让
        sample 问明确通过 —— 顺带验证混合状态下三态没串。
        """
        result = calibers.four_questions(n=50)
        by_key = {i["key"]: i for i in result["items"]}

        assert by_key["sample"]["answered"] is True
        assert by_key["sample"]["passed"] is True
        for key in ("median", "tradable", "benchmark_sign"):
            assert by_key[key]["answered"] is False, key
            assert by_key[key]["passed"] is None, key

    def test_missing_data_never_counts_as_passed(self) -> None:
        """橡皮章防线：答不上来的项绝不能出现在 passed 的成功集合里。"""
        result = calibers.four_questions(n=50)

        assert result["failed_keys"] == []
        assert set(result["unanswered_keys"]) == {"median", "tradable", "benchmark_sign"}
        # 答不上来 3 项 ⇒ verdict 必须是 unknown，不能是 credible
        assert result["verdict"] == "unknown"

    def test_partial_data_answers_only_what_it_can(self) -> None:
        """只给中位数与均值时，只有这一问该是 answered=True。"""
        result = calibers.four_questions(n=50, median=1.2, mean=1.4)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["median"]["answered"] is True
        assert by_key["tradable"]["answered"] is False
        assert by_key["benchmark_sign"]["answered"] is False

    def test_half_given_distribution_is_still_unanswered(self) -> None:
        """只给中位数不给均值 ⇒ 分布形态判不出来，如实标答不上来。"""
        result = calibers.four_questions(n=50, median=1.2)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["median"]["answered"] is False
        assert by_key["median"]["passed"] is None


class TestVerdict:
    """verdict 三态互斥，且必须由「有明确失真项」优先于「有答不上来项」决定。"""

    def test_all_answered_and_clean_is_credible(self) -> None:
        result = calibers.four_questions(
            n=120, median=1.1, mean=1.2, tradable_ratio=0.8, benchmark_sign_flips=False
        )

        assert result["verdict"] == "credible"
        assert result["answered_count"] == 4
        assert result["failed_keys"] == []

    def test_one_failed_item_is_inflated(self) -> None:
        result = calibers.four_questions(
            n=120, median=1.1, mean=1.2, tradable_ratio=0.3, benchmark_sign_flips=False
        )

        assert result["verdict"] == "inflated"
        assert result["failed_keys"] == ["tradable"]

    def test_failure_outranks_unanswered(self) -> None:
        """同时有失真项与答不上来项时，必须报 inflated（更严重的那个）。"""
        result = calibers.four_questions(
            n=120, median=1.1, mean=1.2, tradable_ratio=0.3
        )

        assert result["verdict"] == "inflated"
        assert result["failed_keys"] == ["tradable"]
        assert "benchmark_sign" in result["unanswered_keys"]

    def test_credible_note_never_claims_strategy_is_good(self) -> None:
        """credible 只说「数字可信」，绝不说「策略有效」——那是另一层结论。"""
        result = calibers.four_questions(
            n=120, median=1.1, mean=1.2, tradable_ratio=0.8, benchmark_sign_flips=False
        )

        assert "不代表策略有效" in result["verdict_note"]


class TestSampleGate:
    def test_below_threshold_fails(self) -> None:
        result = calibers.four_questions(n=29)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["sample"]["passed"] is False
        assert str(calibers.MIN_SAMPLE) in by_key["sample"]["detail"]

    def test_at_threshold_passes(self) -> None:
        result = calibers.four_questions(n=calibers.MIN_SAMPLE)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["sample"]["passed"] is True

    def test_zero_sample_still_answers_the_question(self) -> None:
        """n=0 也必须回答（有 n 吗 → 没有），不能退化成「答不上来」。"""
        result = calibers.four_questions(n=0)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["sample"]["answered"] is True
        assert by_key["sample"]["passed"] is False


class TestSignFlipLabels:
    """第四问的文案必须可覆盖 —— 通用文案假设了「有收益」，对方向预测是错的。"""

    def test_labels_only_change_text_never_verdict(self) -> None:
        base = calibers.four_questions(n=200, benchmark_sign_flips=True)
        custom = calibers.four_questions(
            n=200,
            benchmark_sign_flips=True,
            sign_flip_labels=("未超过基线", "命中率未超过无脑猜震荡"),
        )

        assert custom["verdict"] == base["verdict"] == "inflated"
        assert custom["failed_keys"] == base["failed_keys"]
        # 只有文案变了
        assert custom["items"][3]["value"] == "未超过基线"
        assert custom["items"][3]["detail"] == "命中率未超过无脑猜震荡"

    def test_default_labels_speak_about_returns(self) -> None:
        """默认文案是给「有收益」的口径用的 —— 说「收益来自贝塔」。"""
        item = calibers.four_questions(n=200, benchmark_sign_flips=True)["items"][3]

        assert item["value"] == "符号翻转"
        assert "贝塔" in item["detail"]

    def test_pass_side_text_is_generic_enough(self) -> None:
        """通过侧的文案不能提「收益」—— 覆盖后仍是中性表述。"""
        item = calibers.four_questions(
            n=200, benchmark_sign_flips=False,
            sign_flip_labels=("未超过基线", "未超过无脑猜震荡"),
        )["items"][3]

        assert item["passed"] is True
        assert "收益" not in item["detail"]
        assert "对照" in item["detail"]


class TestMedianGuard:
    def test_large_gap_fails_and_names_the_culprit(self) -> None:
        """中位数与均值差 >1pct ⇒ 均值被极端样本拉偏，必须点名引用中位数。"""
        result = calibers.four_questions(n=200, median=0.4, mean=3.1)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["median"]["passed"] is False
        assert "中位数" in by_key["median"]["detail"]

    def test_sign_disagreement_is_called_out(self) -> None:
        """中位数为正、均值为负 —— 这是最阴的一类，必须显式说明。"""
        result = calibers.four_questions(n=200, median=1.0, mean=-2.0)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["median"]["passed"] is False
        assert "中位数为正、均值为负" in by_key["median"]["detail"]

    def test_sign_flip_with_tiny_gap_still_fails(self) -> None:
        """符号相反时，绝对差与相对倍数都盖不住 —— 必须靠第三条判据拦下。

        这是 2026-10-20 线上真实数字（`/api/market/winrate` 主口径 n=48）：
        中位 −0.43%、均值 +0.41%。两条旧判据算出来分别是
        0.84 < 1.0 与 0.95 < 1.3，于是判成「分布未明显偏斜」——
        而它的真实含义是**过半交易跑输指数、正期望全靠少数尾部样本**。
        """
        result = calibers.four_questions(n=48, median=-0.43, mean=0.41)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["median"]["passed"] is False
        assert "符号相反" in by_key["median"]["detail"]
        # 方向文案不能写反：这次是中位数为负
        assert "中位数为负、均值为正" in by_key["median"]["detail"]

    def test_opposite_signs_but_zero_median_stays_quiet(self) -> None:
        """中位数为 0 时乘积为 0，不触发符号判据（贴 0 的正常分布不该狼来了）。"""
        result = calibers.four_questions(n=200, median=0.0, mean=0.3)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["median"]["passed"] is True

    def test_small_gap_passes(self) -> None:
        result = calibers.four_questions(n=200, median=1.10, mean=1.20)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["median"]["passed"] is True

    def test_relative_multiple_catches_low_base_case(self) -> None:
        """低基线场景：绝对差不到 1pct，但均值是中位数的 1.95 倍 ⇒ 必须报警。

        这是 2026-10-17 上线当天实测漏掉的第二个案例（39 次 +1% + 1 次 +40%）。
        单用绝对差阈值时它判成「未明显偏斜」—— 而这恰恰是最该被质疑的分布。
        """
        result = calibers.four_questions(n=40, median=1.0, mean=1.95)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["median"]["passed"] is False
        assert "倍" in by_key["median"]["detail"]

    def test_both_criteria_reported_when_both_trip(self) -> None:
        """绝对差与相对倍数同时超限时，两个理由都要出现在 detail 里。"""
        result = calibers.four_questions(n=200, median=0.4, mean=3.1)

        detail = {i["key"]: i for i in result["items"]}["median"]["detail"]
        assert "个百分点" in detail
        assert "倍" in detail
    def test_relative_guard_needs_a_meaningful_denominator(self) -> None:
        """中位数为 0 时相对倍数无意义，必须退回只看绝对差，不得凭空报警。

        若在这里除以 |median|=0，要么 ZeroDivisionError，要么被写成
        「分母为 0 时 ratio 视为无穷大」—— 后者会让 0 vs 0.01 这种
        完全正常的分布被误判成严重偏斜，守卫一旦狼来了就没人看了。
        """
        near_zero = calibers.four_questions(n=200, median=0.0, mean=0.01)

        by_key = {i["key"]: i for i in near_zero["items"]}
        assert by_key["median"]["passed"] is True
        assert "中位数为 0 只看绝对差" in by_key["median"]["detail"]

        # 中位数贴近 0 但非 0：相对倍数仍然生效（2 倍 ⇒ 报警）
        small = calibers.four_questions(n=200, median=0.01, mean=0.02)
        assert {i["key"]: i for i in small["items"]}["median"]["passed"] is False

    def test_both_criteria_are_or_not_and(self) -> None:
        """复合判据是 OR 不是 AND —— 任一指标显示偏斜就该报（守卫偏保守）。"""
        # 只有绝对差超标（中位 5 / 均值 6.2，相对 1.24 < 1.3）
        gap_only = calibers.four_questions(n=200, median=5.0, mean=6.2)
        assert {i["key"]: i for i in gap_only["items"]}["median"]["passed"] is False

        # 只有相对倍数超标（中位 1.0 / 均值 1.95，绝对差 0.95 < 1.0）
        ratio_only = calibers.four_questions(n=200, median=1.0, mean=1.95)
        assert {i["key"]: i for i in ratio_only["items"]}["median"]["passed"] is False


class TestTradableGuard:
    """可成交比例 —— 涨停次日溢价「收益大头在买不进的档」的直接对应物。"""

    def test_low_ratio_fails(self) -> None:
        result = calibers.four_questions(n=200, tradable_ratio=0.4)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["tradable"]["passed"] is False
        assert "买不进" in by_key["tradable"]["detail"]

    def test_high_ratio_passes(self) -> None:
        result = calibers.four_questions(n=200, tradable_ratio=0.9)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["tradable"]["passed"] is True

    def test_zero_ratio_is_a_real_answer_not_missing(self) -> None:
        """0% 可成交是「回答了且极差」，不是「答不上来」。"""
        result = calibers.four_questions(n=200, tradable_ratio=0.0)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["tradable"]["answered"] is True
        assert by_key["tradable"]["passed"] is False


class TestBenchmarkSignGuard:
    def test_flip_fails_and_names_beta(self) -> None:
        result = calibers.four_questions(n=200, benchmark_sign_flips=True)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["benchmark_sign"]["passed"] is False
        assert "贝塔" in by_key["benchmark_sign"]["detail"]

    def test_no_flip_passes(self) -> None:
        result = calibers.four_questions(n=200, benchmark_sign_flips=False)

        by_key = {i["key"]: i for i in result["items"]}
        assert by_key["benchmark_sign"]["passed"] is True


class TestMedianHelper:
    def test_odd_length(self) -> None:
        assert calibers.median_of([3.0, 1.0, 2.0]) == 2.0

    def test_even_length_averages_middle(self) -> None:
        assert calibers.median_of([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_empty_is_none_not_zero(self) -> None:
        """空样本返回 None：返回 0 会被读成「超额中位数为 0」这个具体结论。"""
        assert calibers.median_of([]) is None


class TestShapeContract:
    """返回结构契约 —— 前端按固定形状渲染，改字段名要同步改前端。"""

    @pytest.mark.parametrize("n", [0, 29, 200])
    def test_always_returns_four_items_in_fixed_order(self, n: int) -> None:
        result = calibers.four_questions(n=n)

        assert [i["key"] for i in result["items"]] == [
            "sample", "median", "tradable", "benchmark_sign",
        ]
        assert result["total_questions"] == 4

    def test_labels_are_stable_and_shared_with_the_contract(self) -> None:
        """问法文案集中在一处；前端不得自行改写（否则守卫与界面会各说一套）。"""
        result = calibers.four_questions(n=10)

        assert [i["label"] for i in result["items"]] == [
            calibers.QUESTION_LABELS["sample"],
            calibers.QUESTION_LABELS["median"],
            calibers.QUESTION_LABELS["tradable"],
            calibers.QUESTION_LABELS["benchmark_sign"],
        ]

    def test_every_verdict_has_a_note(self) -> None:
        """三种 verdict 都必须带解释文案，禁止前端拿到裸字符串自己发挥。"""
        cases = {
            "credible": calibers.four_questions(
                n=200, median=1.0, mean=1.0, tradable_ratio=0.9, benchmark_sign_flips=False
            ),
            "inflated": calibers.four_questions(n=5),
            "unknown": calibers.four_questions(n=200),
        }
        for expected, result in cases.items():
            assert result["verdict"] == expected
            assert result["verdict_note"].strip()
            assert result["verdict_note"] == calibers.VERDICT_NOTE[expected]
