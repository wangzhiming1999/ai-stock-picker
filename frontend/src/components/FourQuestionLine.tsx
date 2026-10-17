import type { FourQuestionItem, FourQuestions } from "../types";

/**
 * 四问守卫的渲染件。
 *
 * ## 为什么它必须常驻显示，不能折叠进 tooltip
 *
 * 口径说明（`CaliberLine`）回答「这个数字是什么意思」，四问回答
 * 「这个数字本身站不站得住」。后者的存在理由恰恰是**容易被忽略**：
 * 样本才 12 条、均值被一个 +40% 的极端样本撑起来、一半样本当时买不进 ——
 * 这些都不会让数字算错，只会让它被读成能力。所以一旦折叠就等于没有。
 *
 * ## 三态必须视觉可区分
 *
 * 每个问项有三种状态，语义完全不同：
 *   · 通过        —— 这一项没问题
 *   · 不通过      —— 检查了，发现明确失真（红）
 *   · 答不上来    —— 根本没检查（灰）
 * 最后一种最容易被漏渲染成「通过」—— 那样守卫就成了橡皮章，
 * 比没有守卫更坏。所以 `passed === null` 走独立的灰色分支与独立的形状标记。
 */

/** 三态 → 视觉档。用几何形状而非仅颜色区分，色弱/单色屏也能读。 */
function toneOf(item: FourQuestionItem): { mark: string; text: string; wrap: string } {
  if (!item.answered) {
    // 答不上来：问号 + 灰。它不是「通过」，也不是「失败」。
    return {
      mark: "?",
      text: "text-ink-muted",
      wrap: "bg-surface-inset/70",
    };
  }
  if (item.passed === false) {
    return {
      mark: "×",
      text: "text-state-danger-soft",
      wrap: "bg-state-danger-surface",
    };
  }
  return {
    mark: "✓",
    text: "text-ink-soft",
    wrap: "bg-surface-inset/70",
  };
}

/** 结论横幅：三态三色，且必须带文案，不能只靠色块。 */
function verdictBanner(four: FourQuestions): { title: string; cls: string } {
  if (four.verdict === "inflated") {
    return {
      title: "存在失真项 · 修正前不能当能力证据",
      cls: "border-state-danger-line bg-state-danger-surface text-state-danger-soft",
    };
  }
  if (four.verdict === "unknown") {
    return {
      title: "有项答不上来 · 只能当观察",
      cls: "border-state-warn-line bg-state-warn-surface text-state-warn-soft",
    };
  }
  return {
    title: "四问齐备 · 数字本身可信",
    cls: "border-state-ok-line bg-state-ok-surface text-state-ok-soft",
  };
}

export function FourQuestionLine({ four }: { four?: FourQuestions | null }) {
  if (!four || !Array.isArray(four.items) || four.items.length === 0) return null;
  const banner = verdictBanner(four);

  return (
    <div className="mt-2 rounded-lg bg-surface-inset/50 px-2.5 py-2">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-meta">
        <span className="font-medium text-ink-muted">四问</span>
        <span className="text-ink-faint">
          {four.answered_count}/{four.total_questions} 项有交代
        </span>
        {four.failed_keys.length > 0 && (
          <span className="text-state-danger-soft">{four.failed_keys.length} 项不通过</span>
        )}
        {four.unanswered_keys.length > 0 && (
          <span className="text-ink-muted">{four.unanswered_keys.length} 项答不上来</span>
        )}
      </div>

      {/* 四问：常驻渲染，不可折叠。每项一行：问法 + 读数 + 结论。 */}
      <ul className="mt-1.5 space-y-1">
        {four.items.map((item) => {
          const tone = toneOf(item);
          return (
            <li key={item.key} className="flex items-start gap-2 text-meta leading-relaxed">
              <span
                aria-hidden
                className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-md text-micro font-semibold ${tone.wrap} ${tone.text}`}
              >
                {tone.mark}
              </span>
              <span className="min-w-0">
                <span className="text-ink-muted">{item.label}</span>
                {item.value && <span className="ml-1 text-ink-soft">{item.value}</span>}
                <span className="mt-0.5 block text-ink-faint">{item.detail}</span>
              </span>
            </li>
          );
        })}
      </ul>

      <p className={`mt-2 rounded-lg border px-2.5 py-1.5 text-meta leading-relaxed ${banner.cls}`}>
        <span className="font-medium">{banner.title}</span>
        <span className="ml-1 text-ink-soft">{four.verdict_note}</span>
      </p>
    </div>
  );
}
