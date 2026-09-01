from pydantic import BaseModel, Field


class StockQuote(BaseModel):
    """单只股票快照"""
    code: str
    name: str
    price: float
    change_pct: float
    turnover: float | None = None
    volume: float | None = None
    pe: float | None = None
    pb: float | None = None
    market_cap: float | None = None


class StockHistory(BaseModel):
    """K 线数据"""
    dates: list[str]
    closes: list[float]
    volumes: list[float] | None = None


class StockInfo(BaseModel):
    """股票基础信息 + 实时行情"""
    code: str
    name: str
    quote: StockQuote | None = None
    history: StockHistory | None = None


class NewsItem(BaseModel):
    title: str
    url: str | None = None
    date: str | None = None
    source: str | None = None


class AnalysisRequest(BaseModel):
    """选股分析请求"""
    codes: list[str] = Field(..., min_length=1, max_length=20, description="股票代码列表，如 ['600519']")


class ScoreDimension(BaseModel):
    name: str
    score: float = Field(..., ge=0, le=10, description="0-10 分")
    comment: str


class TradeSignal(BaseModel):
    """确定性技术信号（由历史K线计算）"""
    price: float
    support: float
    resistance: float
    buy_point: float
    sell_point: float
    stop_loss: float
    rr_ratio: float
    strength: float
    bb_upper: float | None = None
    bb_lower: float | None = None
    ma5: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    low60: float | None = None
    high60: float | None = None


class StockAnalysis(BaseModel):
    """单只股票的分析结果"""
    code: str
    name: str
    overall_score: float = Field(..., ge=0, le=10)
    summary: str
    dimensions: list[ScoreDimension] = []
    risks: list[str] = []
    suggestions: list[str] = []
    signal: TradeSignal | None = None
    holding_advice: str | None = None


class AnalysisEvent(BaseModel):
    """SSE 事件"""
    type: str  # status | stock_start | stock_done | score | done | error
    message: str = ""
    payload: dict | None = None
