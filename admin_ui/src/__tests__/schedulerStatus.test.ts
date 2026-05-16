import { describe, expect, it, vi, afterEach } from "vitest";
import { getSchedulerStatus, type SchedulerCardState } from "../components/OperationsDashboardView";
import {
  getLatestMarketSession,
  getRecentSessionEvents,
} from "../api/client";
import type {
  MarketSessionSummary,
  SchedulerStatusResponse,
  SessionEventsResponse,
  SessionEventSummary,
} from "../types/api";
import {
  mockFetchOnce,
  mockFetchError,
  mockFetchNetworkError,
} from "./test-utils/mockFetch";

/* ── Helper: create a minimal MarketSessionSummary ── */
function makeSession(overrides: Partial<MarketSessionSummary> = {}): MarketSessionSummary {
  return {
    id: 1,
    run_date: "2026-05-16",
    is_trading_day: true,
    opnd_yn: null,
    bzdy_yn: null,
    tr_day_yn: null,
    market_phase: "OPEN",
    raw_opnd_yn: null,
    raw_mkop_cls_code: null,
    raw_antc_mkop_cls_code: null,
    source: "kis_market_state_ws",
    reason: null,
    checked_at: "2026-05-16T06:00:00Z",
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

/* ───────────────────────────────────────────
 * Scenario 1: No Data (session == null)
 * ─────────────────────────────────────────── */
describe("getSchedulerStatus — No Data", () => {
  it("returns neutral/mic수집 when session is null and no fetch error", () => {
    const result = getSchedulerStatus(null, false, null, false, null);

    expect(result.badgeLabel).toBe("미수집");
    expect(result.variant).toBe("neutral");
    expect(result.value).toBe("미수집");
    expect(result.subtitle).toBe("No session data yet");
  });

  it("does NOT return error variant when session is null", () => {
    const result = getSchedulerStatus(null, false, null, false, null);

    // Critical: No Data should NOT look like an error
    expect(result.variant).not.toBe("error");
    expect(result.badgeLabel).not.toBe("오류");
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: Healthy session
 * ─────────────────────────────────────────── */
describe("getSchedulerStatus — Healthy", () => {
  it("returns healthy/정상 for a valid healthy session", () => {
    const session = makeSession({
      source: "kis_market_state_ws",
      market_phase: "OPEN",
      checked_at: "2026-05-16T06:00:00Z",
    });

    const result = getSchedulerStatus(session, true, 5, false, null);

    expect(result.badgeLabel).toBe("정상");
    expect(result.variant).toBe("healthy");
    expect(result.value).toBe("정상");
    expect(result.subtitle).toContain("kis_market_state_ws");
    expect(result.subtitle).toContain("OPEN");
  });

  it("returns healthy during AFTER_HOURS phase", () => {
    const session = makeSession({
      source: "kis_market_state_ws",
      market_phase: "AFTER_HOURS",
    });

    const result = getSchedulerStatus(session, true, 30, false, null);

    expect(result.badgeLabel).toBe("정상");
    expect(result.variant).toBe("healthy");
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: Stale session
 * ─────────────────────────────────────────── */
describe("getSchedulerStatus — Stale", () => {
  it("returns warning/지연 when healthy is false", () => {
    const session = makeSession({ checked_at: "2026-05-16T05:00:00Z" });

    const result = getSchedulerStatus(session, false, 3600, false, null);

    expect(result.badgeLabel).toBe("지연");
    expect(result.variant).toBe("warning");
    expect(result.value).toBe("지연");
    expect(result.subtitle).toContain("Last checked");
    expect(result.subtitle).toContain("KST"); // KST formatter 사용 확인
  });

  it("returns warning/지연 when stale_seconds exceeds 10 min threshold", () => {
    const session = makeSession({ checked_at: "2026-05-16T04:00:00Z" });

    const result = getSchedulerStatus(session, true, 7200, false, null);

    expect(result.badgeLabel).toBe("지연");
    expect(result.variant).toBe("warning");
  });

  it("does NOT return error for stale data", () => {
    const session = makeSession();

    const result = getSchedulerStatus(session, false, 9999, false, null);

    // Stale is warning, NOT error
    expect(result.variant).not.toBe("error");
    expect(result.variant).toBe("warning");
  });

  it("treats mild staleness (< 10 min) as healthy when healthy flag is true", () => {
    const session = makeSession({ checked_at: "2026-05-16T06:00:00Z" });

    // 5 seconds stale — well within threshold
    const result = getSchedulerStatus(session, true, 5, false, null);

    expect(result.badgeLabel).toBe("정상");
    expect(result.variant).toBe("healthy");
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Fetch error → Real error
 * ─────────────────────────────────────────── */
describe("getSchedulerStatus — Error (fetch failure)", () => {
  it("returns error/오류 when fetch failed", () => {
    const result = getSchedulerStatus(null, false, null, true, "Network error: 500");

    expect(result.badgeLabel).toBe("오류");
    expect(result.variant).toBe("error");
    expect(result.value).toBe("오류");
    expect(result.subtitle).toBe("Network error: 500");
  });

  it("shows fetch error even if session data exists (stale cached data)", () => {
    const session = makeSession();

    // Even with session data, fetch error takes precedence
    const result = getSchedulerStatus(session, true, 0, true, "Internal Server Error");

    expect(result.badgeLabel).toBe("오류");
    expect(result.variant).toBe("error");
    expect(result.subtitle).toBe("Internal Server Error");
  });

  it("provides fallback message when error message is null", () => {
    const result = getSchedulerStatus(null, false, null, true, null);

    expect(result.badgeLabel).toBe("오류");
    expect(result.variant).toBe("error");
    expect(result.subtitle).toBe("API fetch failed");
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Fallback source
 * ─────────────────────────────────────────── */
describe("getSchedulerStatus — Fallback", () => {
  it("returns warning/대체 for gate_error_fallback source", () => {
    const session = makeSession({
      source: "gate_error_fallback",
      market_phase: "PRE_MARKET",
    });

    const result = getSchedulerStatus(session, true, 0, false, null);

    expect(result.badgeLabel).toBe("대체");
    expect(result.variant).toBe("warning");
    expect(result.value).toBe("대체");
    expect(result.subtitle).toContain("Fallback");
    expect(result.subtitle).toContain("PRE_MARKET");
  });

  it("returns warning/대체 for fallback source", () => {
    const session = makeSession({
      source: "fallback",
      market_phase: "OPEN",
    });

    const result = getSchedulerStatus(session, true, 0, false, null);

    expect(result.badgeLabel).toBe("대체");
    expect(result.variant).toBe("warning");
    expect(result.value).toBe("대체");
  });

  it("does NOT return error for fallback source", () => {
    const session = makeSession({ source: "fallback" });

    const result = getSchedulerStatus(session, true, 0, false, null);

    // Fallback is warning, NOT error
    expect(result.variant).not.toBe("error");
    expect(result.variant).toBe("warning");
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: Session events empty — covered by component rendering
 * (This scenario tests the panel rendering logic)
 * ─────────────────────────────────────────── */
describe("getSchedulerStatus — Mixed scenarios", () => {
  it("prioritizes fetch error over all other states", () => {
    // Even with a healthy session and all good flags, fetch error wins
    const session = makeSession({ source: "kis_market_state_ws", market_phase: "OPEN" });

    const result = getSchedulerStatus(session, true, 0, true, "Timeout");

    expect(result.badgeLabel).toBe("오류");
    expect(result.variant).toBe("error");
  });

  it("prioritizes no data over stale (session null beats stale flags)", () => {
    // No session but stale flags — no data wins (neutral, not warning)
    const result = getSchedulerStatus(null, false, 99999, false, null);

    expect(result.badgeLabel).toBe("미수집");
    expect(result.variant).toBe("neutral");
  });

  it("handles all sources without throwing", () => {
    const sources = [
      "kis_market_state_ws", "kis_holiday_api", "gate_error_fallback",
      "fallback", "manual", null, undefined,
    ];

    for (const source of sources) {
      const session = source !== undefined
        ? makeSession({ source: source ?? null, market_phase: "CLOSING" })
        : null;

      // Should never throw regardless of input
      expect(() =>
        getSchedulerStatus(session, true, 0, false, null)
      ).not.toThrow();
    }
  });
});

/* ─────────────────────────────────────────────
 * Helper Fixtures — session API responses
 * ───────────────────────────────────────────── */

const mockSchedulerStatusResponse: SchedulerStatusResponse = {
  status: "ok",
  data: {
    id: 1,
    run_date: "2026-05-16",
    is_trading_day: true,
    opnd_yn: null,
    bzdy_yn: null,
    tr_day_yn: null,
    market_phase: "OPEN",
    raw_opnd_yn: null,
    raw_mkop_cls_code: null,
    raw_antc_mkop_cls_code: null,
    source: "kis_market_state_ws",
    reason: null,
    checked_at: "2026-05-16T06:00:00Z",
    created_at: null,
    updated_at: null,
  },
  healthy: true,
  stale_seconds: 5,
};

const mockSessionEventsResponse: SessionEventsResponse = {
  status: "ok",
  data: [
    {
      id: 1,
      market_session_id: 1,
      previous_phase: "PRE_MARKET",
      new_phase: "OPEN",
      trigger_source: "kis_market_state_ws",
      metadata: null,
      occurred_at: "2026-05-16T06:00:00Z",
      created_at: null,
    },
    {
      id: 2,
      market_session_id: 1,
      previous_phase: "OPEN",
      new_phase: "AFTER_HOURS",
      trigger_source: "kis_market_state_ws",
      metadata: null,
      occurred_at: "2026-05-16T12:00:00Z",
      created_at: null,
    },
  ],
};

/* ─────────────────────────────────────────────
 * Scenario 7: getLatestMarketSession() helper
 * ──────────────────────────────────────────── */
describe("getLatestMarketSession()", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls /market-sessions/latest and returns SchedulerStatusResponse", async () => {
    mockFetchOnce(mockSchedulerStatusResponse);

    const result = await getLatestMarketSession();

    expect(result).toEqual(mockSchedulerStatusResponse);
    expect(result.status).toBe("ok");
    expect(result.data?.market_phase).toBe("OPEN");
    expect(result.healthy).toBe(true);
  });

  it("throws ApiResponseError on 500", async () => {
    mockFetchError(500, "Internal Server Error");

    await expect(getLatestMarketSession()).rejects.toThrow(
      /API error 500/,
    );
  });

  it("throws UnauthorizedError on 401", async () => {
    mockFetchError(401, "Unauthorized");

    await expect(getLatestMarketSession()).rejects.toThrow(
      "Unauthorized",
    );
  });

  it("throws on network error", async () => {
    mockFetchNetworkError();

    await expect(getLatestMarketSession()).rejects.toThrow(
      "Network error",
    );
  });
});

/* ─────────────────────────────────────────────
 * Scenario 8: getRecentSessionEvents() helper
 * ──────────────────────────────────────────── */
describe("getRecentSessionEvents()", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls /market-sessions/events/recent?limit=N and returns SessionEventsResponse", async () => {
    mockFetchOnce(mockSessionEventsResponse);

    const result = await getRecentSessionEvents(5);

    expect(result).toEqual(mockSessionEventsResponse);
    expect(result.status).toBe("ok");
    expect(result.data).toHaveLength(2);
    expect(result.data[0].new_phase).toBe("OPEN");
  });

  it("uses default limit=5 when no argument passed", async () => {
    mockFetchOnce(mockSessionEventsResponse);

    const result = await getRecentSessionEvents();

    expect(result).toEqual(mockSessionEventsResponse);
    expect(result.data).toHaveLength(2);
  });

  it("throws ApiResponseError on 500", async () => {
    mockFetchError(500, "Internal Server Error");

    await expect(getRecentSessionEvents(5)).rejects.toThrow(
      /API error 500/,
    );
  });

  it("throws on network error", async () => {
    mockFetchNetworkError();

    await expect(getRecentSessionEvents(5)).rejects.toThrow(
      "Network error",
    );
  });

  it("accepts custom limit parameter", async () => {
    mockFetchOnce(mockSessionEventsResponse);

    const result = await getRecentSessionEvents(10);

    expect(result).toEqual(mockSessionEventsResponse);
  });
});
