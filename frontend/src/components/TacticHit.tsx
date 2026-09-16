import type { TacticResult } from "../types";

/**
 * 形态命中的统一渲染件。
 *
 * 为什么收口成一个组件：形态结果在 4 个界面出现（扫描 / 盯盘 / 简报 / 深度分析），
 * 每处各自拼一次 chip 与文案，导致「同一个形态在 A 页是买点、在 B 页是观察」。
 * 证据等级（`tactic_evidence`）由后端统一挂载，这里只负责**如实呈现**：
 *
 * - `executable = true`（回测达统计显著）才显示方向色（买点红 / 卖点绿）；
 * - 未验证的命中一律给中性「观察」角标 + 观察池说明，**不使用方向色**。
 *
 * 这一点是刻意的：方向色会被读成「该动手了」。判定条件成立只是数学结果，
 * 不等于该形态被证明有效 —— 把两者混在一起就是用户说的「数据不准确」。
 */

/**
 * 归一化：老缓存（改造前写入的形态结果）没有证据字段。
 *
 * 缺失时一律按「未验证」处理 —— 宁可把可用的形态标成观察，也不能因为字段缺失
 * 就让它默认显示成买点。
 */
function normalize(t: TacticResult) {
  const evidence = t.evidence ?? {
    tier: "unknown" as const,
    label: "未验证",
    badge: "观察",
    summary: "该结果来自改造前的缓存，未携带证据等级。",
    provenance: "旧缓存",
    actionable: false,
  };
  const executable = t.executable === true && evidence.actionable;
  return { evidence, executable };
}

function directionChipClass(direction: string, executable: boolean): string {
  if (!executable) {
    // 未验证：中性色，避免被读成买卖指令。质量/可信度类语义不得占用红绿。
    return "bg-slate-700/70 text-ink-soft";
  }
  return direction === "buy" ? "bg-red-600/20 text-red-300" : "bg-green-600/20 text-green-300";
}

export function TacticChip({ t, title }: { t: TacticResult; title?: string }) {
  const { evidence, executable } = normalize(t);
  return (
    <span
      title={title ?? (executable ? t.action : t.gate_note || t.action)}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs ${directionChipClass(
        t.direction,
        executable,
      )}`}
    >
      <span>{t.name}</span>
      {!executable && (
        <span className="rounded bg-slate-900/70 px-1 text-ink-faint">{evidence.badge}</span>
      )}
    </span>
  );
}

export function TacticChips({ tactics }: { tactics: TacticResult[] }) {
  if (tactics.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {tactics.map((t) => (
        <TacticChip key={t.key} t={t} />
      ))}
    </div>
  );
}

/**
 * 一行「结论」文案：只有证据达标的命中才给动作话术，否则给观察池说明。
 *
 * 后端已经保证 `executable` 与 `gate_note` 一致，这里不再自己判断 tier，
 * 避免前端另立一套证据口径。
 */
export function TacticTakeaway({ tactics }: { tactics: TacticResult[] }) {
  if (tactics.length === 0) return null;
  const executable = tactics.filter((t) => normalize(t).executable);
  if (executable.length > 0) {
    return <>{executable.map((t) => t.action).join("；")}</>;
  }
  const first = tactics[0];
  return <span className="text-ink-faint">{first.gate_note || "观察池 · 尚未通过回测验证"}</span>;
}

/** 单条形态的证据等级（供需要自行排版的地方复用兜底逻辑）。 */
export function tacticEvidence(t: TacticResult) {
  return normalize(t).evidence;
}

/** 证据等级文字。 */
export function tacticEvidenceLabel(t: TacticResult): string {
  return tacticEvidence(t).label;
}

/** 形态清单底部的口径说明，与后端 `tactic_evidence` 的分级定义一一对应。 */
export function TacticEvidenceLegend() {
  return (
    <p className="mt-2 text-xs leading-relaxed text-ink-faint">
      证据等级由 walk-forward 回测判定：<span className="text-ink-soft">已验证</span>
      （样本 ≥30 且 |z| ≥1.96，可作买卖点）·
      <span className="text-ink-soft">初步</span>（方向一致但样本不足，仅线索）·
      <span className="text-ink-soft">观察</span>
      （无显著优势或无法回测）。当前没有任何形态达到「已验证」，因此全部命中都只作观察 ——
      判定条件成立不等于该形态被证明有效。
    </p>
  );
}
