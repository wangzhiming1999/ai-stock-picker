import { useRef } from "react";
import { Activity, TrendingDown } from "lucide-react";
import { CARD, STACK, TEXT } from "../../lib/ui";
import { useBlockFocus } from "../../lib/blockFocus";
import LimitUpBar from "../LimitUpBar";
import LimitDownBar from "../LimitDownBar";

/**
 * 涨跌停 · 选机会下的市场情绪大模块
 *
 * 把原本全局常驻的两条温度带（涨停梯队 / 跌停观察）合并到一个子页里展示。
 * 这里不是买点列表，而是「读市场」：涨停侧给连板梯队与次日溢价读数，
 * 跌停侧给抛压分布与修复回测（负期望，只读不推）。
 *
 * 两块默认展开，避免用户点进来还要再点一次才能看到内容；
 * 功能地图跳转时通过 blockFocus 滚动到对应区块。
 */
export default function LimitUpDownPanel() {
  const upRef = useRef<HTMLDivElement>(null);
  const downRef = useRef<HTMLDivElement>(null);

  useBlockFocus("limitup", () => {
    upRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  useBlockFocus("limitdown", () => {
    downRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  return (
    <div className={STACK}>
      <section className={CARD}>
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-brand-light" aria-hidden />
          <h2 className={TEXT.title}>涨停梯队</h2>
        </div>
        <p className="mt-1 text-meta text-ink-muted">
          涨停家数、连板结构、炸板率、主线板块与次日溢价读数；涨停是市场情绪温度，不是买点。
        </p>
        <div id="limitup" ref={upRef} className="mt-4">
          <LimitUpBar defaultOpen embedded />
        </div>
      </section>

      <section className={CARD}>
        <div className="flex items-center gap-2">
          <TrendingDown className="h-4 w-4 text-brand-light" aria-hidden />
          <h2 className={TEXT.title}>跌停观察层</h2>
        </div>
        <p className="mt-1 text-meta text-ink-muted">
          跌停家数、连跌结构、板块抛压与次日竞价修复回测；跌停次日抄底实测为负期望，只读不推。
        </p>
        <div id="limitdown" ref={downRef} className="mt-4">
          <LimitDownBar defaultOpen embedded />
        </div>
      </section>
    </div>
  );
}
