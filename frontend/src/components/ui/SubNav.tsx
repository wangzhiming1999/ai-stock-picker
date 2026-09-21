import type { ComponentType, SVGProps } from "react";
import { motion } from "framer-motion";

type IconComp = ComponentType<SVGProps<SVGSVGElement>>;

export interface SubNavItem<K extends string = string> {
  key: K;
  label: string;
  icon?: IconComp;
}

interface Props<K extends string> {
  /** 无障碍标签，同时作为滑动指示条的 layoutId 前缀（必须全站唯一）。 */
  id: string;
  items: SubNavItem<K>[];
  value: K;
  onChange: (key: K) => void;
}

/**
 * 二级导航 · 吸顶分段控件
 *
 * ## 为什么吸顶
 * 重构前子导航是**静态**的：三个子 tab 排在最上面，往下滚两屏之后它就滚没了，
 * 想换子页必须一路滚回顶部。而每个子页本身就有 4~5 个区块那么长 ——
 * 这直接把功能藏在了「深度 3 且没有回头路」的位置，是「找不到」的主要机械原因。
 * 吸顶之后，一级导航（顶栏）+ 二级导航（这里）在任何滚动位置都同时可见，
 * **任意功能的可达深度被锁死在 2 层**。
 *
 * ## 为什么用滑动指示条而不是换底色
 * 换底色的方案在上一版用过，问题是「哪一个是当前项」只能靠颜色对比判断，
 * 而颜色在同一屏里还承担着涨跌语义，容易打架。滑动条是**位置**信息，
 * 与语义色互不干扰。
 *
 * ## 为什么按钮按内容宽度排、放不下就横向滚动
 * 按钮曾经是 `flex-1`（等分整行）。子页少时看着整齐，但等分后每个按钮只有 1/N 宽度，
 * label 会被挤成竖排单字。所以改成：宽度由内容决定（`flex-auto` + `whitespace-nowrap`），
 * 容器 `scroll-x` 兜底 —— 放得下就铺开，放不下就横向滚动，永不折行。
 */
export default function SubNav<K extends string>({ id, items, value, onChange }: Props<K>) {
  return (
    <nav
      aria-label="子页面"
      className="sticky top-[var(--header-h)] z-30 -mx-1 rounded-xl border border-surface-line bg-surface-panel/95 px-1 py-1 backdrop-blur"
    >
      <div className="scroll-x flex gap-1">
        {items.map((it) => {
          const Icon = it.icon;
          const active = value === it.key;
          return (
            <button
              key={it.key}
              type="button"
              onClick={() => onChange(it.key)}
              aria-current={active ? "page" : undefined}
              className={`relative flex flex-auto items-center justify-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-body font-medium transition-colors ${
                active ? "text-white" : "text-ink-muted hover:text-ink"
              }`}
            >
              {active && (
                <motion.span
                  layoutId={`subnav-${id}`}
                  className="absolute inset-0 rounded-lg bg-brand"
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                />
              )}
              <span className="relative flex items-center gap-1.5">
                {Icon && <Icon className="h-4 w-4" strokeWidth={2.2} aria-hidden />}
                {it.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
