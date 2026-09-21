/**
 * 本地预览服务 · 静态 dist + /api 反代线上后端
 *
 * ## 为什么不用 `vite preview`
 * `vite preview` 会把 `/api` 打向本机 8000（vite.config.ts 的 dev proxy），
 * 而本机没有后端 —— 结果整页数据全空，看不出任何东西。
 *
 * ## 为什么不起本地后端
 * 后端首次请求会真拉全市场约 5500 只快照（`force=true` 那条路径），
 * 那是**线上行情源风控的主要触发原因**（东财 push2 是 IP 级封禁）。
 * 为了看一个样式去制造一次封禁风险，不值得。所以这里只反代线上已部署的后端，
 * 它自己有三层缓存与跨实例冷却。
 *
 * ## 用法（在 frontend/ 下）
 *   node tools/preview-proxy.mjs
 * 然后访问 http://127.0.0.1:4173
 *
 * ⚠️ 不要在起服务时接 `| head` —— 反代不返回 content-length，
 *    head 提前关闭管道会给进程发 SIGPIPE 把它杀掉。
 */
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { join, extname, normalize, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PORT = 4173;
/**
 * ⚠️ Windows 上不要写 `new URL("../dist/", import.meta.url).pathname` ——
 * 那会给出 `/D:/...` 这种带前导斜杠的路径，`join()` 之后读不到文件，
 * 静态服务全部回落成 404（而且不报错，只是白屏）。用 fileURLToPath。
 */
const DIST = resolve(dirname(fileURLToPath(import.meta.url)), "../dist");
const BACKEND = "https://backend-smoky-kappa-70.vercel.app";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
};

/** 把请求转给线上后端，原样回传状态码与响应体。 */
async function proxy(req, res) {
  const target = BACKEND + req.url;
  try {
    const upstream = await fetch(target, {
      method: req.method,
      headers: { "content-type": req.headers["content-type"] ?? "application/json" },
      body: req.method === "GET" || req.method === "HEAD" ? undefined : req,
      duplex: "half",
    });
    res.writeHead(upstream.status, { "content-type": upstream.headers.get("content-type") ?? "application/json" });
    res.end(Buffer.from(await upstream.arrayBuffer()));
  } catch (err) {
    res.writeHead(502, { "content-type": "application/json" });
    res.end(JSON.stringify({ detail: `预览反代失败：${err.message}` }));
  }
}

/** 静态文件；未命中的路径回落到 index.html（SPA 路由）。 */
async function serveStatic(req, res) {
  const urlPath = decodeURIComponent(new URL(req.url, "http://x").pathname);
  // 防目录穿越：normalize 后必须仍在 dist 内
  const rel = normalize(urlPath).replace(/^(\.\.[/\\])+/, "");
  let file = join(DIST, rel);
  try {
    const st = await stat(file);
    if (st.isDirectory()) file = join(file, "index.html");
  } catch {
    file = join(DIST, "index.html");
  }
  try {
    const body = await readFile(file);
    res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    res.end("404");
  }
}

createServer((req, res) => {
  if (req.url?.startsWith("/api")) return void proxy(req, res);
  return void serveStatic(req, res);
}).listen(PORT, "127.0.0.1", () => {
  console.log(`预览已就绪  http://127.0.0.1:${PORT}`);
  console.log(`静态目录    ${DIST}`);
  console.log(`/api 反代   ${BACKEND}`);
});