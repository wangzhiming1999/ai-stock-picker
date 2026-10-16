import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { pnlTone } from "../../lib/tone";
import { CELL, TEXT } from "../../lib/ui";
import type { SectorFollow, SectorFollowItem, SectorFollowState } from "../../types";
import Table, { Th } from "../ui/Table";

/**
 * 四态配色 —— 走 `tone.ts` 的既有语义，不在组件里手写红绿判断。
 *
 * ⚠️ 「加速流入 / 持续流入」表达的是**资金方向**，所以占红（看多语义）；
 * 「退潮」是**警示**而非看空 —— 它窗口累计仍为正，只是边际转弱，
 * 因此用琥珀而不是绿（绿在本项目是「跌/卖出」语义，用在这里会与
 * 同一屏的下跌数字打架，见 lib/tone.ts 顶部约定）；只有「撤离」才是绿。
 */
const STATE_TONE: Record<SectorFollowState, { text: string; bg: string }> = {
  follow_accel: { text: "text-red-300", bg: "bg-red-500/10" },
  follow_steady: { text: "text-red-400", bg: "bg-red-500/10" },
  follow_ebb: { text: "text-amber-300", bg: "bg-amber-500/10" },
  follow_exit: { text: "text-green-400", bg: "bg-green-500/10" },
  unknown: { text: "text-ink-muted", bg: "bg-surface-inset/40" },
};

function StateBadge({ item }: { item: SectorFollowItem }) {
  const tone = STATE_TONE[item.state] ?? STATE_TONE.unknown;
  return (
    <span
      className={`rounded-md px-1.5 py-0.5 text-meta font-medium leading-none ${tone.bg} ${tone.text}`}
      title={item.state_hint}
    >
      {item.state_label}
    </span>
  );
}

/** 缺值一律「—」，不折成 0（0 与「没这个数」不是一回事）。 */
function yi(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

/**
 * 近 N 日主力净额迷你柱状图。
 *
 * 只画形状不画坐标轴 —— 它要回答的是「这一串里最新一根相对前面是变长还是变短」，
 * 有刻度反而会让人去读具体数值（而数值已在右侧列出）。
 * 颜色按资金方向：正红负绿，与全站口径一致。
 */
function TrendSpark({ item }: { item: SectorFollowItem }) {
  const win = item.trend?.window ?? [];
  if (win.length < 2) return <span className={TEXT.meta}>—</span>;

  const vals = win.map((w) => w.main_yi ?? 0);
  const max = Math.max(...vals.map(Math.abs), 1e-9);
  const last = vals[vals.length - 1];
  const bars = vals.map((v, i) => {
    const h = Math.max(2, (Math.abs(v) / max) * 26);
    const isLast = i === vals.length - 1;
    return (
      <span
        key={`${win[i].date}-${i}`}
        className={`w-1.5 shrink-0 rounded-md ${v >= 0 ? "bg-red-500/70" : "bg-green-500/70"} ${
          isLast ? "ring-1 ring-ink/40" : ""
        }`}
        style={{ height: `${h}px` }}
        title={`${win[i].date} 主力净额 ${yi(win[i].main_yi)} 亿`}
      />
    );
  });
  return (
    <div className="flex flex-col items-end gap-0.5">
      <div className="flex items-end gap-0.5">{bars}</div>
      <span className="text-micro text-ink-muted">
        近 {win.length} 日 · 最新 {yi(last)} 亿
      </span>
    </div>
  );
}

function DetailRow({ item, colSpan }: { item: SectorFollowItem; colSpan: number }) {
  const t = item.trend;
  return (
    <tr className="border-t border-surface-line-soft bg-surface-inset/40">
      <td colSpan={colSpan} className={CELL}>
        <div className="py-1">
          <div className="grid gap-3 lg:grid-cols-[1.3fr_1fr_1fr]">
          <div className="min-w-0">
            <p className={`${TEXT.label} mb-1.5`}>时序明细（近 {t?.days ?? 0} 个交易日）</p>
            {t ? (
              <>
                <div className={`${TEXT.meta} space-y-0.5 text-ink-soft`}>
                  <div>
                    窗口累计 <b className={pnlTone(t.main_sum_yi)}>{yi(t.main_sum_yi)} 亿</b>
                    <span className="ml-2 text-ink-muted">日均 {yi(t.main_avg_yi)} 亿</span>
                  </div>
                  <div>
                    最新一日（{t.latest_date}）
                    <b className={pnlTone(t.today_yi)}> {yi(t.today_yi)} 亿</b>
                  </div>
                  <div>
                    加速度（最新 − 日均）
                    <b className={pnlTone(t.accel_yi)}> {yi(t.accel_yi)} 亿</b>
                    <span className="ml-2 text-ink-muted">
                      分位 {item.ranks.acceleration.toFixed(2)}
                    </span>
                  </div>
                  <div>
                    超大单占主力
                    {t.super_share != null ? (
                      <b className="text-ink-soft"> {(t.super_share * 100).toFixed(0)}%</b>
                    ) : (
                      <span className="text-ink-muted"> —</span>
                    )}
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {t.window.map((w) => (
                    <span
                      key={w.date}
                      className={`rounded-md bg-surface-inset/50 px-1 py-0.5 text-micro ${pnlTone(
                        w.main_yi,
                        300,
                      )}`}
                    >
                      {w.date.slice(5)} {yi(w.main_yi, 1)}
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <p className={`${TEXT.meta} text-ink-soft`}>
                该板块资金流日线未取到（端点抖动或样本不足），四态已降级为「仅按当日净额」推断。
              </p>
            )}
          </div>

          <div className="min-w-0">
            <p className={`${TEXT.label} mb-1.5`}>当日资金结构</p>
            <div className={`${TEXT.meta} space-y-0.5 text-ink-soft`}>
              <div>
                主力净额 <b className={pnlTone(item.main_net_yi)}>{yi(item.main_net_yi)} 亿</b>
              </div>
              <div>
                主力净占比
                {item.main_pct != null ? <b className="text-ink-soft"> {pct(item.main_pct)}</b> : <span className="text-ink-muted"> —</span>}
              </div>
              <div>
                超大单净占比
                {item.super_pct != null ? <b className="text-ink-soft"> {pct(item.super_pct)}</b> : <span className="text-ink-muted"> —</span>}
              </div>
              <div>
                大单净占比
                {item.large_pct != null ? <b className="text-ink-soft"> {pct(item.large_pct)}</b> : <span className="text-ink-muted"> —</span>}
              </div>
            </div>
            <p className={`mt-1.5 ${TEXT.meta} text-ink-muted`}>
              分位在<b className="text-ink-soft"> 全量 {item.up_count != null ? "板块" : "样本"} </b>
              横截面上计算，因此只在当日可比；跨日看分位会得到错误的强弱结论。
            </p>
          </div>

          <div className="min-w-0">
            <p className={`${TEXT.label} mb-1.5`}>板块内部</p>
            <div className={`${TEXT.meta} space-y-0.5 text-ink-soft`}>
              <div>
                上涨/下跌家数{" "}
                <b className="text-ink-soft">
                  {item.up_count ?? "—"} / {item.down_count ?? "—"}
                </b>
                {item.breadth != null && (
                  <span className="ml-2 text-ink-muted">上涨占比 {(item.breadth * 100).toFixed(0)}%</span>
                )}
              </div>
              {item.leader_name && (
                <div>
                  领涨{" "}
                  <b className="text-red-300">
                    {item.leader_name}
                    {item.leader_change_pct != null && ` ${pct(item.leader_change_pct)}`}
                  </b>
                </div>
              )}
              {item.laggard_name && (
                <div>
                  领跌 <b className="text-green-400">{item.laggard_name}</b>
                </div>
              )}
            </div>
            <p className={`mt-1.5 ${TEXT.meta} leading-relaxed text-ink-muted`}>
              {item.state_hint}
            </p>
          </div>
          </div>
        </div>
      </td>
    </tr>
  );
}

interface Props {
  data: SectorFollow | null;
  loading?: boolean;
  err?: string;
  onRefresh?: () => void;
}

const COLS = 8;

/**
 * 跟随主力的板块（折叠区）。
 *
 * 排序与四态都由后端决定（`STATE_ORDER`：加速 → 持续 → 退潮 → 撤离），
 * 前端不再二次排序 —— 同一份数据在两处排序必然有一处会漂。
 *
 * ⚠️ 本块**不渲染任何买卖动作**。它是资金结构读数：证据档 unsupported，
 * 没有收益口径。免责说明见下方 `caveats`，取数失败时也要显示而不是藏起来。
 */
export default function SectorFollowPanel({ data, loading, err, onRefresh }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (err) {
    return (
      <div className="rounded-lg border border-state-warn-line bg-state-warn-surface px-3 py-2">
        <p className={`${TEXT.meta} text-state-warn-soft`}>板块资金流取数失败：{err}</p>
        {onRefresh && (
          <button onClick={onRefresh} className={`${TEXT.meta} mt-1 text-brand-light underline`}>
            重试
          </button>
        )}
      </div>
    );
  }

  if (loading && !data) {
    return <p className={`${TEXT.meta} py-3 text-ink-muted`}>正在拉取板块资金流…</p>;
  }

  if (!data || !data.available) {
    return (
      <div className="rounded-lg bg-surface-inset/50 px-3 py-2">
        <p className={`${TEXT.meta} text-ink-soft`}>
          本次未取到板块资金流（{data?.note || "接口降级"}）。这不是「今天没有资金流入板块」，
          而是数据源不可用 —— 两者不要混淆。
        </p>
        {onRefresh && (
          <button onClick={onRefresh} className={`${TEXT.meta} mt-1 text-brand-light underline`}>
            重试
          </button>
        )}
      </div>
    );
  }

  const items = data.sectors;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-ink-muted">
        <span>
          板块总样本 <b className="text-ink-soft">{data.total_sectors}</b>
        </span>
        <span>
          参与判定 <b className="text-ink-soft">{data.ranked_sectors}</b>
        </span>
        <span>
          上榜 <b className="text-ink-soft">{items.length}</b>
        </span>
        {/* 四态分布：必须按参与判定的全量展示，不能只统计上方表格那12 行 ——
            只看表格会以为「撤离」占了绝大多数，而那只是流入榜的正常分布。 */}
        {Object.entries(data.state_distribution).map(([label, n]) => (
          <span key={label}>
            {label} <b className="text-ink-soft">{n}</b>
          </span>
        ))}
        {!data.complete && (
          <span className="text-amber-300">名录未翻页取全，缺失板块不参与判定</span>
        )}
        {!data.trend_available && (
          <span className="text-amber-300">时序未取到，四态暂按当日净额推断</span>
        )}
        {onRefresh && (
          <button onClick={onRefresh} className="text-brand-light underline">
            刷新
          </button>
        )}
      </div>

      {/* 免责口径：必须常驻可见，不能折叠、不能只放 tooltip */}
      <div className="rounded-lg border border-state-warn-line bg-state-warn-surface px-3 py-2">
        <p className="text-meta leading-relaxed text-state-warn-soft">
          <b>口径与免责</b>
        </p>
        <ul className="mt-1 space-y-0.5 text-micro leading-relaxed text-state-warn-soft/90">
          {data.caveats.map((c) => (
            <li key={c}>· {c}</li>
          ))}
          {data.sample_note && <li>· {data.sample_note}</li>}
        </ul>
      </div>

      <Table
        label="跟随主力板块榜"
        minWidth={900}
        maxHeight="md"
        head={
          <tr>
            <Th>板块</Th>
            <Th>四态</Th>
            <Th align="right">今日主力</Th>
            <Th align="right">今日涨跌</Th>
            <Th align="right">窗口累计</Th>
            <Th align="right">加速度</Th>
            <Th align="right">近 5 日</Th>
            <Th align="right">操作</Th>
          </tr>
        }
      >
        {items.map((it) => {
          const isOpen = expanded === it.code;
          const t = it.trend;
          return (
            <Fragment key={it.code}>
              <tr
                className="cursor-pointer border-t border-surface-line-soft transition-colors hover:bg-surface-inset/60"
                onClick={() => setExpanded(isOpen ? null : it.code)}
              >
                <td className={CELL}>
                  <div className="font-medium text-ink-strong">{it.name}</div>
                  <div className="text-meta text-ink-muted">
                    {it.code}
                    {it.leader_name && <span className="ml-1.5">领涨 {it.leader_name}</span>}
                  </div>
                </td>
                <td className={CELL}>
                  <StateBadge item={it} />
                </td>
                <td className={`${CELL} text-right ${pnlTone(it.main_net_yi)}`}>
                  {yi(it.main_net_yi)} 亿
                  <div className="text-meta text-ink-muted">
                    占比 {it.main_pct != null ? pct(it.main_pct) : "—"}
                  </div>
                </td>
                <td className={`${CELL} text-right ${pnlTone(it.change_pct)}`}>
                  {pct(it.change_pct)}
                </td>
                <td className={`${CELL} text-right ${t ? pnlTone(t.main_sum_yi) : ""}`}>
                  {t ? yi(t.main_sum_yi) : "—"}
                  <div className="text-meta text-ink-muted">
                    持续性 {it.ranks.continuity.toFixed(2)}
                  </div>
                </td>
                <td className={`${CELL} text-right ${t ? pnlTone(t.accel_yi) : ""}`}>
                  {t ? yi(t.accel_yi) : "—"}
                  <div className="text-meta text-ink-muted">
                    分位 {it.ranks.acceleration.toFixed(2)}
                  </div>
                </td>
                <td className={`${CELL} text-right`}>
                  <TrendSpark item={it} />
                </td>
                <td className={`${CELL} text-right`}>
                  <button
                    className="rounded-lg p-1 text-ink-muted transition-colors hover:text-ink"
                    title={isOpen ? "收起明细" : "展开时序与结构明细"}
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpanded(isOpen ? null : it.code);
                    }}
                  >
                    {isOpen ? (
                      <ChevronDown className="h-4 w-4" aria-hidden />
                    ) : (
                      <ChevronRight className="h-4 w-4" aria-hidden />
                    )}
                  </button>
                </td>
              </tr>
              {isOpen && <DetailRow item={it} colSpan={COLS} />}
            </Fragment>
          );
        })}
      </Table>

      <p className={`${TEXT.meta} leading-relaxed text-ink-muted`}>
        <b className="text-ink-soft">怎么读这一块</b>：先看四态，再看加速度。
        「加速流入」= 窗口累计仍为正、且今日边际在加速 —— 这是资金真正进场的形态；
        「退潮」= 累计还正但今日已转弱，追进去接的是最后一波。
        今天流入额排名靠前但四态是「撤离」的板块并不少见（实测国防军工 10-13 净流入
        19.3 亿、10-15 净流出 30.7 亿），所以**不要只看当日排名**。
      </p>
    </div>
  );
}