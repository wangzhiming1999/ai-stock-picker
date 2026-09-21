import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, Stethoscope } from "lucide-react";
import { pnlTone } from "../../lib/tone";
import { CELL } from "../../lib/ui";
import type { VanguardBoard, VanguardItem } from "../../types";
import Button from "../ui/Button";
import Table, { Th } from "../ui/Table";
import WatchStar from "../WatchStar";
import { DIM_SHORT, DimChip, ExpectedPriceChip, LevelChips, PctText, YiText } from "./shared";

interface Props {
  data: VanguardBoard;
  onPick: (codes: string[]) => void;
  onDiagnose: (code: string) => void;
}

/** 逐维点评：把后端 comments 摆出来，让分数可复核。 */
function DimComments({ item }: { item: VanguardItem }) {
  return (
    <div className="space-y-1">
      {(["dark_money", "trend", "activity"] as const).map((k) => (
        <div key={k} className="flex gap-2 text-meta">
          <span className="w-10 shrink-0 text-ink-muted">{DIM_SHORT[k]}</span>
          <DimChip v={item.scores[k]} />
          <span className="min-w-0 flex-1 text-ink-soft">{item.comments[k]}</span>
        </div>
      ))}
    </div>
  );
}

function DetailRow({ item, colSpan }: { item: VanguardItem; colSpan: number }) {
  const m = item.metrics;
  const f = item.fund;
  return (
    <tr className="border-t border-surface-line-soft bg-surface-inset/40">
      <td colSpan={colSpan} className="px-3 py-3">
        <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr_1.2fr]">
          <div className="min-w-0">
            <p className="mb-1.5 text-meta font-semibold text-ink-muted">逐维点评（可复核）</p>
            <DimComments item={item} />
          </div>

          <div className="min-w-0">
            <p className="mb-1.5 text-meta font-semibold text-ink-muted">
              主力资金 <span className="font-normal">（大单口径）</span>
            </p>
            {f ? (
              <div className="space-y-1 text-meta text-ink-soft">
                <div>
                  主力净额 <YiText v={f.main_net_yi} /> · 净占比 <PctText v={f.main_pct} />
                </div>
                <div>
                  超大单净额 <YiText v={f.super_net_yi} />
                  {f.rank != null && <span className="ml-2 text-ink-muted">当日资金榜第 {f.rank} 位</span>}
                </div>
                {!f.super_net_yi && <div className="text-ink-soft">该股不在当日资金流两端的批次内</div>}
              </div>
            ) : (
              <p className="text-meta text-ink-soft">该股未进入当日资金流批次（或资金维不可用）</p>
            )}

            {m && (
              <div className="mt-2 space-y-1 text-meta text-ink-soft">
                <div>
                  距 250 日高点 <PctText v={m.pct_from_high} />
                  <span className="ml-2 text-ink-soft">近 20 日 <PctText v={m.r20} /></span>
                </div>
                <div className="text-ink-soft">
                  MA5 {m.ma5.toFixed(2)} · MA20 {m.ma20.toFixed(2)} · MA60 {m.ma60.toFixed(2)} · MA20 斜率{" "}
                  {m.ma20_slope.toFixed(2)}%
                </div>
              </div>
            )}
          </div>

          <div className="min-w-0">
            <p className="mb-1.5 text-meta font-semibold text-ink-muted">买卖时机 · 结构位</p>
            {item.levels && (
              <p className="mb-1.5">
                <ExpectedPriceChip ep={item.expected_price} />
              </p>
            )}
            <LevelChips levels={item.levels} />
            <p className="mt-1.5 text-meta text-ink-soft">
              买卖点锚定主支撑 / 主压力，不随现价漂移；预期价格取其中**这一个**锚点
              （现价贴压力→突破位，否则回踩位），是为了让「回踩/突破到多少才动手」有个能直接挂的数。
              买入侧实测超额为负（证据档 unsupported）—— 这是价位结构参考，不是买入指令。
            </p>
          </div>
        </div>
      </td>
    </tr>
  );
}

/**
 * 三维榜主表。
 *
 * 交互与四维榜（QuadRankTable）保持一致：点行勾选、勾选后可整批送分析。
 * 差异只有一处 —— 每行可展开看**逐维点评与结构位**，因为三维分的可复核性
 * 取决于「这个分是怎么来的」，只给一个数字等于要求用户信任黑箱。
 */
export default function BoardTable({ data, onPick, onDiagnose }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const items = data.items;

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const COLS = 9;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-ink-muted">
        <span>
          候选池 <b className="text-ink-soft">{data.pool_size}</b> 只
        </span>
        <span>
          K 线精算 <b className="text-ink-soft">{data.scored_size}</b> 只
        </span>
        <span>
          上榜 <b className="text-ink-soft">{items.length}</b> 只
        </span>
        <span className="text-ink-faint">{data.weights_note}</span>
        {selected.size > 0 && (
          <Button variant="primary" size="xs" onClick={() => onPick(Array.from(selected))}>
            勾选 {selected.size} 只去深度分析 →
          </Button>
        )}
      </div>

      <Table
        label="三维选股榜"
        minWidth={880}
        maxHeight="md"
        head={
          <tr>
            <Th />
            <Th>#</Th>
            <Th>股票</Th>
            <Th align="right">现价</Th>
            <Th align="center">资金</Th>
            <Th align="center">趋势</Th>
            <Th align="center">活跃</Th>
            <Th align="center">综合</Th>
            <Th align="right">操作</Th>
          </tr>
        }
      >
        {items.map((it) => {
          const isSel = selected.has(it.code);
          const isOpen = expanded === it.code;
          return (
            <Fragment key={it.code}>
              <tr
                onClick={() => toggle(it.code)}
                className={`cursor-pointer border-t border-surface-line-soft transition-colors ${
                  isSel ? "bg-brand/10" : "hover:bg-surface-inset/60"
                }`}
              >
                <td className={CELL}>
                  <input
                    type="checkbox"
                    readOnly
                    checked={isSel}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggle(it.code)}
                    className="accent-brand"
                  />
                </td>
                <td className={`${CELL} text-meta text-ink-muted`}>{it.rank ?? "—"}</td>
                <td className={CELL}>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-ink-strong">{it.name}</span>
                    {it.tags.map((t) => (
                      <span
                        key={t}
                        className="rounded-md bg-brand/15 px-1 py-0.5 text-meta leading-none text-brand-light"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                  <div className="text-meta text-ink-muted">
                    {it.code}
                    {it.sector && <span className="ml-1.5">{it.sector}</span>}
                    {it.sector_strength != null && (
                      <span className="ml-1.5">板块强度 {it.sector_strength.toFixed(1)}</span>
                    )}
                  </div>
                </td>
                <td className={`${CELL} text-right`}>
                  <div className="text-ink">{it.price.toFixed(2)}</div>
                  <div className={`text-meta ${pnlTone(it.change_pct)}`}>
                    {it.change_pct >= 0 ? "+" : ""}
                    {it.change_pct.toFixed(2)}%
                  </div>
                  {/* 预期价格在主表就露出（展开明细里给完整说明）——
                      用户反馈「不知道怎么操作」，多半是不会点开每一行找价位。
                      缺值时不占位：旧快照（undefined）与算不出（null）都留空。 */}
                  {it.expected_price && (
                    <div className="text-meta text-ink-soft" title={it.expected_price.note}>
                      预期 {it.expected_price.price.toFixed(2)}
                      <span className="text-ink-soft">
                        {it.expected_price.setup === "breakout" ? " 突破" : " 回踩"}
                      </span>
                    </div>
                  )}
                </td>
                <td className={`${CELL} text-center`}>
                  <DimChip v={it.scores.dark_money} title={it.comments.dark_money} />
                </td>
                <td className={`${CELL} text-center`}>
                  <DimChip v={it.scores.trend} title={it.comments.trend} />
                </td>
                <td className={`${CELL} text-center`}>
                  <DimChip v={it.scores.activity} title={it.comments.activity} />
                </td>
                <td className={`${CELL} text-center`}>
                  <span
                    className={`text-head font-bold ${
                      it.overall_score >= 7 ? "text-brand-light" : "text-ink-soft"
                    }`}
                    title={data.weights_note}
                  >
                    {it.overall_score.toFixed(2)}
                  </span>
                </td>
                <td className={`${CELL} text-right`} onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="xs"
                      title="用这只票做三维诊股"
                      onClick={() => onDiagnose(it.code)}
                    >
                      <Stethoscope className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                    <Button
                      variant="ghost"
                      size="xs"
                      title={isOpen ? "收起明细" : "展开逐维点评与结构位"}
                      onClick={() => setExpanded(isOpen ? null : it.code)}
                    >
                      {isOpen ? (
                        <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
                      )}
                    </Button>
                    <WatchStar code={it.code} size="sm" />
                  </div>
                </td>
              </tr>
              {isOpen && <DetailRow item={it} colSpan={COLS} />}
            </Fragment>
          );
        })}
      </Table>
    </div>
  );
}
