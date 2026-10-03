import { Suspense, useEffect, useState } from "react";
import { Crosshair, Lightbulb, ScanSearch } from "lucide-react";
import { subNavFor } from "../lib/subnav";
import { useSubPage } from "../lib/useSubPage";
import type { NavJump } from "../lib/featureMap";
import { lazyRetry } from "../lib/lazyRetry";
import { STACK } from "../lib/ui";
import PanelSkeleton from "./ui/PanelSkeleton";
import SubNav from "./ui/SubNav";
import PageHeader from "./ui/PageHeader";
import CandidatePoolBar from "./CandidatePoolBar";
import { mergeCandidateCodes } from "../lib/candidatePool";

const DecisionCenter = lazyRetry(() => import("./DecisionCenter"));
const ScanCenter = lazyRetry(() => import("./ScanCenter"));
const CANDIDATE_POOL_KEY = "opportunity:candidate-pool";

const SUB_ICON = {
  decision: Crosshair,
  scan: ScanSearch,
} as const;
const SUB_KEYS = {
  decision: "decision",
  scan: "scan",
} as const;

interface Props {
  onPick: (codes: string[]) => void;
  /** 从功能地图跳进来的落点 */
  jump?: NavJump | null;
}

/**
 * 选机会 · 「今天买什么」
 *
 * 四个子页是四条互不相同的**票源**：
 *   推荐（模型打分）→ 决策（三维打分：资金 / 趋势 / 活跃度）→
 *   扫描（策略 / 异动 / 自定义条件）→ 形态（K 线量价条件命中）
 *
 * ## 为什么「决策」与「推荐」并存
 * 两者回答的不是同一个问题：推荐偏**静态质地**（模型综合打分），
 * 决策偏**当日行为**（钱在往哪去、谁跟着走）。维度不同、候选池不同，不可相互替代。
 *
 * ## 重构改了两处
 * 1. **「验证」搬走了**（去了「研究」）。它回答的是另一个问题：
 *    这几个子页都在给「今天的票」，验证在给「这套方法可不可信」。
 * 2. **「实战形态」从扫描页里提了出来**。它原本是扫描页的第四个视图 ——
 *    要点进「选机会」→ 再点「扫描」→ 再点「看实战形态」，深度 3 且没有回头路。
 *
 * ⚠️ 本页所有产出都是**候选 / 读数**，不是指令。子页内的免责说明不要为了排版干净删掉。
 */
export default function OpportunityPanel({ onPick, jump }: Props) {
  const [candidateCodes, setCandidateCodes] = useState<string[]>(() => {
    try {
      const stored = JSON.parse(sessionStorage.getItem(CANDIDATE_POOL_KEY) ?? "[]");
      return Array.isArray(stored) ? mergeCandidateCodes([], stored.filter((item): item is string => typeof item === "string")) : [];
    } catch {
      return [];
    }
  });
  const { sub, changeSub, isVisible, isMounted } = useSubPage("opportunity", jump, SUB_KEYS.decision);
  const items = subNavFor("opportunity").map((s) => ({
    ...s,
    icon: SUB_ICON[s.key as keyof typeof SUB_ICON],
  }));
  const pickAndRemember = (codes: string[]) => {
    setCandidateCodes((current) => mergeCandidateCodes(current, codes));
    onPick(codes);
  };

  useEffect(() => {
    sessionStorage.setItem(CANDIDATE_POOL_KEY, JSON.stringify(candidateCodes));
  }, [candidateCodes]);

  return (
    <div className={STACK}>
      <PageHeader icon={Lightbulb} title="选机会" />

      <SubNav id="opportunity" items={items} value={sub} onChange={changeSub} />

      <CandidatePoolBar
        codes={candidateCodes}
        onAdd={(codes) => setCandidateCodes((current) => mergeCandidateCodes(current, codes))}
        onClear={() => setCandidateCodes([])}
      />

      {isMounted(SUB_KEYS.decision) && (
        <div className={isVisible(SUB_KEYS.decision)}>
          <Suspense fallback={<PanelSkeleton label="正在加载精选决策" />}>
            <DecisionCenter onPick={pickAndRemember} />
          </Suspense>
        </div>
      )}

      {isMounted(SUB_KEYS.scan) && (
        <div className={isVisible(SUB_KEYS.scan)}>
          <Suspense fallback={<PanelSkeleton label="正在加载扫描中心" />}>
            <ScanCenter onPick={pickAndRemember} candidateCodes={candidateCodes} />
          </Suspense>
        </div>
      )}
    </div>
  );
}
