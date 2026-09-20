import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import type { MonitorStock } from "../../types";
import type { MonitorAlertItem } from "./constants";
import { ALERT_DEDUPE_MS, ALERT_TOAST_MS, MAX_ALERTS, TRIGGER_ACTIONS } from "./constants";

/**
 * 盯盘提醒的提示音 + 调度逻辑（独立 hook）。
 *
 * 关键契约：
 *  - 去重 `lastHintRef` 是 `code:action → 时间戳` 的 **map**，不是「只存最后一条」。
 *    早先只存最后一条，A→B→A 交替触发时去重失效会重复响铃。
 *  - 同票同指令窗口 3 分钟（ALERT_DEDUPE_MS），页内留痕上限 30 条（MAX_ALERTS）。
 *  - 后台（页面隐藏）toast 用 Infinity 常驻到切回；前台给足 30 秒（ALERT_TOAST_MS）。
 */
export function useMonitorAlerts(notifyOn: boolean) {
  const [alerts, setAlerts] = useState<MonitorAlertItem[]>([]);
  const prevActionRef = useRef<Record<string, string>>({});
  const notifyRef = useRef<boolean>(notifyOn);
  const audioCtxRef = useRef<AudioContext | null>(null);
  /**
   * `code:action` → 上次提醒时间戳。
   * 必须是 map：早先只存「最后一条」，A→B→A 交替触发时去重直接失效，会重复响铃。
   */
  const lastHintRef = useRef<Record<string, number>>({});

  // notifyOn 切换后，下一轮提醒即按新值判断（页面后台才弹系统通知）
  useEffect(() => {
    notifyRef.current = notifyOn;
  }, [notifyOn]);

  /** 提示音：双声"叮" */
  const beep = useCallback(() => {
    try {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return;
      if (!audioCtxRef.current) audioCtxRef.current = new Ctor();
      const ctx = audioCtxRef.current;
      if (ctx.state === "suspended") void ctx.resume();
      const t0 = ctx.currentTime;
      [880, 1174].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = freq;
        const start = t0 + i * 0.18;
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.2, start + 0.03);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.25);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(start);
        osc.stop(start + 0.28);
      });
    } catch {
      /* 无 AudioContext 时静默 */
    }
  }, []);

  const fireAlert = useCallback(
    (it: MonitorStock) => {
      const key = `${it.code}:${it.advice.action}`;
      // 同票同指令窗口内不重复提醒（防止行情在阈值附近抖动时反复响铃）
      const now = Date.now();
      if (now - (lastHintRef.current[key] ?? 0) < ALERT_DEDUPE_MS) return;
      // 顺手回收过期项，避免长期盯盘时 key 无界累积
      for (const k of Object.keys(lastHintRef.current)) {
        if (now - lastHintRef.current[k] >= ALERT_DEDUPE_MS) delete lastHintRef.current[k];
      }
      lastHintRef.current[key] = now;

      beep();
      const title = `${it.name} · ${it.advice.label}`;
      const body = it.advice.do ? `${it.advice.do}（${it.code}）` : `${it.advice.hint}（${it.code}）`;

      // 页内留痕：toast 是限时消失的，这份记录才是能回头查的那一份
      const at = new Date(now).toISOString();
      setAlerts((prev) =>
        [
          { id: `${now}-${it.code}`, code: it.code, name: it.name, label: it.advice.label, body, tone: it.advice.tone, at },
          ...prev,
        ].slice(0, MAX_ALERTS)
      );

      const inBackground = typeof document !== "undefined" && document.hidden;
      const canNotify =
        notifyRef.current &&
        "Notification" in window &&
        window.Notification.permission === "granted";
      if (canNotify && inBackground) {
        try {
          new window.Notification(title, { body });
          return;
        } catch {
          /* fallthrough to toast */
        }
      }
      toast.warning(title, {
        description: body,
        // 后台时用户根本看不到，常驻到切回来为止；前台给足 30 秒读完指令与价位
        duration: inBackground ? Infinity : ALERT_TOAST_MS,
        closeButton: true,
      });
    },
    [beep]
  );

  /** 对比上一轮指令，触发类变化才提醒 */
  const checkAlerts = useCallback(
    (items: MonitorStock[]) => {
      const nowMap: Record<string, string> = {};
      for (const it of items) {
        nowMap[it.code] = it.advice.action;
        const prev = prevActionRef.current[it.code];
        if (prev && prev !== it.advice.action && TRIGGER_ACTIONS.has(it.advice.action)) {
          fireAlert(it);
        }
      }
      // 清理已不在名单中的记录，避免累积
      for (const c of Object.keys(prevActionRef.current)) {
        if (!nowMap[c]) delete prevActionRef.current[c];
      }
      prevActionRef.current = nowMap;
    },
    [fireAlert]
  );

  /** 预热音频上下文，保证后续轮询提示音可播放（需在用户手势内调用） */
  const primeAudio = useCallback(() => {
    try {
      if (!audioCtxRef.current) audioCtxRef.current = new AudioContext();
      void audioCtxRef.current.resume();
    } catch {
      /* ignore */
    }
  }, []);

  const clearAlerts = useCallback(() => setAlerts([]), []);

  return { alerts, fireAlert, checkAlerts, primeAudio, clearAlerts };
}
