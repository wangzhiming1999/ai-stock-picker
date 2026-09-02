/** 统一动效预设：framer-motion 动画变体 */
import type { Variants } from "framer-motion";

/** Tab/面板内容淡入上移 */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.28, ease: [0.22, 1, 0.36, 1] },
  },
};

/** 卡片列表交错入场 */
export const stagger: Variants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.06 },
  },
};

/** 单个卡片项 */
export const cardItem: Variants = {
  hidden: { opacity: 0, y: 16, scale: 0.99 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.25, ease: [0.22, 1, 0.36, 1] },
  },
};

/** 折叠内容展开（高度过渡） */
export const expand: Variants = {
  hidden: { opacity: 0, height: 0, overflow: "hidden" },
  visible: {
    opacity: 1,
    height: "auto",
    transition: { duration: 0.25, ease: [0.22, 1, 0.36, 1] },
  },
};

/** 图标 hover 缩放 */
export const iconTap = { whileHover: { scale: 1.15 }, whileTap: { scale: 0.9 } };
