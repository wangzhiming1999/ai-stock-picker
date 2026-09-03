import { useCallback, useEffect, useState } from "react";
import { Bell, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { addAlertRule, deleteAlertRule, fetchAlertRules } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { AlertRule, AlertType } from "../types";

const TYPE_LABEL: Record<AlertType, string> = {
  stop_loss: "止损（≤触发）",
  breakdown: "破位（≤触发）",
  price_target: "目标价（≥触发）",
};

export default function AlertRulesPanel() {
  const { user } = useAuth();
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [code, setCode] = useState("");
  const [type, setType] = useState<AlertType>("stop_loss");
  const [threshold, setThreshold] = useState("");
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      setRules(await fetchAlertRules());
    } catch (e) {
      toast.error("加载预警规则失败", { description: (e as Error).message });
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!user) return null;

  const submit = async () => {
    const c = code.trim();
    const t = parseFloat(threshold);
    if (!/^\d{6}$/.test(c)) {
      toast.warning("请输入 6 位股票代码");
      return;
    }
    if (!(t > 0 && t < 100000)) {
      toast.warning("阈值价格无效");
      return;
    }
    setAdding(true);
    try {
      await addAlertRule({ code: c, type, threshold: t });
      toast.success("已添加预警规则");
      setCode("");
      setThreshold("");
      await load();
    } catch (e) {
      toast.error("添加失败", { description: (e as Error).message });
    } finally {
      setAdding(false);
    }
  };

  const remove = async (id: number) => {
    try {
      await deleteAlertRule(id);
      setRules((r) => r.filter((x) => x.id !== id));
    } catch (e) {
      toast.error("删除失败", { description: (e as Error).message });
    }
  };

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-3 flex items-center gap-2">
        <Bell className="h-4 w-4 text-brand" />
        <h3 className="text-sm font-semibold text-slate-200">价格预警</h3>
        <span className="text-[11px] text-slate-500">持仓止损 / 目标价 / 破位，触发后铃铛提醒</span>
      </div>

      {/* 添加表单 */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          placeholder="代码"
          className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-brand focus:outline-none"
        />
        <select
          value={type}
          onChange={(e) => setType(e.target.value as AlertType)}
          className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-brand focus:outline-none"
        >
          {(Object.keys(TYPE_LABEL) as AlertType[]).map((k) => (
            <option key={k} value={k}>
              {TYPE_LABEL[k]}
            </option>
          ))}
        </select>
        <input
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
          type="number"
          step="any"
          min="0"
          placeholder="阈值价"
          className="w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-brand focus:outline-none"
        />
        <button
          onClick={() => void submit()}
          disabled={adding}
          className="flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-40"
        >
          <Plus className="h-3.5 w-3.5" />
          添加规则
        </button>
      </div>

      {/* 规则列表 */}
      {loading && rules.length === 0 ? (
        <div className="text-xs text-slate-500">加载中...</div>
      ) : rules.length === 0 ? (
        <div className="text-xs text-slate-500">暂无规则。添加后，现价到达阈值会推送到上方铃铛。</div>
      ) : (
        <div className="space-y-1.5">
          {rules.map((r) => (
            <div key={r.id} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-mono font-semibold text-slate-200">{r.code}</span>
                <span className="text-slate-400">{r.name || "-"}</span>
                <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">{TYPE_LABEL[r.type]}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-slate-300">阈值 {r.threshold}</span>
                <button onClick={() => void remove(r.id)} className="rounded p-1 text-slate-600 hover:bg-red-950/40 hover:text-red-400" title="删除">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
