import { useEffect, useState } from "react";
import { Activity, ClipboardList } from "lucide-react";
import CollapsiblePanel from "./CollapsiblePanel";
import DailyBriefing from "./DailyBriefing";
import MonitorPanel from "./MonitorPanel";
import { sessionInfo, type SessionKey } from "../lib/session";

interface Props {
  onPick: (codes: string[]) => void;
}

type MainView = "briefing" | "monitor";

/** 每个时段告诉用户「现在该看什么」，而不是让他自己在一堆卡片里找 */
const HINT: Record<SessionKey, string> = {
  preopen: "开盘前 · 先定今天的方向和票池",
  auction: "集合竞价进行中 · 9:30 后自动切到盯盘",
  morning: "早盘进行中 · 盯盘为主",
  lunch: "午间休市 · 复盘上午的持仓与信号",
  afternoon: "午后盘中 · 盯盘为主",
  closing: "尾盘窗口 · 该决定卖还是买了",
  closed: "今日已收盘 · 看结果复盘",
  holiday: "今日休市 · 适合提前研究票池",
};

/**
 * 今日作战 · 默认首屏
 *
 * 产品定位是「日内操作指令台」——用户一天只有三个决策点（早盘定方向、盘中盯盘、
 * 尾盘定动作），所以这一页的主视图必须由「现在几点」决定，打开即对应当下该干的事。
 *
 * 主视图规则见 lib/session.ts:sessionInfo()；用户可手动覆盖，跨时段时自动复位。
 */
export default function TodayPanel({ onPick }: Props) {
  const [now, setNow] = useState(() => new Date());
  const [override, setOverride] = useState<MainView | null>(null);

  // 每分钟刷新时段；跨过时段边界时主视图自动跟随
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  const info = sessionInfo(now);

  // 时段一变，清掉手动覆盖，回到自动规则
  useEffect(() => {
    setOverride(null);
  }, [info.key]);

  const view: MainView = override ?? info.mainView;

  return (
    <div className="space-y-4">
      {/* 时段条：说明现在是什么时段、这一屏在看什么 */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5 shrink-0">
            {info.trading && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-light opacity-75" />
            )}
            <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${info.trading ? "bg-brand" : "bg-slate-600"}`} />
          </span>
          <span className="text-sm font-semibold text-white">{info.label}</span>
          <span className="truncate text-xs text-ink-faint">{HINT[info.key]}</span>
        </div>

        <div className="flex shrink-0 rounded-lg border border-slate-800 p-0.5" role="group" aria-label="主视图切换">
          <button
            onClick={() => setOverride("monitor")}
            aria-pressed={view === "monitor"}
            className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              view === "monitor" ? "bg-brand text-white" : "text-ink-muted hover:text-ink"
            }`}
          >
            <Activity className="h-3.5 w-3.5" aria-hidden />
            盯盘
          </button>
          <button
            onClick={() => setOverride("briefing")}
            aria-pressed={view === "briefing"}
            className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              view === "briefing" ? "bg-brand text-white" : "text-ink-muted hover:text-ink"
            }`}
          >
            <ClipboardList className="h-3.5 w-3.5" aria-hidden />
            简报
          </button>
        </div>
      </div>

      {/* 主视图 */}
      {view === "monitor" ? <MonitorPanel /> : <DailyBriefing onPick={onPick} />}

      {/* 副视图：默认收起，按需展开（收起时不挂载，避免白跑请求） */}
      {view === "monitor" ? (
        <CollapsiblePanel
          id="today-briefing"
          title="今日作战简报"
          subtitle="早盘方向 · 尾盘动作 · 盘前预读 · 当日复盘"
          defaultOpen={false}
        >
          <DailyBriefing onPick={onPick} />
        </CollapsiblePanel>
      ) : (
        <CollapsiblePanel
          id="today-monitor"
          title="盘中监控台"
          subtitle="实时盯盘 · 强弱判断与买卖点"
          defaultOpen={false}
        >
          <MonitorPanel />
        </CollapsiblePanel>
      )}
    </div>
  );
}
