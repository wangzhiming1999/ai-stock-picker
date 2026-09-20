import type { StockAnalysis, StockInfo } from "../../types";

/** 分析生命周期阶段。宿主持有，渲染块只读它决定展示。 */
export type Phase = "idle" | "running" | "done" | "error";

/** 单只股票的「分析结果 + 行情」配对，结果列表的每一项。 */
export interface AnalysisItem {
  analysis: StockAnalysis;
  info?: StockInfo;
}

/** 面板宽度记忆：拖窄过一次就一直是窄的，不用每次重调 */
export const WIDTH_KEY = "ai:analysisDrawerWidth";
export const DEFAULT_WIDTH = 768;
export const MIN_WIDTH = 360;
export const MAX_WIDTH = 1200;
/** 主界面至少留出的可见宽度 —— 这是「抽屉不挡事」的硬底线 */
export const MIN_MAIN_WIDTH = 260;

function readInitialWidth(): number {
  try {
    const n = Number(localStorage.getItem(WIDTH_KEY));
    if (Number.isFinite(n) && n >= MIN_WIDTH && n <= MAX_WIDTH) return n;
  } catch {
    /* ignore */
  }
  return DEFAULT_WIDTH;
}

/** 当前视口允许的最大宽度：不占满，永远给主界面留一条可点的区域 */
function maxAllowedWidth(): number {
  if (typeof window === "undefined") return MAX_WIDTH;
  return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth - MIN_MAIN_WIDTH));
}

function parseCodesFromText(text: string): string[] {
  return text
    .split(/[\s,，;；、]+/)
    .map((s) => s.trim())
    .filter((s) => /^\d{6}$/.test(s));
}

export { readInitialWidth, maxAllowedWidth, parseCodesFromText };
