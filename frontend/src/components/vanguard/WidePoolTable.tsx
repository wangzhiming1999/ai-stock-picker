import { Stethoscope } from "lucide-react";
import { CELL } from "../../lib/ui";
import type { VanguardBoard, VanguardWideRow } from "../../types";
import Button from "../ui/Button";
import Table, { Th } from "../ui/Table";
import { PctText, YiText } from "./shared";

interface Props {
  data: VanguardBoard;
  onDiagnose: (code: string) => void;
}

/**
 * 宽池候选：廉价预筛（无 K 线）的全部候选，点行可送诊股。
 *
 * 与「三维选股榜」分工：那张是 K 线精算后的 Top 20；这张是进入精算前的更广候选面，
 * 让用户在「只看 20 只」之外还能翻看更多符合硬过滤的标的。scored=false 的行
 * 没有三维分（没拉 K 线），不应被误读成「分低」。
 */
export default function WidePoolTable({ data, onDiagnose }: Props) {
  const rows = data.wide_pool ?? [];

  const head = (
    <tr>
      <Th align="right">#</Th>
      <Th>名称 / 代码</Th>
      <Th align="right">现价</Th>
      <Th align="right">涨跌幅</Th>
      <Th align="right">成交额</Th>
      <Th align="right">换手</Th>
      <Th align="right">量比</Th>
      <Th align="right">主力净占比</Th>
      <Th>板块</Th>
      <Th align="right">初筛分</Th>
      <Th align="center">状态</Th>
    </tr>
  );

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-ink-muted">
        <span>
          宽池 <b className="text-ink-soft">{data.wide_pool_size}</b> 只
        </span>
        <span className="text-ink-faint">其中 {rows.filter((r) => r.scored).length} 只进入 K 线精算</span>
        <span className="text-ink-faint">点行可送三维诊股</span>
      </div>

      <Table label="宽池候选" maxHeight="lg" minWidth={860} head={head} isEmpty={rows.length === 0} empty={<p className="text-body text-ink-soft">今日没有通过硬过滤的标的。</p>}>
        {rows.map((r: VanguardWideRow, i: number) => (
          <tr
            key={r.code}
            className="border-t border-surface-line-soft hover:bg-surface-inset/50 cursor-pointer"
            onClick={() => onDiagnose(r.code)}
          >
            <td className={`${CELL} text-right text-ink-muted`}>{i + 1}</td>
            <td className={CELL}>
              <div className="flex items-center gap-2">
                <span className="font-medium text-ink-soft">{r.name}</span>
                <span className="text-meta text-ink-faint">{r.code}</span>
              </div>
            </td>
            <td className={`${CELL} text-right tabular-nums`}>{Number.isFinite(r.price) ? r.price.toFixed(2) : "—"}</td>
            <td className={`${CELL} text-right tabular-nums`}>
              <PctText v={r.change_pct} />
            </td>
            <td className={`${CELL} text-right tabular-nums`}>
              <YiText v={r.amount_yi} />
            </td>
            <td className={`${CELL} text-right tabular-nums text-ink-soft`}>
              {r.turnover != null && Number.isFinite(r.turnover) ? `${r.turnover.toFixed(2)}%` : "—"}
            </td>
            <td className={`${CELL} text-right tabular-nums text-ink-soft`}>
              {r.volume_ratio != null && Number.isFinite(r.volume_ratio) ? r.volume_ratio.toFixed(2) : "—"}
            </td>
            <td className={`${CELL} text-right tabular-nums`}>
              {r.main_pct != null ? <PctText v={r.main_pct} /> : <span className="text-ink-faint">—</span>}
            </td>
            <td className={`${CELL} text-ink-soft`}>{r.sector ?? "—"}</td>
            <td className={`${CELL} text-right tabular-nums text-ink-soft`}>
              {Number.isFinite(r.pre_score) ? r.pre_score.toFixed(2) : "—"}
            </td>
            <td className={`${CELL} text-center`}>
              {r.scored ? (
                <span className="rounded-full bg-state-success-surface px-2 py-0.5 text-meta text-state-success-soft">精算</span>
              ) : (
                <span className="rounded-full bg-surface-inset px-2 py-0.5 text-meta text-ink-faint">预筛</span>
              )}
            </td>
          </tr>
        ))}
      </Table>

      <div className="flex justify-end">
        <Button variant="outlineQuiet" size="xs" onClick={() => onDiagnose(rows[0]?.code)} disabled={rows.length === 0}>
          <Stethoscope className="h-3.5 w-3.5" aria-hidden />
          诊股榜首
        </Button>
      </div>
    </div>
  );
}
