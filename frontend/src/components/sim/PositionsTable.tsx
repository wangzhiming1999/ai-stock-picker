import type { SimPositionsData, SimPosition } from "../../types";
import { pnlTone } from "../../lib/tone";
import Table, { Th } from "../ui/Table";
import { CELL } from "../../lib/ui";

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
    <Table
      label="模拟盘持仓"
      maxHeight="none"
      className="mb-4"
      head={
        <tr>
          <Th>股票</Th>
          <Th align="right">现价</Th>
          <Th align="right">成本</Th>
          <Th align="right">数量</Th>
          <Th align="right">浮盈</Th>
          <Th align="right" />
        </tr>
      }
    >
      {positions.positions.map((p: SimPosition) => (
        <tr key={p.code} className="border-t border-surface-line-soft">
          <td className={CELL}>
            <div className="font-medium text-ink">{p.name || p.code}</div>
            <div className="text-meta text-ink-muted">{p.code}</div>
          </td>
          <td className={`${CELL} text-right text-ink-soft`}>{p.current_price?.toFixed(2) ?? "-"}</td>
          <td className={`${CELL} text-right text-ink-muted`}>{p.avg_cost?.toFixed(2)}</td>
          <td className={`${CELL} text-right text-ink-muted`}>{p.shares}</td>
          <td className={`${CELL} text-right ${pnlTone(p.pnl_pct)}`}>
            {p.pnl_pct != null ? `${p.pnl_pct >= 0 ? "+" : ""}${p.pnl_pct.toFixed(2)}%` : "-"}
          </td>
          <td className={`${CELL} text-right`}>
            <button onClick={() => onSell(p.code, p.current_price ?? undefined)} className="rounded-md border border-surface-line-strong px-2 py-1 text-meta text-ink-soft hover:border-green-400 hover:text-green-300">
              卖出
            </button>
          </td>
        </tr>
      ))}
    </Table>
  );
}
