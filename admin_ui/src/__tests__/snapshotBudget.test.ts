import { describe, expect, it } from "vitest";
import {
  countHardSnapshotFallbacks,
  formatSnapshotBudgetParts,
  parseSnapshotBudgetCounters,
} from "../lib/snapshotBudget";

describe("snapshotBudget helpers", () => {
  it("formats pre-check fallback as lowered-severity label", () => {
    const counters = parseSnapshotBudgetCounters({
      VTTC8908R_pre_check: 2,
      VTTC8908R_budget_exhausted: 1,
      VTTC8908R_api_failure: 1,
      after_hours_skip: 3,
    });

    expect(formatSnapshotBudgetParts(counters)).toEqual([
      "pre-check 대체 2회",
      "budget exhausted 1회",
      "API 실패 fallback 1회",
      "장후 skip 3회",
    ]);
  });

  it("counts only hard fallbacks for alerting", () => {
    const counters = parseSnapshotBudgetCounters({
      VTTC8908R_pre_check: 5,
      VTTC8908R_budget_exhausted: 2,
      VTTC8908R_api_failure: 1,
    });

    expect(countHardSnapshotFallbacks(counters)).toBe(3);
  });
});
