import { Fragment, useEffect, useMemo, useState } from "react";
import { listTactics, tacticScan } from "../api/client";
import { fmtNum } from "../lib/safe";
import { confirmForceRefresh, useSpotCooldown } from "../lib/spotGuard";
import { pnlTone } from "../lib/tone";
import CollapsiblePanel from "./ui/CollapsiblePanel";
import { TacticChip, TacticEvidenceLegend, tacticEvidence } from "./TacticHit";
import type { TacticDef, TacticResult, TacticScanResult } from "../types";
import Button from "./ui/Button";
import Table, { Th } from "./ui/Table";
import { CELL } from "../lib/ui";

interface Props {
  onPick: (codes: string[]) => void;
  /** 批量加自选（未登录时由上层弹登录） */
  onImport: (codes: string[]) => void;
}

const DIRECTION_LABEL: Record<TacticDef["direction"], string> = { buy: "买点", sell: "卖点" };

function buttonClass(direction: TacticDef["direction"], active: boolean): string {
  if (direction === "buy") {
    return active ? "border-red-500 bg-red-600/15" : "border-surface-line hover:border-red-600/70";
  }
  return active ? "border-green-500 bg-green-600/15" : "border-surface-line hover:border-green-600/70";
}

/** 未通过回测验证的技巧按钮用中性边框：它不该看起来和已验证的买点一样硬。 */
function tileClass(t: TacticDef, active: boolean): string {
  if (!t.actionable) {
    return active ? "border-brand bg-brand/10" : "border-surface-line hover:border-surface-line-hover";
  }
  return buttonClass(t.direction, active);
}

function DirectionTag({ direction }: { direction: TacticDef["direction"] }) {
  return (
    <span
      className={`rounded-md px-1.5 py-0.5 text-meta ${
        direction === "buy" ? "bg-red-600/20 text-red-300" : "bg-green-600/20 text-green-300"
      }`}
    >
      {DIRECTION_LABEL[direction]}
    </span>
  );
}

/** 证据角标：质量/可信度语义，刻意不用红绿（红绿只表达方向）。 */
function EvidenceTag({ evidence }: { evidence: TacticDef["evidence"] }) {
  const tone =
    evidence.tier === "verified"
      ? "bg-brand/20 text-brand-light"
      : evidence.tier === "preliminary"
        ? "bg-amber-500/15 text-amber-300"
        : "bg-surface-line/70 text-ink-muted";
  return (
    <span
      title={`${evidence.label} · ${evidence.summary}\n依据：${evidence.provenance}`}
      className={`rounded-md px-1.5 py-0.5 text-meta ${tone}`}
    >
      {evidence.label}
    </span>
  );
}

export default function TacticPanel({ onPick, onImport }: Props) {
  const { seconds: cooldown } = useSpotCooldown();
  const [tactics, setTactics] = useState<TacticDef[]>([]);
  const [active, setActive] = useState("all");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TacticScanResult | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    let alive = true;
    listTactics()
      .then((items) => {
        if (alive) setTactics(items);
      })
      .catch(() => {
        if (alive) setError("技巧清单加载失败，请稍后重试");
      });
    return () => {
      alive = false;
    };
  }, []);

  const categories = useMemo(() => Array.from(new Set(tactics.map((t) => t.category))), [tactics]);
  const items = result?.items ?? [];

  const run = async (key: string, force = false) => {
    setActive(key);
    setRunning(true);
    setError("");
    setResult(null);
    setSelected(new Set());
    setExpanded(new Set());
    try {
      // 默认走缓存（内存 5min → Supabase 6h）。原实现硬编码 force=true，
      // 每点一次技巧都绕过两层缓存直打全市场行情源 —— 是 502 风控的前端侧根因之一。
      const r = await tacticScan({
        tactic: key === "all" ? undefined : key,
        limit: 20,
        minAmountYi: 3,
        force,
      });
      setResult(r);
    } catch (e) {
      setError((e as Error).message || "形态扫描失败");
    } finally {
      setRunning(false);
    }
  };

  const forceRun = async () => {
    if (!(await confirmForceRefresh())) return;
    await run(active, true);
  };

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const toggleExpand = (code: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  return (
    <CollapsiblePanel
      id="scan_tactics"
      title="实战形态"
      subtitle="按技巧找形态命中 · 全部条件成立才命中，宁缺毋滥 · 证据等级由回测判定 · 默认读缓存"
      action={
        <div className="flex items-center gap-2">
          <Button variant="outlineQuiet" size="sm"
            onClick={() => void forceRun()}
            disabled={running || cooldown > 0}
            >
            {cooldown > 0 ? `冷却 ${cooldown}s` : "强制刷新"}
          </Button>
          {items.length > 0 && (
            <>
              <button
                onClick={() => onImport(items.map((s) => s.code))}
                className="rounded-lg border border-surface-line-strong px-3 py-1 text-meta text-ink-soft hover:border-surface-line-hover hover:text-white"
              >
                全部加自选
              </button>
              <Button variant="primary" size="sm"
                onClick={() => onPick(Array.from(selected))}
                disabled={selected.size === 0}
                >
                勾选 {selected.size} 只去分析 →
              </Button>
            </>
          )}
        </div>
      }
    >
      <div className="mb-3">
        <button
          onClick={() => void run("all")}
          disabled={running}
          aria-pressed={active === "all"}
          className={`rounded-lg border px-3 py-2 text-left text-body transition ${
            active === "all" ? "border-brand bg-brand/10 text-white" : "border-surface-line text-ink hover:border-surface-line-hover"
          }`}
        >
          全部技巧
          <span className="ml-2 text-meta text-ink-muted">
            {tactics.length > 0 ? `${tactics.length} 条一起查` : "一起查"}
          </span>
        </button>
      </div>

      {categories.map((cat) => (
        <div key={cat} className="mb-3">
          <p className="mb-1 text-meta font-semibold tracking-wide text-ink-muted">{cat}</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {tactics
              .filter((t) => t.category === cat)
              .map((t) => (
                <button
                  key={t.key}
                  onClick={() => void run(t.key)}
                  disabled={running}
                  aria-pressed={active === t.key}
                  title={t.evidence.summary}
                  className={`rounded-lg border p-3 text-left transition ${tileClass(t, active === t.key)}`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-body font-medium text-ink-strong">{t.name}</span>
                    {t.actionable ? <DirectionTag direction={t.direction} /> : <EvidenceTag evidence={t.evidence} />}
                  </div>
                  <div className="mt-0.5 text-meta text-ink-soft">{t.desc}</div>
                </button>
              ))}
          </div>
        </div>
      ))}

      <TacticEvidenceLegend />

      {running && (
        <div role="status" className="mt-3 rounded-lg bg-surface-inset/70 px-3 py-2 text-body text-ink-muted">
          形态扫描中（拉取行情与 K 线；多周期共振额外取周线/月线，首次较慢，之后走 6h/24h 缓存）...
        </div>
      )}

      {!running && error && (
        <div role="alert" className="rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">
          {error}
          <button onClick={() => void run(active)} className="ml-3 cursor-pointer font-medium text-red-200 underline">
            重试
          </button>
        </div>
      )}

      {!running && result && items.length === 0 && (
        <div role="status" className="rounded-lg border border-surface-line bg-surface-inset/40 px-3 py-3 text-body text-ink-soft">
          已检查 {result.checked} 只候选，当前没有「全部条件成立」的形态。形态识别宁缺毋滥，未命中属正常。
        </div>
      )}

      {!running && items.length > 0 && (
        <Table label="实战形态扫描结果" maxHeight="sm" head={
          <tr>
            <Th>勾选</Th>
            <Th>名称</Th>
            <Th>代码</Th>
            <Th align="right">涨跌幅</Th>
            <Th>命中形态</Th>
            <Th>结论</Th>
          </tr>
        }>
              {items.map((s) => (
                <Fragment key={s.code}>
                  <tr
                    onClick={() => toggle(s.code)}
                    className={`cursor-pointer border-t border-surface-line-soft hover:bg-surface-inset/40 ${
                      selected.has(s.code) ? "bg-surface-inset/70" : ""
                    }`}
                  >
                    <td className={CELL}>
                      <input
                        type="checkbox"
                        readOnly
                        checked={selected.has(s.code)}
                        aria-label={`选择 ${s.name}`}
                        className="accent-brand"
                      />
                    </td>
                    <td className={`${CELL} text-ink`}>{s.name}</td>
                    <td className={`${CELL} text-ink-muted`}>{s.code}</td>
                    <td
                      className={`${CELL} text-right ${pnlTone(s.change_pct)}`}
                    >
                      {(s.change_pct ?? 0) >= 0 ? "+" : ""}
                      {fmtNum(s.change_pct ?? 0)}%
                    </td>
                    <td className={CELL}>
                      <div className="flex flex-wrap items-center gap-1">
                        {((s.tactics as TacticResult[] | undefined) ?? []).map((t) => (
                          <TacticChip key={t.key} t={t} />
                        ))}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpand(s.code);
                          }}
                          aria-expanded={expanded.has(s.code)}
                          className="cursor-pointer text-meta text-ink-muted underline hover:text-ink"
                        >
                          {expanded.has(s.code) ? "收起条件" : "看条件"}
                        </button>
                      </div>
                    </td>
                    <td className={`${CELL} text-ink-soft`}>
                      {s.best_action ? (
                        s.best_action
                      ) : (
                        <span className="text-ink-faint">
                          {s.best_gate_note || "尚未通过回测验证（观察池）"}
                        </span>
                      )}
                    </td>
                  </tr>
                  {expanded.has(s.code) && (
                    <tr className="border-t border-surface-line-soft bg-surface-panel">
                      <td colSpan={6} className={CELL}>
                        <div className="space-y-2">
                          {((s.tactics as TacticResult[] | undefined) ?? []).map((t: TacticResult) => (
                            <div key={t.key}>
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="text-meta font-semibold text-ink">{t.name}</span>
                                <TacticChip t={t} />
                                <span className="text-meta text-ink-faint">
                                  {t.passed}/{t.total} 条件成立
                                </span>
                                <span className="text-meta text-ink-soft">
                                  证据：{tacticEvidence(t).label} · {tacticEvidence(t).provenance}
                                </span>
                              </div>
                              {t.gate_note && (
                                <p className="mt-1 rounded-md bg-surface-inset/60 px-2 py-1 text-meta leading-relaxed text-ink-muted">
                                  {t.gate_note}
                                </p>
                              )}
                              <ul className="mt-1 space-y-0.5">
                                {t.conditions.map((cond, i) => (
                                  <li key={i} className="flex items-start gap-2 text-meta">
                                    {/* ✓/✗ 是「通过项」，属质量语义，不得占用红绿（红绿只表达方向） */}
                                    <span className={cond.passed ? "text-brand-light" : "text-ink-muted"}>
                                      {cond.passed ? "✓" : "✗"}
                                    </span>
                                    <span className="text-ink-soft">{cond.name}</span>
                                    <span className="text-ink-soft">{cond.detail}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
        </Table>
      )}

      <p className="mt-3 text-meta text-ink-muted">
        形态由 K 线量价条件确定性推导，标注「算法推导」，不构成投资建议；命中不代表必然上涨，
        实盘请自行判断。
      </p>
    </CollapsiblePanel>
  );
}
