import { useEffect, useRef } from "react";

/**
 * 跨组件事件原语
 *
 * ## 为什么是 window 事件，而不是 Context / 状态提升
 * 有些功能的「落点」不在当前页面的组件树里：
 *   - 涨停 / 跌停两根常驻条挂在 `<main>` **外面**（`App.tsx` 顶层），
 *     任何页面想「把涨停条展开」都跨了子树；
 *   - 顶部搜索框同理。
 * 为这三件事把状态提升到 `App` 再透传五六层，换来的是一堆与业务无关的 props。
 * 事件是这类「无归属的全局副作用」最轻的载体 —— 而且项目里已有先例
 * （`stock:require-auth` 由 `WatchStar` 发出、`App` 监听）。
 *
 * ## 纪律
 * 事件名一律 `ai:` 前缀，且**只在这里登记**。新增一个跨树事件就在这里加一条，
 * 不要在组件里手写字符串 —— 那样拼错了不会有任何提示，只是「点了没反应」。
 * `featureMap.test.ts` 会核对功能地图里每个 anchor 都能在这里找到落点。
 */
export const BUS = {
  /** 展开顶部涨停梯队条（含次日溢价读数） */
  limitup: "ai:open-limitup",
  /** 展开顶部跌停观察条 */
  limitdown: "ai:open-limitdown",
  /** 聚焦顶部全局搜索框（深度分析的入口） */
  search: "ai:focus-search",
} as const;

export type BusEvent = keyof typeof BUS;

export function emitBus(event: BusEvent): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(BUS[event]));
}

/**
 * 订阅一个跨树事件。handler 存在 ref 里，所以调用点不必为「函数每次渲染都变」
 * 去包 useCallback —— 订阅只建立一次。
 */
export function useBus(event: BusEvent, handler: () => void): void {
  const ref = useRef(handler);
  useEffect(() => {
    ref.current = handler;
  }, [handler]);
  useEffect(() => {
    const fn = () => ref.current();
    window.addEventListener(BUS[event], fn);
    return () => window.removeEventListener(BUS[event], fn);
  }, [event]);
}
