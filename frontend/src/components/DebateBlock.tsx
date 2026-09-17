import { Minus, ShieldAlert } from "lucide-react";
import { downTone, divergenceTone, upTone } from "../lib/tone";
import { SUB_QUIET, TEXT } from "../lib/ui";
import type { DebateResult, DebateSide } from "../types";

interface SideProps {
  side: DebateSide;
}

/**
 * 单边研究员卡片。
 *
 * 多/空立场标签走 upTone / downTone（红涨绿跌是方向语义，§6 收口）；
 * 但信心值、论据列表一律中性 ink —— 它们是「论证质量」，不占红绿（§8）。
 */
function SideCard({ side }: SideProps) {
  const isBull = side.side === "bull";
  return (
    <div className={`${SUB_QUIET} p-3`}>
      <div className="flex items-center justify-between">
        <span className={`flex items-center gap-1.5 text-xs font-semibold ${isBull ? upTone() : downTone()}`}>
          {isBull ? "多头研究员" : "空头研究员"}
        </span>
        <span className={`text-xs tabular-nums ${TEXT.meta}`}>
          信心 <span className="font-semibold text-ink">{side.confidence.toFixed(0)}</span>
        </span>
      </div>
      <p className={`mt-1.5 text-sm leading-relaxed ${TEXT.body}`}>{side.thesis || "—"}</p>
      {side.evidence.length > 0 && (
        <ul className={`mt-2 space-y-1 text-xs leading-relaxed ${TEXT.meta}`}>
          {side.evidence.map((e, i) => (
            <li key={i} className="flex gap-1.5">
              <span className="text-ink-faint">·</span>
              <span>{e}</span>
            </li>
          ))}
        </ul>
      )}
      {side.rebuttal.length > 0 && (
        <div className={`mt-2 border-t border-slate-800/60 pt-2`}>
          <p className="text-xs font-medium text-ink-muted">对对方的反驳</p>
          <ul className={`mt-1 space-y-1 text-xs leading-relaxed ${TEXT.meta}`}>
            {side.rebuttal.map((r, i) => (
              <li key={i} className="flex gap-1.5">
                <Minus className="mt-0.5 h-3 w-3 shrink-0 text-ink-faint" aria-hidden />
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

const DIVERGENCE_LABEL = ["共识较强", "存在分歧", "高度分歧"] as const;

function divergenceLabel(v: number): string {
  if (v >= 60) return DIVERGENCE_LABEL[2];
  if (v >= 30) return DIVERGENCE_LABEL[1];
  return DIVERGENCE_LABEL[0];
}

interface Props {
  debate: DebateResult;
}

/**
 * 多空研究员辩论结果块（debate_service）。
 *
 * ⚠️ 定位是「分歧与风险提示」，不是买卖点：后端 executable 恒为 false、
 * 证据等级 unknown。gate_note 必须原样展示 —— 这块如果哪天被顺手改成了
 * 买点卡片的样子，就是证据闸门（§8）被绕过的信号。
 */
export default function DebateBlock({ debate }: Props) {
  if (!debate.bull || !debate.bear) return null;

  return (
    <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      {/* 头部：标题 + 轮数 + 分歧度 + 可信度角标 */}
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-ink">多空研究员对辩</h4>
        <span className={`rounded-md bg-slate-800/60 px-1.5 py-0.5 text-xs ${TEXT.meta}`}>
          {debate.rounds} 轮
        </span>
        <span className={`text-xs font-medium tabular-nums ${divergenceTone(debate.divergence)}`}>
          分歧度 {debate.divergence.toFixed(0)} · {divergenceLabel(debate.divergence)}
        </span>
        <span className="ml-auto rounded-md bg-slate-800/60 px-1.5 py-0.5 text-xs text-ink-muted">
          {debate.evidence?.badge ?? "观察"}
        </span>
      </div>

      {/* 核心分歧 */}
      {debate.key_disagreement && (
        <p className={`mt-2 text-xs leading-relaxed ${TEXT.meta}`}>
          <span className="font-medium text-ink-muted">核心分歧：</span>
          {debate.key_disagreement}
        </p>
      )}

      {/* 双方论证 */}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <SideCard side={debate.bull} />
        <SideCard side={debate.bear} />
      </div>

      {/* 闸门文案：原样展示，不得删改 */}
      {debate.gate_note && (
        <p className={`mt-3 flex items-start gap-1.5 text-xs leading-relaxed ${TEXT.meta}`}>
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" aria-hidden />
          <span>{debate.gate_note}</span>
        </p>
      )}
    </div>
  );
}
