import { lazy } from "react";
import type { ComponentType } from "react";

/**
 * 判断是不是「部署后旧 chunk 失效」这类可自愈的加载失败。
 *
 * 场景：浏览器标签页是部署**前**加载的，SPA 不会重新拉 index.html；
 * 用户此时才点开某个懒加载面板，它拿内存里的旧入口去请求旧 hash 的
 * chunk —— 那个文件在新部署里已经不存在，于是抛
 * `TypeError: Failed to fetch dynamically imported module`。
 * 结果就是「主包能用、懒加载面板全灭」，错误边界兜住一张死屏。
 */
function isChunkLoadError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /failed to fetch dynamically imported module|loading (css )?chunk|error loading dynamically imported module/i.test(
    msg
  );
}

/** 30 秒内最多自愈刷新一次，避免服务端真有问题时陷入刷新死循环。 */
const RELOAD_KEY = "chunk-reload-at";
const RELOAD_COOLDOWN_MS = 30_000;

/**
 * 带自愈的 lazy：chunk 加载失败时整页刷新一次，让浏览器拿到新 index.html
 * 和新 hash 的入口，问题就此消失，用户不需要看到「重试」按钮。
 *
 * 非 chunk 类错误（真正的代码异常）原样抛出，交给错误边界。
 *
 * 用 `lazyRetry(() => import("./X"))` 代替 `lazy(() => import("./X"))`。
 */
export function lazyRetry(
  factory: () => Promise<{ default: ComponentType<any> }>
) {
  return lazy(() =>
    factory().catch((err: unknown) => {
      if (!isChunkLoadError(err)) throw err;
      const last = Number(sessionStorage.getItem(RELOAD_KEY) ?? 0);
      if (Date.now() - last > RELOAD_COOLDOWN_MS) {
        sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
        window.location.reload();
      }
      throw err;
    })
  );
}
