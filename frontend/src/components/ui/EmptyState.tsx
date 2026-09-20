import type { ComponentType, ReactNode, SVGProps } from "react";
import { CARD, TEXT } from "../../lib/ui";

type IconComp = ComponentType<SVGProps<SVGSVGElement>>;

interface Props {
  icon?: IconComp;
  title: string;
  desc?: ReactNode;
  /** 空状态必须给下一步动作 —— 否则用户只能退回去。 */
  action?: ReactNode;
  /** 嵌在面板内部时用 compact（不套主卡、内边距更小）。 */
  compact?: boolean;
}

/**
 * 空状态
 *
 * 此前空状态有 6 种写法：有的只有一行灰字、有的套了主卡、有的是「暂无数据」四个字
 * 连图标都没有。统一形状后，「这里现在没东西 + 你接下来能做什么」变成默认表达。
 *
 * ⚠️ 空状态不要用来表达**失败**。失败有专门的呈现（错误条 + 重试），
 * 两者混淆会让用户以为「今天就是没有」，而实际上是请求挂了 ——
 * 本项目的盯盘链路就踩过这个坑（异常被吞成空数据，看起来像"没命中"）。
 */
export default function EmptyState({ icon: Icon, title, desc, action, compact = false }: Props) {
  return (
    <div
      className={`text-center ${compact ? "px-4 py-8" : `${CARD} px-6 py-12`}`}
    >
      {Icon && (
        <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-surface-inset">
          <Icon className="h-5 w-5 text-ink-muted" aria-hidden />
        </div>
      )}
      <p className={`mt-3 font-medium text-ink ${compact ? "text-sm" : ""}`}>{title}</p>
      {desc && <p className={`mt-1 ${TEXT.meta} ${compact ? "" : "mx-auto max-w-md"}`}>{desc}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
