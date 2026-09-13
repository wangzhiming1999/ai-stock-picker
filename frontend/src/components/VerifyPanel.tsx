import BacktestPanel from "./BacktestPanel";
import TacticBacktestPanel from "./TacticBacktestPanel";
import WinratePanel from "./WinratePanel";

/**
 * 选机会 · 验证 tab
 *
 * 回答「这套选股方法到底靠不靠谱」。回测与胜率原本散落在「选股扫描」里，
 * 和盘中监控、形态选股混在一屏；但它们的语义是「验证方法」而不是「选今天的票」，
 * 所以统一收到这里，跟推荐、扫描并列。
 */
export default function VerifyPanel() {
  return (
    <div className="space-y-5">
      <WinratePanel />
      <BacktestPanel />
      <TacticBacktestPanel />
    </div>
  );
}
