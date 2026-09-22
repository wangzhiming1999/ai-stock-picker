import { useMemo, useState } from "react";
import { sanduAutoCandidates, sanduScan } from "../../api/client";
import type { SanduAutoCandidate, SanduItem, SanduScanResult } from "../../types";
import CollapsiblePanel from "../ui/CollapsiblePanel";
import Button from "../ui/Button";
import Input from "../ui/Input";
import Table, { Th } from "../ui/Table";
import ScoreBar from "../ui/ScoreBar";
import { CELL } from "../../lib/ui";
import { scoreChip, actionTone } from "../../lib/tone";
import { fmtNum, fmtPct } from "../../lib/safe";

interface Props {
  onPick: (codes: string[]) => void;
}

/** 综合分达到该阈值才算「三度齐备」候选（0-10）。与后端默认一致。 */
const DEFAULT_MIN_OVERALL = 6.5;

const STATUS_CHIP: Record<SanduItem["status"], { bg: string; text: string; label: string }> = {
  passed: { bg: "bg-brand/15", text: "text-brand-light", label: "三度齐备" },
  watch: { bg: "bg-amber-500/15", text: "text-amber-300", label: "观察" },
  failed: { bg: "bg-surface-inset/40", text: "text-ink-muted", label: "未成型" },
  insufficient_data: { bg: "bg-surface-inset/40", text: "text-ink-muted", label: "数据不足" },
};

const ZONE_LABEL: Record<SanduItem["zone"], string> = {
  a: "a区 · 低位启动带",
  b: "b区 · 洗盘回踩带",
  risk: "风险区 · 高位",
  none: "—",
};

function StatusChip({ status }: { status: SanduItem["status"] }) {
  const c = STATUS_CHIP[status];
  return (
    <span className={`inline-block rounded-md px-2 py-0.5 text-meta font-medium ${c.bg} ${c.text}`}>
      {c.label}
    </span>
  );
}

/**
 * 三度打分扫描 · 选机会/sandu 子页
 *
 * 「三度」= 厚度（量形态）/ 力度（均线归位）/ 速度（放量异动），对给定候选
 * 逐只打分。口径提醒（文案不可删）：这是主力吸筹**结构**读数，条件成立 ≠
 * 已被验证（未回测），输出一律是候选/观察池，不是买点。
 *
 * 候选制输入（≤30 只）而非全市场扫描：逐只历史 K 是行情源风控主因，
 * 扫描范围必须由用户显式给出（自选、推荐榜、板块成分皆可）。
 */
export default function SanduPanel({ onPick }: Props) {
  const [raw, setRaw] = useState("");
  const [running, setRunning] = useState(false);
  const [picking, setPicking] = useState(false);
  const [result, setResult] = useState<SanduScanResult | null>(null);
  const [error, setError] = useState("");
  const [pickInfo, setPickInfo] = useState<SanduAutoCandidate[] | null>(null);

  const codes = useMemo(
    () =>
      Array.from(
        new Set(
          raw
            .split(/[\s,，;；\n]+/)
            .map((s) => s.trim())
            .filter(Boolean),
        ),
      ).slice(0, 30),
    [raw],
  );
  const overflow = raw.split(/[\s,，;；\n]+/).filter((s) => s.trim()).length > 30;

  const run = async (scanCodes?: string[]) => {
    const target = scanCodes ?? codes;
    if (target.length === 0 || running) return;
    setRunning(true);
    setError("");
    setResult(null);
    try {
      const r = await sanduScan(target, DEFAULT_MIN_OVERALL);
      setResult(r);
    } catch (e) {
      setError((e as Error).message || "三度扫描失败");
    } finally {
      setRunning(false);
    }
  };

  /** 一键自动候选：主力净流入榜前列 → 填入输入框 → 直接扫描 */
  const autoPick = async () => {
    if (picking || running) return;
    setPicking(true);
    setError("");
    try {
      const r = await sanduAutoCandidates(20);
      const cands = r.candidates;
      if (cands.length === 0) {
        setError("主力净流入榜暂无可选候选（全部被过滤），稍后再试或手动输入代码");
        return;
      }
      setRaw(cands.map((c) => c.code).join(" "));
      setPickInfo(cands);
      await run(cands.map((c) => c.code));
    } catch (e) {
      setError((e as Error).message || "自动候选获取失败");
    } finally {
      setPicking(false);
    }
  };

  const passed = result?.items.filter((r) => r.status === "passed") ?? [];
  const others = result?.items.filter((r) => r.status !== "passed") ?? [];

  return (
    <CollapsiblePanel
      id="sandu_scan"
      title="三度打分扫描"
      subtitle="厚度 · 力度 · 速度 三度合成读数 · 主力吸筹结构观察 · 未回测验证，输出是候选不是买点"
      action={
        result && result.scanned > 0 ? (
          <Button variant="primary" size="sm" onClick={() => onPick(passed.length > 0 ? passed.map((s) => s.code) : result.items.map((s) => s.code))}>
            去分析 →
          </Button>
        ) : undefined
      }
    >
      <p className="text-body text-ink-soft">
        输入候选代码（空格 / 逗号分隔，最多 30 只 —— 例如自选或推荐榜里的票），
        逐只拉 120 根日 K 打分。三度齐备（综合 ≥ {DEFAULT_MIN_OVERALL}）的标「三度齐备」，
        部分达标的标「观察」。
      </p>

      <div className="mt-3 flex items-start gap-2">
        <Input
          fieldSize="md"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          placeholder="例如：600519 000858 300750"
          aria-label="候选代码"
          className="flex-1"
        />
        <Button variant="ghost" size="md" onClick={() => void autoPick()} disabled={picking || running}>
          {picking ? "选票中..." : "帮我选"}
        </Button>
        <Button variant="primary" size="md" onClick={() => void run()} disabled={running || codes.length === 0}>
          {running ? "扫描中..." : `扫描（${codes.length}）`}
        </Button>
      </div>
      {pickInfo && (
        <p className="mt-1 text-meta text-ink-faint">
          候选来源：当日主力净流入榜前列（吸筹侧）——{" "}
          {pickInfo.slice(0, 5).map((c) => `${c.name || c.code}`).join("、")}
          {pickInfo.length > 5 ? ` 等 ${pickInfo.length} 只` : ""}
        </p>
      )}
      {overflow && (
        <p role="status" className="mt-1 text-meta text-amber-300">
          候选超过 30 只，仅取前 30 只 —— 控制逐只 K 线请求量（行情源风控约束）。
        </p>
      )}

      {running && (
        <div role="status" className="mt-3 rounded-lg bg-surface-inset/70 px-3 py-2 text-body text-ink-muted">
          三度扫描中（逐只拉取日 K，走缓存时约数秒，首次较慢）...
        </div>
      )}

      {!running && error && (
        <div role="alert" className="mt-3 rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">
          {error}
          <button onClick={() => void run()} className="ml-3 cursor-pointer font-medium text-red-200 underline">
            重试
          </button>
        </div>
      )}

      {!running && result && (
        <>
          <p className="mt-3 text-meta text-ink-muted">
            输入 {result.count} 只 · 成功取到 K 线 {result.scanned} 只 · 三度齐备 {passed.length} 只
          </p>

          {result.scanned === 0 ? (
            <div role="status" className="mt-2 rounded-lg border border-surface-line bg-surface-inset/40 px-3 py-3 text-body text-ink-soft">
              没有任何一只取到有效 K 线。若提示行情源冷却中，请等待冷却结束再试；代码格式需为 6 位数字（如 600519）。
            </div>
          ) : (
            <div className="mt-2 space-y-4">
              <Table label="三度打分结果" minWidth={920} maxHeight="md" head={
                <tr>
                  <Th>名称</Th>
                  <Th>代码</Th>
                  <Th align="right">现价</Th>
                  <Th align="right">涨跌</Th>
                  <Th align="right">厚度</Th>
                  <Th align="right">力度</Th>
                  <Th align="right">速度</Th>
                  <Th align="right">综合</Th>
                  <Th>位置区</Th>
                  <Th>状态</Th>
                  <Th>解读</Th>
                  <Th>操作</Th>
                </tr>
              }>
                {[...passed, ...others].map((s) => (
                  <tr key={s.code} className="border-t border-surface-line-soft hover:bg-surface-inset/40">
                    <td className={`${CELL} text-ink`}>{s.name || "—"}</td>
                    <td className={`${CELL} text-ink-muted`}>{s.code}</td>
                    <td className={`${CELL} text-right text-ink-soft`}>{s.price != null ? fmtNum(s.price) : "—"}</td>
                    <td className={`${CELL} text-right ${s.change_pct != null && s.change_pct >= 0 ? "text-red-400" : "text-green-400"}`}>
                      {s.change_pct != null ? fmtPct(s.change_pct) : "—"}
                    </td>
                    <td className={`${CELL} text-right text-ink-soft`}>{fmtNum(s.thickness, 1)}</td>
                    <td className={`${CELL} text-right text-ink-soft`}>{fmtNum(s.strength, 1)}</td>
                    <td className={`${CELL} text-right text-ink-soft`}>{fmtNum(s.velocity, 1)}</td>
                    <td className={CELL}>
                      <span className={`inline-block rounded-md px-2 py-0.5 text-meta font-semibold ${scoreChip(s.overall)}`}>
                        {fmtNum(s.overall, 1)}
                      </span>
                    </td>
                    <td className={`${CELL} text-meta text-ink-muted`}>{ZONE_LABEL[s.zone]}</td>
                    <td className={CELL}>
                      <StatusChip status={s.status} />
                    </td>
                    <td className={CELL}>
                      <span className={`text-meta ${actionTone(s.action)}`}>{s.action}</span>
                      {s.reasons.length > 0 && (
                        <span className="ml-1 text-meta text-ink-faint">{s.reasons[0]}</span>
                      )}
                    </td>
                    <td className={CELL}>
                      <button
                        onClick={() => onPick([s.code])}
                        className="cursor-pointer text-meta text-brand-light underline hover:text-brand"
                      >
                        去分析
                      </button>
                    </td>
                  </tr>
                ))}
              </Table>

              {/* 齐备票的三度分解：每只给三条 ScoreBar，便于看清是哪一度拖了后腿 */}
              {passed.length > 0 && (
                <div className="rounded-xl bg-surface-inset p-4">
                  <p className="text-body font-semibold text-ink">三度齐备 · 逐维拆解</p>
                  <div className="mt-3 space-y-3">
                    {passed.map((s) => (
                      <div key={s.code} className="space-y-1.5">
                        <p className="text-label text-ink-muted">
                          {s.name}（{s.code}）· {ZONE_LABEL[s.zone]}
                        </p>
                        <ScoreBar label="厚度" score={s.thickness} />
                        <ScoreBar label="力度" score={s.strength} />
                        <ScoreBar label="速度" score={s.velocity} />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 维度条件明细（可展开，默认收起） */}
              <details className="rounded-xl bg-surface-inset px-4 py-3">
                <summary className="cursor-pointer text-body font-semibold text-ink">
                  全部候选 · 逐条条件明细（{result.items.length} 只）
                </summary>
                <div className="mt-3 space-y-3">
                  {result.items.map((s) => (
                    <div key={s.code} className="rounded-lg bg-surface-raised/60 px-3 py-2">
                      <p className="text-label text-ink">
                        {s.name || s.code}（{s.code}）· 综合 {fmtNum(s.overall, 1)} · {s.action}
                      </p>
                      <div className="mt-1.5 grid gap-x-6 gap-y-1 sm:grid-cols-3">
                        {s.dimensions.map((d) => (
                          <div key={d.name}>
                            <p className="text-meta font-medium text-ink-muted">
                              {d.name} {fmtNum(d.score, 1)}
                            </p>
                            <ul className="mt-0.5 space-y-0.5">
                              {d.conditions.map((c, i) => (
                                <li key={i} className="flex items-start gap-1.5 text-meta">
                                  <span className={c.passed ? "text-brand-light" : "text-ink-faint"}>
                                    {c.passed ? "✓" : "✗"}
                                  </span>
                                  <span className="text-ink-soft">{c.label}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            </div>
          )}
        </>
      )}

      <div className="mt-3 space-y-1 text-meta text-ink-faint">
        <p>
          口径：厚度 = 三阳控三阴（阳多阴少 / 阳放阴缩 / 阳聚阴散，量形态能量堆积）；
          力度 = 均线归位（金叉 / 多头排列 / 站上 MA20，对应 a区·b区洗盘结构）；
          速度 = 关键位置的量价异动（近端放量上攻）。三度加权 0.3 / 0.4 / 0.3。
        </p>
        <p>
          三度读数是主力吸筹**结构**观察，全部条件未通过回测验证（证据档「未验证」）；
          风险区（高位巨量 / 高点降低）只标注不排除。输出为候选池，不构成买入建议；实盘请自行判断。
        </p>
      </div>
    </CollapsiblePanel>
  );
}
