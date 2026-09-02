import { motion } from "framer-motion";
import { TrendingUp } from "lucide-react";

interface Props {
  size?: "sm" | "md" | "lg";
  withText?: boolean;
  subtitle?: string;
  onClick?: () => void;
}

const SIZE_MAP = {
  sm: { box: "h-8 w-8", icon: "h-4 w-4", text: "text-sm", sub: "text-[10px]", glow: "shadow-[0_0_8px_rgba(220,38,38,0.35)]" },
  md: { box: "h-10 w-10", icon: "h-5 w-5", text: "text-base", sub: "text-[11px]", glow: "shadow-[0_0_14px_rgba(220,38,38,0.45)]" },
  lg: { box: "h-14 w-14", icon: "h-7 w-7", text: "text-xl", sub: "text-xs", glow: "shadow-[0_0_20px_rgba(220,38,38,0.55)]" },
};

export default function BrandLogo({ size = "md", withText = true, subtitle, onClick }: Props) {
  const c = SIZE_MAP[size];
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.95 }}
      className="flex items-center gap-3 text-left"
      aria-label="AI 选股分析"
    >
      <div className="relative shrink-0">
        {/* 外圈脉冲光环（hover 时增强） */}
        <motion.div
          className={`absolute inset-0 -m-1 rounded-2xl bg-brand/30 blur-md ${c.glow}`}
          animate={{ opacity: [0.3, 0.6, 0.3], scale: [1, 1.08, 1] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
        />
        {/* 主体渐变方块 */}
        <motion.div
          whileHover={{ rotate: 10 }}
          transition={{ type: "spring", stiffness: 260, damping: 18 }}
          className={`relative flex ${c.box} items-center justify-center rounded-xl bg-gradient-to-br from-brand via-rose-500 to-orange-500 text-white ${c.glow}`}
        >
          <TrendingUp className={c.icon} strokeWidth={2.6} />
        </motion.div>
      </div>
      {withText && (
        <div className="hidden sm:block">
          <h1 className={`font-bold leading-tight ${c.text}`}>
            <span className="bg-gradient-to-r from-brand via-rose-400 to-orange-400 bg-clip-text text-transparent">AI 选股</span>
          </h1>
          {subtitle !== null && (
            <p className={`mt-0.5 text-slate-400 ${c.sub}`}>{subtitle ?? "发现 · 扫描 · 分析 · 持仓"}</p>
          )}
        </div>
      )}
    </motion.button>
  );
}