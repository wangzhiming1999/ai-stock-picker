import type { Caliber } from "../types";

/**
 * 口径说明的统一渲染件。
 *
 * 「验证」页同屏会出现 4 个都叫「胜率 / 命中率」的数字（大盘单日命中、推荐 T+1 胜率、
 * 策略调仓期胜率、形态 N 日前向胜率），标的 / 持有期 / 分类数 / 有无基准全不一样。
 * 不写口径就并排展示，读者会默认它们可比 —— 这是最难自查的一类「数据不准确」。
 *
 * 口径定义由后端 `calibers` 随数据一起下发，前端只展示，不自己解释。
 */

export function CaliberLine({ caliber, compact = false }: { caliber?: Caliber | null; compact?: boolean }) {
  if (!caliber || caliber.registered === false) {
    return (
      <p className="text-xs leading-relaxed text-ink-faint">
        口径未登记，请不要据此下结论（后端 calibers 缺少该指标定义）。
      </p>
    );
  }
  return (
    <div className="rounded-lg bg-slate-800/50 px-2.5 py-2 text-xs leading-relaxed">
      <div className="text-ink-soft">
        <span className="text-ink-muted">口径 · </span>
        {caliber.name}
      </div>
      <div className="mt-0.5 text-ink-faint">
        标的 {caliber.target} · 窗口 {caliber.window} · {caliber.bucket} · 基准 {caliber.benchmark}
      </div>
      <div className="mt-0.5 text-ink-faint">判定 {caliber.rule}</div>
      <div className="mt-0.5 text-ink-faint">样本 {caliber.unit}</div>
      {!compact && <div className="mt-1 text-amber-300/90">注意 {caliber.pitfall}</div>}
    </div>
  );
}

/**
 * 不可比声明。只要同屏出现两种以上口径，就必须显示它，
 * 否则用户会把「次日胜率 70%」和「形态胜率 45%」当成同一把尺子比较。
 */
export function CaliberIncomparabilityNote({ note }: { note?: string }) {
  return (
    <p className="rounded-lg border border-amber-900/50 bg-amber-950/25 px-3 py-2 text-xs leading-relaxed text-amber-200/90">
      {note ||
        "本页多个「胜率」的标的、持有期、分类数与是否对比基准都不同，数字之间不可比较、不可相加；" +
          "判断有效性必须看各自口径下的基准超额与样本量。"}
    </p>
  );
}
