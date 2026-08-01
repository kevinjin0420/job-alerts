import { useListings, useMetrics } from "../api/hooks";
import type { Listing, Metrics } from "../api/types";
import { PageHeader } from "../components/AppLayout";
import { RangeSelect, RefreshButton } from "../components/RangeSelect";
import { SkeletonBar } from "../components/Skeleton";
import { TimeSeriesChart } from "../components/charts/TimeSeriesChart";
import { formatLocalDate } from "../lib/formatDate";
import { DEFAULT_RANGE, resolveRange } from "../lib/ranges";
import { useLocalStorage } from "../lib/useLocalStorage";

// Matches aws/config.env's SCHEDULE_RATE.
const SCHEDULE_INTERVAL_SECONDS = 300;
const RANGE_STORAGE_KEY = "job-alerts-metrics-range";

interface ListingCounts {
  total: number;
  notified: number;
  dismissed: number;
  seeded: number;
}

function countByStatus(listings: Listing[]): ListingCounts {
  const counts: ListingCounts = { total: listings.length, notified: 0, dismissed: 0, seeded: 0 };
  for (const listing of listings) {
    if (listing.status === "notified" || listing.status === "dismissed" || listing.status === "seeded") {
      counts[listing.status] += 1;
    }
  }
  return counts;
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : String(value);
}

function formatPercent(numerator: number, denominator: number): string {
  if (!denominator) {
    return "-";
  }
  return `${((numerator / denominator) * 100).toFixed(1)}%`;
}

function buildSections(metrics: Metrics, counts: ListingCounts): Array<{ title: string; cards: Array<[string, string]> }> {
  const nextRunAt = metrics.last_ran ? Date.parse(metrics.last_ran) + SCHEDULE_INTERVAL_SECONDS * 1000 : null;
  return [
    {
      title: "Schedule",
      cards: [
        ["Last ran", metrics.last_ran ? formatLocalDate(Date.parse(metrics.last_ran) / 1000) : "-"],
        ["Next scheduled run", nextRunAt ? formatLocalDate(nextRunAt / 1000) : "-"],
      ],
    },
    {
      title: "Execution",
      cards: [
        ["Invocations", formatNumber(metrics.invocations)],
        ["Errors", formatNumber(metrics.errors)],
        ["Success rate", formatPercent(metrics.invocations - (metrics.errors ?? 0), metrics.invocations)],
        ["Avg duration (ms)", formatNumber(metrics.avg_duration_ms)],
      ],
    },
    {
      title: "Listings",
      cards: [
        ["Total tracked", formatNumber(counts.total)],
        ["Notified", formatNumber(counts.notified)],
        ["Dismissed", formatNumber(counts.dismissed)],
        ["Seeded (first run)", formatNumber(counts.seeded)],
      ],
    },
  ];
}

export function MetricsPage() {
  const [rangeValue, setRangeValue] = useLocalStorage(RANGE_STORAGE_KEY, DEFAULT_RANGE);
  const range = resolveRange(rangeValue);
  const metrics = useMetrics(range.value);
  const listings = useListings(range.value);

  const refresh = () => {
    void metrics.refetch();
    void listings.refetch();
  };

  const isPending = metrics.isPending || listings.isPending;
  const sections =
    metrics.data && listings.data ? buildSections(metrics.data, countByStatus(listings.data.listings)) : [];

  return (
    <>
      <PageHeader title="Metrics">
        <RangeSelect value={range.value} onChange={setRangeValue} />
        <RefreshButton onClick={refresh} />
      </PageHeader>

      {metrics.isError || listings.isError ? (
        <div className="border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-4 py-6 text-sm text-red-600 dark:text-red-400">
          Failed to load metrics
        </div>
      ) : isPending ? (
        <div className="space-y-8">
          {[0, 1, 2].map((section) => (
            <SkeletonBar key={section} className="h-24 w-full" />
          ))}
        </div>
      ) : (
        <div className="space-y-8">
          {sections.map((section) => (
            <section key={section.title}>
              <h3 className="text-xs font-semibold tracking-widest uppercase text-neutral-500 dark:text-neutral-500 mb-3">
                {section.title}
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-px bg-neutral-200 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-800">
                {section.cards.map(([label, value]) => (
                  <div key={label} className="bg-white dark:bg-neutral-900 px-4 py-4">
                    <div className="text-xs text-neutral-500 dark:text-neutral-500">{label}</div>
                    <div className="text-2xl font-mono mt-1">{value}</div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <section className="mt-8">
        <h3 className="text-xs font-semibold tracking-widest uppercase text-neutral-500 dark:text-neutral-500 mb-3">
          Charts
        </h3>
        <div className="grid gap-6 xl:grid-cols-2">
          <TimeSeriesChart
            title="Duration"
            series={[{ key: "value", label: "Duration (ms)", colorIndex: 0 }]}
            data={metrics.data?.duration_series ?? []}
            windowMinutes={range.minutes}
            yFormat={(value) => `${Math.round(value)}ms`}
            yAxisLabel="Duration (ms)"
          />
          <TimeSeriesChart
            title="Classifier backlog"
            series={[{ key: "count", label: "Uncached listings", colorIndex: 1 }]}
            data={metrics.data?.backlog_series ?? []}
            windowMinutes={range.minutes}
            yFormat={(value) => String(Math.round(value))}
            yAxisLabel="Listings"
          />
          <TimeSeriesChart
            title="Listings processed"
            series={[
              { key: "new", label: "New", colorIndex: 0 },
              { key: "notified", label: "Notified", colorIndex: 1 },
              { key: "dismissed", label: "Dismissed", colorIndex: 2 },
            ]}
            data={metrics.data?.throughput_series ?? []}
            windowMinutes={range.minutes}
            yFormat={(value) => String(Math.round(value))}
            yAxisLabel="Listings"
          />
          <TimeSeriesChart
            title="Token usage"
            series={[
              { key: "input_tokens", label: "Input tokens", colorIndex: 0 },
              { key: "output_tokens", label: "Output tokens", colorIndex: 1 },
            ]}
            data={metrics.data?.token_usage_series ?? []}
            windowMinutes={range.minutes}
            yFormat={(value) => Math.round(value).toLocaleString()}
            yAxisLabel="Tokens"
            emptyMeansZero
          />
        </div>
      </section>
    </>
  );
}
