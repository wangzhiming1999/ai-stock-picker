import { useCallback, useState } from "react";

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
      try {
        localStorage.setItem(storageKey, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, [storageKey]);

  return { open, toggle };
}
