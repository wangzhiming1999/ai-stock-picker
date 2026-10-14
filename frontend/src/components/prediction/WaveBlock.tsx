import type { ReactNode } from "react";
import type { WaveAnalysis, WaveLevel } from "../../types";
import { SECTION_SUB, SUB, TEXT } from "../../lib/ui";
import { downTone, scoreChip, upTone } from "../../lib/tone";
import {
  LOW_CONFIDENCE,
  confidencePct,
  failedRequiredRules,
  failedSoftRules,
  hasWave,
  isInProgress,
  targetTexts,
  waveChips,
} from "./waveLogic";

/**
 * 「当前浪位」区块 —— 大盘推演卡里的**只读辅助读数**。
 *
 * ## 与同卡其它块的关系（改之前先读）
 * 这张卡的主结论（方向 + 分数）由量化证据分决定，本块**不参与**它，
 * 后端也刻意没把波浪写进 LLM 上下文（见 `market_prediction.build_market_context`
 * 里 `wave` 字段的三行注释）。所以这里必须做到两件事：
 *   1. **视觉上分层**：副标题直接写明「只读读数，不参与方向分」，不与主结论抢权重；
 *   2. **永远带级别**：文案是「日线 · C 浪第 3 子浪」，不是孤零零一个「第 3 浪」。
 *
 * 置信度低（有铁律没过）时整行弱化 —— 那仍然只是「最接近的一版划分」，
 * 不能和铁律全过的读法长一个样。
 */

/** 方向色：波浪位本身带方向语义（推动浪向上/向下），所以用红绿，不用中性。 */
function dirClass(level: WaveLevel): string {
  if (level.direction === "down") return downTone(300);
  if (level.direction === "up") return upTone(300);
  return "text-ink";
}

function Chip({ active, hint, children }: { active?: boolean; hint?: string; children: ReactNode }) {
  return (
    <span
      title={hint}
      className={`rounded-md px-1.5 py-0.5 text-meta ${
        active ? "bg-brand/15 text-brand-light" : "bg-surface-raised/60 text-ink-muted"
      }`}
    >
      {children}
    </span>
  );
}

function LevelRow({ level }: { level: WaveLevel }) {
  // 定位不出浪位不是异常路径（样本不足 / 结构不匹配模板都会走到这里），
  // 要说清原因而不是显示一片空白。
  if (!level?.position) {
    return (
      <div className={`${SUB} p-3`}>
        <span className={TEXT.label}>{level?.degree ?? "-"}</span>
        <p className="mt-1 text-meta text-ink-soft">{level?.note || "当前结构不匹配波浪模板，暂无法定位浪位。"}</p>
      </div>
    );
  }

  const requiredFailed = failedRequiredRules(level);
  const softFailed = failedSoftRules(level);
  const low = level.confidence < LOW_CONFIDENCE;
  const targets = targetTexts(level);

  return (
    <div className={`${SUB} p-3`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={TEXT.label}>{level.degree}</span>
        {/*
          只渲染 position_cn：它自带标签（「C 浪（…）」「第 5 浪（末段）」
          「C 浪第 3 子浪（…）」），再并排一个裸标签会变成「C · C 浪（…）」的重复读法。
          短标签本身在下面的子浪 chips 里已经有位置，且当前那一浪是高亮的那颗。
        */}
        <span className={`text-body font-semibold ${dirClass(level)}`}>{level.position_cn ?? level.position}</span>
        {isInProgress(level) && <Chip hint="以最后一个摆动点为界，这一浪还没走完">未走完</Chip>}
        <span className={`ml-auto rounded-md px-1.5 py-0.5 text-meta ${scoreChip(low ? null : level.confidence * 10)}`}>
          置信度 {confidencePct(level)}%
        </span>
      </div>

      {level.waves.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {waveChips(level).map((w) => (
            <Chip key={w.label} active={w.current} hint={w.hint}>
              {w.text}
            </Chip>
          ))}
        </div>
      )}

      {targets.length > 0 && (
        <p className="mt-1.5 text-meta text-ink-muted">斐波那契目标位 {targets.join(" · ")}</p>
      )}

      {level.parent && (
        <p className="mt-1 text-meta text-ink-muted">
          外层结构：{level.parent.label_cn ?? "A-B-C 调整"}（子浪按锯齿形 5-3-5 匹配）
        </p>
      )}

      {/* 必过铁律没过 = 这个划分本身不成立 → 告警色 + 明确说「仅供参考」 */}
      {requiredFailed.length > 0 && (
        <p className="mt-1.5 text-meta text-amber-300">
          未通过铁律：{requiredFailed.map((r) => r.name).join("；")}
          {low && " —— 该划分仅供参考"}
        </p>
      )}

      {/* 软性规则只是比例/形态偏离，不影响划分成立 → 中性色，不告警 */}
      {softFailed.length > 0 && (
        <p className="mt-1 text-meta text-ink-muted">
          比例偏离：{softFailed.map((r) => `${r.name}（${r.detail}）`).join("；")}
        </p>
      )}

      {level.rules.length > 0 && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-meta text-ink-muted">铁律校验（{level.rules.length} 条）</summary>
          <ul className="mt-1 space-y-0.5">
            {level.rules.map((r) => (
              <li key={r.name} className="text-meta text-ink-muted">
                <span className={r.ok ? "text-ink-soft" : "text-amber-300"}>{r.ok ? "通过" : "未过"}</span>
                {" "}
                {r.name}：{r.detail}
                {r.applicable === false ? "（当前不可评估）" : ""}
                {r.required === false ? "（软性）" : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default function WaveBlock({ wave }: { wave?: WaveAnalysis | null }) {
  if (!hasWave(wave)) return null;
  const levels = [wave?.daily, wave?.weekly].filter((l): l is WaveLevel => Boolean(l));

  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className={SECTION_SUB}>当前浪位</span>
        <span className="text-meta text-ink-muted">艾略特波浪 · 日线 / 周线双级别</span>
        <span className="text-meta text-ink-muted">只读读数，不参与方向分</span>
      </div>
      <div className="space-y-2">
        {levels.map((l) => (
          <LevelRow key={l.degree} level={l} />
        ))}
      </div>
      {wave?.note && <p className="mt-1.5 text-meta text-ink-faint">{wave.note}</p>}
    </div>
  );
}
