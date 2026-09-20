import { useState } from "react";
import { toast } from "sonner";
import { simTrade } from "../../api/client";
import Input from "../ui/Input";

/** 买卖弹窗 */
export default function TradeModal({
  side,
  initialCode,
  initialPrice,
  onClose,
  onDone,
}: {
  side: "buy" | "sell";
  initialCode: string;
  initialPrice?: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const [code, setCode] = useState(initialCode);
  const [shares, setShares] = useState("");
  const [price, setPrice] = useState(initialPrice ? initialPrice.toString() : "");
  const [priceAuto, setPriceAuto] = useState(true);
  const [busy, setBusy] = useState(false);
  const isBuy = side === "buy";
  const sharesNum = parseInt(shares) || 0;
  const priceNum = parseFloat(price) || null;

  const submit = async () => {
    if (!code || code.length !== 6 || !sharesNum) {
      toast.error("请填写代码与数量");
      return;
    }
    setBusy(true);
    try {
      await simTrade({ code, side, shares: sharesNum, price: priceAuto ? undefined : (priceNum ?? undefined) });
      toast.success(isBuy ? "模拟买入成功" : "模拟卖出成功", {
        description: `${code} ${sharesNum}股${priceAuto ? " @实时价" : `@${priceNum}`}`,
      });
      onDone();
      onClose();
    } catch (err) {
      const msg = (err as Error).message || "";
      if (/500|NetworkError|Failed to fetch|timeout/i.test(msg)) {
        toast.error("模拟盘后端暂不可用，请稍后重试");
      } else {
        toast.error(msg);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-xl border border-slate-700 bg-slate-900 p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <span className={`text-sm font-bold ${isBuy ? "text-red-400" : "text-green-400"}`}>
            {isBuy ? "模拟买入" : "模拟卖出"}
          </span>
          <button onClick={onClose} className="text-xs text-ink-faint hover:text-ink-soft">关闭</button>
        </div>
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-ink-faint">股票代码</span>
            <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6 位代码" disabled={!!initialCode} className="w-full rounded-lg bg-slate-800/70 px-3 py-1.5 text-sm" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-ink-faint">数量（股，100 的整数倍）</span>
            <Input value={shares} onChange={(e) => setShares(e.target.value.replace(/\D/g, ""))} type="number" placeholder="如 100" className="w-full rounded-lg bg-slate-800/70 px-3 py-1.5 text-sm" />
          </label>
          <label className="block">
            <span className="mb-1 flex items-center justify-between text-xs text-ink-faint">
              成交价
              <label className="flex items-center gap-1 text-ink-faint">
                <input type="checkbox" checked={priceAuto} onChange={(e) => setPriceAuto(e.target.checked)} className="h-3 w-3 accent-brand" />
                用实时价
              </label>
            </span>
            <Input value={price} onChange={(e) => setPrice(e.target.value)} type="number" step="0.01" disabled={priceAuto} placeholder={priceAuto ? "自动取当前价" : "如 12.50"} className="w-full rounded-lg bg-slate-800/70 px-3 py-1.5 text-sm" />
          </label>
          <div className="flex gap-2 pt-1">
            <button onClick={submit} disabled={busy} className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium text-white ${isBuy ? "bg-red-600 hover:bg-red-500" : "bg-green-600 hover:bg-green-500"}`}>
              {busy ? "提交中..." : isBuy ? "买入" : "卖出"}
            </button>
            <button onClick={onClose} className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-ink-muted hover:text-ink">取消</button>
          </div>
        </div>
      </div>
    </div>
  );
}
