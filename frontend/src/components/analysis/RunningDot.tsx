/**
 * 运行中的呼吸点：状态条和折叠胶囊共用，避免两处各写一遍。
 */
export default function RunningDot() {
  return (
    <span className="relative flex h-2.5 w-2.5 shrink-0">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-light opacity-75" />
      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand" />
    </span>
  );
}
