import { AlertTriangle, Crown, Users } from "lucide-react";
import { pnlTone, scoreBg } from "../../lib/tone";
import { CELL, SUB, TEXT } from "../../lib/ui";
import type { VanguardBoard, VanguardLeader, VanguardSector } from "../../types";
import Button from "../ui/Button";
import Table, { Th } from "../ui/Table";
import { HERDING_LABEL, herdingTone, PctText, YiText } from "./shared";

/**
 * 市场层三块：板块强度、主力抱团、潜力龙头。
 *
 * 它们的共同点是**都建立在「当日横截面分位」上**（见后端 `_pct_rank`）：
 * 分位回答「今天这个板块相对其他板块强不强」，换一天就换一套基准，
 * 因此**不能跨日比较**，也不能当成绝对强度。这句话必须出现在界面上，不然
 * 用户会把「强度 8.0」当成一个稳定的板块评级。
 */

function StrengthBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score * 10));
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-raised">
        <div className={`h-full rounded-full ${scoreBg(score)}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-meta font-semibold text-ink">{score.toFixed(1)}</span>
    </div>
  );
}

interface SectorProps {
  data: VanguardBoard;
}

/** 板块强度多维表。行业字段不可用时给明确原因，而不是渲染一张空表。 */
export function SectorTable({ data }: SectorProps) {
  const sectors: VanguardSector[] = data.sectors;

  if (!data.sector_field_available) {
    return (
      <div className="rounded-lg border border-state-warn-line bg-state-warn-surface px-3 py-2 text-meta text-state-warn-soft">
        <AlertTriangle className="mr-1 inline h-3 w-3" aria-hidden />
        本次没有取到行业字段（东财返回值缺少 f100 列时会发生），板块强度**无法计算**。
        这是数据缺失，不是「今天没有强势板块」。
      </div>
    );
  }
  if (sectors.length === 0) {
    return <p className="text-body text-ink-soft">今日资金流批次里没有形成可统计的板块（每板块至少 2 只）。</p>;
  }

  return (
    <Table
      label="板块强度榜"
      minWidth={780}
      maxHeight="sm"
      head={
        <tr>
          <Th>#</Th>
          <Th>板块</Th>
          <Th align="right">均值涨跌</Th>
          <Th align="right">净流入</Th>
          <Th align="center">上涨/成员</Th>
          <Th align="center">涨停</Th>
          <Th align="center">最高板</Th>
          <Th align="center">强度</Th>
          <Th>标签</Th>
        </tr>
      }
    >
      {sectors.map((s, i) => (
        <tr key={s.sector} className="border-t border-surface-line-soft hover:bg-surface-inset/60">
          <td className={`${CELL} text-meta text-ink-muted`}>{i + 1}</td>
          <td className={CELL}>
            <span className="font-medium text-ink-strong">{s.sector}</span>
            <div className="text-meta text-ink-muted">
              资金 <b className="text-ink-muted">{s.dims.money.toFixed(1)}</b> · 动量{" "}
              <b className="text-ink-muted">{s.dims.momentum.toFixed(1)}</b> · 广度{" "}
              <b className="text-ink-muted">{s.dims.breadth.toFixed(1)}</b>
            </div>
          </td>
          <td className={`${CELL} text-right`}>
            <PctText v={s.avg_change_pct} />
          </td>
          <td className={`${CELL} text-right`}>
            <YiText v={s.net_inflow_yi} />
          </td>
          <td className={`${CELL} text-center text-meta text-ink-soft`}>
            {s.up_count}/{s.member_count}
          </td>
          <td className={`${CELL} text-center text-meta ${s.limitup_count > 0 ? "text-ink-strong" : "text-ink-muted"}`}>
            {s.limitup_count}
          </td>
          <td className={`${CELL} text-center text-meta text-ink-soft`}>{s.max_boards || "—"}</td>
          <td className={`${CELL} text-center`}>
            <div className="flex justify-center">
              <StrengthBar score={s.strength_score} />
            </div>
          </td>
          <td className={CELL}>
            <div className="flex flex-wrap gap-1">
              {s.tags.map((t) => (
                <span key={t} className="rounded-md bg-surface-raised px-1 py-0.5 text-meta leading-none text-ink-soft">
                  {t}
                </span>
              ))}
            </div>
          </td>
        </tr>
      ))}
    </Table>
  );
}

/** 主力抱团：涨停板块集中度 + 板块资金净流入占比的合读。 */
export function HerdingCard({ data }: { data: VanguardBoard }) {
  const h = data.herding;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className={`text-num font-bold ${herdingTone(h.level)}`}>{HERDING_LABEL[h.level] ?? h.level}</span>
        {h.score != null && <span className="text-body text-ink-soft">抱团读数 {h.score.toFixed(1)} / 10</span>}
        {h.limitup_total != null && <span className="text-meta text-ink-muted">当日涨停 {h.limitup_total} 家</span>}
      </div>

      <p className="text-body text-ink-soft">{h.note}</p>

      <div className={`${SUB} px-3 py-2 text-meta text-ink-muted`}>
        两个代理口径：① 涨停池板块集中度（抱团的**结果**）② 前 3 板块占全部正净流入板块的比例（抱团的**动作**）。
        真正的抱团要看席位与持仓，本项目拿不到 —— 因此这里只到「代理」层级，不能据此认定主力行为。
      </div>

      {h.top_sectors.length > 0 && (
        <div>
          <p className={`mb-1.5 ${TEXT.label}`}>情绪最集中的板块</p>
          <div className="space-y-1">
            {h.top_sectors.map((s) => (
              <div
                key={s.sector}
                className="flex flex-wrap items-center gap-x-3 gap-y-0.5 rounded-lg bg-surface-inset px-3 py-1.5 text-meta"
              >
                <span className="font-medium text-ink">{s.sector}</span>
                <span className="text-ink-muted">涨停 {s.limitup_count} 家</span>
                {s.max_boards > 0 && <span className="text-ink-muted">最高 {s.max_boards} 板</span>}
                <span className="text-ink-muted">
                  板块资金 <YiText v={s.net_inflow_yi} />
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface LeaderProps {
  data: VanguardBoard;
  onPick: (codes: string[]) => void;
  onDiagnose: (code: string) => void;
}

/** 潜力龙头：资金已进场、趋势成立、且尚未被拉到买不进的候选。 */
export function LeadersList({ data, onPick, onDiagnose }: LeaderProps) {
  const leaders: VanguardLeader[] = data.leaders;

  if (leaders.length === 0) {
    return (
      <p className="text-body text-ink-soft">
        今日没有同时满足「主力净占比达标 + 趋势成立 + 距高点不超 30% + 涨幅低于 9%」的标的。
        这是筛选条件的结果，不是「今天没有龙头」。
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {leaders.map((l) => (
        <div key={l.code} className={`${SUB} px-3 py-2`}>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Crown className="h-3.5 w-3.5 shrink-0 text-brand-light" aria-hidden />
            <span className="font-medium text-ink-strong">{l.name}</span>
            <span className="text-meta text-ink-muted">{l.code}</span>
            {l.sector && <span className="text-meta text-ink-muted">{l.sector}</span>}
            <span className="text-meta text-ink">
              {l.price.toFixed(2)}{" "}
              <span className={pnlTone(l.change_pct)}>
                {l.change_pct >= 0 ? "+" : ""}
                {l.change_pct.toFixed(2)}%
              </span>
            </span>
            <span className="text-meta text-ink-muted">
              资金 <b className="text-ink">{l.dark_money.toFixed(1)}</b> · 趋势{" "}
              <b className="text-ink">{l.trend.toFixed(1)}</b> · 综合{" "}
              <b className="text-ink">{l.overall_score.toFixed(2)}</b>
            </span>
            <div className="ml-auto flex items-center gap-1">
              <Button variant="ghost" size="xs" onClick={() => onDiagnose(l.code)}>
                诊股
              </Button>
              <Button variant="outlineQuiet" size="xs" onClick={() => onPick([l.code])}>
                深度分析
              </Button>
            </div>
          </div>
          <p className="mt-1 text-meta text-ink-soft">{l.reason}</p>
        </div>
      ))}
      <p className="text-meta text-ink-soft">
        <Users className="mr-1 inline h-3 w-3" aria-hidden />
        「龙头」在这里是**筛选结果**（资金 + 趋势 + 位置），不是对市场地位的认定，也不构成买入建议。
        涨幅 ≥9% 的标的已剔除 —— 它们大概率一字或秒板，列出来只会导向一个买不进的价格。
      </p>
    </div>
  );
}
