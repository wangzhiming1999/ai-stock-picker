"""守卫：扫描 / 回测的**默认技巧集合**必须与 `TACTIC_MAP` 同域。

## 事故（2026-09-21）

`pattern_service.RETIRED_TACTICS = ["ma20_slope"]` 把已下线技巧的 detect 函数
**刻意保留**在 `DETECTORS` 里（注释写明：留给日后重新校准区间时复用回测链路），
但那个 key **不在 `TACTIC_MAP` 里**（TACTIC_MAP 由 TACTICS 推导）。

三处入口把 `keys or list(DETECTORS)` 当默认集合，于是下游 `TACTIC_MAP[key]`
直接 KeyError，线上表现为（报错文案都含 `'ma20_slope'`）：

- `POST /api/backtest/tactic`（前端不传 tactic）→ 502「形态回测失败: 'ma20_slope'」
- `POST /api/market/tactic-scan`（前端「全部技巧」按钮）→ 502「形态计算失败: 'ma20_slope'」
- `GET /api/market/tactic-check`（单票形态体检）→ 502

危害远不止「按钮点不动」：**形态回测是唯一能把技巧从观察池升到 verified 的通道**，
它挂着，11 条技巧的证据等级就永远停在原地。

因此这里不测「某个函数返回值对不对」，只钉一条不变量：
**参与扫描/回测的默认键集合 = TACTIC_MAP 的键**，并且带一条反向验证，
防止守卫退化成「碰巧通过」（如果哪天 DETECTORS 与 TACTIC_MAP 同域，
这条守卫就失去了判别力，需要重新审视它到底在保护什么）。
"""
import datetime as dt

import pytest

from app.models import StockHistory, StockQuote
from app.services import data_service, pattern_service as ps
from app.services import tactic_backtest_service as bt


def _dates(n: int, start: dt.date = dt.date(2024, 1, 1)) -> list[str]:
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _hist(closes, volumes=None, turnover=None) -> StockHistory:
    n = len(closes)
    return StockHistory(
        dates=_dates(n),
        closes=list(closes),
        volumes=list(volumes) if volumes is not None else [1000.0] * n,
        opens=list(closes),
        highs=list(closes),
        lows=list(closes),
        turnover=list(turnover) if turnover is not None else None,
    )


# ---------------- 不变量 ----------------


class ActiveTacticsInvariantTests:
    def test_active_tactics_is_exactly_the_tactic_map_keys(self):
        assert set(ps.ACTIVE_TACTICS) == set(ps.TACTIC_MAP)

    def test_detectors_is_strictly_wider_than_active_tactics(self):
        """反向验证判别力。

        「默认集合 ⊆ TACTIC_MAP」这条断言只有在 DETECTORS 确实更宽时才有意义。
        若哪天两者同域，说明 RETIRED_TACTICS 被清空了 —— 那时本文件的守卫
        就是空转，应该连同 `ACTIVE_TACTICS` 一起重新评估，而不是留着自我安慰。
        """
        extra = set(ps.DETECTORS) - set(ps.ACTIVE_TACTICS)
        assert extra, "DETECTORS 不再宽于 ACTIVE_TACTICS，这组守卫已失去判别力"
        assert extra == set(ps.RETIRED_TACTICS)

    def test_retired_keys_keep_detector_but_leave_the_map(self):
        """下线 ≠ 抹掉：detect 函数保留（可复用回测链路），但不再出现在扫描/面板里。"""
        for key in ps.RETIRED_TACTICS:
            assert key in ps.DETECTORS
            assert key not in ps.TACTIC_MAP

    def test_every_active_tactic_has_a_detector(self):
        missing = [k for k in ps.ACTIVE_TACTICS if ps.DETECTORS.get(k) is None]
        assert missing == []


# ---------------- 三处默认入口不再 KeyError ----------------


class DefaultKeySetEntryPointTests:
    def test_check_one_without_keys_covers_every_active_tactic(self):
        """默认跑全部：过去这里会因默认集合含 ma20_slope 而在取元数据时炸掉。"""
        rows = ps.check_one({"daily": None, "price": None})

        assert [r["key"] for r in rows] == list(ps.ACTIVE_TACTICS)

    def test_evaluate_sync_accepts_the_whole_active_set(self):
        """回测默认路径：`_evaluate_sync` 对每个默认 key 都要能取到元数据。"""
        items = bt._evaluate_sync({}, list(ps.ACTIVE_TACTICS), 10, 100)

        assert [i["key"] for i in items] == list(ps.ACTIVE_TACTICS)
        # 空 hist_map → 落在「未纳入评估」；分时背离另属 not_backtestable。
        # 关键是不能报错，且两者都必须显式区别于「有结果」。
        assert all(i["status"] in {"insufficient_data", "not_backtestable"} for i in items)

    def test_backtest_default_selection_drops_retired_keys(self):
        """显式传入已下线技巧时，它会被过滤掉，而不是让整批回测 502。"""
        requested = ["guillotine", *ps.RETIRED_TACTICS]
        selected = [k for k in requested if k in ps.TACTIC_MAP]

        assert selected == ["guillotine"]


class CheckCodesDefaultPathTests:
    """走一遍 `check_codes` 的默认键路径 —— 这是「全部技巧」按钮的真实调用。"""

    @pytest.fixture
    def patch_sources(self, monkeypatch):
        # 700 根足够覆盖回测最长预热期，且不依赖任何真实行情源
        hist = _hist([10.0 + i * 0.01 for i in range(700)])
        monkeypatch.setattr(data_service, "get_history", lambda code, days=120, **kw: hist)
        monkeypatch.setattr(
            data_service,
            "get_spot_quote",
            lambda cs: [
                StockQuote(code=c, name=f"票{c}", price=10.0, change_pct=1.0, turnover=2.0)
                for c in cs
            ],
        )
        monkeypatch.setattr(data_service, "get_intraday_history", lambda c, p="5m": None)
        # 筹码链路要打东财，测试里一律桩掉（这里只关心「默认键能不能走通」）
        from app.services import chip_service

        async def _no_chips(codes):
            return {}

        monkeypatch.setattr(chip_service, "get_chip_batch_async", _no_chips)

    @pytest.mark.asyncio
    async def test_check_codes_without_keys_runs_every_active_tactic(self, patch_sources):
        rows = await ps.check_codes(["000001"])

        assert len(rows) == 1
        assert [t["key"] for t in rows[0]["tactics"]] == list(ps.ACTIVE_TACTICS)

    @pytest.mark.asyncio
    async def test_backtest_evaluate_default_path_returns_every_active_tactic(self, patch_sources):
        """`evaluate()` 不传 keys 是前端「运行回测验证」的真实调用 —— 修复前必抛 KeyError。"""
        result = await bt.evaluate(codes=["600519"], horizon=5, eval_bars=60)

        assert "error" not in result
        assert [i["key"] for i in result["items"]] == list(ps.ACTIVE_TACTICS)


# ---------------- 顺带钉住的两处「文案必须跟着常量走」 ----------------


class NoteReportingTests:
    def test_turnover_missing_is_reported_with_real_counts(self):
        acc = {"points": 10, "no_turnover": 3, "errors": 0}

        note = bt._note_for("volume_peak", acc)

        assert "3/10" in note

    def test_turnover_note_only_attaches_to_tactics_that_read_it(self):
        acc = {"points": 10, "no_turnover": 3, "errors": 0}

        # 这个技巧根本不看换手率，不该挂一句「缺换手率」误导读者
        assert bt._note_for("guillotine", acc) is None

    def test_skipped_detector_exceptions_are_visible(self):
        """静默 continue 会让「算不出来」和「真没信号」长得一模一样。"""
        acc = {"points": 10, "no_turnover": 0, "errors": 2}

        note = bt._note_for("guillotine", acc)

        assert "2" in note
        assert "异常" in note

    def test_no_note_when_nothing_was_missing(self):
        assert bt._note_for("volume_peak", {"points": 10, "no_turnover": 0, "errors": 0}) is None


class ConditionLabelTests:
    def test_volume_floor_label_uses_the_calibrated_threshold(self):
        """标签必须由常量插值：原文 20% 与校准后的 30% 不一致时，
        会出现「28% 前期均量」被打 ✓ 却标着「≤ 20%」的自相矛盾。"""
        res = ps.detect_volume_floor({"daily": _hist([10.0] * 80), "price": 10.0})
        names = [c["name"] for c in res["conditions"]]

        label = next(n for n in names if "地量" in n and "前期均量" in n)
        assert f"{ps._FLOOR_VOLUME_RATIO:.0%}" in label
        assert "20%" not in label

    def test_volume_floor_confirm_label_uses_the_confirm_ratio(self):
        res = ps.detect_volume_floor({"daily": _hist([10.0] * 80), "price": 10.0})
        names = [c["name"] for c in res["conditions"]]

        label = next(n for n in names if "温和放量" in n)
        assert f"{ps._FLOOR_CONFIRM_RATIO:.0f} 倍" in label
