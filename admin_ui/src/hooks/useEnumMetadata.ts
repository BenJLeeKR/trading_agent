/* ───────────────────────────────────────────
 * useEnumMetadata — shared hook + module-level cache
 *
 * Loads ``GET /metadata/enums`` once at module level and caches the
 * result so that every consumer shares the same data without redundant
 * network requests.
 *
 * ``_pendingPromise`` prevents duplicate in-flight requests when
 * multiple components mount concurrently.
 * ─────────────────────────────────────────── */

import { useState, useEffect } from "react";
import { getEnumMetadata } from "../api/client";
import type { EnumFieldMetadataSchema } from "../types/api";

// ── Module-level cache + pendingPromise ─────────────────────────────
let _cachedData: Record<string, EnumFieldMetadataSchema> | null = null;
let _pendingPromise: Promise<void> | null = null;

/**
 * React hook that loads enum metadata once and caches at module level.
 *
 * Returns:
 * - ``fieldMap`` — ``Record<field_name, EnumFieldMetadataSchema>``
 * - ``loading``  — ``true`` during initial fetch
 * - ``error``    — error message string on failure, ``null`` otherwise
 *
 * Usage::
 *
 *   const { fieldMap } = useEnumMetadata();
 *   const label = getEnumLabel(fieldMap, "order_type", order.order_type);
 *   // → "지정가"  (fallback: "limit")
 */
export function useEnumMetadata() {
  const [fieldMap, setFieldMap] = useState<
    Record<string, EnumFieldMetadataSchema>
  >(_cachedData ?? {});
  const [loading, setLoading] = useState(_cachedData === null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (_cachedData) return; // already loaded

    if (!_pendingPromise) {
      // First caller — initiate fetch
      _pendingPromise = getEnumMetadata()
        .then((data) => {
          const map: Record<string, EnumFieldMetadataSchema> = {};
          for (const f of data.fields) {
            map[f.field] = f;
          }
          _cachedData = map;
          setFieldMap(map);
        })
        .catch((err: unknown) => {
          const msg =
            err instanceof Error
              ? err.message
              : "Failed to load enum metadata";
          setError(msg);
        })
        .finally(() => {
          setLoading(false);
        });
    } else {
      // Already in-flight — wait for the same promise
      _pendingPromise.then(() => {
        if (_cachedData) setFieldMap(_cachedData);
        setLoading(false);
      });
    }
  }, []);

  return { fieldMap, loading, error };
}

/**
 * Resolve a canonical enum value to its display label.
 *
 * @param fieldMap - Field map from ``useEnumMetadata()``.
 * @param field    - Field name (e.g. ``"order_type"``).
 * @param value    - Canonical value (e.g. ``"limit"``), may be nullish.
 * @returns Display label, ``"-"`` for nullish input, or raw value as fallback.
 *
 * Usage::
 *
 *   getEnumLabel(fieldMap, "order_type", "limit")  // → "지정가"
 *   getEnumLabel(fieldMap, "order_type", null)     // → "-"
 *   getEnumLabel({}, "order_type", "limit")        // → "limit"  (fallback)
 */
export function getEnumLabel(
  fieldMap: Record<string, EnumFieldMetadataSchema>,
  field: string,
  value: string | null | undefined,
): string {
  if (!value) return "-";
  return (
    fieldMap[field]?.values.find((v) => v.value === value)?.label ?? value
  );
}

// TODO(P1): Extend enum label lookup to other fields:
//   - side:    "buy" → "매수", "sell" → "매도"
//   - status:  "filled" → "체결", "pending" → "대기", "rejected" → "거부", etc.
//   - decision_type: "approve" → "승인", "reject" → "거절", "hold" → "보류", etc.
//   - entry_style: "limit" → "지정가", "market" → "시장가", etc.
//   These require P1 registration in the backend ENUM_METADATA registry first.
