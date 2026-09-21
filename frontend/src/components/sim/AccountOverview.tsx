import type { SimAccount } from "../../types";
import { fmtPct, safeNumber } from "../../lib/safe";
import StatTile from "../ui/StatTile";
import { pnlTone } from "../../lib/tone";

/** 虚拟资金总览 + 统计格行。
 *
 * 模拟盘是**虚拟资金记账**，不是真实持仓 —— 这里的「总资产/盈亏」只反映模拟账户，
 * 不要写成真实交易。marketValue 由宿主按持仓聚合算出后下传（缺持仓时退回账户层市值）。
 */
export default function AccountOverview({
  account,
  marketValue,
}: {
  account: SimAccount;
  marketValue: number;
}) {
  return (
    <>
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile value={safeNumber(account.total_value).toLocaleString()} label="总资产" />
        <StatTile value={safeNumber(account.cash).toLocaleString()} label="可用现金" />
        <StatTile
          value={account.total_pnl != null ? `${account.total_pnl >= 0 ? "+" : ""}${safeNumber(account.total_pnl).toLocaleString()}` : "-"}
          label="总盈亏"
          valueClass={pnlTone(account.total_pnl)}
        />
        <StatTile value={fmtPct(account.total_pnl_pct)} label="盈亏率" valueClass={pnlTone(account.total_pnl_pct)} />
      </div>
      <div className="mb-3 flex gap-4 text-meta text-ink-muted">
        <span>已实现盈亏 <span className={pnlTone(account.realized_pnl)}>{account.realized_pnl >= 0 ? "+" : ""}{safeNumber(account.realized_pnl)}</span></span>
        <span>未实现盈亏 <span className={pnlTone(account.unrealized_pnl)}>{account.unrealized_pnl >= 0 ? "+" : ""}{safeNumber(account.unrealized_pnl)}</span></span>
        <span>持仓市值 <span className="text-ink-soft">{safeNumber(marketValue).toLocaleString()}</span></span>
      </div>
    </>
  );
}
