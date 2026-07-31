// Run: npm run check
import assert from "node:assert/strict";

import { matchesFitScore, parseFitScoreFilter } from "./fitScoreFilter.ts";

assert.deepEqual(parseFitScoreFilter("90"), { operator: "=", value: 90 });
assert.deepEqual(parseFitScoreFilter(">=90"), { operator: ">=", value: 90 });
assert.deepEqual(parseFitScoreFilter("  < 20 "), { operator: "<", value: 20 });
assert.equal(parseFitScoreFilter(""), null);
assert.equal(parseFitScoreFilter("abc"), null);
assert.equal(parseFitScoreFilter(">="), null);
assert.equal(parseFitScoreFilter("9 0"), null);

assert.equal(matchesFitScore({ operator: ">=", value: 90 }, 90), true);
assert.equal(matchesFitScore({ operator: ">=", value: 90 }, 89), false);
assert.equal(matchesFitScore({ operator: "<", value: 50 }, 49), true);
assert.equal(matchesFitScore({ operator: "=", value: 75 }, 75), true);
assert.equal(matchesFitScore({ operator: "=", value: 75 }, 76), false);

console.log("fitScoreFilter: all assertions passed");
