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
    // 2026-05-16T05:00:00Z → KST: 2026-05-16 14:00
    const result = formatKstDateTime("2026-05-16T05:00:00Z");
    expect(result).toMatch(/^2026-05-16 14:00$/);
  });

  it("formats another KST time correctly", () => {
    // 2026-05-15T23:59:59Z → KST: 2026-05-16 08:59
    const result = formatKstDateTime("2026-05-15T23:59:59Z");
    expect(result).toMatch(/^2026-05-16 08:59$/);
  });

  it("handles midnight crossing correctly", () => {
    // 2026-05-15T15:00:00Z → KST: 2026-05-16 24:00 (ko-KR locale)
    const result = formatKstDateTime("2026-05-15T15:00:00Z");
    expect(result).toMatch(/^2026-05-16 24:00$/);
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

/* ───────────────────────────────────────────
 * EI Interpretation Formatter
 * ─────────────────────────────────────────── */
import {
  formatBiasLabel,
  formatConflictLabel,
  formatReasonCodeLabel,
  formatEvidenceStrength,
  formatReliabilityTier,
  formatImpactDirection,
  formatNovelty,
  formatImpactHorizon,
  formatEiOutput,
} from "../lib/utils";

describe("formatBiasLabel", () => {
  it('returns Korean label for neutral', () => {
    expect(formatBiasLabel("neutral")).toBe("중립");
  });
  it('returns Korean label for positive', () => {
    expect(formatBiasLabel("positive")).toBe("긍정");
  });
  it('returns Korean label for negative', () => {
    expect(formatBiasLabel("negative")).toBe("부정");
  });
  it('normalizes bearish to 부정', () => {
    expect(formatBiasLabel("bearish")).toBe("부정");
  });
  it('returns em dash for null', () => {
    expect(formatBiasLabel(null)).toBe("—");
  });
  it('returns em dash for undefined', () => {
    expect(formatBiasLabel(undefined)).toBe("—");
  });
  it('returns empty string unchanged', () => {
    expect(formatBiasLabel("")).toBe("—");
  });
});

describe("formatConflictLabel", () => {
  it('returns conflict text for true', () => {
    expect(formatConflictLabel(true)).toBe("상반된 이벤트 존재");
  });
  it('returns em dash for false', () => {
    expect(formatConflictLabel(false)).toBe("—");
  });
  it('returns em dash for null', () => {
    expect(formatConflictLabel(null)).toBe("—");
  });
  it('returns em dash for undefined', () => {
    expect(formatConflictLabel(undefined)).toBe("—");
  });
});

describe("formatReasonCodeLabel", () => {
  it('returns Korean label for known code', () => {
    expect(formatReasonCodeLabel("foreign_investor_selling")).toBe("외국인 매도");
  });
  it('returns Korean label for price_decline', () => {
    expect(formatReasonCodeLabel("price_decline")).toBe("가격 하락");
  });
  it('returns raw code for unknown code', () => {
    expect(formatReasonCodeLabel("unknown_reason_xyz")).toBe("unknown_reason_xyz");
  });
  it('handles case insensitivity', () => {
    expect(formatReasonCodeLabel("FOREIGN_INVESTOR_SELLING")).toBe("외국인 매도");
  });
});

describe("formatEvidenceStrength", () => {
  it('returns Korean labels', () => {
    expect(formatEvidenceStrength("none")).toBe("없음");
    expect(formatEvidenceStrength("weak")).toBe("약함");
    expect(formatEvidenceStrength("moderate")).toBe("보통");
    expect(formatEvidenceStrength("strong")).toBe("강함");
  });
  it('returns em dash for null', () => {
    expect(formatEvidenceStrength(null)).toBe("—");
  });
});

describe("formatReliabilityTier", () => {
  it('returns Korean labels', () => {
    expect(formatReliabilityTier("T1")).toBe("1등급 (높음)");
    expect(formatReliabilityTier("T2")).toBe("2등급");
    expect(formatReliabilityTier("T3")).toBe("3등급");
    expect(formatReliabilityTier("T4")).toBe("4등급 (낮음)");
  });
  it('returns em dash for null', () => {
    expect(formatReliabilityTier(null)).toBe("—");
  });
});

describe("formatImpactDirection", () => {
  it('returns Korean labels', () => {
    expect(formatImpactDirection("positive")).toBe("긍정");
    expect(formatImpactDirection("negative")).toBe("부정");
    expect(formatImpactDirection("neutral")).toBe("중립");
  });
  it('returns em dash for null', () => {
    expect(formatImpactDirection(null)).toBe("—");
  });
});

describe("formatNovelty", () => {
  it('returns Korean labels', () => {
    expect(formatNovelty("high")).toBe("높음");
    expect(formatNovelty("medium")).toBe("보통");
    expect(formatNovelty("low")).toBe("낮음");
  });
  it('returns em dash for null', () => {
    expect(formatNovelty(null)).toBe("—");
  });
});

describe("formatImpactHorizon", () => {
  it('returns Korean labels', () => {
    expect(formatImpactHorizon("short")).toBe("단기");
    expect(formatImpactHorizon("swing")).toBe("스윙");
    expect(formatImpactHorizon("long")).toBe("장기");
  });
  it('returns em dash for null', () => {
    expect(formatImpactHorizon(null)).toBe("—");
  });
});

describe("formatEiOutput", () => {
  it('returns null for null input', () => {
    expect(formatEiOutput(null)).toBeNull();
  });
  it('returns null for undefined input', () => {
    expect(formatEiOutput(undefined)).toBeNull();
  });
  it('returns null for empty object', () => {
    expect(formatEiOutput({})).toBeNull();
  });

  it('returns null when aggregate_view is missing', () => {
    expect(formatEiOutput({ some_field: "value" })).toBeNull();
  });

  it('formats EI aggregate_view correctly', () => {
    const result = formatEiOutput({
      aggregate_view: {
        overall_bias: 'negative',
        event_conflict: false,
        top_reason_codes: ['foreign_investor_selling', 'price_decline'],
        evidence_strength: 'moderate',
        event_count: 2,
        no_material_events: false,
      },
      interpreted_event_count: 2,
    });
    expect(result).not.toBeNull();
    expect(result!.biasLabel).toBe('부정');
    expect(result!.conflictLabel).toBe('—');
    expect(result!.reasonCodeLabels).toEqual(['외국인 매도', '가격 하락']);
    expect(result!.reasonCodes).toEqual(['foreign_investor_selling', 'price_decline']);
    expect(result!.evidenceStrengthLabel).toBe('보통');
    expect(result!.eventCount).toBe(2);
    expect(result!.hasMaterialEvents).toBe(true);
    expect(result!.operatorSummary).toContain('성향: 부정');
    expect(result!.operatorSummary).toContain('외국인 매도');
    expect(result!.operatorSummary).toContain('이벤트 2건');
  });

  it('includes conflict in operatorSummary when event_conflict is true', () => {
    const result = formatEiOutput({
      aggregate_view: {
        overall_bias: 'neutral',
        event_conflict: true,
        top_reason_codes: ['earnings_surprise'],
        evidence_strength: 'weak',
        event_count: 3,
        no_material_events: false,
      }
    });
    expect(result).not.toBeNull();
    expect(result!.biasLabel).toBe('중립');
    expect(result!.conflictLabel).toBe('상반된 이벤트 존재');
    expect(result!.operatorSummary).toContain('상반된 이벤트 존재');
  });

  it('handles no_material_events', () => {
    const result = formatEiOutput({
      aggregate_view: {
        overall_bias: 'neutral',
        event_count: 0,
        no_material_events: true,
      }
    });
    expect(result).not.toBeNull();
    expect(result!.hasMaterialEvents).toBe(false);
    expect(result!.operatorSummary).not.toContain('이벤트');
  });

  it('limits reason code labels to top 3 in operatorSummary', () => {
    const result = formatEiOutput({
      aggregate_view: {
        overall_bias: 'positive',
        top_reason_codes: ['a', 'b', 'c', 'd', 'e'],
        event_count: 5,
        no_material_events: false,
      }
    });
    expect(result!.operatorSummary).toContain(' 외');
  });

  it('handles missing fields gracefully', () => {
    const result = formatEiOutput({
      aggregate_view: {}
    });
    expect(result).not.toBeNull();
    expect(result!.biasLabel).toBe('—');
    expect(result!.conflictLabel).toBe('—');
    expect(result!.reasonCodeLabels).toEqual([]);
    expect(result!.evidenceStrengthLabel).toBe('—');
    expect(result!.eventCount).toBe(0);
    expect(result!.hasMaterialEvents).toBe(true);
    expect(result!.operatorSummary).toBe('성향: —');
  });

  it('returns new Phase 1 fields from top-level (T7)', () => {
    const result = formatEiOutput({
      aggregate_view: {
        overall_bias: 'positive',
        event_conflict: false,
        top_reason_codes: ['earnings_surprise'],
        evidence_strength: 'moderate',
        event_count: 5,
        no_material_events: false,
        interpretation_incomplete: false,
      },
      detected_event_count: 5,
      interpreted_event_count: 2,
      summary_basis: 'interpreted',
    });
    expect(result).not.toBeNull();
    // 신규 필드가 최상위 값 사용
    expect(result!.detectedEventCount).toBe(5);
    expect(result!.interpretedEventCount).toBe(2);
    expect(result!.summaryBasis).toBe('interpreted');
    // eventCount는 interpretedEventCount와 같아야 함
    expect(result!.eventCount).toBe(2);
    // operatorSummary에는 interpretedEventCount 사용
    expect(result!.operatorSummary).toContain('이벤트 2건');
  });

  it('fallback to aggregate_view when new fields are missing (T8)', () => {
    const result = formatEiOutput({
      aggregate_view: {
        overall_bias: 'negative',
        event_conflict: false,
        top_reason_codes: ['price_decline'],
        evidence_strength: 'weak',
        event_count: 3,
        no_material_events: false,
      },
      // detected_event_count, interpreted_event_count, summary_basis 없음
    });
    expect(result).not.toBeNull();
    // detectedEventCount는 aggregate_view.event_count로 fallback
    expect(result!.detectedEventCount).toBe(3);
    // interpretedEventCount는 events.length로 fallback (events 없음 → 0)
    expect(result!.interpretedEventCount).toBe(0);
    // summaryBasis는 "none"으로 fallback
    expect(result!.summaryBasis).toBe('none');
    // eventCount는 interpretedEventCount (0) 사용
    expect(result!.eventCount).toBe(0);
    // operatorSummary에 events count 없음 (interpretedEventCount=0)
    expect(result!.operatorSummary).not.toContain('이벤트');
  });

  it('returns isReconstructed=true when all events have is_reconstructed=true', () => {
    const result = formatEiOutput({
      aggregate_view: {
        overall_bias: 'neutral',
        event_conflict: false,
        evidence_strength: 'weak',
        event_count: 2,
        no_material_events: false,
      },
      events: [
        { is_reconstructed: true, summary: '재구성 이벤트 1' },
        { is_reconstructed: true, summary: '재구성 이벤트 2' },
      ],
      detected_event_count: 2,
      interpreted_event_count: 2,
      summary_basis: 'detected_only',
    });
    expect(result).not.toBeNull();
    expect(result!.isReconstructed).toBe(true);
  });

  it('returns isReconstructed=false when some events lack is_reconstructed', () => {
    const result = formatEiOutput({
      aggregate_view: {
        overall_bias: 'positive',
        event_conflict: false,
        evidence_strength: 'moderate',
        event_count: 2,
        no_material_events: false,
      },
      events: [
        { is_reconstructed: true, summary: '재구성 이벤트' },
        { summary: '정상 해석 이벤트' },
      ],
      detected_event_count: 2,
      interpreted_event_count: 2,
      summary_basis: 'interpreted',
    });
    expect(result).not.toBeNull();
    expect(result!.isReconstructed).toBe(false);
  });

  it('returns isReconstructed=false when events array is empty', () => {
    const result = formatEiOutput({
      aggregate_view: {
        overall_bias: 'neutral',
        event_conflict: false,
        evidence_strength: 'none',
        event_count: 0,
        no_material_events: true,
      },
      events: [],
      detected_event_count: 0,
      interpreted_event_count: 0,
      summary_basis: 'none',
    });
    expect(result).not.toBeNull();
    expect(result!.isReconstructed).toBe(false);
  });
});
