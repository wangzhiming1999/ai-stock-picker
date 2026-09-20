import { useCallback } from "react";
import { toast } from "sonner";
import { importToWatchlist } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { requestAuth } from "../components/WatchStar";

/**
 * 批量加入自选 · 一处实现
 *
 * 原逻辑内联在 `ScanPanel` 里，形态视图通过 props 传下去。形态提成独立子页之后，
 * 这份逻辑需要被两个页面共用 —— 与其复制一份（然后其中一份忘了处理未登录），
 * 不如抽出来。
 *
 * 未登录时不静默失败，而是**弹登录**：用户点了「加入自选」却什么都没发生，
 * 是最容易让人以为"这功能坏了"的场景。
 */
export function useImportToWatchlist() {
  const { user } = useAuth();

  return useCallback(
    async (codes: string[]) => {
      if (!user) {
        requestAuth();
        return;
      }
      if (!codes.length) return;
      try {
        const r = await importToWatchlist(codes);
        toast.success(`已加入自选 ${r.added} 只${r.skipped ? `，跳过 ${r.skipped} 只` : ""}`);
      } catch (e) {
        toast.error("加入自选失败", { description: (e as Error).message });
      }
    },
    [user],
  );
}
