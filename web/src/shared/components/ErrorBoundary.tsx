import { Component, type ReactNode, type ErrorInfo } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * React Error Boundary — 捕获子树未处理异常，显示降级 UI 而非白屏。
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  reset() {
    this.setState({ hasError: false, error: null });
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
          <AlertTriangle className="h-10 w-10 text-red-400 opacity-80" />
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-[var(--color-foreground)]">页面渲染出错</p>
            <p className="max-w-xs text-xs text-[var(--color-muted-foreground)] break-words">
              {this.state.error?.message ?? "未知错误"}
            </p>
          </div>
          <button
            onClick={() => this.reset()}
            className="flex items-center gap-2 rounded-md border border-[var(--color-border)] px-4 py-2 text-xs hover:bg-[var(--color-accent)] transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
