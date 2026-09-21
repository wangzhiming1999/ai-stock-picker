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
    quote_time: str | None = None


class StockHistory(BaseModel):
    """K 线数据（日线只有 closes；分钟线附带 OHLC 供日内决策使用）"""
    dates: list[str]
    closes: list[float]
    volumes: list[float] | None = None
    opens: list[float] | None = None
    highs: list[float] | None = None
    lows: list[float] | None = None
    # 换手率%（腾讯 newfqkline 行索引 7，日/周/月线均返回）
    turnover: list[float] | None = None


class IntradaySignal(BaseModel):
    """分钟级技术信号（日内战术决策）"""
    price: float
    vwap: float | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    ma_fast: float | None = None
    ma_slow: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    volume_ratio: float | None = None
    trend: str = "flat"                      # up | down | flat
    support: float | None = None
    resistance: float | None = None
    stop_loss: float | None = None
    strength: float = 5.0
    bars: int = 0                            # 参与计算的 K 线根数
    session: str = "unknown"                 # 数据所属交易日


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
    force: bool = Field(False, description="强制重跑，忽略当日缓存")
    debate: bool = Field(
        False,
        description="是否额外跑「多空研究员辩论」。每只票多 2 轮 LLM 调用，明显更慢，故默认关闭",
    )


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


class StrategyAssessment(BaseModel):
    """可复核的规则策略检查，不依赖 LLM 自由发挥。"""
    name: str
    source: str
    status: str
    score: float = Field(..., ge=0, le=10)
    passed: int
    total: int
    action: str
    conditions: list[dict] = []


class DebateSide(BaseModel):
    """辩论中的一方（多头 / 空头研究员）。"""
    side: str = Field(..., description="bull | bear")
    thesis: str = Field("", description="核心论点，一句话")
    evidence: list[str] = Field(default_factory=list, description="支撑论点的具体数据，尽量引用上下文里的数字")
    rebuttal: list[str] = Field(default_factory=list, description="对对方论点的逐条反驳（第一轮为空）")
    confidence: float = Field(0, ge=0, le=100, description="该方对自己的信心 0-100")


class DebateResult(BaseModel):
    """多空研究员结构化辩论结果。

    定位：**风险与分歧标签，不是买卖点**。论据来自 LLM 推理，没有任何统计回测支撑，
    因此证据等级固定取自 `tactic_evidence` 的 `unknown` 档、`executable` 恒为 False ——
    与形态闸门同一纪律（未验证的东西不得进入买卖点位置）。
    """
    rounds: int = Field(0, description="实际完成的辩论轮数")
    bull: DebateSide | None = None
    bear: DebateSide | None = None
    divergence: float = Field(
        0, ge=0, le=100,
        description="分歧度 0-100，口径为 min(多头信心, 空头信心)：两边都笃定说明是真争议",
    )
    direction: str = Field("neutral", description="辩论后的倾向：bull | bear | neutral")
    key_disagreement: str = Field("", description="双方最核心的分歧点")
    evidence: dict = Field(default_factory=dict, description="与 pattern_service 同形：tier/label/badge/summary/actionable")
    executable: bool = Field(False, description="恒为 False：辩论结论不得作为买卖依据")
    gate_note: str = Field("", description="闸门说明，前端必须原样展示")


class TradePlan(BaseModel):
    """交易员基于辩论结论起草的交易计划。

    定位：辩论的下游——把多空论据翻译成「可被风控检验」的计划草案，而不是可执行指令。
    是否采纳由 fund_manager_verdict（风控/基金经理终审）决定，本模型自身不带任何执行许可。
    """

    action: str = Field("hold", description="计划动作：buy | add | hold | reduce | avoid")
    entry_price: float | None = Field(None, description="入场触发价（buy/add 时必填）")
    stop_price: float | None = Field(None, description="止损价（buy/add 时必填）")
    target_price: float | None = Field(None, description="目标价（可选，到达即分批止盈）")
    position_pct: float = Field(0, ge=0, le=100, description="建议仓位占总资金 %")
    batches: list[str] = Field(default_factory=list, description="分批方案，每条一句话（如「现价 1/3，回踩 MA20 再 1/3」）")
    rationale: str = Field("", description="计划依据：必须引用辩论双方论据与技术位，禁止空话")
    invalidation: str = Field("", description="计划失效条件：出现什么信号说明论证已破，必须放弃")
    source: str = Field("trader", description="产出来源标识：trader")


class FundManagerVerdict(BaseModel):
    """风控/基金经理终审结论：对交易员计划的批准 / 降级 / 否决。

    三档语义：
    - approved：计划未违反任何硬约束，可按计划参考（仍非买点承诺）
    - demoted：计划方向可参考，但仓位/触发价被降级修正（verdict_notes 说明改了什么）
    - rejected：计划违反证据闸门或风控红线，不可参考
    """

    decision: str = Field("rejected", description="approved | demoted | rejected")
    verdict_notes: list[str] = Field(default_factory=list, description="逐条裁决理由（违反/通过的风控项）")
    final_position_pct: float = Field(0, ge=0, le=100, description="终审后允许参考的仓位 %（rejected 时为 0）")
    final_stop_price: float | None = Field(None, description="终审后止损价：只能比交易员的更严，不能更松")
    source: str = Field("fund_manager", description="产出来源标识")


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
    strategy: StrategyAssessment | None = None
    # 命中的实战形态（pattern_service），只装「全部条件成立」的技巧
    tactics: list[dict] = Field(default_factory=list)
    # 多空研究员辩论（debate_service），仅在请求显式开启时才有值
    debate: DebateResult | None = None
    # 交易员计划 + 基金经理终审（TradingAgents ③④层），仅在开启辩论且辩论成功时产出
    trade_plan: TradePlan | None = None
    fund_manager_verdict: FundManagerVerdict | None = None
    # 本次分析落库的 agent 决策行 id（agent_decisions，执行闭环：一键采纳建仓用）。
    # None = 未登录 / 表未建 / 落库失败 —— 前端据此隐藏「按计划建仓」按钮。
    agent_decision_id: int | None = None
    holding_advice: str | None = None


class AnalysisEvent(BaseModel):
    """SSE 事件"""
    type: str  # status | stock_start | stock_done | score | done | error
    message: str = ""
    payload: dict | None = None
