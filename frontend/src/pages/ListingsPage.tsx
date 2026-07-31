import { useMemo, useState } from "react";

import { useListings, useRetryListing } from "../api/hooks";
import type { Listing } from "../api/types";
import { PageHeader } from "../components/AppLayout";
import { Spinner, TableSkeleton } from "../components/Skeleton";
import { matchesFitScore, parseFitScoreFilter } from "../lib/fitScoreFilter";
import { formatLocalDate } from "../lib/formatDate";

const STATUS_STYLES: Record<string, string> = {
  notified: "text-green-700 dark:text-green-400",
  dismissed: "text-red-600 dark:text-red-400",
  seeded: "text-neutral-500 dark:text-neutral-500",
};

const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "None" },
  { value: "notified", label: "Notified" },
  { value: "dismissed", label: "Dismissed" },
  { value: "seeded", label: "Seeded" },
];

interface ColumnFilters {
  company: string;
  title: string;
  status: string;
  fitScore: string;
}

const EMPTY_FILTERS: ColumnFilters = { company: "", title: "", status: "", fitScore: "" };

const FILTER_FIELD_CLASS =
  "w-full rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-2 py-1 text-xs font-normal normal-case tracking-normal text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-1 focus:ring-neutral-500";

function applyFilters(listings: Listing[], filters: ColumnFilters): Listing[] {
  const fitFilter = filters.fitScore ? parseFitScoreFilter(filters.fitScore) : null;
  const company = filters.company.toLowerCase();
  const title = filters.title.toLowerCase();

  return listings.filter((listing) => {
    if (filters.status && listing.status !== filters.status) {
      return false;
    }
    if (company && !listing.company_name.toLowerCase().includes(company)) {
      return false;
    }
    if (title && !listing.title.toLowerCase().includes(title)) {
      return false;
    }
    if (fitFilter) {
      if (listing.fit_score === undefined || listing.fit_score === null) {
        return false;
      }
      if (!matchesFitScore(fitFilter, Number(listing.fit_score))) {
        return false;
      }
    }
    return true;
  });
}

function ListingRow({ listing }: { listing: Listing }) {
  const retry = useRetryListing();
  const title = listing.title || "(unknown - seen before this tracking existed)";

  return (
    <tr className="border-b border-neutral-200 dark:border-neutral-800 last:border-0">
      <td className="px-3 py-2 align-middle break-words">{listing.company_name || "-"}</td>
      <td className="px-3 py-2 align-middle break-words">
        <div className="min-h-[2.5rem] flex items-center">
          <span className="line-clamp-2">
            {listing.url ? (
              <a href={listing.url} target="_blank" rel="noopener" className="hover:underline">
                {title}
              </a>
            ) : (
              title
            )}
          </span>
        </div>
      </td>
      <td className="px-3 py-2 align-middle break-words font-mono text-xs">{listing.source || "-"}</td>
      <td className={`px-3 py-2 align-middle ${STATUS_STYLES[listing.status] ?? ""}`}>
        {listing.status || "legacy"}
      </td>
      <td className="px-3 py-2 align-middle break-words">
        <div className="min-h-[2.5rem] flex items-center">
          <span className="line-clamp-2">{listing.reason || "-"}</span>
        </div>
      </td>
      <td className="px-3 py-2 align-middle font-mono text-xs">{listing.fit_score ?? "-"}</td>
      <td className="px-3 py-2 align-middle font-mono text-xs">
        {listing.seen_at ? formatLocalDate(listing.seen_at) : "-"}
      </td>
      <td className="px-3 py-2 align-middle text-right">
        {listing.status === "dismissed" && (
          <button
            type="button"
            onClick={() => retry.mutate(listing.listing_id)}
            disabled={retry.isPending}
            className="text-xs px-2 py-1 rounded-none border border-neutral-300 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-900 disabled:opacity-40"
          >
            {retry.isPending ? "…" : "Retry"}
          </button>
        )}
      </td>
    </tr>
  );
}

export function ListingsPage() {
  const { data, isPending, isError, isFetching, refetch } = useListings();
  const [filters, setFilters] = useState<ColumnFilters>(EMPTY_FILTERS);

  const listings = useMemo(() => applyFilters(data?.listings ?? [], filters), [data, filters]);

  const setFilter = (key: keyof ColumnFilters, value: string) =>
    setFilters((current) => ({ ...current, [key]: value }));

  return (
    <>
      <PageHeader title="Listings">
        {isFetching && !isPending && <Spinner className="w-3.5 h-3.5 text-neutral-400" />}
        <button
          type="button"
          onClick={() => void refetch()}
          className="text-xs px-3 py-1.5 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900"
        >
          Refresh
        </button>
      </PageHeader>

      <div className="border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 max-h-[calc(100vh-160px)] overflow-y-auto overflow-x-hidden">
        {isPending && <TableSkeleton />}
        {isError && <div className="px-4 py-6 text-sm text-red-600 dark:text-red-400">Failed to load listings</div>}
        {!isPending && !isError && (
          <table className="w-full table-fixed border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-white dark:bg-neutral-900">
              <tr className="text-left text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-500">
                <th className="px-3 py-2 font-medium w-1/12">Company</th>
                <th className="px-3 py-2 font-medium w-2/12">Title</th>
                <th className="px-3 py-2 font-medium w-1/12">Source</th>
                <th className="px-3 py-2 font-medium w-1/12">Status</th>
                <th className="px-3 py-2 font-medium w-4/12">Reason</th>
                <th className="px-3 py-2 font-medium w-1/12">Fit score</th>
                <th className="px-3 py-2 font-medium w-1/12">Seen</th>
                <th className="px-3 py-2 font-medium w-1/12" />
              </tr>
              <tr className="border-b border-neutral-200 dark:border-neutral-800">
                <th className="px-2 py-1.5">
                  <input
                    type="text"
                    placeholder="Filter…"
                    value={filters.company}
                    onChange={(event) => setFilter("company", event.target.value)}
                    className={FILTER_FIELD_CLASS}
                  />
                </th>
                <th className="px-2 py-1.5">
                  <input
                    type="text"
                    placeholder="Filter…"
                    value={filters.title}
                    onChange={(event) => setFilter("title", event.target.value)}
                    className={FILTER_FIELD_CLASS}
                  />
                </th>
                <th className="px-2 py-1.5" />
                <th className="px-2 py-1.5">
                  <select
                    value={filters.status}
                    onChange={(event) => setFilter("status", event.target.value)}
                    className={FILTER_FIELD_CLASS}
                  >
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </th>
                <th className="px-2 py-1.5" />
                <th className="px-2 py-1.5">
                  <input
                    type="text"
                    placeholder=">=90"
                    value={filters.fitScore}
                    onChange={(event) => setFilter("fitScore", event.target.value)}
                    className={FILTER_FIELD_CLASS}
                  />
                </th>
                <th className="px-2 py-1.5" />
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {listings.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-sm text-neutral-500 dark:text-neutral-500">
                    {data && data.listings.length === 0 ? "No listings yet" : "No listings match"}
                  </td>
                </tr>
              ) : (
                listings.map((listing) => <ListingRow key={listing.listing_id} listing={listing} />)
              )}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
