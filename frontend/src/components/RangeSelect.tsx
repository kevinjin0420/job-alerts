import { RANGE_OPTIONS } from "../lib/ranges";

export function RangeSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="text-xs px-2 py-1.5 rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 focus:outline-none focus:ring-1 focus:ring-neutral-500"
    >
      {RANGE_OPTIONS.map((option) => (
        <option key={option.value} value={option.value}>
          Last {option.label}
        </option>
      ))}
    </select>
  );
}

export function RefreshButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-xs px-3 py-1.5 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900"
    >
      Refresh
    </button>
  );
}
