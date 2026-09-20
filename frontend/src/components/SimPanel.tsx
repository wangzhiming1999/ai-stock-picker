import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import type {
  SimAccount,
  SimPerformance,
  SimPositionsData,
  SimTradesData,
} from "../types";
import { useAuth } from "../auth/AuthContext";
import { safeNumber } from "../lib/safe";
import {
  MOCK_SIM_ACCOUNT,
  MOCK_SIM_PERFORMANCE,
  MOCK_SIM_POSITIONS,
  MOCK_SIM_TRADES,
} from "../data/simMock";
import {
  fetchSimAccount,
  fetchSimPerformance,
  fetchSimPositions,
  fetchSimTrades,
  initSimAccount,
  resetSimAccount,
} from "../api/client";
import Button from "./ui/Button";
import AccountOverview from "./sim/AccountOverview";
import PositionsTable from "./sim/PositionsTable";
import TradesList from "./sim/TradesList";
import PerfChart from "./sim/PerfChart";
import TradeModal from "./sim/TradeModal";
import AgentDecisionsSection from "./sim/AgentDecisionsSection";
import type { ModalState } from "./sim/shared";

export default function SimPanel() {
  const { user } = useAuth();
  const [account, setAccount] = useState<SimAccount | null>(null);
  const [positions, setPositions] = useState<SimPositionsData | null>(null);
  const [trades, setTrades] = useState<SimTradesData | null>(null);
  const [perf, setPerf] = useState<SimPerformance | null>(null);
  const [usingMock, setUsingMock] = useState(false);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState<ModalState | null>(null);

  /** 真实优先：并行拉取 4 个接口；任一 500/网络失败则整体降级到固定 mock 数据。 */
  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const [acct, pos, trd, pf] = await Promise.all([
        fetchSimAccount(),
        fetchSimPositions(),
        fetchSimTrades(30),
        fetchSimPerformance(),
      ]);
      setAccount(acct);
      setPositions(pos);
      setTrades(trd);
      setPerf(pf);
      setUsingMock(false);
    } catch {
      // 后端 sim 接口不可用（缺表/未部署）：降级到固定演示数据，不抛红屏
      setAccount(MOCK_SIM_ACCOUNT);
      setPositions(MOCK_SIM_POSITIONS);
      setTrades(MOCK_SIM_TRADES);
      setPerf(MOCK_SIM_PERFORMANCE);
      setUsingMock(true);
      toast.warning("模拟盘后端暂不可用，已显示演示数据", { id: "sim-mock-fallback" });
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!user) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5 text-sm text-ink-muted">
        请先登录后使用模拟盘（虚拟资金，按用户隔离）。
      </div>
    );
  }

  // 真实模式但未初始化账户：提示建仓
  const realButUninit = !usingMock && account && !account.initialized;

  const summary = useMemo(() => {
    if (!positions || positions.positions.length === 0) return null;
    return positions.positions.reduce((s, p) => s + safeNumber(p.market_value), 0);
  }, [positions]);

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div>
            <h3 className="text-sm font-semibold text-ink">模拟盘</h3>
            <p className="mt-0.5 text-xs text-ink-faint">虚拟资金实操验证 · A 股费用规则 · T+1</p>
          </div>
          {usingMock && (
            <span className="rounded border border-amber-700/40 bg-amber-950/40 px-1.5 py-0.5 text-xs font-medium text-amber-300" title="模拟盘后端当前不可用，前端展示固定演示数据">
              演示数据
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {loading && <span className="text-xs text-ink-faint">加载中…</span>}
          {!usingMock && (
            <button
              onClick={async () => {
                const ok = window.confirm(
                  "重置模拟盘将清空：\n" +
                    "· 所有成交流水（sim_trades）\n" +
                    "· 净值快照（portfolio_snapshots）\n" +
                    "· 现金归零\n\n" +
                    "不影响：「总资金」与「我的持仓」配置（user_profiles）。\n" +
                    "如需调整总资金，请到「我的持仓」面板修改。\n\n" +
                    "此操作不可恢复，确认重置？"
                );
                if (!ok) return;
                try {
                  await resetSimAccount();
                  toast.success("已重置模拟盘");
                  void load();
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
              className="rounded border border-red-800/60 px-2.5 py-1 text-xs text-red-300 hover:border-red-500 hover:bg-red-950/30 hover:text-red-200"
              title="清空所有成交流水、净值快照、现金归零（不影响总资金与持仓配置）"
            >
              重置
            </button>
          )}
          <Button variant="primary" size="md"
            onClick={() => setModal({ side: "buy", code: "" })}
            >
            + 模拟买入
          </Button>
        </div>
      </div>

      {realButUninit && (
        <div className="mb-4 rounded-lg border border-amber-700/40 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
          模拟账户尚未初始化。
          <button
            onClick={async () => {
              try {
                await initSimAccount();
                toast.success("模拟账户已初始化");
                void load();
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
            className="ml-2 underline underline-offset-2 hover:text-amber-100"
          >
            立即初始化（¥100,000 虚拟资金）
          </button>
        </div>
      )}

      {account && account.initialized && (
        <>
          <AccountOverview account={account} marketValue={safeNumber(summary ?? account.market_value)} />
          <PositionsTable
            positions={positions}
            onSell={(code, price) => setModal({ side: "sell", code, price })}
          />
          {perf && perf.snapshots.length > 1 && <PerfChart data={perf} />}
          <TradesList trades={trades} />
          {/* Agent 决策闭环：track record + 采纳/未采纳对照（表未启用时内部自降级为一行说明） */}
          <AgentDecisionsSection />
        </>
      )}

      {modal && (
        <TradeModal
          side={modal.side}
          initialCode={modal.code}
          initialPrice={modal.price}
          onClose={() => setModal(null)}
          onDone={() => void load()}
        />
      )}
    </div>
  );
}
