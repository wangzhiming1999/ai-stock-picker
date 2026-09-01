"""股票接口：行情、K线、新闻。"""
from fastapi import APIRouter, HTTPException

from app.models import NewsItem, StockHistory, StockInfo
from app.services import data_service

router = APIRouter(prefix="/api/stock", tags=["stock"])


def _to_stock_info(code: str) -> StockInfo:
    quotes = data_service.get_spot_quote([code])
    if not quotes:
        raise HTTPException(status_code=404, detail=f"未找到股票 {code}")
    q = quotes[0]
    history = data_service.get_history(code)
    return StockInfo(code=code, name=q.name, quote=q, history=history)


@router.get("/{code}", response_model=StockInfo)
async def get_stock(code: str) -> StockInfo:
    """获取单只股票的行情 + 历史 K 线"""
    return _to_stock_info(code)


@router.get("/{code}/history", response_model=StockHistory)
async def get_stock_history(code: str, days: int = 120) -> StockHistory:
    history = data_service.get_history(code, days)
    if history is None:
        raise HTTPException(status_code=404, detail="未获取到历史数据")
    return history


@router.get("/{code}/news")
async def get_stock_news(code: str) -> list[NewsItem]:
    name = data_service.get_stock_name(code)
    return data_service.get_news(code, name)
