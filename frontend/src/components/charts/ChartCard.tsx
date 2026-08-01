import { useState, type ReactNode } from "react";

// min-w-0: grid items default to min-width:auto, letting the canvas push the card off-viewport.
const FIGURE_CLASS =
  "min-w-0 border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-4 py-4";

/** Chart.js has no accessible/no-JS equivalent, so every card carries a table twin. */
export function ChartCard({
  title,
  isEmpty,
  chart,
  table,
}: {
  title: string;
  isEmpty: boolean;
  chart: ReactNode;
  table: ReactNode;
}) {
  const [showingTable, setShowingTable] = useState(false);

  return (
    <figure className={FIGURE_CLASS}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-semibold tracking-widest uppercase text-neutral-500 dark:text-neutral-500">
          {title}
        </h4>
        {!isEmpty && (
          <button
            type="button"
            onClick={() => setShowingTable((current) => !current)}
            className="text-xs px-2 py-1 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900"
          >
            {showingTable ? "View as chart" : "View as table"}
          </button>
        )}
      </div>
      {isEmpty ? (
        <div className="text-sm text-neutral-500 dark:text-neutral-500 py-6">No data in the selected window</div>
      ) : showingTable ? (
        <div className="overflow-x-auto">{table}</div>
      ) : (
        chart
      )}
    </figure>
  );
}

export function ChartCardError({ title, message }: { title: string; message: string }) {
  return (
    <figure className={FIGURE_CLASS}>
      <h4 className="text-xs font-semibold tracking-widest uppercase text-neutral-500 dark:text-neutral-500 mb-3">
        {title}
      </h4>
      <div className="text-sm text-red-600 dark:text-red-400 py-6">{message}</div>
    </figure>
  );
}
