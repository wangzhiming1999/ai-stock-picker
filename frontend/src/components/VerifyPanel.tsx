import BacktestPanel from "./BacktestPanel";
import EvidenceLedgerPanel from "./EvidenceLedgerPanel";
import TacticBacktestPanel from "./TacticBacktestPanel";
import WinratePanel from "./WinratePanel";
import { CaliberIncomparabilityNote } from "./CaliberNote";

/**
 * 选机会 · 验证 tab
 *
 * 回答「这套选股方法到底靠不靠谱」。回测与胜率原本散落在「选股扫描」里，
 * 和盘中监控、形态选股混在一屏；但它们的语义是「验证方法」而不是「选今天的票」，
 * 所以统一收到这里，跟推荐、扫描并列。
 *
 * ⚠️ 本屏同时出现 4 个都叫「胜率 / 命中率」的数字（大盘单日命中、推荐 T+1、
 * 策略调仓期、形态 N 日前向）。它们标的 / 持有期 / 分类数 / 有无基准全不同，
 * **不可比较**。因此不可比声明统一放在本屏顶部只写一次，各面板各自展示自己的口径。
 *
 * 顶部先放「证据台账」：它把每条口径的可信度与样本出处汇总成一张表，
 * 用户先知道「哪些能动手」（当前 0 条），再往下看各口径自己的数字才不会误读。
 */
export default function VerifyPanel() {
  return (
    <div className="space-y-5">
      <CaliberIncomparabilityNote />
      <EvidenceLedgerPanel />
      <WinratePanel />
      <BacktestPanel />
      <TacticBacktestPanel />
    </div>
  );
}
