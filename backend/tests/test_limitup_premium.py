"""涨停次日溢价读数（打板方向）的回归测试。

这是本项目**唯一收益为正**的方向，也正因如此最容易越界 —— 三处必须锁死：

1. **档位归档不能错** —— 换手率是「可成交性」的代理，归档写反会把「买不进的一字板」
   当成「可执行的档位」报给用户；封板时间的边界（09:35 整）同理。
2. **期望与可成交性必须分开报** —— 收益大头落在买不进的档（换手 <5% 期望 +3.31%），
   合并成一个数字就等于把「看得见吃不着」的收益算进用户预期。
3. **证据闸门** —— 可成交性只是代理口径，因此 `limitup_premium` 必须停在 preliminary
   且 `actionable=False`。收益为正**不构成**升级理由。
"""
import unittest

from app.services import calibers, limitup_service as L, tactic_evidence as E

# 措辞纪律：统计读数里不允许出现动作词（与 limitup_relay 的 tier 分层同一套约束）
_ACTION_WORDS = ("买入", "建仓", "加仓", "建议", "推荐", "介入", "抄底", "上车")


def _stock(code="600000", turnover=10.0, seal_time="09:40:00", breaks=0) -> dict:
    return {"code": code, "name": f"股票{code}", "turnover": turnover, "seal_time": seal_time, "break_count": breaks}


class TurnoverBucketTests(unittest.TestCase):
    def test_buckets_are_archived_by_turnover(self) -> None:
        cases = [(0.5, "<5%"), (4.99, "<5%"), (5.0, "5-15%"), (14.99, "5-15%"), (15.0, "15-30%"), (29.99, "15-30%"), (30.0, "≥30%"), (88.0, "≥30%")]
        for turnover, expected in cases:
            with self.subTest(turnover=turnover):
                self.assertEqual(L.premium_readout(_stock(turnover=turnover))["bucket"], expected)

    def test_expectation_decays_as_turnover_rises(self) -> None:
        # 单调性是这条口径的核心事实；若哪天数值反过来，说明档位表被改错了。
        values = [L.premium_readout(_stock(turnover=t))["expect_pct"] for t in (1.0, 10.0, 20.0, 40.0)]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_low_turnover_is_marked_unbuyable(self) -> None:
        # 缩量一字/秒板期望最高但挂不上单 —— 可成交性必须为 False。
        low = L.premium_readout(_stock(turnover=1.0))
        self.assertTrue(low["tradable"] is False)
        self.assertIn("挂不上单", low["bucket_note"])

    def test_tradable_depends_on_turnover_alone(self) -> None:
        self.assertTrue(L.premium_readout(_stock(turnover=8.0))["tradable"])
        self.assertFalse(L.premium_readout(_stock(turnover=4.9))["tradable"])


class SealTimeTests(unittest.TestCase):
    def test_seal_time_boundaries(self) -> None:
        cases = [
            ("09:25:00", 3.67, False),
            ("09:35:00", 3.67, False),
            ("09:35:01", 1.56, False),
            ("10:00:00", 1.56, False),
            ("11:00:00", 1.67, False),
            ("13:30:00", 1.17, False),
            ("14:00:00", 1.17, False),
            ("14:00:01", -0.48, True),
            ("14:59:00", -0.48, True),
        ]
        for seal_time, expect, negative in cases:
            with self.subTest(seal_time=seal_time):
                readout = L.premium_readout(_stock(seal_time=seal_time))
                self.assertEqual(readout["seal_expect_pct"], expect)
                self.assertEqual(any(f["key"] == "late_seal" for f in readout["flags"]), negative)

    def test_missing_seal_time_is_not_archived_and_does_not_flag(self) -> None:
        # 缺失 ≠ 尾盘板：不能因为拿不到封板时间就打上负期望标记。
        for raw in (None, "", "09"):
            with self.subTest(raw=raw):
                readout = L.premium_readout(_stock(seal_time=raw))
                self.assertIsNone(readout["seal_expect_pct"])
                self.assertEqual(readout["flags"], [])

    def test_break_count_flag_only_from_three(self) -> None:
        for breaks, flagged in ((0, False), (2, False), (3, True), (7, True)):
            with self.subTest(breaks=breaks):
                readout = L.premium_readout(_stock(breaks=breaks))
                self.assertEqual(any(f["key"] == "high_break" for f in readout["flags"]), flagged)


class SummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stocks = [
            _stock("600001", turnover=2.0),   # 缩量一字 —— 买不进
            _stock("600002", turnover=3.0),   # 缩量一字 —— 买不进
            _stock("600003", turnover=8.0),   # 可成交
            _stock("600004", turnover=40.0),  # 可成交（期望最薄）
            _stock("600005", turnover=12.0, seal_time="14:30:00"),  # 可成交但尾盘封板
        ]

    def test_tradable_and_unbuyable_are_reported_separately(self) -> None:
        summary = L.premium_summary(self.stocks)

        self.assertEqual(summary["total"], 5)
        self.assertEqual(summary["tradable"]["count"], 3)
        self.assertEqual(summary["unbuyable"]["count"], 2)
        # 两者必须分开：合并后会把 +3.31% 的一字板算进「能赚多少」。
        self.assertLessEqual(summary["tradable"]["expect_high"], 1.62)
        self.assertEqual(summary["unbuyable"]["expect_high"], 3.31)

    def test_late_seal_count_is_surfaced(self) -> None:
        summary = L.premium_summary(self.stocks)

        self.assertEqual(summary["late_seal_count"], 1)
        self.assertIn("尾盘封板", summary["headline"])

    def test_bucket_counts_add_up_to_total(self) -> None:
        summary = L.premium_summary(self.stocks)

        self.assertEqual(sum(b["count"] for b in summary["buckets"]), summary["total"])
        self.assertEqual([b["label"] for b in summary["buckets"]], ["<5%", "5-15%", "15-30%", "≥30%"])

    def test_empty_pool_returns_readable_summary(self) -> None:
        summary = L.premium_summary([])

        self.assertEqual(summary["total"], 0)
        self.assertIsNone(summary["tradable"])
        self.assertIn("无涨停股", summary["headline"])

    def test_all_unbuyable_pool_says_so(self) -> None:
        summary = L.premium_summary([_stock(f"60000{i}", turnover=1.0) for i in range(3)])

        self.assertIsNone(summary["tradable"])
        self.assertIn("可成交性差", summary["headline"])


class DisciplineTests(unittest.TestCase):
    def test_bucket_and_flag_copy_contains_no_action_words(self) -> None:
        # 免责句（headline 里的「不是买入指令」）本身含「买入」二字，故只检查分档文案与标记。
        summary = L.premium_summary(
            [_stock("600001", turnover=1.0), _stock("600002", turnover=9.0, seal_time="14:40:00")]
        )
        copy = "".join(b["label"] + b["note"] for b in summary["buckets"])
        for s in (_stock("600003", breaks=4), _stock("600004", seal_time="14:50:00")):
            copy += "".join(f["label"] + f["note"] for f in L.premium_readout(s)["flags"])
        for word in _ACTION_WORDS:
            self.assertNotIn(word, copy, f"统计读数里出现动作词「{word}」")

    def test_headline_carries_the_disclaimer(self) -> None:
        summary = L.premium_summary([_stock(turnover=9.0)])

        self.assertIn("不是买入指令", summary["headline"])

    def test_evidence_stays_preliminary_and_not_actionable(self) -> None:
        # 收益为正但可成交性是代理口径 —— 不可升级。
        self.assertEqual(E.tier_of("limitup_premium"), "preliminary")
        self.assertFalse(E.is_actionable("limitup_premium"))

    def test_caliber_is_registered_and_shipped_with_the_data(self) -> None:
        # 「没有登记的百分比不允许出现在界面上」：读数必须自带口径与易骗点。
        readout = L.premium_readout(_stock())
        summary = L.premium_summary([_stock()])

        self.assertIsNotNone(readout["evidence"]["tier"])
        self.assertEqual(summary["caliber"]["key"], "limitup_premium")
        self.assertTrue(summary["caliber"]["registered"])
        self.assertIn("买不进", calibers.describe("limitup_premium")["pitfall"])


if __name__ == "__main__":
    unittest.main()
