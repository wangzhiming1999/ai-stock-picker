import type { BriefingTactics } from "../../types";
import { SUB_QUIET, TEXT } from "../../lib/ui";
import { TacticChips, TacticTakeaway } from "../TacticHit";

/** 形态命中块：持仓偏风险（优先处理），关注池偏买点 */
export function TacticsBlock({ tactics, onPick }: { tactics: BriefingTactics; onPick: (codes: string[]) => void }) {
  const groups = [
    { key: "holdings", label: "持仓形态信号", hint: "偏卖出 / 风险，优先处理", items: tactics.holdings ?? [] },
    { key: "morning", label: "关注池形态命中", hint: "偏买点，需结合买点与止损", items: tactics.morning ?? [] },
  ].filter((g) => g.items.length > 0);

  if (groups.length === 0) return null;

  return (
    <>
      {tactics.summary && <p className="text-meta leading-relaxed text-ink-muted">{tactics.summary}</p>}
      <div className="mt-2 space-y-2">
        {groups.map((g) => (
          <div key={g.key}>
            <div className={TEXT.meta}>
              {g.label} · {g.hint}
            </div>
            <div className="mt-1 space-y-1">
              {g.items.map((it) => (
                <button
                  key={it.code}
                  onClick={() => onPick([it.code])}
                  className={`${SUB_QUIET} w-full px-2 py-1.5 text-left transition-colors hover:bg-surface-inset/70`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-meta font-medium text-ink-strong">{it.name}</span>
                    <span className={TEXT.meta}>{it.code}</span>
                    <TacticChips tactics={it.tactics} />
                  </div>
                  <div className="mt-0.5 text-meta leading-relaxed text-ink-muted">
                    <TacticTakeaway tactics={it.tactics} />
                  </div>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
