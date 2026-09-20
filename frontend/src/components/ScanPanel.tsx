import { useState } from "react";
import { toast } from "sonner";
import { fetchAuctionOpportunity, fetchClosingOpportunity, scanMarket, strategyScan } from "../api/client";
import { confirmForceRefresh, useSpotCooldown } from "../lib/spotGuard";
import { useImportToWatchlist } from "../lib/useImportToWatchlist";
import { STACK } from "../lib/ui";
import type { OpportunityResult, ScanStock, StrategyName, StrategyStock } from "../types";
import { getScanViewAction } from "./scanPanelLogic";
import type { ScanView } from "./scanPanelLogic";
import ScanViewPicker from "./scan/ScanViewPicker";
import AuctionPanel from "./scan/AuctionPanel";
import ClosingPanel from "./scan/ClosingPanel";
import StrategyPanel from "./scan/StrategyPanel";
import MarketScanPanel from "./scan/MarketScanPanel";
import type { ScanFilterKey } from "./scan/shared";

interface Props {
  onPick: (codes: string[]) => void;
}

export default function ScanPanel({ onPick }: Props) {
  const { seconds: cooldown } = useSpotCooldown();
  const [scanView, setScanView] = useState<ScanView>("quick");
  // 批量加入自选（需登录）。与「形态」子页共用同一份实现，见 useImportToWatchlist。
  const importCodes = useImportToWatchlist();

  // 策略选股状态
  const [strategy, setStrategy] = useState<StrategyName>("momentum");
  const [strategyRunning, setStrategyRunning] = useState(false);
  const [strategyResult, setStrategyResult] = useState<StrategyStock[]>([]);
  const [strategySelected, setStrategySelected] = useState<Set<string>>(new Set());
  const [strategyAttempted, setStrategyAttempted] = useState(false);
  const [strategyError, setStrategyError] = useState("");

  // 全市场扫描状态
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<ScanStock[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [minChange, setMinChange] = useState("0");
  const [minAmount, setMinAmount] = useState("10");
  const [minPrice, setMinPrice] = useState("0");
  const [maxPrice, setMaxPrice] = useState("500");
  const [limit, setLimit] = useState("50");
  const [err, setErr] = useState("");

  // 早盘竞价 / 尾盘机会状态
  const [auctionResult, setAuctionResult] = useState<OpportunityResult | null>(null);
  const [auctionLoading, setAuctionLoading] = useState(false);
  const [closingResult, setClosingResult] = useState<OpportunityResult | null>(null);
  const [closingLoading, setClosingLoading] = useState(false);
  const [opportunitySelected, setOpportunitySelected] = useState<Set<string>>(new Set());

  const runAuction = async (force = false) => {
    setAuctionLoading(true);
    setErr("");
    if (force) setAuctionResult(null);
    setOpportunitySelected(new Set());
    try {
      setAuctionResult(await fetchAuctionOpportunity(15, force));
    } catch (e) {
      toast.error("早盘竞价机会获取失败", { description: (e as Error).message });
    } finally {
      setAuctionLoading(false);
    }
  };

  const runClosing = async (force = false) => {
    setClosingLoading(true);
    setErr("");
    if (force) setClosingResult(null);
    setOpportunitySelected(new Set());
    try {
      setClosingResult(await fetchClosingOpportunity(15, force));
    } catch (e) {
      toast.error("尾盘机会获取失败", { description: (e as Error).message });
    } finally {
      setClosingLoading(false);
    }
  };

  /**
   * 首扫走缓存、命中缓存后才提供「强制重跑」。
   *
   * 原实现是同一个按钮永远 `force=true`：每点一次都跳过两层缓存直打行情源，
   * 这是 2026-09-15 那次全站 502 的前端侧根因。现在只有显式重跑且通过二次确认才 force。
   */
  const guardedRun = async (cached: boolean, run: (force: boolean) => Promise<void>) => {
    if (!cached) {
      await run(false);
      return;
    }
    if (!(await confirmForceRefresh())) return;
    await run(true);
  };

  const toggleOpportunity = (code: string) => {
    setOpportunitySelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const pickOpportunitySelected = () => {
    if (opportunitySelected.size === 0) return;
    onPick(Array.from(opportunitySelected));
  };

  const runStrategy = async (s: StrategyName, force = false) => {
    setStrategy(s);
    setStrategyRunning(true);
    setStrategyAttempted(true);
    setStrategyError("");
    setErr("");
    setStrategyResult([]);
    setStrategySelected(new Set());
    try {
      // 默认走后端两层缓存（内存 5min → Supabase 6h）：首扫约 70s，之后秒开。
      // 需要最新数据时用面板右上角「强制刷新」（会先过二次确认与冷却闸门）。
      setStrategyResult(await strategyScan(s, 20, 3, force));
    } catch (e) {
      const message = (e as Error).message || "行情服务暂时不可用，请稍后重试";
      setStrategyError(message);
      toast.error("策略选股失败", { description: message });
    } finally {
      setStrategyRunning(false);
    }
  };

  const forceRefreshStrategy = async () => {
    if (!(await confirmForceRefresh())) return;
    await runStrategy(strategy, true);
  };

  const selectScanView = (view: ScanView) => {
    setScanView(view);
    if (getScanViewAction(view, strategyResult.length > 0, strategyRunning) === "run-default") {
      void runStrategy("momentum");
    }
  };

  const toggleStrategy = (code: string) => {
    setStrategySelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const pickStrategySelected = () => {
    if (strategySelected.size === 0) return;
    onPick(Array.from(strategySelected));
  };

  const doScan = async () => {
    setScanning(true);
    setErr("");
    setScanResult([]);
    setSelected(new Set());
    try {
      // 默认走缓存；需要最新数据时用「强制刷新」（过闸门）。
      setScanResult(
        await scanMarket(
          {
            min_price: parseFloat(minPrice) || 0,
            max_price: parseFloat(maxPrice) || 10000,
            min_change: parseFloat(minChange) || -100,
            max_change: 100,
            min_amount_yi: parseFloat(minAmount) || 0,
            max_pe: 1000,
            limit: parseInt(limit) || 50,
          },
          false
        )
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setScanning(false);
    }
  };

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const pickSelected = () => {
    if (selected.size === 0) return;
    onPick(Array.from(selected));
  };

  const onFilterChange = (key: ScanFilterKey, value: string) => {
    if (key === "minChange") setMinChange(value);
    else if (key === "minAmount") setMinAmount(value);
    else if (key === "minPrice") setMinPrice(value);
    else if (key === "maxPrice") setMaxPrice(value);
    else if (key === "limit") setLimit(value);
  };

  return (
    <div className={STACK}>
      <ScanViewPicker
        scanView={scanView}
        strategyRunning={strategyRunning}
        onSelect={selectScanView}
      />

      {scanView === "timing" && <>
        <AuctionPanel
          result={auctionResult}
          loading={auctionLoading}
          cooldown={cooldown}
          selected={opportunitySelected}
          onRun={() => void guardedRun(Boolean(auctionResult?.cached), runAuction)}
          onImportAll={() => void importCodes(auctionResult ? auctionResult.items.map((s) => s.code) : [])}
          onPickSelected={pickOpportunitySelected}
          onToggle={toggleOpportunity}
        />
        <ClosingPanel
          result={closingResult}
          loading={closingLoading}
          cooldown={cooldown}
          selected={opportunitySelected}
          onRun={() => void guardedRun(Boolean(closingResult?.cached), runClosing)}
          onImportAll={() => void importCodes(closingResult ? closingResult.items.map((s) => s.code) : [])}
          onPickSelected={pickOpportunitySelected}
          onToggle={toggleOpportunity}
        />
      </>}

      {scanView === "quick" && (
        <StrategyPanel
          strategy={strategy}
          running={strategyRunning}
          result={strategyResult}
          selected={strategySelected}
          attempted={strategyAttempted}
          error={strategyError}
          cooldown={cooldown}
          onRun={(s) => void runStrategy(s)}
          onForceRefresh={() => void forceRefreshStrategy()}
          onImportAll={() => void importCodes(strategyResult.map((s) => s.code))}
          onPickSelected={pickStrategySelected}
          onToggle={toggleStrategy}
        />
      )}

      {scanView === "advanced" && (
        <MarketScanPanel
          scanning={scanning}
          scanResult={scanResult}
          selected={selected}
          err={err}
          filters={{ minChange, minAmount, minPrice, maxPrice, limit }}
          onFilterChange={onFilterChange}
          onScan={() => void doScan()}
          onImportAll={() => void importCodes(scanResult.map((s) => s.code))}
          onPickSelected={pickSelected}
          onToggle={toggle}
        />
      )}
    </div>
  );
}
