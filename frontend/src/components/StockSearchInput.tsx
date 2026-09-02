import { useEffect, useRef, useState } from "react";
import { searchStocks } from "../api/client";
import type { StockSearchResult } from "../types";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onPickCode: (code: string) => void;
  disabled?: boolean;
}

export default function StockSearchInput({ value, onChange, onPickCode, disabled }: Props) {
  const [suggestions, setSuggestions] = useState<StockSearchResult[]>([]);
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setShow(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (disabled) return;
    const q = value.trim();
    if (q.length < 1) {
      setSuggestions([]);
      setShow(false);
      return;
    }
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const res = await searchStocks(q, 8);
        setSuggestions(res);
        setShow(res.length > 0);
      } catch {
        setSuggestions([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [value, disabled]);

  const pick = (s: StockSearchResult) => {
    onChange(`${s.code} ${s.name}`);
    onPickCode(s.code);
    setShow(false);
  };

  return (
    <div className="relative flex-1" ref={boxRef}>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="输入 6 位代码或股票名称，如 600519 / 茅台 / 贵州茅台"
        disabled={disabled}
        className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2.5 text-sm outline-none placeholder:text-slate-500 focus:border-brand disabled:opacity-50"
      />
      {loading && <span className="absolute right-3 top-3 text-xs text-slate-500">...</span>}
      {show && suggestions.length > 0 && (
        <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-slate-700 bg-slate-900 shadow-xl">
          {suggestions.map((s) => (
            <button
              key={s.code}
              onClick={() => pick(s)}
              className="flex w-full items-center justify-between px-4 py-2 text-left hover:bg-slate-800"
            >
              <span className="text-sm text-slate-200">{s.name}</span>
              <span className="ml-3 flex items-center gap-3 text-xs">
                <span className="text-slate-500">{s.code}</span>
                <span className="text-slate-400">{s.price.toFixed(2)}</span>
                <span className={s.change_pct >= 0 ? "text-green-400" : "text-red-400"}>
                  {s.change_pct >= 0 ? "+" : ""}
                  {s.change_pct.toFixed(2)}%
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
