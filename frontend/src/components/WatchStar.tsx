import { useState } from "react";
import { motion } from "framer-motion";
import { Star } from "lucide-react";
import { addToWatchlist } from "../api/client";
import { useAuth } from "../auth/AuthContext";

interface Props {
  code: string;
  /** 小尺寸（列表内嵌）还是按钮尺寸 */
  size?: "sm" | "md";
}

/** 通知 App 打开登录弹窗（避免逐层传 props） */
export function requestAuth() {
  window.dispatchEvent(new CustomEvent("stock:require-auth"));
}

export default function WatchStar({ code, size = "sm" }: Props) {
  const { user } = useAuth();
  const [active, setActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const handle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (busy) return;
    if (!user) {
      requestAuth();
      return;
    }
    setBusy(true);
    setMsg("");
    try {
      await addToWatchlist(code);
      setActive(true);
      setMsg("已加自选");
      setTimeout(() => setMsg(""), 1500);
    } catch (err) {
      setMsg((err as Error).message);
      setTimeout(() => setMsg(""), 2000);
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="relative inline-flex items-center">
      <motion.button
        whileTap={{ scale: 0.85 }}
        onClick={(e) => void handle(e)}
        title={active ? "已在自选" : "加入自选"}
        className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] transition-colors ${
          active
            ? "text-amber-400"
            : "text-slate-500 hover:bg-slate-700/50 hover:text-amber-300"
        }`}
      >
        <Star className={`h-3.5 w-3.5 ${active ? "fill-amber-400" : ""}`} strokeWidth={2} />
        {size === "md" && (active ? "已加" : "加自选")}
      </motion.button>
      {msg && (
        <span className={`absolute left-0 top-full z-10 whitespace-nowrap rounded bg-slate-800 px-1.5 py-0.5 text-[10px] ${msg.includes("已") ? "text-amber-300" : "text-red-300"}`}>
          {msg}
        </span>
      )}
    </span>
  );
}
