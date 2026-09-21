"""决策先锋（vanguard_service + 资金流批量端点）测试。

钉死四类容易悄悄退化的东西：

1. **三维打分的缺失语义** —— 数据「没观测到」绝不能被算成「读数很差」。
   本项目已经踩过一次同类坑（行情源缺 PE 时把候选池清空），所以
   `amount_yi is None` / `fund is None` / 资金维整体不可用三种情况各有独立断言。
2. **权重归一化** —— 资金维不可用时综合分必须重新归一化，不能拿 0 分冒充缺失。
3. **不 force 底层行情源** —— `refresh=True` 只穿透本服务缓存，底层快照永远
   `force=False`。诊断线上「行情源被风控」的故障，正是「跳过缓存直拉」这句话本身。
4. **证据闸门** —— 三维榜是读数不是收益口径，必须停在 preliminary 且不可执行。
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.models import StockHistory
from app.routes import market as market_routes
from app.services import data_service
from app.services import limitup_service as L
from app.services import quad_service
from app.services import spot_service as S
from app.services import supabase_store
from app.services import tactic_evidence as ev
from app.services import trade_calendar_service
from app.services import vanguard_service as V


def _up_closes(n: int = 250, start: float = 10.0, step: float = 0.1) -> list[float]:
    return [round(start + i * step, 2) for i in range(n)]


def _down_closes(n: int = 250, start: float = 34.9, step: float = 0.1) -> list[float]:
    return [round(start - i * step, 2) for i in range(n)]


def _hist(closes: list[float]) -> StockHistory:
    return StockHistory(
        dates=[f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(len(closes))],
        closes=list(closes),
        volumes=[1e6] * len(closes),
        opens=list(closes),
        highs=list(closes),
        lows=list(closes),
    )


def _spot_row(code: str, name: str = "测试股", **over) -> dict:
    row = {
        "code": code,
        "name": name,
        "price": 20.0,
        "change_pct": 2.0,
        "amount_yi": 10.0,
        "volume_ratio": 1.5,
        "turnover": 5.0,
        "pe": 20.0,
        "pb": 2.0,
        "market_cap_yi": 200.0,
        "change_5min": None,
    }
    row.update(over)
    return row


def _fund_row(code: str, main_net: float, main_pct: float, sector: str | None = "半导体", **over) -> dict:
    row = {
        "code": code,
        "name": "测试股",
        "price": 20.0,
        "change_pct": 2.0,
        "amount": 1e9,
        "main_net": main_net,
        "main_pct": main_pct,
        "super_net": main_net * 0.5,
        "super_pct": main_pct * 0.6,
        "large_net": main_net * 0.5,
        "large_pct": main_pct * 0.4,
        "mid_net": None,
        "small_net": None,
        "sector": sector,
        "rank": 1,
    }
    row.update(over)
    return row


@pytest.fixture(autouse=True)
def _clean_caches():
    V.clear_caches()
    yield
    V.clear_caches()


# ───────────────────────── 暗盘资金维 ─────────────────────────


class DarkMoneyTests:
    def test_strong_inflow_hits_the_ceiling(self) -> None:
        fund = _fund_row("600001", main_net=4e8, main_pct=8.5)
        score, comment = V._score_dark_money(fund, _spot_row("600001"), available=True)

        assert score == 10.0
        assert "吸筹" in comment

    def test_clear_outflow_scores_low(self) -> None:
        fund = _fund_row("600001", main_net=-2e8, main_pct=-5.0, super_net=-1e8)
        score, comment = V._score_dark_money(fund, _spot_row("600001", change_pct=-3.0), available=True)

        assert score == 3.0
        assert "净流出" in comment

    def test_rise_with_main_outflow_is_penalised(self) -> None:
        """上涨但主力净流出 = 拉高出货嫌疑，必须扣分（而不是只按涨幅给分）。"""
        fund = _fund_row("600001", main_net=-2e7, main_pct=-1.0, super_net=-1e7)
        score, comment = V._score_dark_money(
            fund, _spot_row("600001", change_pct=5.0, volume_ratio=0.9), available=True
        )

        assert score == 3.2
        assert "出货" in comment

    def test_unavailable_dim_returns_none_not_zero(self) -> None:
        """资金维整体不可用 → None（调用方重新归一化权重），不能给 0 分。"""
        score, comment = V._score_dark_money(None, _spot_row("600001"), available=False)

        assert score is None
        assert "不可用" in comment

    def test_missing_from_batch_is_neutral_not_zero(self) -> None:
        """批次只覆盖两端；中间段的票是「没被观测」，不是「资金很差」。"""
        score, _ = V._score_dark_money(None, _spot_row("600001"), available=True)

        assert score is not None
        assert 3.5 <= score <= 4.5


# ───────────────────────── 趋势维 ─────────────────────────


class TrendTests:
    def test_bullish_alignment_scores_high(self) -> None:
        closes = _up_closes()
        m = V._trend_metrics(closes, closes, closes, closes[-1])
        score, comment = V._score_trend(m, closes[-1])

        assert score is not None and score >= 9
        assert "多头排列" in comment

    def test_bearish_structure_scores_low(self) -> None:
        closes = _down_closes()
        m = V._trend_metrics(closes, closes, closes, closes[-1])
        score, _ = V._score_trend(m, closes[-1])

        assert score is not None and score <= 2

    def test_insufficient_bars_returns_none(self) -> None:
        m = V._trend_metrics([10.0] * 30, [], [], 10.0)

        assert m is None
        score, comment = V._score_trend(None, 10.0)
        assert score is None
        assert "K 线不足" in comment


# ───────────────────────── 活跃度维（缺失语义回归） ─────────────────────────


class ActivityTests:
    def test_unknown_amount_is_not_punished(self) -> None:
        """回归：成交额未知（None）与成交额很低是两件事，前者不能扣分。

        历史版本写成 `amount = rich.get("amount_yi") or 0` 再判 `< 0.8`，
        于是数据缺失会凭空扣 1.5 分 —— 缺失被伪装成「交投冷清」。
        """
        rich = {"turnover": 5.0, "volume_ratio": 1.5, "market_cap_yi": 100.0, "amount_yi": None}
        unknown, _ = V._score_activity(rich, None)

        thin, comment = V._score_activity({**rich, "amount_yi": 0.5}, None)

        assert unknown == 8.5
        assert thin == 7.0
        assert unknown > thin
        assert "冷清" in comment

    def test_mega_cap_turnover_is_layered(self) -> None:
        """换手率必须按市值分层：大盘蓝筹换手 1% 是活跃，小盘换手 1% 是清淡。"""
        mega, _ = V._score_activity(
            {"turnover": 1.0, "volume_ratio": None, "market_cap_yi": 1200.0, "amount_yi": None}, None
        )
        small, _ = V._score_activity(
            {"turnover": 1.0, "volume_ratio": None, "market_cap_yi": 60.0, "amount_yi": None}, None
        )

        assert mega > small


# ───────────────────────── 综合分与分位 ─────────────────────────


class CompositeTests:
    def test_full_weights_when_all_dims_available(self) -> None:
        overall, used = V._composite({"dark_money": 10.0, "trend": 8.0, "activity": 6.0})

        assert overall == pytest.approx(8.3, abs=0.01)
        assert used == {"dark_money": 0.4, "trend": 0.35, "activity": 0.25}

    def test_missing_dim_renormalises_instead_of_zeroing(self) -> None:
        overall, used = V._composite({"dark_money": None, "trend": 8.0, "activity": 6.0})

        assert overall == pytest.approx(7.17, abs=0.01)
        assert "dark_money" not in used
        assert sum(used.values()) == pytest.approx(1.0, abs=1e-6)

    def test_all_missing_is_zero_with_no_weights(self) -> None:
        overall, used = V._composite({"dark_money": None, "trend": None, "activity": None})

        assert overall == 0.0
        assert used == {}


class PctRankTests:
    def test_rank_is_bounded_and_monotonic(self) -> None:
        vals = [1.0, 2.0, 3.0]

        assert V._pct_rank(vals, 1.0) < V._pct_rank(vals, 2.0) < V._pct_rank(vals, 3.0)
        assert 0.0 <= V._pct_rank(vals, -100) < 0.2
        assert 0.8 < V._pct_rank(vals, 3.0) <= 1.0
        assert V._pct_rank([], 5.0) == 0.5


# ───────────────────────── 板块 / 抱团 / 龙头 ─────────────────────────


class SectorTests:
    def test_missing_sector_field_marks_unavailable(self) -> None:
        rows = [_fund_row(f"60000{i}", 1e8, 3.0, sector=None) for i in range(4)]
        sectors, available = V._sector_strength(rows, None)

        assert available is False
        assert sectors == []

    def test_sector_strength_ranks_by_money(self) -> None:
        rows = [
            _fund_row("600001", 3e8, 5.0, "半导体"),
            _fund_row("600002", 2e8, 3.0, "半导体"),
            _fund_row("600003", -1e8, -1.0, "银行"),
            _fund_row("600004", -2e8, -2.0, "银行"),
            _fund_row("600005", 1e7, 1.0, "医药"),
            _fund_row("600006", -1e7, 0.5, "医药"),
        ]
        sectors, available = V._sector_strength(rows, None)

        assert available is True
        assert [s["sector"] for s in sectors][0] == "半导体"
        assert sectors[0]["strength_score"] > sectors[-1]["strength_score"]
        assert sectors[0]["net_inflow_yi"] == pytest.approx(5.0, abs=0.01)

    def test_single_member_sector_is_dropped(self) -> None:
        rows = [_fund_row("600001", 3e8, 5.0, "半导体")] + [
            _fund_row(f"60001{i}", 1e8, 2.0, "银行") for i in range(2)
        ]
        sectors, _ = V._sector_strength(rows, None)

        assert [s["sector"] for s in sectors] == ["银行"]

    def test_limitup_layer_lifts_concentrated_sector(self) -> None:
        rows = [
            _fund_row("600001", 1e8, 2.0, "半导体"),
            _fund_row("600002", 1e8, 2.0, "半导体"),
            _fund_row("600003", 1e8, 2.0, "银行"),
            _fund_row("600004", 1e8, 2.0, "银行"),
        ]
        plain, _ = V._sector_strength(rows, None)
        lifted, _ = V._sector_strength(
            rows, {"sectors": [{"sector": "半导体", "count": 5, "max_boards": 3, "seal_fund_yi": 1.0}]}
        )

        before = next(s for s in plain if s["sector"] == "半导体")["strength_score"]
        after = next(s for s in lifted if s["sector"] == "半导体")["strength_score"]
        assert after > before


class HerdingTests:
    def test_concentrated_flow_and_sentiment_scores_high(self) -> None:
        sectors = [
            {"sector": "A", "net_inflow_yi": 10.0},
            {"sector": "B", "net_inflow_yi": 5.0},
            {"sector": "C", "net_inflow_yi": 1.0},
        ]
        snapshot = {
            "stocks": [{}] * 8,
            "sectors": [
                {"sector": "A", "count": 4, "max_boards": 3},
                {"sector": "B", "count": 2, "max_boards": 2},
            ],
            "sentiment": {"tone": "good"},
        }
        h = V._herding(sectors, snapshot)

        assert h["level"] == "high"
        assert h["score"] == 10.0
        assert h["concentration"] == pytest.approx(0.75, abs=0.01)
        assert h["limitup_total"] == 8

    def test_no_input_degrades_to_unknown(self) -> None:
        h = V._herding([], None)

        assert h["level"] == "unknown"
        assert h["score"] is None


class LeaderTests:
    @staticmethod
    def _item(code: str, dm: float, tr: float, change: float, **over) -> dict:
        item = {
            "code": code,
            "name": f"股{code}",
            "price": 20.0,
            "change_pct": change,
            "sector": "半导体",
            "turnover": 5.0,
            "overall_score": 8.0,
            "scores": {"dark_money": dm, "trend": tr, "activity": 7.0},
            "metrics": {"pct_from_high": -5.0},
            "fund": {"main_pct": 5.0},
        }
        item.update(over)
        return item

    def test_excludes_near_limit_up_targets(self) -> None:
        """涨幅 ≥9% 的排掉：它们大概率一字/秒板，列出来只会导向一个买不进的价格。"""
        items = [self._item("600001", 8.0, 7.0, 3.0), self._item("600002", 9.0, 9.0, 9.5)]
        leaders = V._leaders(items, {"半导体"})

        assert [x["code"] for x in leaders] == ["600001"]

    def test_requires_both_money_and_trend(self) -> None:
        items = [self._item("600001", 6.0, 9.0, 2.0), self._item("600002", 9.0, 4.0, 2.0)]
        leaders = V._leaders(items, set())

        assert leaders == []

    def test_far_from_high_is_not_a_leader(self) -> None:
        items = [self._item("600001", 9.0, 9.0, 2.0, metrics={"pct_from_high": -55.0})]

        assert V._leaders(items, set()) == []


# ───────────────────────── 资金流批量端点（spot_service） ─────────────────────────


class FundFlowParseTests:
    def test_row_parses_all_fields(self) -> None:
        row = S._fund_flow_row(
            {
                "f12": "600519",
                "f14": "贵州茅台",
                "f2": 1500.0,
                "f3": 2.1,
                "f6": 5e9,
                "f62": 3.2e8,
                "f184": 6.5,
                "f66": 2e8,
                "f69": 4.1,
                "f72": 1.2e8,
                "f75": 2.4,
                "f78": -1e7,
                "f84": -5e6,
                "f100": "酿酒行业",
            },
            rank=1,
        )

        assert row is not None
        assert row["code"] == "600519"
        assert row["name"] == "贵州茅台"
        assert row["main_net"] == pytest.approx(3.2e8)
        assert row["main_pct"] == pytest.approx(6.5)
        assert row["amount"] == pytest.approx(5e9)
        assert row["sector"] == "酿酒行业"

    def test_blank_sector_becomes_none(self) -> None:
        row = S._fund_flow_row({"f12": "600001", "f62": 1e8, "f100": "-"}, rank=1)

        assert row is not None
        assert row["sector"] is None

    def test_rows_without_code_or_money_are_dropped(self) -> None:
        assert S._fund_flow_row({"f62": 1e8}, rank=1) is None
        assert S._fund_flow_row({"f12": "600001", "f62": None, "f184": None}, rank=1) is None

    def test_fetch_uses_clist_batch_params(self, monkeypatch) -> None:
        """必须打 clist 批量端点（按 fid 排序整页返回），而不是逐股接口。"""
        sent: list[dict] = []

        def fake_em(session, params, host_offset=0):
            sent.append(dict(params))
            return {"data": {"total": 1}}, [{"f12": "600001", "f62": 1e8, "f184": 3.0, "f100": "半导体"}]

        monkeypatch.setattr(S, "_em_request", fake_em)
        rows = S.fetch_fund_flow_rows("f62", ascending=False, max_pages=1)

        assert len(rows) == 1
        assert len(sent) == 1, "单页请求不应产生额外请求"
        assert sent[0]["fid"] == "f62"
        assert sent[0]["po"] == "1"
        assert "/api/qt/clist/get" == S._EM_FF_PATH
        assert "f62" in sent[0]["fields"]

    def test_ascending_switches_sort_direction(self, monkeypatch) -> None:
        sent: list[dict] = []

        def fake_em(session, params, host_offset=0):
            sent.append(dict(params))
            return {"data": {"total": 1}}, [{"f12": "600001", "f62": -1e8, "f184": -3.0}]

        monkeypatch.setattr(S, "_em_request", fake_em)
        S.fetch_fund_flow_rows("f62", ascending=True, max_pages=1)

        assert sent[0]["po"] == "0"

    def test_page_count_is_capped(self, monkeypatch) -> None:
        calls: list[str] = []

        def fake_em(session, params, host_offset=0):
            calls.append(params["pn"])
            return {"data": {"total": 5000}}, [{"f12": f"6000{params['pn']}", "f62": 1e8, "f184": 1.0}]

        monkeypatch.setattr(S, "_em_request", fake_em)
        S.fetch_fund_flow_rows("f62", ascending=False, max_pages=2)

        assert calls == ["1", "2"], "页数必须被 max_pages 截断，否则一次刷新就是几十个请求"

    def test_empty_payload_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(S, "_em_request", lambda *a, **k: ({"data": {}}, []))

        with pytest.raises(RuntimeError):
            S.fetch_fund_flow_rows("f62", ascending=False, max_pages=1)


class FundMapTests:
    def test_roundtrip_preserves_units(self) -> None:
        rows = [_fund_row("600001", 3.2e8, 6.5, "半导体")]
        mapping = V._fund_map(rows)

        assert mapping["600001"][0] == pytest.approx(3.2, abs=1e-3)
        back = V._fund_map_entry_to_row("600001", "测试股", mapping["600001"])
        assert back["main_net"] == pytest.approx(3.2e8, rel=1e-4)
        assert back["main_pct"] == pytest.approx(6.5)
        assert back["sector"] == "半导体"

    def test_map_keeps_largest_absolute_flows(self) -> None:
        rows = [_fund_row(f"6000{i:02d}", v, 1.0) for i, v in enumerate([1e7, 9e8, 5e8, -2e8])]
        mapping = V._fund_map(rows, limit=2)

        assert set(mapping) == {"600001", "600002"}

    def test_short_entry_does_not_crash(self) -> None:
        back = V._fund_map_entry_to_row("600001", "x", [1.0])

        assert back["main_net"] == pytest.approx(1e8)
        assert back["sector"] is None


class FundLoadGateTests:
    @pytest.mark.asyncio
    async def test_market_cooldown_short_circuits_before_any_request(self, monkeypatch) -> None:
        """共享冷却期内**不能**去打资金流端点 —— 那正是把封禁拖长的动作。"""
        calls: list[str] = []

        async def fake_cooldown() -> int:
            return 42

        def fake_fetch(*a, **k):
            calls.append("fetch")
            return []

        monkeypatch.setattr(market_routes, "spot_cooldown_seconds", fake_cooldown)
        monkeypatch.setattr(S, "fetch_fund_flow_rows", fake_fetch)

        result = await V._load_fund_flow()

        assert result["status"] == "cooldown"
        assert calls == []
        assert "42" in result["note"]

    @pytest.mark.asyncio
    async def test_failure_enters_local_cooldown_and_does_not_retry(self, monkeypatch) -> None:
        calls: list[str] = []

        async def fake_cooldown() -> int:
            return 0

        def fake_fetch(*a, **k):
            calls.append("fetch")
            raise RuntimeError("东财断连")

        monkeypatch.setattr(market_routes, "spot_cooldown_seconds", fake_cooldown)
        monkeypatch.setattr(S, "fetch_fund_flow_rows", fake_fetch)

        first = await V._load_fund_flow()
        second = await V._load_fund_flow()

        assert first["status"] == "unavailable"
        assert second["status"] == "unavailable"
        assert "冷却中" in second["note"]
        assert len(calls) == 2, "两轮各一次；第二轮必须命中本地冷却，不再打端点"

    @pytest.mark.asyncio
    async def test_success_is_cached(self, monkeypatch) -> None:
        calls: list[str] = []

        async def fake_cooldown() -> int:
            return 0

        def fake_fetch(field, ascending=False, **k):
            calls.append(field)
            return [_fund_row("600001", 1e8, 3.0)]

        monkeypatch.setattr(market_routes, "spot_cooldown_seconds", fake_cooldown)
        monkeypatch.setattr(S, "fetch_fund_flow_rows", fake_fetch)

        first = await V._load_fund_flow()
        second = await V._load_fund_flow()

        assert first["status"] == "ok"
        assert second["status"] == "cached"
        assert len(calls) == 2, "成功时只在首次拉两侧，第二次命中内存缓存"


# ───────────────────────── 整榜生成 ─────────────────────────


class BoardGenerationTests:
    @staticmethod
    def _patch_environment(monkeypatch, calls: dict, fund_rows: list[dict]) -> None:
        async def fake_full_spot(force: bool = False):
            calls["spot_force"] = force            # 记录底层是否被 force
            codes = [f"6000{i:02d}" for i in range(1, 7)]
            # 现价与 K 线末根对齐（34.9），否则 pct_from_high 会被算成 -40% 以上，
            # 把「龙头候选」的筛选条件测成假阴性。
            return [_spot_row(c, name=f"测试{i}", price=34.9) for i, c in enumerate(codes, start=1)]

        async def fake_fund(force: bool = False):
            calls["fund_force"] = force
            return {"status": "ok", "rows": fund_rows}

        async def fake_snapshot(force: bool = False):
            return {
                "stocks": [{"code": "600001", "sector": "半导体"}] * 6,
                "sectors": [{"sector": "半导体", "count": 6, "max_boards": 2, "seal_fund_yi": 1.0}],
                "sentiment": {"tone": "good"},
            }

        async def fake_last_trading_day():
            return dt.date(2026, 9, 19)

        monkeypatch.setattr(quad_service, "get_full_spot", fake_full_spot)
        monkeypatch.setattr(V, "_load_fund_flow", fake_fund)
        monkeypatch.setattr(data_service, "get_history", lambda code, days=120, **k: _hist(_up_closes()))
        monkeypatch.setattr(L, "get_snapshot", fake_snapshot)
        monkeypatch.setattr(supabase_store, "is_configured", lambda: False)
        monkeypatch.setattr(trade_calendar_service, "last_trading_day", fake_last_trading_day)

    @pytest.mark.asyncio
    async def test_refresh_never_forces_the_underlying_spot(self, monkeypatch) -> None:
        """refresh=True 只穿透本服务缓存；底层全市场快照永远 force=False。

        这条约束是**诊断线上故障的定义本身**：跳过缓存直拉行情源会把 IP 封禁拖长。
        """
        calls: dict = {}
        fund_rows = [_fund_row(f"6000{i:02d}", 1e8 * i, 2.0 * i, "半导体") for i in range(1, 7)]
        self._patch_environment(monkeypatch, calls, fund_rows)

        await V.generate_board(force_refresh=True)

        assert calls["spot_force"] is False
        assert calls["fund_force"] is True, "refresh 应当穿透本服务的资金流缓存"

    @pytest.mark.asyncio
    async def test_board_shape_and_gates(self, monkeypatch) -> None:
        calls: dict = {}
        fund_rows = [_fund_row(f"6000{i:02d}", 1e8 * i, 2.0 * i, "半导体") for i in range(1, 7)]
        self._patch_environment(monkeypatch, calls, fund_rows)

        board = await V.generate_board(force_refresh=True)

        assert board["date"] == "2026-09-19"
        assert board["evidence"]["tier"] == "preliminary"
        assert board["evidence"]["actionable"] is False
        assert board["fund_flow"]["status"] == "ok"
        assert board["items"], "应至少产出一只上榜股"
        assert board["fund_map"], "资金映射必须随榜下发，供诊股在冷实例复用"

        first = board["items"][0]
        assert first["rank"] == 1
        assert set(first["scores"]) == {"dark_money", "trend", "activity"}
        assert first["levels"] is not None
        assert "support" in first["levels"] and "stop_loss" in first["levels"]

        # 买卖时机复用的是「买入侧实测为负」的 monitor_levels —— 必须显式下发
        assert board["timing"]["evidence"]["tier"] == "unsupported"
        assert "不是买入指令" in board["timing"]["note"]

        assert isinstance(board["sectors"], list) and board["sectors"]
        assert board["leaders"], "资金与趋势双达标的票应当选出龙头候选"

    @pytest.mark.asyncio
    async def test_fund_unavailable_renormalises_and_says_so(self, monkeypatch) -> None:
        calls: dict = {}

        async def fake_fund(force: bool = False):
            return {"status": "unavailable", "rows": [], "note": "端点冷却中"}

        self._patch_environment(monkeypatch, calls, [])
        monkeypatch.setattr(V, "_load_fund_flow", fake_fund)

        board = await V.generate_board(force_refresh=True)

        assert board["fund_flow"]["status"] == "unavailable"
        assert board["items"][0]["scores"]["dark_money"] is None
        assert "重新归一化" in board["weights_note"]
        assert "不可用" in board["headline"]

    @pytest.mark.asyncio
    async def test_limitup_failure_does_not_break_the_board(self, monkeypatch) -> None:
        """涨停池失败只降级板块情绪层，整榜仍要出得来。"""
        calls: dict = {}
        fund_rows = [_fund_row(f"6000{i:02d}", 1e8 * i, 2.0 * i, "半导体") for i in range(1, 7)]
        self._patch_environment(monkeypatch, calls, fund_rows)

        async def boom(force: bool = False):
            raise RuntimeError("涨停池获取失败")

        monkeypatch.setattr(L, "get_snapshot", boom)

        board = await V.generate_board(force_refresh=True)

        assert board["items"]
        assert board["herding"]["level"] in {"low", "mid", "high", "unknown"}


# ───────────────────────── 证据闸门 ─────────────────────────


class EvidenceGateTests:
    def test_registered_as_preliminary_and_not_actionable(self) -> None:
        record = ev.get("vanguard_three_dim")

        assert record.tier == "preliminary"
        assert record.actionable is False
        assert record.summary.strip() and record.provenance.strip()

    def test_namespace_stays_disjoint(self) -> None:
        assert not (set(ev.EVIDENCE) & set(ev.STRATEGY_EVIDENCE))

    def test_dark_pool_wording_is_honest(self) -> None:
        """产品名可以叫「暗盘资金」，但证据文案必须写明它是大单口径 —— 口径不能被名字带走。"""
        record = ev.get("vanguard_three_dim")

        assert "大单口径" in record.summary
        assert "没有公开暗盘成交数据" in record.summary
