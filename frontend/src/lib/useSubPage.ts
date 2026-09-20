import { useCallback, useEffect, useState } from "react";
import type { NavJump } from "./featureMap";
import type { Tab } from "./nav";
import { SUB_NAV } from "./subnav";

/**
 * 二级子页状态机 · 一处实现，四个页面共用
 *
 * 三个 Panel（选机会 / 持仓 / 研究）此前各自复制了一份同样的逻辑：
 * 「当前子页 + 已挂载子页集合 + 跟随外部跳转」，连注释都几乎一样。
 * 抽出来的直接好处不是少写几行，而是**行为一致** ——
 * 尤其"跳转 id 必须自增"这条，复制三份就会有一份漏掉。
 *
 * ## 两条不能坏的语义
 * 1. **子页一旦访问就常驻 DOM（隐藏而非卸载）**。切走再切回来不该重新拉一遍数据 ——
 *    行情类接口有 IP 级限流，重复拉取是真实风险，不是性能偏好。
 * 2. **依赖 `jump.id` 而不是 `jump` 对象**。用户可能先手动切走再点回同一个功能，
 *    只比 `sub` 值的话第二次不会有任何变化 —— 这与 `AnalysisDrawer` 的 requestId 同一个坑。
 *
 * @param tab        当前一级页
 * @param jump       外部跳转请求（来自功能地图）
 * @param fallbackKey 首次进入落在哪个子页；不传则用第一个
 */
export function useSubPage(tab: Tab, jump?: NavJump | null, fallbackKey?: string) {
  const subs = SUB_NAV[tab];
  const keys = subs.map((s) => s.key as string);
  const first = fallbackKey && keys.includes(fallbackKey) ? fallbackKey : keys[0];

  /** 只接受"属于本页"的跳转，防止把别的页的子页塞进来（那种情况会渲染出一片空白） */
  const pick = (j?: NavJump | null): string | null =>
    j && j.tab === tab && j.sub && keys.includes(j.sub) ? j.sub : null;

  const [sub, setSub] = useState<string>(() => pick(jump) ?? first);
  const [mounted, setMounted] = useState<Set<string>>(() => new Set<string>([pick(jump) ?? first]));

  const changeSub = useCallback((k: string) => {
    setSub(k);
    setMounted((prev) => {
      if (prev.has(k)) return prev;
      const next = new Set(prev);
      next.add(k);
      return next;
    });
  }, []);

  useEffect(() => {
    const target = pick(jump);
    if (target) changeSub(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jump?.id, jump?.sub]);

  return {
    /** 当前子页 key */
    sub,
    changeSub,
    /** 传给子页容器的可见性 class */
    isVisible: (k: string) => (sub === k ? "" : "hidden"),
    /** 该子页是否已经挂载过 */
    isMounted: (k: string) => mounted.has(k),
  };
}
