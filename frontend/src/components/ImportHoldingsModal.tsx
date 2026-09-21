import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ClipboardPaste, ImageUp, Loader2, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { importHoldingsBatch, parseHoldingImport } from "../api/client";
import { compressImage } from "../lib/image";
import { CARD, INPUT_BASE, CELL } from "../lib/ui";
import type { ParsedHolding } from "../types";
import Input from "./ui/Input";
import Button from "./ui/Button";
import Table, { Th } from "./ui/Table";

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
            className={`${CARD} flex max-h-[88vh] w-full max-w-2xl flex-col shadow-2xl`}
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, scale: 0.94, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            {/* 头部 */}
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-num font-bold text-white">导入持仓</h2>
              <motion.button
                onClick={onClose}
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.9 }}
                className="text-ink-muted hover:text-ink-soft"
                aria-label="关闭"
              >
                <X className="h-5 w-5" />
              </motion.button>
            </div>

            {/* 模式切换 */}
            <div className="mb-4 flex rounded-lg border border-surface-line bg-surface-inset/70 p-1">
              {(
                [
                  { key: "image", label: "截图识别", icon: ImageUp },
                  { key: "text", label: "粘贴文本", icon: ClipboardPaste },
                ] as const
              ).map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => setMode(key)}
                  className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-body transition-colors ${
                    mode === key ? "bg-brand text-white" : "text-ink-muted hover:text-ink"
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
                className="mb-4 rounded-xl border-2 border-dashed border-surface-line p-5 text-center transition-colors hover:border-surface-line-hover"
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
                  <div className="flex flex-col items-center gap-2 py-2 text-body text-ink-soft">
                    <Loader2 className="h-6 w-6 animate-spin text-brand-light" aria-hidden />
                    正在识别截图（约 5~15 秒）...
                  </div>
                ) : (
                  <>
                    <ImageUp className="mx-auto mb-2 h-8 w-8 text-ink-faint" aria-hidden />
                    <p className="text-body text-ink-soft">
                      {fileName ? (
                        <>
                          已识别 <b className="text-ink-strong">{fileName}</b>，可重新上传
                        </>
                      ) : (
                        "上传券商 App 持仓页截图"
                      )}
                    </p>
                    <p className="mt-1 text-meta text-ink-soft">点击选择 / 拖入 / 直接 Ctrl+V 粘贴截图</p>
                    <Button variant="primary" size="md"
                      onClick={() => fileRef.current?.click()}
                      className="mt-3">
                      选择截图
                    </Button>
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
                  className={`${INPUT_BASE} w-full resize-y bg-surface-canvas px-3 py-2 text-meta`} />
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-meta text-ink-soft">支持 名称+代码+成本+数量 的任意组合顺序</span>
                  <Button variant="primary" size="md"
                    onClick={() => void parseText()}
                    disabled={parsing || !text.trim()}
                    >
                    {parsing ? "解析中..." : "解析文本"}
                  </Button>
                </div>
              </div>
            )}

            {/* 警告 */}
            {warnings.length > 0 && (
              <div className="mb-3 space-y-1 rounded-lg border border-state-warn-line bg-state-warn-surface px-3 py-2">
                {warnings.slice(0, 5).map((w, i) => (
                  <p key={i} className="text-meta text-amber-300">
                    ⚠ {w}
                  </p>
                ))}
              </div>
            )}

            {/* 预览编辑表 */}
            {rows.length > 0 && (
              <Table
                label="导入持仓预览"
                minWidth={520}
                maxHeight="none"
                className="mb-4 min-h-0 flex-1"
                head={
                  <tr>
                    <Th />
                    <Th>代码</Th>
                    <Th>名称</Th>
                    <Th align="right">成本价</Th>
                    <Th align="right">数量(股)</Th>
                    <Th align="right">操作</Th>
                  </tr>
                }
              >
                {rows.map((r, idx) => (
                  <tr key={`${r.code}-${idx}`} className={`border-t border-surface-line-soft ${!rowValid(r) ? "bg-state-danger-surface" : ""}`}>
                    <td className={CELL}>
                      <input
                        type="checkbox"
                        checked={r.selected}
                        onChange={(e) => updateRow(idx, { selected: e.target.checked })}
                        className="accent-brand"
                      />
                    </td>
                    <td className={CELL}>
                      <Input
                        value={r.code}
                        onChange={(e) => updateRow(idx, { code: e.target.value.replace(/\D/g, "").slice(0, 6) })}
                        tone={/^\d{6}$/.test(r.code) ? "default" : "danger"}
                        className="w-20 bg-surface-canvas px-1.5 py-1 text-meta"
                      />
                    </td>
                    <td className={`${CELL} text-meta text-ink-soft`}>{r.name || "-"}</td>
                    <td className={`${CELL} text-right`}>
                      <Input
                        type="number"
                        step="any"
                        min="0"
                        value={r.cost_price ?? ""}
                        onChange={(e) =>
                          updateRow(idx, { cost_price: e.target.value === "" ? null : parseFloat(e.target.value) })
                        }
                        placeholder="必填"
                        tone={(r.cost_price ?? 0) > 0 ? "default" : "danger"}
                        className="w-20 bg-surface-canvas px-1.5 py-1 text-right text-meta"
                      />
                    </td>
                    <td className={`${CELL} text-right`}>
                      <Input
                        type="number"
                        min="0"
                        value={r.shares ?? ""}
                        onChange={(e) =>
                          updateRow(idx, { shares: e.target.value === "" ? null : parseInt(e.target.value, 10) })
                        }
                        placeholder="必填"
                        tone={(r.shares ?? 0) > 0 ? "default" : "danger"}
                        className="w-20 bg-surface-canvas px-1.5 py-1 text-right text-meta"
                      />
                    </td>
                    <td className={`${CELL} text-right`}>
                      <button
                        onClick={() => removeRow(idx)}
                        className="rounded-md p-1 text-ink-muted hover:bg-state-danger-surface hover:text-state-danger"
                        title="移除此行"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </button>
                    </td>
                  </tr>
                ))}
              </Table>
            )}

            {/* 底部动作 */}
            <div className="flex items-center justify-between gap-3">
              <button onClick={reset} disabled={rows.length === 0} className="text-meta text-ink-muted hover:text-ink-soft">
                清空重来
              </button>
              <Button variant="primary" size="lg"
                onClick={() => void doImport()}
                disabled={importing || validSelected.length === 0}
                >
                {importing ? "导入中..." : `导入选中 ${validSelected.length} 只`}
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
