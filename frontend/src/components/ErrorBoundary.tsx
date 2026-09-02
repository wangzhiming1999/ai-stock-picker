import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-xl p-6">
          <div className="rounded-xl border border-red-800 bg-red-950/30 p-5">
            <h2 className="text-lg font-semibold text-red-300">页面遇到了一个问题</h2>
            <p className="mt-2 text-sm text-slate-300">
              某个组件渲染失败，已被错误边界拦截，避免整个页面崩溃。
            </p>
            <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-slate-950/60 p-3 text-[11px] text-slate-400">
              {String(this.state.error?.stack ?? this.state.error?.message ?? this.state.error)}
            </pre>
            <button
              onClick={this.reset}
              className="mt-4 rounded-lg bg-brand px-5 py-2 text-sm font-medium text-white hover:bg-brand-dark"
            >
              重试
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}