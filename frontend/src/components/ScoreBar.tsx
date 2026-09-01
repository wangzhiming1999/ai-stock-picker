interface Props {
  label: string;
  score: number;
}

function scoreColor(score: number): string {
  if (score >= 7) return "bg-green-500";
  if (score >= 5) return "bg-yellow-500";
  if (score >= 3) return "bg-orange-500";
  return "bg-red-500";
}

export default function ScoreBar({ label, score }: Props) {
  const pct = Math.max(0, Math.min(100, score * 10));
  return (
    <div className="flex items-center gap-3">
      <span className="w-14 shrink-0 text-sm text-slate-400">{label}</span>
      <div className="h-2 flex-1 rounded-full bg-slate-800 overflow-hidden">
        <div
          className={`h-full rounded-full ${scoreColor(score)} transition-all duration-700`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-8 shrink-0 text-right text-sm font-medium text-slate-200">
        {score.toFixed(1)}
      </span>
    </div>
  );
}
