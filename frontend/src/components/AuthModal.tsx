import { useState } from "react";
import { useAuth } from "../auth/AuthContext";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function AuthModal({ open, onClose }: Props) {
  const { signIn, signUp, loading } = useAuth();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  if (!open) return null;

  const submit = async () => {
    setError("");
    setNotice("");
    if (!email || !password) {
      setError("请填写邮箱和密码");
      return;
    }
    if (password.length < 6) {
      setError("密码至少 6 位");
      return;
    }
    try {
      if (mode === "signin") {
        await signIn(email, password);
        onClose();
      } else {
        await signUp(email, password);
        setNotice("注册成功！请检查邮箱完成确认（若无需确认则已自动登录）。");
        setMode("signin");
      }
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-bold text-white">{mode === "signin" ? "登录" : "注册"}</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300" aria-label="关闭">
            ✕
          </button>
        </div>

        <div className="mb-4 flex rounded-lg border border-slate-700 bg-slate-800/60 p-1">
          {(["signin", "signup"] as const).map((m) => (
            <button
              key={m}
              onClick={() => {
                setMode(m);
                setError("");
                setNotice("");
              }}
              className={`flex-1 rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                mode === m ? "bg-brand text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {m === "signin" ? "登录" : "注册"}
            </button>
          ))}
        </div>

        <label className="mb-3 block">
          <span className="mb-1 block text-sm text-slate-400">邮箱</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-2 text-sm outline-none focus:border-brand"
          />
        </label>
        <label className="mb-4 block">
          <span className="mb-1 block text-sm text-slate-400">密码</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void submit()}
            placeholder="至少 6 位"
            className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-2 text-sm outline-none focus:border-brand"
          />
        </label>

        {error && <div className="mb-3 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</div>}
        {notice && <div className="mb-3 rounded-lg border border-green-800 bg-green-950/40 px-3 py-2 text-sm text-green-300">{notice}</div>}

        <button
          onClick={() => void submit()}
          disabled={loading}
          className="w-full rounded-lg bg-brand py-2.5 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {loading ? "请稍候..." : mode === "signin" ? "登录" : "注册"}
        </button>
      </div>
    </div>
  );
}
