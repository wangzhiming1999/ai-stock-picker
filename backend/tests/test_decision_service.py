"""决策契约守卫（``app/services/decision.py``）。

背景：项目此前并存 4 套动作枚举（TradePlan / 盯盘 advice / 涨停带 level，以及
portfolio·pattern·sandu 直接拼中文串），用户在同一屏能看到 9 种说法表达同一件事。
本文件把下面两条变成可执行的断言：

1. 动作词只有一个来源，且**不得**包含「观察 / 关注 / 留意 / 跟踪」这类无结论措辞；
2. ``skip``（不参与）与买卖并列，是一等公民 —— 它必须带原因，否则自己又变成模糊词。
"""

import unittest

from app.services import decision


class NormalizeTests(unittest.TestCase):
    """历史散装措辞必须能被归一化，否则灰度期会出现「一半结构化、一半中文」。"""

    def test_legacy_chinese_phrases_map_to_contract(self) -> None:
        cases = {
            "持有观察": "hold",
            "建议减仓": "reduce",
            "可考虑部分止盈": "reduce",
            "可考虑逢低分批关注": "skip",
            "观察：三度尚未齐备，继续跟踪": "skip",
            "可观察回踩成本峰": "skip",
            "暂不参与，等待企稳": "skip",
            "只看不动手": "skip",
            "空仓等待": "skip",
            "封板质量最弱的优先留意": "skip",
            "建议买入区 12.34": "buy",
            "可打板": "buy",
        }
        for raw, expected in cases.items():
            self.assertEqual(decision.normalize(raw), expected, raw)

    def test_english_marks_are_kept(self) -> None:
        for raw, expected in (
            ("buy", "buy"),
            ("sell", "sell"),
            ("hold", "hold"),
            ("stop", "sell"),
            ("avoid", "skip"),
        ):
            self.assertEqual(decision.normalize(raw), expected, raw)

    def test_holding_phrase_is_not_swallowed_by_observation_rule(self) -> None:
        """「持有观察」同时含「持有」与「观察」：hold 规则必须先命中。

        否则它会被 skip 的「观察」吃掉，把「继续持有」误判成「不参与」——
        这类误判会让同一只票在两个页面上拿到相反结论。
        """
        self.assertEqual(decision.normalize("持有观察"), "hold")
        self.assertEqual(decision.normalize("继续观察"), "skip")

    def test_unknown_falls_back_to_skip_never_to_buy(self) -> None:
        """读不懂的文案宁可判成「不参与」，也不能渲染成开仓信号。"""
        self.assertEqual(decision.normalize(None), "skip")
        self.assertEqual(decision.normalize(""), "skip")
        self.assertEqual(decision.normalize("   "), "skip")
        self.assertEqual(decision.normalize("yolo"), "skip")
        self.assertEqual(decision.normalize("yolo", default="hold"), "hold")


class ContractTests(unittest.TestCase):
    def test_six_decisions_and_skip_is_first_class(self) -> None:
        self.assertEqual(len(decision.DECISIONS), 6)
        self.assertIn("skip", decision.DECISIONS)
        # 长标签必须带原因，否则「不参与」自己就又变成一个没有结论的词
        self.assertIn("空仓", decision.DECISION_LONG_LABEL["skip"])

    def test_labels_cover_every_decision(self) -> None:
        for d in decision.DECISIONS:
            self.assertIn(d, decision.DECISION_LABEL)
            self.assertIn(d, decision.DECISION_LONG_LABEL)
            self.assertIn(d, decision.DECISION_ORDER)

    def test_contract_copy_has_no_vague_wording(self) -> None:
        """动作文案里不得再出现「观察 / 关注 / 留意 / 跟踪 / 观望」。"""
        banned = ("观察", "关注", "留意", "跟踪", "观望")
        for d in decision.DECISIONS:
            for text in (decision.DECISION_LABEL[d], decision.DECISION_LONG_LABEL[d]):
                for word in banned:
                    self.assertNotIn(word, text, f"{d} 的文案含模糊词「{word}」")

    def test_label_of_unknown_action_is_skip(self) -> None:
        self.assertEqual(decision.label("yolo"), "不参与")
        self.assertEqual(decision.label(None), "不参与")
        self.assertEqual(decision.label("skip", long=True), "不参与（空仓等待）")

    def test_order_puts_risk_disposal_first(self) -> None:
        order = decision.DECISION_ORDER
        self.assertLess(order["sell"], order["reduce"])
        self.assertLess(order["reduce"], order["buy"])
        self.assertLess(order["add"], order["hold"])
        self.assertLess(order["hold"], order["skip"])


class MakeTests(unittest.TestCase):
    def test_make_returns_four_elements(self) -> None:
        d = decision.make("buy", reason="趋势向上", trigger="到 12.34 挂单", invalidation="跌破 11")
        self.assertEqual(d["action"], "buy")
        self.assertEqual(d["label"], "买入")
        self.assertEqual(d["reason"], "趋势向上")
        self.assertEqual(d["trigger"], "到 12.34 挂单")
        self.assertEqual(d["invalidation"], "跌破 11")

    def test_make_normalizes_input(self) -> None:
        self.assertEqual(decision.make("建议减仓")["action"], "reduce")

    def test_entry_decisions_declared(self) -> None:
        self.assertEqual(set(decision.ENTRY_DECISIONS), {"buy", "add"})


if __name__ == "__main__":
    unittest.main()
