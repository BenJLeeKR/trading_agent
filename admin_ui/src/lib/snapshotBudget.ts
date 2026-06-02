export type SnapshotBudgetCounters = {
  preCheck: number;
  budgetExhausted: number;
  apiFailure: number;
  afterHoursSkip: number;
};

export function parseSnapshotBudgetCounters(
  summaryJson: Record<string, number> | null | undefined,
): SnapshotBudgetCounters {
  const sj = summaryJson ?? {};
  return {
    preCheck: sj["VTTC8908R_pre_check"] ?? 0,
    budgetExhausted: sj["VTTC8908R_budget_exhausted"] ?? 0,
    apiFailure: sj["VTTC8908R_api_failure"] ?? 0,
    afterHoursSkip: sj["after_hours_skip"] ?? 0,
  };
}

export function formatSnapshotBudgetParts(
  counters: SnapshotBudgetCounters,
): string[] {
  const parts: string[] = [];
  if (counters.preCheck > 0) parts.push(`pre-check 대체 ${counters.preCheck}회`);
  if (counters.budgetExhausted > 0) parts.push(`budget exhausted ${counters.budgetExhausted}회`);
  if (counters.apiFailure > 0) parts.push(`API 실패 fallback ${counters.apiFailure}회`);
  if (counters.afterHoursSkip > 0) parts.push(`장후 skip ${counters.afterHoursSkip}회`);
  return parts;
}

export function countHardSnapshotFallbacks(
  counters: SnapshotBudgetCounters,
): number {
  return counters.budgetExhausted + counters.apiFailure;
}
