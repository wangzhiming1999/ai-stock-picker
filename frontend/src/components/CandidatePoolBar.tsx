import { useState } from "react";
import { ListPlus, Plus, X } from "lucide-react";
import Button from "./ui/Button";
import Input from "./ui/Input";
import Panel from "./ui/Panel";
import { parseCandidateCodes } from "../lib/candidatePool";

interface Props {
  codes: string[];
  onAdd: (codes: string[]) => void;
  onClear: () => void;
}

export default function CandidatePoolBar({ codes, onAdd, onClear }: Props) {
  const [raw, setRaw] = useState("");
  const add = () => {
    const next = parseCandidateCodes(raw);
    if (next.length === 0) return;
    onAdd(next);
    setRaw("");
  };

  return (
    <Panel
      icon={ListPlus}
      title={`共享候选池 · ${codes.length} 只`}
      desc="进入深度分析的股票会保留在本中心，并自动带入三度扫描"
      actions={codes.length > 0 ? (
        <Button variant="ghost" size="sm" onClick={onClear} aria-label="清空共享候选池">
          <X className="h-4 w-4" aria-hidden />
          清空
        </Button>
      ) : undefined}
      bodyClassName="px-4 py-3"
    >
      <div className="flex flex-col gap-3">
        <div className="flex gap-2">
          <Input
            id="shared-candidate-codes"
            name="shared-candidate-codes"
            value={raw}
            onChange={(event) => setRaw(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                add();
              }
            }}
            placeholder="输入代码加入共享池，如 600519 000858"
            aria-label="输入共享候选股票代码"
            className="flex-1"
          />
          <Button variant="neutral" size="md" onClick={add} disabled={parseCandidateCodes(raw).length === 0}>
            <Plus className="h-4 w-4" aria-hidden />
            加入
          </Button>
        </div>
        {codes.length > 0 && (
          <div className="flex flex-wrap gap-2" aria-label="共享候选股票代码">
            {codes.map((code) => (
              <span key={code} className="rounded-md bg-surface-inset px-2 py-1 text-meta text-ink-soft">
                {code}
              </span>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}
