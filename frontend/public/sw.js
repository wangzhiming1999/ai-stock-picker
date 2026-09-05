/**
 * AI 选股分析工具 · Service Worker
 *
 * 策略：
 * - install: 预缓存 app shell（离线可打开首页骨架）
 * - fetch:
 *   - 同源静态资源（/assets/*，文件名带 hash）→ cache-first（immutable，命中即用）
 *   - /api/* → 网络优先，失败回退缓存（行情/分析数据允许降级展示）
 *   - 导航请求 → 网络优先，失败回退缓存的 index.html（离线兜底）
 *   - 其余（icons/manifest/og 等）→ stale-while-revalidate
 * - activate: 清理旧版本缓存
 */
const VERSION = "v1";
const SHELL_CACHE = `shell-${VERSION}`;
const ASSET_CACHE = `assets-${VERSION}`;
const RUNTIME_CACHE = `runtime-${VERSION}`;
const API_CACHE = `api-${VERSION}`;

const SHELL_ASSETS = ["/", "/index.html", "/manifest.webmanifest", "/favicon.ico"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => ![SHELL_CACHE, ASSET_CACHE, RUNTIME_CACHE, API_CACHE].includes(k))
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // 跨域（后端 API 直连）不拦截

  // 带 hash 的构建产物：cache-first
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((resp) => {
            if (resp.ok) {
              const clone = resp.clone();
              caches.open(ASSET_CACHE).then((c) => c.put(request, clone));
            }
            return resp;
          })
      )
    );
    return;
  }

  // API：网络优先，失败回退缓存（允许离线降级展示）
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(API_CACHE).then((c) => c.put(request, clone));
          }
          return resp;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // 导航：网络优先，离线回退 index.html
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(SHELL_CACHE).then((c) => c.put("/index.html", clone));
          }
          return resp;
        })
        .catch(async () => (await caches.match("/index.html")) || Response.error())
    );
    return;
  }

  // 其余同源资源（icons/og/manifest）：stale-while-revalidate
  event.respondWith(
    caches.match(request).then((hit) => {
      const network = fetch(request)
        .then((resp) => {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(RUNTIME_CACHE).then((c) => c.put(request, clone));
          }
          return resp;
        })
        .catch(() => hit);
      return hit || network;
    })
  );
});
