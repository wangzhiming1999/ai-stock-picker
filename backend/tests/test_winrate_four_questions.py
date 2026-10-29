"""胜率接口的「四问守卫」接线测试。

## 锁的是什么

`calibers.four_questions` 是纯函数（本文件不测它，见 test_four_questions.py）。
这里锁的是**接线**：真实数据必须真的喂进去，且喂错时不能静默。

三条最容易被写错、且写错后完全静默的地方：
  1. **可成交比例的分母**。`execution_status` 是 v16 新列，v16 未跑时整列为 NULL。
     此时必须整问标 answered=False（答不上来），而不是当成 0%（全都买不进）——
     前者会提示「未跑迁移」，后者会给出一个凭空而来的假警报。
  2. **中位数只能用 excess_return**，不能用旧的 next_return。两者的判定规则不同
     （前者减基准、后者不减），混用会让「中位数」这个数字对应另一套口径。
  3. **符号翻转必须如实标 unknown**。本链路只有沪深300 一条基准，答不上来就是答不上来，
     不允许为了「四问全绿」去编一个 False。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import winrate_service as wr


class _Chain:
    """Supabase 查询链的最小替身（与 test_calibers.py 同款）。"""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def __getattr__(self, _name: str) -> "_Chain":
        return self

    def __call__(self, *_a, **_k) -> "_Chain":
        return self

    async def execute(self):
        return SimpleNamespace(data=self._rows)


def _fake_client(tables: dict[str, list]):
    class _Client:
        def table(self, name: str) -> _Chain:
            return _Chain(tables.get(name, []))

    async def _get():
        return _Client()

    return _get


def _rows(items: list[dict]) -> dict:
    return {
        "prediction_records": [],
        "daily_recommendations": items,
        "winrate_snapshot": [],
    }


async def _stats(monkeypatch, items: list[dict]) -> dict:
    monkeypatch.setattr(wr.supabase_store, "is_configured", lambda: True)
    monkeypatch.setattr(wr.supabase_store, "get_service_client", _fake_client(_rows(items)))
    return await wr.get_winrate_stats()


def _by_key(four: dict) -> dict[str, dict]:
    return {i["key"]: i for i in four["items"]}


class TestTradableRatio:
    @pytest.mark.asyncio
    async def test_ratio_comes_from_execution_status(self, monkeypatch) -> None:
        """可成交比例 = filled / **全部到期推荐**（含 not_triggered / unverifiable）。

        分母刻意用全部到期行，而不是主口径行：`not_triggered`（计划价没碰到）与
        `unverifiable` 本来就被排除在胜率分母之外，若再从可成交比例的分母里剔掉，
        这个比例会恒等于 100% —— 恰好把「买不进」这个最该暴露的问题藏掉了。
        3 filled / 5 到期 = 60%。
        """
        stats = await _stats(monkeypatch, [
            {"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "filled"},
            {"hit": True, "source": "llm", "excess_return": 2.0, "execution_status": "filled"},
            {"hit": False, "source": "llm", "excess_return": -1.0, "execution_status": "filled"},
            {"hit": None, "source": "llm", "excess_return": None, "execution_status": "not_triggered"},
            {"hit": None, "source": "llm", "excess_return": None, "execution_status": "unverifiable"},
        ])
        reco = stats["recommendation"]
        by_key = _by_key(reco["four_questions"])

        # 主口径 3 条（not_triggered / unverifiable 已被过滤，不计胜率）
        assert reco["total"] == 3
        assert reco["not_triggered"] == 1
        assert reco["unverifiable"] == 1
        # 但可成交比例的分母是全部 5 条到期行
        assert by_key["tradable"]["answered"] is True
        assert by_key["tradable"]["passed"] is True
        assert "60.0%" in by_key["tradable"]["value"]

    @pytest.mark.asyncio
    async def test_low_fill_ratio_is_reported_as_a_loss(self, monkeypatch) -> None:
        """filled 少、not_triggered 多 ⇒ 这一问判不过。

        1 filled / 4 到期 = 25%，低于 50% 门槛。胜率数字本身仍然只算那 1 条，
        但可成交比例会把「另外 3 条根本没买进」显式摊出来。
        """
        stats = await _stats(monkeypatch, [
            {"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "filled"},
            {"hit": None, "source": "llm", "excess_return": None, "execution_status": "not_triggered"},
            {"hit": None, "source": "llm", "excess_return": None, "execution_status": "not_triggered"},
            {"hit": None, "source": "llm", "excess_return": None, "execution_status": "not_triggered"},
        ])
        reco = stats["recommendation"]
        by_key = _by_key(reco["four_questions"])

        assert reco["not_triggered"] == 3
        assert by_key["tradable"]["passed"] is False
        assert "25.0%" in by_key["tradable"]["value"]
        assert "买不进" in by_key["tradable"]["detail"]
        assert reco["four_questions"]["verdict"] == "inflated"
        assert reco["four_questions"]["failed_keys"] == ["sample", "tradable"]

    @pytest.mark.asyncio
    async def test_null_status_column_degrades_to_unanswered(self, monkeypatch) -> None:
        """v16 未跑时 execution_status 全 NULL ⇒ 整问答不上来，绝不能当成 0%。

        样本给到 120 条以隔离出「可成交这一问答不上来」这一个变量 ——
        否则 n 过小会先触发 sample 失真，把 verdict 变成 inflated，看不出这一问的状态。
        """
        stats = await _stats(monkeypatch, [
            {"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": None}
            for _ in range(120)
        ])
        reco = stats["recommendation"]
        by_key = _by_key(reco["four_questions"])

        assert by_key["tradable"]["answered"] is False
        assert by_key["tradable"]["passed"] is None
        assert "benchmark_sign" in reco["four_questions"]["unanswered_keys"]
        # 其余三问都干净 ⇒ unknown（不是 inflated，也不是虚假的 credible）
        assert reco["four_questions"]["verdict"] == "unknown"
        assert reco["four_questions"]["failed_keys"] == []

    @pytest.mark.asyncio
    async def test_ratio_ignores_legacy_but_keeps_tracked_ones(self, monkeypatch) -> None:
        """回归：线上真实形态（大量 legacy + 少量 filled/not_triggered）。

        修正前算出 0.5%（把 legacy 算进分母）；修正后应为 filled / 可判定行。
        这个用例直接对应 2026-10-17 线上实测的数据形态。
        """
        rows = (
            [{"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "legacy"}] * 94
            + [{"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "filled"}] * 3
            + [{"hit": None, "source": "llm", "excess_return": None, "execution_status": "not_triggered"}]
        )
        reco = (await _stats(monkeypatch, rows))["recommendation"]
        item = _by_key(reco["four_questions"])["tradable"]

        # 3 filled / 4 可判定行 = 75%（不是 3/98 = 3.1%）
        assert item["answered"] is True
        assert "75.0%" in item["value"]
        assert item["passed"] is True
        assert reco["legacy_without_execution_tracking"] == 94
        assert reco["execution_tracked_ratio"] == 4.1  # 4 可判定 / 98 到期

    @pytest.mark.asyncio
    async def test_legacy_rows_are_excluded_from_the_denominator(self, monkeypatch) -> None:
        """`legacy` 是「没有执行追踪」，不是「没成交」—— 绝不能算进分母。

        2026-10-17 上线后第一次跑真实线上数据才暴露的 bug：
        线上 48 条推荐里绝大多数是 v13 迁移前的历史行（execution_status='legacy'）。
        把它们算进分母算出「可成交 0.5%」，读起来像「97% 的推荐买不进」，
        实际上只是**压根没有执行数据**。把「不知道」当成「买不进」是最坏的一类误导。
        """
        stats = await _stats(monkeypatch, [
            {"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "legacy"},
            {"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "legacy"},
        ])
        reco = stats["recommendation"]
        by_key = _by_key(reco["four_questions"])

        # 无可判定行 ⇒ 整问答不上来（不是 0%，也不是「97% 买不进」）
        assert by_key["tradable"]["answered"] is False
        assert by_key["tradable"]["passed"] is None
        assert reco["legacy_without_execution_tracking"] == 2
        assert reco["execution_tracked_ratio"] == 0.0

    @pytest.mark.asyncio
    async def test_legacy_rows_do_not_inflate_the_failure(self, monkeypatch) -> None:
        """legacy 占比高时，四问的 detail 要说明「样本基础薄」，而不是报假警报。

        注意这 41 条里只有 1 条可判定 —— 可成交比例算出来是 100%（1/1），
        **看起来完美，实际是 1 个样本**。所以真正该被看见的是覆盖率（2.4%）
        与 detail 里的说明，而不是那个 100%。这正是「n 与覆盖率要一起看」的例子。
        """
        rows = (
            [{"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "legacy"}] * 40
            + [{"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "filled"}]
        )
        reco = (await _stats(monkeypatch, rows))["recommendation"]
        item = _by_key(reco["four_questions"])["tradable"]

        assert item["answered"] is True
        assert "100.0%" in item["value"]
        detail = item["detail"]
        assert "40 条迁移前历史行" in detail
        assert "不等于没成交" in detail
        # 执行追踪覆盖率如实下发：1/41
        assert reco["execution_tracked_ratio"] == 2.4


class TestDistributionGuard:
    @pytest.mark.asyncio
    async def test_median_uses_excess_not_next_return(self, monkeypatch) -> None:
        """中位数必须由 excess_return 算出，且与均值一起下发。"""
        stats = await _stats(monkeypatch, [
            {"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "filled"},
            {"hit": True, "source": "llm", "excess_return": 1.2, "execution_status": "filled"},
            {"hit": True, "source": "llm", "excess_return": 1.1, "execution_status": "filled"},
        ])
        by_key = _by_key(stats["recommendation"]["four_questions"])

        assert by_key["median"]["answered"] is True
        assert by_key["median"]["passed"] is True
        assert "中位 1.1" in by_key["median"]["value"]

    @pytest.mark.asyncio
    async def test_outlier_inflates_mean_and_trips_the_guard(self, monkeypatch) -> None:
        """一个 +40% 的极端样本把均值拉走，中位数纹丝不动 —— 守卫必须报警。"""
        stats = await _stats(monkeypatch, [
            {"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "filled"},
            {"hit": True, "source": "llm", "excess_return": 1.1, "execution_status": "filled"},
            {"hit": True, "source": "llm", "excess_return": 1.2, "execution_status": "filled"},
            {"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "filled"},
            {"hit": True, "source": "llm", "excess_return": 40.0, "execution_status": "filled"},
        ])
        reco = stats["recommendation"]
        by_key = _by_key(reco["four_questions"])

        # 均值被拉到 8.86，中位数仍是 1.1 —— 这正是「均值不可单独引用」的现实例子
        assert reco["avg_excess_return"] == 8.86
        assert by_key["median"]["passed"] is False
        assert reco["four_questions"]["verdict"] == "inflated"
        assert "median" in reco["four_questions"]["failed_keys"]

    @pytest.mark.asyncio
    async def test_tail_driven_distribution_trips_the_guard(self, monkeypatch) -> None:
        """过半跑输 + 少数大赢家把均值拉正 —— 这必须判失真，不能判「未偏斜」。

        线上实测形态（n=48：中位 −0.43%、均值 +0.41%）。两条旧判据
        （绝对差 0.84 / 相对倍数 0.95）都够不到阈值，于是「低胜率」被读成「分布健康」。
        """
        rows = [
            {"hit": False, "source": "llm", "excess_return": -0.5, "execution_status": "filled"}
            for _ in range(39)
        ] + [
            {"hit": True, "source": "llm", "excess_return": 35.9, "execution_status": "filled"}
        ]
        stats = await _stats(monkeypatch, rows)
        reco = stats["recommendation"]
        by_key = _by_key(reco["four_questions"])

        # 中位 −0.5、均值 +0.41：符号相反
        assert by_key["median"]["passed"] is False
        assert "符号相反" in by_key["median"]["detail"]

    @pytest.mark.asyncio
    async def test_no_excess_rows_leaves_distribution_unanswered(self, monkeypatch) -> None:
        """没有 excess_return（v14 未跑）⇒ 分布这一问答不上来，不能折算成 0%。"""
        stats = await _stats(monkeypatch, [
            {"hit": True, "source": "llm", "excess_return": None, "execution_status": "filled"},
        ])
        reco = stats["recommendation"]
        by_key = _by_key(reco["four_questions"])

        assert reco["benchmark_available"] is False
        assert by_key["median"]["answered"] is False
        assert by_key["median"]["passed"] is None


class TestBenchmarkSignHonesty:
    @pytest.mark.asyncio
    async def test_sign_flip_is_reported_as_unanswered_not_passed(self, monkeypatch) -> None:
        """推荐链路只有沪深300 一条基准，做不了符号翻转检验 ⇒ 必须 unknown。

        这是本文件最重要的一条：把它硬填成 False 会让四问「全绿」，
        而实际上这个口径根本没被检验过 —— 守卫就成了橡皮章。

        样本给到 120 条：否则 n 过小会先触发 sample 失真（verdict 变 inflated），
        掩盖掉「符号翻转答不上来」这个真正的结论。
        """
        stats = await _stats(monkeypatch, [
            {"hit": True, "source": "llm", "excess_return": 2.0, "execution_status": "filled"}
            for _ in range(120)
        ])
        reco = stats["recommendation"]
        four = reco["four_questions"]
        by_key = _by_key(four)

        assert by_key["benchmark_sign"]["answered"] is False
        assert by_key["benchmark_sign"]["passed"] is None
        assert "benchmark_sign" in four["unanswered_keys"]
        # 其余三问都干净 ⇒ 仍是 unknown，不是 credible
        assert four["verdict"] == "unknown"

    @pytest.mark.asyncio
    async def test_verdict_never_reaches_credible_on_this_caliber(self, monkeypatch) -> None:
        """只要符号翻转没做，verdict 就不可能是 credible —— 锁死「不虚报合格」。"""
        stats = await _stats(monkeypatch, [
            {"hit": True, "source": "llm", "excess_return": 1.0, "execution_status": "filled"}
            for _ in range(120)
        ])
        four = stats["recommendation"]["four_questions"]

        assert four["verdict"] != "credible"
        assert four["answered_count"] == 3
        assert four["total_questions"] == 4


class TestBothBlocksCarryTheGuard:
    @pytest.mark.asyncio
    async def test_prediction_block_also_carries_four_questions(self, monkeypatch) -> None:
        """大盘命中率同样要过闸：它的口径声明「无基准」，所以该问天然答不上来。"""
        monkeypatch.setattr(wr.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(wr.supabase_store, "get_service_client", _fake_client({
            "prediction_records": [
                {"direction": "上涨", "hit": True},
                {"direction": "下跌", "hit": True},
            ],
            "daily_recommendations": [],
            "winrate_snapshot": [],
        }))
        stats = await wr.get_winrate_stats()
        four = stats["prediction"]["four_questions"]

        assert four["total_questions"] == 4
        assert _by_key(four)["sample"]["passed"] is False  # n=2
        assert _by_key(four)["benchmark_sign"]["answered"] is False

    @pytest.mark.asyncio
    async def test_unconfigured_payload_omits_blocks_but_keeps_note(self, monkeypatch) -> None:
        """未配置 Supabase 时两个块都是 None —— 前端据此走空态，不许读到半个四问。"""
        monkeypatch.setattr(wr.supabase_store, "is_configured", lambda: False)

        stats = await wr.get_winrate_stats()

        assert stats["prediction"] is None
        assert stats["recommendation"] is None
