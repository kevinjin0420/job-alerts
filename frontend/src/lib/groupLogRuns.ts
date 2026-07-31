import type { LogEvent } from "../api/types";

export interface LogRun {
  id: string | null;
  startTime: string | null;
  endTime: string | null;
  durationMs: number | null;
  lines: LogEvent[];
  failureCount: number;
}

const START_PATTERN = /^START RequestId: (\S+)/;
const END_PATTERN = /^END RequestId: (\S+)/;
const REPORT_PATTERN = /^REPORT RequestId: (\S+)\s+Duration: ([\d.]+) ms/;

/** Lambda only tags the platform START/END/REPORT lines with a RequestId, not the
 * print() lines between them, so untagged lines are attributed to whichever run
 * is currently open. Tagged lines go to the run they name: REPORT always arrives
 * *after* END, so resolving it through the open stack would attribute every
 * duration to a phantom run instead of the invocation it belongs to.
 *
 * A genuinely overlapping invocation (rare - a manual scan overlapping the
 * schedule) still misattributes its untagged lines; not solved here.
 *
 * Takes events newest-first (as /api/logs returns them) and returns runs newest-first. */
export function groupLogRuns(events: LogEvent[]): LogRun[] {
  const ascending = [...events].reverse();
  const runs: LogRun[] = [];
  const runsById = new Map<string, LogRun>();
  const openStack: LogRun[] = [];
  let unknownRun: LogRun | null = null;

  const currentRun = (): LogRun => {
    const open = openStack[openStack.length - 1];
    if (open !== undefined) {
      return open;
    }
    if (unknownRun === null) {
      unknownRun = { id: null, startTime: null, endTime: null, durationMs: null, lines: [], failureCount: 0 };
      runs.push(unknownRun);
    }
    return unknownRun;
  };

  for (const event of ascending) {
    const startId = START_PATTERN.exec(event.message)?.[1];
    if (startId !== undefined) {
      const run: LogRun = {
        id: startId,
        startTime: event.timestamp,
        endTime: null,
        durationMs: null,
        lines: [],
        failureCount: 0,
      };
      runs.push(run);
      runsById.set(startId, run);
      openStack.push(run);
    }

    const endId = END_PATTERN.exec(event.message)?.[1];
    const reportMatch = REPORT_PATTERN.exec(event.message);
    const taggedId = startId ?? endId ?? reportMatch?.[1];
    const run = (taggedId !== undefined ? runsById.get(taggedId) : undefined) ?? currentRun();

    run.lines.push(event);
    if (event.is_failure) {
      run.failureCount += 1;
    }
    if (reportMatch?.[2] !== undefined) {
      run.durationMs = Number.parseFloat(reportMatch[2]);
    }
    if (endId !== undefined) {
      run.endTime = event.timestamp;
      const openIndex = openStack.lastIndexOf(run);
      if (openIndex !== -1) {
        openStack.splice(openIndex, 1);
      }
    }
  }

  return runs.reverse();
}
