"""跟随主力的板块（只读资金结构读数）。

## 它回答什么

「钱今天正在往哪些板块流，这些流是刚开始、还是在退潮」—— 而不是「今天谁流入最多」。

数据链：东财**板块级**资金流排行（``clist fs=m:90+t:2 fid=f62``，全量 496 行业板块，
单请求覆盖整页）→ 对横截面靠前的板块逐个拉**板块资金流日线**
（``fflow/daykline secid=90.BK####``）→ 合成持续性 / 加速度 / 结构质量 / 确认度
→ 归成四态。

## 为什么必须拉时序（这是本模块存在的理由）

只看当日横截面会给出**方向相反**的答案。实测国防军工（BK1204）：

    10-13  +19.33 亿
    10-14   -2.93 亿
    10-15  -30.69 亿

10-13 它还是当日吸筹榜前列，跟进去第二天就是两天流出 33 亿。资金流的**边际方向**
比**绝对量级**有信息量，所以「加速 / 退潮」必须靠时序差分才判得出来，
当日净额只能当其中一个输入。

## 为什么不复用 vanguard 的板块强度

``vanguard_service._sector_strength`` 是把**个股**资金流两端榜按 ``f100`` 行业字段聚合
得到的：① 样本只覆盖榜单两端，中等强度的板块系统性缺席；② 完全无时序；
③ 聚合出的板块口径与东财原生板块口径不一致（``f100`` 是三级行业）。
本模块直接用东财**原生板块**口径，避免再造一套口径再对不上。

## 口径与红线（与 wave_service / board_wave_service 一致，不得放宽）

* 读数**不进** ``evidence_score``、**不进** LLM prompt、**不产出买卖动作**；
  它是结构读数，不是信号 —— 要动作必须先定义收益口径并回测。
* **横截面分位不可跨日比较**：绝对流入量级随大盘情绪整体漂移（冰点日与亢奋日差一个
  数量级），写死绝对阈值等于每过几周悄悄失效。所以四态由分位判，代价是换日换基准，
  **这句话必须渲染到 UI 上**（见 ``Caveats`` 与前端免责区）。
* 「主力」是东财口径 = 超大单 + 大单净额，**不是真实暗盘成交**；板块级资金流本身
  是估算值（成分股按行业归类求和）。口径说明随接口一起下发。

## 取数坑（实测）

1. **push2 / push2his 是一组编号域名**（1. / 7. / 17. / 82.），会各自单独抽风 ——
   必须轮换，钉死一个域名会让整块功能在域名级抖动时全灭。
2. **板块排行单页上限 100**，全量 496 需翻页；按涨跌幅排序盘中会漂移，
   翻页可能重复或漏项，所以「拿全」按比例判（与 ``board_wave_service`` 同策略）。
3. **日线 URL 漏 ``lmt`` 会只回很短一段**；``fields2`` 必须全给，
   缺字段不报错、只会让对应分项永远 ``None``。
4. ``daykline`` 的 ``fields2`` 是**按位**解析（逗号分隔定长），少给一个字段会让后面全部错位 ——
   见 ``_parse_daily`` 里的长度守卫。
"""
from __future__ import annotations

import asyncio
import time

import requests

from app.services import board_wave_service
from app.services.concurrency import gather_limited

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 与 board_wave_service 同源：push2 / push2his 域名会各自单独抽风，轮换而非重试。
_FLOW_HOSTS = board_wave_service._LIST_HOSTS
_DAILY_HOSTS = board_wave_service._KLINE_HOSTS
_RANK_PATH = "/api/qt/clist/get"
_DAILY_PATH = "/api/qt/stock/fflow/daykline/get"

# ⚠️ f184（主力净占比）**不能漏**：漏了不报错，只是 main_pct 恒为 None，
# 结构质量维会整块失效（同一坑在 spot_service._EM_FF_FIELDS 已经踩过一次）。
# f104/f105 = 上涨家数 / 下跌家数（确认度维）；f128/f140/f136 = 领涨股及涨幅（归因展示）。
_RANK_FIELDS = "f12,f14,f3,f62,f184,f66,f69,f72,f75,f104,f105,f128,f140,f136,f207,f208"
_RANK_FS = "m:90 t:2"
_RANK_UT = "bd1d9ddb04089700cf9c27f6f7426281"

# 单页上限就是 100（传 500 也只回 100），全量 496 需翻 5 页。
_PAGE_SIZE = "100"
_MAX_PAGES = 6
_PAGE_SLEEP = 0.25
_TIMEOUT = 12
_RETRY = 2

# 时序窗口：判「持续 + 加速度」用近 5 日，只需 10 根留出节假日余量。
# 刻意**不**拉 60+ 根 —— 每根都是一次独立 HTTP 请求，496 全拉必触发风控。
_DAILY_LMT = "10"
_TREND_WINDOW = 5

# 只对横截面靠前的板块拉时序：Top N 决定「有多少条主线」，也决定请求量。
# 20 个板块 × 10 根 = 20 次请求，走 gather_limited(8) 约 3 轮完成。
_TREND_TOP_N = 20
_DISPLAY_SIZE = 12

# 排行是慢变量（盘中十几分钟不变一次量级），10 分钟够用；降级短缓存留自愈。
_RANK_TTL = 600
_TTL_DEGRADED = 120
# 端点连续失败后的实例冷却：与快照/资金流端点同源，重试只会延长 IP 封禁。
_FAIL_COOLDOWN = 180
# refresh 穿透排行的最小间隔（防连点）
_FORCE_MIN_INTERVAL = 60

_rank_cache: tuple[float, float, dict] | None = None   # (写入时刻, 有效期秒, 载荷)
_daily_cache: dict[str, tuple[float, float, list[dict] | None]] = {}  # 同上
_cooldown_until = 0.0
_last_live_at = 0.0


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Referer": "https://data.eastmoney.com/zjlx/", "Accept": "*/*"})
    return s


def _get_json(hosts: tuple[str, ...], path: str, params: dict) -> dict:
    """在 hosts 之间轮换取 JSON；全部失败才抛错。与 board_wave_service 同策略。"""
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


def _num(value) -> float | None:
    """东财用 ``"-"`` 表示缺失，必须与真实 0 区分开 —— 缺失要降级 None，不能折成 0。"""
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_rank(values: list[float], v: float) -> float:
    """v 在 values 中的横截面分位（0~1）。口径理由见模块说明。"""
    if not values:
        return 0.5
    below = sum(1 for x in values if x < v)
    equal = sum(1 for x in values if x == v)
    return (below + equal / 2) / len(values)


# ---------------------------------------------------------------- 板块资金流排行


def _rank_row(item: dict) -> dict | None:
    """东财板块排行行 → 归一化 dict。"""
    code = str(item.get("f12") or "").strip()
    name = str(item.get("f14") or "").strip()
    if not code or not name:
        return None
    row = {
        "code": code,
        "name": name,
        "change_pct": _num(item.get("f3")),
        "main_net": _num(item.get("f62")),
        "main_pct": _num(item.get("f184")),
        "super_net": _num(item.get("f66")),
        "super_pct": _num(item.get("f69")),
        "large_net": _num(item.get("f72")),
        "large_pct": _num(item.get("f75")),
        "up_count": _num(item.get("f104")),
        "down_count": _num(item.get("f105")),
        "leader_name": str(item.get("f128") or "").strip() or None,
        "leader_code": str(item.get("f140") or "").strip() or None,
        "leader_change_pct": _num(item.get("f136")),
        "laggard_name": str(item.get("f207") or "").strip() or None,
        "laggard_code": str(item.get("f208") or "").strip() or None,
    }
    # 主力净额与净占比全拿不到的行没有排序价值
    if row["main_net"] is None and row["main_pct"] is None:
        return None
    return row


def _fetch_rank() -> dict:
    """翻页抓全量板块资金流排行。

    中途断线**保留已拿到的部分**而不是整块失败（漏掉的板块降级，不影响其它板块）。
    按涨跌幅排序盘中会漂移，翻页可能重复或漏项 —— 所以按 ``_COMPLETE_RATIO`` 判完整度。
    """
    global _cooldown_until
    if time.time() < _cooldown_until:
        return {"rows": [], "available": False, "complete": False,
                "note": f"板块资金流端点冷却中（{int(_cooldown_until - time.time())}s）"}

    out: dict[str, dict] = {}
    total = 0
    for page in range(1, _MAX_PAGES + 1):
        try:
            payload = _get_json(
                _FLOW_HOSTS,
                _RANK_PATH,
                {
                    "pn": str(page),
                    "pz": _PAGE_SIZE,
                    "po": "1",
                    "np": "1",
                    "ut": _RANK_UT,
                    "fltt": "2",
                    "invt": "2",
                    "fid": "f62",
                    "fs": _RANK_FS,
                    "fields": _RANK_FIELDS,
                },
            )
        except RuntimeError as exc:
            if not out:
                _cooldown_until = time.time() + _FAIL_COOLDOWN
                return {"rows": [], "available": False, "complete": False, "note": f"板块资金流端点不可用：{exc}"}
            break  # 已有部分可用，别让整块功能陪葬

        data = payload.get("data") or {}
        diff = data.get("diff") or []
        if not diff:
            break
        for item in diff:
            row = _rank_row(item)
            if row:
                out[row["code"]] = row   # 按 code 去重：翻页漂移会产生重复项
        total = int(data.get("total") or total)
        if total and len(out) >= total:
            break
        time.sleep(_PAGE_SLEEP)

    if not out:
        _cooldown_until = time.time() + _FAIL_COOLDOWN
        return {"rows": [], "available": False, "complete": False, "note": "板块资金流排行返回空数据"}

    complete = bool(total) and len(out) >= total * board_wave_service._COMPLETE_RATIO
    rows = sorted(out.values(), key=lambda r: (r["main_net"] is None, -(r["main_net"] or 0)))
    note = ""
    if not complete:
        note = f"翻页漂移漏项，本次拿到 {len(out)}/{total} 个板块（缺失板块不参与判定）。"
    return {"rows": rows, "available": True, "complete": complete, "note": note}


async def get_rank(force: bool = False) -> dict:
    """带缓存的板块资金流排行。取数是同步 requests，走 to_thread 不阻塞事件循环。"""
    global _rank_cache, _last_live_at
    now = time.time()
    if _rank_cache:
        cached_at, ttl, cached = _rank_cache
        if not force and now - cached_at < ttl:
            return cached

    # force 节流锚点是「上一次**真实取数**」而不是「上一次 force」——
    # 只记 force 时刻会让「普通取数 → 紧跟 force」直接绕过限流，force 就成了
    # 绕过闸门的通道（与 vanguard_service._load_fund_flow 的 _fund_last_live 同口径）。
    if force and _last_live_at and now - _last_live_at < _FORCE_MIN_INTERVAL:
        return _rank_cache[2] if _rank_cache else {
            "rows": [], "available": False, "complete": False,
            "note": f"刷新间隔过短（{_FORCE_MIN_INTERVAL}s），返回上次结果",
        }

    result = await asyncio.to_thread(_fetch_rank)
    # 降级结果只短缓存 —— 否则一次网络抖动会把「端点不可用」钉死 10 分钟
    ttl = _TTL_DEGRADED if not result["available"] else _RANK_TTL
    _rank_cache = (now, ttl, result)
    if result["available"]:
        _last_live_at = now
    return result


# ---------------------------------------------------------------- 板块资金流日线


def _parse_daily(klines: list[str]) -> list[dict]:
    """东财 ``daykline`` 逐行解析。

    ``fields2`` 按位定长：``日期,主力净额,小单,中单,大单,超大单,主力占比,小单占比,
    中单占比,大单占比,超大单占比,收盘价,涨跌幅,...``（实测口径，已用
    「主力 = 大单 + 超大单」恒等式在样本上校验）。**少一位后面全部错位**，
    所以这里对长度做硬守卫，不足就整行丢弃而不是硬解。
    """
    rows: list[dict] = []
    for line in klines or []:
        parts = str(line).split(",")
        if len(parts) < 13:
            continue
        rows.append({
            "date": parts[0],
            "main_net": _num(parts[1]),
            "small_net": _num(parts[2]),
            "mid_net": _num(parts[3]),
            "large_net": _num(parts[4]),
            "super_net": _num(parts[5]),
            "main_pct": _num(parts[6]),
            "close": _num(parts[11]),
            "change_pct": _num(parts[12]),
        })
    return rows


def _fetch_daily(code: str) -> list[dict] | None:
    """单个板块的资金流日线。``code`` 形如 ``BK1204``。

    ⚠️ ``lmt`` 不能漏 —— 漏了只回很短一段（与 kline 的 ``smplmt`` 同类坑）。
    """
    payload = _get_json(
        _DAILY_HOSTS,
        _DAILY_PATH,
        {
            "secid": f"90.{code}",
            "lmt": _DAILY_LMT,
            "klt": "101",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        },
    )
    data = payload.get("data") or {}
    rows = _parse_daily(data.get("klines") or [])
    return rows or None


async def get_daily(code: str) -> list[dict] | None:
    """带缓存的板块资金流日线（异步包装）。"""
    now = time.time()
    hit = _daily_cache.get(code)
    if hit:
        cached_at, ttl, cached = hit
        if now - cached_at < ttl:
            return cached
    try:
        rows = await asyncio.to_thread(_fetch_daily, code)
    except RuntimeError:
        rows = None
    # 失败也短缓存：否则每次请求都会重打一轮失败端点，等于自造风控
    _daily_cache[code] = (now, _RANK_TTL if rows else _TTL_DEGRADED, rows)
    if len(_daily_cache) > 64:
        for stale in sorted(_daily_cache, key=lambda k: _daily_cache[k][0])[:16]:
            _daily_cache.pop(stale, None)
    return rows


# ---------------------------------------------------------------- 四态判据


def _trend_metrics(daily: list[dict]) -> dict | None:
    """从日线序列算持续性 / 加速度 / 结构质量。样本不足或当日缺数则降级 None。

    口径说明（都刻意用**占成交额/净占比**或相对自身历史的量，避免绝对量级漂移）：
      * ``main_sum_yi``  近 N 日主力净额累计（亿元）—— 持续性
      * ``main_avg_yi``  近 N 日日均净额 —— 与今日比得到加速度
      * ``accel_yi``     今日 − 日均 —— **边际方向**，本模块的核心量
      * ``super_share`` 超大单占主力净额比 —— 结构质量（主力是否靠超大单驱动）
    """
    window = daily[-_TREND_WINDOW:] if len(daily) > _TREND_WINDOW else daily
    nets = [d["main_net"] for d in window if d.get("main_net") is not None]
    if len(nets) < 3:            # 少于 3 日不判持续性 —— 节假日会让窗口更短
        return None
    today = window[-1].get("main_net")
    if today is None:
        return None

    main_sum = sum(nets)
    main_avg = main_sum / len(nets)
    super_sum = sum(d["super_net"] for d in window if d.get("super_net") is not None) if any(
        d.get("super_net") is not None for d in window
    ) else None
    return {
        "days": len(window),
        "main_sum_yi": round(main_sum / 1e8, 2),
        "main_avg_yi": round(main_avg / 1e8, 2),
        "today_yi": round(today / 1e8, 2),
        "accel_yi": round((today - main_avg) / 1e8, 2),
        "super_share": (round(super_sum / main_sum, 2) if super_sum is not None and main_sum else None),
        "latest_date": window[-1].get("date"),
        "window": [
            {"date": d.get("date"), "main_yi": round(d["main_net"] / 1e8, 2) if d.get("main_net") is not None else None}
            for d in window
        ],
    }


def _state(metrics: dict | None, main_net: float | None, accel_rank: float, cont_rank: float) -> str:
    """四态分类（follow_accel / follow_steady / follow_ebb / follow_exit）。

    判据刻意**只用时序**（持续性 + 加速度），当日净额只作兜底 —— 理由见模块说明：
    单看当日会给出方向相反的答案（实测国防军工 10-13 +19.3 亿 → 10-15 -30.7 亿）。

    四态的边界是**两张分位表的联合**：
      * 只看 ``accel_rank``（加速度分位）会让「加速流入」和「持续流入」都落在高加速度档，
        持续性完全没用上；所以 ``follow_accel`` 要求**持续性分位也在中位以上** ——
        即「本来就有人在买，且今天买得更凶」，这才是可跟随的形态。
      * ``follow_ebb`` 的判据是加速度分位落到**后 1/3**：窗口累计仍为正但边际明显转弱。
    """
    if metrics is None:
        # 时序不可用时降级到「仅当日」，并由调用方标注 trend_available=False
        if main_net is None:
            return "unknown"
        return "follow_exit" if main_net < 0 else "follow_steady"

    main_sum = metrics["main_sum_yi"]
    if main_sum <= 0:
        return "follow_exit"                     # 窗口累计已转负 = 撤离

    if accel_rank >= _ACCEL_HIGH and cont_rank >= _CONT_MID:
        return "follow_accel"                    # 持续有人在买 + 今日边际加速 = 可跟随
    if accel_rank <= _ACCEL_LOW:
        return "follow_ebb"                      # 窗口还正但边际转弱 = 退潮
    return "follow_steady"                       # 其余 = 持续流入但速度一般


# 加速度分位的高/低档阈值：0.70 / 0.30。写成分位而不是绝对金额，因为流入量级随
# 大盘情绪整体漂移（冰点日与亢奋日差一个数量级）。
_ACCEL_HIGH = 0.70
_ACCEL_LOW = 0.30
_CONT_MID = 0.50

# 展示排序：加速流入 → 持续流入 → 退潮 → 撤离 → 未知；同态内按窗口累计净额降序
STATE_ORDER = {"follow_accel": 0, "follow_steady": 1, "follow_ebb": 2, "follow_exit": 3, "unknown": 4}


STATE_META = {
    "follow_accel": {"label": "加速流入", "tone": "up", "hint": "窗口持续净流入且今日边际向上，资金正在进场。"},
    "follow_steady": {"label": "持续流入", "tone": "up", "hint": "窗口持续净流入，但边际速度已放缓。"},
    "follow_ebb": {"label": "退潮", "tone": "flat", "hint": "窗口累计仍为正，但今日边际转弱，流入正在退潮。"},
    "follow_exit": {"label": "撤离", "tone": "down", "hint": "窗口累计主力净额已转负，资金在撤离。"},
    "unknown": {"label": "—", "tone": "flat", "hint": "时序样本不足或取数失败，本次不判定。"},
}

CAVEATS = [
    "「主力」是东财口径（超大单 + 大单净额），不是真实暗盘成交数据。",
    "板块资金流为估算值（成分股按行业归类求和），与真实席位资金不同源。",
    "四态由当日横截面分位判出，换日即换基准，不可跨日比较。",
    "本模块是资金结构读数，不是买卖信号；未定义收益口径，不产出动作。",
]


# ---------------------------------------------------------------- 对外主入口


def _degraded(note: str, rank_note: str = "") -> dict:
    return {
        "sectors": [],
        "available": False,
        "complete": False,
        "total_sectors": 0,
        "ranked_sectors": 0,
        "trend_available": False,
        "state_distribution": {},
        "sample_note": "",
        "note": note,
        "rank_note": rank_note,
        "caveats": CAVEATS,
        "states": {k: v["label"] for k, v in STATE_META.items()},
    }


async def get_sector_follow(force: bool = False) -> dict:
    """跟随主力板块（主入口）。

    流程：排行（当日横截面）→ 对靠前 N 个板块并发拉日线 → 分位合成四态。
    任何一步失败都降级成结构完整的读数，**异常不外抛到路由**（辅助读数不允许影响主链路）。
    """
    try:
        rank = await get_rank(force=force)
    except Exception as exc:  # noqa: BLE001
        return _degraded(f"板块资金流排行异常：{exc}")

    rows = rank["rows"]
    if not rank["available"] or not rows:
        return _degraded(rank.get("note") or "板块资金流端点不可用，本次不判定。")

    # 时序只对横截面靠前的板块拉：Top N 既是请求量闸门，也是「有多少条主线」的答案
    picks = rows[:_TREND_TOP_N]
    codes = [r["code"] for r in picks]
    dailies = await gather_limited([get_daily(c) for c in codes], return_exceptions=True)

    metrics_by_code: dict[str, dict | None] = {}
    for code, res in zip(codes, dailies):
        if isinstance(res, Exception):
            metrics_by_code[code] = None
            continue
        try:
            metrics_by_code[code] = _trend_metrics(res or [])
        except Exception:  # noqa: BLE001 — 单板块算失败只降级该条
            metrics_by_code[code] = None

    trend_ok = [m for m in metrics_by_code.values() if m]
    # 分位在全量排行上算（不是只在 Top N 上算）—— 否则分位恒为 0.5~1.0，失去区分度
    sum_vals = [m["main_sum_yi"] for m in trend_ok]
    accel_vals = [m["accel_yi"] for m in trend_ok]

    out: list[dict] = []
    for row in picks:
        code = row["code"]
        m = metrics_by_code.get(code)
        main_net = row.get("main_net")
        cont_rank = _pct_rank(sum_vals, m["main_sum_yi"]) if m else 0.5
        accel_rank = _pct_rank(accel_vals, m["accel_yi"]) if m else 0.5
        state = _state(m, main_net, accel_rank, cont_rank)

        up = row.get("up_count")
        down = row.get("down_count")
        breadth = (up / (up + down)) if up is not None and down is not None and (up + down) > 0 else None
        meta = STATE_META[state]
        out.append({
            "code": code,
            "name": row["name"],
            "state": state,
            "state_label": meta["label"],
            "state_hint": meta["hint"],
            "change_pct": row.get("change_pct"),
            "main_net_yi": round(main_net / 1e8, 2) if main_net is not None else None,
            "main_pct": row.get("main_pct"),
            "super_pct": row.get("super_pct"),
            "large_pct": row.get("large_pct"),
            "up_count": up,
            "down_count": down,
            "breadth": round(breadth, 3) if breadth is not None else None,
            "leader_name": row.get("leader_name"),
            "leader_code": row.get("leader_code"),
            "leader_change_pct": row.get("leader_change_pct"),
            "laggard_name": row.get("laggard_name"),
            "laggard_code": row.get("laggard_code"),
            "trend_available": m is not None,
            "trend": m,
            "ranks": {
                "continuity": round(cont_rank, 3),
                "acceleration": round(accel_rank, 3),
                "structure": row.get("super_pct"),
            },
        })

    out.sort(key=lambda r: (STATE_ORDER.get(r["state"], 99), -(r["trend"] or {}).get("main_sum_yi", -1e9)))

    shown = out[:_DISPLAY_SIZE]
    dist: dict[str, int] = {}
    for r in out:                      # 按**参与判定的全量**统计，不是只统计展示的 12 条
        dist[r["state_label"]] = dist.get(r["state_label"], 0) + 1

    return {
        "sectors": shown,
        "available": True,
        "complete": bool(rank["complete"]),
        "total_sectors": len(rows),
        "ranked_sectors": len(out),
        "trend_available": bool(trend_ok),
        # 取样口径必须下发：这批是「当日主力净流入」的前 N 名，天然以流入为主，
        # 所以「撤离」占比天然偏高。不说清楚会被读成「全市场都在撤离」。
        "sample_note": (
            f"时序取样为当日主力净流入前 {len(out)} 名（横截面共 {len(rows)} 个板块）。"
            "该样本天然偏向流入端，因此「撤离」占比偏高属预期，不代表全市场资金状况。"
        ),
        "state_distribution": dist,
        "note": rank.get("note") or "",
        "rank_note": rank.get("note") or "",
        "caveats": CAVEATS,
        "states": {k: v["label"] for k, v in STATE_META.items()},
        "source": "东财 clist 板块资金流排行（fs=m:90+t:2 fid=f62，翻页取全量）+ fflow/daykline 板块资金流日线",
    }