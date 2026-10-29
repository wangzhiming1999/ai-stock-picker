import { useCallback, useEffect, useState } from "react";
import { RefreshCw, ShieldAlert } from "lucide-react";
import { fetchDarkFlow } from "../../api/client";
import { pnlTone } from "../../lib/tone";
import { CELL, TEXT } from "../../lib/ui";
import type { DarkFlow, DarkFlowItem, DarkFlowSignal } from "../../types";
import Panel from "../ui/Panel";
import Table, { Th } from "../ui/Table";

/**
 * 暗盘资金 G/S 信号（明暗背离形态）。
 *
 * 判定：明盘（超大单+大单净额）与中单净额方向相反 → G（明出暗进，拆单吸筹嫌疑）
 * / S（明进暗出，拉高派发嫌疑）。
 *
 * ⚠️ 两条渲染纪律（全站红线，不得放宽）：
 *   1. **未验证形态** —— `signal_status` 恒为 `unsupported`（未定义收益口径），
 *      G/S 不是买卖建议；徽章与整块必须带「未验证」标注，禁用「买入/卖出」措辞。
 *   2. **口径随数据渲染** —— 「暗盘」是中单代理（散户+拆单主力混合体），
 *      后端下发的 `caveats` 必须原样展示，不得折叠隐藏。
 *
 * 配色走 tone.ts 语义：G=买入方向占红、S=卖出方向占绿（A 股惯例红涨绿跌）。
 */

const SIGNAL_META: Record<DarkFlowSignal, { label: string; hint: string; text: string; bg: string }> = {
  G: {
    label: "G",
    hint: "明出暗进 · 拆单吸筹嫌疑（未验证形态，不是买入建议）",
    text: "text-red-300",
    bg: "bg-red-500/12",
  },
  S: {
    label: "S",
    hint: "明进暗出 · 拉高派发嫌疑（未验证形态，不是卖出建议）",
    text: "text-green-300",
    bg: "bg-green-500/12",
  },
};

/** 元 → 亿元，缺值「—」（0 与「没这个数」不是一回事，不折成 0）。 */
function yi(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${(v / 1e8).toFixed(2)}`;
}

function pct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

function SignalChip({ signal }: { signal: DarkFlowSignal }) {
  const meta = SIGNAL_META[signal];
  return (
    <span
      className={`inline-flex h-5 w-5 items-center justify-center rounded-md text-meta font-semibold leading-none ${meta.bg} ${meta.text}`}
      title={meta.hint}
    >
      {meta.label}
    </span>
  );
}

function SignalRow({ item }: { item: DarkFlowItem }) {
  return (
    <tr>
      <td className={CELL}>
        <SignalChip signal={item.signal} />
      </td>
      <td className={CELL}>
        <div className="flex items-baseline gap-1.5">
          <span className={TEXT.label}>{item.name}</span>
          <span className="text-micro text-ink-muted">{item.code}</span>
        </div>
        {item.sector && <div className="text-micro text-ink-faint">{item.sector}</div>}
      </td>
      <td className={`${CELL} text-right ${pnlTone(item.change_pct)}`}>{pct(item.change_pct)}</td>
      <td className={`${CELL} text-right ${pnlTone(item.main_net)}`}>{yi(item.main_net)}</td>
      <td className={`${CELL} text-right ${pnlTone(item.mid_net)}`}>{yi(item.mid_net)}</td>
      <td className={`${CELL} text-right text-ink-soft`}>{pct(item.mid_pct)}</td>
      <td className={`${CELL} min-w-[220px]`}>
        <p className={`${TEXT.meta} text-ink-soft`} title={item.reason}>
          {item.reason}
        </p>
      </td>
    </tr>
  );
}

export default function DarkFlowPanel() {
  const [data, setData] = useState<DarkFlow | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (force = false) => {
    setLoading(true);
    setErr(null);
    try {
      setData(await fetchDarkFlow(force));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  const rows = [...(data?.g_items ?? []), ...(data?.s_items ?? [])];

  return (
    <Panel
      id="dark-flow"
      title="暗盘资金 G/S"
      icon={ShieldAlert}
      desc="明暗背离形态：明盘大单与中单方向相反时标注 G（明出暗进）/ S（明进暗出）"
      meta={
        <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/12 px-1.5 py-0.5 text-meta text-amber-300">
          <ShieldAlert className="h-3 w-3" aria-hidden />
          未验证形态 · unsupported
        </span>
      }
      actions={
        <button
          type="button"
          onClick={() => void load(true)}
          disabled={loading}
          className="inline-flex items-center gap-1 rounded-lg border border-surface-line-strong px-2 py-1 text-meta text-ink-soft hover:bg-surface-raised disabled:opacity-50"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} aria-hidden />
          刷新
        </button>
      }
    >
      <div className="space-y-3">
        {err && <p className={`${TEXT.meta} text-red-300`}>加载失败：{err}</p>}

        {data && !data.available && (
          <p className={`${TEXT.meta} text-ink-soft`}>{data.note || "暂无数据"}</p>
        )}

        {rows.length > 0 ? (
          <Table
            label="暗盘资金 G/S 信号"
            minWidth={860}
            maxHeight="sm"
            head={
              <tr>
                <Th>信号</Th>
                <Th>个股</Th>
                <Th align="right">涨幅</Th>
                <Th align="right">明盘净额(亿)</Th>
                <Th align="right">中单净额(亿)</Th>
                <Th align="right">中单占比</Th>
                <Th>形态说明</Th>
              </tr>
            }
          >
            {rows.map((item) => (
              <SignalRow key={`${item.signal}-${item.code}`} item={item} />
            ))}
          </Table>
        ) : (
          data?.available && (
            <p className={`${TEXT.meta} text-ink-soft`}>
              今日暂无明暗背离形态（扫描 {data.counts.scanned} 只，G {data.counts.g} / S {data.counts.s}）。
            </p>
          )
        )}

        {data && (
          <p className={`${TEXT.meta} text-ink-muted`}>
            {data.caliber} · 扫描 {data.counts.scanned} 只 · G {data.counts.g} / S {data.counts.s} · {data.note}
          </p>
        )}

        {/* 口径免责：后端下发的 caveats 必须原样渲染，不得折叠隐藏（红线） */}
        {data && data.caveats.length > 0 && (
          <ul className="space-y-1 rounded-lg bg-surface-inset/50 px-2.5 py-2">
            {data.caveats.map((c) => (
              <li key={c} className={`${TEXT.meta} leading-relaxed text-ink-faint`}>
                · {c}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
