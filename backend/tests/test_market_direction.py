"""大盘方向合成与口径一致性的回归测试。

这里是「方向不稳」的正面防线：方向分必须由量化证据主导、LLM 只能微调、
且单日不允许翻转；方向标签只能从分数推导，不能由文案关键词决定。
"""
import datetime as dt
import random
import unittest

from app.services import market_prediction as mp
from app.services import regime_service as rs


def _summary(evidence: float, breadth: dict | None = None, state: str = "震荡") -> dict:
    return {
        "evidence_score": evidence,
        "regime": {"state": state, "regime_score": evidence, "method": "rule"},
        "breadth": breadth,
    }


def _hist(days: int = 180) -> list[dict]:
    rng = random.Random(3)
    out: list[dict] = []
    price = 3000.0
    start = dt.date(2026, 1, 1)
    for i in range(days):
        out.append(
            {
                "date": (start + dt.timedelta(days=i)).isoformat(),
                "open": round(price, 2),
                "high": round(price, 2),
                "low": round(price, 2),
                "close": round(price, 2),
                "volume": 1.0e8,
            }
        )
        price *= 1 + 0.002 + rng.uniform(-0.005, 0.005)
    return out


class NormalizeDirectionTests(unittest.TestCase):
    def test_flat_keyword_wins_over_bias_word(self) -> None:
        # 历史 bug：「震荡偏强」含「强」被判成上涨，与结算口径矛盾、胜率统计失真
        self.assertEqual(mp.normalize_direction("震荡偏强"), "震荡")
        self.assertEqual(mp.normalize_direction("弱势震荡"), "震荡")
        self.assertEqual(mp.normalize_direction("横盘整理"), "震荡")

    def test_plain_directions(self) -> None:
        self.assertEqual(mp.normalize_direction("上涨"), "上涨")
        self.assertEqual(mp.normalize_direction("强势上涨"), "上涨")
        self.assertEqual(mp.normalize_direction("下跌"), "下跌")
        self.assertEqual(mp.normalize_direction("偏弱"), "下跌")
        self.assertEqual(mp.normalize_direction(""), "震荡")

    def test_is_idempotent_on_normalized_labels(self) -> None:
        for raw in ("上涨", "震荡", "下跌", "震荡偏强", "偏弱"):
            once = mp.normalize_direction(raw)
            self.assertEqual(mp.normalize_direction(once), once)


class FinalizeDirectionTests(unittest.TestCase):
    def test_evidence_dominates_and_llm_is_capped(self) -> None:
        result = {"source": "llm", "summary": {"direction": "震荡偏强", "direction_score": 9.5}}

        mp._finalize_direction(result, _summary(6.8), None, llm_score=9.5)

        summary = result["summary"]
        model = summary["direction_model"]
        # 证据分原样传递（6.8），LLM 贡献被截断在 +0.5 → 7.3
        self.assertAlmostEqual(model["llm_contribution"], rs.LLM_MAX_ADJUST, places=2)
        self.assertAlmostEqual(model["raw_score"], 7.3, places=2)
        self.assertAlmostEqual(summary["direction_score"], 7.3, places=2)
        self.assertEqual(summary["direction"], "上涨")
        # LLM 原始文案单独保留，不参与方向判定
        self.assertEqual(summary["llm_direction"], "震荡偏强")
        self.assertEqual(summary["direction_model"]["llm_direction"], "震荡偏强")

    def test_label_follows_evidence_not_llm_wording(self) -> None:
        # 证据分偏空，即使 LLM 打满分 8.0，标签也必须由证据分决定
        result = {"source": "llm", "summary": {"direction": "上涨", "direction_score": 8.0}}

        mp._finalize_direction(result, _summary(3.2), None, llm_score=8.0)

        summary = result["summary"]
        self.assertEqual(summary["direction"], "下跌")
        self.assertLessEqual(summary["direction_score"], rs.SCORE_DOWN)
        # 分与标签自洽
        self.assertEqual(rs.score_to_direction(summary["direction_score"]), "下跌")

    def test_rule_branch_has_no_llm_input(self) -> None:
        result = {"source": "rule", "summary": {"direction": "震荡", "direction_score": 5.0}}

        mp._finalize_direction(result, _summary(5.0), None, llm_score=None)

        self.assertAlmostEqual(result["summary"]["direction_score"], 5.0, places=2)
        self.assertEqual(result["summary"]["direction"], "震荡")
        self.assertIsNone(result["summary"]["llm_direction"])

    def test_single_day_score_jump_is_capped_inside_a_band(self) -> None:
        prev = {"summary": {"direction_score": 3.9}}
        result = {"source": "llm", "summary": {"direction": "震荡", "direction_score": 5.0}}

        mp._finalize_direction(result, _summary(6.0), prev, llm_score=5.0)

        model = result["summary"]["direction_model"]
        # 平滑 0.6×6.0 + 0.4×3.9 = 5.16，相对昨日 +1.26 超过上限 → 收敛到 4.9
        self.assertAlmostEqual(result["summary"]["direction_score"], 4.9, places=2)
        self.assertEqual(result["summary"]["direction"], "震荡")
        self.assertEqual(model["prev_score"], 3.9)

    def test_consistent_evidence_keeps_direction_stable(self) -> None:
        """同样的证据分连续两天出现时，方向不应发生翻转。"""
        prev = {"summary": {"direction_score": 3.2}}
        result = {"source": "rule", "summary": {"direction": "震荡", "direction_score": 5.0}}

        mp._finalize_direction(result, _summary(3.2), prev, llm_score=None)

        summary = result["summary"]
        self.assertEqual(summary["direction"], "下跌")
        self.assertAlmostEqual(summary["direction_score"], 3.2, places=2)

    def test_prev_amount_and_prev_score_readers(self) -> None:
        prev = {
            "summary": {"direction_score": 4.2},
            "technical": {"breadth": {"total_amount_yi": 9000.0}},
        }

        self.assertAlmostEqual(mp._prev_direction_score(prev), 4.2, places=2)
        self.assertAlmostEqual(mp._prev_amount_yi(prev), 9000.0, places=1)
        self.assertIsNone(mp._prev_direction_score(None))
        self.assertIsNone(mp._prev_amount_yi({"technical": {}}))


class MarketContextTests(unittest.TestCase):
    def test_breadth_is_folded_into_context_and_evidence(self) -> None:
        breadth = rs.compute_breadth(
            [{"code": f"60{i:04d}", "change_pct": 2.0, "amount_yi": 100.0} for i in range(30)]
            + [{"code": f"00{i:04d}", "change_pct": -1.0, "amount_yi": 50.0} for i in range(10)]
        )

        ctx, summary = mp.build_market_context(_hist(), breadth=breadth)

        self.assertIn("【系统量化结论】", ctx)
        self.assertIn("市场宽度：", ctx)
        self.assertIn("上涨占比 75.0%", ctx)
        self.assertEqual(summary["breadth"], breadth)
        # 证据分 = 状态分 + 宽度修正；宽度看多只能把证据分抬高有限幅度
        regime_score = summary["regime"]["regime_score"]
        self.assertGreater(summary["evidence_score"], regime_score)
        self.assertLessEqual(
            summary["evidence_score"], min(10.0, round(regime_score + rs.BREADTH_MAX_TILT, 2))
        )

    def test_missing_breadth_is_tolerated(self) -> None:
        ctx, summary = mp.build_market_context(_hist(), breadth=None)

        self.assertIn("市场宽度：数据暂不可用", ctx)
        self.assertIsInstance(summary["evidence_score"], float)
        self.assertIsNone(summary["breadth"])

    def test_evidence_score_is_always_in_range(self) -> None:
        _, summary = mp.build_market_context(_hist())

        self.assertGreaterEqual(summary["evidence_score"], 0.0)
        self.assertLessEqual(summary["evidence_score"], 10.0)


class RuleBasedPredictionTests(unittest.TestCase):
    def test_note_is_prefixed_to_summary_text(self) -> None:
        _, summary = mp.build_market_context(_hist())

        result = mp._rule_based_prediction(summary, note="LLM 预测输出异常，已回退规则预判。")

        self.assertTrue(result["summary"]["summary"].startswith("LLM 预测输出异常"))
        self.assertEqual(result["source"], "rule")
        # 规则分支不自造方向分，占位值等 _finalize_direction 覆盖
        self.assertEqual(result["date"], "")

    def test_drivers_reference_regime_and_breadth(self) -> None:
        breadth = rs.compute_breadth(
            [{"code": f"60{i:04d}", "change_pct": 2.0, "amount_yi": 100.0} for i in range(30)]
        )
        _, summary = mp.build_market_context(_hist(), breadth=breadth)

        result = mp._rule_based_prediction(summary)

        drivers = " ".join(result["summary"]["drivers"])
        self.assertIn("市场状态", drivers)
        self.assertIn("市场宽度", drivers)


class FlatBandTests(unittest.TestCase):
    def test_flat_band_is_wider_than_legacy_value(self) -> None:
        # 旧的 0.2% 带宽下「震荡」几乎不可能命中，与模型 1/3 的震荡预测概率不匹配
        self.assertGreaterEqual(mp.DIRECTION_FLAT_BAND_PCT, 0.5)


if __name__ == "__main__":
    unittest.main()
