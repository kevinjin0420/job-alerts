// Run: npm run check
import assert from "node:assert/strict";

import { groupLogRuns } from "./groupLogRuns.ts";
import type { LogEvent } from "../api/types.ts";

const event = (timestamp: string, message: string, is_failure = false): LogEvent => ({
  timestamp,
  message,
  is_failure,
});

// /api/logs returns newest-first, so these are in descending time order.
// Note REPORT lands after END - that is the real Lambda ordering.
const newestFirst: LogEvent[] = [
  event("2026-07-31T00:00:06Z", "REPORT RequestId: req-2\tDuration: 1234.56 ms\tBilled..."),
  event("2026-07-31T00:00:05Z", "END RequestId: req-2"),
  event("2026-07-31T00:00:04Z", "Source 'apple' failed: boom", true),
  event("2026-07-31T00:00:03Z", "START RequestId: req-2 Version: $LATEST"),
  event("2026-07-31T00:00:02Z", "END RequestId: req-1"),
  event("2026-07-31T00:00:01Z", "Scan complete: 1 user(s)"),
  event("2026-07-31T00:00:00Z", "START RequestId: req-1 Version: $LATEST"),
];

const runs = groupLogRuns(newestFirst);

assert.equal(runs.length, 2, "no phantom run for the post-END REPORT line");
assert.equal(runs[0]?.id, "req-2", "newest run comes first");
assert.equal(runs[1]?.id, "req-1");

// The REPORT arrives after END pops the stack, so it must be attributed by RequestId.
assert.equal(runs[0]?.durationMs, 1234.56);
assert.equal(runs[0]?.failureCount, 1);
assert.equal(runs[0]?.startTime, "2026-07-31T00:00:03Z");
assert.equal(runs[0]?.endTime, "2026-07-31T00:00:05Z");
assert.equal(runs[0]?.lines.length, 4, "START + failure + END + REPORT");

assert.equal(runs[1]?.failureCount, 0);
assert.equal(runs[1]?.durationMs, null);
assert.equal(runs[1]?.lines.length, 3, "START + print + END");

// Lines before the first START in the window land in a synthetic run with no id.
const orphaned = groupLogRuns([
  event("2026-07-31T00:00:01Z", "START RequestId: req-3 Version: $LATEST"),
  event("2026-07-31T00:00:00Z", "leftover line from a run that started before the window"),
]);
assert.equal(orphaned.length, 2);
assert.equal(
  orphaned.some((run) => run.id === null && run.lines.length === 1),
  true,
);

assert.deepEqual(groupLogRuns([]), []);

console.log("groupLogRuns: all assertions passed");
