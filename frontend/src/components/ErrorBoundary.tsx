import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  error: Error | null;
}

/** In the old multi-page dashboard a broken page could not take down navigation.
 * In an SPA an uncaught render error blanks the whole app, so one boundary keeps
 * a failed route recoverable instead of leaving a white screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Unhandled render error:", error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (error === null) {
      return this.props.children;
    }
    return (
      <div className="min-h-dvh flex items-center justify-center p-6">
        <div className="w-full max-w-md rounded-none border border-red-200 dark:border-red-900 bg-white dark:bg-neutral-900 p-6">
          <h1 className="text-sm font-semibold uppercase tracking-wide text-red-600 dark:text-red-400">
            Something broke
          </h1>
          <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">{error.message}</p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="mt-4 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900 text-sm font-medium px-3 py-1.5"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }
}
