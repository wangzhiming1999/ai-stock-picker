"""形态证据等级闸门的测试。

背景：9 条技巧在 UI 上一律以「买点 / 卖点」呈现，但回测显示没有任何一条达到统计显著。
本文件锁定「未验证形态不得进入买卖点位置」这条约束 —— 它很容易在后续迭代里被
顺手放开（毕竟放开后界面更好看），那正是产品可信度重新崩塌的路径。
"""
import pytest

from app.models import StockHistory
from app.services import pattern_service as ps
from app.services import tactic_evidence as ev

ALLOWED_TIERS = {"verified", "preliminary", "unsupported", "unknown", "not_testable"}


def _hist(closes) -> StockHistory:
    n = len(closes)
    dates = [f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    return StockHistory(dates=dates, closes=list(closes), volumes=[1000.0] * n,
                        opens=list(closes), highs=list(closes), lows=list(closes))


class TestRegistryIntegrity:
    def test_every_tactic_is_registered(self) -> None:
        """新增技巧必须同时登记证据等级，否则会以「未验证」身份悄悄进入 UI。"""
        keys = {t["key"] for t in ps.TACTICS}

        assert set(ev.EVIDENCE) == keys

    def test_tiers_stay_within_the_allowed_set(self) -> None:
        assert {e.tier for e in ev.EVIDENCE.values()} <= ALLOWED_TIERS

    def test_only_verified_tier_is_actionable(self) -> None:
        assert ev.ACTIONABLE_TIERS == {"verified"}
        assert ev.ESCALATION_TIERS == {"verified"}

    def test_unregistered_key_falls_back_to_unknown(self) -> None:
        assert ev.tier_of("no_such_tactic") == "unknown"
        assert ev.is_actionable("no_such_tactic") is False

    def test_every_record_has_summary_and_provenance(self) -> None:
        for key, record in ev.EVIDENCE.items():
            assert record.summary.strip(), key
            assert record.provenance.strip(), key

    def test_snapshot_declares_the_run(self) -> None:
        snap = ev.SNAPSHOT

        assert snap["run_at"] and snap["pool"] and snap["horizons"]
        # 「早期正超额没有复现」这个反例必须留在表里，否则下次有人会照抄旧文档
        assert "未能复现" in snap["note"]

    def test_survey_counts_match_registry(self) -> None:
        survey = ev.survey()

        assert survey["total"] == len(ev.EVIDENCE)
        assert survey["actionable"] == sum(1 for e in ev.EVIDENCE.values() if e.actionable)
        assert sum(survey["by_tier"].values()) == survey["total"]


class TestEscalationGate:
    def test_escalate_keys_are_derived_and_sell_only(self) -> None:
        assert ps.ESCALATE_SELL_KEYS <= {
            t["key"] for t in ps.TACTICS if t["direction"] == "sell"
        }

    def test_escalate_keys_match_verified_sell_tactics(self) -> None:
        expected = {
            t["key"]
            for t in ps.TACTICS
            if t["direction"] == "sell" and ev.EVIDENCE[t["key"]].tier == "verified"
        }

        assert ps.ESCALATE_SELL_KEYS == expected

    def test_no_sell_tactic_currently_escalates(self) -> None:
        """当前无显著卖出形态 → 闸门必须为空。放开前请先把 tier 改成 verified 并说明依据。"""
        assert ps.ESCALATE_SELL_KEYS == set()


class TestPackAttachesEvidence:
    @staticmethod
    def _guillotine_hist() -> StockHistory:
        """均线粘合后一根 -6% 大阴线：一定会命中 guillotine。"""
        return StockHistory(
            dates=[f"2024-01-{i + 1:02d}" for i in range(22)],
            closes=[10.0] * 21 + [9.4],
            volumes=[1000.0] * 22,
            opens=[10.0] * 21 + [10.0],
            highs=[10.0] * 21 + [10.05],
            lows=[10.0] * 21 + [9.3],
        )

    def test_matched_but_unverified_is_not_executable(self) -> None:
        result = ps.detect_guillotine({"daily": self._guillotine_hist(), "price": 9.4})

        assert result["matched"] is True
        # 判定条件成立 ≠ 该形态被证明有效：未验证的命中只能进观察池
        assert result["executable"] is False
        assert result["evidence"]["tier"] == "unsupported"
        assert result["gate_note"].startswith("观察池")

    def test_not_matched_never_executable(self) -> None:
        results = ps.check_one({"daily": None, "intraday": None, "price": None})

        assert all(r["executable"] is False for r in results)
        assert all(r["evidence"]["tier"] in ALLOWED_TIERS for r in results)

    def test_actionable_tier_unlocks_execution(self, monkeypatch) -> None:
        """闸门必须是双向的：真正验证通过的形态要能进入买点位置。

        否则这个闸门会退化成「全部屏蔽」的死开关，日后没人敢动。
        """
        monkeypatch.setitem(
            ev.EVIDENCE,
            "guillotine",
            ev.Evidence(tier="verified", summary="测试用", provenance="测试用"),
        )

        result = ps.detect_guillotine({"daily": self._guillotine_hist(), "price": 9.4})

        assert result["matched"] is True
        assert result["executable"] is True
        assert result["gate_note"] == ""

    def test_list_tactics_exposes_evidence(self) -> None:
        meta = {t["key"]: t for t in ps.list_tactics()}

        assert meta["wash_scrub"]["evidence"]["tier"] == "unsupported"
        assert meta["wash_scrub"]["actionable"] is False
        assert meta["cycle_resonance"]["evidence"]["tier"] == "preliminary"


class TestGateNote:
    def test_gate_note_explains_why_for_every_non_actionable_tactic(self) -> None:
        for key in ev.EVIDENCE:
            note = ev.gate_note(key)
            if ev.is_actionable(key):
                assert note == ""
            else:
                assert "观察池" in note
                assert ev.get(key).summary[:10] in note

    @pytest.mark.parametrize("tier", ["unsupported", "unknown", "not_testable"])
    def test_scope_only_verified_passes(self, tier) -> None:
        assert tier not in ev.ACTIONABLE_TIERS
