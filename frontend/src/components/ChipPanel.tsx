import { useEffect, useState } from "react";
import { listTactics, chipScan } from "../api/client";
import { confirmForceRefresh, useSpotCooldown } from "../lib/spotGuard";
import CollapsiblePanel from "./ui/CollapsiblePanel";
import { TacticChip, TacticEvidenceLegend } from "./TacticHit";
import type { TacticDef, TacticResult, TacticScanResult } from "../types";
import Button from "./ui/Button";
import Table, { Th } from "./ui/Table";
import { CELL } from "../lib/ui";

interface Props {
  onPick: (codes: string[]) => void;
}

/** 筹码形态技巧 key（与后端 pattern_service.TACTICS 一致） */
const CHIP_KEYS = ["chip_single_peak", "chip_low_profit", "chip_transfer_up"] as const;

/**
 * 筹码形态洞察 · 选机会/chip 子页
 *
 * 与 TacticPanel 的关系：扫描链路**完全复用**（后端同一个端点、同一个结果结构），
 * 差异只有三点 —— 技巧清单过滤为筹码类、扫描只发 chip_* 键、说明文案讲筹码口径。
 * 不直接复用 TacticPanel 组件的原因：把「技巧清单过滤 + 文案」做成参数会让那个
 * 组件背上两个域的条件逻辑，不如各自薄封装。
 *
 * 口径提醒（文案不可删）：筹码指标由本项目自复刻东财 CYQ（三角分布近似），
 * 与东财 App 官方读数存在小幅偏差；三条形态均未回测验证，命中一律进观察池。
 */
export default function ChipPanel({ onPick }: Props) {
  const { seconds: cooldown } = useSpotCooldown();
  const [tactics, setTactics] = useState<TacticDef[]>([]);
  const [active, setActive] = useState("all");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TacticScanResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    listTactics()
      .then((items) => {
        if (alive) setTactics(items.filter((t) => (CHIP_KEYS as readonly string[]).includes(t.key)));
      })
      .catch(() => {
        if (alive) setError("技巧清单加载失败，请稍后重试");
      });
    return () => {
      alive = false;
    };
  }, []);

  const items = result?.items ?? [];
  const runningLabel =
    active === "all"
      ? "筹码扫描中（逐只拉取 210 根 K 线计算筹码分布，首次较慢，之后走当日缓存）..."
      : "筹码扫描中...";
  const run = async (key: string, force = false) => {
    setActive(key);
    setRunning(true);
    setError("");
    setResult(null);
    try {
      const r = await chipScan({
        tactic: key === "all" ? undefined : (key as (typeof CHIP_KEYS)[number]),
        limit: 20,
        minAmountYi: 3,
        force,
      });
      setResult(r);
    } catch (e) {
      setError((e as Error).message || "筹码扫描失败");
    } finally {
      setRunning(false);
    }
  };

  const forceRun = async () => {
    if (!(await confirmForceRefresh())) return;
    await run(active, true);
  };

  return (
    <CollapsiblePanel
      id="scan_chip"
      title="筹码形态洞察"
      subtitle="筹码峰形态扫描 · 自复刻东财 CYQ · 三条形态均未回测，命中一律进观察池 · 默认读当日缓存"
      action={
        <div className="flex items-center gap-2">
          <Button variant="outlineQuiet" size="sm" onClick={() => void forceRun()} disabled={running || cooldown > 0}>
            {cooldown > 0 ? `冷却 ${cooldown}s` : "强制刷新"}
          </Button>
          {items.length > 0 && (
            <Button variant="primary" size="sm" onClick={() => onPick(items.map((s) => s.code))}>
              去分析 →
            </Button>
          )}
        </div>
      }
    >
      <div className="mb-3 flex flex-wrap gap-2">
        <button
          onClick={() => void run("all")}
          disabled={running}
          aria-pressed={active === "all"}
          className={`rounded-lg border px-3 py-2 text-left text-body transition ${
            active === "all" ? "border-brand bg-brand/10 text-white" : "border-surface-line text-ink hover:border-surface-line-hover"
          }`}
        >
          全部筹码形态
          <span className="ml-2 text-meta text-ink-muted">{tactics.length} 条一起查</span>
        </button>
        {tactics.map((t) => (
          <button
            key={t.key}
            onClick={() => void run(t.key)}
            disabled={running}
            aria-pressed={active === t.key}
            title={t.evidence.summary}
            className={`rounded-lg border px-3 py-2 text-left text-body transition ${
              active === t.key ? "border-brand bg-brand/10 text-white" : "border-surface-line text-ink hover:border-surface-line-hover"
            }`}
          >
            {t.name}
            <span className="ml-2 text-meta text-ink-muted">{t.evidence.badge}</span>
          </button>
        ))}
      </div>

      <TacticEvidenceLegend />

      {running && (
        <div role="status" className="mt-3 rounded-lg bg-surface-inset/70 px-3 py-2 text-body text-ink-muted">
          {runningLabel}
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
          已检查 {result.checked} 只候选，当前没有筹码形态命中。筹码形态对「换手充分度」要求高，未命中属正常；
          部分个股可能因东财数据源失败缺数据，可稍后重试。
        </div>
      )}

      {!running && items.length > 0 && (
        <Table label="筹码形态扫描结果" maxHeight="sm" head={
          <tr>
            <Th>名称</Th>
            <Th>代码</Th>
            <Th>命中形态</Th>
            <Th>结论</Th>
            <Th>操作</Th>
          </tr>
        }>
              {items.map((s) => {
                // tactics 缺失（后端部分成功/旧结构）时按无命中处理，不能让整页崩进 ErrorBoundary
                const hits = ((s.tactics as TacticResult[] | undefined) ?? []).filter((t) => t.matched);
                const best = hits[0];
                return (
                  <tr key={s.code} className="border-t border-surface-line-soft hover:bg-surface-inset/40">
                    <td className={`${CELL} text-ink`}>{s.name}</td>
                    <td className={`${CELL} text-ink-muted`}>{s.code}</td>
                    <td className={CELL}>
                      <div className="flex flex-wrap items-center gap-1">
                        {hits.map((t) => (
                          <TacticChip key={t.key} t={t} />
                        ))}
                      </div>
                      {best && (
                        <ul className="mt-1 space-y-0.5">
                          {best.conditions.map((cond, i) => (
                            <li key={i} className="flex items-start gap-2 text-meta">
                              <span className={cond.passed ? "text-brand-light" : "text-ink-muted"}>
                                {cond.passed ? "✓" : "✗"}
                              </span>
                              <span className="text-ink-soft">{cond.name}</span>
                              <span className="text-ink-soft">{cond.detail}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td className={`${CELL} text-ink-soft`}>
                      <span className="text-ink-soft">{s.best_gate_note || "尚未通过回测验证（观察池）"}</span>
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
                );
              })}
        </Table>
      )}

      <div className="mt-3 space-y-1 text-meta text-ink-soft">
        <p>
          口径：筹码分布由本项目复刻东财 CYQ 算法（120 日窗口三角分布、按换手率衰减），
          指标与东财 App 官方读数存在小幅偏差；获利比例 / 成本区间 / 集中度为算法推导读数。
        </p>
        <p>
          三条筹码形态均未通过回测验证（证据档「未验证」），命中只代表形态条件成立，
          不构成买入建议；实盘请自行判断。
        </p>
      </div>
    </CollapsiblePanel>
  );
}
