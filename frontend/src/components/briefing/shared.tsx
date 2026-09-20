import type { ReactNode } from "react";
import { DIVIDER, SECTION } from "../../lib/ui";

/** ③ 分区：不套容器，只用一条分隔线 + 留白切分主卡内部主题 */
export function Section({
  icon,
  title,
  hint,
  children,
}: {
  icon: ReactNode;
  title: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={`mt-4 ${DIVIDER} pt-4`}>
      <div className={SECTION}>
        {icon}
        {title}
        {hint}
      </div>
      <div className="mt-2.5">{children}</div>
    </div>
  );
}

/** 模拟盘失败统一降级提示：500/网络错误给友好文案，其余透传后端消息 */
export function simErrMsg(e: unknown): string {
  const msg = (e as Error)?.message || "";
  if (/500|NetworkError|Failed to fetch|timeout/i.test(msg)) return "模拟盘后端暂不可用，请稍后重试";
  return msg;
}

/** 算法推导标识：不预判确定性，整卡只出现一次（放在卡片页脚），避免每个数字都挂标签 */
export function AlgoTag() {
  return (
    <span className="text-ink-faint" title="买点 / 止损 / 手数由技术位规则推导，非确定性建议">
      算法推导
    </span>
  );
}

export function Money({ v }: { v?: number | null }) {
  if (v == null) return <span className="text-ink-faint">—</span>;
  return <span>{v.toFixed(2)}</span>;
}
