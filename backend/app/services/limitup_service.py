"""连板梯队与板块聚集度：追连板「鱼腹」的观察层。

## 为什么单独开一条数据链路

现有全市场快照走 ``push2.eastmoney.com``（60 页分页，IP 级风控高危，见 ``spot_service``）。
连板数据来自 ``push2ex.eastmoney.com`` 的**涨停板池**业务端点，性质完全不同：

* **单次请求**返回全市场涨停池（一日约 40~90 只），比全市场快照少两个数量级；
* 直接带 ``lbc``（连板数）与 ``hybk``（所属板块），不必按 code 逐只回捞历史 K 线；
* 域名与 push2 相互独立 —— push2 被风控时本模块仍然可用。

``date=YYYYMMDD`` 支持回溯，于是晋级率回测**只需要涨停池本身**：把 D 日与 D+1 日的池子按
code 取交集，看 ``lbc`` 是否恰好 +1，即可得到晋级率，**零额外行情请求**。

⚠️ 但回溯窗口很短：实测 2026-08-27 及以前一律返回**空池**，只有最近约 15 个交易日有数据
（见 ``MAX_RELAY_DAYS``）。因此本模块的统计结论天然受限于 3 周窗口，且**空池必须与
「当天真的没有涨停」区分**——否则不同 ``days`` 会返回完全相同的统计量而不自知。

## 这一层只做「观察」，不做「买点」

连板接力的有效性尚未通过回测（见 ``tactic_evidence``），因此：

* 本模块不输出任何买卖动作，只输出客观的封板质量与位置描述；
* 该策略的证据等级（tier）由 ``relay_backtest`` 跑出的真实数字决定，**不允许人工拔高**；
* 前端展示必须带口径说明（``calibers.limitup_relay``）。

「鱼腹」在本模块的对应物是**位置分桶**（启动 / 加速 / 中继 / 高位 / 分歧）——
它是统计意义上的分组，不是建议。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time

import requests

from app.services import calibers, cache_utils, concurrency, tactic_evidence, trade_calendar_service

try:  # supabase 未配置时落库/读回静默降级，不影响实时链路
    from app.services import supabase_store
except Exception:  # pragma: no cover
    supabase_store = None

_BASE = "https://push2ex.eastmoney.com"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT = 12

# 涨停板池各业务端点。字段差异见 normalize_* / normalize_broken。
_POOL_KIND = {
    "zt": "getTopicZTPool",  # 涨停板池：带 lbc 连板数、fbt 首封时间
    "zb": "getTopicZBPool",  # 炸板池：带 ztp 涨停价、zf 振幅，无 lbc
}

_UT = "7eea3edcaed734bea9cbfc24409ed989"
_DPT = "wz.ztzt"

_PAGE_SIZE = 500
_MAX_PAGES = 4
_PAGE_SLEEP = 0.15

# 全市场股票数（沪深京 A 股），用于把「次日涨停率」换算成随机基线。
# 注意方向：分母取偏大值会让基线偏小、结论偏宽松；这里取 5400 接近真实规模，
# 且真实晋级率与基线相差两个数量级（数十 % vs 不到 1 %），取值误差不影响定性结论。
_MARKET_UNIVERSE = 5400

_SNAP_TTL = 60           # 盘中最短短缓存：涨停池在盘中持续变化
_SNAP_CACHE_MAX = 8
_SNAP_CACHE: dict[str, tuple[float, dict]] = {}

_RELAY_TTL = 6 * 3600    # 晋级率只依赖已收盘交易日，半天内不会变
_RELAY_CACHE: dict[str, tuple[float, dict]] = {}

# 东财涨停池的历史回溯上限：实测 2026-08-27 及以前返回空池，08-28 起才有数据，
# 即**只覆盖最近约 15 个交易日（3 周）**。回测默认就取这个窗口 —— 取更大值只会
# 白白多打十几次必然返回空池的请求，统计量不会有任何变化（这个坑实测踩过）。
MAX_RELAY_DAYS = 15


# ---------- 每日落库（解决 15 交易日回溯上限） ----------
#
# 为什么必须落库：涨停池接口对更早日期一律返回空池，relay_backtest 的样本窗口
# 永远只有 ~3 周，且**不会随时间变长** —— 昨天跑是 08-28~09-16，明天跑还是只剩
# 最近 15 天，更早的样本永久丢失。每天收盘后把当日池子写进 Supabase，
# 回测读路径优先用累积表补齐窗口外样本：跑得越久，可回测窗口越长。
#
# 表未建 / Supabase 未配置时**全部静默降级**（与 market_source_state 同一策略）：
# 实时快照与现有 relay_backtest 完全不受影响。

# 落库字段 = normalize_limit_up 输出的子集（不含派生的 position 等展示字段）。
_SNAPSHOT_COLUMNS = (
    "code", "name", "boards", "sector", "seal_time", "last_seal_time",
    "break_count", "seal_fund_yi", "float_mv_yi", "seal_ratio", "turnover",
    "amount_yi", "price", "change_pct", "stat_days", "stat_boards",
)


def _snapshot_rows(trade_date: str, stocks: list[dict]) -> list[dict]:
    """当日全景里的涨停股 → 落库行（trade_date 冗余进每行，UNIQUE 去重键）。"""
    text_cols = {"name", "sector", "seal_time", "last_seal_time"}
    rows = []
    for t in stocks:
        if not t.get("code"):
            continue
        row = {"trade_date": trade_date}
        for col in _SNAPSHOT_COLUMNS:
            v = t.get(col)
            if v is None:
                v = "" if col in text_cols else 0
            row[col] = v
        rows.append(row)
    return rows


async def save_daily_snapshot(trade_date: str | None = None, stocks: list[dict] | None = None) -> int:
    """把某日涨停池写入 limitup_daily_snapshot（幂等，重复写自动跳过已有行）。

    默认落**当日**快照：盘中调用时池子还在变，只写不删 —— 以 UNIQUE(trade_date, code)
    冲突跳过，收盘后由 cron 再跑一次拿最终状态。直接传 ``stocks`` 时（如从
    ``get_snapshot`` 结果回填）用传入数据，否则拉当日池子。

    返回新写入行数；Supabase 未配置 / 表未建时返回 0（静默降级，不抛异常）。
    """
    if supabase_store is None or not supabase_store.is_configured():
        return 0
    date_key = trade_date or trade_calendar_service.now_cn().date().isoformat()
    try:
        if stocks is None:
            raw = await asyncio.to_thread(_fetch_pool_sync, "zt", date_key.replace("-", ""))
            stocks = [normalize_limit_up(x) for x in raw]
        rows = _snapshot_rows(date_key, stocks)
        if not rows:
            return 0
        sb = await supabase_store.get_service_client()
        # upsert on UNIQUE(trade_date, code)：盘中重复写自动覆盖为最新状态
        res = await (
            sb.table("limitup_daily_snapshot")
            .upsert(rows, on_conflict="trade_date,code")
            .execute()
        )
        return len(res.data or [])
    except Exception as e:
        # 表未建是预期内降级（需执行 v10 迁移）；其他异常同样只记录，不拖垮调用方
        print(f"[limitup] 每日快照落库失败({date_key}): {e}")
        return 0


# 累积表扫描上限：一个交易日 60~90 只涨停，5000 行够覆盖约 50 个交易日。
# 观察期是按周计的，先取全量去重比逐日 count 便宜；超出后改用 range 分页。
_ACCUMULATED_SCAN_LIMIT = 5000


async def accumulated_stats() -> dict:
    """累积表的观察期进度：已落库多少个交易日 / 多少行 / 起止日期。

    涨停池接口只回溯约 15 个交易日，样本窗口永远 3 周且不会随时间变长 ——
    每日落库（v10）就是为此把窗口自积累起来。这个读数让「观察到第几天了」
    可被直接看到，而不是靠猜（此前 accumulated_days 一直是 0，很容易被误判成迁移没生效）。

    Supabase 未配置 / 表未建 → 返回 configured=False + days=0（静默降级，不抛）。
    """
    empty = {"configured": False, "days": 0, "rows": 0, "first_date": None, "last_date": None}
    if supabase_store is None or not supabase_store.is_configured():
        return empty
    try:
        sb = await supabase_store.get_service_client()
        res = await sb.table("limitup_daily_snapshot").select("trade_date").limit(_ACCUMULATED_SCAN_LIMIT).execute()
        rows = res.data or []
        dates = {r["trade_date"] for r in rows if r.get("trade_date")}
        return {
            "configured": True,
            "days": len(dates),
            "rows": len(rows),
            "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
        }
    except Exception as e:
        print(f"[limitup] 累积表统计失败: {e}")
        return {**empty, "configured": True}


async def load_accumulated_snapshots(start_date: str, end_date: str) -> dict[str, list[dict]]:
    """读取 [start_date, end_date] 内已落库的涨停池（trade_date -> normalize 后的 stocks）。

    供 relay_backtest 补齐接口回溯窗口外的样本：本地窗口 + 累积表 = 更长回测窗口。
    表未建 / 无数据返回空 dict，调用方按「没有累积样本」处理。
    """
    if supabase_store is None or not supabase_store.is_configured():
        return {}
    try:
        sb = await supabase_store.get_service_client()
        res = (
            await sb.table("limitup_daily_snapshot")
            .select("*")
            .gte("trade_date", start_date)
            .lte("trade_date", end_date)
            .order("trade_date", desc=False)
            .execute()
        )
        out: dict[str, list[dict]] = {}
        for row in (res.data or []):
            out.setdefault(str(row["trade_date"]), []).append(row)
        return out
    except Exception as e:
        print(f"[limitup] 累积快照读取失败({start_date}~{end_date}): {e}")
        return {}


# ---------- 抓取 ----------


def _fetch_pool_sync(kind: str, date_str: str) -> list[dict]:
    """同步抓取某一天的某个池子，返回原始记录列表（未规范化）。

    空池（``tc = 0``）是合法返回值，不抛异常；只有整体失败才抛 ``RuntimeError``。
    """
    endpoint = _POOL_KIND[kind]
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": _UA,
            "Accept": "*/*",
            "Referer": "https://quote.eastmoney.com/",
            "Connection": "keep-alive",
        }
    )
    out: list[dict] = []
    last_error: Exception | None = None
    for page in range(_MAX_PAGES):
        params = {
            "ut": _UT,
            "dpt": _DPT,
            "Pageindex": str(page),
            "pagesize": str(_PAGE_SIZE),
            "sort": "fbt:asc",
            "date": date_str,
        }
        try:
            resp = session.get(f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT)
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - 网络/解析异常统一降级或上抛
            last_error = exc
            break
        data = payload.get("data") or {}
        pool = data.get("pool") or []
        total = data.get("tc")
        out.extend(pool)
        if not pool:
            break
        if isinstance(total, int) and len(out) >= total:
            break
        time.sleep(_PAGE_SLEEP)
    if not out and last_error is not None:
        raise RuntimeError(f"涨停板池请求失败({kind}/{date_str}): {last_error}")
    return out


# ---------- 规范化（单位统一为 元 / 亿元 / %） ----------


def _num(value, default: float = 0.0) -> float:
    """东财缺值可能是 None / '' / '-'。"""
    try:
        if value is None or value == "" or value == "-":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_time(raw) -> str:
    """封板时间是 HHMMSS 整数（``92500`` = 09:25:00），补零到 6 位再切分。"""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    s = str(v).zfill(6)
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"


def normalize_limit_up(item: dict) -> dict:
    """涨停池单条 → 内部结构。

    价格单位是「厘」（``p = 37000`` 即 37.00 元），必须除 1000；
    市值与封单资金单位是元，换算成亿元便于展示。
    """
    stat = item.get("zttj") or {}
    seal_fund = _num(item.get("fund"))
    float_mv = _num(item.get("ltsz"))
    return {
        "code": str(item.get("c") or "").strip(),
        "name": str(item.get("n") or "").strip(),
        "price": round(_num(item.get("p")) / 1000.0, 2),
        "change_pct": round(_num(item.get("zdp")), 2),
        "boards": int(_num(item.get("lbc"))),
        "seal_time": _fmt_time(item.get("fbt")),
        "last_seal_time": _fmt_time(item.get("lbt")),
        "break_count": int(_num(item.get("zbc"))),
        "seal_fund_yi": round(seal_fund / 1e8, 3),
        "float_mv_yi": round(float_mv / 1e8, 2),
        "turnover": round(_num(item.get("hs")), 2),
        "amount_yi": round(_num(item.get("amount")) / 1e8, 3),
        "sector": str(item.get("hybk") or "").strip() or "其他",
        "stat_days": int(_num(stat.get("days"))),
        "stat_boards": int(_num(stat.get("ct"))),
        # 封单占流通市值比（%）：衡量封板强度。大市值股 1% 已属强势，
        # 小盘股需要更高比例才算封得结实，所以它只能横向比、不能跨市值硬套。
        "seal_ratio": round(seal_fund / float_mv * 100, 3) if float_mv > 0 else 0.0,
    }


def normalize_broken(item: dict) -> dict:
    """炸板池单条 → 内部结构（该池没有连板数字段）。"""
    return {
        "code": str(item.get("c") or "").strip(),
        "name": str(item.get("n") or "").strip(),
        "price": round(_num(item.get("p")) / 1000.0, 2),
        "change_pct": round(_num(item.get("zdp")), 2),
        "limit_price": round(_num(item.get("ztp")) / 1000.0, 2),
        "break_count": int(_num(item.get("zbc"))),
        "amplitude": round(_num(item.get("zf")), 2),
        "sector": str(item.get("hybk") or "").strip() or "其他",
    }


# ---------- 聚合 ----------

# 连板高度分桶上限：6 及以上合并为「6板+」，避免出现 count=1 的长尾桶稀释统计。
_LADDER_CAP = 6


def ladder_label(boards: int) -> str:
    if boards <= 1:
        return "首板"
    if boards >= _LADDER_CAP:
        return f"{_LADDER_CAP}板+"
    return f"{boards}板"


def build_ladder(items: list[dict]) -> list[dict]:
    """按连板高度分组，从高到低；组内按首封时间升序（越早封板越靠前）。"""
    buckets: dict[int, list[dict]] = {}
    for it in items:
        key = min(max(it["boards"], 1), _LADDER_CAP)
        buckets.setdefault(key, []).append(it)
    out = []
    for key in sorted(buckets, reverse=True):
        rows = sorted(buckets[key], key=lambda x: x["seal_time"] or "99:99:99")
        out.append(
            {
                "key": key,
                "label": ladder_label(key),
                "count": len(rows),
                "items": rows,
            }
        )
    return out


def build_sectors(items: list[dict], limit: int = 8) -> list[dict]:
    """按所属板块聚合，用于识别「主线」。

    排序主键是板块内涨停家数 —— 家数比封单金额更能反映资金是否在这个板块里抱团。
    """
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it["sector"], []).append(it)

    out = []
    for sector, rows in groups.items():
        relay = [r for r in rows if r["boards"] >= 2]
        out.append(
            {
                "sector": sector,
                "count": len(rows),
                "relay_count": len(relay),
                "max_boards": max(r["boards"] for r in rows),
                "seal_fund_yi": round(sum(r["seal_fund_yi"] for r in rows), 2),
                "avg_turnover": round(sum(r["turnover"] for r in rows) / len(rows), 2),
                "codes": [r["code"] for r in rows],
                "names": [r["name"] for r in rows],
            }
        )
    out.sort(key=lambda x: (x["count"], x["max_boards"], x["seal_fund_yi"]), reverse=True)
    return out[:limit]


def build_sentiment(limit_up: list[dict], broken: list[dict]) -> dict:
    """当日情绪温度：涨停家数 / 炸板率 / 最高板 / 连板家数。

    炸板率 = 炸板家数 ÷ (涨停家数 + 炸板家数)。分母用「曾涨停过的家数」，
    而不是当日涨停家数，否则盘中炸板多、涨停少时该比值会突破 100%。
    """
    lu = len(limit_up)
    zb = len(broken)
    denom = lu + zb
    relay = [t for t in limit_up if t["boards"] >= 2]
    return {
        "limit_up_count": lu,
        "broken_count": zb,
        "break_rate": round(zb / denom * 100, 1) if denom else 0.0,
        "max_boards": max((t["boards"] for t in limit_up), default=0),
        "relay_count": len(relay),
        "first_board_count": lu - len(relay),
        "intact_count": sum(1 for t in limit_up if t["break_count"] == 0),
    }


# 情绪分级只做「当日横向」描述。之所以不写「历史高位 / 冰点」，是因为这里没有历史分位数据，
# 用分位口径的词会让读者以为做了统计比较 —— 那正是本项目反复出现的可信度越界。
def sentiment_note(s: dict) -> dict:
    rate = s["break_rate"]
    top = s["max_boards"]
    if rate >= 40:
        tone, text = "warn", "炸板率偏高，接力分歧加大"
    elif rate <= 20 and top >= 4:
        tone, text = "good", "封板扎实、高度尚在，接力相对顺畅"
    elif top == 0:
        tone, text = "neutral", "暂无涨停，情绪偏冷"
    else:
        tone, text = "neutral", "封板与炸板相对均衡"
    return {"tone": tone, "text": text}


# ---------- 操作建议（三档） ----------
#
# ⚠️ 证据纪律：这份建议只基于**已经回测过的口径**：
#   - 炸板率与封板成功的关系（当日横截面，随时可得）
#   - 板块聚集度对晋级率的影响（limitup_relay 回测：≥5 家 9.2% vs 1-2 家 18.8%，方向为负）
#   - 梯队结构断层（2-4 板晋级率 33~40% 显著高于首板 16.3% —— 「鱼腹」位置）
# 连板接力整体证据等级仍是 preliminary（见 tactic_evidence.STRATEGY_EVIDENCE），
# 因此结论措辞是「环境适不适合打板」，而不是「哪只票会涨」——前者是统计观察，后者是荐股越界。

# 打板环境判定阈值。改这里必须同步改 test_limitup_service.py 的 PlayAdviceTests。
_BREAK_RATE_GOOD = 25.0   # 炸板率低于此 → 封板扎实
_BREAK_RATE_BAD = 35.0    # 炸板率高于此 → 分歧过大
_MIN_MAINLINE = 4         # 同板块涨停 ≥ 此数 → 有主线（回测中 ≥5 家晋级率反而在降，4 家是保守下沿）


def ladder_gaps(ladder: list[dict]) -> list[int]:
    """梯队断层检测：首板与最高板之间出现 count=0 的档位。

    与前端 ``limitUpLogic.ladderGaps`` 语义一致（2 ~ top-1 之间缺档），
    但这里有原始 boards 数据，直接用真实高度、不受 6 板+ 分桶截断影响。
    例：5板1只、4板0只、3板1只 → 断层 = [4]。
    """
    counts = {g["key"]: g["count"] for g in ladder}
    if not counts:
        return []
    top = max(counts)
    # 纯首板行情（只有 1 档）谈不上断层
    if top <= 1:
        return []
    # 补齐首板~最高板之间缺失的档位（build_ladder 只输出非空组）
    return [b for b in range(2, top) if counts.get(b, 0) == 0]


def play_advice(sentiment: dict, ladder: list[dict], sectors: list[dict]) -> dict:
    """今日操作建议：可打板 / 只看不动手 / 空仓等待 三档。

    判定顺序（从否决到放宽）：
    1. 炸板率过高 → 分歧太大，接力亏钱概率占优（当日横截面口径）
    2. 梯队断层 → 高度接力无承接，追高容易接最后一棒
    3. 无主线板块 → 资金没形成合力，「追最热」在回测里反而晋级率更低
    4. 以上都过关 → 环境相对友好，但仍强调选 2-4 板的「鱼腹」段，不追孤岛高位
    """
    rate = sentiment["break_rate"]
    relay = sentiment["relay_count"]
    gaps = ladder_gaps(ladder)
    top_sector = sectors[0] if sectors else None
    mainline_count = top_sector["count"] if top_sector else 0
    mainline_name = top_sector["sector"] if top_sector else "—"
    max_boards = sentiment["max_boards"]

    reasons: list[str] = []
    if sentiment["limit_up_count"] == 0:
        return {
            "level": "avoid",
            "title": "空仓等待",
            "reasons": ["全市场没有涨停，情绪冰点，无从接力"],
            "gaps": gaps,
            "mainline": mainline_name,
        }
    if relay == 0:
        # 有涨停但全是首板：梯队尚未形成，谈不上「追连板」，但也不是冰点 —— 放 watch。
        return {
            "level": "watch",
            "title": "只看不动手",
            "reasons": [f"今日 {sentiment['limit_up_count']} 家全部为首板，鱼腹（2-4 板梯队）尚未形成，明天才看得到晋级分化"],
            "gaps": gaps,
            "mainline": mainline_name,
        }
    if rate >= _BREAK_RATE_BAD:
        reasons.append(f"炸板率 {rate}% ≥ {_BREAK_RATE_BAD}%，分歧过大")
    if gaps:
        reasons.append(f"梯队断层 {gaps} 板档位空缺，高度无承接")
    if mainline_count < _MIN_MAINLINE:
        reasons.append(f"最热板块仅 {mainline_count} 家（{mainline_name}），资金无合力")
    if reasons:
        return {
            "level": "avoid",
            "title": "空仓等待",
            "reasons": reasons,
            "gaps": gaps,
            "mainline": mainline_name,
        }

    if rate >= _BREAK_RATE_GOOD or max_boards <= 1:
        return {
            "level": "watch",
            "title": "只看不动手",
            "reasons": [
                f"炸板率 {rate}% 处于中性区间，接力盈亏比一般" if rate >= _BREAK_RATE_GOOD else "市场只有首板，鱼腹尚未形成"
            ],
            "gaps": gaps,
            "mainline": mainline_name,
        }

    return {
        "level": "hunt",
        "title": "可打板",
        "reasons": [
            f"炸板率 {rate}% 封板扎实",
            f"梯队完整（最高 {max_boards} 板，无断层）",
            f"主线 {mainline_name}（{mainline_count} 家涨停）",
        ],
        "gaps": gaps,
        "mainline": mainline_name,
    }


# ---------- 连板资金面评分（明日晋级概率） ----------
#
# ⚠️ 口径先行（calibers.limitup_relay 的延伸观察，2026-09-17 用 08-28~09-16 涨停池回测算出）：
#   连板股样本 n=164（晋级 55 / 未晋级 109），三个资金面因子都有单调区分度：
#     - 封单/流通 ≥2% → 晋级率 44.7%（vs <0.5% 档 17.6%）；分箱: <0.5:17.6 / 0.5-1:20.0 / 1-2:26.1 / 2-5:44.7 / ≥5:63.2
#     - 换手 <5%      → 晋级率 44.8%（vs ≥30% 档 0%）；分箱: <5:44.8 / 5-15:36.1 / 15-30:18.9 / ≥30:0.0
#     - 炸板 0 次     → 晋级率 44.6%（vs ≥1 次 22.6~23.1%）
#   三因子合成 0-3 分后与晋级率单调：11.8% / 26.2% / 34.2% / 54.0%；
#   且控制连板高度后区分度仍在（2板: 17.4% vs 41.8%；3板+: 24.1% vs 53.1%）。
#   ⚠️ 样本窗口只有 ~13 个交易日（涨停池回溯上限），是「封板延续率」不是收益率，
#   数字随行情阶段波动，必须当**相对强弱读数**用，不当绝对概率承诺。

# 因子阈值。改这里必须同步改 test_limitup_service.py 的 RelayScoreTests 与上方注释数字。
_SEAL_RATIO_HIT = 2.0     # 封单/流通 ≥ 此值 → +1 分
_TURNOVER_HIT = 15.0      # 换手 < 此值 → +1 分
_BREAK_FREE = 1           # 炸板次数 < 此值（即 0 次）→ +1 分

# 得分 → 回测晋级率（%）。索引即得分。
_SCORE_RATE = [11.8, 26.2, 34.2, 54.0]
_SCORE_RATE_N = [34, 42, 38, 50]  # 各得分档样本量，前端展示用

# 得分 → 相对强弱分层。解决的是「3/3 分 · 54%」这种数字用户读不懂的问题：
# 把三档合成一个直观的分层标签。措辞纪律：分层是**相对强弱描述**，
# 不含动作词（买/进/关注），"强/中/弱"只是统计分组命名。
_TIER_BY_SCORE = {
    3: {"tier": 1, "tier_label": "资金面最强", "tier_note": "三因子全达标：封单厚、换手低、全天未开板"},
    2: {"tier": 2, "tier_label": "资金面较强", "tier_note": "两项达标，一项欠缺（通常是盘中开过板）"},
    1: {"tier": 3, "tier_label": "资金面偏弱", "tier_note": "只一项达标，封板质量有明显短板"},
    0: {"tier": 3, "tier_label": "资金面最弱", "tier_note": "三项全不达标，封板质量最差"},
}


def relay_score(stock: dict) -> dict:
    """单只连板股的资金面持续性评分（0-3）与明日晋级概率读数。

    三因子各 1 分：封单/流通、换手、炸板次数 —— 都能从涨停池单条直接拿到，
    不发额外行情请求（资金流向类接口逐股请求是风控主因，刻意绕开）。
    """
    factors = [
        {
            "name": "封单/流通",
            "value": stock["seal_ratio"],
            "hit": stock["seal_ratio"] >= _SEAL_RATIO_HIT,
            "rule": f"≥{_SEAL_RATIO_HIT}% 记 1 分（回测：≥2% 档晋级率 44.7% vs <0.5% 档 17.6%）",
        },
        {
            "name": "换手率",
            "value": stock["turnover"],
            "hit": stock["turnover"] < _TURNOVER_HIT,
            "rule": f"<{_TURNOVER_HIT}% 记 1 分（回测：<5% 档 44.8% vs ≥30% 档 0%）",
        },
        {
            "name": "炸板次数",
            "value": stock["break_count"],
            "hit": stock["break_count"] < _BREAK_FREE,
            "rule": "全天 0 次开板记 1 分（回测：0 次档 44.6% vs ≥1 次档 ~23%）",
        },
    ]
    score = sum(1 for f in factors if f["hit"])
    return {
        "score": score,
        "max_score": len(factors),
        "rate": _SCORE_RATE[score],
        "rate_n": _SCORE_RATE_N[score],
        "factors": factors,
        **_TIER_BY_SCORE[score],
    }


def build_relay_stocks(stocks: list[dict]) -> list[dict]:
    """从当日全景里抽出连板股（boards ≥2），挂上资金面评分，按概率降序。

    「抽离」的意义：梯队视图按高度分组看的是**结构**，这里按个股看的是**各自还接不接得动**。
    """
    relays = [t for t in stocks if t["boards"] >= 2]
    out = []
    for t in relays:
        sc = relay_score(t)
        out.append(
            {
                "code": t["code"],
                "name": t["name"],
                "boards": t["boards"],
                "sector": t["sector"],
                "seal_time": t["seal_time"],
                "seal_fund_yi": t["seal_fund_yi"],
                "seal_ratio": t["seal_ratio"],
                "turnover": t["turnover"],
                "break_count": t["break_count"],
                **sc,
            }
        )
    out.sort(key=lambda x: (-x["score"], -x["boards"], x["seal_time"] or "99:99:99"))
    return out


def relay_tier_summary(relay_stocks: list[dict]) -> dict:
    """资金面分层一览：给「哪个可以碰」一个**统计分组层面**的直接回答。

    用户看不懂「3/3 分 · 54%」意味着什么 —— 这层把当日连板股按得分聚合成三组，
    每组给一句人话概括（谁在里面、历史晋级读数多少）。措辞纪律：
    分层名是强弱描述不是动作指令；summary 里不出现个股「买/进」话术。
    """
    if not relay_stocks:
        return {"groups": [], "headline": "今日无连板股，无分层可言"}
    groups: dict[int, list[dict]] = {}
    for r in relay_stocks:
        groups.setdefault(r["tier"], []).append(r)

    tier_defs = [
        (1, "资金面最强", "三因子全达标（封单厚 / 换手低 / 未开板），历史同档晋级读数最高"),
        (2, "资金面较强", "两项达标，通常差在盘中开过板"),
        (3, "资金面偏弱", "至多一项达标，封板质量有短板，相对风险最高"),
    ]
    out_groups = []
    for tier, label, desc in tier_defs:
        members = groups.get(tier) or []
        if not members:
            continue
        out_groups.append(
            {
                "tier": tier,
                "label": label,
                "desc": desc,
                "rate": members[0]["rate"],
                "rate_n": members[0]["rate_n"],
                "codes": [m["code"] for m in members],
                "names": [m["name"] for m in members],
            }
        )

    top = out_groups[0] if out_groups else None
    headline = (
        f"今日 {len(relay_stocks)} 只连板股中，{top['names'][0]}等 {len(top['names'])} 只资金面最强"
        f"（历史同档明日晋级读数 {top['rate']}%）。"
        "这是相对强弱分组，不是买入指令 —— 晋级了也常一字板买不进。"
        if top
        else "今日无连板股"
    )
    return {"groups": out_groups, "headline": headline}


def position_tag(item: dict) -> dict:
    """位置分桶 —— 「鱼腹」所在的段位。

    ⚠️ 这是**统计分桶，不是建议**。连板接力尚未通过回测（见 ``tactic_evidence``），
    因此这里只描述「处在哪个位置」，绝不含任何动作词。
    """
    b = item["boards"]
    if b <= 1:
        return {"tag": "启动", "reason": "首板，尚未形成连板"}
    if b >= 5:
        return {"tag": "高位", "reason": f"{b} 连板，位置偏高、波动放大"}
    if item["break_count"] >= 3:
        return {"tag": "分歧", "reason": f"{b} 连板，盘中反复开板 {item['break_count']} 次"}
    if b >= 4:
        return {"tag": "中继", "reason": f"{b} 连板，进入中继段"}
    return {"tag": "加速", "reason": f"{b} 连板，处于加速段"}


# ---------- 次日溢价读数（打板方向） ----------
# 口径 `limitup_premium`：买入 = D 日涨停价（= 收盘价），卖出 = D+1 集合竞价开盘。
# D 买 D+1 卖满足 T+1，不涉及违规动作。
#
# 数据来源（2026-09-18 实测，两口径互证）：
#   · 涨停池口径：东财池真实封板字段，14 个交易日 / n=758，期望 +2.00% / 中位 +1.27%
#   · 日 K 口径：548 只 × 250 交易日 / n=4953，期望 +1.91% / 中位 +1.16% / 胜率 61.7%
#   · 非涨停日对照 n=10694：期望 −0.06% —— 「涨停」这个条件本身贡献约 2 个百分点
#   · 13/13 个月正期望；打平需胜率 35.3%，实际 51.4%（盈亏比结构健康）
#
# ⚠️ 核心事实：**收益大头落在买不进的档**。换手率越高期望越低（单调），
#    而缩量一字/秒板恰恰挂不上单。所以读数必须同时给「期望」和「可成交性」——
#    只报期望会诱导去追根本买不到的一字板。
#
# ⚠️ 证据等级 preliminary：可成交性是**代理指标**（池快照没有量比字段，用换手率替代），
#    不是实测成交率。因此读数不含动作词，且 `executable` 恒 False（不进买卖点位置）。
_TURNOVER_BUCKETS: tuple[tuple[str, float, float, str, bool], ...] = (
    # (档位标签, 上界, 历史期望 %, 说明, 可成交性)
    ("<5%", 5.0, 3.31, "缩量一字/秒板：历史期望最高，但多数挂不上单", False),
    ("5-15%", 15.0, 1.62, "换手温和：可成交性较好，溢价居中", True),
    ("15-30%", 30.0, 1.10, "换手偏高：可成交，溢价收窄", True),
    ("≥30%", float("inf"), 0.40, "巨量换手：溢价最薄", True),
)

_SEAL_BUCKETS: tuple[tuple[str, float, str, bool], ...] = (
    # (上界 HH:MM, 历史期望 %, 说明, 是否负期望档)
    ("09:35", 3.67, "早盘封板（≤09:35）：期望最高的一档", False),
    ("10:00", 1.56, "09:35–10:00 封板", False),
    ("11:30", 1.67, "10:00–11:30 封板", False),
    ("14:00", 1.17, "13:00–14:00 封板", False),
    ("23:59", -0.48, "尾盘封板（≥14:00）：唯一负期望档（胜率 37.8%）", True),
)


def _turnover_readout(turnover: float) -> tuple[str, float, str, bool]:
    for label, upper, expect, note, tradable in _TURNOVER_BUCKETS:
        if turnover < upper:
            return label, expect, note, tradable
    last = _TURNOVER_BUCKETS[-1]  # 兜底不可达（最后一档上界为 inf），仅为类型完整
    return last[0], last[2], last[3], last[4]


def _seal_readout(seal_time: str | None) -> tuple[float | None, str, bool]:
    """首封时间 → (期望 %, 说明, 是否负期望档)。seal_time 形如 `09:35:12`。

    比较精确到秒（`09:35:00` 属早盘档、`09:35:01` 属下一档）：档位边界必须可复现，
    否则同一只票在两次跑批里可能落到不同档。
    """
    if not seal_time or len(seal_time) < 5:
        return None, "封板时间缺失，无法归档", False
    hms = seal_time if len(seal_time) >= 8 else f"{seal_time[:5]}:00"
    for upper, expect, note, negative in _SEAL_BUCKETS:
        if hms <= f"{upper}:00":
            return expect, note, negative
    return None, "封板时间异常，无法归档", False


def premium_readout(stock: dict) -> dict:
    """单只涨停股的次日溢价读数（涨停价买入 → 次日集合竞价卖出）。

    这是本项目所有验证中**唯一没被否掉的方向**（其余要么负期望、要么超额符号随基准翻转）。
    但可成交性仍是代理口径，故按 preliminary 纪律输出：无动作词、不进买卖点位置。
    """
    turnover = float(stock.get("turnover") or 0.0)
    bucket, expect, note, tradable = _turnover_readout(turnover)
    seal_expect, seal_note, seal_negative = _seal_readout(stock.get("seal_time"))
    breaks = int(stock.get("break_count") or 0)

    flags: list[dict] = []
    if seal_negative:
        flags.append({"key": "late_seal", "label": "尾盘封板", "tone": "warn", "note": seal_note})
    if breaks >= 3:
        flags.append(
            {
                "key": "high_break",
                "label": f"炸板 {breaks} 次",
                "tone": "warn",
                "note": "炸板 ≥3 次：期望降至 +0.68%（0–2 次为 +2.0~2.5%）",
            }
        )
    return {
        "expect_pct": expect,
        "bucket": bucket,
        "bucket_note": note,
        "tradable": tradable,
        "seal_expect_pct": seal_expect,
        "seal_note": seal_note,
        "flags": flags,
        "evidence": tactic_evidence.describe("limitup_premium"),
    }


def premium_summary(stocks: list[dict]) -> dict:
    """当日涨停池的次日溢价读数汇总 —— **可成交档与不可成交档分开报**。

    回答两件事：① 今天这批涨停明天竞价卖出的历史读数是多少；② 其中挂得上单的那部分是多少。
    刻意不合并成一个数字：缩量一字板期望最高（+3.31%）却买不进，合并会把「看得见吃不着」
    的收益算进用户预期。
    """
    if not stocks:
        return {
            "total": 0,
            "tradable": None,
            "unbuyable": None,
            "buckets": [],
            "headline": "今日无涨停股，无溢价读数可言",
            "caliber": calibers.describe("limitup_premium"),
            "evidence": tactic_evidence.describe("limitup_premium"),
        }

    rows = []
    for s in stocks:
        r = premium_readout(s)
        rows.append((s, r))

    tradable_rows = [(s, r) for s, r in rows if r["tradable"]]
    unbuyable_rows = [(s, r) for s, r in rows if not r["tradable"]]

    buckets = []
    for label, upper, expect, note, tradable in _TURNOVER_BUCKETS:
        members = [(s, r) for s, r in rows if r["bucket"] == label]
        buckets.append(
            {
                "label": label,
                "expect_pct": expect,
                "note": note,
                "tradable": tradable,
                "count": len(members),
                "codes": [m[0]["code"] for m in members],
                "names": [m[0]["name"] for m in members],
            }
        )

    def _span(group: list[tuple[dict, dict]]) -> dict | None:
        if not group:
            return None
        values = [r["expect_pct"] for _, r in group]
        return {
            "count": len(group),
            "expect_low": round(min(values), 2),
            "expect_high": round(max(values), 2),
        }

    tradable = _span(tradable_rows)
    unbuyable = _span(unbuyable_rows)
    late_seal = [s for s, r in rows if any(f["key"] == "late_seal" for f in r["flags"])]

    if tradable:
        headline = (
            f"今日 {len(rows)} 只涨停，其中 {tradable['count']} 只换手 ≥5%（可成交性较好），"
            f"同档历史次日溢价读数 {tradable['expect_low']:+.2f}% ~ {tradable['expect_high']:+.2f}%；"
            f"另有 {len(unbuyable_rows)} 只换手 <5%（缩量一字/秒板），历史读数更高但多数挂不上单。"
        )
        if late_seal:
            headline += f"尾盘封板 {len(late_seal)} 只属唯一负期望档。"
        headline += "这是统计读数，不是买入指令。"
    else:
        headline = "今日涨停股全部为缩量一字/秒板，历史读数虽高但可成交性差，不具备可执行性。"

    return {
        "total": len(rows),
        "tradable": tradable,
        "unbuyable": unbuyable,
        "late_seal_count": len(late_seal),
        "buckets": buckets,
        "headline": headline,
        "caliber": calibers.describe("limitup_premium"),
        "evidence": tactic_evidence.describe("limitup_premium"),
    }


# ---------- 当日全景 ----------


async def get_snapshot(force: bool = False) -> dict:
    """当日连板全景：情绪 + 梯队 + 板块 + 个股位置标注。

    60 秒内存缓存。涨停池与炸板池并发拉取（各 1 次请求）。
    """
    today = trade_calendar_service.now_cn().date()
    key = today.isoformat()
    now = time.monotonic()
    if not force:
        hit = _SNAP_CACHE.get(key)
        if hit and now - hit[0] < _SNAP_TTL:
            return {**hit[1], "cached": True}

    date_str = today.strftime("%Y%m%d")
    zt_raw, zb_raw = await asyncio.gather(
        asyncio.to_thread(_fetch_pool_sync, "zt", date_str),
        asyncio.to_thread(_fetch_pool_sync, "zb", date_str),
        return_exceptions=True,
    )
    if isinstance(zt_raw, Exception):
        raise RuntimeError(f"涨停池获取失败: {zt_raw}")
    limit_up = [normalize_limit_up(x) for x in zt_raw]
    # 炸板池失败只影响炸板率，不该让整条链路失败 —— 降级为空并放一个标记。
    broken_ok = not isinstance(zb_raw, Exception)
    broken = [normalize_broken(x) for x in zb_raw] if broken_ok else []

    sentiment = build_sentiment(limit_up, broken)
    # 先统一挂上位置标注与溢价读数，再进各聚合层 —— 三处（ladder / sectors / stocks）必须看到同一份数据。
    # 反例：只给 stocks 挂 position 会让展开后的「连板梯队」缺字段，前端读到 undefined。
    decorated = [
        {**t, "position": position_tag(t), "premium": premium_readout(t)} for t in limit_up
    ]
    stocks = sorted(decorated, key=lambda x: (-x["boards"], x["seal_time"] or "99:99:99"))
    ladder = build_ladder(decorated)
    sectors = build_sectors(decorated)
    relay_stocks = build_relay_stocks(stocks)
    data = {
        "trade_date": key,
        "session": trade_calendar_service.session_label(),
        "sentiment": sentiment,
        "sentiment_note": sentiment_note(sentiment),
        "play_advice": play_advice(sentiment, ladder, sectors),
        "ladder": ladder,
        "sectors": sectors,
        "relay_stocks": relay_stocks,
        "relay_tier_summary": relay_tier_summary(relay_stocks),
        # 次日溢价读数（可成交档与不可成交档分开报）
        "premium_summary": premium_summary(limit_up),
        "stocks": stocks,
        "broken_ok": broken_ok,
        "evidence": tactic_evidence.describe("limitup_relay"),
        "caliber": calibers.describe("limitup_relay"),
    }
    cache_utils.put_bounded(_SNAP_CACHE, key, (now, data), max_entries=_SNAP_CACHE_MAX)

    # 每日落库（fire-and-forget）：实时拉到的池子顺手写入累积表，收盘后的最后一次
    # 请求会落最终状态。失败静默（save_daily_snapshot 内部已兜底），绝不影响实时链路。
    try:
        await save_daily_snapshot(key, stocks)
    except Exception as e:  # pragma: no cover - 双保险，save 内部不应抛
        print(f"[limitup] 快照落库异常(主流程不受影响): {e}")

    return {**data, "cached": False}


# ---------- 晋级率回测 ----------


async def _completed_trading_days(n: int) -> list[dt.date]:
    """最近 n 个**已收盘**的交易日，从旧到新。

    盘中调用会跳过当天：当天池子还在变，用它统计「次日晋级」等于把半成品当样本。
    """
    d = await trade_calendar_service.last_trading_day()
    if not trade_calendar_service.is_after_close():
        d = await trade_calendar_service.last_trading_day(d - dt.timedelta(days=1))
    out: list[dt.date] = []
    for _ in range(max(1, n)):
        out.append(d)
        d = await trade_calendar_service.last_trading_day(d - dt.timedelta(days=1))
    return list(reversed(out))


def _cluster_bucket(sector_count: int) -> str:
    if sector_count >= 5:
        return "≥5家"
    if sector_count >= 3:
        return "3-4家"
    return "1-2家"


def _relay_stats(days: list[dt.date], per_day: dict[str, list[dict]]) -> dict:
    """核心统计：N 连板 → 次日晋级率，并按板块聚集度分组对比。

    晋级判定：次日涨停池里该 code 的 ``lbc`` 恰好等于当日 +1。
    停牌或未晋级一律记未晋级（保守），不做「剔除无法交易样本」这类对结论有利的处理。

    ⚠️ 为什么必须给「高度 × 聚集度」交叉表：板块聚集度与连板高度是**混淆**的 ——
    一个板块当天涨停 7 只时，这 7 只往往全是首板（板块启动第一天），而首板晋级率天然最低。
    只看聚集度的边缘分布，会把「首板占比高」误读成「热点板块不容易连板」。
    分层之后才能回答「控制住高度，板块聚集本身还有没有额外信息」。
    """
    by_boards: dict[int, dict] = {}
    by_cluster: dict[str, dict] = {}
    by_boards_cluster: dict[tuple[int, str], dict] = {}
    total = promoted_total = 0
    sessions = 0

    for i in range(len(days) - 1):
        cur = per_day.get(days[i].isoformat())
        nxt = per_day.get(days[i + 1].isoformat())
        if cur is None or nxt is None:
            continue
        sessions += 1
        next_map = {t["code"]: t["boards"] for t in nxt}

        sector_count: dict[str, int] = {}
        for t in cur:
            sector_count[t["sector"]] = sector_count.get(t["sector"], 0) + 1

        for t in cur:
            if not t["code"] or t["boards"] < 1:
                continue
            promoted = next_map.get(t["code"], 0) == t["boards"] + 1
            total += 1
            promoted_total += int(promoted)

            key = min(t["boards"], _LADDER_CAP)
            slot = by_boards.setdefault(key, {"key": key, "label": ladder_label(key), "total": 0, "promoted": 0})
            slot["total"] += 1
            slot["promoted"] += int(promoted)

            ckey = _cluster_bucket(sector_count[t["sector"]])
            slot2 = by_cluster.setdefault(ckey, {"key": ckey, "total": 0, "promoted": 0})
            slot2["total"] += 1
            slot2["promoted"] += int(promoted)

            slot3 = by_boards_cluster.setdefault(
                (key, ckey), {"boards": key, "cluster": ckey, "total": 0, "promoted": 0}
            )
            slot3["total"] += 1
            slot3["promoted"] += int(promoted)

    def _ratio(slot: dict) -> float:
        return round(slot["promoted"] / slot["total"] * 100, 1) if slot["total"] else 0.0

    boards_rows = [{**slot, "rate": _ratio(slot)} for slot in sorted(by_boards.values(), key=lambda x: x["key"])]
    cluster_order = {"1-2家": 0, "3-4家": 1, "≥5家": 2}
    cluster_rows = [
        {**slot, "rate": _ratio(slot)}
        for slot in sorted(by_cluster.values(), key=lambda x: cluster_order.get(x["key"], 9))
    ]

    # 交叉表按高度归并，只保留两层都有样本的组合，避免展示 n=1 的格子误导读者。
    cross: dict[int, list[dict]] = {}
    for (bkey, ckey), slot in by_boards_cluster.items():
        cross.setdefault(bkey, []).append({**slot, "rate": _ratio(slot)})
    cross_rows = [
        {
            "boards": bkey,
            "label": ladder_label(bkey),
            "clusters": sorted(cross[bkey], key=lambda x: cluster_order.get(x["cluster"], 9)),
        }
        for bkey in sorted(cross)
    ]

    return {
        "sessions": sessions,
        "total_samples": total,
        "overall_rate": round(promoted_total / total * 100, 1) if total else 0.0,
        "by_boards": boards_rows,
        "by_cluster": cluster_rows,
        "by_boards_cluster": cross_rows,
    }


async def relay_backtest(days: int = MAX_RELAY_DAYS, force: bool = False) -> dict:
    """历史 N 连板 → 次日晋级率（口径见 ``calibers.limitup_relay``）。

    只打涨停池接口，每天 1 次请求，走 ``concurrency.gather_limited`` 限流。
    结果缓存 6 小时（只依赖已收盘交易日，半天内不会变）。

    ⚠️ **数据窗口只有约 15 个交易日**：东财涨停池对更早的日期返回**空池**（实测
    2026-08-27 及以前全为 0 条，08-28 起才有数据）。空池必须与「当天真的没有涨停」区分开 ——
    前者要标为无数据并排除出样本，否则会把「接口不提供」算成「样本不足」，
    更糟的是会让不同 ``days`` 请求返回**完全相同**的统计量而不自知。
    """
    days = max(2, min(days, 40))
    cache_key = str(days)
    now = time.monotonic()
    if not force:
        hit = _RELAY_CACHE.get(cache_key)
        if hit and now - hit[0] < _RELAY_TTL:
            return {**hit[1], "cached": True}

    trading_days = await _completed_trading_days(days)
    results = await concurrency.gather_limited(
        [asyncio.to_thread(_fetch_pool_sync, "zt", d.strftime("%Y%m%d")) for d in trading_days],
        return_exceptions=True,
    )

    per_day: dict[str, list[dict]] = {}
    skipped: list[str] = []
    empty: list[str] = []
    for d, res in zip(trading_days, results):
        if isinstance(res, Exception):
            skipped.append(d.isoformat())
            continue
        if not res:
            # 空池 = 该日期超出接口回溯范围（见 docstring），不是「零样本」。
            empty.append(d.isoformat())
            continue
        per_day[d.isoformat()] = [normalize_limit_up(x) for x in res]

    # 累积表补样本：接口回溯窗口外（或当日请求失败）的日期，若已每日落库则有真实数据。
    # 这是「窗口自积累」的读路径 —— 落库跑得越久，这里能补回来的天数越多。
    accumulated_from = trading_days[0].isoformat() if trading_days else None
    accumulated_to = trading_days[-1].isoformat() if trading_days else None
    accumulated_days = 0
    if accumulated_from and accumulated_to and empty:
        saved = await load_accumulated_snapshots(accumulated_from, accumulated_to)
        for d_key in list(empty):
            rows = saved.get(d_key)
            if rows:
                per_day[d_key] = rows  # 落库行字段与 normalize_limit_up 输出对齐
                empty.remove(d_key)
                accumulated_days += 1

    stats = _relay_stats(trading_days, per_day)
    # 随机基线：不看任何条件、随手买一只票，次日刚好封上涨停的概率 ≈ 日均涨停家数 ÷ 全市场股票数。
    # 注意它不是「同口径基准」—— 晋级率的样本本身就是今日已封板的强势股，天然占优，
    # 这个数字只用来标出「随机水平」的量级，不能当作超额收益的基准（见 calibers.limitup_relay.pitfall）。
    avg_daily = round(stats["total_samples"] / stats["sessions"], 1) if stats["sessions"] else 0.0
    covered = sorted(per_day)
    data = {
        "caliber": calibers.describe("limitup_relay"),
        "evidence": tactic_evidence.describe("limitup_relay"),
        "days": days,
        "date_range": [trading_days[0].isoformat(), trading_days[-1].isoformat()] if trading_days else [],
        "data_window": [covered[0], covered[-1]] if covered else [],
        "effective_days": len(covered),
        "empty_dates": empty,
        "skipped_dates": skipped,
        "accumulated_days": accumulated_days,
        "avg_daily_limit_up": avg_daily,
        "baseline_rate": round(avg_daily / _MARKET_UNIVERSE * 100, 4),
        "market_universe": _MARKET_UNIVERSE,
        **stats,
    }
    cache_utils.put_bounded(_RELAY_CACHE, cache_key, (now, data), max_entries=_SNAP_CACHE_MAX)
    return {**data, "cached": False}


def clear_caches() -> None:
    """清空模块缓存（测试与手动刷新用）。"""
    _SNAP_CACHE.clear()
    _RELAY_CACHE.clear()
