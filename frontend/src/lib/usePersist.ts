import { useCallback, useState } from "react";

function persist(storageKey: string, open: boolean): void {
  try {
    localStorage.setItem(storageKey, open ? "1" : "0");
  } catch {
    /* ignore */
  }
}

/** 折叠状态（localStorage 记忆） */
export function useCollapse(key: string, defaultOpen = true) {
  const storageKey = `ai:collapse:${key}`;
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(storageKey);
      return v === null ? defaultOpen : v === "1";
    } catch {
      return defaultOpen;
    }
  });

  const toggle = useCallback(() => {
    setOpen((o) => {
      const next = !o;
      persist(storageKey, next);
      return next;
    });
  }, [storageKey]);

  /**
   * 直接展开 / 收起（不是切换）。
   *
   * 给「功能地图跳到某一区块」用：用户点的是一条明确的落点，展开动作必须幂等 ——
   * 若用 `toggle`，目标面板恰好是展开状态时会被反过来收起。
   * 写入 localStorage 与手动点击一致，所以「跳过去看过」和「自己点开」是同一份记忆。
   */
  const setValue = useCallback(
    (next: boolean) => {
      setOpen(next);
      persist(storageKey, next);
    },
    [storageKey],
  );

  return { open, toggle, setOpen: setValue };
}
