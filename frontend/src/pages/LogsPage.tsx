import { useEffect, useState } from "react";

import { useLogRuns, useLogs, useLogSearch } from "../api/hooks";
import type { LogEvent, LogRun } from "../api/types";
import { PageHeader } from "../components/AppLayout";
import { RefreshButton } from "../components/RangeSelect";
import { SkeletonBar } from "../components/Skeleton";
import { LAMBDA_OPTIONS } from "../lib/lambdas";
import { useLocalStorage } from "../lib/useLocalStorage";

const VIEW_MODE_STORAGE_KEY = "job-alerts-logs-view-mode";
const LAMBDA_STORAGE_KEY = "job-alerts-logs-lambda";
const SEARCH_DEBOUNCE_MS = 400;

type ViewMode = "flat" | "runs";

function isoTime(value: string): string {
  return new Date(value).toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** Insights queries take seconds - debouncing avoids firing one per keystroke. */
function useDebouncedValue(value: string, delayMs: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

function LogLine({ event }: { event: LogEvent }) {
  return (
    <div className={event.is_failure ? "text-red-600 dark:text-red-400" : "text-neutral-700 dark:text-neutral-300"}>
      <span className="text-neutral-400 dark:text-neutral-600 mr-2">{isoTime(event.timestamp)}</span>
      {event.message}
    </div>
  );
}

function RunBlock({ run, lines }: { run: LogRun; lines: LogEvent[] }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="border border-neutral-200 dark:border-neutral-800 mb-2 last:mb-0">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        className="w-full flex items-center justify-between gap-3 px-2 py-1.5 text-left bg-neutral-100 dark:bg-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-700"
      >
        <span className="flex items-center gap-2 truncate">
          <span className="text-neutral-400 dark:text-neutral-600">{run.startTime ? isoTime(run.startTime) : ""}</span>
          <span className="truncate">
            {run.id ? `RequestId ${run.id}` : "Lines before first START in window"}
          </span>
        </span>
        <span className="flex items-center gap-2 shrink-0 text-neutral-500 dark:text-neutral-500">
          {run.durationMs !== null && <span>{run.durationMs.toFixed(0)} ms</span>}
          {run.failureCount > 0 && (
            <span className="text-red-600 dark:text-red-400">{run.failureCount} failure(s)</span>
          )}
          <span>{run.lines.length} line(s)</span>
        </span>
      </button>
      {isOpen && (
        <div className="p-2">
          {lines.map((event, index) => (
            <LogLine key={`${event.timestamp}:${index}`} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}

function LoadMoreButton({ onClick, loading, label }: { onClick: () => void; loading: boolean; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      className="mt-2 w-full text-xs px-3 py-1.5 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900 disabled:opacity-40"
    >
      {loading ? "Loading..." : label}
    </button>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 12 }, (_, index) => (
        <SkeletonBar key={index} className="h-4 w-full" />
      ))}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="text-sm text-neutral-500 dark:text-neutral-500">{text}</div>;
}

function ErrorState({ text }: { text: string }) {
  return <div className="text-sm text-red-600 dark:text-red-400">{text}</div>;
}

export function LogsPage() {
  const [viewMode, setViewMode] = useLocalStorage<ViewMode>(VIEW_MODE_STORAGE_KEY, "flat");
  const [lambdaKey, setLambdaKey] = useLocalStorage(LAMBDA_STORAGE_KEY, "watch");
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const searchQuery = useDebouncedValue(searchInput.trim(), SEARCH_DEBOUNCE_MS);
  const isSearching = searchQuery.length > 0;

  const logs = useLogs(lambdaKey);
  const runsQuery = useLogRuns(lambdaKey);
  const searchResults = useLogSearch(searchQuery, lambdaKey);

  const activeClass = "bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900";
  const inactiveClass = "hover:bg-neutral-100 dark:hover:bg-neutral-900";

  const renderSearchBody = () => {
    if (searchResults.isPending) {
      return <LoadingSkeleton />;
    }
    if (searchResults.isError) {
      return <ErrorState text="Search failed" />;
    }
    const events = searchResults.data.pages.flatMap((page) => page.events);
    const filtered = failuresOnly ? events.filter((event) => event.is_failure) : events;
    if (filtered.length === 0) {
      return <EmptyState text={`No matches for "${searchQuery}"`} />;
    }
    return (
      <>
        {filtered.map((event, index) => (
          <LogLine key={`${event.timestamp}:${index}`} event={event} />
        ))}
        {searchResults.hasNextPage && (
          <LoadMoreButton
            onClick={() => void searchResults.fetchNextPage()}
            loading={searchResults.isFetchingNextPage}
            label="Load more matches"
          />
        )}
      </>
    );
  };

  const renderRunsBody = () => {
    if (runsQuery.isPending) {
      return <LoadingSkeleton />;
    }
    if (runsQuery.isError) {
      return <ErrorState text="Failed to load logs" />;
    }
    const runs = runsQuery.data.pages.flatMap((page) => page.runs);
    const blocks = runs
      .map((run) => ({ run, lines: failuresOnly ? run.lines.filter((line) => line.is_failure) : run.lines }))
      .filter((block) => block.lines.length > 0);
    if (blocks.length === 0) {
      return <EmptyState text="No log events in this window" />;
    }
    return (
      <>
        {blocks.map((block, index) => (
          <RunBlock key={block.run.id ?? `unknown-${index}`} run={block.run} lines={block.lines} />
        ))}
        {runsQuery.hasNextPage && (
          <LoadMoreButton
            onClick={() => void runsQuery.fetchNextPage()}
            loading={runsQuery.isFetchingNextPage}
            label="Load more runs"
          />
        )}
      </>
    );
  };

  const renderFlatBody = () => {
    if (logs.isPending) {
      return <LoadingSkeleton />;
    }
    if (logs.isError) {
      return <ErrorState text="Failed to load logs" />;
    }
    const events = logs.data.events;
    const flat = failuresOnly ? events.filter((event) => event.is_failure) : events;
    if (flat.length === 0) {
      return <EmptyState text="No log events in this window" />;
    }
    return flat.map((event, index) => <LogLine key={`${event.timestamp}:${index}`} event={event} />);
  };

  const renderBody = () => {
    if (isSearching) {
      return renderSearchBody();
    }
    return viewMode === "runs" ? renderRunsBody() : renderFlatBody();
  };

  const refresh = () => {
    if (isSearching) {
      void searchResults.refetch();
    } else if (viewMode === "runs") {
      void runsQuery.refetch();
    } else {
      void logs.refetch();
    }
  };

  return (
    <>
      <PageHeader title="Logs">
        <select
          value={lambdaKey}
          onChange={(event) => setLambdaKey(event.target.value)}
          className="text-xs px-2 py-1.5 rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 focus:outline-none focus:ring-1 focus:ring-neutral-500"
        >
          {LAMBDA_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Search logs..."
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          className="text-xs px-3 py-1.5 rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 focus:outline-none focus:ring-1 focus:ring-neutral-500 w-40"
        />
        {!isSearching && (
          <div className="flex items-center border border-neutral-300 dark:border-neutral-700 text-xs">
            <button
              type="button"
              onClick={() => setViewMode("flat")}
              className={`px-3 py-1.5 ${viewMode === "flat" ? activeClass : inactiveClass}`}
            >
              Flat
            </button>
            <button
              type="button"
              onClick={() => setViewMode("runs")}
              className={`px-3 py-1.5 ${viewMode === "runs" ? activeClass : inactiveClass}`}
            >
              By run
            </button>
          </div>
        )}
        <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400">
          <input
            type="checkbox"
            checked={failuresOnly}
            onChange={(event) => setFailuresOnly(event.target.checked)}
            className="rounded-none border-neutral-300 dark:border-neutral-700"
          />
          Failures only
        </label>
        <RefreshButton onClick={refresh} />
      </PageHeader>

      <div className="flex-1 min-h-0 border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3 overflow-y-auto font-mono text-xs leading-5">
        {renderBody()}
      </div>
    </>
  );
}
