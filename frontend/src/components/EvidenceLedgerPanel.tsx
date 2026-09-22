import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { fetchEvidenceLedger } from "../api/client";
import { DIVIDER, SUB_QUIET, TEXT } from "../lib/ui";
import type { EvidenceLedger, EvidenceLedgerItem } from "../types";

/**
 * 证据台账：一处回答「现在到底哪些结论能动手」。
 *
 * ## 为什么需要这一屏
 * 项目里 K 线形态 8 条、结构化口径若干，可信度由后端 `tactic_evidence` 统一裁决，
 * 但用户要知道「什么能用」得跨好几个页面拼信息。这一块把它们聚合成一张表：
 * 每条口径的证据等级 + 样本出处 + 观察期自积累进度。
 *
 * ## 它存在的另一个理由
 * 本项目多次出现「文档写 A、代码登记表写 B」的不一致。台账的数字全部来自
 * 后端登记表与跑批快照，因此可以与 README / ROADMAP 逐条对照 ——
 * 不一致时以台账为准，并去修文档。
 *
 * ## 配色纪律
 * 全部走中性 / 琥珀；只有 verified（当前 0 条）才允许用品牌色。
 * 证据等级是**质量语义**，不占红绿 —— 红绿在本项目里只表达方向。
 */
const TIER_CHIP: Record<string, string> = {
  verified: "bg-brand/15 text-brand-light",
  preliminary: "bg-amber-500/10 text-amber-300",
  unsupported: "bg-surface-inset/70 text-ink-soft",
  unknown: "bg-surface-inset/70 text-ink-muted",
  not_testable: "bg-surface-inset/70 text-ink-muted",
};

const NAMESPACE_LABEL: Record<string, string> = {
  pattern: "K 线形态",
  strategy: "结构化口径（策略 / 盯盘 / 板块）",
};

function LedgerRow({ item, open, onToggle }: { item: EvidenceLedgerItem; open: boolean; onToggle: () => void }) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full flex-wrap items-baseline gap-x-2 gap-y-1 rounded-lg bg-surface-inset/40 px-3 py-2 text-left transition-colors hover:bg-surface-inset/70"
      >
        <span
          className={`shrink-0 rounded-md px-1.5 py-0.5 text-meta font-semibold ${
            TIER_CHIP[item.tier] ?? TIER_CHIP.unknown
          }`}
        >
          {item.badge}
        </span>
        <span className="text-meta text-ink">{item.key}</span>
        <span className="flex-1 text-meta text-ink-soft">{item.label}</span>
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-ink-muted transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>
      {open && (
        <div className="mt-1 space-y-1 px-3 pb-1">
          <p className="text-meta leading-relaxed text-ink-soft">{item.summary}</p>
          <p className="text-meta text-ink-faint">依据：{item.provenance}</p>
        </div>
      )}
    </div>
  );
}

export default function EvidenceLedgerPanel() {
  const [data, setData] = useState<EvidenceLedger | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchEvidenceLedger()
      .then((d) => {
        if (!alive) return;
        setData(d);
        setErr("");
      })
      .catch((e: unknown) => {
        if (alive) setErr((e as Error).message);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (err) {
    return (
      <div className={SUB_QUIET + " px-3 py-2 text-meta text-red-300"}>证据台账加载失败：{err}</div>
    );
  }
  if (!data) {
    return <div className={SUB_QUIET + " px-3 py-2 text-meta text-ink-soft"}>正在读取证据台账…</div>;
  }

  const acc = data.observation.limitup_accumulated;
  const namespaces = ["pattern", "strategy"] as const;

  return (
    <div className="space-y-3">
      <div>
        <h3 className={TEXT.label}>证据台账（哪些结论能动手）</h3>
        <p className="mt-1.5 rounded-lg bg-surface-inset/50 px-3 py-2 text-meta leading-relaxed text-ink-soft">
          {data.headline}
        </p>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-meta text-ink-muted">
        {(data.tier_order ?? [])
          .filter((t) => (data.counts[t] ?? 0) > 0)
          .map((t) => (
            <span key={t}>
              {data.tier_meaning[t]?.split(" ——")[0] ?? t}：
              <span className="text-ink-soft"> {data.counts[t]} 条</span>
            </span>
          ))}
      </div>

      {namespaces.map((ns) => {
        const items = (data.items ?? []).filter((i) => i.namespace === ns);
        if (items.length === 0) return null;
        return (
          <div key={ns}>
            <h4 className="mb-1.5 text-meta font-semibold text-ink-muted">{NAMESPACE_LABEL[ns] ?? ns}</h4>
            <div className="space-y-1">
              {items.map((i) => (
                <LedgerRow
                  key={i.key}
                  item={i}
                  open={open === i.key}
                  onToggle={() => setOpen(open === i.key ? null : i.key)}
                />
              ))}
            </div>
          </div>
        );
      })}

      <div className={DIVIDER} />

      <div>
        <h4 className="text-meta font-semibold text-ink-faint">观察期自积累</h4>
        <p
          className={`mt-1 text-meta leading-relaxed ${
            acc.configured ? "text-ink-soft" : "text-amber-300/90"
          }`}
        >
          涨停池累积表：
          {acc.configured && acc.days > 0
            ? `已落库 ${acc.days} 个交易日 / ${acc.rows} 行${
                acc.first_date ? `（${acc.first_date} 起）` : ""
              }`
            : acc.configured
            ? "已落库 0 个交易日（表已建，暂无快照；每日落库任务会逐步积累）"
            : acc.note === "supabase_not_configured"
            ? "未接入：Supabase 未配置（全站数据类功能均不可用，需在 Vercel 环境变量设置 SUPABASE_URL / SUPABASE_SERVICE_KEY）"
            : acc.note === "table_missing"
            ? "未接入：v10 表 limitup_daily_snapshot 未迁移（需在 Supabase SQL Editor 执行 backend/supabase-schema-v10.sql）"
            : acc.note && acc.note.startsWith("read_error:")
            ? `读取失败（${acc.note.slice("read_error:".length)}）`
            : "未接入（原因未知）"}
        </p>
        <p className="mt-1 text-meta leading-relaxed text-ink-soft">{data.observation.note}</p>
      </div>

      <p className="text-meta text-ink-muted">台账生成于 {data.generated_at}</p>
    </div>
  );
}
