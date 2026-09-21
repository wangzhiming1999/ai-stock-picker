import { useEffect, useState } from "react";
import { Activity, ClipboardList, Zap } from "lucide-react";
import DailyBriefing from "./DailyBriefing";
import FeatureMapBar from "./FeatureMapBar";
import MonitorPanel from "./MonitorPanel";
import SubNav from "./ui/SubNav";
import PageHeader from "./ui/PageHeader";
import type { Domain, NavJump } from "../lib/featureMap";
import { sessionInfo, type SessionKey } from "../lib/session";
import { subNavFor } from "../lib/subnav";
import { STACK } from "../lib/ui";

interface Props {
  onPick: (codes: string[]) => void;
  /** 打开功能地图（null = 整张图，传域 = 滚到那一组） */
  onOpenMap: (domain: Domain | null) => void;
  /** 从功能地图跳进来的落点 */
  jump?: NavJump | null;
}

type MainView = "briefing" | "monitor";

const SUB_ICON = { monitor: Activity, briefing: ClipboardList } as const;

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
 * 尾盘定动作），所以这一页默认停在哪个子页必须由「现在几点」决定，打开即对应当下
 * 该干的事（规则见 `lib/session.ts:sessionInfo()`）。用户可手动覆盖，跨时段自动复位。
 *
 * ## 与另外三个页面的差别（为什么没有用 useSubPage）
 * 选机会 / 持仓 / 研究 的默认子页是**固定**的，这里的是**随时间变**的。
 * 多出来的那条「时段一变就复位手动覆盖」的规则塞不进通用 hook，
 * 强塞只会让另外三个页面也背上一份用不到的复杂度。
 *
 * ## 重构去掉了什么
 * 上一版是「主视图 + 另一视图折叠在下面」，两个视图互相包含：盯盘为主时下面挂着简报，
 * 简报为主时下面挂着盯盘。结果是同一屏里两套不同节奏的读数同时存在，而且折叠区
 * 一旦被"永久展开"过就再也回不到干净状态。现在两者是**平级的两个子页**，靠二级导航切换。
 */
export default function TodayPanel({ onPick, onOpenMap, jump }: Props) {
  const [now, setNow] = useState(() => new Date());
  const [override, setOverride] = useState<MainView | null>(null);
  const [mounted, setMounted] = useState<Set<MainView>>(
    () => new Set<MainView>([sessionInfo(new Date()).mainView]),
  );

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

  // ⚠️ 必须排在上面那条之后：挂载时两条都会跑一遍，
  //    顺序反了的话「跳转指定的主视图」会被「按时段复位」立刻冲掉。
  useEffect(() => {
    if (jump?.tab === "today" && (jump.sub === "monitor" || jump.sub === "briefing")) {
      setOverride(jump.sub);
    }
  }, [jump?.id, jump?.sub, jump?.tab]);

  const view: MainView = override ?? info.mainView;

  // 访问过的子页常驻 DOM（隐藏而非卸载）—— 来回切换不该重新拉一遍行情。
  useEffect(() => {
    setMounted((prev) => (prev.has(view) ? prev : new Set(prev).add(view)));
  }, [view]);

  const changeSub = (k: string) => {
    if (k === "monitor" || k === "briefing") setOverride(k);
  };

  const items = subNavFor("today").map((s) => ({
    ...s,
    icon: SUB_ICON[s.key as keyof typeof SUB_ICON],
  }));

  return (
    <div className={STACK}>
      <PageHeader
        icon={Zap}
        title="今日作战"
        meta={
          <span className="flex items-center justify-end gap-1.5">
            <span className="relative flex h-2 w-2">
              {info.trading && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-light opacity-75" />
              )}
              <span
                className={`relative inline-flex h-2 w-2 rounded-full ${info.trading ? "bg-brand" : "bg-surface-line-strong"}`}
              />
            </span>
            <span className="font-medium text-ink-soft">{info.label}</span>
          </span>
        }
      />

      {/* 时段说明：这一屏现在在看什么 */}
      <p className="-mt-2 text-meta text-ink-soft">{HINT[info.key]}</p>

      {/* 功能地图入口：一行高，说明这个工具一共有多少东西，并能按域直达 */}
      <FeatureMapBar onOpen={onOpenMap} />

      <SubNav id="today" items={items} value={view} onChange={changeSub} />

      <div className={view === "monitor" ? "" : "hidden"}>{mounted.has("monitor") && <MonitorPanel />}</div>
      <div className={view === "briefing" ? "" : "hidden"}>
        {mounted.has("briefing") && <DailyBriefing onPick={onPick} />}
      </div>
    </div>
  );
}
