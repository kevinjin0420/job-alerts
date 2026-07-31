import { useMemo, useState } from "react";

import { useAdminActivity } from "../api/hooks";
import type { AdminActivity } from "../api/types";
import { PageHeader } from "../components/AppLayout";
import { RangeSelect, RefreshButton } from "../components/RangeSelect";
import { SkeletonBar } from "../components/Skeleton";
import { ChartCardError } from "../components/charts/ChartCard";
import { UserPieChart, buildUserColorMap, userLabel } from "../components/charts/UserPieChart";
import { formatLocalDate } from "../lib/formatDate";
import { DEFAULT_RANGE, resolveRange } from "../lib/ranges";
import { useLocalStorage } from "../lib/useLocalStorage";
import { useTheme } from "../theme/ThemeContext";

const RANGE_STORAGE_KEY = "job-alerts-activity-range";

interface NotificationRow {
  user_id: string;
  company_name: string;
  title: string;
  url: string;
  seen_at: number;
  fit_score?: number | null;
}

function flattenNotifications(activity: AdminActivity | undefined): NotificationRow[] {
  const rows: NotificationRow[] = [];
  for (const entry of activity?.notifications_by_user ?? []) {
    for (const notification of entry.notifications) {
      rows.push({ user_id: entry.user_id, ...notification });
    }
  }
  rows.sort((a, b) => b.seen_at - a.seen_at);
  return rows;
}

export function ActivityPage() {
  const [rangeValue, setRangeValue] = useLocalStorage(RANGE_STORAGE_KEY, DEFAULT_RANGE);
  const range = resolveRange(rangeValue);
  const activity = useAdminActivity(range.value);
  const { isDark } = useTheme();

  const [search, setSearch] = useState("");
  const [userFilter, setUserFilter] = useState("");

  const allRows = useMemo(() => flattenNotifications(activity.data), [activity.data]);

  const tokenRows = useMemo(
    () =>
      (activity.data?.token_usage_by_user ?? []).map((row) => ({
        user_id: row.user_id,
        value: row.input_tokens + row.output_tokens,
      })),
    [activity.data],
  );
  const notificationCountRows = useMemo(
    () =>
      (activity.data?.notifications_by_user ?? []).map((entry) => ({
        user_id: entry.user_id,
        value: entry.notifications.length,
      })),
    [activity.data],
  );

  const colorMap = useMemo(
    () => buildUserColorMap([...tokenRows, ...notificationCountRows].map((row) => row.user_id), isDark),
    [tokenRows, notificationCountRows, isDark],
  );

  const filteredRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return allRows.filter((row) => {
      if (userFilter && row.user_id !== userFilter) {
        return false;
      }
      if (!query) {
        return true;
      }
      return `${row.company_name} ${row.title}`.toLowerCase().includes(query);
    });
  }, [allRows, search, userFilter]);

  const filterableUserIds = useMemo(
    () => Array.from(new Set(allRows.map((row) => row.user_id))).sort((a, b) => a.localeCompare(b)),
    [allRows],
  );

  const formatCount = (value: number) => Math.round(value).toLocaleString();

  return (
    <div className="flex flex-col min-h-0 flex-1">
      <PageHeader title={`Activity · last ${range.label}`}>
        <RangeSelect value={range.value} onChange={setRangeValue} />
        <RefreshButton onClick={() => void activity.refetch()} />
      </PageHeader>

      <div className="grid gap-6 xl:grid-cols-2 mb-8">
        {activity.isError ? (
          <>
            <ChartCardError title="Token usage by user" message="Failed to load activity" />
            <ChartCardError title="Notifications sent by user" message="Failed to load activity" />
          </>
        ) : activity.isPending ? (
          <>
            <SkeletonBar className="h-72 w-full" />
            <SkeletonBar className="h-72 w-full" />
          </>
        ) : (
          <>
            <UserPieChart
              title="Token usage by user"
              rows={tokenRows}
              valueLabel="Tokens"
              colorMap={colorMap}
              formatValue={formatCount}
            />
            <UserPieChart
              title="Notifications sent by user"
              rows={notificationCountRows}
              valueLabel="Notifications"
              colorMap={colorMap}
              formatValue={formatCount}
            />
          </>
        )}
      </div>

      <h3 className="text-xs font-semibold tracking-widest uppercase text-neutral-500 dark:text-neutral-500 mb-3">
        Notifications sent
      </h3>
      <div className="flex items-center gap-3 mb-3">
        <input
          type="text"
          placeholder="Search company or title…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="flex-1 rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-neutral-500"
        />
        <select
          value={userFilter}
          onChange={(event) => setUserFilter(event.target.value)}
          className="text-sm px-2 py-2 rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 focus:outline-none focus:ring-1 focus:ring-neutral-500"
        >
          <option value="">All users</option>
          {filterableUserIds.map((userId) => (
            <option key={userId} value={userId}>
              {userLabel(userId)}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1 min-h-0 border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 overflow-y-auto">
        <table className="w-full table-fixed border-collapse text-sm">
          <thead>
            <tr className="sticky top-0 bg-white dark:bg-neutral-900 border-b border-neutral-200 dark:border-neutral-800 text-left text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-500">
              <th className="px-3 py-2 font-medium w-3/12">User</th>
              <th className="px-3 py-2 font-medium w-2/12">Company</th>
              <th className="px-3 py-2 font-medium w-4/12">Title</th>
              <th className="px-3 py-2 font-medium w-1/12">Fit score</th>
              <th className="px-3 py-2 font-medium w-2/12">Sent at</th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-sm text-neutral-500 dark:text-neutral-500">
                  No notifications match
                </td>
              </tr>
            ) : (
              filteredRows.map((row) => (
                <tr
                  key={`${row.user_id}:${row.url}:${row.seen_at}`}
                  className="border-b border-neutral-100 dark:border-neutral-900 last:border-0"
                >
                  <td className="px-3 py-2 align-middle break-words">{userLabel(row.user_id)}</td>
                  <td className="px-3 py-2 align-middle break-words">{row.company_name || "-"}</td>
                  <td className="px-3 py-2 align-middle break-words">
                    {row.url ? (
                      <a href={row.url} target="_blank" rel="noopener" className="hover:underline">
                        {row.title || "-"}
                      </a>
                    ) : (
                      row.title || "-"
                    )}
                  </td>
                  <td className="px-3 py-2 align-middle font-mono text-xs">{row.fit_score ?? "-"}</td>
                  <td className="px-3 py-2 align-middle font-mono text-xs">
                    {row.seen_at ? formatLocalDate(row.seen_at) : "-"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
