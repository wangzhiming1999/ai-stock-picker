import { useCallback, useEffect, useState } from "react";
import { Crosshair, Gauge, Layers, RefreshCw, Target, Timer, TrendingUp, Users } from "lucide-react";
import { fetchVanguardBoard } from "../api/client";
import { STACK, STACK_TIGHT } from "../lib/ui";
import type { VanguardBoard } from "../types";
import Button from "./ui/Button";
import CollapsiblePanel from "./ui/CollapsiblePanel";
import Panel from "./ui/Panel";
import BoardTable from "./vanguard/BoardTable";
import WidePoolTable from "./vanguard/WidePoolTable";
import DiagnoseCard from "./vanguard/DiagnoseCard";
import { HerdingCard, LeadersList, SectorTable } from "./vanguard/MarketLayer";
import { EvidenceBadge, EvidenceNote, FundFlowNotice } from "./vanguard/shared";

interface Props {
  onPick: (codes: string[]) => void;
}

const DIM_ICON = {
  dark_money: Layers,
  trend: TrendingUp,
  activity: Gauge,
} as const;

const DIAGNOSE_ANCHOR = "vanguard-diagnose";

/**
 * 选机会 · 决策（决策先锋）
 *
 * ## 这一页回答什么
 * 「今天的钱在往哪去、谁跟着走，以及我在什么价位介入」。与「推荐」互补：
 * 推荐偏静态质地（模型对个股综合打分），决策偏当日行为（资金 / 趋势 / 活跃度三维）。
 *
 * ## 五块内容
 *   ① 三维选股榜 —— 主表，可展开看逐维点评与结构位
 *   ② 板块强度   —— 当日横截面分位合成（资金 / 动量 / 广度 / 情绪）
 *   ③ 主力抱团   —— 涨停板块集中度 + 板块资金集中度（两个代理口径）
 *   ④ 潜力龙头   —— 资金已进场、趋势成立且尚未买不进的候选
 *   ⑤ 三维诊股   —— 单票体检；与全局「深度分析」（LLM 辩论）分工不同
 *
 * ## 两条不能破的约束
 * 1. **刷新不碰行情源**。本页的 refresh 只穿透后端榜单缓存；底层全市场快照与资金流
 *    都走既有缓存与跨实例冷却，因此这里**不需要** spotGuard 那套「强制刷新」确认闸门
 *    （四维榜需要，因为它的 refresh 会一路 force 到底层）。
 * 2. **读数不是指令**。三维分 / 板块强度 / 抱团 / 龙头全是读数，证据档 preliminary；
 *    买卖时机的结构位来自 monitor_levels，其买入侧实测为负（unsupported）。
 *    这个页面上任何一处都不得出现「建议买入」一类措辞。
 */
export default function VanguardPanel({ onPick }: Props) {
  const [data, setData] = useState<VanguardBoard | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [diagCode, setDiagCode] = useState<string | null>(null);
  const [diagReq, setDiagReq] = useState(0);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setErr("");
    try {
      setData(await fetchVanguardBoard(refresh));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const diagnose = useCallback((code: string) => {
    setDiagCode(code);
    setDiagReq((n) => n + 1);
    document.getElementById(DIAGNOSE_ANCHOR)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const refreshBtn = (
    <Button variant="outlineQuiet" size="sm" onClick={() => void load(true)} disabled={loading}>
      <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
      {loading ? "重算中..." : "刷新"}
    </Button>
  );

  return (
    <div className={STACK}>
      <Panel
        icon={Crosshair}
        title="决策先锋"
        actions={refreshBtn}
        meta={data ? `${data.date} 收盘 · ${data.headline}` : "每日更新"}
      >
        <div className={STACK_TIGHT}>
          {/* 三维口径说明：**一行 inline**，不是三张卡。
              原先三张 `rounded-xl bg-surface-inset px-3 py-2` 的卡只写了口径名、
              没给任何数字，却占了约 60px 高 —— 等于用卡片的视觉权重装了一句注释。
              这里压成一行带分隔的说明，视觉上归到「注释」层级，把首屏让给榜单。 */}
          <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-meta text-ink-muted">
            {(data?.dims ?? [
              { key: "dark_money", label: "暗盘资金", desc: "主力净流入（大单口径）" },
              { key: "trend", label: "趋势", desc: "均线 · 斜率 · 位置 · MACD" },
              { key: "activity", label: "活跃度", desc: "分层换手 · 量比 · 成交额" },
            ]).map((d) => {
              const Icon = DIM_ICON[d.key as keyof typeof DIM_ICON] ?? Layers;
              return (
                <li key={d.key} className="flex items-center gap-1.5">
                  <Icon className="h-3.5 w-3.5 shrink-0 text-brand-light" aria-hidden />
                  <span className="font-medium text-ink-soft">{d.label}</span>
                  <span>{d.desc}</span>
                </li>
              );
            })}
          </ul>

          {data && <FundFlowNotice status={data.fund_flow.status} covered={data.fund_flow.covered} note={data.fund_flow.note} />}
          {data && <EvidenceNote evidence={data.evidence} />}
        </div>
      </Panel>

      {err && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">
          <span className="min-w-0 flex-1">{err}</span>
          <Button variant="outlineQuiet" size="xs" onClick={() => void load()}>
            重试
          </Button>
        </div>
      )}

      {!data && !err && (
        <p className="text-body text-ink-soft">
          正在计算三维榜：首次生成会拉取一次资金流批次与数十只 K 线，约需 1~2 分钟；
          之后当日整日命中缓存秒回。
        </p>
      )}

      {data && (
        <>
          <CollapsiblePanel
            id="vanguard-board"
            title="三维选股榜"
            badge={<EvidenceBadge evidence={data.evidence} />}
            subtitle={`暗盘资金 · 趋势 · 活跃度加权排序 Top ${data.items.length} · 候选池 ${data.pool_size} 只 · 点行勾选、点箭头展开明细`}
            defaultOpen
            action={refreshBtn}
          >
            {data.items.length === 0 ? (
              <p className="text-body text-ink-soft">今日没有通过硬过滤与精算的标的。</p>
            ) : (
              <BoardTable data={data} onPick={onPick} onDiagnose={diagnose} />
            )}
          </CollapsiblePanel>

          <CollapsiblePanel
            id="vanguard-sector"
            title="板块强度"
            subtitle="资金 / 动量 / 广度 / 情绪四维的当日横截面分位合成 —— 分位换日即换基准，不可跨日比较"
            defaultOpen={false}
          >
            <SectorTable data={data} />
          </CollapsiblePanel>

          <CollapsiblePanel
            id="vanguard-wide-pool"
            title="宽池候选"
            subtitle="廉价预筛（无 K 线）的更广候选面，点行可送三维诊股；「精算」标记=进入 K 线精算、带三维分"
            defaultOpen={false}
          >
            <WidePoolTable data={data} onDiagnose={diagnose} />
          </CollapsiblePanel>

          <CollapsiblePanel
            id="vanguard-herding"
            title="主力抱团监测"
            subtitle="涨停板块集中度与板块资金集中度的合读（两个代理口径，不是席位数据）"
            defaultOpen={false}
          >
            <HerdingCard data={data} />
          </CollapsiblePanel>

          <CollapsiblePanel
            id="vanguard-leader"
            title="潜力龙头"
            subtitle="资金已进场 · 趋势成立 · 距高点不超 30% · 涨幅低于 9%（剔除买不进的标的）"
            defaultOpen={false}
            action={
              data.leaders.length > 0 ? (
                <Button variant="outlineQuiet" size="sm" onClick={() => onPick(data.leaders.map((l) => l.code))}>
                  全部送深度分析 →
                </Button>
              ) : undefined
            }
          >
            <LeadersList data={data} onPick={onPick} onDiagnose={diagnose} />
          </CollapsiblePanel>

          <div id={DIAGNOSE_ANCHOR}>
            <CollapsiblePanel
              id="vanguard-diagnose"
              title="三维诊股"
              subtitle="单票体检：三维分 + 结构位 + 所属板块强度。只给读数，多空结论在「深度分析」抽屉里"
              defaultOpen={false}
            >
              <DiagnoseCard code={diagCode} requestId={diagReq} />
            </CollapsiblePanel>
          </div>

          <CollapsiblePanel
            id="vanguard-timing"
            title="买卖时机 · 结构位"
            badge={<EvidenceBadge evidence={data.timing?.evidence} />}
            subtitle="支撑 / 压力 / 止损锚定结构位，不随现价漂移；买入侧实测为负，只作价位参考"
            defaultOpen={false}
          >
            <div className={STACK_TIGHT}>
              <p className="text-body text-ink-soft">{data.timing?.note}</p>
              <ul className="space-y-1 text-meta leading-relaxed text-ink-faint">
                <li className="flex items-start gap-1.5">
                  <Target className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span>
                    每个价位在各行展开明细里查看。买卖点是结构位而不是「现价 × 系数」——后者会让挂单价
                    每天跟着现价平移，实测超过七成样本退化成现价 ∓1%。
                  </span>
                </li>
                <li className="flex items-start gap-1.5">
                  <Timer className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span>本页不做盘中轮询：结构位来自日线，盯实时买卖点请用「今日作战 → 盯盘」。</span>
                </li>
              </ul>
            </div>
          </CollapsiblePanel>

          {/* 页脚免责：降到最低视觉权重 —— 它是合规说明，不该和读数抢注意力 */}
          <p className="flex items-start gap-1.5 px-1 text-meta text-ink-faint">
            <Users className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            本页全部为统计读数与规则打分，不是投资建议；三维榜尚未做收益回测，证据档为「初步」。
          </p>
        </>
      )}
    </div>
  );
}
