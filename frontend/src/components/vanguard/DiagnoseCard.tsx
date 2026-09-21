import { useCallback, useEffect, useState } from "react";
import { Stethoscope } from "lucide-react";
import { fetchVanguardDiagnose } from "../../api/client";
import { pnlTone } from "../../lib/tone";
import { SUB } from "../../lib/ui";
import { fmtNum } from "../../lib/safe";
import type { VanguardDiagnose, VanguardSector } from "../../types";
import Button from "../ui/Button";
import StockSearchInput from "../StockSearchInput";
import { DIM_SHORT, DimChip, EvidenceBadge, ExpectedPriceChip, LevelChips, PctText, YiText } from "./shared";

interface Props {
  /** 外部（榜单行的「诊股」按钮）请求诊断的代码 */
  code: string | null;
  /** 外部请求自增计数：同一个 code 连点两次也要重新触发 */
  requestId: number;
}

function SectorCompare({ sector }: { sector: VanguardSector }) {
  return (
    <div className={`${SUB} px-3 py-2 text-meta`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium text-ink">所属板块：{sector.sector}</span>
        <span className="text-ink-soft">
          强度 <b className="text-ink">{sector.strength_score.toFixed(1)}</b> / 10
        </span>
        <span className="text-ink-muted">
          成员 {sector.member_count} 只 · 上涨 {sector.up_count} 只 · 涨停 {sector.limitup_count} 家
        </span>
      </div>
      <div className="mt-1 text-ink-soft">
        资金分位 {sector.dims.money.toFixed(1)} · 动量分位 {sector.dims.momentum.toFixed(1)} · 广度分位{" "}
        {sector.dims.breadth.toFixed(1)} —— 分位是**当日横截面**排名，换日即换基准，不可跨日比较
      </div>
    </div>
  );
}

/**
 * 诊股：单票三维体检。
 *
 * ## 与「深度分析」的分工（刻意不重叠）
 * 这里只给**量化读数** —— 三维分、结构位、板块分位，不给多空结论、不调 LLM。
 * LLM 的多角色辩论在全局的「深度分析」抽屉里，入口就在本卡右侧。
 * 两处都叫「诊股」会让人分不清该看哪个，所以这里的动作按钮一律写「深度分析」。
 */
export default function DiagnoseCard({ code, requestId }: Props) {
  const [text, setText] = useState("");
  const [data, setData] = useState<VanguardDiagnose | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const run = useCallback(async (target: string) => {
    const c = target.trim();
    if (!c) return;
    setLoading(true);
    setErr("");
    try {
      setData(await fetchVanguardDiagnose(c));
    } catch (e) {
      setErr((e as Error).message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // 榜单行的「诊股」按钮 → 外部 code 变化即触发
  useEffect(() => {
    if (!code) return;
    setText(code);
    void run(code);
  }, [code, requestId, run]);

  const item = data?.item ?? null;
  const fund = item?.fund ?? null;
  const metrics = item?.metrics ?? null;
  const inBoard = data?.in_board;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-full max-w-xs">
          <StockSearchInput value={text} onChange={setText} onPickCode={(c) => void run(c)} disabled={loading} />
        </div>
        <Button variant="info" size="sm" onClick={() => void run(text)} disabled={loading || !text.trim()}>
          <Stethoscope className="h-3.5 w-3.5" aria-hidden />
          {loading ? "体检中..." : "三维诊股"}
        </Button>
      </div>

      {err && (
        <div className="rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">{err}</div>
      )}

      {!data && !err && (
        <p className="text-body text-ink-faint">
          输入代码或名称做单票三维体检：给出资金 / 趋势 / 活跃度三个分数、结构位与所属板块强度。
          榜单里已有的票直接命中缓存（零额外请求），不在榜内的现场计算。
        </p>
      )}

      {data && item && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-head font-semibold text-ink-strong">{item.name || data.code}</span>
            <span className="text-meta text-ink-muted">{data.code}</span>
            <span className="text-body text-ink">
              {item.price.toFixed(2)}{" "}
              <span className={pnlTone(item.change_pct)}>
                {item.change_pct >= 0 ? "+" : ""}
                {item.change_pct.toFixed(2)}%
              </span>
            </span>
            <span className="text-meta text-ink-muted">
              {inBoard ? `在榜第 ${data.rank} 名` : "不在今日榜内（现场计算）"}
            </span>
            {data.date && <span className="text-meta text-ink-muted">{data.date}</span>}
            <span className="ml-auto">
              <EvidenceBadge evidence={data.evidence} />
            </span>
          </div>

          <div className="grid gap-3 lg:grid-cols-[1fr_1fr_1.1fr]">
            <div className={`${SUB} px-3 py-2`}>
              <p className="mb-1.5 text-meta font-semibold text-ink-muted">
                三维分 · 综合 <b className="text-ink">{item.overall_score.toFixed(2)}</b>
              </p>
              <div className="space-y-1">
                {(["dark_money", "trend", "activity"] as const).map((k) => (
                  <div key={k} className="flex gap-2 text-meta">
                    <span className="w-10 shrink-0 text-ink-muted">{DIM_SHORT[k]}</span>
                    <DimChip v={item.scores[k]} />
                    <span className="min-w-0 flex-1 text-ink-soft">{item.comments[k]}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className={`${SUB} px-3 py-2`}>
              <p className="mb-1.5 text-meta font-semibold text-ink-muted">资金 / 位置</p>
              <div className="space-y-1 text-meta text-ink-soft">
                {fund ? (
                  <>
                    <div>
                      主力净额 <YiText v={fund.main_net_yi} /> · 净占比 <PctText v={fund.main_pct} />
                    </div>
                    <div>
                      超大单 <YiText v={fund.super_net_yi} />
                    </div>
                  </>
                ) : (
                  <div className="text-ink-soft">该股不在当日资金流批次内（或资金维不可用）</div>
                )}
                {metrics ? (
                  <>
                    <div>
                      距 250 日高点 <PctText v={metrics.pct_from_high} /> · 近 20 日{" "}
                      <PctText v={metrics.r20} />
                    </div>
                    <div className="text-ink-soft">
                      MA5 {fmtNum(metrics.ma5)} · MA20 {fmtNum(metrics.ma20)} · MA60 {fmtNum(metrics.ma60)}
                    </div>
                  </>
                ) : (
                  <div className="text-ink-soft">K 线不足 60 根，趋势维与结构位不可用</div>
                )}
              </div>
            </div>

            <div className={`${SUB} px-3 py-2`}>
              <p className="mb-1.5 text-meta font-semibold text-ink-muted">买卖时机 · 结构位</p>
              {item.levels && (
                <p className="mb-1.5">
                  <ExpectedPriceChip ep={item.expected_price} />
                </p>
              )}
              <LevelChips levels={item.levels} />
              <p className="mt-1.5 text-meta text-ink-soft">{data.timing?.note}</p>
            </div>
          </div>

          {data.sector && <SectorCompare sector={data.sector} />}
          {!data.sector && (
            <p className="text-meta text-ink-soft">
              该股所在行业未能匹配到今日板块强度榜（可能不在资金流批次内，或行业字段缺失）——
              这里留空而不是给一个编造的板块分。
            </p>
          )}

          {data.note && <p className="text-meta text-amber-300/90">{data.note}</p>}
        </div>
      )}
    </div>
  );
}
