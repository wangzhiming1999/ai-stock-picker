"""连板梯队服务的回归测试。

重点覆盖四类容易错的地方：

1. **单位换算** —— 东财价格字段是「厘」（37000 = 37.00 元），封板时间是 HHMMSS 整数，
   市值/封单是「元」。这三处任何一个漏换算，界面上就是 1000 倍或 10 倍的错值。
2. **聚合口径** —— 梯队分桶、板块排序、炸板率分母。炸板率若用「当日涨停家数」作分母，
   盘中炸板多时该比值会突破 100%。
3. **晋级率统计** —— 晋级判定是「次日 lbc 恰好 +1」；也要验证控制高度后的分层交叉表
   确实按 (高度, 聚集度) 切分，而不是退回边缘分布。
4. **证据闸门** —— limitup_relay 必须**不可执行**。这是本模块最容易越界的地方：
   晋级率看着像胜率，一旦被标成 actionable，前端就会把它渲染成买点。
"""
import unittest

from app.services import calibers, limitup_service as L, tactic_evidence as E


class FormatTests(unittest.TestCase):
    def test_seal_time_pads_to_six_digits(self) -> None:
        # 92500 是 09:25:00，不是 92:50:0 —— 必须补零到 6 位再切分。
        self.assertEqual(L._fmt_time(92500), "09:25:00")
        self.assertEqual(L._fmt_time(95939), "09:59:39")
        self.assertEqual(L._fmt_time(142530), "14:25:30")

    def test_seal_time_missing_values(self) -> None:
        for raw in (0, None, "", "-", "abc"):
            self.assertEqual(L._fmt_time(raw), "")

    def test_num_tolerates_eastmoney_placeholders(self) -> None:
        self.assertEqual(L._num(None), 0.0)
        self.assertEqual(L._num("-"), 0.0)
        self.assertEqual(L._num(""), 0.0)
        self.assertEqual(L._num("1.5"), 1.5)
        self.assertEqual(L._num("abc"), 0.0)


class NormalizeTests(unittest.TestCase):
    def test_price_is_converted_from_li(self) -> None:
        # 东财 p 字段单位是「厘」，37000 → 37.00 元。
        item = {"c": "003026", "n": "中晶科技", "p": 37000, "zdp": 9.98, "lbc": 3}
        row = L.normalize_limit_up(item)
        self.assertEqual(row["price"], 37.0)
        self.assertEqual(row["code"], "003026")
        self.assertEqual(row["boards"], 3)

    def test_money_fields_converted_to_yi(self) -> None:
        item = {
            "c": "003026",
            "n": "中晶科技",
            "p": 37000,
            "fund": 214_714_034,
            "ltsz": 5_333_952_560,
            "amount": 552_239_792,
        }
        row = L.normalize_limit_up(item)
        self.assertAlmostEqual(row["seal_fund_yi"], 2.147, places=3)
        self.assertAlmostEqual(row["float_mv_yi"], 53.34, places=2)
        self.assertAlmostEqual(row["amount_yi"], 5.522, places=3)

    def test_seal_ratio_zero_float_mv_guarded(self) -> None:
        """流通市值为 0 时不能除零，也不能把封单比算成 inf。"""
        row = L.normalize_limit_up({"c": "1", "n": "X", "p": 1000, "fund": 100, "ltsz": 0})
        self.assertEqual(row["seal_ratio"], 0.0)

    def test_seal_ratio_is_percentage_of_float_mv(self) -> None:
        row = L.normalize_limit_up({"c": "1", "n": "X", "p": 1000, "fund": 100_000_000, "ltsz": 1_000_000_000})
        self.assertAlmostEqual(row["seal_ratio"], 10.0, places=3)

    def test_sector_falls_back_to_other(self) -> None:
        row = L.normalize_limit_up({"c": "1", "n": "X", "p": 1000, "hybk": ""})
        self.assertEqual(row["sector"], "其他")

    def test_zttj_expanded_to_days_and_boards(self) -> None:
        row = L.normalize_limit_up({"c": "1", "n": "X", "p": 1000, "zttj": {"days": 5, "ct": 3}})
        self.assertEqual(row["stat_days"], 5)
        self.assertEqual(row["stat_boards"], 3)

    def test_broken_pool_has_no_boards_field(self) -> None:
        """炸板池没有 lbc，不能因此抛异常或硬塞一个假的连板数。"""
        row = L.normalize_broken({"c": "603139", "n": "康惠股份", "p": 38970, "ztp": 44320, "zbc": 1})
        self.assertEqual(row["code"], "603139")
        self.assertEqual(row["limit_price"], 44.32)
        self.assertNotIn("boards", row)


class LadderTests(unittest.TestCase):
    def _item(self, boards: int, seal_time: str = "09:30:00") -> dict:
        return {"boards": boards, "seal_time": seal_time, "code": f"{boards}", "name": "x"}

    def test_label_buckets(self) -> None:
        self.assertEqual(L.ladder_label(0), "首板")
        self.assertEqual(L.ladder_label(1), "首板")
        self.assertEqual(L.ladder_label(2), "2板")
        self.assertEqual(L.ladder_label(6), "6板+")
        # 7 板及以上合并进同一桶，避免长尾每档只有 1 只稀释统计
        self.assertEqual(L.ladder_label(9), "6板+")

    def test_groups_sorted_high_to_low(self) -> None:
        items = [self._item(1), self._item(3), self._item(2), self._item(1)]
        ladder = L.build_ladder(items)
        self.assertEqual([g["label"] for g in ladder], ["3板", "2板", "首板"])
        self.assertEqual([g["count"] for g in ladder], [1, 1, 2])

    def test_within_group_sorted_by_seal_time(self) -> None:
        """组内按首封时间升序 —— 越早封板越靠前，这是短线看强度的第一眼。"""
        items = [self._item(2, "10:30:00"), self._item(2, "09:31:00"), self._item(2, "09:25:00")]
        ladder = L.build_ladder(items)
        self.assertEqual([t["seal_time"] for t in ladder[0]["items"]], ["09:25:00", "09:31:00", "10:30:00"])

    def test_empty_input(self) -> None:
        self.assertEqual(L.build_ladder([]), [])


class SectorTests(unittest.TestCase):
    def _item(self, sector: str, boards: int, fund: float = 0.0) -> dict:
        return {"sector": sector, "boards": boards, "seal_fund_yi": fund, "turnover": 5.0, "code": "x", "name": "x"}

    def test_aggregates_count_and_max_boards(self) -> None:
        items = [
            self._item("半导体", 3, 2.0),
            self._item("半导体", 1, 1.0),
            self._item("医药", 2, 0.5),
        ]
        sectors = L.build_sectors(items)
        semi = next(s for s in sectors if s["sector"] == "半导体")
        self.assertEqual(semi["count"], 2)
        self.assertEqual(semi["relay_count"], 1)  # 只有 3 板那只算连板
        self.assertEqual(semi["max_boards"], 3)
        self.assertAlmostEqual(semi["seal_fund_yi"], 3.0, places=2)

    def test_sorted_by_count_first(self) -> None:
        """家数优先于封单金额 —— 抱团程度比单笔封单更能说明资金去向。"""
        items = [
            self._item("A", 1, 99.0),
            self._item("B", 1, 0.1),
            self._item("B", 1, 0.1),
        ]
        self.assertEqual([s["sector"] for s in L.build_sectors(items)][0], "B")

    def test_limit_applied(self) -> None:
        items = [self._item(f"S{i}", 1) for i in range(20)]
        self.assertEqual(len(L.build_sectors(items, limit=5)), 5)


class SentimentTests(unittest.TestCase):
    def _up(self, boards: int, breaks: int = 0) -> dict:
        return {"boards": boards, "break_count": breaks}

    def test_break_rate_denominator_includes_broken(self) -> None:
        """分母必须是「曾涨停家数」= 涨停 + 炸板，否则盘中炸板多时会超过 100%。"""
        s = L.build_sentiment([self._up(1)] * 3, [{}] * 7)
        self.assertEqual(s["limit_up_count"], 3)
        self.assertEqual(s["broken_count"], 7)
        self.assertEqual(s["break_rate"], 70.0)

    def test_break_rate_guarded_when_empty(self) -> None:
        s = L.build_sentiment([], [])
        self.assertEqual(s["break_rate"], 0.0)
        self.assertEqual(s["max_boards"], 0)

    def test_relay_and_first_board_split(self) -> None:
        items = [self._up(1), self._up(1), self._up(2), self._up(5)]
        s = L.build_sentiment(items, [])
        self.assertEqual(s["relay_count"], 2)
        self.assertEqual(s["first_board_count"], 2)
        self.assertEqual(s["max_boards"], 5)

    def test_intact_count_only_counts_never_broken(self) -> None:
        items = [self._up(2, 0), self._up(2, 1), self._up(3, 0)]
        self.assertEqual(L.build_sentiment(items, [])["intact_count"], 2)

    def test_note_tones(self) -> None:
        self.assertEqual(L.sentiment_note({"break_rate": 50.0, "max_boards": 3})["tone"], "warn")
        self.assertEqual(L.sentiment_note({"break_rate": 10.0, "max_boards": 5})["tone"], "good")
        self.assertEqual(L.sentiment_note({"break_rate": 25.0, "max_boards": 3})["tone"], "neutral")


class PositionTagTests(unittest.TestCase):
    def _pos(self, boards: int, breaks: int = 0) -> str:
        return L.position_tag({"boards": boards, "break_count": breaks})["tag"]

    def test_buckets(self) -> None:
        self.assertEqual(self._pos(1), "启动")
        self.assertEqual(self._pos(2), "加速")
        self.assertEqual(self._pos(3), "加速")
        self.assertEqual(self._pos(4), "中继")
        self.assertEqual(self._pos(5), "高位")

    def test_high_board_wins_over_divergence(self) -> None:
        """5 板以上即使反复开板也先报「高位」—— 位置风险优先于分歧描述。"""
        self.assertEqual(self._pos(5, breaks=9), "高位")

    def test_divergence_detected_at_three_breaks(self) -> None:
        self.assertEqual(self._pos(3, breaks=3), "分歧")
        self.assertEqual(self._pos(3, breaks=2), "加速")

    def test_tag_contains_no_action_words(self) -> None:
        """位置标签是分桶描述，不能出现任何动作词 —— 闸门未通过前不允许出现买入暗示。"""
        banned = ("买", "建仓", "加仓", "建议", "推荐", "介入")
        for boards in range(1, 9):
            for breaks in (0, 3):
                pos = L.position_tag({"boards": boards, "break_count": breaks})
                text = pos["tag"] + pos["reason"]
                for word in banned:
                    self.assertNotIn(word, text, f"位置标签出现动作词 {word!r}: {text}")


class RelayStatsTests(unittest.TestCase):
    """晋级率统计：用构造数据把口径钉死。"""

    def _mk(self, code: str, boards: int, sector: str = "S") -> dict:
        return {"code": code, "boards": boards, "sector": sector}

    def test_promotion_requires_exact_plus_one(self) -> None:
        """次日 lbc 必须恰好 +1。跳到 +2 或原地不动都不算晋级。"""
        import datetime as dt

        d1, d2 = dt.date(2026, 1, 1), dt.date(2026, 1, 2)
        per_day = {
            d1.isoformat(): [self._mk("A", 1), self._mk("B", 1), self._mk("C", 2)],
            # A 正常晋级；B 停在 1 板；C 直接跳到 4 板（非 +1）
            d2.isoformat(): [self._mk("A", 2), self._mk("B", 1), self._mk("C", 4)],
        }
        st = L._relay_stats([d1, d2], per_day)
        self.assertEqual(st["total_samples"], 3)
        self.assertEqual(st["overall_rate"], 33.3)
        by = {b["key"]: b for b in st["by_boards"]}
        self.assertEqual(by[1]["promoted"], 1)
        self.assertEqual(by[1]["total"], 2)
        self.assertEqual(by[2]["promoted"], 0)

    def test_missing_day_is_skipped_not_counted_as_zero(self) -> None:
        """无数据的日期不能算进分母 —— 否则「接口不提供」会被误读成「全都没晋级」。"""
        import datetime as dt

        d1, d2, d3 = dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 3)
        per_day = {
            d1.isoformat(): [self._mk("A", 1)],
            # d2 缺失
            d3.isoformat(): [self._mk("A", 1)],
        }
        st = L._relay_stats([d1, d2, d3], per_day)
        self.assertEqual(st["sessions"], 0)
        self.assertEqual(st["total_samples"], 0)
        self.assertEqual(st["overall_rate"], 0.0)

    def test_cluster_cross_table_splits_by_boards(self) -> None:
        """分层表必须按 (高度, 聚集度) 切分，而不是退回边缘分布。"""
        import datetime as dt

        d1, d2 = dt.date(2026, 1, 1), dt.date(2026, 1, 2)
        # 当日 S 板块 5 只涨停（≥5家），其中 4 只首板 + 1 只 2 板
        cur = [self._mk(f"S{i}", 1, "S") for i in range(4)] + [self._mk("S9", 2, "S")]
        nxt = [self._mk("S0", 2, "S"), self._mk("S9", 3, "S")]
        st = L._relay_stats([d1, d2], {d1.isoformat(): cur, d2.isoformat(): nxt})

        self.assertEqual(len(st["by_boards_cluster"]), 2)  # 首板 + 2板 两行
        first = next(r for r in st["by_boards_cluster"] if r["boards"] == 1)
        self.assertEqual(first["clusters"][0]["cluster"], "≥5家")
        self.assertEqual(first["clusters"][0]["total"], 4)
        self.assertEqual(first["clusters"][0]["promoted"], 1)

    def test_cluster_bucket_thresholds(self) -> None:
        self.assertEqual(L._cluster_bucket(5), "≥5家")
        self.assertEqual(L._cluster_bucket(4), "3-4家")
        self.assertEqual(L._cluster_bucket(3), "3-4家")
        self.assertEqual(L._cluster_bucket(2), "1-2家")
        self.assertEqual(L._cluster_bucket(1), "1-2家")

    def test_zero_board_rows_ignored(self) -> None:
        """lbc 缺失（0 板）的记录不参与统计，避免污染首板桶。"""
        import datetime as dt

        d1, d2 = dt.date(2026, 1, 1), dt.date(2026, 1, 2)
        st = L._relay_stats([d1, d2], {d1.isoformat(): [self._mk("A", 0)], d2.isoformat(): [self._mk("A", 1)]})
        self.assertEqual(st["total_samples"], 0)


class EvidenceGateTests(unittest.TestCase):
    """本模块最容易越界的地方：晋级率像胜率，但绝不能变成可执行信号。"""

    def test_limitup_relay_registered(self) -> None:
        self.assertEqual(E.tier_of("limitup_relay"), "preliminary")

    def test_limitup_relay_is_not_actionable(self) -> None:
        self.assertFalse(E.is_actionable("limitup_relay"))
        self.assertFalse(E.describe("limitup_relay")["actionable"])

    def test_limitup_relay_is_not_escalatable(self) -> None:
        """也不允许把「持有观察」升级成「减仓建议」。"""
        self.assertFalse(E.is_escalatable("limitup_relay"))

    def test_gate_note_has_no_action_words(self) -> None:
        note = E.gate_note("limitup_relay")
        for word in ("买入", "可分批建仓", "建议买"):
            self.assertNotIn(word, note)

    def test_no_tactic_is_actionable(self) -> None:
        """全仓位的守门断言：目前一条都不许可执行。"""
        self.assertEqual(E.survey()["actionable"], 0)

    def test_caliber_registered(self) -> None:
        """没有登记口径的百分比不允许出现在界面上，晋级率必须已登记。"""
        cal = calibers.describe("limitup_relay")
        self.assertTrue(cal["registered"])
        self.assertIn("limitup_relay", calibers.all_keys())

    def test_caliber_states_it_is_not_a_return_metric(self) -> None:
        """口径的 pitfall 必须点明「不是收益率」，防止被当成胜率解读。"""
        pitfall = calibers.describe("limitup_relay")["pitfall"]
        self.assertIn("不是收益率", pitfall)


class ResponseContractTests(unittest.TestCase):
    """接口字段契约。

    这些字段名是前端直接解构的，改一次就会静默炸掉一个面板 —— 曾经的真实 bug：
    `ladder[].items[]` 只在 `stocks[]` 上挂了 `position`，前端渲染梯队时读到 undefined。
    """

    def test_every_stock_slot_carries_position(self) -> None:
        """ladder / stocks 两处个股都必须带 position（三处共用同一份装饰后的数据）。"""
        items = [self._stock("600001", 3), self._stock("600002", 1)]
        decorated = [{**t, "position": L.position_tag(t)} for t in items]

        ladder = L.build_ladder(decorated)
        flat = [t for g in ladder for t in g["items"]]

        self.assertEqual(len(flat), 2)
        for t in flat:
            self.assertIn("position", t)
            self.assertIn("tag", t["position"])
            self.assertIn("reason", t["position"])

    def test_stratum_uses_boards_not_key(self) -> None:
        """分层交叉表的档位字段名是 `boards`（高度分桶表用的是 `key`），两者不一致是刻意的。"""
        import datetime as dt

        d1, d2 = dt.date(2026, 1, 1), dt.date(2026, 1, 2)
        cur = [self._stock("600001", 2), self._stock("600002", 1)]
        nxt = [self._stock("600001", 3), self._stock("600003", 1)]
        st = L._relay_stats([d1, d2], {d1.isoformat(): cur, d2.isoformat(): nxt})

        for row in st["by_boards_cluster"]:
            self.assertIn("boards", row)
            self.assertIn("clusters", row)
            for cell in row["clusters"]:
                self.assertIn("boards", cell)
                self.assertIn("cluster", cell)

    @staticmethod
    def _stock(code: str, boards: int) -> dict:
        return {
            "code": code,
            "name": f"票{code[-2:]}",
            "boards": boards,
            "sector": "测试板块",
            "seal_time": "09:31:00",
            "break_count": 0,
            "seal_fund_yi": 1.0,
            "float_mv_yi": 50.0,
            "turnover": 5.0,
        }


class PlayAdviceTests(unittest.TestCase):
    """三档操作建议：判定顺序 = 否决项（炸板率/断层/主线）→ 放宽档位。"""

    @staticmethod
    def _sentiment(rate: float, max_boards: int = 5, relay: int = 9, limit_up: int = 47) -> dict:
        return {"break_rate": rate, "max_boards": max_boards, "relay_count": relay, "limit_up_count": limit_up}

    @staticmethod
    def _ladder(*levels: tuple[int, int]) -> list[dict]:
        return [{"key": k, "count": c, "label": "", "items": []} for k, c in levels]

    def test_no_limit_up_at_all_means_avoid(self) -> None:
        adv = L.play_advice(self._sentiment(0, 0, relay=0, limit_up=0), [], [])
        self.assertEqual(adv["level"], "avoid")
        self.assertIn("没有涨停", adv["reasons"][0])

    def test_high_break_rate_blocks(self) -> None:
        ladder = self._ladder((5, 1), (4, 2), (3, 3), (2, 4), (1, 20))
        adv = L.play_advice(self._sentiment(36.0), ladder, [{"sector": "半导体", "count": 5}])
        self.assertEqual(adv["level"], "avoid")
        self.assertTrue(any("炸板率" in r for r in adv["reasons"]))

    def test_ladder_gap_blocks(self) -> None:
        # 5 板孤岛：2/3/4 板全空
        ladder = self._ladder((5, 1), (1, 38))
        adv = L.play_advice(self._sentiment(20.0), ladder, [{"sector": "半导体", "count": 5}])
        self.assertEqual(adv["level"], "avoid")
        self.assertTrue(any("断层" in r for r in adv["reasons"]))
        self.assertEqual(adv["gaps"], [2, 3, 4])

    def test_no_mainline_blocks(self) -> None:
        ladder = self._ladder((5, 1), (4, 2), (3, 3), (2, 4), (1, 20))
        adv = L.play_advice(self._sentiment(20.0), ladder, [{"sector": "汽车零部", "count": 3}])
        self.assertEqual(adv["level"], "avoid")
        self.assertTrue(any("无合力" in r for r in adv["reasons"]))

    def test_healthy_environment_unlocks_hunt(self) -> None:
        ladder = self._ladder((5, 1), (4, 2), (3, 3), (2, 4), (1, 20))
        adv = L.play_advice(self._sentiment(15.0), ladder, [{"sector": "半导体", "count": 5}])
        self.assertEqual(adv["level"], "hunt")
        self.assertEqual(adv["title"], "可打板")
        # 三条理由必须把关键事实都带上
        joined = " ".join(adv["reasons"])
        self.assertIn("15.0%", joined)
        self.assertIn("半导体", joined)

    def test_mid_break_rate_lands_watch_even_if_structure_ok(self) -> None:
        ladder = self._ladder((5, 1), (4, 2), (3, 3), (2, 4), (1, 20))
        adv = L.play_advice(self._sentiment(28.0), ladder, [{"sector": "半导体", "count": 5}])
        self.assertEqual(adv["level"], "watch")

    def test_first_board_only_lands_watch(self) -> None:
        # 没有断层（纯首板不算断层）、板块聚集度够，但鱼腹尚未形成 → watch 而不是 avoid
        ladder = self._ladder((1, 38))
        adv = L.play_advice(self._sentiment(20.0, max_boards=1, relay=0), ladder, [{"sector": "半导体", "count": 5}])
        self.assertEqual(adv["level"], "watch")
        self.assertTrue(any("首板" in r for r in adv["reasons"]))

    def test_ladder_gaps_ignores_first_board_only(self) -> None:
        self.assertEqual(L.ladder_gaps([]), [])
        self.assertEqual(L.ladder_gaps([{"key": 1, "count": 5}]), [])

    def test_ladder_gaps_finds_missing_levels(self) -> None:
        # build_ladder 只输出非空组，缺失档位要补出来
        ladder = [{"key": 5, "count": 1}, {"key": 3, "count": 1}, {"key": 1, "count": 10}]
        self.assertEqual(L.ladder_gaps(ladder), [2, 4])

    def test_advice_never_recommends_a_specific_stock(self) -> None:
        """证据纪律：建议只能讲环境，不能出现任何个股代码/名称/买入动作指向。"""
        ladder = self._ladder((5, 1), (4, 2), (3, 3), (2, 4), (1, 20))
        adv = L.play_advice(self._sentiment(15.0), ladder, [{"sector": "半导体", "count": 5}])
        blob = adv["title"] + " ".join(adv["reasons"])
        self.assertNotIn("买入", blob)
        self.assertNotIn("加仓", blob)
        # 理由里只允许出现板块名，不允许出现个股（sectors 里的 names 字段不含在此接口）
        self.assertNotIn("票", blob.replace("打板", ""))  # 排除"打板"词本身的误伤


if __name__ == "__main__":
    unittest.main()
