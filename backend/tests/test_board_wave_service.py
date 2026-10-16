"""``board_wave_service`` 的用例。

分五组：① 名称归一化（核心，``hybk`` 是 4 字截断的）② 名录翻页 ③ 板块指数解析
④ 降级路径 ⑤ 缓存与不变量。

fixture 里的板块名与 BK 代码全部是 **2026-10-14 从东财真实名录抓下来的**，
不是编的 —— 归一化规则就是照着这批真实截断样本定的（见 ``_resolve`` 文档）。
"""
from __future__ import annotations

import pytest

from app.services import board_wave_service as bws

# 真实名录切片（2026-10-14 实测）
_LISTING: dict[str, str] = {
    "专用设备": "BK0910",
    "中药Ⅱ": "BK1040",
    "元件": "BK0459",
    "出版": "BK1218",
    "化学制品": "BK0538",
    "化学制药": "BK0465",
    "化学原料": "BK1019",
    "广告营销": "BK1220",
    "影视院线": "BK1222",
    "数字媒体": "BK1221",
    "服装家纺": "BK1225",
    "渔业": "BK1260",
    "游戏Ⅱ": "BK1046",
    "游戏Ⅲ": "BK1301",
    "焦炭Ⅱ": "BK1249",
    "煤炭开采": "BK1250",
    "燃气Ⅱ": "BK1028",
    "电力": "BK0428",
    "电池": "BK1033",
    "纺织制造": "BK1224",
    "通用设备": "BK0545",
    "铁路公路": "BK0421",
    "饮料乳品": "BK1282",
    "饲料": "BK1258",
    "房地产开发": "BK0451",
    "汽车零部件": "BK0481",
    "家电零部件Ⅲ": "BK1455",
    "家电零部件Ⅱ": "BK1242",
    "航空装备Ⅲ": "BK1384",
    "航空装备Ⅱ": "BK1231",
    "半导体": "BK1036",
}

# 2026-10-14 涨停池 hybk 的真实取值（27 个）
_REAL_HYBK = [
    "专用设备", "中药Ⅱ", "元件", "出版", "化学制品", "化学制药", "化学原料",
    "家电零部", "广告营销", "影视院线", "房地产开", "数字媒体", "服装家纺",
    "汽车零部", "渔业", "游戏Ⅱ", "焦炭Ⅱ", "煤炭开采", "燃气Ⅱ", "电力",
    "电池", "纺织制造", "航空装备", "通用设备", "铁路公路", "饮料乳品", "饲料",
]


@pytest.fixture(autouse=True)
def _clear_caches():
    """模块级缓存是全局的，逐个用例清干净，避免互相污染。"""
    bws._list_cache = None
    bws._read_cache.clear()
    yield
    bws._list_cache = None
    bws._read_cache.clear()


# ---------------------------------------------------------------- ① 名称归一化


def test_hybk全部不超过四个字符_这是必须归一化的原因() -> None:
    assert {len(s) for s in _REAL_HYBK} == {2, 3, 4}


def test_精确命中的板块原样返回() -> None:
    name, code, how = bws._resolve("专用设备", _LISTING)
    assert (name, code, how) == ("专用设备", "BK0910", "exact")


def test_四字截断名走唯一前缀还原() -> None:
    name, code, how = bws._resolve("汽车零部", _LISTING)
    assert (name, code, how) == ("汽车零部件", "BK0481", "prefix")
    name, code, how = bws._resolve("房地产开", _LISTING)
    assert (name, code, how) == ("房地产开发", "BK0451", "prefix")


def test_截断名有二级三级两个候选时取二级() -> None:
    """``hybk`` 自己给出的「中药Ⅱ」「游戏Ⅱ」说明它用的是二级行业口径。"""
    name, code, how = bws._resolve("家电零部", _LISTING)
    assert (name, code, how) == ("家电零部件Ⅱ", "BK1242", "prefix_ii")
    name, code, how = bws._resolve("航空装备", _LISTING)
    assert (name, code, how) == ("航空装备Ⅱ", "BK1231", "prefix_ii")


def test_多义且没有二级标注时宁可降级也不猜() -> None:
    """「化学」能前缀到化学制药/化学原料/化学制品，三个都是 4 字且无 Ⅱ，
    这时必须返回 ambiguous —— 猜错会把浪位挂在另一个板块上，比不显示更糟。"""
    name, code, how = bws._resolve("化学", _LISTING)
    assert (name, code, how) == (None, None, "ambiguous")


def test_名录里没有的名字降级为none() -> None:
    assert bws._resolve("光刻胶", _LISTING) == (None, None, "none")


def test_空名与空白名都返回none() -> None:
    assert bws._resolve("", _LISTING) == (None, None, "none")
    assert bws._resolve("   ", _LISTING) == (None, None, "none")


def test_真实27个hybk全部可解_覆盖率达到100percent() -> None:
    """实测这批样本没有一个是不可解的 —— 这条用例是归一化规则的回归网。"""
    resolved = [bws._resolve(s, _LISTING) for s in _REAL_HYBK]
    unresolved = [s for s, (n, _c, how) in zip(_REAL_HYBK, resolved) if n is None or how not in {"exact", "prefix", "prefix_ii"}]
    assert unresolved == []


# ---------------------------------------------------------------- ② 名录翻页


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _page(rows: list[tuple[str, str]], total: int) -> dict:
    return {"data": {"total": total, "diff": [{"f12": c, "f14": n} for n, c in rows]}}


class _FakeSession:
    """按调用次序依次返回给定的 payload；``raise_at`` 里的页码直接抛异常。"""

    def __init__(self, pages: list[dict], raise_at: set[int] | None = None) -> None:
        self._pages = pages
        self._raise_at = raise_at or set()
        self.calls = 0

    def get(self, *_a, **_kw):
        self.calls += 1
        if self.calls in self._raise_at:
            raise RuntimeError("boom")
        idx = min(self.calls - 1, len(self._pages) - 1)
        return _FakeResp(self._pages[idx])


def test_名录要翻页拼接(monkeypatch) -> None:
    pages = [
        _page([("汽车零部件", "BK0481"), ("半导体", "BK1036")], total=4),
        _page([("出版", "BK1218")], total=4),
        _page([("元件", "BK0459")], total=4),
    ]
    monkeypatch.setattr(bws, "_PAGE_SLEEP", 0)
    # 必须是**同一个** session 实例：``_get_json`` 每次都会重新取 session，
    # 若每次新建，调用计数就重置了，翻页会反复拿到第一页。
    sess = _FakeSession(pages)
    monkeypatch.setattr(bws, "_session", lambda: sess)
    listing = bws.fetch_board_list()
    assert listing == {
        "汽车零部件": "BK0481",
        "半导体": "BK1036",
        "出版": "BK1218",
        "元件": "BK0459",
    }


def test_首页就失败要抛错而不是返回空名录(monkeypatch) -> None:
    sess = _FakeSession([_page([], 0)], raise_at={1, 2, 3})
    monkeypatch.setattr(bws, "_session", lambda: sess)
    with pytest.raises(RuntimeError, match="取数失败"):
        bws.fetch_board_list()


def test_后续页失败时保留已拿到的部分而不是整块失败(monkeypatch) -> None:
    """翻页本来就可能漏项（涨跌幅排序会漂移），漏的板块降级，不影响其它板块。"""
    pages = [
        _page([("汽车零部件", "BK0481")], total=496),
        _page([("半导体", "BK1036")], total=496),
    ]
    # 同一个 session 实例，calls 才会跨页累加；2/3/4 是第 2 页的三次尝试（``_RETRY + 1``）
    sess = _FakeSession(pages, raise_at={2, 3, 4})
    monkeypatch.setattr(bws, "_session", lambda: sess)
    monkeypatch.setattr(bws, "_PAGE_SLEEP", 0)
    listing = bws.fetch_board_list()
    assert listing == {"汽车零部件": "BK0481"}


# ---------------------------------------------------------------- ③ 板块指数解析


def test_板块指数日线解析(monkeypatch) -> None:
    payload = {
        "data": {
            "name": "汽车零部件",
            "klines": [
                "2026-10-12,42026.75,41477.43,42189.31,41407.59,23068592,3.2e10,1.86,-1.52,-641.18,1.59",
                "2026-10-13,41002.59,41355.23,41611.75,40109.18,26315856,3.6e10,3.62,-0.29,-122.20,1.81",
            ],
        }
    }
    monkeypatch.setattr(bws, "_session", lambda: _FakeSession([payload]))
    bars = bws._fetch_kline("BK0481")
    assert len(bars) == 2
    assert bars[0] == {
        "date": "2026-10-12", "open": 42026.75, "close": 41477.43,
        "high": 42189.31, "low": 41407.59, "volume": 23068592.0,
    }


def test_板块指数超过样本上限时只保留最近180根(monkeypatch) -> None:
    lines = [f"2026-01-01,1,2,3,0.5,{i},0,0,0,0,0" for i in range(300)]
    monkeypatch.setattr(bws, "_session", lambda: _FakeSession([{"data": {"klines": lines}}]))
    bars = bws._fetch_kline("BK0481")
    assert len(bars) == bws._KLINE_DAYS == 180
    assert bars[-1]["volume"] == 299.0


def test_缺字段的k线行被跳过而不是崩掉(monkeypatch) -> None:
    monkeypatch.setattr(bws, "_session", lambda: _FakeSession([{"data": {"klines": ["2026-10-14,1,2"]}}]))
    assert bws._fetch_kline("BK0481") == []


def test_data为null时返回空列表(monkeypatch) -> None:
    monkeypatch.setattr(bws, "_session", lambda: _FakeSession([{"data": None}]))
    assert bws._fetch_kline("BK0481") == []


# ---------------------------------------------------------------- ④ 降级路径


def test_没有主线板块时直接降级(monkeypatch) -> None:
    def _boom():
        raise AssertionError("没有主线时不该去打名录")

    monkeypatch.setattr(bws, "get_board_list", _boom)
    res = bws.analyze_mainline("—")
    assert res["wave"] is None
    assert res["match"] == "none"
    assert "没有形成主线板块" in res["note"]


def test_名录不可用时降级(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("connect timeout")

    monkeypatch.setattr(bws, "get_board_list", _boom)
    res = bws.analyze_mainline("汽车零部")
    assert res["wave"] is None
    assert "板块名录不可用" in res["note"]


def test_板块名对不上时降级且不改写原始名(monkeypatch) -> None:
    monkeypatch.setattr(bws, "get_board_list", lambda: _LISTING)
    res = bws.analyze_mainline("光刻胶")
    assert res["wave"] is None
    assert res["raw_sector"] == "光刻胶"
    assert "没有对应的行业板块" in res["note"]


def test_板块指数取数失败时降级(monkeypatch) -> None:
    monkeypatch.setattr(bws, "get_board_list", lambda: _LISTING)

    def _boom(_code: str):
        raise RuntimeError("502")

    monkeypatch.setattr(bws, "_fetch_kline", _boom)
    res = bws.analyze_mainline("汽车零部")
    assert res["sector"] == "汽车零部件"
    assert res["code"] == "BK0481"
    assert res["wave"] is None
    assert "板块指数取数失败" in res["note"]


def test_板块指数样本不足时降级(monkeypatch) -> None:
    monkeypatch.setattr(bws, "get_board_list", lambda: _LISTING)
    monkeypatch.setattr(bws, "_fetch_kline", lambda _c: [{"date": "2026-10-14", "close": 1.0}] * 10)
    res = bws.analyze_mainline("汽车零部")
    assert res["wave"] is None
    assert "样本不足 30 根" in res["note"]


def test_波浪计算抛异常也不外抛(monkeypatch) -> None:
    monkeypatch.setattr(bws, "get_board_list", lambda: _LISTING)
    monkeypatch.setattr(bws, "_fetch_kline", lambda _c: [{"date": f"2026-01-{i:02d}", "close": 100.0 + i} for i in range(1, 60)])
    monkeypatch.setattr(bws.wave_service, "analyze_dual", lambda _b: (_ for _ in ()).throw(ValueError("bad")))
    res = bws.analyze_mainline("汽车零部")
    assert res["wave"] is None
    assert "波浪计算异常" in res["note"]


# ---------------------------------------------------------------- ⑤ 成功路径 / 缓存 / 不变量


def _ok_bars(n: int = 120) -> list[dict]:
    """造一段能判出结构的日线（先涨后回），够 30 根且交替明显。"""
    bars = []
    price = 1000.0
    for i in range(n):
        price *= 1.01 if (i // 20) % 2 == 0 else 0.985
        bars.append({"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": price, "close": price,
                     "high": price * 1.01, "low": price * 0.99, "volume": 1e6 + i})
    return bars


def test_成功路径给出双级别读数与匹配说明(monkeypatch) -> None:
    monkeypatch.setattr(bws, "get_board_list", lambda: _LISTING)
    monkeypatch.setattr(bws, "_fetch_kline", lambda _c: _ok_bars())
    res = bws.analyze_mainline("汽车零部")
    assert res["sector"] == "汽车零部件"
    assert res["code"] == "BK0481"
    assert res["match"] == "prefix"
    assert res["bars"] == 120
    assert set(res["wave"]) == {"daily", "weekly", "note"}
    assert "截断名" in res["note"]
    assert "120 根板块指数日线" in res["note"]


def test_读数里没有任何方向或证据字段() -> None:
    """浪位是辅助读数：不得携带方向标签、证据分或可执行性判断。"""
    res = bws.analyze_mainline("—")
    forbidden = {"evidence", "evidence_score", "actionable", "direction_label", "signal"}
    assert forbidden.isdisjoint(res.keys())


def test_名录缓存命中后不再发请求(monkeypatch) -> None:
    calls = {"n": 0}

    def _counted():
        calls["n"] += 1
        return dict(_LISTING), True

    monkeypatch.setattr(bws, "_fetch_board_list", _counted)
    bws.get_board_list()
    bws.get_board_list()
    bws.get_board_list()
    assert calls["n"] == 1


def test_残缺名录只短缓存_网络恢复后能自愈(monkeypatch) -> None:
    """实测翻页中途断线会只拿到 100/496 —— 这种残缺结果按一天缓存会让
    几十个板块整天落在 ``match="none"``。"""
    monkeypatch.setattr(bws, "_fetch_board_list", lambda: ({"元件": "BK0459"}, False))
    bws.get_board_list()
    assert bws._list_cache is not None
    assert bws._list_cache[2] == bws._LIST_TTL_PARTIAL


def test_名录拿全时按一天缓存(monkeypatch) -> None:
    monkeypatch.setattr(bws, "_fetch_board_list", lambda: (dict(_LISTING), True))
    bws.get_board_list()
    assert bws._list_cache is not None
    assert bws._list_cache[2] == bws._LIST_TTL


@pytest.mark.asyncio
async def test_浪位带30分钟缓存(monkeypatch) -> None:
    calls = {"n": 0}

    def _counted(sector: str) -> dict:
        calls["n"] += 1
        return {"sector": sector, "wave": None}

    monkeypatch.setattr(bws, "analyze_mainline", _counted)
    first = await bws.get_mainline_wave("汽车零部")
    second = await bws.get_mainline_wave("汽车零部")
    assert calls["n"] == 1
    assert first == second


@pytest.mark.asyncio
async def test_降级结果也进缓存_避免对不上名字时反复打行情源(monkeypatch) -> None:
    calls = {"n": 0}

    def _counted(sector: str) -> dict:
        calls["n"] += 1
        return {"sector": sector, "wave": None, "match": "none"}

    monkeypatch.setattr(bws, "analyze_mainline", _counted)
    await bws.get_mainline_wave("光刻胶")
    await bws.get_mainline_wave("光刻胶")
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_不同板块各自缓存(monkeypatch) -> None:
    calls = {"n": 0}

    def _counted(sector: str) -> dict:
        calls["n"] += 1
        return {"sector": sector, "wave": None}

    monkeypatch.setattr(bws, "analyze_mainline", _counted)
    await bws.get_mainline_wave("汽车零部")
    await bws.get_mainline_wave("元件")
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_取数失败的降级只短缓存_给自愈留机会(monkeypatch) -> None:
    """名称匹配成功了但拿不到数据 —— 这是临时抖动，不能按 30 分钟锁死。"""
    monkeypatch.setattr(
        bws, "analyze_mainline", lambda s: {"sector": s, "wave": None, "match": "prefix"}
    )
    await bws.get_mainline_wave("汽车零部")
    assert bws._read_cache["汽车零部"][2] == bws._READ_TTL_DEGRADED


@pytest.mark.asyncio
async def test_名称对不上的降级按常规时长缓存(monkeypatch) -> None:
    """名字对不上是稳定结论，重试也不会变，没必要两分钟打一次行情源。"""
    monkeypatch.setattr(
        bws, "analyze_mainline", lambda s: {"sector": s, "wave": None, "match": "none"}
    )
    await bws.get_mainline_wave("光刻胶")
    assert bws._read_cache["光刻胶"][2] == bws._READ_TTL


def test_取数走域名轮换_单域名抽风时不至于全灭(monkeypatch) -> None:
    """东财 push2 是一组编号域名，会各自单独抽风 —— 第一个域名失败要能换到下一个。"""
    seen: list[str] = []

    class _Flaky:
        def get(self, url, **_kw):
            seen.append(url)
            if "17.push2" in url:
                raise RuntimeError("RemoteDisconnected")
            return _FakeResp({"ok": True})

    monkeypatch.setattr(bws, "_session", lambda: _Flaky())
    monkeypatch.setattr(bws, "_RETRY", 3)
    assert bws._get_json(bws._LIST_HOSTS, bws._LIST_PATH, {}) == {"ok": True}
    assert "17.push2" in seen[0]
    assert len(seen) >= 2
