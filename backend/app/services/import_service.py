"""持仓导入解析服务：粘贴文本（正则）+ 持仓截图（视觉模型）→ 结构化候选列表。

解析结果只做预览，不落库；由前端确认后调用批量导入接口。
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.config import get_settings
from app.services import data_service

_CODE_RE = re.compile(r"(?<!\d)([04568]\d{5})(?!\d)")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_COST_KW = ("成本", "保本", "成本价", "摊薄")
_SHARES_KW = ("数量", "持仓", "股数", "持股", "股")


def _clean_code(raw: str) -> str | None:
    c = (raw or "").strip().lower().replace("sh", "").replace("sz", "").replace("bj", "")
    return c if re.fullmatch(r"[04568]\d{5}", c) else None


def _extract_name(line: str, code: str) -> str:
    """从行中提取股票名称：代码附近的中文/字母串。"""
    m = re.search(r"[\u4e00-\u9fa5A-Za-z*]{2,10}", line.replace(code, " "))
    return m.group(0).strip() if m else ""


def _parse_line(line: str) -> dict | None:
    """解析单行持仓文本。返回 {code, name, cost_price, shares} 或 None。"""
    code_m = _CODE_RE.search(line)
    if not code_m:
        return None
    code = code_m.group(1)
    name = _extract_name(line, code)

    # 关键词定位：成本 / 数量
    cost = shares = None
    for kw in _COST_KW:
        m = re.search(kw + r"[^\d]{0,6}(\d+(?:\.\d+)?)", line)
        if m:
            cost = float(m.group(1))
            break
    for kw in _SHARES_KW:
        m = re.search(kw + r"[^\d]{0,4}(\d+(?:\.\d+)?)", line)
        if m:
            shares = int(float(m.group(1)))
            break

    # 无关键词时启发式：收集行内其他数字（排除代码），带小数者视为成本候选，整数视为数量候选
    if cost is None or shares is None:
        nums = [float(x) for x in _NUM_RE.findall(line.replace(code_m.group(0), " ", 1))]
        decimals = [n for n in nums if not n.is_integer()]
        ints = [n for n in nums if n.is_integer()]
        if cost is None and decimals:
            cost = max(decimals)  # 多个小数时取大者（现价/成本接近，避开盈亏比例小值）
        if shares is None and ints:
            big = [n for n in ints if n >= 10]
            shares = int(big[0]) if big else None

    if cost is not None and (cost <= 0 or cost > 100000):
        cost = None
    if shares is not None and (shares <= 0 or shares > 10_000_000):
        shares = None
    if cost is None and shares is None and not name:
        return None
    return {"code": code, "name": name, "cost_price": cost, "shares": shares}


def parse_holdings_text(text: str) -> tuple[list[dict], list[str]]:
    """解析粘贴的持仓文本 → (候选列表, 警告)。"""
    warnings: list[str] = []
    items: list[dict] = []
    seen: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _parse_line(line)
        if not parsed:
            if re.search(r"\d{6}", line):
                warnings.append(f"无法解析行：{line[:40]}")
            continue
        if parsed["code"] in seen:
            continue
        seen.add(parsed["code"])
        items.append(parsed)
    if not items:
        warnings.append("未识别出任何 6 位股票代码，请确认文本格式（每行包含股票代码）")
    return items, warnings


def _vl_configured() -> bool:
    return bool(get_settings().vl_api_key)


_VL_PROMPT = (
    "你是证券持仓截图解析器。从图片表格中提取每一只股票的信息："
    "代码（6 位数字）、名称、成本价（或保本价）、持仓数量（股，整数）。"
    '只输出 JSON 数组，格式如 [{"code":"600519","name":"贵州茅台","cost_price":1224.5,"shares":100}]。'
    "无法确定的字段用 null。不要输出任何其他文字或解释。"
)


def _extract_json_array(text: str) -> list[dict]:
    """从模型回复中提取 JSON 数组（容忍 ```json 包裹与前后杂文）。"""
    text = (text or "").strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


async def parse_holdings_image(image_base64: str) -> tuple[list[dict], list[str]]:
    """截图识别：视觉模型 → 结构化持仓候选。"""
    warnings: list[str] = []
    if not _vl_configured():
        raise ValueError("未配置视觉模型 API Key（VL_API_KEY），无法识别截图。可改用文本粘贴导入，或配置免费的智谱 GLM-4V-Flash。")

    raw = image_base64.strip()
    if raw.startswith("data:"):
        header_end = raw.find(",")
        b64_body = raw[header_end + 1 :] if header_end != -1 else raw
        data_url = raw
    else:
        b64_body = raw
        data_url = f"data:image/jpeg;base64,{raw}"

    # 基本校验 base64 体积（约 <3.5MB，防 Vercel 4.5MB 请求体限制）
    if len(b64_body) > 3_500_000:
        raise ValueError("图片过大（>2.6MB），请截取持仓区域后重试")

    from openai import AsyncOpenAI

    s = get_settings()
    client = AsyncOpenAI(api_key=s.vl_api_key, base_url=s.vl_base_url)
    try:
        resp = await client.chat.completions.create(
            model=s.vl_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": _VL_PROMPT},
                    ],
                }
            ],
            temperature=0,
            max_tokens=2000,
        )
    except Exception as e:
        raise ValueError(f"视觉模型调用失败：{e}") from e

    content = resp.choices[0].message.content if resp.choices else ""
    rows = _extract_json_array(content or "")
    items: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        code = _clean_code(str(r.get("code", "")))
        if not code or code in seen:
            continue
        seen.add(code)
        cost = r.get("cost_price")
        shares = r.get("shares")
        try:
            cost = round(float(cost), 3) if cost is not None else None
        except (TypeError, ValueError):
            cost = None
        try:
            shares = int(float(shares)) if shares is not None else None
        except (TypeError, ValueError):
            shares = None
        if cost is not None and (cost <= 0 or cost > 100000):
            cost = None
        if shares is not None and (shares <= 0 or shares > 10_000_000):
            shares = None
        items.append({"code": code, "name": str(r.get("name", "") or "").strip(), "cost_price": cost, "shares": shares})
    if not items:
        warnings.append("截图未识别出持仓，请确保截图清晰、包含股票代码/成本/数量列")
    return items, warnings


async def enrich_names(items: list[dict]) -> list[dict]:
    """批量用实时行情补全名称并校验代码有效性（无效代码标记 valid=False）。"""
    codes = [it["code"] for it in items if it.get("code")]
    name_map: dict[str, str] = {}
    if codes:
        try:
            quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
            name_map = {q.code: q.name for q in quotes if q.name}
        except Exception:
            name_map = {}
    for it in items:
        qname = name_map.get(it.get("code", ""))
        # 行情库名称更可信（文本/截图里的名称可能带 sh/sz 前缀等杂质）
        it["name"] = qname or it.get("name") or ""
        it["valid"] = bool(qname)  # 行情库能查到 = 代码有效
    return items


def sanitize_items(items: list[dict]) -> list[dict]:
    """预览确认后的入库前清洗：仅保留有效完整项。"""
    out = []
    for it in items:
        code = _clean_code(str(it.get("code", "")))
        try:
            cost = float(it.get("cost_price"))
            shares = int(float(it.get("shares")))
        except (TypeError, ValueError):
            continue
        if not code or cost <= 0 or shares <= 0:
            continue
        out.append(
            {
                "code": code,
                "name": str(it.get("name", "") or ""),
                "cost_price": round(cost, 3),
                "shares": shares,
                "buy_date": it.get("buy_date") or None,
                "note": str(it.get("note", "") or ""),
            }
        )
    return out
