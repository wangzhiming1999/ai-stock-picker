import { useCallback, useEffect, useState } from "react";
import {
  addHolding,
  fetchHoldings,
  fetchPortfolioAdvice,
  fetchPortfolioProfile,
  removeHolding,
  updatePortfolioProfile,
} from "../api/client";
import StockSearchInput from "./StockSearchInput";
import type { HoldingsData, PortfolioAdvice, UserProfile } from "../types";
import { useAuth } from "../auth/AuthContext";
import { fmtPct, safeNumber } from "../lib/safe";

const RISK_LEVELS = [
  { name: "保守", desc: "低波动优先，严格控制仓位" },
  { name: "稳健", desc: "攻守平衡，分散配置" },
  { name: "进取", desc: "适度激进，可承担一定波动" },
  { name: "激进", desc: "高弹性追求，容忍较大回撤" },
];

export default function PortfolioPanel() {
  const { user } = useAuth();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [holdings, setHoldings] = useState<HoldingsData | null>(null);
  const [advice, setAdvice] = useState<PortfolioAdvice | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [showAdd, setShowAdd] = useState(false);

  // 添加表单
  const [searchText, setSearchText] = useState("");
  const [addCode, setAddCode] = useState("");
  const [costPrice, setCostPrice] = useState("");
  const [shares, setShares] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const [p, h, a] = await Promise.all([
        fetchPortfolioProfile(),
        fetchHoldings(),
        fetchPortfolioAdvice().catch(() => null),
      ]);
      setProfile(p);
      setHoldings(h);
      setAdvice(a);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 text-sm text-slate-400">
        请先登录后使用持仓管理（持仓数据按用户存储）。
      </div>
    );
  }

  const setRisk = async (level: string) => {
    try {
      const p = await updatePortfolioProfile({ risk_level: level, total_capital: profile?.total_capital });
      setProfile(p);
      const a = await fetchPortfolioAdvice().catch(() => null);
      setAdvice(a);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const submitAdd = async () => {
    setErr("");
    if (!addCode || !costPrice || !shares) {
      setErr("请填写股票代码、成本价和数量");
      return;
    }
    try {
      await addHolding({
        code: addCode,
        cost_price: parseFloat(costPrice),
        shares: parseInt(shares),
        note: note || undefined,
      });
      setShowAdd(false);
      setSearchText("");
      setAddCode("");
      setCostPrice("");
      setShares("");
      setNote("");
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const del = async (id: number) => {
    try {
      await removeHolding(id);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const pnlColor = (v: number | null | undefined) => (v == null ? "text-slate-500" : v >= 0 ? "text-green-400" : "text-red-400");
  const actionColor = (a: string) => (a.includes("减仓") ? "text-red-400" : a.includes("加仓") ? "text-green-400" : "text-yellow-400");

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">我的持仓</h3>
          <p className="mt-0.5 text-[11px] text-slate-500">按用户存储，建议根据你的风险等级生成</p>
        </div>
        <button onClick={() => setShowAdd(true)} className="rounded-lg bg-brand px-4 py-1.5 text-xs font-medium text-white hover:bg-brand-dark">
          + 添加持仓
        </button>
      </div>

      {err && <div className="mb-3 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}
      {loading && <div className="p-3 text-sm text-slate-500">加载中...</div>}

      {/* 风险等级 */}
      {profile && (
        <div className="mb-4">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400">风险等级</span>
            <label className="flex items-center gap-2 text-[11px] text-slate-500">
              总资金
              <input
                type="number"
                defaultValue={profile.total_capital}
                onBlur={(e) => {
                  const v = parseFloat(e.target.value);
                  if (v > 0) void updatePortfolioProfile({ risk_level: profile.risk_level, total_capital: v }).then(setProfile);
                }}
                className="w-24 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200"
              />
            </label>
          </div>
          <div className="flex gap-2">
            {RISK_LEVELS.map((r) => (
              <button
                key={r.name}
                onClick={() => void setRisk(r.name)}
                title={r.desc}
                className={`flex-1 rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                  profile.risk_level === r.name ? "border-brand bg-brand/15 text-white" : "border-slate-700 text-slate-400 hover:border-slate-500"
                }`}
              >
                {r.name}
              </button>
            ))}
          </div>
          {advice && <p className="mt-1.5 text-[11px] text-slate-500">{advice.risk_desc}</p>}
        </div>
      )}

      {/* 添加表单 */}
      {showAdd && (
        <div className="mb-4 rounded-lg border border-slate-700 bg-slate-800/50 p-4">
          <div className="mb-3 text-xs font-semibold text-slate-300">添加持仓</div>
          <div className="flex flex-col gap-3">
            <StockSearchInput
              value={searchText}
              onChange={(v) => setSearchText(v)}
              onPickCode={(code) => setAddCode(code)}
            />
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-xs text-slate-500">成本价</span>
                <input value={costPrice} onChange={(e) => setCostPrice(e.target.value)} type="number" step="0.01" placeholder="如 1250.00" className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm" />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-slate-500">数量(股)</span>
                <input value={shares} onChange={(e) => setShares(e.target.value)} type="number" placeholder="如 100" className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm" />
              </label>
            </div>
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">备注（可选）</span>
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="如：核心持仓" className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm" />
            </label>
            <div className="flex gap-2">
              <button onClick={() => void submitAdd()} className="rounded-lg bg-brand px-4 py-1.5 text-xs font-medium text-white hover:bg-brand-dark">
                保存
              </button>
              <button onClick={() => setShowAdd(false)} className="rounded-lg border border-slate-600 px-4 py-1.5 text-xs text-slate-400 hover:text-slate-200">
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 汇总 */}
      {holdings && holdings.holdings.length > 0 && (
        <div className="mb-4 grid grid-cols-3 gap-2">
          <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
            <div className="text-lg font-bold text-slate-200">{safeNumber(holdings.total_value).toLocaleString()}</div>
            <div className="text-[11px] text-slate-500">市值</div>
          </div>
          <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
            <div className={`text-lg font-bold ${pnlColor(holdings.total_pnl)}`}>
              {holdings.total_pnl >= 0 ? "+" : ""}
              {safeNumber(holdings.total_pnl).toLocaleString()}
            </div>
            <div className="text-[11px] text-slate-500">总盈亏</div>
          </div>
          <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
            <div className={`text-lg font-bold ${pnlColor(holdings.total_pnl_pct)}`}>
              {fmtPct(holdings.total_pnl_pct)}
            </div>
            <div className="text-[11px] text-slate-500">盈亏率</div>
          </div>
        </div>
      )}

      {/* 持仓列表 */}
      {holdings && holdings.holdings.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-400">
              <tr>
                <th className="px-2 py-2">股票</th>
                <th className="px-2 py-2 text-right">现价</th>
                <th className="px-2 py-2 text-right">成本</th>
                <th className="px-2 py-2 text-right">数量</th>
                <th className="px-2 py-2 text-right">盈亏</th>
                <th className="px-2 py-2">技术信号</th>
                <th className="px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {holdings.holdings.map((h) => (
                <tr key={h.id} className="border-t border-slate-800/60">
                  <td className="px-2 py-2">
                    <div className="font-medium text-slate-200">{h.name || h.code}</div>
                    <div className="text-[11px] text-slate-500">{h.code}</div>
                  </td>
                  <td className="px-2 py-2 text-right text-slate-300">{h.current_price?.toFixed(2) ?? "-"}</td>
                  <td className="px-2 py-2 text-right text-slate-400">{h.cost_price.toFixed(2)}</td>
                  <td className="px-2 py-2 text-right text-slate-400">{h.shares}</td>
                  <td className={`px-2 py-2 text-right ${pnlColor(h.pnl_pct)}`}>
                    {h.pnl_pct != null ? `${h.pnl_pct >= 0 ? "+" : ""}${h.pnl_pct.toFixed(2)}%` : "-"}
                  </td>
                  <td className="px-2 py-2">
                    {h.signal ? (
                      <span className={`rounded px-1.5 py-0.5 text-[11px] ${h.signal.strength >= 6 ? "bg-green-900/40 text-green-300" : h.signal.strength >= 4 ? "bg-yellow-900/40 text-yellow-300" : "bg-red-900/40 text-red-300"}`}>
                        强度 {h.signal.strength.toFixed(1)}
                      </span>
                    ) : (
                      <span className="text-slate-600">-</span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <button onClick={() => void del(h.id)} className="text-xs text-slate-500 hover:text-red-400" title="删除">
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg bg-slate-800/40 p-4 text-center text-sm text-slate-500">
          暂无持仓，点击"添加持仓"录入你的股票
        </div>
      )}

      {/* 持仓建议 */}
      {advice && advice.holdings_advice.length > 0 && (
        <div className="mt-5 border-t border-slate-800 pt-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400">持仓建议（{advice.risk_level}型）</span>
            <button onClick={() => void load()} className="text-[11px] text-slate-500 hover:text-slate-300">
              刷新建议
            </button>
          </div>
          <div className="mb-2 space-y-1 rounded-lg bg-slate-800/40 p-3">
            {advice.portfolio_tips.map((t, i) => (
              <p key={i} className="text-xs text-slate-400">• {t}</p>
            ))}
          </div>
          <div className="space-y-2">
            {advice.holdings_advice.map((a) => (
              <div key={a.code} className="rounded-lg border border-slate-800 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-200">{a.name} <span className="text-xs text-slate-500">{a.code}</span></span>
                  <span className={`text-xs font-semibold ${actionColor(a.action)}`}>{a.action}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-500">
                  <span>仓位 {a.position_pct}%</span>
                  {a.support != null && <span>支撑 {a.support}</span>}
                  {a.resistance != null && <span>压力 {a.resistance}</span>}
                  {a.stop_loss != null && <span>止损 {a.stop_loss}</span>}
                  <span>风报比 {a.rr_ratio}</span>
                </div>
                <ul className="mt-1.5 space-y-0.5">
                  {a.tips.map((t, i) => (
                    <li key={i} className="text-xs text-slate-400">• {t}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
