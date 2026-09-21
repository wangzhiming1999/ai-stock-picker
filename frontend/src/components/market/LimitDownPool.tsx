import { TEXT } from "../../lib/ui";
import { downTone } from "../../lib/tone";
import type { LimitDownLadderGroup, LimitDownSnapshot, LimitDownStock } from "../../types";
import { downPositionChip } from "./constants";

/**
 * 跌停带「跌停池列表」一侧的展示件（个股芯片 + 连续跌停梯队 + 板块聚集度）。
 *
 * 跌停这条带子是**只读观察层**：结论是负期望（跌停次日抄底实测 −4.47%/次，n=133），
 * 所以它**不能出现任何动作词**（买/卖/建议/机会），亏损数字走绿（跌=绿），
 * 且不进一级导航。这些刻意的，不是遗漏。本组组件只做位置描述与风险读数。
 */

function StockChip({ t }: { t: LimitDownStock }) {
  // 位置标注缺失时降级成「未知」而不是渲染空白：滚动发布期间前端可能连到旧后端，
  // 一个字段缺失不该让整段梯队失效（与 TacticCell / TacticHit 的兜底同思路）。
  const position = t.position ?? { tag: "未知", reason: "位置标注缺失" };
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-lg bg-surface-inset/60 px-2 py-1 text-meta"
      title={`${position.reason}｜封单 ${t.seal_fund_yi} 亿｜流通 ${t.float_mv_yi} 亿｜封单比 ${t.seal_ratio}%`}
    >
      <span className="text-ink">{t.name}</span>
      <span className="text-ink-muted">{t.code}</span>
      {t.down_days > 1 && <span className={downTone(400)}>{t.down_days} 连跌</span>}
      <span className="text-ink-muted">换手 {t.turnover}%</span>
      <span className={`rounded-md px-1 text-meta ${downPositionChip(position.tag)}`}>{position.tag}</span>
    </span>
  );
}

function LadderSection({ ladder }: { ladder: LimitDownLadderGroup[] }) {
  if (ladder.length === 0) return null;
  const max = Math.max(...ladder.map((g) => g.count), 1);
  return (
    <div>
      <h3 className={TEXT.label}>连续跌停梯队（位置描述 · 非买点）</h3>
      <div className="mt-2 space-y-1.5">
        {ladder.map((g) => (
          <div key={g.key} className="flex items-center gap-2">
            <span className="w-16 shrink-0 text-meta text-ink-muted">{g.label}</span>
            <span className="w-10 shrink-0 text-right text-meta font-semibold text-ink">{g.count}</span>
            <span
              className="h-2 shrink-0 rounded-full bg-green-600/70"
              style={{ width: `${Math.max((g.count / max) * 100, 3)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-3 space-y-2">
        {ladder.map((g) => (
          <div key={g.key}>
            <div className="mb-1 text-meta text-ink-muted">
              {g.label} · {g.count} 只
            </div>
            <div className="flex flex-wrap gap-1.5">
              {g.items.map((t) => (
                <StockChip key={t.code} t={t} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SectorSection({ snapshot }: { snapshot: LimitDownSnapshot }) {
  if (snapshot.sectors.length === 0) return null;
  return (
    <div>
      <h3 className={TEXT.label}>跌停板块聚集度（当日跌停家数排序）</h3>
      <div className="mt-2 space-y-1">
        {snapshot.sectors.slice(0, 6).map((s) => (
          <div key={s.sector} className="flex items-center justify-between gap-2 text-meta">
            <span className="truncate text-ink-soft">{s.sector}</span>
            <span className="shrink-0 text-ink-muted">
              跌停 <span className={downTone(400)}>{s.count}</span> 家 · 连跌{" "}
              <span className={downTone(400)}>{s.chain_count}</span> 家 · 最长{" "}
              <span className="text-ink">{s.max_down_days}</span> 日 · 封单{" "}
              <span className="text-ink">{s.seal_fund_yi}</span> 亿
            </span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-meta leading-relaxed text-ink-faint">
        这里的家数**与涨停侧方向相反**：涨停板块家数多是资金抱团做多，跌停板块家数多是板块级利空。
        回测显示聚集度越高次日反而越差（≥5 家期望 −7.17%），所以它是风险读数，不是机会读数。
      </p>
    </div>
  );
}

export { LadderSection, SectorSection, StockChip };
