import type { LimitUpRelayStock } from "../../types";

interface Props {
  hits: LimitUpRelayStock[];
}

/**
 * 「持仓 ∩ 当日连板」提示块：封板质量差的排最前，走弱时减仓优先级最高。
 * 措辞只讲资金面强弱与观察点，不下卖单指令（与后端证据闸门口径一致）。
 */
export default function RelayHits({ hits }: Props) {
  return (
    <div className="mb-3 rounded-xl border border-orange-900/50 bg-orange-950/20 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-orange-300">持仓连板对照</span>
        <span className="text-xs text-ink-faint">
          {hits.length} 只在当日连板池 · 按封板质量从弱到强
        </span>
      </div>
      <div className="mt-2 space-y-1">
        {hits.map((r) => (
          <div key={r.code} className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-medium text-ink-strong">{r.name}</span>
            <span className="text-ink-faint">{r.code}</span>
            <span className="text-ink-soft">
              {r.boards}板 · {r.tier_label ?? `${r.score}/${r.max_score} 分`}
            </span>
            <span className="text-ink-faint">历史同档晋级读数 {r.rate}%（n={r.rate_n}）</span>
          </div>
        ))}
      </div>
      <p className="mt-1.5 text-xs text-ink-faint">
        分层是相对强弱读数，不是买卖指令；晋级了也常一字板买不进。开盘走弱时，封板质量最弱的优先留意。
      </p>
    </div>
  );
}
