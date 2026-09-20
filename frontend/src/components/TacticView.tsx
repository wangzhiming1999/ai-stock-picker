import TacticPanel from "./TacticPanel";
import { useImportToWatchlist } from "../lib/useImportToWatchlist";

interface Props {
  onPick: (codes: string[]) => void;
}

/**
 * 实战形态 · 子页外壳
 *
 * 只做一件事：给 `TacticPanel` 接上「批量加自选」。
 * 抽出来的理由是形态从「扫描页里的第四个视图」提升为独立子页之后，
 * 加自选的逻辑需要与扫描页共用（见 `useImportToWatchlist`）。
 */
export default function TacticView({ onPick }: Props) {
  const importCodes = useImportToWatchlist();
  return <TacticPanel onPick={onPick} onImport={(c) => void importCodes(c)} />;
}
