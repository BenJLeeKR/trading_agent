import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { formatKstDateTime, formatKstTime, formatKstElapsed, formatOrderEventReason } from "../lib/utils";

/* ───────────────────────────────────────────
 * formatKstDateTime
 * ─────────────────────────────────────────── */
describe("formatKstDateTime", () => {
  it("returns '—' for null", () => {
    expect(formatKstDateTime(null)).toBe("—");
  });

  it("returns '—' for undefined", () => {
    expect(formatKstDateTime(undefined)).toBe("—");
  });

  it("returns '—' for empty string", () => {
    expect(formatKstDateTime("")).toBe("—");
  });

  it("returns '—' for invalid date string", () => {
    expect(formatKstDateTime("not-a-date")).toBe("—");
  });

  it("formats a valid UTC ISO string to KST datetime", () => {
    // 2026-05-16T05:00:00Z → KST: 2026-05-16 14:00:00
    const result = formatKstDateTime("2026-05-16T05:00:00Z");
    expect(result).toMatch(/^2026-05-16 14:00:00 KST$/);
  });

  it("formats another KST time correctly", () => {
    // 2026-05-15T23:59:59Z → KST: 2026-05-16 08:59:59
    const result = formatKstDateTime("2026-05-15T23:59:59Z");
    expect(result).toMatch(/^2026-05-16 08:59:59 KST$/);
  });

  it("handles midnight crossing correctly", () => {
    // 2026-05-15T15:00:00Z → KST: 2026-05-16 24:00:00 (ko-KR locale)
    const result = formatKstDateTime("2026-05-15T15:00:00Z");
    expect(result).toMatch(/^2026-05-16 24:00:00 KST$/);
  });
});

/* ───────────────────────────────────────────
 * formatKstTime
 * ─────────────────────────────────────────── */
describe("formatKstTime", () => {
  it("returns '—' for null", () => {
    expect(formatKstTime(null)).toBe("—");
  });

  it("returns '—' for undefined", () => {
    expect(formatKstTime(undefined)).toBe("—");
  });

  it("returns '—' for empty string", () => {
    expect(formatKstTime("")).toBe("—");
  });

  it("returns '—' for invalid date string", () => {
    expect(formatKstTime("bad-date")).toBe("—");
  });

  it("formats a valid UTC ISO string to KST compact time", () => {
    // 2026-05-16T05:00:00Z → KST: 05-16 14:00
    const result = formatKstTime("2026-05-16T05:00:00Z");
    expect(result).toBe("05-16 14:00");
  });

  it("formats midnight crossing correctly", () => {
    // 2026-05-15T15:00:00Z → KST: 05-16 24:00 (ko-KR locale)
    const result = formatKstTime("2026-05-15T15:00:00Z");
    expect(result).toBe("05-16 24:00");
  });
});

/* ───────────────────────────────────────────
 * formatKstElapsed
 * ─────────────────────────────────────────── */
describe("formatKstElapsed", () => {
  beforeEach(() => {
    // Fix "now" to 2026-05-16T07:00:00Z (= KST 2026-05-16 16:00:00)
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-16T07:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns '—' for null", () => {
    expect(formatKstElapsed(null)).toBe("—");
  });

  it("returns '—' for undefined", () => {
    expect(formatKstElapsed(undefined)).toBe("—");
  });

  it("returns '—' for empty string", () => {
    expect(formatKstElapsed("")).toBe("—");
  });

  it("returns '—' for invalid date string", () => {
    expect(formatKstElapsed("invalid")).toBe("—");
  });

  it('shows "방금 전" for events less than 1 minute ago', () => {
    // now=07:00:00Z, event=06:59:31Z (29초 전)
    const result = formatKstElapsed("2026-05-16T06:59:31Z");
    expect(result).toContain("방금 전");
    expect(result).toMatch(/^2026-05-16 15:59:31 KST \(방금 전\)$/);
  });

  it('shows "3분 전" for events 3 minutes ago', () => {
    // now=07:00:00Z, event=06:57:00Z (3분 전)
    const result = formatKstElapsed("2026-05-16T06:57:00Z");
    expect(result).toContain("3분 전");
    expect(result).toMatch(/^2026-05-16 15:57:00 KST \(3분 전\)$/);
  });

  it('shows "1시간 30분 전" for events 90 minutes ago', () => {
    // now=07:00:00Z, event=05:30:00Z (1시간 30분 전)
    const result = formatKstElapsed("2026-05-16T05:30:00Z");
    expect(result).toContain("1시간 30분 전");
    expect(result).toMatch(/^2026-05-16 14:30:00 KST \(1시간 30분 전\)$/);
  });

  it('shows "N일 전" for events more than 24 hours ago', () => {
    // now=07:00:00Z, event=2026-05-14T07:00:00Z (2일 전)
    const result = formatKstElapsed("2026-05-14T07:00:00Z");
    expect(result).toContain("2일 전");
    expect(result).toMatch(/^2026-05-14 16:00:00 KST \(2일 전\)$/);
  });

  it("handles future dates without elapsed suffix", () => {
    // Future date → no elapsed suffix
    const result = formatKstElapsed("2026-05-17T07:00:00Z");
    expect(result).toMatch(/^2026-05-17 16:00:00 KST \(\)$/);
  });
});

/* ───────────────────────────────────────────
 * formatOrderEventReason
 * ─────────────────────────────────────────── */
describe("formatOrderEventReason", () => {
  // TC1: null → "—"
  it('returns "—" for null', () => {
    expect(formatOrderEventReason(null)).toBe("—");
  });

  // TC2: undefined → "—"
  it('returns "—" for undefined', () => {
    expect(formatOrderEventReason(undefined)).toBe("—");
  });

  // TC3: empty string → "—"
  it('returns "—" for empty string', () => {
    expect(formatOrderEventReason("")).toBe("—");
  });

  // TC4: known code → 한글 라벨
  it('returns "체결 확인" for FILL_CONFIRMED', () => {
    expect(formatOrderEventReason("FILL_CONFIRMED")).toBe("체결 확인");
  });

  // TC5: another known code
  it('returns "차단됨" for BLOCKED', () => {
    expect(formatOrderEventReason("BLOCKED")).toBe("차단됨");
  });

  // TC6: numeric string → broker order ID format
  it('returns "브로커 주문번호: 12345678" for "12345678"', () => {
    expect(formatOrderEventReason("12345678")).toBe("브로커 주문번호: 12345678");
  });

  // TC7: unknown raw code → 원문 fallback
  it('returns "UNKNOWN_REASON" for unknown code', () => {
    expect(formatOrderEventReason("UNKNOWN_REASON")).toBe("UNKNOWN_REASON");
  });

  // TC8: manual_paper_resolution → 운영자 수동 해소
  it('returns "운영자 수동 해소" for manual_paper_resolution', () => {
    expect(formatOrderEventReason("manual_paper_resolution")).toBe("운영자 수동 해소");
  });

  // TC9: all known codes in REASON_LABEL_MAP produce non-empty Korean labels
  it("all entries in REASON_LABEL_MAP are covered", () => {
    const knownCodes = [
      "BLOCKED",
      "UNCERTAIN",
      "RECONCILE_RESOLVED",
      "MANUAL_RESOLVE",
      "manual_paper_resolution",
      "WS_FILL",
      "FILL_CONFIRMED",
      "REJECTED",
    ];
    for (const code of knownCodes) {
      const result = formatOrderEventReason(code);
      expect(result).not.toBe("—");
      expect(result).not.toBe(code); // must be translated
    }
  });
});

/* ───────────────────────────────────────────
 * formatOrderEventReason with fieldMap
 * ─────────────────────────────────────────── */
describe("formatOrderEventReason with fieldMap", () => {
  it("fieldMap이 제공되면 local map보다 우선 조회해야 함", () => {
    const fieldMap: Record<string, string> = {
      BLOCKED: "metadata-차단됨",
      CUSTOM: "커스텀 라벨",
    };
    expect(formatOrderEventReason("BLOCKED", fieldMap)).toBe("metadata-차단됨");
  });

  it("fieldMap에 없는 code는 local map fallback", () => {
    const fieldMap: Record<string, string> = { CUSTOM: "커스텀" };
    expect(formatOrderEventReason("WS_FILL", fieldMap)).toBe("WS 체결 수신");
  });

  it("fieldMap이 null이면 기존 동작 유지", () => {
    expect(formatOrderEventReason("BLOCKED", null)).toBe("차단됨");
  });

  it("fieldMap이 undefined면 기존 동작 유지", () => {
    expect(formatOrderEventReason("BLOCKED")).toBe("차단됨");
  });

  it("fieldMap과 local map 모두에 없는 code는 broker ID heuristic", () => {
    expect(formatOrderEventReason("12345", {})).toBe("브로커 주문번호: 12345");
  });
});
