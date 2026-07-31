import { useState } from "react";

import { useLogs } from "../api/hooks";
import type { LogEvent } from "../api/types";
import { PageHeader } from "../components/AppLayout";
import { RefreshButton } from "../components/RangeSelect";
import { SkeletonBar } from "../components/Skeleton";
import { groupLogRuns, type LogRun } from "../lib/groupLogRuns";
import { useLocalStorage } from "../lib/useLocalStorage";

const VIEW_MODE_STORAGE_KEY = "job-alerts-logs-view-mode";

type ViewMode = "flat" | "runs";

function isoTime(value: string): string {
  return new Date(value).toISOString().replace(/\.\d{3}Z$/, "Z");
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
  // Failing runs open by default - they are the reason anyone opens this page.
  const [isOpen, setIsOpen] = useState(run.failureCount > 0);

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

export function LogsPage() {
  const logs = useLogs();
  const [viewMode, setViewMode] = useLocalStorage<ViewMode>(VIEW_MODE_STORAGE_KEY, "flat");
  const [failuresOnly, setFailuresOnly] = useState(false);

  const events = logs.data?.events ?? [];
  const activeClass = "bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900";
  const inactiveClass = "hover:bg-neutral-100 dark:hover:bg-neutral-900";

  const renderBody = () => {
    if (logs.isPending) {
      return (
        <div className="space-y-2">
          {Array.from({ length: 12 }, (_, index) => (
            <SkeletonBar key={index} className="h-4 w-full" />
          ))}
        </div>
      );
    }
    if (logs.isError) {
      return <div className="text-sm text-red-600 dark:text-red-400">Failed to load logs</div>;
    }

    if (viewMode === "runs") {
      const blocks = groupLogRuns(events)
        .map((run) => ({ run, lines: failuresOnly ? run.lines.filter((line) => line.is_failure) : run.lines }))
        .filter((block) => block.lines.length > 0);
      if (blocks.length === 0) {
        return <div className="text-sm text-neutral-500 dark:text-neutral-500">No log events in this window</div>;
      }
      return blocks.map((block, index) => (
        <RunBlock key={block.run.id ?? `unknown-${index}`} run={block.run} lines={block.lines} />
      ));
    }

    const flat = failuresOnly ? events.filter((event) => event.is_failure) : events;
    if (flat.length === 0) {
      return <div className="text-sm text-neutral-500 dark:text-neutral-500">No log events in this window</div>;
    }
    return flat.map((event, index) => <LogLine key={`${event.timestamp}:${index}`} event={event} />);
  };

  return (
    <>
      <PageHeader title="Logs · last 24h">
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
        <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400">
          <input
            type="checkbox"
            checked={failuresOnly}
            onChange={(event) => setFailuresOnly(event.target.checked)}
            className="rounded-none border-neutral-300 dark:border-neutral-700"
          />
          Failures only
        </label>
        <RefreshButton onClick={() => void logs.refetch()} />
      </PageHeader>

      <div className="border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3 min-h-[200px] max-h-[calc(100vh-160px)] overflow-y-auto font-mono text-xs leading-5">
        {renderBody()}
      </div>
    </>
  );
}
