/* ───────────────────────────────────────────
 * Unit tests for getEnumLabel()
 *
 * The hook itself (useEnumMetadata) is tested indirectly via
 * integration tests in orderDetail.test.tsx.  Here we focus on
 * the pure function getEnumLabel() which has no React dependency.
 * ─────────────────────────────────────────── */

import { describe, it, expect } from "vitest";
import { getEnumLabel } from "../../hooks/useEnumMetadata";
import type { EnumFieldMetadataSchema } from "../../types/api";

const mockFieldMap: Record<string, EnumFieldMetadataSchema> = {
  order_type: {
    field: "order_type",
    type: "enum",
    values: [
      {
        value: "limit",
        label: "지정가",
        description: null,
        broker_code: "00",
        supported: true,
      },
      {
        value: "market",
        label: "시장가",
        description: null,
        broker_code: "01",
        supported: true,
      },
      {
        value: "stop",
        label: "조건부지정가",
        description: "KIS adapter currently unsupported",
        broker_code: "02",
        supported: false,
      },
      {
        value: "stop_limit",
        label: "조건부지정가",
        description: "KIS adapter currently unsupported",
        broker_code: "03",
        supported: false,
      },
    ],
  },
  side: {
    field: "side",
    type: "enum",
    values: [
      { value: "buy", label: "매수", description: null, broker_code: null, supported: true },
      { value: "sell", label: "매도", description: null, broker_code: null, supported: true },
      { value: "hold", label: "보류", description: null, broker_code: null, supported: true },
    ],
  },
  order_status: {
    field: "order_status",
    type: "enum",
    values: [
      { value: "draft", label: "초안", description: null, broker_code: null, supported: true },
      { value: "validated", label: "검증됨", description: null, broker_code: null, supported: true },
      { value: "pending_submit", label: "제출 대기", description: null, broker_code: null, supported: true },
      { value: "submitted", label: "제출됨", description: null, broker_code: null, supported: true },
      { value: "acknowledged", label: "확인됨", description: null, broker_code: null, supported: true },
      { value: "partially_filled", label: "부분 체결", description: null, broker_code: null, supported: true },
      { value: "filled", label: "체결", description: null, broker_code: null, supported: true },
      { value: "cancel_pending", label: "취소 대기", description: null, broker_code: null, supported: true },
      { value: "cancelled", label: "취소됨", description: null, broker_code: null, supported: true },
      { value: "rejected", label: "거부됨", description: null, broker_code: null, supported: true },
      { value: "expired", label: "만료", description: null, broker_code: null, supported: true },
      { value: "reconcile_required", label: "조정 필요", description: null, broker_code: null, supported: true },
    ],
  },
  decision_type: {
    field: "decision_type",
    type: "enum",
    values: [
      { value: "approve", label: "승인", description: null, broker_code: null, supported: true },
      { value: "reject", label: "거부", description: null, broker_code: null, supported: true },
      { value: "hold", label: "보류", description: null, broker_code: null, supported: true },
      { value: "watch", label: "관찰", description: null, broker_code: null, supported: true },
      { value: "exit", label: "청산", description: null, broker_code: null, supported: true },
      { value: "reduce", label: "축소", description: null, broker_code: null, supported: true },
    ],
  },
};

describe("getEnumLabel", () => {
  /* ── Happy path ───────────────────────────────────── */

  it("returns label for known value (limit → 지정가)", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", "limit")).toBe("지정가");
  });

  it("returns label for known value (market → 시장가)", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", "market")).toBe("시장가");
  });

  it("returns label for known value (stop → 조건부지정가)", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", "stop")).toBe("조건부지정가");
  });

  /* ── Fallback: field not found ────────────────────── */

  it("returns raw value when field is not in fieldMap", () => {
    expect(getEnumLabel(mockFieldMap, "unknown_field", "some_value")).toBe(
      "some_value"
    );
  });

  /* ── Fallback: value not found in field ───────────── */

  it("returns raw value when value is not in field metadata", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", "nonexistent_value")).toBe(
      "nonexistent_value"
    );
  });

  /* ── Nullish / empty input ────────────────────────── */

  it("returns '-' for null value", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", null)).toBe("-");
  });

  it("returns '-' for undefined value", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", undefined)).toBe("-");
  });

  it("returns '-' for empty string value", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", "")).toBe("-");
  });

  /* ── Empty fieldMap (fetch failure simulation) ────── */

  it("returns raw value when fieldMap is empty (fetch failure)", () => {
    expect(getEnumLabel({}, "order_type", "limit")).toBe("limit");
  });

  /* ════════════════════════════════════════════════════
   * P1 — side
   * ════════════════════════════════════════════════════ */

  it("returns label for side buy → 매수", () => {
    expect(getEnumLabel(mockFieldMap, "side", "buy")).toBe("매수");
  });

  it("returns label for side sell → 매도", () => {
    expect(getEnumLabel(mockFieldMap, "side", "sell")).toBe("매도");
  });

  it("returns label for side hold → 보류", () => {
    expect(getEnumLabel(mockFieldMap, "side", "hold")).toBe("보류");
  });

  /* ════════════════════════════════════════════════════
   * P1 — order_status
   * ════════════════════════════════════════════════════ */

  it("returns label for order_status submitted → 제출됨", () => {
    expect(getEnumLabel(mockFieldMap, "order_status", "submitted")).toBe("제출됨");
  });

  it("returns label for order_status filled → 체결", () => {
    expect(getEnumLabel(mockFieldMap, "order_status", "filled")).toBe("체결");
  });

  it("returns label for order_status rejected → 거부됨", () => {
    expect(getEnumLabel(mockFieldMap, "order_status", "rejected")).toBe("거부됨");
  });

  /* ════════════════════════════════════════════════════
   * P1 — decision_type
   * ════════════════════════════════════════════════════ */

  it("returns label for decision_type approve → 승인", () => {
    expect(getEnumLabel(mockFieldMap, "decision_type", "approve")).toBe("승인");
  });

  it("returns label for decision_type hold → 보류", () => {
    expect(getEnumLabel(mockFieldMap, "decision_type", "hold")).toBe("보류");
  });

  it("returns label for decision_type exit → 청산", () => {
    expect(getEnumLabel(mockFieldMap, "decision_type", "exit")).toBe("청산");
  });

  /* ── Cross-field fallback ────────────────────────── */

  it("returns raw value for known field + unknown value (cross-check)", () => {
    expect(getEnumLabel(mockFieldMap, "side", "unknown_side")).toBe("unknown_side");
  });
});
