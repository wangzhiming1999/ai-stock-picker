import { Bell, BellRing, RefreshCw } from "lucide-react";
import Button from "../ui/Button";

interface Props {
  notifyOn: boolean;
  onToggleNotify: () => void;
  onForceRefresh: () => void;
  loading: boolean;
  disabled: boolean;
}

/** 面板头部操作区：通知开关 + 立即刷新 */
export default function MonitorHeaderActions({ notifyOn, onToggleNotify, onForceRefresh, loading, disabled }: Props) {
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={onToggleNotify}
        title="指令变化时（买入/减仓/止损）响铃提醒，页面后台时弹系统通知"
        className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1 text-meta transition-colors ${
          notifyOn
            ? "border-state-warn-line bg-state-warn-surface text-state-warn-soft hover:bg-state-warn-surface"
            : "border-surface-line text-ink-muted hover:text-ink"
        }`}
      >
        {notifyOn ? <BellRing className="h-3.5 w-3.5" aria-hidden /> : <Bell className="h-3.5 w-3.5" aria-hidden />}
        {notifyOn ? "提醒已开" : "开启提醒"}
      </button>
      <Button
        variant="outlineQuiet"
        size="sm"
        onClick={onForceRefresh}
        disabled={loading || disabled}
      >
        <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
        {loading ? "刷新中..." : "立即刷新"}
      </Button>
    </div>
  );
}
