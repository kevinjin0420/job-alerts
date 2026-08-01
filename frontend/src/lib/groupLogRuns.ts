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

/** REPORT arrives after END pops the stack, so tagged lines resolve by RequestId. Newest-first in and out. */
export function groupLogRuns(events: LogEvent[]): LogRun[] {
  const ascending = [...events].reverse();
  const runs: LogRun[] = [];
  const runsById = new Map<string, LogRun>();
  const openStack: LogRun[] = [];
  let unknownRun: LogRun | null = null;

  // ponytail: untagged lines follow the open stack, so overlapping invocations misattribute theirs.
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
