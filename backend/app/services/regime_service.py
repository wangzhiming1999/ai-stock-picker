"""市场状态识别（Regime Detection）：把「明日方向」从 LLM 单次采样改成可复核的量化证据分。

为什么需要这一层：

原来的方向只由「上证指数 OHLCV + 单次 LLM 调用」产生 —— 证据面窄、无状态、无惯性，
同一个市场状态下分数每天小幅摆动，用户体感就是「方向不稳」。本模块提供两层稳定机制：

1. **市场状态**：确定性规则（均线结构 + 动量 + RSI + 波动）× HMM 交叉验证，
   输出**连续** regime_score 而不是三分类硬标签（硬标签会在状态边界上来回跳）。
   HMM 用状态转移矩阵给出粘性估计（自转移概率、期望持续天数）；
   算法与特征工程参考 wzx11223344/regime-detector（Baum-Welch + Viterbi），
   特征只用指数行情本身，保证历史上可复现。
   **主判据是规则而不是 HMM** —— 原因见 ``compute_regime`` 的实测对比。
2. **市场宽度**：涨跌家数比 / 涨停跌停家数 / 成交额环比，作为当日证据层。

为什么宽度不塞进 HMM：涨跌家数只能拿到「当日」快照，没有可回溯的历史序列，
无法参与 HMM 的时序训练，只能作为当日修正项。

对外输出（供 market_prediction 合成方向分）：
- ``compute_regime()``        → 含 regime_score(0-10) 的状态识别结果
- ``fetch_breadth()``         → 含 breadth_score(0-10) 的市场宽度
- ``blend_evidence()``        → evidence_score（状态分 + 宽度修正）
- ``resolve_direction()``     → **方向的唯一出口**：(方向标签, 方向分)
- ``blend_direction_score()`` → 方向分（证据分 + LLM 微调，LLM 单独影响力限 ±0.5）
- ``apply_inertia()``         → 相对昨日方向分做平滑（禁止单日跳变超过 MAX_DAILY_JUMP）
- ``score_to_direction()``    → 方向分落回 上涨/震荡/下跌 标签

方向标签只由证据分决定（LLM 与惯性都改不了标签），这是「方向稳」的核心保证。

依赖：numpy 必装；hmmlearn 可选 —— 缺失或训练失败时自动走确定性规则状态，不降级功能。
"""
from __future__ import annotations

import logging
import math

import numpy as np

# hmmlearn 在多状态拟合时会持续输出 "Model is not converging" 警告；
# 不收敛本身是我们已经处理并降级的正常情况，不需要污染日志。
logging.getLogger("hmmlearn").setLevel(logging.ERROR)

# ---------- 打分参数（调这一组常量即可整体调节方向的保守程度） ----------

# 三个市场状态的基准分：中间的「震荡」锚在中性 5.0，上下两侧留空间，
# 避免状态刚确认就把仓位打满。
STATE_BASE_SCORE: dict[str, float] = {"下行": 3.2, "震荡": 5.0, "上行": 6.8}

# 方向分 → 标签阈值。中间带宽（3.8~6.2）就是「震荡」，
# 与 market_prediction.normalize_direction() 的三分类语义严格对齐。
SCORE_UP = 6.2
SCORE_DOWN = 3.8
# 「震荡」分数带的贴边余量：中间带在 score_to_direction 里是开区间
_BAND_EPS = 0.05

# 证据分构成：量化证据 0.7 + LLM 0.3（LLM 只能在中性 5.0 附近微调）
EVIDENCE_WEIGHT = 0.7
NEUTRAL_SCORE = 5.0
# LLM 单独能改变最终方向的幅度上限（0.3 × |LLM 分 - 5| 被截断到 ±0.5）
LLM_MAX_ADJUST = 0.5
# 市场宽度对状态分的最大修正幅度
BREADTH_MAX_TILT = 1.2
# 单日方向分最大跳变：超过就按上限向昨日收敛，从机制上禁止「方向一天翻转」
MAX_DAILY_JUMP = 1.0
# 昨日分在平滑里的权重（越大越钝、越稳）
INERTIA_PREV_WEIGHT = 0.4

# 涨跌停判定阈值：主板 10% / 创业板·科创板 20% 都用 9.7% 兜住。
# 北交所是 30% 涨跌幅且家数占比很小，直接剔除，以免污染宽度统计。
LIMIT_PCT = 9.7
_BJ_PREFIXES = ("4", "8", "920")

# HMM 参数
HMM_N_STATES = 3
HMM_MIN_SAMPLES = 60
HMM_RANDOM_STATE = 42
HMM_RESTARTS = 5          # 随机重启次数，取对数似然最高的一次

# 观测特征里用于给状态排序赋义的那一列 = 20 日动量。
# 不用日收益率：它的噪声大一个量级（√20），排序会把「下行」和「震荡」排反。
_SORT_FEATURE_IDX = 2

# 退化判别：如果整段历史其实只有一个 regime（例如单边上涨/下跌），HMM 会收敛成
# 「一个吸收态吞掉几乎全部样本、其余状态只捞到几个离群点」。这时给状态贴
# 「上行/下行」标签就是随机的 —— 实测会把一段单边下跌判成「上行」，
# 是最危险的失败模式（自信地给错方向）。命中以下任一条件即判定拟合无效。
_MAX_STATE_OCCUPANCY = 0.9      # 单个状态占比超过 90% 视为未分出状态
_MIN_STATE_OCCUPANCY = 0.05     # 任一状态占比低于 5% 视为空状态（状态数 > regime 数）
_MIN_STATE_SEPARATION = 0.25    # 状态动量均值（z 分）极差低于此值视为不可区分


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _yf(value) -> float | None:
    """安全转 float：脏数据一律当缺失，不抛异常。"""
    try:
        if value is None:
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def score_to_direction(score: float | None) -> str:
    """方向分 → 方向标签（最终对外口径）。

    分数落在中间带就是「震荡」，不再靠关键词猜 —— 这是修复
    「震荡偏强」被判成「上涨」那类口径不一致问题的关键。
    """
    if score is None:
        return "震荡"
    if score >= SCORE_UP:
        return "上涨"
    if score <= SCORE_DOWN:
        return "下跌"
    return "震荡"


# 方向标签 ↔ 市场状态标签是同一套阈值的两种词表：对外叫「上涨/下跌」，
# 描述市场状态时叫「上行/下行」。集中在这里，避免两处各自判阈值而漂移。
_STATE_BY_DIRECTION = {"上涨": "上行", "下跌": "下行", "震荡": "震荡"}


def state_of_score(score: float | None) -> str:
    """方向分 → 市场状态标签（上行/震荡/下行）。与 score_to_direction 同源同阈值。"""
    return _STATE_BY_DIRECTION[score_to_direction(score)]


# ---------------- 市场状态：HMM ----------------

def _build_features(
    closes: list[float], volumes: list[float] | None
) -> tuple[np.ndarray, dict] | None:
    """构造 HMM 观测序列。

    特征顺序敏感：**第 0 列必须是收益率** —— 状态排序按它的均值做，才谈得上
    「最低收益 = 下行、最高收益 = 上行」的经济含义。

      0 ret     日收益率
      1 vol20   20 日滚动波动率
      2 mom20   20 日动量
      3 vchg    成交量变化率（无成交量数据时置 0）
      4 rsi14   RSI(14)

    返回 (观测矩阵, 用于展示的尾部特征)。样本不足返回 None。
    """
    n = len(closes)
    if n < HMM_MIN_SAMPLES + 21:
        return None
    arr = np.asarray(closes, dtype=float)

    ret = np.zeros(n)
    prev = arr[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = arr[1:] / np.where(prev > 0, prev, np.nan) - 1.0
    ret[1:] = np.nan_to_num(raw, nan=0.0, posinf=0.0, neginf=0.0)

    gains = np.zeros(n)
    losses = np.zeros(n)
    for t in range(1, n):
        diff = arr[t] - arr[t - 1]
        if diff > 0:
            gains[t] = diff
        elif diff < 0:
            losses[t] = -diff

    vol20 = np.zeros(n)
    mom20 = np.zeros(n)
    vchg = np.zeros(n)
    rsi = np.full(n, 50.0)

    volume_arr = None
    if volumes and len(volumes) >= n:
        volume_arr = np.asarray(volumes[:n], dtype=float)

    for t in range(20, n):
        vol20[t] = float(np.std(ret[t - 19 : t + 1]))
        base = arr[t - 20]
        mom20[t] = (arr[t] / base - 1.0) if base > 0 else 0.0
        if volume_arr is not None and volume_arr[t - 1] > 0:
            vchg[t] = volume_arr[t] / volume_arr[t - 1] - 1.0
    for t in range(14, n):
        avg_gain = float(gains[t - 13 : t + 1].mean())
        avg_loss = float(losses[t - 13 : t + 1].mean())
        if avg_loss > 0:
            rsi[t] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        else:
            rsi[t] = 100.0 if avg_gain > 0 else 50.0

    matrix = np.column_stack([ret[20:], vol20[20:], mom20[20:], vchg[20:], rsi[20:]])
    matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
    if matrix.shape[0] < HMM_MIN_SAMPLES:
        return None

    features = {
        "ret20_pct": round(float(mom20[-1]) * 100.0, 2),
        "vol20_pct": round(float(vol20[-1]) * 100.0, 2),
        "rsi14": round(float(rsi[-1]), 1),
    }
    return matrix, features


def _fit_hmm(z: np.ndarray):
    """多次随机重启取对数似然最高的模型。

    单次拟合实测常收敛到「两个 regime 被合并、一个状态占 0 样本」的局部最优，
    重启能明显改善；成本可接受（每日只跑一次且有缓存）。
    """
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        return None

    best = None
    for offset in range(HMM_RESTARTS):
        try:
            model = GaussianHMM(
                n_components=HMM_N_STATES,
                covariance_type="diag",
                n_iter=200,
                tol=1e-4,
                random_state=HMM_RANDOM_STATE + offset,
            )
            model.fit(z)
            log_likelihood = float(model.score(z))
        except Exception:  # noqa: BLE001 - 单个重启失败不影响其余重启
            continue
        if not math.isfinite(log_likelihood):
            continue
        if best is None or log_likelihood > best[0]:
            best = (log_likelihood, model)
    return best[1] if best else None


def _hmm_regime(matrix: np.ndarray) -> dict | None:
    """高斯 HMM（对角协方差）识别 3 个市场状态，给出状态、粘性与后验概率。

    状态按**20 日动量**均值排序赋经济含义，而不是按日收益率排序：
    日收益的噪声比 20 日动量大一个量级（√20），用它排序会把「下行」和「震荡」
    排反（实测把单边下跌判成上行）。动量是低噪声的趋势量，排序稳定得多。

    hmmlearn 缺失、训练失败、或拟合退化成无效状态时返回 None。
    """
    try:
        # 手写标准化，避免为了一个 StandardScaler 把 scikit-learn 拉进依赖
        std = matrix.std(axis=0)
        std[std == 0] = 1.0
        z = (matrix - matrix.mean(axis=0)) / std
    except Exception as exc:  # noqa: BLE001
        print(f"[regime] HMM 特征标准化失败: {exc}")
        return None

    model = _fit_hmm(z)
    if model is None:
        print("[regime] HMM 训练失败（含全部重启）")
        return None

    try:
        posterior = np.nan_to_num(model.predict_proba(z)[-1], nan=0.0, posinf=0.0, neginf=0.0)
        total = float(posterior.sum())
        if total <= 0:
            return None
        posterior = posterior / total

        # 退化判别，见 _MAX_STATE_OCCUPANCY / _MIN_STATE_OCCUPANCY / _MIN_STATE_SEPARATION 注释
        states = model.predict(z)
        counts = np.bincount(states, minlength=model.n_components)
        if counts.max() / len(states) > _MAX_STATE_OCCUPANCY:
            print("[regime] HMM 未分出状态（单一状态吞掉整段历史）")
            return None
        if counts.min() / len(states) < _MIN_STATE_OCCUPANCY:
            print("[regime] HMM 存在空状态（状态数超过数据里的 regime 数）")
            return None
        means_mom = [float(model.means_[i][_SORT_FEATURE_IDX]) for i in range(model.n_components)]
        if max(means_mom) - min(means_mom) < _MIN_STATE_SEPARATION:
            print("[regime] HMM 状态在动量上不可区分")
            return None
    except Exception as exc:  # noqa: BLE001
        print(f"[regime] HMM 结果解析失败: {exc}")
        return None

    order = sorted(range(model.n_components), key=lambda i: means_mom[i])
    label_of = {order[0]: "下行", order[-1]: "上行"}
    for idx in order[1:-1]:
        label_of[idx] = "震荡"

    probs = {"上行": 0.0, "震荡": 0.0, "下行": 0.0}
    for idx in range(model.n_components):
        probs[label_of[idx]] += float(posterior[idx])
    score = sum(STATE_BASE_SCORE[label] * prob for label, prob in probs.items())

    current = int(np.argmax(posterior))
    persistence = None
    duration = None
    try:
        self_prob = float(model.transmat_[current][current])
        if math.isfinite(self_prob):
            persistence = round(self_prob, 4)
            if self_prob < 0.999:
                # 期望持续交易日数 E[T] = 1 / (1 - A[i,i])
                duration = round(1.0 / (1.0 - self_prob), 1)
            # self_prob ≈ 1 表示样本区间内该状态从未被打破 —— 此时**不给**「期望天数」：
            # 任何平滑出来的数字都只是状态占用天数的回声，不是真实的转移证据。
    except Exception:  # noqa: BLE001 - 转移矩阵只是附加信息，取不到就算了
        pass

    return {
        "state": label_of[current],
        "regime_score": round(_clamp(score, 0.0, 10.0), 2),
        "method": "hmm",
        "state_probs": {key: round(val, 3) for key, val in probs.items()},
        "state_persistence": persistence,
        "expected_duration": duration,
        "note": None,
    }


def _rule_regime(closes: list[float], note: str | None = None) -> dict:
    """确定性状态判据：均线结构 + 动量 + RSI + 波动放大。

    这是**主判据**。它可复核、可回测、无拟合自由度；实测在含多段 regime 的
    合成样本上 7/7 判对，而同期 HMM 单次拟合只有 3/7 —— 见 compute_regime 的说明。
    """
    arr = [float(c) for c in closes]
    n = len(arr)
    price = arr[-1]

    def _ma(k: int) -> float:
        window = arr[-min(k, n) :]
        return sum(window) / len(window)

    ma20, ma60 = _ma(20), _ma(60)
    ret20 = (price / arr[-21] - 1.0) if n >= 21 and arr[-21] > 0 else 0.0
    ret5 = (price / arr[-6] - 1.0) if n >= 6 and arr[-6] > 0 else 0.0

    span = min(14, n - 1)
    gains = losses = 0.0
    for i in range(n - span, n):
        diff = arr[i] - arr[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += -diff
    if losses > 0:
        rsi = 100.0 - 100.0 / (1.0 + gains / losses)
    else:
        rsi = 100.0 if gains > 0 else 50.0

    rets = [arr[i] / arr[i - 1] - 1.0 for i in range(1, n) if arr[i - 1] > 0]
    vol_recent = float(np.std(rets[-20:])) if len(rets) >= 20 else 0.0
    vol_base = float(np.std(rets[-60:])) if len(rets) >= 60 else vol_recent
    vol_ratio = (vol_recent / vol_base) if vol_base > 0 else 1.0

    score = NEUTRAL_SCORE
    # 均线结构：相等（完全走平）时不加减分，避免本该中性的行情被推成偏空
    if price > ma20 and ma20 > ma60:
        score += 1.2
    elif price < ma20 and ma20 < ma60:
        score -= 1.2
    elif price > ma20:
        score += 0.4
    elif price < ma20:
        score -= 0.4
    score += _clamp(ret20 * 20.0, -1.4, 1.4)
    score += _clamp(ret5 * 25.0, -0.8, 0.8)
    score += _clamp((rsi - 50.0) / 25.0, -0.8, 0.8)
    if vol_ratio > 1.5:
        score -= 0.6  # 波动放大 = 趋势不稳定
    elif vol_ratio < 0.8:
        score += 0.3

    score = round(_clamp(score, 0.0, 10.0), 2)
    state = state_of_score(score)
    return {
        "state": state,
        "regime_score": score,
        "method": "rule",
        "state_probs": {"上行": 1.0 if state == "上行" else 0.0,
                        "震荡": 1.0 if state == "震荡" else 0.0,
                        "下行": 1.0 if state == "下行" else 0.0},
        "state_persistence": None,
        "expected_duration": None,
        "note": note,
    }


def _neutral_regime(note: str) -> dict:
    return {
        "state": "震荡",
        "regime_score": NEUTRAL_SCORE,
        "method": "neutral",
        "state_probs": {"上行": 0.0, "震荡": 1.0, "下行": 0.0},
        "state_persistence": None,
        "expected_duration": None,
        "features": {},
        "note": note,
    }


def compute_regime(closes: list[float], volumes: list[float] | None = None) -> dict:
    """识别市场状态并给出连续状态分（0-10）。数据不足时返回中性结果，不抛异常。

    **分工（这是本模块最重要的设计决定）**

    主判据是确定性规则（``_rule_regime``），HMM 是**一致性交叉验证 + 粘性估计**：

    - 规则可复核、无拟合自由度。实测在含多段 regime 的合成样本上 7/7 判对；
      同期 HMM 单次拟合只有 3/7（常把两段 regime 合并、或留一个空状态，
      再用错位的均值排序给出自信但错误的方向）。
    - 因此不让 HMM 决定方向标签。只有它与规则**判定一致**时，才采用它更细的
      状态概率、自转移概率与期望持续天数（method="rule+hmm"）——两者互相印证，
      这些粘性信息才可信；不一致时记下 HMM 的意见（hmm_state）供复核，仍以规则为准。

    这样方向标签的正确性由可复核的规则保证，而 HMM 只在被印证时贡献它的粘性信息。
    """
    if not closes or len(closes) < 60:
        return _neutral_regime("指数K线不足 60 根")

    regime = _rule_regime(closes)

    built = _build_features(closes, volumes)
    if built is None:
        regime["features"] = {}
        regime["hmm_state"] = None
        regime["note"] = regime["note"] or "特征样本不足，仅用规则状态"
        return regime

    matrix, features = built
    regime["features"] = features
    hmm = _hmm_regime(matrix)

    if hmm is None:
        regime["hmm_state"] = None
        regime["note"] = regime["note"] or "HMM 不可用或拟合无效，仅用规则状态"
        return regime

    regime["hmm_state"] = hmm["state"]
    regime["hmm_state_probs"] = hmm["state_probs"]
    if hmm["state"] != regime["state"]:
        regime["note"] = (
            f"HMM 倾向「{hmm['state']}」与规则「{regime['state']}」不一致，以规则为准"
        )
        return regime

    # 两者一致：采用 HMM 的后验概率与粘性估计（互相印证的置信更高）
    regime["method"] = "rule+hmm"
    regime["state_probs"] = hmm["state_probs"]
    regime["state_persistence"] = hmm["state_persistence"]
    regime["expected_duration"] = hmm["expected_duration"]
    regime["note"] = None
    return regime


# ---------------- 市场宽度 ----------------

def compute_breadth(rows: list[dict], prev_amount_yi: float | None = None) -> dict | None:
    """从全市场快照计算市场宽度：涨跌家数比 / 涨停跌停家数 / 成交额环比。

    ``rows`` 为 quad_service 全市场快照结构（code / change_pct / amount_yi）。
    ``prev_amount_yi`` 为上一交易日全市场成交额（亿），用于算环比；缺失则该维度不计分。
    """
    if not rows:
        return None

    up = down = flat = limit_up = limit_down = 0
    total_amount = 0.0
    for row in rows:
        code = str(row.get("code") or "")
        if code.startswith(_BJ_PREFIXES):
            continue
        change = _yf(row.get("change_pct"))
        if change is None:
            continue
        amount = _yf(row.get("amount_yi"))
        if amount:
            total_amount += amount

        if change >= LIMIT_PCT:
            limit_up += 1
        elif change <= -LIMIT_PCT:
            limit_down += 1
        if change > 0:
            up += 1
        elif change < 0:
            down += 1
        else:
            flat += 1

    denominator = up + down
    if denominator <= 0:
        return None
    ratio = up / denominator
    total_amount = round(total_amount, 0)

    amount_change = None
    prev_amount = _yf(prev_amount_yi)
    if prev_amount and prev_amount > 0:
        amount_change = round((total_amount / prev_amount - 1.0) * 100.0, 1)

    score = NEUTRAL_SCORE
    score += _clamp((ratio - 0.5) * 16.0, -3.0, 3.0)          # 涨跌家数比：多空力量
    score += _clamp((limit_up - limit_down) / 40.0, -1.5, 1.5)  # 涨停跌停净额：赚钱效应
    if amount_change is not None:
        score += _clamp(amount_change / 20.0, -1.0, 1.0)        # 成交额环比：资金参与度

    return {
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "up_down_ratio": round(ratio, 3),
        "limit_up_count": limit_up,
        "limit_down_count": limit_down,
        "total_amount_yi": total_amount,
        "amount_change_pct": amount_change,
        "breadth_score": round(_clamp(score, 0.0, 10.0), 2),
        "sample_size": up + down + flat,
    }


async def _spot_rows(force: bool = False) -> list[dict]:
    """全市场快照：与四维榜同源，走 _get_spot 三层回退（内存 → Supabase 热快照 → 真拉+冷却）。

    此前直连 quad_service._full_spot 同步直拉，行情源被风控时这条路径也会撞上去
    （冷却对本函数不生效）。改后共享缓存与冷却，失败快速返回。
    """
    from app.services import quad_service  # 延迟导入：避免服务间循环依赖

    return await quad_service.get_full_spot(force)


async def fetch_breadth(prev_amount_yi: float | None = None) -> dict | None:
    """取市场宽度。失败返回 None —— 宽度只是附加证据，绝不能拖垮方向预测。"""
    try:
        rows = await _spot_rows()
    except Exception as exc:  # noqa: BLE001
        print(f"[regime] 全市场快照获取失败，市场宽度缺失: {exc}")
        return None
    return compute_breadth(rows, prev_amount_yi=prev_amount_yi)


# ---------------- 方向分合成 ----------------

def blend_evidence(regime_score: float | None, breadth_score: float | None) -> float:
    """证据分 = 状态分 + 宽度修正。

    宽度只做**有限**修正（最多 ±1.2）：它是日频情绪指标，极端宽度本身有均值回复属性，
    让它压过状态分会把方向重新变敏感。
    """
    regime = NEUTRAL_SCORE if regime_score is None else float(regime_score)
    tilt = 0.0
    if breadth_score is not None:
        tilt = _clamp(
            (float(breadth_score) - NEUTRAL_SCORE) * 0.35, -BREADTH_MAX_TILT, BREADTH_MAX_TILT
        )
    return round(_clamp(regime + tilt, 0.0, 10.0), 2)


def llm_contribution(llm_score: float | None) -> float:
    """LLM 分相对中性 5.0 的修正量（已被 ±LLM_MAX_ADJUST 截断）。

    LLM 给 5.0 时修正为 0 —— 等价于「不改变系统结论」，这是 prompt 里
    反复强调的默认行为；给 8.0 和给 6.0 的效果完全相同（都会被截断）。
    """
    score = _yf(llm_score)
    if score is None:
        return 0.0
    return round(
        _clamp((1.0 - EVIDENCE_WEIGHT) * (score - NEUTRAL_SCORE), -LLM_MAX_ADJUST, LLM_MAX_ADJUST),
        2,
    )


def blend_direction_score(evidence_score: float | None, llm_score: float | None = None) -> float:
    """最终方向分 = 证据分 + LLM 微调量（LLM 权重 0.3、单独影响力上限 ±0.5）。

    这里**故意不对证据分做 0.7 收缩**。``SCORE_UP / SCORE_DOWN`` 是照证据分的量纲
    标定的（三个状态基准分 3.2 / 5.0 / 6.8）。若按 ``0.7 × 证据 + 0.3 × 中性`` 收缩，
    上行的 6.8 会变成 6.26，与阈值 6.2 只差 0.06 —— 一点点扰动就能把标签从「上涨」
    打回「震荡」，等于把好不容易修掉的抖动又装回去。所以证据分原样传递，
    LLM 只在其上叠加一个受限的修正量。
    """
    evidence = NEUTRAL_SCORE if evidence_score is None else float(evidence_score)
    return round(_clamp(evidence + llm_contribution(llm_score), 0.0, 10.0), 2)


def _label_band(direction: str) -> tuple[float, float]:
    """方向标签对应的分数带（闭区间）。"""
    if direction == "上涨":
        return SCORE_UP, 10.0
    if direction == "下跌":
        return 0.0, SCORE_DOWN
    # 中间带在 score_to_direction 里是「非两侧」的补集，留一点余量避免贴边
    return SCORE_DOWN + _BAND_EPS, SCORE_UP - _BAND_EPS


def resolve_direction(
    evidence_score: float | None,
    llm_score: float | None = None,
    prev_score: float | None = None,
) -> tuple[str, float]:
    """方向的**唯一出口**：返回 (方向标签, 方向分)。

    1. ``方向标签 = score_to_direction(证据分)`` —— 只由量化证据决定。
       LLM 与昨日惯性都**不能**改变标签：否则一次异常的 LLM 输出或一次平滑滞后
       就能把方向翻过去，正是在修的那个问题。
    2. ``方向分 = 证据分 + LLM 微调 → 惯性平滑 → 夹回标签对应的分数带``。
       夹回是保证「分」与「标签」永远自洽 —— 不会出现方向=上涨但分数=5.3 这种展示矛盾。
       惯性只在**带内**生效：证据分一旦穿过 SCORE_UP / SCORE_DOWN，分与标签会一起切到新带。
       这是刻意的：把惯性加到证据分上，会让一次真实的 regime 反转拖好几天才反映出来
       （每天只能挪 1.0 分），反而更危险。稳定性由 HMM 状态本身的粘性提供，
       惯性只负责抑制带内的分数噪声（即仓位不要随分数抖动而跳档）。
    """
    evidence = NEUTRAL_SCORE if evidence_score is None else float(evidence_score)
    direction = score_to_direction(evidence)
    score = blend_direction_score(evidence, llm_score)
    score = apply_inertia(score, prev_score)
    low, high = _label_band(direction)
    return direction, round(_clamp(score, low, high), 2)


def apply_inertia(score: float, prev_score: float | None) -> float:
    """相对昨日方向分做平滑，并硬性限制单日跳变。

    - 平滑：``0.6 × 今日 + 0.4 × 昨日``，抑制单次采样的小幅摆动
    - 硬约束：平滑后若与昨日相差超过 ``MAX_DAILY_JUMP``，按上限收敛
      —— 方向可以变，但不允许一天之内从看多翻成看空
    """
    score = float(score)
    prev = _yf(prev_score)
    if prev is None:
        return round(_clamp(score, 0.0, 10.0), 2)

    smoothed = (1.0 - INERTIA_PREV_WEIGHT) * score + INERTIA_PREV_WEIGHT * prev
    delta = smoothed - prev
    if abs(delta) > MAX_DAILY_JUMP:
        smoothed = prev + math.copysign(MAX_DAILY_JUMP, delta)
    return round(_clamp(smoothed, 0.0, 10.0), 2)
