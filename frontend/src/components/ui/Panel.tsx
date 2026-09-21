import type { ComponentType, ReactNode, SVGProps } from "react";
import { PANEL_ACTIONS, PANEL_BODY, PANEL_DESC, PANEL_HEAD, PANEL_TITLE } from "../../lib/ui";
import { cn } from "../../lib/cn";
import { panelShellVariants } from "./CollapsiblePanel";

type IconComp = ComponentType<SVGProps<SVGSVGElement>>;

interface Props {
  /** 面板标题。省略则只渲染无头容器（纯容器用法）。 */
  title?: ReactNode;
  /** 一句话说明「这个面板回答什么问题」。不要写「值得买」这类话术。 */
  desc?: ReactNode;
  icon?: IconComp;
  /** 头部右侧操作区（按钮、刷新等）。 */
  actions?: ReactNode;
  /** 头部副信息，跟在 desc 后面（更新时间、口径提示）。 */
  meta?: ReactNode;
  /** 锚点 id —— 二级导航滚动定位靠它。 */
  id?: string;
  className?: string;
  /** 内容区内边距覆盖。表格类面板常传 "" 自己控制。 */
  bodyClassName?: string;
  children: ReactNode;
}

/**
 * 面板 · 唯一的主卡形状
 *
 * 替代此前全站 12+ 种手写的「rounded-2xl border border-surface-line bg-surface-panel p-5」。
 * 头部固定为「图标 + 标题 + 说明 + 右侧操作」，用一条弱分隔线与内容分开 ——
 * 这条线是必要的：没有它，标题会看起来像内容的第一行。
 *
 * ⚠️ 卡片外观**不在本文件定义** —— 复用 `CollapsiblePanel` 的 `panelShellVariants`。
 *    这是刻意的：折叠面板与静态面板在同一个页面里是并列的两种形态，
 *    它们必须长得一样。分成两张变体表的那一刻，它们就开始各自演化了。
 *
 * 不建议再手写 CARD_* 组合；确实需要非常规布局时传 bodyClassName 微调。
 */
export default function Panel({
  title,
  desc,
  icon: Icon,
  actions,
  meta,
  id,
  className,
  bodyClassName = PANEL_BODY,
  children,
}: Props) {
  const hasHead = title != null;

  return (
    <section id={id} className={cn(panelShellVariants({ surface: "panel" }), "scroll-mt-0", className)}>
      {hasHead && (
        <div className={PANEL_HEAD}>
          <div className="min-w-0">
            <h3 className={PANEL_TITLE}>
              {Icon && <Icon className="h-4 w-4 shrink-0 text-brand-light" aria-hidden />}
              {title}
            </h3>
            {(desc || meta) && (
              <p className={PANEL_DESC}>
                {desc}
                {desc && meta ? " · " : ""}
                {meta}
              </p>
            )}
          </div>
          {actions && <div className={PANEL_ACTIONS}>{actions}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
