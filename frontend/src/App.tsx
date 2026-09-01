import { useCallback, useRef, useState } from "react";
import { fetchStock, streamAnalysis } from "./api/client";
import HistoryPanel from "./components/HistoryPanel";
import MarketPanel from "./components/MarketPanel";
import StockCard from "./components/StockCard";
import type { StockAnalysis, StockInfo, SSEEvent } from "./types";

type Phase = "idle" | "running" | "done" | "error";
type Tab = "analyze" | "market" | "history";

interface AnalysisItem {
  analysis: StockAnalysis;
  info?: StockInfo;
}

export default function App() {
  const [tab, setTab] = useState<Tab>("analyze");
  const [codes, setCodes] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState("");
  const [items, setItems] = useState<AnalysisItem[]>([]);
  const [currentCode, setCurrentCode] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState("");
  const [infos, setInfos] = useState<Record<string, StockInfo>>({});
  const [historyRefresh, setHistoryRefresh] = useState(0);

  const abortRef = useRef<AbortController | null>(null);

  const parseCodes = useCallback((): string[] => {
    return codes
      .split(/[\s,，;；、]+/)
      .map((s) => s.trim())
      .filter((s) => /^\d{6}$/.test(s));
  }, [codes]);

  const runAnalysis = async () => {
    const list = parseCodes();
    if (list.length === 0) {
      setErrorMsg("请输入有效的 6 位股票代码，多个用逗号分隔，例如：600519, 000858, 300750");
      return;
    }

    setPhase("running");
    setErrorMsg("");
    setItems([]);
    setStatus("正在准备...");
    setInfos({});

    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    const infoTask = Promise.all(
      list.map((code) => fetchStock(code).catch(() => undefined))
    ).then((results) => {
      const map: Record<string, StockInfo> = {};
      for (const info of results) {
        if (info) map[info.code] = info;
      }
      setInfos(map);
    });

    const handleEvent = (e: SSEEvent) => {
      switch (e.type) {
        case "status":
          setStatus(e.message);
          break;
        case "stock_start":
          setCurrentCode(e.payload?.code ?? "");
          setStatus(e.message);
          break;
        case "delta":
          break;
        case "stock_done": {
          const result = e.payload?.result;
          if (result) {
            setItems((prev) => [...prev, { analysis: result }]);
            setStatus(e.message);
          }
          break;
        }
        case "stock_error":
          setStatus(e.message);
          break;
        case "batch_saved":
          setHistoryRefresh((n) => n + 1);
          break;
        case "done":
          setPhase("done");
          setStatus(e.message);
          break;
        case "error":
          setPhase("error");
          setErrorMsg(e.message);
          break;
      }
    };

    try {
      await Promise.all([infoTask, streamAnalysis(list, handleEvent, signal)]);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setPhase("error");
        setErrorMsg((err as Error).message || "分析失败，请检查后端服务是否启动、API Key 是否配置");
      }
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setPhase("idle");
    setStatus("已手动停止");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void runAnalysis();
    }
  };

  // 从市场面板带回勾选的股票
  const handleMarketPick = (codesList: string[]) => {
    setCodes(codesList.join(", "));
    setTab("analyze");
  };

  const tabs: { key: Tab; label: string }[] = [
    { key: "analyze", label: "AI 选股" },
    { key: "market", label: "市场扫描" },
    { key: "history", label: "历史记录" },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* 顶部 */}
      <header className="border-b border-slate-800/80 bg-slate-900/50 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand text-xl font-black text-white">
              股
            </div>
            <div>
              <h1 className="text-lg font-bold">AI 选股分析</h1>
              <p className="text-xs text-slate-400">LLM 驱动 · A股 · 基本面/技术面/消息面综合评分</p>
            </div>
          </div>
          <a
            href="http://localhost:8000/api/health"
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200"
          >
            后端状态
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {/* Tab 导航 */}
        <div className="mb-6 flex gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                tab === t.key ? "bg-brand text-white" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "analyze" && (
          <>
            {/* 输入区 */}
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
              <label className="mb-2 block text-sm font-medium text-slate-300">股票代码</label>
              <div className="flex flex-col gap-3 sm:flex-row">
                <input
                  value={codes}
                  onChange={(e) => setCodes(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="输入 6 位代码，逗号分隔，如：600519, 000858, 300750"
                  disabled={phase === "running"}
                  className="flex-1 rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2.5 text-sm outline-none placeholder:text-slate-500 focus:border-brand disabled:opacity-50"
                />
                {phase === "running" ? (
                  <button
                    onClick={stop}
                    className="rounded-lg border border-slate-600 bg-slate-800 px-6 py-2.5 text-sm font-medium text-slate-200 hover:bg-slate-700"
                  >
                    停止
                  </button>
                ) : (
                  <button
                    onClick={() => void runAnalysis()}
                    className="rounded-lg bg-brand px-6 py-2.5 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
                  >
                    开始分析
                  </button>
                )}
              </div>
              <p className="mt-2 text-xs text-slate-500">提示：支持 Ctrl + Enter 快捷触发</p>
            </div>

            {/* 状态 */}
            {(phase === "running" || phase === "done") && status && (
              <div className="mt-5 flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm text-slate-300">
                {phase === "running" ? (
                  <>
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" />
                    </span>
                    <span>{status}</span>
                    {currentCode && <span className="ml-2 text-xs text-slate-500">({currentCode})</span>}
                  </>
                ) : (
                  <span className="text-green-400">✓ {status}</span>
                )}
              </div>
            )}

            {/* 错误 */}
            {phase === "error" && errorMsg && (
              <div className="mt-5 rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-300">
                {errorMsg}
              </div>
            )}

            {/* 结果列表 */}
            {items.length > 0 && (
              <div className="mt-8">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-lg font-bold text-white">分析结果</h2>
                  <div className="flex items-center gap-4 text-sm">
                    <span className="text-slate-400">平均分</span>
                    <span className="text-xl font-bold text-brand">
                      {(items.reduce((s, i) => s + i.analysis.overall_score, 0) / items.length).toFixed(1)}
                    </span>
                  </div>
                </div>
                <div className="mb-6 flex h-8 w-full overflow-hidden rounded-lg border border-slate-800">
                  {items.map((item, idx) => (
                    <div
                      key={item.analysis.code + idx}
                      className="flex items-center justify-center overflow-hidden border-r border-slate-800 last:border-r-0 text-xs font-medium"
                      style={{
                        width: `${(item.analysis.overall_score / Math.max(...items.map((i) => i.analysis.overall_score), 1)) * (100 / items.length)}%`,
                        background: `linear-gradient(to top, rgba(220,38,38,0.85), rgba(220,38,38,0.45))`,
                      }}
                      title={`${item.analysis.name} ${item.analysis.overall_score.toFixed(1)}`}
                    >
                      {item.analysis.name}
                    </div>
                  ))}
                </div>
                <div className="grid gap-6 lg:grid-cols-2">
                  {items.map((item, idx) => (
                    <StockCard key={item.analysis.code + idx} analysis={item.analysis} info={infos[item.analysis.code]} />
                  ))}
                </div>
              </div>
            )}

            {/* 空状态 */}
            {phase === "idle" && (
              <div className="mt-12 text-center">
                <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-900 border border-slate-800 text-3xl">
                  📊
                </div>
                <p className="mt-4 text-sm text-slate-500">
                  输入 A 股代码，AI 将综合行情、K线趋势与最新新闻给出选股评分
                </p>
              </div>
            )}
          </>
        )}

        {tab === "market" && <MarketPanel onPick={handleMarketPick} />}

        {tab === "history" && <HistoryPanel refreshKey={historyRefresh} />}
      </main>

      <footer className="mx-auto max-w-6xl px-6 pb-8 text-center text-xs text-slate-600">
        数据来源：akshare（腾讯/新浪）· 分析模型：DeepSeek · 仅供研究学习，不构成投资建议
      </footer>
    </div>
  );
}
