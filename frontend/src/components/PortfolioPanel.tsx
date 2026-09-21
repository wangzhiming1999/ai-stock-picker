import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  addHolding,
  fetchHoldings,
  fetchPortfolioAdvice,
  fetchPortfolioProfile,
  removeHolding,
  updatePortfolioProfile,
} from "../api/client";
import StockSearchInput from "./StockSearchInput";
import ImportHoldingsModal from "./ImportHoldingsModal";
import AlertRulesPanel from "./AlertRulesPanel";
import type { HoldingsData, PortfolioAdvice, UserProfile } from "../types";
import { useAuth } from "../auth/AuthContext";
import { fmtPct, safeNumber } from "../lib/safe";
import { actionTone, pnlTone, scoreChip } from "../lib/tone";
import Input from "./ui/Input";
import Button from "./ui/Button";
import StatTile from "./ui/StatTile";
import Table, { Th } from "./ui/Table";
import Panel from "./ui/Panel";
// CARD 仍有一处正当用途：未登录时的门禁卡（不是面板，没有头部）
import { CARD, CELL } from "../lib/ui";

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
  const [showImport, setShowImport] = useState(false);

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
      <div className={`${CARD} text-body text-ink-muted`}>
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

  const del = async (id: number, name: string) => {
    if (!window.confirm(`确认删除持仓「${name || id}」？此操作不可恢复。`)) return;
    try {
      await removeHolding(id);
      toast.success(`已删除持仓 ${name || id}`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
      toast.error("删除失败", { description: (e as Error).message });
    }
  };

  return (
    <Panel
      title="我的持仓"
      desc="按用户存储，建议根据你的风险等级生成"
      actions={
        <>
          <button
            onClick={() => setShowImport(true)}
            className="rounded-lg border border-surface-line-strong px-3 py-1.5 text-meta font-medium text-ink-soft hover:border-surface-line-hover hover:text-white"
            title="从券商 App 截图或文本批量导入"
          >
            截图导入
          </button>
          <Button variant="primary" size="md" onClick={() => setShowAdd(true)}>
            + 添加持仓
          </Button>
        </>
      }
    >
      {err && <div className="mb-3 rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">{err}</div>}
      {loading && <div className="p-3 text-body text-ink-soft">加载中...</div>}

      {/* 风险等级 */}
      {profile && (
        <div className="mb-4">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-meta font-semibold text-ink-muted">风险等级</span>
            <label className="flex items-center gap-2 text-meta text-ink-muted">
              总资金
              <Input
                type="number"
                defaultValue={profile.total_capital}
                onBlur={(e) => {
                  const v = parseFloat(e.target.value);
                  if (!(v > 0)) return;
                  void updatePortfolioProfile({ risk_level: profile.risk_level, total_capital: v })
                    .then((p) => {
                      setProfile(p);
                      toast.success("总资金已更新");
                    })
                    .catch((err) => toast.error("总资金保存失败", { description: (err as Error).message }));
                }}
                className="w-24 bg-surface-inset px-2 py-1 text-meta"
              />
            </label>
          </div>
          <div className="flex gap-2">
            {RISK_LEVELS.map((r) => (
              <button
                key={r.name}
                onClick={() => void setRisk(r.name)}
                title={r.desc}
                className={`flex-1 rounded-lg border px-3 py-1.5 text-meta transition-colors ${
                  profile.risk_level === r.name ? "border-brand bg-brand/15 text-white" : "border-surface-line text-ink-muted hover:border-surface-line-hover"
                }`}
              >
                {r.name}
              </button>
            ))}
          </div>
          {advice && <p className="mt-1.5 text-meta text-ink-soft">{advice.risk_desc}</p>}
        </div>
      )}

      {/* 添加表单 */}
      {showAdd && (
        <div className="mb-4 rounded-lg border border-surface-line bg-surface-inset/70 p-4">
          <div className="mb-3 text-meta font-semibold text-ink-soft">添加持仓</div>
          <div className="flex flex-col gap-3">
            <StockSearchInput
              value={searchText}
              onChange={(v) => setSearchText(v)}
              onPickCode={(code) => setAddCode(code)}
            />
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-meta text-ink-muted">成本价</span>
                <Input value={costPrice} onChange={(e) => setCostPrice(e.target.value)} type="number" step="0.01" placeholder="如 1250.00" className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
              </label>
              <label className="block">
                <span className="mb-1 block text-meta text-ink-muted">数量(股)</span>
                <Input value={shares} onChange={(e) => setShares(e.target.value)} type="number" placeholder="如 100" className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
              </label>
            </div>
            <label className="block">
              <span className="mb-1 block text-meta text-ink-muted">备注（可选）</span>
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="如：核心持仓" className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
            </label>
            <div className="flex gap-2">
              <Button variant="primary" size="md" onClick={() => void submitAdd()}>
                保存
              </Button>
              <button onClick={() => setShowAdd(false)} className="rounded-lg border border-surface-line-strong px-4 py-1.5 text-meta text-ink-muted hover:text-ink">
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 汇总 */}
      {holdings && holdings.holdings.length > 0 && (
        <div className="mb-4 grid grid-cols-3 gap-2">
          <StatTile value={safeNumber(holdings.total_value).toLocaleString()} label="市值" />
          <StatTile
            value={<>{holdings.total_pnl >= 0 ? "+" : ""}{safeNumber(holdings.total_pnl).toLocaleString()}</>}
            label="总盈亏"
            valueClass={pnlTone(holdings.total_pnl)}
          />
          <StatTile value={fmtPct(holdings.total_pnl_pct)} label="盈亏率" valueClass={pnlTone(holdings.total_pnl_pct)} />
        </div>
      )}

      {/* 持仓列表 */}
      {holdings && holdings.holdings.length > 0 ? (
        <Table label="持仓列表" maxHeight="none" head={
          <tr>
            <Th>股票</Th>
            <Th align="right">现价</Th>
            <Th align="right">成本</Th>
            <Th align="right">数量</Th>
            <Th align="right">盈亏</Th>
            <Th>技术信号</Th>
            <Th />
          </tr>
        }>
              {holdings.holdings.map((h) => (
                <tr key={h.id} className="border-t border-surface-line-soft">
                  <td className={CELL}>
                    <div className="font-medium text-ink">{h.name || h.code}</div>
                    <div className="text-meta text-ink-muted">{h.code}</div>
                  </td>
                  <td className={`${CELL} text-right text-ink-soft`}>{h.current_price?.toFixed(2) ?? "-"}</td>
                  <td className={`${CELL} text-right text-ink-muted`}>{h.cost_price.toFixed(2)}</td>
                  <td className={`${CELL} text-right text-ink-muted`}>{h.shares}</td>
                  <td className={`${CELL} text-right ${pnlTone(h.pnl_pct)}`}>
                    {h.pnl_pct != null ? `${h.pnl_pct >= 0 ? "+" : ""}${h.pnl_pct.toFixed(2)}%` : "-"}
                  </td>
                  <td className={CELL}>
                    {h.signal ? (
                      <span className={`rounded-md px-1.5 py-0.5 text-meta ${scoreChip(h.signal.strength)}`}>
                        强度 {h.signal.strength.toFixed(1)}
                      </span>
                    ) : (
                      <span className="text-ink-faint">-</span>
                    )}
                  </td>
                  <td className={CELL}>
                    <button onClick={() => void del(h.id, h.name)} className="text-meta text-ink-muted hover:text-red-400" title="删除">
                      删除
                    </button>
                  </td>
                </tr>
              ))}
          </Table>
      ) : (
        <div className="rounded-lg bg-surface-inset/40 p-4 text-center text-body text-ink-soft">
          暂无持仓，点击"添加持仓"录入你的股票
        </div>
      )}

      {/* 持仓建议 */}
      {advice && advice.holdings_advice.length > 0 && (
        <div className="mt-5 border-t border-surface-line pt-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-meta font-semibold text-ink-muted">持仓建议（{advice.risk_level}型）</span>
            <button onClick={() => void load()} className="text-meta text-ink-muted hover:text-ink-soft">
              刷新建议
            </button>
          </div>
          <div className="mb-2 space-y-1 rounded-lg bg-surface-inset/40 p-3">
            {advice.portfolio_tips.map((t, i) => (
              <p key={i} className="text-meta text-ink-muted">• {t}</p>
            ))}
          </div>
          <div className="space-y-2">
            {advice.holdings_advice.map((a) => (
              <div key={a.code} className="rounded-xl border border-surface-line p-3">
                <div className="flex items-center justify-between">
                  <span className="text-body font-medium text-ink">{a.name} <span className="text-meta text-ink-muted">{a.code}</span></span>
                  <span className={`text-meta font-semibold ${actionTone(a.action)}`}>{a.action}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-meta text-ink-soft">
                  <span>仓位 {a.position_pct}%</span>
                  {a.support != null && <span>支撑 {a.support}</span>}
                  {a.resistance != null && <span>压力 {a.resistance}</span>}
                  {a.stop_loss != null && <span>止损 {a.stop_loss}</span>}
                  <span>风报比 {a.rr_ratio}</span>
                </div>
                <ul className="mt-1.5 space-y-0.5">
                  {a.tips.map((t, i) => (
                    <li key={i} className="text-meta text-ink-muted">• {t}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      <ImportHoldingsModal open={showImport} onClose={() => setShowImport(false)} onImported={() => void load()} />

      <AlertRulesPanel />
    </Panel>
  );
}
