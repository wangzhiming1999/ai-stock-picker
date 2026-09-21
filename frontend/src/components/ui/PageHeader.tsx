import type { ComponentType, ReactNode, SVGProps } from "react";
import { TEXT } from "../../lib/ui";

type IconComp = ComponentType<SVGProps<SVGSVGElement>>;

interface Props {
  title: string;
  /** 这一页回答什么问题。一级页必填 —— 它同时是「这个 tab 到底装了什么」的说明。 */
  desc?: string;
  icon?: IconComp;
  /** 右侧元信息：状态、时间、当前时段读数。 */
  meta?: ReactNode;
}

/**
 * 页面头 · 每个一级页面顶部唯一一处 h1
 *
 * 为什么需要：此前三个页面都没有标题 —— 顶部那个 tab 条既是导航又是"我在哪"
 * 的唯一线索，用户切进来后满屏都是卡片，没有一句话告诉他这一页的主题。
 *
 * 规范：
 *   · 页面内**只有一处 h1**（就是这里），区块标题一律 h3；h2 留给未来的分组。
 *   · desc 写「回答什么」，不写「有什么功能」—— 后者应该从内容本身看出来。
 */
export default function PageHeader({ title, desc, icon: Icon, meta }: Props) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 pb-1">
      <div className="min-w-0">
        <h1 className={TEXT.h1}>
          <span className="flex items-center gap-2">
            {Icon && <Icon className="h-5 w-5 shrink-0 text-brand-light" aria-hidden />}
            {title}
          </span>
        </h1>
        {desc && <p className="mt-1 text-body text-ink-muted">{desc}</p>}
      </div>
      {meta && <div className="shrink-0 text-right text-meta text-ink-muted">{meta}</div>}
    </header>
  );
}
