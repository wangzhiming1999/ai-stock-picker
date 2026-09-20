import { Suspense } from "react";
import { History, LineChart, Star, Wallet } from "lucide-react";
import { subNavFor } from "../lib/subnav";
import { useSubPage } from "../lib/useSubPage";
import type { NavJump } from "../lib/featureMap";
import { lazyRetry } from "../lib/lazyRetry";
import { STACK } from "../lib/ui";
import PanelSkeleton from "./ui/PanelSkeleton";
import Button from "./ui/Button";
import EmptyState from "./ui/EmptyState";
import SubNav from "./ui/SubNav";
import PageHeader from "./ui/PageHeader";

const WatchlistPanel = lazyRetry(() => import("./WatchlistPanel"));
const SimPanel = lazyRetry(() => import("./SimPanel"));
const PortfolioPanel = lazyRetry(() => import("./PortfolioPanel"));
const HistoryPanel = lazyRetry(() => import("./HistoryPanel"));

const SUB_ICON = { position: Wallet, sim: LineChart, watch: Star, history: History } as const;
const SUB_KEYS = {
  position: "position",
  sim: "sim",
  watch: "watch",
  history: "history",
} as const;

interface Props {
  authed: boolean;
  onAnalyze: (code: string) => void;
  onRequestAuth: () => void;
  /** 分析批次落库后 +1，用于刷新历史记录 */
  historyRefresh: number;
  /** 从功能地图跳进来的落点 */
  jump?: NavJump | null;
}

/**
 * 持仓 · 「我手里有什么」
 *
 * ## 未登录时整页引导，不给子导航
 * 上一版也是这么做的，理由值得写下来：如果先显示四个子页、用户点进去才发现
 * 每个都要求登录，那他要试错四次才能知道"这一页现在不可用"。
 *
 * ## 子页顺序 = 使用频率
 * 持仓（每天看）→ 模拟盘（练手）→ 自选（备选池）→ 历史（回溯）。
 * 顺序即默认落点，所以「持仓」排第一。
 */
export default function HoldingsPanel({ authed, onAnalyze, onRequestAuth, historyRefresh, jump }: Props) {
  const { sub, changeSub, isVisible, isMounted } = useSubPage("holdings", jump, SUB_KEYS.position);

  if (!authed) {
    return (
      <div className={STACK}>
        <PageHeader icon={Wallet} title="持仓" desc="我手里有什么：持仓、模拟盘、自选与历史记录" />
        <EmptyState
          icon={Wallet}
          title="登录后管理你的持仓与历史记录"
          desc="持仓数据、风险等级建议与历史分析将按账号隔离保存"
          action={
            <Button variant="primary" size="xl" onClick={onRequestAuth}>
              登录 / 注册
            </Button>
          }
        />
      </div>
    );
  }

  const items = subNavFor("holdings").map((s) => ({
    ...s,
    icon: SUB_ICON[s.key as keyof typeof SUB_ICON],
  }));

  return (
    <div className={STACK}>
      <PageHeader
        icon={Wallet}
        title="持仓"
        desc="我手里有什么：真实持仓、模拟盘、自选与历史分析记录"
      />

      <SubNav id="holdings" items={items} value={sub} onChange={changeSub} />

      {isMounted(SUB_KEYS.position) && (
        <div className={isVisible(SUB_KEYS.position)}>
          <Suspense fallback={<PanelSkeleton label="正在加载持仓" />}>
            <PortfolioPanel />
          </Suspense>
        </div>
      )}

      {isMounted(SUB_KEYS.sim) && (
        <div className={isVisible(SUB_KEYS.sim)}>
          <Suspense fallback={<PanelSkeleton label="正在加载模拟盘" />}>
            <SimPanel />
          </Suspense>
        </div>
      )}

      {isMounted(SUB_KEYS.watch) && (
        <div className={isVisible(SUB_KEYS.watch)}>
          <Suspense fallback={<PanelSkeleton label="正在加载自选股" />}>
            <WatchlistPanel onAnalyze={onAnalyze} />
          </Suspense>
        </div>
      )}

      {isMounted(SUB_KEYS.history) && (
        <div className={isVisible(SUB_KEYS.history)}>
          <Suspense fallback={<PanelSkeleton label="正在加载历史记录" />}>
            <HistoryPanel refreshKey={historyRefresh} />
          </Suspense>
        </div>
      )}
    </div>
  );
}
