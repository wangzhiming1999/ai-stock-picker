import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { addAlertRule, fetchHoldings, fetchLimitUpSnapshot, fetchMonitor, fetchWatchlist } from "../api/client";
import CollapsiblePanel from "./ui/CollapsiblePanel";
import { useAuth } from "../auth/AuthContext";
import type { LimitUpRelayStock, MonitorInterval, MonitorResult, MonitorStock } from "../types";
import { ensureNotCooling } from "../lib/spotGuard";
import {
  DEFAULT_POLL_MS,
  LS_KEY,
  LS_NOTIFY,
  MAX_CODES,
  fmtTime,
  loadInterval,
  loadNotify,
  loadSaved,
  num,
} from "./monitor/constants";
import { useMonitorAlerts } from "./monitor/useMonitorAlerts";
import MonitorRow from "./monitor/MonitorRow";
import MonitorSummary from "./monitor/MonitorSummary";
import MonitorToolbar from "./monitor/MonitorToolbar";
import MonitorHeaderActions from "./monitor/MonitorHeaderActions";
import AlertLog from "./monitor/AlertLog";
import RelayHits from "./monitor/RelayHits";

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
  const costsRef = useRef<Record<string, number>>({});
  const intervalRef = useRef<MonitorInterval>(interval);

  const { alerts, checkAlerts, primeAudio, clearAlerts } = useMonitorAlerts(notifyOn);

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

  /**
   * 持仓 ∩ 当日连板股：盯盘页的连板减仓优先级提示。
   * relay_score 越低（封板质量越差）的持仓，明天还接不接得动越存疑 —— 排最前。
   * 连板快照获取失败（行情源风控等）时静默隐藏，绝不影响盯盘主链路。
   */
  const [relayHits, setRelayHits] = useState<LimitUpRelayStock[]>([]);
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const snap = await fetchLimitUpSnapshot();
        if (!alive) return;
        const relayMap = new Map((snap.relay_stocks ?? []).map((r) => [r.code, r]));
        const hits = codes
          .filter((c) => relayMap.has(c))
          .map((c) => relayMap.get(c) as LimitUpRelayStock)
          .sort((a, b) => a.score - b.score || b.boards - a.boards);
        setRelayHits(hits);
      } catch {
        if (alive) setRelayHits([]);
      }
    })();
    return () => {
      alive = false;
    };
  }, [codes.join(",")]);

  const refresh = useCallback(
    /** silent: 静默（轮询）不显示 loading；force: 忽略后端 K 线缓存重新拉取 */
    async (silent = false, force = false) => {
      if (codes.length === 0) return;
      if (busyRef.current) return;
      busyRef.current = true;
      if (!silent) setLoading(true);
      try {
        const result = await fetchMonitor(codes, force, costsRef.current, intervalRef.current);
        setData(result);
        // 成功才清错，而不是开头无条件清 —— 否则上一轮的失败提示会被下一轮轮询
        // 立刻抹掉（20s 一轮），用户只看到一闪而过的红字，接着以为一切正常。
        setErr("");
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

  /**
   * 「立即刷新」= 忽略后端 K 线缓存重算挂单价。
   *
   * 这是盯盘的核心动作（盘中会反复点），所以不弹二次确认；
   * 但风控期内仍必须拦住 —— 那时打行情源只会失败，还会把封禁窗口拖长。
   */
  const forceRefresh = async () => {
    if (!(await ensureNotCooling())) return;
    await refresh(false, true);
  };

  /** 开启/关闭桌面通知 */
  const toggleNotify = async () => {
    if (!("Notification" in window)) {
      toast.error("当前浏览器不支持系统通知，仅保留提示音与页面提醒");
      return;
    }
    if (notifyOn) {
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
    setNotifyOn(on);
    try {
      localStorage.setItem(LS_NOTIFY, on ? "1" : "0");
    } catch {
      /* ignore */
    }
    if (on) {
      // 用户手势内预热音频上下文，保证后续轮询提示音可播放
      primeAudio();
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
      return;
    }
    // 换周期会让所有指令重算，先清掉基线，避免把周期切换误报成「指令变化」
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
        <MonitorHeaderActions
          notifyOn={notifyOn}
          onToggleNotify={() => void toggleNotify()}
          onForceRefresh={() => void forceRefresh()}
          loading={loading}
          disabled={codes.length === 0}
        />
      }
    >
      {/* 今日决策条：一眼知道现在要不要动 */}
      {summary && summary.total > 0 && (
        <MonitorSummary
          summary={summary}
          onlyAction={onlyAction}
          onToggleOnlyAction={() => setOnlyAction((v) => !v)}
        />
      )}

      {/* 持仓连板提示：封板质量差的排最前，走弱时减仓优先级最高。
          措辞只讲资金面强弱与观察点，不下卖单指令（与后端证据闸门口径一致）。 */}
      {relayHits.length > 0 && <RelayHits hits={relayHits} />}

      {/* 盯盘提醒留痕：顶部的浮层提示会限时消失，这里不会 */}
      <AlertLog alerts={alerts} onClear={clearAlerts} />

      <MonitorToolbar
        input={input}
        setInput={setInput}
        onAdd={addCodes}
        onImportWatchlist={() => void importWatchlist()}
        onImportHoldings={() => void importHoldings()}
        interval={interval}
        setInterval={setInterval}
      />

      {interval !== "1d" && (
        <div className="mb-2 rounded-lg border border-amber-800/50 bg-amber-950/30 px-3 py-1.5 text-xs text-amber-300">
          日内模式：信号基于当日 VWAP 与 {interval} 均线，止损 1% 上下（最宽 1.5%），<b>仅当日有效</b>，收盘前需了结或改按日线持有。
          {data?.degraded && <span className="text-red-300"> 分钟数据暂不可用，已自动降级为日线决策。</span>}
        </div>
      )}

      {/* 部分失败必须显式提示：只让列表变短，用户会把行情源故障读成「今天没什么可操作的」 */}
      {data?.partial && data.notice && (
        <div className="mb-2 rounded-lg border border-amber-800/50 bg-amber-950/30 px-3 py-1.5 text-xs text-amber-300">
          {data.notice}
          {data.missed?.length > 0 && (
            <span className="text-amber-200/70">　未出结果：{data.missed.join(" ")}</span>
          )}
        </div>
      )}
      {/* 周/月线未加载 ≠ 形态未命中：不说清楚，多周期共振不显示会被读成「没命中」 */}
      {data?.periods && !data.periods.loaded && (
        <div className="mb-2 text-xs text-ink-faint">
          多周期形态（周/月线）本轮未加载，点「立即刷新」可补上。
        </div>
      )}

      <div className="mb-3 text-xs text-ink-faint">
        {data && (
          <>
            行情时间 <b className="text-ink-soft">{fmtTime(data.quote_at || data.updated_at)}</b> ·{" "}
            <span className={data.freshness === "stale" ? "text-amber-400" : data.freshness === "live" ? "text-green-400" : "text-ink-faint"}>
              {data.freshness === "stale" ? "行情可能延迟" : data.freshness === "live" ? "实时" : data.freshness === "closed" ? "收盘数据" : "时间未知"}
            </span>{" · "}
          </>
        )}
        {data?.market_open ? `每 ${data.poll_interval_seconds ?? 20} 秒刷新` : "休市低频刷新"} · {codes.length}/{MAX_CODES}
        {Object.keys(costs).length > 0 && <span className="text-ink-faint"> · 已加载 {Object.keys(costs).length} 只持仓成本</span>}
      </div>

      {err && <div className="mb-2 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-300">{err}</div>}

      {codes.length === 0 && !data && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-700 py-8 text-center">
          <p className="text-sm text-ink-soft">还没有监控的股票</p>
          <p className="mt-1 max-w-sm text-xs text-ink-faint">
            输入代码或一键导入自选/持仓。每只票会给出「挂多少买、挂多少卖、跌到哪里止损」，
            到价可一键设提醒
          </p>
        </div>
      )}

      {codes.length > 0 && data && visibleCodes.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-700 py-6 text-center text-xs text-ink-faint">
          当前没有需要操作的标的（全部观望）
        </div>
      )}

      {visibleCodes.length > 0 && (
        <div className="max-h-[520px] overflow-auto rounded-xl border border-slate-800">
          <table className="w-full text-sm" style={{ minWidth: 940 }}>
            <thead className="sticky top-0 z-10 bg-slate-900 text-left text-xs text-ink-muted">
              <tr>
                <th scope="col" className="px-3 py-2">#</th>
                <th scope="col" className="px-3 py-2">股票</th>
                <th scope="col" className="px-3 py-2 text-right">现价</th>
                <th scope="col" className="px-3 py-2 text-right">{interval === "1d" ? "支撑/压力" : "VWAP / 日内高低"}</th>
                <th scope="col" className="px-3 py-2">指令</th>
                <th scope="col" className="px-3 py-2">挂单计划</th>
                <th scope="col" className="px-3 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {visibleCodes.map((code, idx) => (
                <MonitorRow
                  key={code}
                  code={code}
                  idx={idx}
                  it={byCode.get(code)}
                  hasData={!!data}
                  alertBusy={alertBusy}
                  onQuickAlert={quickAlert}
                  onRemove={remove}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-2 text-xs text-ink-faint">
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
