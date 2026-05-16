/* ───────────────────────────────────────────
 * Pure helper: derive reconcile-required cases
 *
 * UI-only computation.  No side effects, no API calls.
 * Computes position-reflected signal and interpretive text
 * from already-fetched orders + positions data.
 * ─────────────────────────────────────────── */
import type { OrderSummary, PositionSnapshotView } from "../types/api";

/* ── Public types ────────────────────────── */

export interface ReconcileRequiredCase {
  order: OrderSummary;
  /** Whether a matching position exists in the account snapshot */
  positionReflected: boolean;
  /** Matching position snapshot, if any */
  matchedPosition: PositionSnapshotView | null;
  /** Price tolerance check result (only when positionReflected=true) */
  priceMatch: boolean;
  /** Quantity sufficiency check (position.quantity >= order.requested_quantity) */
  quantitySufficient: boolean;
  /** Interpretive text variant — never "success" */
  variant: "info" | "warning";
  /** Human-readable interpretive text in Korean */
  interpretiveText: string;
}

/* ── Constants ───────────────────────────── */

/** Price comparison tolerance in KRW */
const PRICE_TOLERANCE = 1;

/* ── Pure helpers ────────────────────────── */

/**
 * Find a matching position for an order by instrument_id (primary) or symbol (fallback).
 */
function findMatchingPosition(
  order: OrderSummary,
  positions: PositionSnapshotView[],
): PositionSnapshotView | null {
  // instrument_id is not available on OrderSummary, so we use symbol matching
  // (instrument_id matching would require OrderDetail; Phase 2 may add it)
  if (!order.symbol) return null;
  return (
    positions.find((p) => p.symbol === order.symbol) ?? null
  );
}

/**
 * Check whether the position average price matches the order requested price
 * within tolerance.
 */
function checkPriceMatch(
  order: OrderSummary,
  position: PositionSnapshotView,
): boolean {
  if (order.requested_price == null || position.average_price == null) {
    return false;
  }
  return Math.abs(order.requested_price - position.average_price) <= PRICE_TOLERANCE;
}

/**
 * Check whether the position quantity is at least the order requested quantity.
 */
function checkQuantitySufficient(
  order: OrderSummary,
  position: PositionSnapshotView,
): boolean {
  return position.quantity >= order.requested_quantity;
}

/**
 * Derive interpretive text variant and message for a reconcile-required case.
 *
 * Rules (4-tier, no "success" variant):
 *   Tier 1: positionReflected=true + priceMatch=true + quantitySufficient=true
 *     → info, "포지션 반영됨 · 수량/단가 정합"
 *   Tier 2: positionReflected=true + priceMatch=true + quantitySufficient=false
 *     → warning, "포지션 반영됨 · 수량 부족 (주문 {qty} > 포지션 {posQty})"
 *   Tier 3: positionReflected=true + priceMatch=false
 *     → warning, "포지션 반영됨 · 단가 불일치 (주문 {price} ≠ 포지션 {posPrice})"
 *   Tier 4: positionReflected=false
 *     → warning, "조정 필요 · 포지션 미반영"
 */
function deriveInterpretiveText(
  positionReflected: boolean,
  priceMatch: boolean,
  quantitySufficient: boolean,
  order: OrderSummary,
  matchedPosition: PositionSnapshotView | null,
): { variant: "info" | "warning"; interpretiveText: string } {
  if (!positionReflected || !matchedPosition) {
    return {
      variant: "warning",
      interpretiveText: "조정 필요 · 포지션 미반영",
    };
  }

  if (priceMatch && quantitySufficient) {
    return {
      variant: "info",
      interpretiveText: "포지션 반영됨 · 수량/단가 정합",
    };
  }

  if (priceMatch && !quantitySufficient) {
    return {
      variant: "warning",
      interpretiveText: `포지션 반영됨 · 수량 부족 (주문 ${order.requested_quantity} > 포지션 ${matchedPosition.quantity})`,
    };
  }

  // priceMatch = false
  return {
    variant: "warning",
    interpretiveText: `포지션 반영됨 · 단가 불일치 (주문 ${order.requested_price} ≠ 포지션 ${matchedPosition.average_price})`,
  };
}

/* ── Main entry point ────────────────────── */

/**
 * Build an account-level symbol→position index for O(1) lookups.
 *
 * Returns `Map<accountId, Map<symbol, PositionSnapshotView>>`.
 */
function buildPositionIndex(
  positionsByAccount: Map<string, PositionSnapshotView[]>,
): Map<string, Map<string, PositionSnapshotView>> {
  const index = new Map<string, Map<string, PositionSnapshotView>>();
  for (const [accountId, positions] of positionsByAccount) {
    const symbolMap = new Map<string, PositionSnapshotView>();
    for (const pos of positions) {
      if (pos.symbol) symbolMap.set(pos.symbol, pos);
    }
    index.set(accountId, symbolMap);
  }
  return index;
}

/**
 * Derive reconcile-required cases from orders and positions data.
 *
 * Uses an account-level symbol→position Map index for O(n) total complexity
 * instead of O(orders × positions) linear search.
 *
 * @param orders - List of orders (pre-filtered by status=reconcile_required)
 * @param positionsByAccount - Map of account_id → position snapshots
 * @returns Sorted list of ReconcileRequiredCase (newest first)
 */
export function deriveReconcileRequiredCases(
  orders: OrderSummary[],
  positionsByAccount: Map<string, PositionSnapshotView[]>,
): ReconcileRequiredCase[] {
  // Build account-level symbol→position index (O(P) where P = total positions)
  const positionIndex = buildPositionIndex(positionsByAccount);

  const cases: ReconcileRequiredCase[] = [];

  for (const order of orders) {
    // O(1) lookup per order — no linear search
    const acctIndex = positionIndex.get(order.account_id);
    const matchedPosition =
      order.symbol && acctIndex
        ? (acctIndex.get(order.symbol) ?? null)
        : null;

    const positionReflected = matchedPosition !== null;
    const priceMatch = positionReflected
      ? checkPriceMatch(order, matchedPosition!)
      : false;
    const quantitySufficient = positionReflected
      ? checkQuantitySufficient(order, matchedPosition!)
      : false;
    const { variant, interpretiveText } = deriveInterpretiveText(
      positionReflected,
      priceMatch,
      quantitySufficient,
      order,
      matchedPosition,
    );

    cases.push({
      order,
      positionReflected,
      matchedPosition,
      priceMatch,
      quantitySufficient,
      variant,
      interpretiveText,
    });
  }

  // Sort by created_at descending (newest first)
  return cases.sort(
    (a, b) =>
      new Date(b.order.created_at ?? 0).getTime() -
      new Date(a.order.created_at ?? 0).getTime(),
  );
}
