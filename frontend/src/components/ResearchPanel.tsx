import { Microscope } from "lucide-react";
import type { NavJump } from "../lib/featureMap";
import { STACK } from "../lib/ui";
import PageHeader from "./ui/PageHeader";
import VerificationCenter from "./VerificationCenter";

interface Props {
  /** 从功能地图跳进来的落点 */
  jump?: NavJump | null;
}

/**
 * 研究 · 「这些方法靠不靠谱」
 *
 * ## 为什么独立成一级页（2026-09-20 重构）
 * 此前「验证」是「选机会」的第三个子页，和「推荐」「扫描」并列。语义上不对：
 * 推荐 / 扫描回答「今天买什么」，这里回答「这套方法本身行不行」——是**回头看**。
 * 混在一起时，用户找「回测」「胜率」会先去翻选股页，翻不到就以为没有。
 *
 * ## 本页的排版纪律
 * 顶部**只写一次**「口径不可比」声明。本页同时出现四个都叫「胜率 / 命中率」的数字
 * （大盘单日命中、推荐 T+1、策略调仓期、形态 N 日前向），它们的标的 / 持有期 /
 * 分类数 / 有无基准全不同，**不可比较、不可相加**。分散到各面板各写一遍的话，
 * 用户会以为那是同一件事的四个读数。
 *
 * 先看证据台账，再看各口径自己的数字 —— 顺序是刻意的：
 * 先知道「哪些能动手」（当前 0 条），后面的数字才不会被误读成「能用」。
 */
export default function ResearchPanel({ jump: _jump }: Props) {
  return (
    <div className={STACK}>
      <PageHeader icon={Microscope} title="研究" />
      <VerificationCenter />
    </div>
  );
}
