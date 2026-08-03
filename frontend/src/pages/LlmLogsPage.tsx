import { useState } from "react";

import { useLlmLogs } from "../api/hooks";
import type { LlmLogEvent } from "../api/types";
import { PageHeader } from "../components/AppLayout";
import { RefreshButton } from "../components/RangeSelect";
import { SkeletonBar } from "../components/Skeleton";

function isoTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** user_content already starts with "Company: ...\nTitle: ..." - truncating it reads as a useful summary on its own. */
function previewOf(userContent: string): string {
  const flattened = userContent.replace(/\s+/g, " ").trim();
  return flattened.length > 100 ? `${flattened.slice(0, 100)}...` : flattened;
}

function verdictOf(event: LlmLogEvent): string {
  if (event.event === "classifier_call") {
    const score = event.fit_score !== null && event.fit_score !== undefined ? ` (${event.fit_score})` : "";
    return `${event.fit ? "fits" : "dismissed"}${score}`;
  }
  return event.is_job_posting ? "valid posting" : "rejected";
}

/** watch/validator.py and watch/classifier.py both render a missing description as this literal string. */
function isMissingDescription(event: LlmLogEvent): boolean {
  return event.user_content.includes("Description: not available");
}

const EVENT_FILTERS: { label: string; value: string | null }[] = [
  { label: "All", value: null },
  { label: "Classifier", value: "classifier_call" },
  { label: "Validator", value: "validity_check" },
];

function LlmLogRow({ event }: { event: LlmLogEvent }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="border border-neutral-200 dark:border-neutral-800 mb-2 last:mb-0">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left bg-neutral-100 dark:bg-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-700 text-xs"
      >
        <span className="flex items-center gap-3 min-w-0">
          <span className="text-neutral-400 dark:text-neutral-600 shrink-0">{isoTime(event.created_at)}</span>
          <span className="shrink-0 px-1.5 py-0.5 border border-neutral-300 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400">
            {event.event}
          </span>
          {event.event === "validity_check" && isMissingDescription(event) && (
            <span className="shrink-0 px-1.5 py-0.5 border border-amber-400 dark:border-amber-600 text-amber-700 dark:text-amber-400">
              no JD
            </span>
          )}
          <span className="truncate text-neutral-700 dark:text-neutral-300">{previewOf(event.user_content)}</span>
        </span>
        <span className="flex items-center gap-3 shrink-0 text-neutral-500 dark:text-neutral-500">
          <span>{event.model}</span>
          <span className={event.fit === false || event.is_job_posting === false ? "text-red-600 dark:text-red-400" : ""}>
            {verdictOf(event)}
          </span>
        </span>
      </button>
      {isOpen && (
        <div className="p-3 space-y-3 text-xs">
          <div>
            <div className="text-neutral-500 dark:text-neutral-500 mb-1">System prompt</div>
            <pre className="whitespace-pre-wrap break-words bg-neutral-50 dark:bg-neutral-950 border border-neutral-200 dark:border-neutral-800 p-2 font-mono">
              {event.system_content}
            </pre>
          </div>
          <div>
            <div className="text-neutral-500 dark:text-neutral-500 mb-1">Listing sent to the model</div>
            <pre className="whitespace-pre-wrap break-words bg-neutral-50 dark:bg-neutral-950 border border-neutral-200 dark:border-neutral-800 p-2 font-mono">
              {event.user_content}
            </pre>
          </div>
          <div>
            <div className="text-neutral-500 dark:text-neutral-500 mb-1">Response</div>
            <pre className="whitespace-pre-wrap break-words bg-neutral-50 dark:bg-neutral-950 border border-neutral-200 dark:border-neutral-800 p-2 font-mono">
              {event.reason}
            </pre>
          </div>
          <div className="text-neutral-500 dark:text-neutral-500">
            {event.input_tokens} input / {event.output_tokens} output tokens
            {event.user_id ? ` · ${event.user_id}` : ""}
          </div>
        </div>
      )}
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 12 }, (_, index) => (
        <SkeletonBar key={index} className="h-8 w-full" />
      ))}
    </div>
  );
}

export function LlmLogsPage() {
  const [eventFilter, setEventFilter] = useState<string | null>(null);
  const llmLogs = useLlmLogs(eventFilter);

  const renderBody = () => {
    if (llmLogs.isPending) {
      return <LoadingSkeleton />;
    }
    if (llmLogs.isError) {
      return <div className="text-sm text-red-600 dark:text-red-400">Failed to load LLM logs</div>;
    }
    const events = llmLogs.data.pages.flatMap((page) => page.events);
    if (events.length === 0) {
      return <div className="text-sm text-neutral-500 dark:text-neutral-500">No LLM calls yet</div>;
    }
    return (
      <>
        {events.map((event, index) => (
          <LlmLogRow key={`${event.created_at}:${index}`} event={event} />
        ))}
        {llmLogs.hasNextPage && (
          <button
            type="button"
            onClick={() => void llmLogs.fetchNextPage()}
            disabled={llmLogs.isFetchingNextPage}
            className="mt-2 w-full text-xs px-3 py-1.5 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900 disabled:opacity-40"
          >
            {llmLogs.isFetchingNextPage ? "Loading..." : "Load more"}
          </button>
        )}
      </>
    );
  };

  return (
    <>
      <PageHeader title="LLM Logs">
        <RefreshButton onClick={() => void llmLogs.refetch()} />
      </PageHeader>

      <div className="flex items-center gap-2 mb-2">
        {EVENT_FILTERS.map((filter) => (
          <button
            key={filter.label}
            type="button"
            onClick={() => setEventFilter(filter.value)}
            className={`text-xs px-2 py-1 border ${
              eventFilter === filter.value
                ? "border-neutral-500 dark:border-neutral-400 bg-neutral-200 dark:bg-neutral-700"
                : "border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900"
            }`}
          >
            {filter.label}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3 overflow-y-auto">
        {renderBody()}
      </div>
    </>
  );
}
