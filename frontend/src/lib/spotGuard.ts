/**
 * 「强制刷新」统一闸门。
 *
 * 为什么需要：`force=true` 会让后端跳过内存快照与 Supabase 持久化快照**两层缓存**，
 * 直接打东财 push2（约 60 页分页，单次约 70s）。这是全站唯一能触发 **IP 级封禁**的动作：
 * 一旦被风控，东财所有域名集体断连、新浪返回 HTML 风控页，全站行情接口 502 数分钟。
 *
 * 所以前端不能把 `force` 当成「拿新数据」的默认手段（这正是 2026-09-15 那次 502 的前端侧根因），
 * 而必须做到两件事：
 * 1. **二次确认** —— 让用户知道这次点击的代价；
 * 2. **冷却拦截 + 倒计时** —— 风控期内禁止再次触发，因为连点会不断后延封禁窗口。
 *
 * 冷却状态来自后端 `/api/market/spot-status`，是**跨实例共享**的全局状态；
 * 本地只负责倒计时展示与请求去重，不自行判断风控是否结束。
 */
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { fetchSpotStatus } from "../api/client";

/** 状态接口的本地缓存时长：多个面板同时挂载时共用一次请求 */
const STATUS_TTL_MS = 15_000;

let lastCheckedAt = 0;
let lastServerSeconds = 0;

/** 本地倒计时终点（毫秒时间戳）。仅用于展示，服务端始终是权威来源。 */
let cooldownUntil = 0;

/** 二次确认文案：把代价说清楚，而不是问一句「确定吗」。 */
export const FORCE_REFRESH_HINT =
  "强制刷新会跳过两层行情缓存，直接向行情源重新拉取全市场数据（约需 1 分钟）。\n\n" +
  "短时间内反复触发会引来 IP 级风控，导致全站行情接口在数分钟内不可用。\n\n" +
  "确认现在刷新吗？";

/** 重跑 LLM 类任务（大盘推衍等）的确认文案：代价是时间与额度，不是风控。 */
export const FORCE_ANALYSIS_HINT =
  "强制刷新会跳过当日缓存，重新调用模型跑一次分析（通常需要 30 秒以上）。\n\n" +
  "确认现在重跑吗？";

/** 记录一次冷却（秒）。传 0 或负数忽略。 */
export function markCooldown(seconds: number): void {
  if (seconds > 0) cooldownUntil = Date.now() + seconds * 1000;
}

/** 本地剩余冷却秒数（0 = 不在冷却中）。 */
export function localCooldownSeconds(): number {
  return Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
}

/**
 * 查询行情源剩余冷却秒数。
 *
 * 网络异常时返回 0（放行）：状态接口自己挂了不该把用户的操作能力一起锁死，
 * 真正的兜底在后端 `_get_spot` 的冷却判断与 `_SPOT_FORCE_MIN_INTERVAL` 节流上。
 */
export async function cooldownSeconds(force = false): Promise<number> {
  if (!force && Date.now() - lastCheckedAt < STATUS_TTL_MS) return lastServerSeconds;
  try {
    const status = await fetchSpotStatus();
    lastCheckedAt = Date.now();
    lastServerSeconds = status.cooldown_seconds ?? 0;
    markCooldown(lastServerSeconds);
    return lastServerSeconds;
  } catch {
    return 0;
  }
}

/**
 * 冷却闸门：只在风控期内拦截，不做二次确认。
 *
 * 用于「立即刷新」这类高频核心动作 —— 它们本来就该被允许频繁触发，
 * 但风控期内必须拦住（那时打行情源只会失败，还会延长封禁）。
 *
 * @returns true 表示不在冷却期、可以继续。
 */
export async function ensureNotCooling(): Promise<boolean> {
  const local = localCooldownSeconds();
  if (local > 0) {
    toast.warning("行情源冷却中", { description: `还需等待 ${local} 秒；连点会延长封禁时间` });
    return false;
  }

  const server = await cooldownSeconds(true);
  if (server > 0) {
    toast.warning("行情源冷却中", { description: `还需等待 ${server} 秒；连点会延长封禁时间` });
    return false;
  }
  return true;
}

/**
 * 强制刷新的统一入口：冷却中直接拦下并给出倒计时，否则弹二次确认。
 *
 * @param hint 二次确认文案；默认按「跳过行情缓存」口径，重跑 LLM 的场景传 `FORCE_ANALYSIS_HINT`。
 * @returns true 才允许调用方带 `force=true` 发请求。
 */
export async function confirmForceRefresh(hint: string = FORCE_REFRESH_HINT): Promise<boolean> {
  if (!(await ensureNotCooling())) return false;
  if (!window.confirm(hint)) return false;

  // 用户已确认 → 先本地按下 60s 节流（与后端 _SPOT_FORCE_MIN_INTERVAL 对齐），
  // 避免确认后连点绕过二次确认直接打行情源。
  markCooldown(60);
  return true;
}

/** 订阅行情源冷却倒计时，供按钮展示「冷却 Ns」并禁用。 */
export function useSpotCooldown(): { seconds: number; recheck: () => void } {
  const [seconds, setSeconds] = useState(() => localCooldownSeconds());

  useEffect(() => {
    const sync = () => setSeconds(localCooldownSeconds());
    sync();
    const timer = window.setInterval(sync, 1000);
    return () => window.clearInterval(timer);
  }, []);

  // 挂载时对齐一次服务端状态：风控是全局的，别的用户触发时本机也要拦。
  // 走 TTL 去重，多个面板同时挂载只会产生一次请求。
  const recheck = useCallback(() => {
    void cooldownSeconds().then(() => setSeconds(localCooldownSeconds()));
  }, []);

  useEffect(() => {
    recheck();
  }, [recheck]);

  return { seconds, recheck };
}
