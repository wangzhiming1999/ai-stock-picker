"""跌停池与「次日修复」服务的回归测试。

重点覆盖四类容易错的地方：

1. **字段错位与单位换算** —— 跌停池的封单金额在 ``fba``（不是涨停池的 ``fund``），
   连续跌停天数在 ``days``（不是 ``lbc``），价格单位仍是「厘」。字段用错**不会报错**，
   只会静默给出差三个数量级的错值 —— 这类错误在界面上看起来完全正常。
2. **聚合口径** —— 连跌分桶、板块排序，以及「跌停/涨停比」在涨停数缺失时必须给 None：
   0 和「算不出来」是两件事，混同会让前端把数据缺失渲染成「抛压为零」。
3. **收益统计** —— 打平胜率的计算，以及 ``ret_close=None``（D+1 为进行中交易日）
   不能被当成 0 参与统计（那会把均值拉低、把胜率造假）。
4. **证据闸门** —— limitdown_repair 必须**不可执行**且等级为 ``unsupported``。
   这是本模块最容易越界的地方：收益口径算出来是**负的**，一旦被标成 actionable，
   前端就会把一个负期望策略渲染成抄底信号 —— 那是把 UI 变成亏损按钮。
"""
import unittest

from app.services import calibers, limitdown_service as L, tactic_evidence as E


class FormatTests(unittest.TestCase):
    def test_last_seal_time_pads_to_six_digits(self) -> None:
        # 145600 是 14:56:00，不是 14:56:0 也不是 1456:00 —— 必须补零到 6 位再切分。
        self.assertEqual(L._fmt_time(145600), "14:56:00")
        self.assertEqual(L._fmt_time(92500), "09:25:00")
        self.assertEqual(L._fmt_time(100000), "10:00:00")

    def test_time_missing_values(self) -> None:
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
        # 东财 p 字段单位是「厘」，7860 → 7.86 元。
        row = L.normalize_limit_down({"c": "002163", "n": "海南发展", "p": 7860, "zdp": -9.97})
        self.assertEqual(row["price"], 7.86)
        self.assertEqual(row["code"], "002163")
        self.assertAlmostEqual(row["change_pct"], -9.97, places=2)

    def test_seal_fund_reads_fba_not_fund(self) -> None:
        """跌停池的封单金额在 fba；fund 是小额噪声字段，用错会差三个数量级。

        实测样本：同一只票 fund=461382（约 46 万）vs fba=164236761（约 1.64 亿）。
        """
        row = L.normalize_limit_down(
            {"c": "1", "n": "X", "p": 1000, "fba": 164_236_761, "fund": 461_382}
        )
        self.assertAlmostEqual(row["seal_fund_yi"], 1.642, places=3)

    def test_down_days_reads_days_not_lbc(self) -> None:
        """跌停池没有 lbc（那是涨停池的连板数）；即使上游误塞也不能拿它当连跌天数。"""
        row = L.normalize_limit_down({"c": "1", "n": "X", "days": 3, "lbc": 9})
        self.assertEqual(row["down_days"], 3)

    def test_down_days_defaults_to_one(self) -> None:
        """days 缺失或为 0 时按「首日跌停」处理，不能变成 0 连跌。"""
        self.assertEqual(L.normalize_limit_down({"c": "1", "n": "X"})["down_days"], 1)
        self.assertEqual(L.normalize_limit_down({"c": "1", "n": "X", "days": 0})["down_days"], 1)

    def test_money_fields_converted_to_yi(self) -> None:
        row = L.normalize_limit_down(
            {"c": "1", "n": "X", "p": 1000, "fba": 214_714_034, "ltsz": 5_333_952_560, "amount": 552_239_792}
        )
        self.assertAlmostEqual(row["seal_fund_yi"], 2.147, places=3)
        self.assertAlmostEqual(row["float_mv_yi"], 53.34, places=2)
        self.assertAlmostEqual(row["amount_yi"], 5.522, places=3)

    def test_seal_ratio_guards_zero_float_mv(self) -> None:
        row = L.normalize_limit_down({"c": "1", "n": "X", "p": 1000, "fba": 100, "ltsz": 0})
        self.assertEqual(row["seal_ratio"], 0.0)

    def test_seal_ratio_is_percentage(self) -> None:
        row = L.normalize_limit_down(
            {"c": "1", "n": "X", "p": 1000, "fba": 100_000_000, "ltsz": 1_000_000_000}
        )
        self.assertAlmostEqual(row["seal_ratio"], 10.0, places=3)

    def test_sector_falls_back_to_other(self) -> None:
        self.assertEqual(L.normalize_limit_down({"c": "1", "n": "X", "hybk": ""})["sector"], "其他")


class LadderTests(unittest.TestCase):
    def _item(self, days: int, fund: float = 0.0) -> dict:
        return {"down_days": days, "seal_fund_yi": fund, "code": "x", "name": "x"}

    def test_label_buckets(self) -> None:
        self.assertEqual(L.ladder_label(1), "首日跌停")
        self.assertEqual(L.ladder_label(2), "2连跌")
        self.assertEqual(L.ladder_label(3), "3连跌")
        # 4 及以上合并进同一桶，避免长尾每档只有 1 只稀释统计
        self.assertEqual(L.ladder_label(4), "4连跌+")
        self.assertEqual(L.ladder_label(9), "4连跌+")

    def test_groups_sorted_high_to_low(self) -> None:
        ladder = L.build_ladder([self._item(1), self._item(3), self._item(1)])
        self.assertEqual([g["label"] for g in ladder], ["3连跌", "首日跌停"])
        self.assertEqual([g["count"] for g in ladder], [1, 2])

    def test_within_group_sorted_by_seal_fund_desc(self) -> None:
        """组内按封单金额降序 —— 封得越死排越前，这是看抛压厚度的第一眼。"""
        ladder = L.build_ladder([self._item(2, 1.0), self._item(2, 5.0), self._item(2, 3.0)])
        self.assertEqual([t["seal_fund_yi"] for t in ladder[0]["items"]], [5.0, 3.0, 1.0])

    def test_empty_input(self) -> None:
        self.assertEqual(L.build_ladder([]), [])


class SectorTests(unittest.TestCase):
    def _item(self, sector: str, days: int = 1, fund: float = 0.0, turnover: float = 5.0) -> dict:
        return {
            "sector": sector,
            "down_days": days,
            "seal_fund_yi": fund,
            "turnover": turnover,
            "code": "x",
            "name": "x",
        }

    def test_aggregates_count_chain_and_max_days(self) -> None:
        items = [
            self._item("A"),
            self._item("A"),
            self._item("A", days=2),
            self._item("B"),
            self._item("B", days=3),
        ]
        sectors = L.build_sectors(items)
        self.assertEqual(sectors[0]["sector"], "A")
        self.assertEqual(sectors[0]["count"], 3)
        self.assertEqual(sectors[0]["max_down_days"], 2)
        self.assertEqual(sectors[0]["chain_count"], 1)
        self.assertEqual(sectors[1]["sector"], "B")

    def test_limit_applied(self) -> None:
        items = [self._item(f"S{i}") for i in range(12)]
        self.assertEqual(len(L.build_sectors(items, limit=8)), 8)

    def test_empty_input(self) -> None:
        self.assertEqual(L.build_sectors([]), [])


class SentimentTests(unittest.TestCase):
    def _item(self, sector: str = "A", days: int = 1) -> dict:
        return {"sector": sector, "down_days": days}

    def test_counts_chain_and_top_sector(self) -> None:
        # 涨停数取 50 是为了让比值落在可精确表示的数上：3/40 的浮点值是 0.074999…，
        # round(…, 2) 会得 0.07，用它断言会变成在测浮点表示而不是在测聚合逻辑。
        s = L.build_sentiment([self._item(), self._item("B", 2), self._item("B", 3)], limit_up_count=50)
        self.assertEqual(s["limit_down_count"], 3)
        self.assertEqual(s["chain_count"], 2)
        self.assertEqual(s["max_down_days"], 3)
        self.assertEqual(s["sector_count"], 2)
        self.assertEqual(s["top_sector"], "B")
        self.assertEqual(s["top_sector_count"], 2)
        self.assertAlmostEqual(s["down_up_ratio"], 0.06, places=2)

    def test_ratio_is_none_when_limit_up_count_missing(self) -> None:
        """涨跌停比算不出来时给 None —— 0 和「缺失」是两件事，前端要能区分，
        否则数据缺失会被渲染成「抛压为零」。"""
        s = L.build_sentiment([self._item()], limit_up_count=0)
        self.assertIsNone(s["down_up_ratio"])

    def test_zero_down(self) -> None:
        s = L.build_sentiment([], limit_up_count=0)
        self.assertEqual(s["limit_down_count"], 0)
        self.assertIsNone(s["top_sector"])
        self.assertEqual(s["max_down_days"], 0)


class PositionTests(unittest.TestCase):
    def _item(self, days: int = 1, seal_ratio: float = 0.0, turnover: float = 5.0) -> dict:
        return {"down_days": days, "seal_ratio": seal_ratio, "turnover": turnover}

    def test_tags(self) -> None:
        self.assertEqual(L.position_tag(self._item(days=3))["tag"], "深跌")
        self.assertEqual(L.position_tag(self._item(days=2))["tag"], "连跌")
        self.assertEqual(L.position_tag(self._item(seal_ratio=1.5))["tag"], "封死")
        self.assertEqual(L.position_tag(self._item(turnover=12.0))["tag"], "换手")
        self.assertEqual(L.position_tag(self._item())["tag"], "首跌")

    def test_reason_has_no_action_words(self) -> None:
        """位置标签是统计分桶不是建议，理由里不能出现动作词。"""
        for days in (1, 2, 3, 5):
            reason = L.position_tag(self._item(days=days))["reason"]
            for word in ("买入", "建仓", "加仓", "建议", "推荐", "介入", "抄底"):
                self.assertNotIn(word, reason)


class ClusterTests(unittest.TestCase):
    def test_buckets(self) -> None:
        self.assertEqual(L._cluster_bucket(1), "1家")
        self.assertEqual(L._cluster_bucket(2), "2-4家")
        self.assertEqual(L._cluster_bucket(4), "2-4家")
        self.assertEqual(L._cluster_bucket(5), "≥5家")
        self.assertEqual(L._cluster_bucket(9), "≥5家")


class StatsTests(unittest.TestCase):
    """收益统计是**纯函数**，可以完全离线验证 —— 这条口径的结论（负期望）就建立在它上面。"""

    def _row(self, ret_open: float, ret_close=None, ret_high: float = 0.0, **kw) -> dict:
        return {
            "ret_open": ret_open,
            "ret_close": ret_close,
            "ret_high": ret_high,
            "next_sealed_down": kw.get("next_sealed_down", False),
            "next_limit_up": kw.get("next_limit_up", False),
        }

    def test_empty_rows(self) -> None:
        self.assertEqual(L.stats_of([]), {"n": 0})

    def test_breakeven_win_rate(self) -> None:
        """均盈 +2% / 均亏 −5% 时，打平需要 71.4% 胜率。

        这是本模块最该被看见的换算：它把「胜率看起来还行」直接翻译成「够不够」。
        60% 胜率的期望是 −0.8% —— 胜率过半照样亏。
        """
        rows = [self._row(0.02)] * 6 + [self._row(-0.05)] * 4
        st = L.stats_of(rows)
        self.assertEqual(st["n"], 10)
        self.assertAlmostEqual(st["win_rate_open"], 60.0, places=1)
        self.assertAlmostEqual(st["avg_win"], 2.0, places=2)
        self.assertAlmostEqual(st["avg_loss"], -5.0, places=2)
        self.assertAlmostEqual(st["breakeven_win_rate"], 71.4, places=1)
        self.assertAlmostEqual(st["expect_open"], -0.8, places=2)

    def test_zero_return_counted_on_loss_side(self) -> None:
        """二分类口径下「不赚」不该被算成赢，否则胜率会被 0 收益样本虚高。"""
        st = L.stats_of([self._row(0.0)] * 3)
        self.assertEqual(st["win_rate_open"], 0.0)
        self.assertEqual(st["avg_win"], 0.0)

    def test_breakeven_guards_zero_denominator(self) -> None:
        st = L.stats_of([self._row(0.0)])
        self.assertEqual(st["breakeven_win_rate"], 0.0)

    def test_close_none_excluded_not_treated_as_zero(self) -> None:
        """D+1 是进行中交易日时 ret_close 为 None，不能当 0 拉低均值。"""
        rows = [self._row(0.01, ret_close=None), self._row(0.03, ret_close=0.05)]
        st = L.stats_of(rows)
        self.assertAlmostEqual(st["expect_close"], 5.0, places=2)
        self.assertAlmostEqual(st["win_rate_close"], 100.0, places=1)

    def test_all_close_none_gives_none(self) -> None:
        st = L.stats_of([self._row(0.01, ret_close=None)])
        self.assertIsNone(st["expect_close"])
        self.assertIsNone(st["win_rate_close"])

    def test_pool_based_rates(self) -> None:
        rows = [self._row(-0.03, next_sealed_down=True), self._row(0.01, next_limit_up=True)]
        st = L.stats_of(rows)
        self.assertAlmostEqual(st["next_sealed_down_rate"], 50.0, places=1)
        self.assertAlmostEqual(st["next_limit_up_rate"], 50.0, places=1)

    def test_high_elasticity_stats(self) -> None:
        """盘中最高价口径用来回答「反抽是否存在」——它存在，但不等于能覆盖低开。"""
        rows = [self._row(-0.02, ret_high=0.01), self._row(-0.04, ret_high=-0.01)]
        st = L.stats_of(rows)
        self.assertAlmostEqual(st["avg_high"], 0.0, places=2)
        self.assertAlmostEqual(st["high_positive_rate"], 50.0, places=1)


class CaliberTests(unittest.TestCase):
    def test_registered(self) -> None:
        c = calibers.describe("limitdown_repair")
        self.assertTrue(c["registered"])
        self.assertIn("集合竞价", c["window"])

    def test_pitfall_states_negative_expectation(self) -> None:
        """口径说明必须点明这是负期望 —— 否则读者会把「修复率」当机会读。"""
        c = calibers.describe("limitdown_repair")
        self.assertIn("负期望", c["pitfall"])
        self.assertIn("4.47", c["pitfall"])


class GateTests(unittest.TestCase):
    """证据闸门：本模块存在的全部意义就是「不要让一个负期望策略变成抄底按钮」。"""

    def test_not_actionable(self) -> None:
        ev = E.get("limitdown_repair")
        self.assertFalse(ev.actionable)
        self.assertFalse(E.is_actionable("limitdown_repair"))
        self.assertFalse(E.is_escalatable("limitdown_repair"))

    def test_tier_is_unsupported_not_unknown(self) -> None:
        """n≥30 且超额为负 → unsupported（有明确结论），不是「还没跑」的 unknown。"""
        ev = E.get("limitdown_repair")
        self.assertEqual(ev.tier, "unsupported")
        self.assertNotEqual(ev.tier, "preliminary")

    def test_summary_carries_sample_size_and_window(self) -> None:
        ev = E.get("limitdown_repair")
        self.assertIn("133", ev.summary)
        self.assertIn("2026-08-31", ev.provenance)

    def test_summary_has_no_recommendation_words(self) -> None:
        """负期望策略的说明里不能出现推荐性话术（描述口径的「买入」不在此列）。"""
        ev = E.get("limitdown_repair")
        for word in ("建议", "推荐", "值得", "可以买", "抄底"):
            self.assertNotIn(word, ev.summary)

    def test_gate_note_offers_observation_not_action(self) -> None:
        """命中但证据不足时，展示层拿到的是「观察池」而不是动作话术。"""
        note = E.gate_note("limitdown_repair")
        self.assertIn("观察池", note)

    def test_survey_reports_zero_actionable(self) -> None:
        s = E.strategy_survey()
        self.assertGreaterEqual(s["total"], 2)
        self.assertEqual(s["actionable"], 0)


class SnapshotShapeTests(unittest.TestCase):
    """快照的字段契约（用纯构造的 items 走聚合层，不打网络）。"""

    def test_decorated_items_carry_position(self) -> None:
        items = [L.normalize_limit_down({"c": "600359", "n": "新农开发", "p": 7860, "days": 2})]
        decorated = [{**t, "position": L.position_tag(t)} for t in items]
        self.assertEqual(decorated[0]["position"]["tag"], "连跌")
        self.assertEqual(decorated[0]["code"], "600359")

    def test_ladder_and_sectors_share_the_same_items(self) -> None:
        """三个聚合层必须看到同一份装饰后数据，否则展开区会缺 position 字段。"""
        items = [L.normalize_limit_down({"c": f"60030{i}", "n": f"N{i}", "p": 7860, "days": i}) for i in range(1, 4)]
        decorated = [{**t, "position": L.position_tag(t)} for t in items]
        for group in L.build_ladder(decorated):
            for row in group["items"]:
                self.assertIn("position", row)
        for sector in L.build_sectors(decorated):
            self.assertTrue(sector["codes"])


if __name__ == "__main__":
    unittest.main()
