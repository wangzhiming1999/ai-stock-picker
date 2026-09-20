import type { SimPositionsData, SimPosition } from "../../types";
import { pnlTone } from "../../lib/tone";

/** 持仓表：现价 / 成本 / 数量 / 浮盈，以及每行的卖出（平仓）动作。
 *
 * 卖出动作只负责把「标的 + 实时价」回传给宿主，由宿主统一打开交易弹窗，不在本组件内直接调接口。
 */
export default function PositionsTable({
  positions,
  onSell,
}: {
  positions: SimPositionsData | null;
  onSell: (code: string, price?: number) => void;
}) {
  if (!positions || positions.positions.length === 0) return null;
  return (
    <div className="mb-4 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-ink-muted">
          <tr>
            <th scope="col" className="px-3 py-2">股票</th>
            <th scope="col" className="px-3 py-2 text-right">现价</th>
            <th scope="col" className="px-3 py-2 text-right">成本</th>
            <th scope="col" className="px-3 py-2 text-right">数量</th>
            <th scope="col" className="px-3 py-2 text-right">浮盈</th>
            <th scope="col" className="px-3 py-2 text-right"></th>
          </tr>
        </thead>
        <tbody>
          {positions.positions.map((p: SimPosition) => (
            <tr key={p.code} className="border-t border-slate-800/60">
              <td className="px-3 py-2">
                <div className="font-medium text-ink">{p.name || p.code}</div>
                <div className="text-xs text-ink-faint">{p.code}</div>
              </td>
              <td className="px-3 py-2 text-right text-ink-soft">{p.current_price?.toFixed(2) ?? "-"}</td>
              <td className="px-3 py-2 text-right text-ink-muted">{p.avg_cost?.toFixed(2)}</td>
              <td className="px-3 py-2 text-right text-ink-muted">{p.shares}</td>
              <td className={`px-2 py-2 text-right ${pnlTone(p.pnl_pct)}`}>
                {p.pnl_pct != null ? `${p.pnl_pct >= 0 ? "+" : ""}${p.pnl_pct.toFixed(2)}%` : "-"}
              </td>
              <td className="px-3 py-2 text-right">
                <button onClick={() => onSell(p.code, p.current_price ?? undefined)} className="rounded border border-slate-600 px-2 py-1 text-xs text-ink-soft hover:border-green-400 hover:text-green-300">
                  卖出
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
