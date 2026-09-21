"""全市场实时行情快照：东财（多域名轮换）优先 + 新浪兜底。

为什么不直接用 ak.stock_zh_a_spot_em / ak.stock_zh_a_spot（akshare 1.16.94）：

* ``stock_zh_a_spot_em`` 硬编码 ``82.push2.eastmoney.com``。该域名对部分出口 IP
  会直接断连（RemoteDisconnected），且分页无浏览器 UA、无节流、无重试，一次性拉
  全市场约 60 页极易触发东财风控，触发后同 IP 下所有 push2 域名会短暂集体断连。
* ``stock_zh_a_spot`` 走的是**新浪**（不是腾讯），高频访问后新浪会返回 HTML 风控页，
  demjson 解码时报 ``Can not decode value starting with character '<'``。

这里自建抓取：多域名轮换 + 浏览器 UA/Referer + 页间节流 + 指数退避重试，并对整份
快照做有效性（有效价格占比）校验，避免盘前全 0 快照被当成可用数据。
"""
from __future__ import annotations

import json
import math
import re
import time

import pandas as pd
import requests

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT = 15

# ---------- 东财 ----------
# 82.push2 是 akshare 唯一使用的域名，挂掉时其余编号域名通常仍可用。
_EM_HOSTS = (
    "82.push2.eastmoney.com",
    "push2.eastmoney.com",
    "48.push2.eastmoney.com",
    "1.push2.eastmoney.com",
    "7.push2.eastmoney.com",
    "9.push2.eastmoney.com",
    "13.push2.eastmoney.com",
    "16.push2.eastmoney.com",
)
_EM_PATH = "/api/qt/clist/get"
_EM_FIELDS = (
    "f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23"
)
_EM_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"
_EM_PAGE_SIZE = 200
_EM_HOST_ATTEMPTS = 3        # 单页最多尝试的域名数
_EM_MAX_FAILED_PAGES = 1     # 东财风控是 IP 级，少量失败页即说明该源不可用，快速降级

# ---------- 新浪 ----------
_SINA_BASE = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
_SINA_LIST_URL = f"{_SINA_BASE}/Market_Center.getHQNodeData"
_SINA_COUNT_URL = f"{_SINA_BASE}/Market_Center.getHQNodeStockCount"
_SINA_PAGE_SIZE = 80
_SINA_MAX_FAILED_PAGES = 3

_PAGE_SLEEP = 0.08          # 页间节流，降低被风控概率
_RETRY_SLEEP = 0.8          # 重试退避基数
_HOST_RETRY_SLEEP = 0.25    # 域名轮换退避基数
_SOURCE_ATTEMPTS = 2        # 每个数据源的整体尝试轮次

_MIN_ROWS = 100
_MIN_PRICED_RATIO = 0.5


def _num(value, scale: float = 1.0) -> float | None:
    """东财/新浪缺值时可能是 '-'、''、None。scale 用于单位换算（如万元→元）。"""
    try:
        if value is None or value == "" or value == "-":
            return None
        return float(value) * scale
    except (TypeError, ValueError):
        return None


def _session(referer: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": _UA,
            "Accept": "*/*",
            "Referer": referer,
            "Connection": "keep-alive",
        }
    )
    return session


def _is_valid_frame(df: pd.DataFrame | None) -> bool:
    """快照是否可用：行数足够且有价格的占比达标（过滤盘前全 0 快照）。"""
    if df is None or len(df) < _MIN_ROWS:
        return False
    prices = pd.to_numeric(df.get("最新价"), errors="coerce").fillna(0)
    return (prices > 0).sum() / len(df) >= _MIN_PRICED_RATIO


def _em_request(session: requests.Session, params: dict, host_offset: int = 0):
    """带域名轮换与退避重试的单页请求，返回 diff 列表。"""
    last: Exception | None = None
    for attempt in range(_EM_HOST_ATTEMPTS):
        host = _EM_HOSTS[(host_offset + attempt) % len(_EM_HOSTS)]
        try:
            resp = session.get(f"https://{host}{_EM_PATH}", params=params, timeout=_TIMEOUT)
            payload = resp.json()
            diff = (payload.get("data") or {}).get("diff")
            if not diff:
                raise ValueError(f"东财返回空数据 (host={host}, rc={payload.get('rc')})")
            return payload, diff
        except Exception as exc:  # noqa: BLE001 - 需要吞掉所有网络/解析异常以换域名重试
            last = exc
            time.sleep(_HOST_RETRY_SLEEP * (attempt + 1))
    raise RuntimeError(f"东财行情请求失败: {last}")


def _frame_from_em(rows: list[dict]) -> pd.DataFrame:
    records = []
    for item in rows:
        code = str(item.get("f12", "")).strip()
        if not code:
            continue
        records.append(
            {
                "代码": code,
                "名称": str(item.get("f14", "")).strip(),
                "最新价": _num(item.get("f2")),
                "涨跌幅": _num(item.get("f3")),
                "涨跌额": _num(item.get("f4")),
                "成交量": _num(item.get("f5")),
                "成交额": _num(item.get("f6")),
                "振幅": _num(item.get("f7")),
                "换手率": _num(item.get("f8")),
                "市盈率-动态": _num(item.get("f9")),
                "量比": _num(item.get("f10")),
                "5分钟涨跌": _num(item.get("f11")),
                "最高": _num(item.get("f15")),
                "最低": _num(item.get("f16")),
                "今开": _num(item.get("f17")),
                "昨收": _num(item.get("f18")),
                "总市值": _num(item.get("f20")),
                "流通市值": _num(item.get("f21")),
                "市净率": _num(item.get("f23")),
            }
        )
    return pd.DataFrame(records)


def _fetch_eastmoney(max_pages: int | None = None) -> pd.DataFrame:
    """东财沪深京 A 股实时快照（分页抓取，单页失败自动换域名重试）。"""
    session = _session("https://quote.eastmoney.com/")
    params = {
        "pn": "1",
        "pz": str(_EM_PAGE_SIZE),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": _EM_FS,
        "fields": _EM_FIELDS,
    }
    payload, diff = _em_request(session, params)
    total = int((payload.get("data") or {}).get("total") or 0)
    rows: list[dict] = list(diff)
    total_pages = max(1, math.ceil(total / max(len(diff), 1)))
    if max_pages:
        total_pages = min(total_pages, max_pages)

    failed = 0
    for page in range(2, total_pages + 1):
        params["pn"] = str(page)
        try:
            _, page_diff = _em_request(session, params, host_offset=page)
            rows.extend(page_diff)
        except Exception:  # noqa: BLE001 - 容忍少量失败页，超过阈值才整体失败
            failed += 1
            if failed > _EM_MAX_FAILED_PAGES:
                raise
        time.sleep(_PAGE_SLEEP)
    return _frame_from_em(rows)


def _sina_request(session: requests.Session, url: str, params: dict, attempts: int = 3):
    """新浪请求：自动重试并识别 HTML 风控页。"""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = session.get(url, params=params, timeout=_TIMEOUT)
            body = (resp.text or "").strip()
            if body.startswith("<"):
                # 风控是 IP 级的，重试没有意义，直接失败让上层降级/进入冷却
                raise RuntimeError("新浪返回 HTML 风控页（请求过于频繁，请稍后重试）")
            return json.loads(body)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if "风控页" in str(exc):
                break
            time.sleep(_RETRY_SLEEP * (attempt + 1))
    raise RuntimeError(f"新浪行情请求失败: {last}")


def _frame_from_sina(rows: list[dict]) -> pd.DataFrame:
    records = []
    for item in rows:
        # 新浪返回 sh600519 形式，统一为东财的 600519
        symbol = re.sub(r"^(?:sh|sz|bj)", "", str(item.get("symbol", "")).strip())
        if not symbol:
            continue
        high = _num(item.get("high"))
        low = _num(item.get("low"))
        prev = _num(item.get("settlement"))
        amplitude = None
        if high is not None and low is not None and prev:
            amplitude = (high - low) / prev * 100
        records.append(
            {
                "代码": symbol,
                "名称": str(item.get("name", "")).strip(),
                "最新价": _num(item.get("trade")),
                "涨跌幅": _num(item.get("changepercent")),
                "涨跌额": _num(item.get("pricechange")),
                "成交量": _num(item.get("volume")),
                "成交额": _num(item.get("amount")),
                "振幅": amplitude,
                "换手率": _num(item.get("turnoverratio")),
                "市盈率-动态": _num(item.get("per")),
                "量比": None,  # 新浪无此字段
                "5分钟涨跌": None,
                "最高": high,
                "最低": low,
                "今开": _num(item.get("open")),
                "昨收": prev,
                # 新浪 mktcap/nmc 单位是「万元」，东财 f20/f21 是「元」，此处统一转成元
                "总市值": _num(item.get("mktcap"), scale=1e4),
                "流通市值": _num(item.get("nmc"), scale=1e4),
                "市净率": _num(item.get("pb")),
            }
        )
    return pd.DataFrame(records)


def _fetch_sina(max_pages: int | None = None) -> pd.DataFrame:
    """新浪 A 股实时快照兜底（字段少于东财，量比/5分钟涨跌不可用）。"""
    session = _session("https://vip.stock.finance.sina.com.cn/")
    count_text = session.get(_SINA_COUNT_URL, params={"node": "hs_a"}, timeout=_TIMEOUT).text.strip()
    if count_text.startswith("<"):
        raise RuntimeError("新浪返回 HTML 风控页（请求过于频繁，请稍后重试）")
    matched = re.search(r"\d+", count_text)
    if not matched:
        raise RuntimeError(f"新浪行情返回非预期内容: {count_text[:60]!r}（可能触发风控）")
    total_pages = max(1, math.ceil(int(matched.group()) / _SINA_PAGE_SIZE))
    if max_pages:
        total_pages = min(total_pages, max_pages)

    rows: list[dict] = []
    failed = 0
    for page in range(1, total_pages + 1):
        try:
            data = _sina_request(
                session,
                _SINA_LIST_URL,
                {
                    "page": str(page),
                    "num": str(_SINA_PAGE_SIZE),
                    "sort": "symbol",
                    "asc": "1",
                    "node": "hs_a",
                    "_s_r_a": "page",
                },
            )
            if isinstance(data, list):
                rows.extend(data)
        except Exception:  # noqa: BLE001
            failed += 1
            if failed > _SINA_MAX_FAILED_PAGES:
                raise
        time.sleep(_PAGE_SLEEP)
    if not rows:
        raise RuntimeError("新浪行情返回空数据")
    return _frame_from_sina(rows)


# 用函数名而非函数对象，便于测试时替换具体数据源
_SOURCES = (("东财", "_fetch_eastmoney"), ("新浪", "_fetch_sina"))


def fetch_spot_frame() -> pd.DataFrame:
    """获取全市场快照 DataFrame（统一字段名），全部数据源失败时抛 RuntimeError。"""
    errors: list[str] = []
    for round_no in range(_SOURCE_ATTEMPTS):
        for label, fetcher_name in _SOURCES:
            fetcher = globals()[fetcher_name]
            try:
                df = fetcher()
                if _is_valid_frame(df):
                    return df
                errors.append(f"{label}#{round_no + 1}: 有效价格不足（{len(df)} 行）")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}#{round_no + 1}: {exc}")
            time.sleep(_RETRY_SLEEP * (round_no + 1))
    raise RuntimeError("；".join(errors))


# ───────────────────────── 全市场资金流排行（东财 clist · 批量） ─────────────────────────
#
# ⚠️ 这一节**刻意走与快照同一个 clist 端点**，而不是 `ak.stock_individual_fund_flow`
#    （那是逐个 code 请求，正是 memory 里点名的风控主因）。
#    同一个 `/api/qt/clist/get` 换一个 `fid` 就能按「主力净流入」排序返回**整页**个股，
#    一次请求覆盖数百只 —— 拿真实主力资金数据，而请求量比逐股方案低两个数量级。
#    因此：**永远不要在这里加逐股回环**。
#
# 字段口径（东财 push2 资金流列）：
#   f62 主力净流入额（元）  f184 主力净占比（%）
#   f66/f69 超大单净额/占比  f72/f75 大单  f78/f81 中单  f84/f87 小单
#   f6 成交额（元，供活跃度维复用）  f100 所属行业  f124 快照时间戳
# 单位：与 akshare `stock_individual_fund_flow_rank` 一致，f62 系**元**，消费方自行折亿元。
_EM_FF_PATH = "/api/qt/clist/get"
# ⚠️ f184（主力净占比）**不能漏**：`_fund_flow_row` 会读它，漏了不报错 ——
#    只是 `main_pct` 永远为 None，资金维就只剩「净额加成」，分数被压在 5.0~5.6，
#    下游「潜力龙头」的资金门槛（≥7）**永远不可能达到**（线上实测踩过，见 tests 的字段守卫）。
#    与 akshare `stock_individual_fund_flow_rank` 同端点的字段串一致（只多 f100 行业）。
_EM_FF_FIELDS = "f12,f14,f2,f3,f6,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f100,f124"
# 与快照的 _EM_FS 相比不含北交所（s:2048）—— 资金流排行对北交所支持不稳定，缺了会整页返空
_EM_FF_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23"
# 单页 500：东财单页上限通常在 100~200，超限会被截断；这里按 200 走，靠页数覆盖
_EM_FF_PAGE_SIZE = 200
_EM_FF_MAX_PAGES = 3
_EM_FF_UT = "bd1d9ddb04089700cf9c27f6f7426281"


def _fund_flow_row(item: dict, rank: int) -> dict | None:
    """东财资金流行 → 归一化 dict。code 缺失或全字段不可用时返回 None。"""
    code = str(item.get("f12", "")).strip()
    if not code:
        return None
    sector = item.get("f100")
    sector = str(sector).strip() if sector not in (None, "", "-") else None
    row = {
        "code": code,
        "name": str(item.get("f14", "")).strip(),
        "price": _num(item.get("f2")),
        "change_pct": _num(item.get("f3")),
        "amount": _num(item.get("f6")),
        "main_net": _num(item.get("f62")),
        "main_pct": _num(item.get("f184")),
        "super_net": _num(item.get("f66")),
        "super_pct": _num(item.get("f69")),
        "large_net": _num(item.get("f72")),
        "large_pct": _num(item.get("f75")),
        "mid_net": _num(item.get("f78")),
        "small_net": _num(item.get("f84")),
        "sector": sector,
        "rank": rank,
    }
    # 主力净额完全拿不到的行没有价值（既不能排序也不能归因）
    if row["main_net"] is None and row["main_pct"] is None:
        return None
    return row


def fetch_fund_flow_rows(
    sort_field: str = "f62",
    ascending: bool = False,
    max_pages: int = _EM_FF_MAX_PAGES,
) -> list[dict]:
    """按资金流字段排序取全市场排行（批量，非逐股）。

    sort_field: `f62`（主力净流入额）/ `f184`（主力净占比）/ `f66`（超大单）…
    ascending=False 取净流入前列（吸筹侧），True 取净流出前列（出货侧）。
    单页失败自动换域名重试；页间节流与整份快照一致。

    全部失败时抛 RuntimeError，由调用方决定是否进入冷却 ——
    ⚠️ 调用方**不要**在这里做兜底重试循环：与快照同源，重试只会延长 IP 封禁。
    """
    session = _session("https://data.eastmoney.com/zjlx/")
    params = {
        "pn": "1",
        "pz": str(_EM_FF_PAGE_SIZE),
        "po": "0" if ascending else "1",
        "np": "1",
        "ut": _EM_FF_UT,
        "fltt": "2",
        "invt": "2",
        "fid": sort_field,
        "fs": _EM_FF_FS,
        "fields": _EM_FF_FIELDS,
    }
    payload, diff = _em_request(session, params)
    raw: list[dict] = list(diff)
    total = int((payload.get("data") or {}).get("total") or 0)
    total_pages = max(1, math.ceil(total / max(len(diff), 1)))
    total_pages = min(total_pages, max(1, max_pages))

    failed = 0
    for page in range(2, total_pages + 1):
        params["pn"] = str(page)
        try:
            _, page_diff = _em_request(session, params, host_offset=page)
            raw.extend(page_diff)
        except Exception:  # noqa: BLE001 - 容忍少量失败页，与快照同一策略
            failed += 1
            if failed > _EM_MAX_FAILED_PAGES:
                break
        time.sleep(_PAGE_SLEEP)

    rows: list[dict] = []
    for idx, item in enumerate(raw):
        row = _fund_flow_row(item, rank=idx + 1)
        if row:
            rows.append(row)
    if not rows:
        raise RuntimeError("东财资金流排行返回空数据")
    return rows
