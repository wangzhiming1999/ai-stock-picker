"""测量口径登记的测试。

背景：「验证」页同屏会出现 4 个都叫「胜率 / 命中率」的数字（大盘单日命中、推荐 T+1 胜率、
策略调仓期胜率、形态 N 日前向胜率），标的 / 持有期 / 分类数 / 有无基准全都不一样。
把它们并排展示且不说明口径，读者会默认可比——这是「数据不准确」里最隐蔽的一类。

本文件锁定：口径必须登记在案、必须随接口下发、必须写明不可比。
"""
import pytest

from app.services import calibers
from app.services import winrate_service as wr

REQUIRED_FIELDS = ("key", "name", "target", "window", "bucket", "benchmark", "rule", "unit", "pitfall")

# 界面上会出现「率」的六个出处，改动口径必须动这里，不能悄悄新增第七个。
# limitup_relay 是 2026-09-17 新增的连板晋级率：**它和上面四个都不可比**，
# 因为它根本不是收益率口径（详见该条 pitfall）。
# limitdown_repair 是 2026-09-18 新增的跌停次日修复：它是**收益率**口径，
# 但结论为负（n=133、期望 −4.47%/次、胜率 4.5%）—— 登记它正是为了让这个负数
# 在界面上有出处可查，而不是被藏起来或换个说法。它与上面几条同样不可比：
# 标的（全量跌停股）、持有期（D+1 集合竞价）与判定方向都不同。
EXPECTED_KEYS = {
    "prediction",
    "recommendation",
    "strategy_backtest",
    "tactic_backtest",
    "limitup_relay",
    "limitdown_repair",
    "agent_plan",
}


class _Chain:
    """Supabase 查询链的最小替身：任意属性/调用都返回自身，execute 返回预置行。

    只用于让 `get_winrate_stats` 走到「已配置」分支，避免为了测口径解析去连真库。
    """

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def __getattr__(self, _name: str) -> "_Chain":
        return self

    def __call__(self, *_a, **_k) -> "_Chain":
        return self

    async def execute(self):
        from types import SimpleNamespace

        return SimpleNamespace(data=self._rows)


def _fake_client(tables: dict[str, list]):
    class _Client:
        def table(self, name: str) -> _Chain:
            return _Chain(tables.get(name, []))

    async def _get():
        return _Client()

    return _get


class TestRegistry:
    def test_registry_covers_every_rate_shown_in_the_ui(self) -> None:
        assert set(calibers.all_keys()) == EXPECTED_KEYS

    @pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
    def test_every_field_is_filled(self, key: str) -> None:
        item = calibers.describe(key)

        assert item["registered"] is True
        for field in REQUIRED_FIELDS:
            assert str(item.get(field, "")).strip(), f"{key}.{field} 不能为空"

    @pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
    def test_name_states_the_window(self, key: str) -> None:
        """名字必须自带持有期/标的，否则用户在并排对比时无从分辨。"""
        name = calibers.describe(key)["name"]

        assert any(mark in name for mark in ("单日", "T+1", "调仓周期", "持有 N 日")), name

    def test_unregistered_key_is_flagged_not_silently_filled(self) -> None:
        item = calibers.describe("no_such_rate")

        assert item["registered"] is False
        assert "未登记" in item["name"]
        assert item["pitfall"]


class TestIncomparability:
    def test_note_forbids_comparison_and_summing(self) -> None:
        note = calibers.note()

        assert "不可比较" in note
        assert "不可相加" in note

    def test_calibers_actually_differ(self) -> None:
        """如果四条口径实质相同，这一层就没有存在意义 —— 断言它们确实不同。"""
        windows = {calibers.describe(k)["window"] for k in EXPECTED_KEYS}
        targets = {calibers.describe(k)["target"] for k in EXPECTED_KEYS}

        assert len(windows) == len(EXPECTED_KEYS)
        assert len(targets) == len(EXPECTED_KEYS)

    def test_benchmark_is_stated_explicitly_for_every_caliber(self) -> None:
        """有基准的要写清基准是什么，没有的要显式写「无」——留空看起来像忘了填。"""
        for key in EXPECTED_KEYS:
            benchmark = calibers.describe(key)["benchmark"]

            assert benchmark.strip(), key
            assert benchmark.startswith(("无", "沪深300", "同股票池")), f"{key}: {benchmark}"

    def test_only_the_two_backtests_have_a_benchmark(self) -> None:
        with_benchmark = {k for k in EXPECTED_KEYS if not calibers.describe(k)["benchmark"].startswith("无")}

        assert with_benchmark == {"strategy_backtest", "tactic_backtest"}


class TestApiPayload:
    @pytest.mark.asyncio
    async def test_winrate_payload_carries_caliber_and_note(self, monkeypatch) -> None:
        """未配置 Supabase 时也必须下发口径 —— 否则前端空态下无法解释它会显示什么。"""
        monkeypatch.setattr(wr.supabase_store, "is_configured", lambda: False)

        stats = await wr.get_winrate_stats()

        assert stats["caliber_note"] == calibers.note()
        assert stats["prediction"] is None
        assert stats["recommendation"] is None

    @pytest.mark.asyncio
    async def test_winrate_blocks_embed_their_own_caliber(self, monkeypatch) -> None:
        """两个统计块各自带口径，且必须是登记表里的权威内容（不是本地副本）。"""
        monkeypatch.setattr(wr.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(
            wr.supabase_store,
            "get_service_client",
            _fake_client(
                {
                    "prediction_records": [
                        {"direction": "上涨", "hit": True},
                        {"direction": "下跌", "hit": False},
                    ],
                    "daily_recommendations": [{"hit": True}, {"hit": True}, {"hit": False}],
                    "winrate_snapshot": [],
                }
            ),
        )

        stats = await wr.get_winrate_stats()

        assert stats["prediction"]["hit_rate"] == 50.0
        assert stats["recommendation"]["hit_rate"] == 66.7
        assert stats["prediction"]["caliber"] == calibers.describe("prediction")
        assert stats["recommendation"]["caliber"] == calibers.describe("recommendation")
        assert stats["caliber_note"] == calibers.note()
        # 两个口径必须不同，否则同屏展示就是误导
        assert stats["prediction"]["caliber"]["window"] != stats["recommendation"]["caliber"]["window"]

    def test_backtest_service_uses_registered_key(self) -> None:
        """回测接口的 caliber 必须来自登记表，key 写错会静默变成「未登记口径」。"""
        assert "strategy_backtest" in calibers.all_keys()
        assert "tactic_backtest" in calibers.all_keys()
        assert calibers.describe("tactic_backtest")["unit"].startswith("每次命中")
        assert calibers.describe("strategy_backtest")["unit"].startswith("每个调仓期")
