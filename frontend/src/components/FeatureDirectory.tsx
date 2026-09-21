import { useEffect, useRef, useState } from "react";
import { ArrowRight, Search } from "lucide-react";
import {
  DOMAINS,
  FEATURES,
  filterFeatures,
  type Domain,
  type FeatureEntry,
} from "../lib/featureMap";
import { INPUT_BASE, INPUT_TONE, TEXT } from "../lib/ui";

interface Props {
  onGo: (f: FeatureEntry) => void;
  /** 打开时把某一组滚到可视区（首页那条「功能地图」按域点进来时用） */
  focusDomain?: Domain | null;
}

/**
 * 功能目录 · 全站功能的一览与直达
 *
 * 存在的理由见 `lib/featureMap.ts` 顶部：一级导航只有 3 项，但功能有 20+ 个，
 * 新加的功能加完就等于埋了。这一屏把清单摊开，点一下就到位。
 *
 * ## 两个刻意的取舍
 * 1. **不做分类折叠**。默认全部展开 —— 折叠会重新制造"找不到"的问题，
 *    而清单本身不长（20 多条，两列排下来一屏能看完）。真正的收窄靠搜索。
 * 2. **搜索框只搜功能关键词，不搜股票**。顶部那个搜索框已经负责股票了，
 *    两者混在一起会让"输入 600519 却跳到设置"这种事发生。见 `filterFeatures`。
 */
export default function FeatureDirectory({ onGo, focusDomain }: Props) {
  const [q, setQ] = useState("");
  const hit = filterFeatures(q);
  const searching = q.trim().length > 0;

  // 从首页按域点进来时，把那一组滚到眼前
  const first = useRef(true);
  useEffect(() => {
    if (!focusDomain) return;
    const el = document.getElementById(`feature-group-${focusDomain}`);
    // 首次挂载时浏览器还没排版完，延迟一帧再滚
    const id = window.setTimeout(() => el?.scrollIntoView({ block: "start" }), first.current ? 60 : 0);
    first.current = false;
    return () => window.clearTimeout(id);
  }, [focusDomain]);

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" aria-hidden />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜功能：溢价 / 炸板 / 回测 / 模拟盘 / 盯盘…"
          aria-label="搜索功能"
          className={`${INPUT_BASE} ${INPUT_TONE.default} w-full bg-surface-inset/70 py-2.5 pl-9 pr-3 text-body`}
        />
      </div>

      {searching ? (
        <p className={TEXT.meta}>
          匹配 {hit.length} / {FEATURES.length} 项
          {hit.length === 0 && " —— 换个说法试试，比如「抄底」「练手」「挂单」"}
        </p>
      ) : (
        <p className={TEXT.meta}>共 {FEATURES.length} 项，按「一天里先做哪件事」排</p>
      )}

      {DOMAINS.map((d) => {
        const items = hit.filter((f) => f.domain === d.key);
        if (items.length === 0) return null;
        return (
          <section key={d.key} id={`feature-group-${d.key}`} className="scroll-mt-4">
            <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2">
              <h3 className={TEXT.label}>{d.label}</h3>
              <span className="text-meta text-ink-muted">
                {d.desc} · {items.length} 项
              </span>
            </div>
            <div className="grid gap-1 sm:grid-cols-2">
              {items.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => onGo(f)}
                  className="group flex w-full items-start gap-2 rounded-lg bg-surface-inset/40 px-3 py-2 text-left transition-colors hover:bg-surface-inset/70"
                >
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className="text-body text-ink">{f.label}</span>
                      {f.isNew && (
                        <span className="shrink-0 rounded-md bg-brand/15 px-1.5 py-0.5 text-meta font-semibold text-brand-light">
                          新
                        </span>
                      )}
                    </span>
                    <span className="mt-0.5 block text-meta leading-relaxed text-ink-muted">{f.desc}</span>
                  </span>
                  <ArrowRight
                    className="mt-1 h-3.5 w-3.5 shrink-0 text-ink-muted transition-colors group-hover:text-ink"
                    aria-hidden
                  />
                </button>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
