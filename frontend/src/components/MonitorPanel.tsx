import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bell, BellPlus, BellRing, Download, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { addAlertRule, fetchHoldings, fetchMonitor, fetchWatchlist } from "../api/client";
import CollapsiblePanel from "./CollapsiblePanel";
import { useAuth } from "../auth/AuthContext";
import type { MonitorInterval, MonitorResult, MonitorStock } from "../types";
import { actionTone, pnlTone } from "../lib/tone";

const LS_KEY = "ai:monitorCodes";
const LS_NOTIFY = "ai:monitorNotify";
const LS_INTERVAL = "ai:monitorInterval";
const DEFAULT_POLL_MS = 5 * 60 * 1000;
const MAX_CODES = 20;

/** 周期档位：日线定方向，分钟线定这一笔 */
const INTERVALS: { value: MonitorInterval; label: string; hint: string }[] = [
  { value: "1d", label: "日线", hint: "波段：日 K 支撑压力，止损较宽（3% 左右），持仓数天到数周" },
  { value: "15m", label: "15 分", hint: "日内：VWAP + 15 分钟均线，止损 0.5%~1.1%，当日了结" },
  { value: "5m", label: "5 分", hint: "日内：最灵敏，止损 0.3%~0.8%，噪音也最多，适合盯盘时做 T" },
];

function loadInterval(): MonitorInterval {
  try {
    const v = localStorage.getItem(LS_INTERVAL);
    if (v === "1d" || v === "5m" || v === "15m" || v === "30m" || v === "60m") return v;
  } catch {
    /* ignore */
  }
  return "1d";
}

/** 触发类指令：动作从其他状态切换进来时提醒 */
const TRIGGER_ACTIONS = new Set(["buy", "sell", "stop"]);

function loadSaved(): string[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr)
      ? arr.filter((x) => typeof x === "string" && /^\d{6}$/.test(x)).slice(0, MAX_CODES)
      : [];
  } catch {
    return [];
  }
}

function loadNotify(): boolean {
  try {
    return localStorage.getItem(LS_NOTIFY) === "1";
  } catch {
    return false;
  }
}

/** 指令色调 */
const toneClass: Record<string, string> = {
  danger: "border-red-800/70 bg-red-950/50 text-red-300",
  warn: "border-amber-800/60 bg-amber-950/40 text-amber-300",
  good: "border-green-800/60 bg-green-950/40 text-green-300",
  neutral: "border-slate-700 bg-slate-800/60 text-slate-300",
  info: "border-sky-800/60 bg-sky-950/40 text-sky-300",
};

const toneDot: Record<string, string> = {
  danger: "bg-red-400",
  warn: "bg-amber-400",
  good: "bg-green-400",
  neutral: "bg-slate-500",
  info: "bg-sky-400",
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function num(v: number | undefined | null, digits = 2): string {
  return v == null || Number.isNaN(v) ? "-" : v.toFixed(digits);
}

export default function MonitorPanel() {
  const { user } = useAuth();
  const [codes, setCodes] = useState<string[]>(loadSaved);
  const [input, setInput] = useState("");
  const [data, setData] = useState<MonitorResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [notifyOn, setNotifyOn] = useState<boolean>(loadNotify);
  const [onlyAction, setOnlyAction] = useState(false);
  const [alertBusy, setAlertBusy] = useState<string | null>(null);
  const [costs, setCosts] = useState<Record<string, number>>({});
  const [interval, setInterval] = useState<MonitorInterval>(loadInterval);
  const busyRef = useRef(false);
  const prevActionRef = useRef<Record<string, string>>({});
  const notifyRef = useRef<boolean>(notifyOn);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const lastHintRef = useRef<{ code: string; at: number; label: string } | null>(null);
  const costsRef = useRef<Record<string, number>>({});
  const intervalRef = useRef<MonitorInterval>(interval);

  costsRef.current = costs;
  intervalRef.current = interval;

  const persist = (arr: string[]) => {
    setCodes(arr);
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(arr));
    } catch {
      /* ignore */
    }
  };

  /** 登录后拉取持仓成本，让指令带上盈亏视角 */
  useEffect(() => {
    if (!user) {
      setCosts({});
      return;
    }
    let alive = true;
    void (async () => {
      try {
        const d = await fetchHoldings();
        if (!alive) return;
        const map: Record<string, number> = {};
        for (const h of d.holdings ?? []) {
          if (h?.code && h.cost_price > 0) map[h.code] = h.cost_price;
        }
        setCosts(map);
      } catch {
        /* 未登录或后端不可用：按无成本处理 */
      }
    })();
    return () => {
      alive = false;
    };
  }, [user?.id]);

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
      // 同票同指令 3 分钟内不重复提醒（防止连续轮询反复响）
      const now = Date.now();
      const prev = lastHintRef.current;
      if (prev && prev.code === key && now - prev.at < 3 * 60 * 1000) return;
      lastHintRef.current = { code: key, at: now, label: it.advice.label };

      beep();
      const title = `${it.name} · ${it.advice.label}`;
      const body = it.advice.do ? `${it.advice.do}（${it.code}）` : `${it.advice.hint}（${it.code}）`;
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
      toast.warning(title, { description: body });
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

  const refresh = useCallback(
    /** silent: 静默（轮询）不显示 loading；force: 忽略后端 K 线缓存重新拉取 */
    async (silent = false, force = false) => {
      if (codes.length === 0) return;
      if (busyRef.current) return;
      busyRef.current = true;
      if (!silent) setLoading(true);
      setErr("");
      try {
        const result = await fetchMonitor(codes, force, costsRef.current, intervalRef.current);
        setData(result);
        checkAlerts(result.items);
      } catch (e) {
        const message = (e as Error).message;
        setErr(silent ? `自动刷新失败，正在显示上次行情：${message}` : message);
      } finally {
        busyRef.current = false;
        setLoading(false);
      }
    },
    [codes, checkAlerts]
  );

  /** 开启/关闭桌面通知 */
  const toggleNotify = async () => {
    if (!("Notification" in window)) {
      toast.error("当前浏览器不支持系统通知，仅保留提示音与页面提醒");
      return;
    }
    if (notifyOn) {
      notifyRef.current = false;
      setNotifyOn(false);
      try {
        localStorage.setItem(LS_NOTIFY, "0");
      } catch {
        /* ignore */
      }
      return;
    }
    const perm = await window.Notification.requestPermission();
    const on = perm === "granted";
    notifyRef.current = on;
    setNotifyOn(on);
    try {
      localStorage.setItem(LS_NOTIFY, on ? "1" : "0");
    } catch {
      /* ignore */
    }
    if (on) {
      // 用户手势内预热音频上下文，保证后续轮询提示音可播放
      try {
        if (!audioCtxRef.current) audioCtxRef.current = new AudioContext();
        void audioCtxRef.current.resume();
      } catch {
        /* ignore */
      }
      toast.success("桌面提醒已开启：指令变化时响铃+通知");
    } else {
      toast.warning("未获得通知权限，仍会保留页面内提示音提醒");
    }
  };

  const codesKey = codes.join(",");
  const costsKey = Object.entries(costs)
    .map(([k, v]) => `${k}:${v}`)
    .join(",");

  // 名单 / 成本 / 周期变化 → 立即刷新
  useEffect(() => {
    if (codes.length === 0) {
      setData(null);
      prevActionRef.current = {};
      return;
    }
    // 换周期会让所有指令重算，先清掉基线，避免把周期切换误报成「指令变化」
    prevActionRef.current = {};
    void refresh(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codesKey, costsKey, interval]);

  // 交易时段按后端建议频率刷新；休市时降为 5 分钟。每次收到结果后重排定时器。
  useEffect(() => {
    if (codes.length === 0) return;
    const delay = Math.max(15_000, (data?.poll_interval_seconds ?? 300) * 1000);
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh(true);
    }, delay || DEFAULT_POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") void refresh(true);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codesKey, data?.updated_at, data?.poll_interval_seconds, refresh]);

  const addCodes = () => {
    const parsed = input.match(/\d{6}/g) ?? [];
    const uniq = parsed.filter((c) => !codes.includes(c));
    if (!uniq.length) {
      setErr("未识别到 6 位股票代码");
      return;
    }
    if (codes.length + uniq.length > MAX_CODES) {
      setErr(`最多同时监控 ${MAX_CODES} 只`);
      return;
    }
    persist([...codes, ...uniq].slice(0, MAX_CODES));
    setInput("");
    setErr("");
  };

  const mergeCodes = (incoming: string[], nextCosts?: Record<string, number>) => {
    if (nextCosts) {
      setCosts((prev) => ({ ...prev, ...nextCosts }));
    }
    const merged = [...codes, ...incoming.filter((c) => !codes.includes(c))].slice(0, MAX_CODES);
    persist(merged);
    setErr("");
  };

  const importWatchlist = async () => {
    if (!user) {
      toast.error("登录后才能导入自选股");
      return;
    }
    try {
      const d = await fetchWatchlist();
      const list = (d.watchlist ?? []).map((w) => w.code).filter((c) => /^\d{6}$/.test(c));
      if (!list.length) {
        toast.warning("自选股还是空的");
        return;
      }
      mergeCodes(list);
      toast.success(`已导入 ${list.length} 只自选股`);
    } catch (e) {
      toast.error(`导入自选失败：${(e as Error).message}`);
    }
  };

  const importHoldings = async () => {
    if (!user) {
      toast.error("登录后才能导入持仓");
      return;
    }
    try {
      const d = await fetchHoldings();
      const list = (d.holdings ?? []).filter((h) => /^\d{6}$/.test(h.code));
      if (!list.length) {
        toast.warning("还没有持仓");
        return;
      }
      const map: Record<string, number> = {};
      list.forEach((h) => {
        if (h.cost_price > 0) map[h.code] = h.cost_price;
      });
      mergeCodes(
        list.map((h) => h.code),
        map
      );
      toast.success(`已导入 ${list.length} 只持仓（带成本，指令含盈亏视角）`);
    } catch (e) {
      toast.error(`导入持仓失败：${(e as Error).message}`);
    }
  };

  /** 一键按建议价建到价提醒 */
  const quickAlert = async (it: MonitorStock) => {
    if (!user) {
      toast.error("登录后才能设置到价提醒");
      return;
    }
    const plan = it.advice?.plan;
    if (!plan) return;
    const pick =
      it.advice.action === "buy"
        ? { type: "buy_point" as const, threshold: plan.buy, text: `跌到 ${num(plan.buy)} 提醒买入` }
        : it.advice.action === "stop"
          ? { type: "stop_loss" as const, threshold: plan.stop, text: `跌到 ${num(plan.stop)} 提醒止损` }
          : { type: "sell_point" as const, threshold: plan.sell, text: `涨到 ${num(plan.sell)} 提醒卖出/减仓` };
    setAlertBusy(it.code);
    try {
      await addAlertRule({ code: it.code, type: pick.type, threshold: pick.threshold, name: it.name, note: "auto:monitor" });
      toast.success(`${it.name} 已设提醒：${pick.text}`);
    } catch (e) {
      toast.error(`设置失败：${(e as Error).message}`);
    } finally {
      setAlertBusy(null);
    }
  };

  const remove = (code: string) => {
    persist(codes.filter((c) => c !== code));
    if (codes.length === 1) setData(null);
  };

  const byCode = useMemo(() => {
    const m = new Map<string, MonitorStock>();
    (data?.items ?? []).forEach((it) => m.set(it.code, it));
    return m;
  }, [data]);

  // 后端已按「需要操作的优先」排序；此处按同一顺序展示，可选只看需要操作的
  const visibleCodes = useMemo(() => {
    if (!onlyAction) return codes;
    return codes.filter((c) => {
      const it = byCode.get(c);
      return it && it.advice.action !== "hold";
    });
  }, [onlyAction, codes, byCode]);

  const summary = data?.summary;

  return (
    <CollapsiblePanel
      id="monitor"
      title="盯盘监控"
      subtitle="日线 / 15 分 / 5 分多周期 · 每行给出挂单价 · 交易时段约 20 秒刷新（名单保存在本机）"
      defaultOpen
      action={
        <div className="flex items-center gap-2">
          <button
            onClick={() => void toggleNotify()}
            title="指令变化时（买入/减仓/止损）响铃提醒，页面后台时弹系统通知"
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1 text-xs transition-colors ${
              notifyOn
                ? "border-amber-700/60 bg-amber-950/40 text-amber-300 hover:bg-amber-950/60"
                : "border-slate-700 text-slate-400 hover:text-slate-200"
            }`}
          >
            {notifyOn ? <BellRing className="h-3.5 w-3.5" /> : <Bell className="h-3.5 w-3.5" />}
            {notifyOn ? "提醒已开" : "开启提醒"}
          </button>
          <button
            onClick={() => void refresh(false, true)}
            disabled={loading || codes.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            {loading ? "刷新中..." : "立即刷新"}
          </button>
        </div>
      }
    >
      {/* 今日决策条：一眼知道现在要不要动 */}
      {summary && summary.total > 0 && (
        <div className="mb-3 rounded-lg border border-slate-800 bg-gradient-to-br from-slate-900 to-slate-950 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-slate-200">现在要不要动</span>
            {summary.act_now === 0 ? (
              <span className="text-xs text-slate-400">全部观望，暂无需要立刻操作的标的</span>
            ) : (
              <>
                <span className="text-xs text-slate-300">
                  共 <b className="text-base text-white">{summary.act_now}</b> 只要操作
                </span>
                {summary.stop > 0 && (
                  <span className="rounded-md border border-red-800/70 bg-red-950/50 px-2 py-0.5 text-[11px] text-red-300">
                    止损 {summary.stop}
                  </span>
                )}
                {summary.sell > 0 && (
                  <span className="rounded-md border border-amber-800/60 bg-amber-950/40 px-2 py-0.5 text-[11px] text-amber-300">
                    卖出/减仓 {summary.sell}
                  </span>
                )}
                {summary.buy > 0 && (
                  <span className="rounded-md border border-green-800/60 bg-green-950/40 px-2 py-0.5 text-[11px] text-green-300">
                    买入 {summary.buy}
                  </span>
                )}
                {(summary.tactic_hits ?? 0) > 0 && (
                  <span
                    title="命中实战形态（K 线量价条件全部成立）的只数，名单内每只票的形态标签见股票列"
                    className="rounded-md border border-sky-800/60 bg-sky-950/40 px-2 py-0.5 text-[11px] text-sky-300"
                  >
                    形态命中 {summary.tactic_hits}
                  </span>
                )}
              </>
            )}
            <button
              onClick={() => setOnlyAction((v) => !v)}
              className={`ml-auto rounded-lg border px-2.5 py-1 text-[11px] transition-colors ${
                onlyAction
                  ? "border-brand bg-brand/10 text-brand"
                  : "border-slate-700 text-slate-400 hover:text-slate-200"
              }`}
            >
              {onlyAction ? "显示全部" : "只看要操作的"}
            </button>
          </div>
          {summary.top.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {summary.top.map((t) => (
                <span
                  key={t.code}
                  title={t.do}
                  className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] ${toneClass[t.tone] ?? toneClass.neutral}`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${toneDot[t.tone] ?? toneDot.neutral}`} />
                  <b>{t.name}</b>
                  <span className="opacity-80">{t.do || t.label}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 周期切换：日线定方向，分钟线定这一笔 */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-slate-700 p-0.5">
          {INTERVALS.map((it) => (
            <button
              key={it.value}
              onClick={() => {
                setInterval(it.value);
                try {
                  localStorage.setItem(LS_INTERVAL, it.value);
                } catch {
                  /* ignore */
                }
              }}
              title={it.hint}
              className={`rounded-md px-3 py-1 text-xs transition-colors ${
                interval === it.value ? "bg-brand/15 text-brand" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {it.label}
            </button>
          ))}
        </div>
        <span className="text-[11px] text-slate-500">
          {INTERVALS.find((i) => i.value === interval)?.hint}
        </span>
      </div>

      {interval !== "1d" && (
        <div className="mb-2 rounded-lg border border-amber-800/50 bg-amber-950/30 px-3 py-1.5 text-[11px] text-amber-300">
          日内模式：信号基于当日 VWAP 与 {interval} 均线，止损 1% 上下（最宽 1.5%），<b>仅当日有效</b>，收盘前需了结或改按日线持有。
          {data?.degraded && <span className="text-red-300"> 分钟数据暂不可用，已自动降级为日线决策。</span>}
        </div>
      )}

      {/* 添加栏 */}
      <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex flex-1 gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCodes();
              }
            }}
            placeholder="输入股票代码，空格/逗号分隔，如 600519 000858"
            className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-brand focus:outline-none"
          />
          <button
            onClick={addCodes}
            className="inline-flex items-center gap-1 rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700"
          >
            <Plus className="h-4 w-4" /> 添加
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void importWatchlist()}
            title="把自选股一次性加入监控名单"
            className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1.5 text-[11px] text-slate-400 hover:text-slate-200"
          >
            <Download className="h-3.5 w-3.5" /> 导入自选
          </button>
          <button
            onClick={() => void importHoldings()}
            title="把持仓加入监控，并带上成本价（指令会显示浮盈浮亏）"
            className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1.5 text-[11px] text-slate-400 hover:text-slate-200"
          >
            <Download className="h-3.5 w-3.5" /> 导入持仓
          </button>
        </div>
      </div>

      <div className="mb-3 text-[11px] text-slate-500">
        {data && (
          <>
            行情时间 <b className="text-slate-300">{fmtTime(data.quote_at || data.updated_at)}</b> ·{" "}
            <span className={data.freshness === "stale" ? "text-amber-400" : data.freshness === "live" ? "text-green-400" : "text-slate-500"}>
              {data.freshness === "stale" ? "行情可能延迟" : data.freshness === "live" ? "实时" : data.freshness === "closed" ? "收盘数据" : "时间未知"}
            </span>{" · "}
          </>
        )}
        {data?.market_open ? `每 ${data.poll_interval_seconds ?? 20} 秒刷新` : "休市低频刷新"} · {codes.length}/{MAX_CODES}
        {Object.keys(costs).length > 0 && <span className="text-slate-600"> · 已加载 {Object.keys(costs).length} 只持仓成本</span>}
      </div>

      {err && <div className="mb-2 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-300">{err}</div>}

      {codes.length === 0 && !data && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-700 py-8 text-center">
          <p className="text-sm text-slate-300">还没有监控的股票</p>
          <p className="mt-1 max-w-sm text-xs text-slate-500">
            输入代码或一键导入自选/持仓。每只票会给出「挂多少买、挂多少卖、跌到哪里止损」，
            到价可一键设提醒
          </p>
        </div>
      )}

      {codes.length > 0 && data && visibleCodes.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-700 py-6 text-center text-xs text-slate-500">
          当前没有需要操作的标的（全部观望）
        </div>
      )}

      {visibleCodes.length > 0 && (
        <div className="max-h-[520px] overflow-auto rounded-lg border border-slate-800">
          <table className="w-full text-sm" style={{ minWidth: 940 }}>
            <thead className="sticky top-0 z-10 bg-slate-900 text-left text-xs text-slate-400">
              <tr>
                <th className="px-2 py-2">#</th>
                <th className="px-2 py-2">股票</th>
                <th className="px-2 py-2 text-right">现价</th>
                <th className="px-2 py-2 text-right">{interval === "1d" ? "支撑/压力" : "VWAP / 日内高低"}</th>
                <th className="px-2 py-2">指令</th>
                <th className="px-2 py-2">挂单计划</th>
                <th className="px-2 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {visibleCodes.map((code, idx) => {
                const it = byCode.get(code);
                if (!it) {
                  return (
                    <tr key={code} className="border-t border-slate-800/60">
                      <td className="px-2 py-2 text-xs text-slate-500">{idx + 1}</td>
                      <td className="px-2 py-2">
                        <span className="text-slate-400">{code}</span>
                      </td>
                      <td colSpan={4} className="px-2 py-2 text-xs text-slate-500">
                        {data ? "暂无行情（可能停牌或代码有误）" : "加载中..."}
                      </td>
                      <td className="px-2 py-2 text-right">
                        <button
                          onClick={() => remove(code)}
                          className="rounded p-1 text-slate-600 hover:bg-red-950/40 hover:text-red-400"
                          title="移除"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  );
                }
                const { signal: s, advice: a } = it;
                const up = it.change_pct >= 0;
                const plan = a?.plan;
                const pnl = a?.pnl_pct;
                const intraday = a?.scope === "intraday";
                const trendMark = s?.trend === "up" ? "↑" : s?.trend === "down" ? "↓" : "→";
                return (
                  <tr key={code} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                    <td className="px-2 py-2 text-xs text-slate-500">{idx + 1}</td>
                    <td className="px-2 py-2">
                      <div className="font-medium text-slate-100">{it.name}</div>
                      <div className="text-[11px] text-slate-500">{code}</div>
                      {it.tactics && it.tactics.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {it.tactics.map((t) => (
                            <span
                              key={t.key}
                              title={t.action}
                              className={`rounded px-1 py-0.5 text-[10px] ${
                                t.direction === "buy" ? "bg-red-950/60" : "bg-green-950/50"
                              } ${actionTone(t.direction, 300)}`}
                            >
                              {t.name}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right">
                      <div className="text-slate-200">{num(it.price)}</div>
                      <div className={`text-[11px] ${pnlTone(it.change_pct)}`}>
                        {up ? "+" : ""}
                        {num(it.change_pct, 2)}%
                      </div>
                      {pnl != null && (
                        <div className={`text-[10px] ${pnlTone(pnl, 500)}`}>
                          浮盈 {pnl >= 0 ? "+" : ""}
                          {num(pnl, 1)}%
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right">
                      {intraday ? (
                        <>
                          <div className="text-slate-200">
                            <span className="text-[10px] text-slate-500">VWAP </span>
                            {num(s?.vwap)}
                          </div>
                          <div className="text-[11px]">
                            <span className="text-green-400/80">高 {num(s?.day_high)}</span>
                            <span className="text-slate-600"> / </span>
                            <span className="text-red-400/80">低 {num(s?.day_low)}</span>
                          </div>
                          <div className="text-[10px] text-slate-600">
                            {trendMark} 强度 {num(s?.strength, 1)}
                            {s?.volume_ratio != null ? ` · 量比 ${num(s.volume_ratio, 2)}x` : ""}
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="text-slate-300">{num(s?.support)}</div>
                          <div className="text-[11px] text-slate-500">{num(s?.resistance)}</div>
                          <div className="text-[10px] text-slate-600">
                            强度 {num(s?.strength, 1)}
                            {s?.volume_ratio != null ? ` · 量比 ${num(s.volume_ratio, 2)}x` : ""}
                          </div>
                        </>
                      )}
                    </td>
                    <td className="px-2 py-2">
                      <span
                        title={a?.hint}
                        className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium ${toneClass[a?.tone ?? "neutral"]}`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full ${toneDot[a?.tone ?? "neutral"]}`} />
                        {a?.label ?? "等待信号"}
                      </span>
                      <div className="mt-0.5 max-w-[240px] truncate text-[10px] text-slate-500" title={a?.hint}>
                        {a?.hint ?? " "}
                      </div>
                    </td>
                    <td className="px-2 py-2">
                      <div className="text-xs font-medium text-slate-100">{a?.do ?? "—"}</div>
                      <div className="mt-0.5 flex flex-wrap gap-x-2 text-[10px] text-slate-500">
                        <span>
                          买 <b className="text-green-400/90">{num(plan?.buy)}</b>
                        </span>
                        <span>
                          卖 <b className="text-amber-400/90">{num(plan?.sell)}</b>
                        </span>
                        <span>
                          止损 <b className="text-red-400/90">{num(plan?.stop)}</b>
                        </span>
                        {plan?.position_pct ? <span>仓位 {plan.position_pct}%</span> : null}
                      </div>
                      {intraday && it.daily && (
                        <div className="mt-0.5 text-[10px] text-slate-600">
                          日线 支撑 {num(it.daily.support)} · 压力 {num(it.daily.resistance)}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => void quickAlert(it)}
                          disabled={alertBusy === code}
                          className="rounded p-1 text-slate-500 hover:bg-slate-700/50 hover:text-amber-300 disabled:opacity-40"
                          title="按建议价建到价提醒（到价后报警中心提醒）"
                        >
                          {alertBusy === code ? (
                            <Bell className="h-4 w-4 animate-pulse" />
                          ) : (
                            <BellPlus className="h-4 w-4" />
                          )}
                        </button>
                        <button
                          onClick={() => remove(code)}
                          className="rounded p-1 text-slate-600 hover:bg-red-950/40 hover:text-red-400"
                          title="移除监控"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-2 text-[10px] text-slate-600">
        {interval === "1d" ? (
          <>
            日线档：挂单计划由日 K 布林带/均线/斐波那契回撤推导（买入=回踩支撑、卖出=压力位、止损=支撑下方 3%），
            适合持仓数天到数周的波段。
          </>
        ) : (
          <>
            {interval} 档：挂单计划由当日 VWAP、{interval} 均线与布林带推导，止损 1% 上下（最宽 1.5%），仅当日有效。
            日线大方向仍显示在「VWAP / 日内高低」列的下方参考，避免日内与波段反着做。
          </>
        )}
        导入持仓后叠加成本，硬止损取更紧者。开启「提醒」后指令变化会响铃，点铃铛图标可设到价提醒。
        仅供参考，不构成投资建议。
      </p>
    </CollapsiblePanel>
  );
}
