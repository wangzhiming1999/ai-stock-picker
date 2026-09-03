import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ClipboardPaste, ImageUp, Loader2, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { importHoldingsBatch, parseHoldingImport } from "../api/client";
import { compressImage } from "../lib/image";
import type { ParsedHolding } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}

type Mode = "image" | "text";

interface EditRow extends ParsedHolding {
  selected: boolean;
}

function rowValid(r: EditRow): boolean {
  return /^\d{6}$/.test(r.code) && (r.cost_price ?? 0) > 0 && (r.shares ?? 0) > 0;
}

export default function ImportHoldingsModal({ open, onClose, onImported }: Props) {
  const [mode, setMode] = useState<Mode>("image");
  const [parsing, setParsing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [text, setText] = useState("");
  const [rows, setRows] = useState<EditRow[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [fileName, setFileName] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const applyResult = useCallback((items: ParsedHolding[], warns: string[]) => {
    setRows(items.map((it) => ({ ...it, selected: true })));
    setWarnings(warns);
    if (items.length === 0 && warns.length === 0) {
      setWarnings(["未解析出持仓，请检查内容"]);
    }
  }, []);

  const parseText = useCallback(async () => {
    if (!text.trim()) {
      toast.warning("请先粘贴持仓文本");
      return;
    }
    setParsing(true);
    try {
      const r = await parseHoldingImport({ text });
      applyResult(r.items, r.warnings);
    } catch (e) {
      toast.error("解析失败", { description: (e as Error).message });
    } finally {
      setParsing(false);
    }
  }, [text, applyResult]);

  const parseImage = useCallback(
    async (file: File | Blob, name = "") => {
      setParsing(true);
      setFileName(name || "剪贴板图片");
      try {
        const dataUrl = await compressImage(file);
        const r = await parseHoldingImport({ image_base64: dataUrl });
        applyResult(r.items, r.warnings);
      } catch (e) {
        toast.error("截图识别失败", { description: (e as Error).message });
      } finally {
        setParsing(false);
      }
    },
    [applyResult]
  );

  // 截图模式：支持直接 Ctrl+V 粘贴截图
  useEffect(() => {
    if (!open || mode !== "image") return;
    const onPaste = (e: ClipboardEvent) => {
      const item = Array.from(e.clipboardData?.items ?? []).find((i) => i.type.startsWith("image/"));
      const file = item?.getAsFile();
      if (file) {
        e.preventDefault();
        void parseImage(file, "剪贴板截图");
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [open, mode, parseImage]);

  const updateRow = (idx: number, patch: Partial<EditRow>) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const removeRow = (idx: number) => setRows((prev) => prev.filter((_, i) => i !== idx));

  const validSelected = rows.filter((r) => r.selected && rowValid(r));
  const invalidSelected = rows.filter((r) => r.selected && !rowValid(r));

  const doImport = async () => {
    if (validSelected.length === 0) return;
    if (invalidSelected.length > 0) {
      toast.warning(`有 ${invalidSelected.length} 只信息不完整，请补全或取消勾选`);
      return;
    }
    setImporting(true);
    try {
      const r = await importHoldingsBatch(
        validSelected.map((r) => ({ code: r.code, name: r.name, cost_price: r.cost_price!, shares: r.shares! }))
      );
      toast.success(`导入成功：${r.added} 只${r.skipped ? `（跳过 ${r.skipped} 只）` : ""}`);
      onImported();
      onClose();
    } catch (e) {
      toast.error("导入失败", { description: (e as Error).message });
    } finally {
      setImporting(false);
    }
  };

  const reset = () => {
    setRows([]);
    setWarnings([]);
    setText("");
    setFileName("");
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={onClose}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
          <motion.div
            className="flex max-h-[88vh] w-full max-w-2xl flex-col rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, scale: 0.94, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            {/* 头部 */}
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">导入持仓</h2>
              <motion.button
                onClick={onClose}
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.9 }}
                className="text-slate-500 hover:text-slate-300"
                aria-label="关闭"
              >
                <X className="h-5 w-5" />
              </motion.button>
            </div>

            {/* 模式切换 */}
            <div className="mb-4 flex rounded-lg border border-slate-700 bg-slate-800/60 p-1">
              {(
                [
                  { key: "image", label: "截图识别", icon: ImageUp },
                  { key: "text", label: "粘贴文本", icon: ClipboardPaste },
                ] as const
              ).map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => setMode(key)}
                  className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
                    mode === key ? "bg-brand text-white" : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </button>
              ))}
            </div>

            {/* 输入区 */}
            {mode === "image" ? (
              <div
                className="mb-4 rounded-xl border-2 border-dashed border-slate-700 p-5 text-center transition-colors hover:border-slate-500"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const f = e.dataTransfer.files?.[0];
                  if (f && f.type.startsWith("image/")) void parseImage(f, f.name);
                }}
              >
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void parseImage(f, f.name);
                    e.target.value = "";
                  }}
                />
                {parsing ? (
                  <div className="flex flex-col items-center gap-2 py-2 text-sm text-slate-300">
                    <Loader2 className="h-6 w-6 animate-spin text-brand" />
                    正在识别截图（约 5~15 秒）...
                  </div>
                ) : (
                  <>
                    <ImageUp className="mx-auto mb-2 h-8 w-8 text-slate-500" />
                    <p className="text-sm text-slate-300">
                      {fileName ? (
                        <>
                          已识别 <b className="text-slate-100">{fileName}</b>，可重新上传
                        </>
                      ) : (
                        "上传券商 App 持仓页截图"
                      )}
                    </p>
                    <p className="mt-1 text-[11px] text-slate-500">点击选择 / 拖入 / 直接 Ctrl+V 粘贴截图</p>
                    <button
                      onClick={() => fileRef.current?.click()}
                      className="mt-3 rounded-lg bg-brand px-4 py-1.5 text-xs font-medium text-white hover:bg-brand-dark"
                    >
                      选择截图
                    </button>
                  </>
                )}
              </div>
            ) : (
              <div className="mb-4">
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={5}
                  placeholder={"从券商 App 复制持仓文本后粘贴到这里，每行一只，例如：\n贵州茅台 600519 1224.50 100\n五粮液 000858 成本128.5 数量200"}
                  className="w-full resize-y rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:border-brand focus:outline-none"
                />
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-[11px] text-slate-500">支持 名称+代码+成本+数量 的任意组合顺序</span>
                  <button
                    onClick={() => void parseText()}
                    disabled={parsing || !text.trim()}
                    className="rounded-lg bg-brand px-4 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-40"
                  >
                    {parsing ? "解析中..." : "解析文本"}
                  </button>
                </div>
              </div>
            )}

            {/* 警告 */}
            {warnings.length > 0 && (
              <div className="mb-3 space-y-1 rounded-lg border border-amber-800/60 bg-amber-950/30 px-3 py-2">
                {warnings.slice(0, 5).map((w, i) => (
                  <p key={i} className="text-[11px] text-amber-300">
                    ⚠ {w}
                  </p>
                ))}
              </div>
            )}

            {/* 预览编辑表 */}
            {rows.length > 0 && (
              <div className="mb-4 min-h-0 flex-1 overflow-auto rounded-lg border border-slate-800">
                <table className="w-full text-sm" style={{ minWidth: 520 }}>
                  <thead className="sticky top-0 z-10 bg-slate-900 text-left text-xs text-slate-400">
                    <tr>
                      <th className="px-2 py-2"></th>
                      <th className="px-2 py-2">代码</th>
                      <th className="px-2 py-2">名称</th>
                      <th className="px-2 py-2 text-right">成本价</th>
                      <th className="px-2 py-2 text-right">数量(股)</th>
                      <th className="px-2 py-2 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, idx) => (
                      <tr key={`${r.code}-${idx}`} className={`border-t border-slate-800/60 ${!rowValid(r) ? "bg-red-950/20" : ""}`}>
                        <td className="px-2 py-1.5">
                          <input
                            type="checkbox"
                            checked={r.selected}
                            onChange={(e) => updateRow(idx, { selected: e.target.checked })}
                            className="accent-brand"
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <input
                            value={r.code}
                            onChange={(e) => updateRow(idx, { code: e.target.value.replace(/\D/g, "").slice(0, 6) })}
                            className={`w-20 rounded border bg-slate-950 px-1.5 py-1 text-xs ${
                              /^\d{6}$/.test(r.code) ? "border-slate-700 text-slate-200" : "border-red-700 text-red-300"
                            }`}
                          />
                        </td>
                        <td className="px-2 py-1.5 text-xs text-slate-300">{r.name || "-"}</td>
                        <td className="px-2 py-1.5 text-right">
                          <input
                            type="number"
                            step="any"
                            min="0"
                            value={r.cost_price ?? ""}
                            onChange={(e) =>
                              updateRow(idx, { cost_price: e.target.value === "" ? null : parseFloat(e.target.value) })
                            }
                            placeholder="必填"
                            className={`w-20 rounded border bg-slate-950 px-1.5 py-1 text-right text-xs ${
                              (r.cost_price ?? 0) > 0 ? "border-slate-700 text-slate-200" : "border-red-700 text-red-300"
                            }`}
                          />
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          <input
                            type="number"
                            min="0"
                            value={r.shares ?? ""}
                            onChange={(e) =>
                              updateRow(idx, { shares: e.target.value === "" ? null : parseInt(e.target.value, 10) })
                            }
                            placeholder="必填"
                            className={`w-20 rounded border bg-slate-950 px-1.5 py-1 text-right text-xs ${
                              (r.shares ?? 0) > 0 ? "border-slate-700 text-slate-200" : "border-red-700 text-red-300"
                            }`}
                          />
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          <button
                            onClick={() => removeRow(idx)}
                            className="rounded p-1 text-slate-600 hover:bg-red-950/40 hover:text-red-400"
                            title="移除此行"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* 底部动作 */}
            <div className="flex items-center justify-between gap-3">
              <button onClick={reset} disabled={rows.length === 0} className="text-xs text-slate-500 hover:text-slate-300 disabled:opacity-30">
                清空重来
              </button>
              <button
                onClick={() => void doImport()}
                disabled={importing || validSelected.length === 0}
                className="rounded-lg bg-brand px-5 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-40"
              >
                {importing ? "导入中..." : `导入选中 ${validSelected.length} 只`}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
