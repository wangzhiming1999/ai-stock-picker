"""主线板块的波浪定位（只读辅助读数）。

## 它回答什么

「今天涨停聚集度最高的那条主线板块，指数自己走到第几浪了」。

数据链：涨停快照的 ``sectors[0].sector``（主线板块名，来自东财涨停池 ``hybk``）
→ 东财行业板块名录换成 ``BK####`` 代码 → 该板块的**板块指数**日线
→ ``wave_service.analyze_dual`` 判浪（日线 + 周线）。

## 三个必须知道的坑（改之前先读）

1. **``hybk`` 是被截断到 4 个字符的**。实测 2026-10-14 的 27 个 sector 值长度分布只有
   {2, 3, 4}：``汽车零部`` / ``家电零部`` / ``房地产开`` 分别对应完整的
   ``汽车零部件`` / ``家电零部件Ⅱ`` / ``房地产开发``。因此**不能**拿它直接当板块名去查，
   必须过 ``_resolve()`` 归一化 —— 直接用原名匹配的话命中率是 0。

2. **东财行业板块有 Ⅱ/Ⅲ 分级，全量 496 个**，而列表接口单页上限 100，必须翻页。
   翻页用的是**涨跌幅排序**，盘中实时漂移，前后两次可能重复或漏项 —— 实测一轮拿到
   488/496。漏掉的板块会走到 ``match="none"`` 并降级，不影响其它板块的读数。

3. **akshare 的 ``stock_board_industry_hist_em`` 不能按板块名调用**：它内部先拉名录做
   ``板块名称 == symbol`` 的**精确**匹配，名字对不上直接抛 IndexError；而且那段请求会
   走进程的环境代理（本地代理不稳时必挂）。所以这里自己维护名录 + 直接传 ``BK####`` 代码。

## 口径（与 ``wave_service`` 一致，不得放宽）

* 读数**不进** ``evidence_score``、**不进** LLM prompt —— 理由见 ``wave_service`` 模块说明；
* 任何一步失败都降级成**结构完整**的读数（``wave=None`` + ``note`` 说明原因），
  异常不外抛到路由 —— 辅助读数不允许影响主链路；
* 沿用 ``wave_service`` 的输出结构：必须带级别（日线/周线）与置信度。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time

import requests

from app.services import wave_service

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 东财的 push2 / push2his 是**一组编号域名**（1. / 7. / 17. / 82. …），它们会各自单独抽风：
# 实测同一时刻 `17.push2` 的连接被直接断开，而同组的另一个域名正常返回。所以这里做
# 域名轮换，而不是钉死一个域名连着重试 —— 后者在域名级抖动时会让整块功能全灭。
_LIST_HOSTS = (
    "17.push2.eastmoney.com",
    "push2.eastmoney.com",
    "82.push2.eastmoney.com",
    "1.push2.eastmoney.com",
)
_KLINE_HOSTS = ("push2his.eastmoney.com", "7.push2his.eastmoney.com")
_LIST_PATH = "/api/qt/clist/get"
_KLINE_PATH = "/api/qt/stock/kline/get"

# 东财板块列表接口单页上限就是 100（传 500 也只回 100），全量 496 需翻 5 页。
_PAGE_SIZE = "100"
_MAX_PAGES = 6
_PAGE_SLEEP = 0.25
_TIMEOUT = 12
_RETRY = 2

# 判浪样本根数：与指数口径一致（``market_prediction.get_index_history`` 取 180）。
# 取数窗口按自然日放宽到 300 天，保证扣掉节假日仍有 ≥180 根。
_KLINE_DAYS = 180
_KLINE_BEG_DAYS = 300

_LIST_TTL = 24 * 3600   # 板块名录极少变（东财调整分类才变），一天一次足够
# 翻页中途断线会拿到**残缺名录**（实测一轮只回 100/496）。残缺结果不能按一天缓存，
# 否则一次网络抖动会让几十个板块在 24 小时内全部落到 ``match="none"``。
_LIST_TTL_PARTIAL = 10 * 60
_COMPLETE_RATIO = 0.95  # 拿到 total 的 95% 以上即算拿全（翻页漂移本来就会漏几个）

_READ_TTL = 30 * 60     # 浪位是慢变量；板块指数最后一根 K 线盘中在动，30 分钟够用
# 取数/名录临时故障造成的降级**不能**按 30 分钟缓存：一次网络抖动会把「无法定位」
# 钉死半小时。这种降级只短缓存，让下一次请求有机会自愈。
_READ_TTL_DEGRADED = 120

_list_cache: tuple[float, dict[str, str], float] | None = None
_read_cache: dict[str, tuple[float, dict, float]] = {}


# ---------------------------------------------------------------- 取数


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/", "Accept": "*/*"})
    return s


def _get_json(hosts: tuple[str, ...], path: str, params: dict) -> dict:
    """在 ``hosts`` 之间轮换取 JSON；全部失败才抛错（带上前一个域名的错误便于定位）。"""
    session = _session()
    last: Exception | None = None
    for attempt in range(_RETRY + 1):
        host = hosts[attempt % len(hosts)]
        try:
            return session.get(f"https://{host}{path}", params=params, timeout=_TIMEOUT).json()
        except Exception as exc:  # noqa: BLE001 — 网络异常统一在最后一轮汇总
            last = exc
            time.sleep(0.4)
    raise RuntimeError(f"{path} 取数失败（{len(hosts)} 个域名 × {_RETRY + 1} 次）: {last}")


# ---------------------------------------------------------------- 板块名录


def _fetch_board_list() -> tuple[dict[str, str], bool]:
    """抓全量行业板块名录，返回 ``(名录, 是否拿全)``。

    排序用涨跌幅（``fid=f3``）是东财该接口的默认行为，盘中会漂移 —— 翻页时**可能**
    重复或漏项，所以「拿全」按 ``_COMPLETE_RATIO`` 判，不要求严格相等。

    中途断线时**保留已拿到的部分**而不是整块失败（漏的板块降级，不影响其它板块），
    但用第二个返回值告诉调用方：别把它当完整名录长期缓存。
    """
    out: dict[str, str] = {}
    total = 0
    for page in range(1, _MAX_PAGES + 1):
        try:
            payload = _get_json(
                _LIST_HOSTS,
                _LIST_PATH,
                {
                    "pn": str(page),
                    "pz": _PAGE_SIZE,
                    "po": "1",
                    "np": "1",
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": "2",
                    "invt": "2",
                    "fid": "f3",
                    "fs": "m:90 t:2 f:!50",
                    "fields": "f12,f14",
                },
            )
        except RuntimeError:
            if not out:
                raise
            break  # 已有部分名录可用，别让整块功能陪葬

        data = payload.get("data") or {}
        diff = data.get("diff") or []
        if not diff:
            break
        for row in diff:
            name = str(row.get("f14") or "").strip()
            code = str(row.get("f12") or "").strip()
            if name and code:
                out[name] = code
        total = data.get("total") or total
        if total and len(out) >= total:
            break
        time.sleep(_PAGE_SLEEP)
    if not out:
        raise RuntimeError("板块名录为空")
    return out, bool(total) and len(out) >= total * _COMPLETE_RATIO


def fetch_board_list() -> dict[str, str]:
    """全量行业板块名录 ``{板块名称: BK代码}``（丢掉完整度标记，便于直接调用与测试）。"""
    return _fetch_board_list()[0]


def get_board_list(force: bool = False) -> dict[str, str]:
    """带内存缓存的板块名录。

    正常情况下一天一次；**残缺名录只缓存 10 分钟** —— 这样网络恢复后最多 10 分钟
    就能自愈，而不是把几十个板块的 ``match="none"`` 钉死一整天。
    """
    global _list_cache
    now = time.time()
    if not force and _list_cache and now - _list_cache[0] < _list_cache[2]:
        return _list_cache[1]
    listing, complete = _fetch_board_list()
    _list_cache = (now, listing, _LIST_TTL if complete else _LIST_TTL_PARTIAL)
    return listing


# ---------------------------------------------------------------- 名称归一化


def _resolve(name: str, listing: dict[str, str]) -> tuple[str | None, str | None, str]:
    """把涨停池的 4 字截断板块名还原成名录里的真实板块。

    返回 ``(板块名, BK代码, 匹配方式)``；匹配不上时前两项为 ``None``。
    顺序：精确 → 前缀且候选里**名称最短**（最接近原名，避免落到 Ⅱ/Ⅲ 细分）
    → 仍在多义时**取 Ⅱ**（``hybk`` 本身用的是二级行业口径：它自己给出的
    ``中药Ⅱ`` / ``游戏Ⅱ`` / ``焦炭Ⅱ`` / ``燃气Ⅱ`` 都带 Ⅱ，所以优先 Ⅱ 不是猜的）。
    """
    key = (name or "").strip()
    if not key:
        return None, None, "none"
    if key in listing:
        return key, listing[key], "exact"

    cands = [n for n in listing if n.startswith(key)]
    if not cands:
        return None, None, "none"

    shortest = min(len(n) for n in cands)
    cands = [n for n in cands if len(n) == shortest]
    if len(cands) == 1:
        return cands[0], listing[cands[0]], "prefix"

    level2 = [n for n in cands if n.endswith("Ⅱ")]
    if len(level2) == 1:
        return level2[0], listing[level2[0]], "prefix_ii"
    return None, None, "ambiguous"


# ---------------------------------------------------------------- 板块指数日线


def _fetch_kline(code: str) -> list[dict]:
    """板块指数日线（不复权）。``code`` 形如 ``BK0481``。"""
    end = dt.date.today()
    beg = end - dt.timedelta(days=_KLINE_BEG_DAYS)
    payload = _get_json(
        _KLINE_HOSTS,
        _KLINE_PATH,
        {
            "secid": f"90.{code}",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",  # 日 K
            "fqt": "0",    # 不复权
            "beg": beg.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "smplmt": "10000",
            "lmt": "1000000",
        },
    )
    data = payload.get("data") or {}
    rows: list[dict] = []
    for line in data.get("klines") or []:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        rows.append(
            {
                "date": parts[0],
                "open": _num(parts[1]),
                "close": _num(parts[2]),
                "high": _num(parts[3]),
                "low": _num(parts[4]),
                "volume": _num(parts[5]),
            }
        )
    return rows[-_KLINE_DAYS:] if len(rows) > _KLINE_DAYS else rows


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- 对外主入口


def _result(
    sector: str,
    raw: str,
    code: str | None,
    match: str,
    wave: dict | None,
    bars: int,
    note: str,
) -> dict:
    return {
        "sector": sector,
        "raw_sector": raw,
        "code": code,
        "match": match,
        "wave": wave,
        "bars": bars,
        "degree": "日线 + 周线",
        "note": note,
    }


def analyze_mainline(sector: str) -> dict:
    """主线板块波浪定位（同步）。任何失败都降级，不抛异常。"""
    raw = (sector or "").strip()
    if not raw or raw == "—":
        return _result("—", raw, None, "none", None, 0, "当日没有形成主线板块（涨停聚集度不足），无法定位。")

    try:
        listing = get_board_list()
    except Exception as exc:  # noqa: BLE001
        return _result(raw, raw, None, "none", None, 0, f"板块名录不可用，本次无法定位：{exc}")

    name, code, how = _resolve(raw, listing)
    if not name or not code:
        detail = "名称有多个候选，无法安全归一" if how == "ambiguous" else "名录里没有对应的行业板块"
        return _result(raw, raw, None, how, None, 0, f"涨停池给的板块名「{raw}」{detail}，本次不定位。")

    try:
        bars = _fetch_kline(code)
    except Exception as exc:  # noqa: BLE001
        return _result(name, raw, code, how, None, 0, f"板块指数取数失败，本次无法定位：{exc}")
    if len(bars) < 30:
        return _result(name, raw, code, how, None, len(bars), f"板块指数仅 {len(bars)} 根 K 线，样本不足 30 根，无法定位。")

    try:
        wave = wave_service.analyze_dual(bars)
    except Exception as exc:  # noqa: BLE001 — 辅助读数不允许影响主链路
        return _result(name, raw, code, how, None, len(bars), f"波浪计算异常：{exc}")

    match_note = {
        "exact": "",
        "prefix": f"涨停池给的「{raw}」是截断名，归一为「{name}」。",
        "prefix_ii": f"涨停池给的「{raw}」是截断名，且有 Ⅱ/Ⅲ 两个候选，按二级行业口径取「{name}」。",
    }.get(how, "")
    return _result(
        name,
        raw,
        code,
        how,
        wave,
        len(bars),
        (match_note + f"{len(bars)} 根板块指数日线。") if match_note else f"{len(bars)} 根板块指数日线。",
    )


async def get_mainline_wave(sector: str) -> dict:
    """带内存缓存的主线板块浪位。

    取数是**同步** requests 调用，因此走 ``asyncio.to_thread`` —— 与
    ``market_prediction._wave_history`` 同一处理，避免阻塞事件循环。
    """
    key = sector or "—"
    now = time.time()
    hit = _read_cache.get(key)
    if hit and now - hit[0] < hit[2]:
        return hit[1]

    result = await asyncio.to_thread(analyze_mainline, sector)
    # 降级结果也要缓存：否则主线板块名对不上时会退化成每次请求都打一遍行情源。
    # 但要把两类降级分开 ——「名称对不上」是稳定结论（按 ``_READ_TTL`` 缓存），
    # 「名录/取数失败」多是临时抖动（按 ``_READ_TTL_DEGRADED`` 短缓存，留出自愈机会）。
    transient = result.get("wave") is None and result.get("match") in ("exact", "prefix", "prefix_ii")
    _read_cache[key] = (now, result, _READ_TTL_DEGRADED if transient else _READ_TTL)
    if len(_read_cache) > 16:
        for stale in sorted(_read_cache, key=lambda k: _read_cache[k][0])[:8]:
            _read_cache.pop(stale, None)
    return result
