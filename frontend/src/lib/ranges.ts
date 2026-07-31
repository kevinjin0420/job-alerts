export interface RangeOption {
  value: string;
  label: string;
  minutes: number;
}

/** Mirrors dashboard/app.py's METRICS_RANGE_PRESETS_MINUTES - keep both in sync. */
export const RANGE_OPTIONS: readonly RangeOption[] = [
  { value: "5m", label: "5 minutes", minutes: 5 },
  { value: "10m", label: "10 minutes", minutes: 10 },
  { value: "15m", label: "15 minutes", minutes: 15 },
  { value: "30m", label: "30 minutes", minutes: 30 },
  { value: "1h", label: "1 hour", minutes: 60 },
  { value: "2h", label: "2 hours", minutes: 120 },
  { value: "3h", label: "3 hours", minutes: 180 },
  { value: "6h", label: "6 hours", minutes: 360 },
  { value: "12h", label: "12 hours", minutes: 720 },
  { value: "24h", label: "24 hours", minutes: 1440 },
  { value: "2d", label: "2 days", minutes: 2880 },
  { value: "3d", label: "3 days", minutes: 4320 },
  { value: "1w", label: "1 week", minutes: 10080 },
];

export const DEFAULT_RANGE = "24h";

export function resolveRange(value: string): RangeOption {
  const found = RANGE_OPTIONS.find((option) => option.value === value);
  if (found) {
    return found;
  }
  const fallback = RANGE_OPTIONS.find((option) => option.value === DEFAULT_RANGE);
  if (!fallback) {
    throw new Error("DEFAULT_RANGE is not present in RANGE_OPTIONS");
  }
  return fallback;
}
