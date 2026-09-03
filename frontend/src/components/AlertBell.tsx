import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Bell, BellRing, CheckCheck } from "lucide-react";
import { toast } from "sonner";
import { evaluateAlerts, fetchAlertEvents, fetchAlertUnread, markAlertRead } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { AlertEvent } from "../types";

const EVAL_INTERVAL = 180_000; // 3 分钟评估一次（兜底高频；cron 另做服务端兜底）

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

const sevStyle: Record<string, string> = {
  danger: "text-red-400",
  warn: "text-amber-400",
  info: "text-slate-400",
};

export default function AlertBell() {
  const { user } = useAuth();
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<number | null>(null);

  const refreshUnread = useCallback(async () => {
    if (!user) return;
    setUnread(await fetchAlertUnread());
  }, [user]);

  const runEvaluate = useCallback(async () => {
    if (!user) return;
    const n = await evaluateAlerts();
    if (n > 0) {
      toast.warning(`触发 ${n} 条价格预警`, { description: "查看右上角铃铛" });
    }
    void refreshUnread();
  }, [user, refreshUnread]);

  const loadEvents = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      setEvents(await fetchAlertEvents(false, 30));
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    void refreshUnread();
    void runEvaluate();
    timerRef.current = window.setInterval(() => void runEvaluate(), EVAL_INTERVAL);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [user, refreshUnread, runEvaluate]);

  useEffect(() => {
    if (open) void loadEvents();
  }, [open, loadEvents]);

  if (!user) return null;

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) void loadEvents();
  };

  const readAll = async () => {
    await markAlertRead();
    setUnread(0);
    setEvents((ev) => ev.map((e) => ({ ...e, is_read: true })));
  };

  return (
    <div className="relative">
      <button
        onClick={toggle}
        className="relative rounded-lg p-2 text-slate-300 hover:bg-slate-800 hover:text-white"
        title="价格预警"
        aria-label="预警通知"
      >
        {unread > 0 ? <BellRing className="h-5 w-5 text-amber-400" /> : <Bell className="h-5 w-5" />}
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <motion.div
              initial={{ opacity: 0, y: -8, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.97 }}
              transition={{ duration: 0.16 }}
              className="absolute right-0 z-50 mt-2 w-80 rounded-xl border border-slate-700 bg-slate-900 shadow-2xl"
            >
              <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2.5">
                <span className="text-sm font-semibold text-slate-100">价格预警</span>
                <button onClick={readAll} className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-brand">
                  <CheckCheck className="h-3.5 w-3.5" />
                  全部已读
                </button>
              </div>
              <div className="max-h-80 overflow-auto">
                {loading && events.length === 0 ? (
                  <div className="px-4 py-6 text-center text-xs text-slate-500">加载中...</div>
                ) : events.length === 0 ? (
                  <div className="px-4 py-6 text-center text-xs text-slate-500">暂无预警事件。在「持仓」页添加止损/目标价规则。</div>
                ) : (
                  events.map((e) => (
                    <div
                      key={e.id}
                      className={`border-b border-slate-800/60 px-4 py-2.5 ${e.is_read ? "" : "bg-amber-950/10"}`}
                    >
                      <div className="flex items-center justify-between">
                        <span className={`text-xs font-semibold ${sevStyle[e.severity] ?? "text-slate-200"}`}>{e.title}</span>
                        <span className="text-[10px] text-slate-500">{timeAgo(e.created_at)}</span>
                      </div>
                      <p className="mt-0.5 text-[11px] text-slate-400">{e.message}</p>
                    </div>
                  ))
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
