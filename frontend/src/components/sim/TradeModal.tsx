import { useState } from "react";
import { toast } from "sonner";
import { simTrade } from "../../api/client";
import Input from "../ui/Input";
import { slippagePct } from "./shared";

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
  // 预期价格（计划成交价）只对买入有意义：卖出没有「建仓计划价」这个语义。
  const [expected, setExpected] = useState(initialPrice ? initialPrice.toString() : "");
  const [busy, setBusy] = useState(false);
  const isBuy = side === "buy";
  const sharesNum = parseInt(shares) || 0;
  const priceNum = parseFloat(price) || null;
  const expectedNum = parseFloat(expected) || null;
  // 计划价 vs 现价的偏差：只是给用户一个「按现在这个价成交会偏多少」的即时读数，
  // 真正的记录与事后核对在成交流水（TradesList）里。
  const previewSlip =
    priceNum != null ? slippagePct({ price: priceNum, expected_price: expectedNum }) : null;

  const submit = async () => {
    if (!code || code.length !== 6 || !sharesNum) {
      toast.error("请填写代码与数量");
      return;
    }
    setBusy(true);
    try {
      await simTrade({
        code,
        side,
        shares: sharesNum,
        price: priceAuto ? undefined : (priceNum ?? undefined),
        expected_price: isBuy ? (expectedNum ?? undefined) : undefined,
      });
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
      <div className="w-full max-w-sm rounded-xl border border-surface-line bg-surface-panel p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <span className={`text-body font-bold ${isBuy ? "text-red-400" : "text-green-400"}`}>
            {isBuy ? "模拟买入" : "模拟卖出"}
          </span>
          <button onClick={onClose} className="text-meta text-ink-muted hover:text-ink-soft">关闭</button>
        </div>
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-meta text-ink-muted">股票代码</span>
            <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6 位代码" disabled={!!initialCode} className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
          </label>
          <label className="block">
            <span className="mb-1 block text-meta text-ink-muted">数量（股，100 的整数倍）</span>
            <Input value={shares} onChange={(e) => setShares(e.target.value.replace(/\D/g, ""))} type="number" placeholder="如 100" className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
          </label>
          <label className="block">
            <span className="mb-1 flex items-center justify-between text-meta text-ink-muted">
              成交价
              <label className="flex items-center gap-1 text-ink-muted">
                <input type="checkbox" checked={priceAuto} onChange={(e) => setPriceAuto(e.target.checked)} className="h-3 w-3 accent-brand" />
                用实时价
              </label>
            </span>
            <Input value={price} onChange={(e) => setPrice(e.target.value)} type="number" step="0.01" disabled={priceAuto} placeholder={priceAuto ? "自动取当前价" : "如 12.50"} className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
          </label>
          {isBuy && (
            <label className="block">
              <span className="mb-1 block text-meta text-ink-muted">
                预期价格（选填 · 你本来打算在什么价成交）
              </span>
              <Input
                value={expected}
                onChange={(e) => setExpected(e.target.value)}
                type="number"
                step="0.01"
                placeholder="如 12.30（打板价 / 回踩位）"
                className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body"
              />
              <span className="mt-1 block text-meta text-ink-soft">
                只用于事后看「预期 vs 实际成交」差多少，<b className="text-ink-muted">不参与盈亏计算</b>
                {previewSlip != null && (
                  <>
                    。若按当前价成交，比计划价{" "}
                    <span className="text-ink-soft">
                      {previewSlip >= 0 ? "贵" : "便宜"} {Math.abs(previewSlip).toFixed(2)}%
                    </span>
                  </>
                )}
              </span>
            </label>
          )}
          <div className="flex gap-2 pt-1">
            <button onClick={submit} disabled={busy} className={`flex-1 rounded-lg px-4 py-2 text-body font-medium text-white ${isBuy ? "bg-red-600 hover:bg-red-500" : "bg-green-600 hover:bg-green-500"}`}>
              {busy ? "提交中..." : isBuy ? "买入" : "卖出"}
            </button>
            <button onClick={onClose} className="rounded-lg border border-surface-line-strong px-4 py-2 text-body text-ink-muted hover:text-ink">取消</button>
          </div>
        </div>
      </div>
    </div>
  );
}
