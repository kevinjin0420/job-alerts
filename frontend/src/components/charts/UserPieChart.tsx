import { Pie } from "react-chartjs-2";

import "./registerCharts";
import { chartPalette } from "../../lib/chartPalette";
import { useMediaQuery } from "../../lib/useMediaQuery";
import { useTheme } from "../../theme/ThemeContext";
import { ChartCard } from "./ChartCard";

export const UNKNOWN_USER_ID = "unknown";
const UNKNOWN_USER_LABEL = "Unknown (before per-user tracking)";
const OTHER_SLICE_ID = "__other__";
const MAX_INDIVIDUAL_SLICES = 6;

export interface UserValueRow {
  user_id: string;
  value: number;
}

export function userLabel(userId: string): string {
  return userId === UNKNOWN_USER_ID ? UNKNOWN_USER_LABEL : userId;
}

/** Alphabetical so identity decides color, not rank - stable across both charts and reloads. */
export function buildUserColorMap(userIds: Iterable<string>, isDark: boolean): Map<string, string> {
  const palette = chartPalette(isDark);
  const sorted = Array.from(new Set(userIds))
    .filter((id) => id !== UNKNOWN_USER_ID)
    .sort((a, b) => a.localeCompare(b));

  const colorMap = new Map<string, string>();
  sorted.forEach((userId, index) => {
    colorMap.set(userId, palette.series[index] ?? palette.other);
  });
  colorMap.set(UNKNOWN_USER_ID, palette.other);
  return colorMap;
}

/** Beyond MAX_INDIVIDUAL_SLICES, fold into "Other" rather than cycling the palette. */
function foldIntoTopSlices(rows: UserValueRow[]): UserValueRow[] {
  const sorted = [...rows].sort((a, b) => b.value - a.value);
  const top = sorted.slice(0, MAX_INDIVIDUAL_SLICES);
  const otherTotal = sorted.slice(MAX_INDIVIDUAL_SLICES).reduce((sum, row) => sum + row.value, 0);
  return otherTotal > 0 ? [...top, { user_id: OTHER_SLICE_ID, value: otherTotal }] : top;
}

export function UserPieChart({
  title,
  rows,
  valueLabel,
  colorMap,
  formatValue,
}: {
  title: string;
  rows: UserValueRow[];
  valueLabel: string;
  colorMap: Map<string, string>;
  formatValue: (value: number) => string;
}) {
  const { isDark } = useTheme();
  const palette = chartPalette(isDark);
  // Emails truncate to a few characters beside the pie on a phone.
  const isNarrow = useMediaQuery("(max-width: 767px)");

  const sliced = foldIntoTopSlices(rows.filter((row) => row.value > 0));
  const labelFor = (userId: string) => (userId === OTHER_SLICE_ID ? "Other" : userLabel(userId));
  const sliceColors = sliced.map((row) =>
    row.user_id === OTHER_SLICE_ID ? palette.other : (colorMap.get(row.user_id) ?? palette.other),
  );

  return (
    <ChartCard
      title={title}
      isEmpty={sliced.length === 0}
      chart={
        <div className={isNarrow ? "h-80" : "h-64"}>
          <Pie
            data={{
              labels: sliced.map((row) => labelFor(row.user_id)),
              datasets: [
                {
                  data: sliced.map((row) => row.value),
                  backgroundColor: sliceColors,
                  borderColor: sliceColors,
                  borderWidth: 2,
                },
              ],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: {
                  position: isNarrow ? "bottom" : "right",
                  labels: { color: palette.axis, usePointStyle: true, boxWidth: 8 },
                },
                tooltip: {
                  usePointStyle: true,
                  callbacks: { label: (item) => `${formatValue(item.parsed)}  ${item.label}` },
                },
              },
            }}
          />
        </div>
      }
      table={
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="text-left font-medium text-neutral-500 dark:text-neutral-500 pb-2 pr-4">User</th>
              <th className="text-right font-medium text-neutral-500 dark:text-neutral-500 pb-2 pl-4">
                {valueLabel}
              </th>
            </tr>
          </thead>
          <tbody>
            {sliced.map((row) => (
              <tr key={row.user_id}>
                <td className="py-1 pr-4">{labelFor(row.user_id)}</td>
                <td className="py-1 pl-4 text-right font-mono">{formatValue(row.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  );
}
