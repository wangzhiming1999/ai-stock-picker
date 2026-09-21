import { useEffect, useRef } from "react";

/**
 * 区块级聚焦 · 「功能地图点到具体那一块」的落点通道
 *
 * ## 为什么不复用 `bus.ts`
 * `bus.ts` 里那三个事件（涨停 / 跌停 / 搜索）都是**无参数**的，落点唯一，
 * 所以一个固定事件名就够了。这里要带一个区块 id，且「谁来响应」由渲染情况决定 ——
 * 语义不同，硬塞进 `BUS` 会逼着调用方去拼动态事件名，那正是 `bus.ts` 明确禁止的。
 *
 * ## 为什么是「事件 + 待认领请求」，而不是把 block 逐层透传成 props
 * 目标区块**什么时候才会渲染出来，调用方说了不算**，有三个真实约束：
 *   1. 目标面板多为 `lazyRetry` + Suspense：事件先发出，组件后挂载；
 *   2. 未激活的子页是 `display:none`（四个 Panel 都是隐藏而非卸载），
 *      此时 `scrollIntoView` 会滚到错误位置，必须等它真正可见；
 *   3. 折叠面板的内容在数据到达前根本不渲染（`{data && <CollapsiblePanel/>}`），
 *      而决策先锋首次生成要 1~2 分钟。
 * 于是：调用方只发一个**带有效期的请求**，谁最终渲染出来谁认领 ——
 * 无论它是同步挂载的、懒加载的，还是等数据才出现的。
 *
 * ## 认领只发生一次
 * 否则「切走再切回」会被莫名其妙地重复滚动一次。认领即消费。
 */
const EVENT = "ai:focus-block";

/**
 * 请求的有效期。
 *
 * 定得比「决策先锋首屏 1~2 分钟」更长：请求必须在数据到达后依然有效，
 * 否则「点了『潜力龙头』，等两分钟数据出来」这条路径会静默失效 ——
 * 而那恰好是最需要它的一条。超过两分钟视为用户早已自己滚过去看了。
 */
const TTL_MS = 150_000;

let pending: { id: string; at: number } | null = null;

/** 请求把某个区块展开并滚到眼前。区块还没渲染出来也有效（等它出现时认领）。 */
export function requestBlockFocus(id: string): void {
  if (typeof window === "undefined") return;
  pending = { id, at: Date.now() };
  window.dispatchEvent(new CustomEvent<string>(EVENT, { detail: id }));
}

/** 认领请求：只认一次，且只在有效期内。 */
function claim(id: string): boolean {
  if (!pending || pending.id !== id) return false;
  if (Date.now() - pending.at > TTL_MS) {
    pending = null;
    return false;
  }
  pending = null;
  return true;
}

/**
 * 订阅聚焦请求，并补领「挂载之前就已经发出」的那一次。
 *
 * 补领这一步是懒加载与「等数据才渲染」两条路径的唯一支撑：
 * 订阅只能收到订阅**之后**的事件，而这两种情况下事件总是先到。
 */
export function useBlockFocus(id: string, apply: (id: string) => void): void {
  const ref = useRef(apply);
  useEffect(() => {
    ref.current = apply;
  });

  useEffect(() => {
    const handler = (e: Event) => {
      const target = (e as CustomEvent<string>).detail;
      if (target === id) ref.current(id);
    };
    window.addEventListener(EVENT, handler);
    if (claim(id)) ref.current(id);
    return () => window.removeEventListener(EVENT, handler);
  }, [id]);
}
