import { Line } from "react-chartjs-2";

import "./registerCharts";
import { chartPalette } from "../../lib/chartPalette";
import { formatLocalDate } from "../../lib/formatDate";
import { useTheme } from "../../theme/ThemeContext";
import { ChartCard } from "./ChartCard";

export interface TimestampedPoint {
  timestamp: string;
}

export interface SeriesDefinition<T> {
  key: keyof T & string;
  label: string;
  colorIndex: number;
}

/** Normalized so the component needs no index signature on the caller's point type. */
interface PlottedRow {
  timestamp: string;
  values: number[];
}

function formatTimeTick(iso: string): string {
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toPlottedRows<T extends TimestampedPoint>(data: T[], series: SeriesDefinition<T>[]): PlottedRow[] {
  return data.map((point) => ({
    timestamp: point.timestamp,
    values: series.map((definition) => Number(point[definition.key]) || 0),
  }));
}

function zeroFilledRows(seriesCount: number, windowMinutes: number): PlottedRow[] {
  const now = Date.now();
  const zeroRow = (milliseconds: number): PlottedRow => ({
    timestamp: new Date(milliseconds).toISOString(),
    values: Array.from({ length: seriesCount }, () => 0),
  });
  return [zeroRow(now - windowMinutes * 60 * 1000), zeroRow(now)];
}

export function TimeSeriesChart<T extends TimestampedPoint>({
  title,
  series,
  data,
  windowMinutes,
  yFormat = (value: number) => String(value),
  yAxisLabel,
  emptyMeansZero = false,
}: {
  title: string;
  series: SeriesDefinition<T>[];
  data: T[];
  windowMinutes: number;
  yFormat?: (value: number) => string;
  yAxisLabel?: string;
  emptyMeansZero?: boolean;
}) {
  const { isDark } = useTheme();
  const palette = chartPalette(isDark);

  // Empty can mean genuinely zero activity rather than missing data.
  const rows =
    data.length === 0 && emptyMeansZero ? zeroFilledRows(series.length, windowMinutes) : toPlottedRows(data, series);

  return (
    <ChartCard
      title={title}
      isEmpty={rows.length === 0}
      chart={
        <div className="h-56">
          <Line
            data={{
              labels: rows.map((row) => formatTimeTick(row.timestamp)),
              datasets: series.map((definition, seriesIndex) => ({
                label: definition.label,
                data: rows.map((row) => row.values[seriesIndex] ?? 0),
                borderColor: palette.series[definition.colorIndex],
                backgroundColor: palette.series[definition.colorIndex],
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 4,
                pointHitRadius: 12,
                tension: 0,
              })),
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              interaction: { mode: "index", intersect: false },
              plugins: {
                legend: {
                  display: series.length > 1,
                  labels: { color: palette.axis, usePointStyle: true, boxWidth: 8 },
                },
                tooltip: {
                  usePointStyle: true,
                  callbacks: {
                    title: (items) => {
                      const row = rows[items[0]?.dataIndex ?? 0];
                      return row ? formatLocalDate(Date.parse(row.timestamp) / 1000) : "";
                    },
                    label: (item) => `${yFormat(Number(item.parsed.y ?? 0))}  ${item.dataset.label ?? ""}`,
                  },
                },
              },
              scales: {
                x: {
                  border: { color: palette.baseline },
                  grid: { color: palette.gridline },
                  ticks: { color: palette.axis, autoSkip: true, maxTicksLimit: 6, maxRotation: 0 },
                  title: { display: true, text: "Time", color: palette.axis, font: { size: 11 } },
                },
                y: {
                  beginAtZero: true,
                  border: { color: palette.baseline },
                  grid: { color: palette.gridline },
                  ticks: { color: palette.axis, callback: (value) => yFormat(Number(value)) },
                  title: {
                    display: yAxisLabel !== undefined,
                    text: yAxisLabel ?? "",
                    color: palette.axis,
                    font: { size: 11 },
                  },
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
              <th className="text-left font-medium text-neutral-500 dark:text-neutral-500 pb-2 pr-4">Time</th>
              {series.map((definition) => (
                <th
                  key={definition.key}
                  className="text-right font-medium text-neutral-500 dark:text-neutral-500 pb-2 pl-4"
                >
                  {definition.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.timestamp}>
                <td className="py-1 pr-4 font-mono">{formatLocalDate(Date.parse(row.timestamp) / 1000)}</td>
                {series.map((definition, seriesIndex) => (
                  <td key={definition.key} className="py-1 pl-4 text-right font-mono">
                    {row.values[seriesIndex] ?? "-"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  );
}
