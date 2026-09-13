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


def _num(value) -> float | None:
    """东财/新浪缺值时可能是 '-'、''、None。"""
    try:
        if value is None or value == "" or value == "-":
            return None
        return float(value)
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
                "总市值": _num(item.get("mktcap")),
                "流通市值": _num(item.get("nmc")),
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
