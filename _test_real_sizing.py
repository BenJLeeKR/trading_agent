#!/usr/bin/env python3
"""Pure sizing calculation using actual snapshot values from DB."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from decimal import Decimal
from agent_trading.services.sizing_engine import calculate_sizing, SizingInputs
from agent_trading.domain.enums import OrderSide
from agent_trading.services.ai_agents.schemas import SizingHint

# ── Actual snapshot values (from Task 1) ──
AVAILABLE_CASH = Decimal("9109140")
ORDERABLE_AMOUNT = None  # NULL in DB
NAV = Decimal("27568261")
REFERENCE_PRICE = Decimal("291500")
POSITION_QTY = Decimal("0")  # 005930 position is 0 (sold)
POSITION_AVG_PRICE = None    # No position
MAX_POSITION_PCT = Decimal("100")  # legacy fallback
CASH_BUFFER_PCT = None  # not configured
MAX_ORDER_VALUE = None   # not configured
MIN_ORDER_QTY = None     # not configured
MAX_ORDER_QTY = None     # not configured
LOT_SIZE = Decimal("1")  # 005930

# ── Helper ──
def run_case(name: str, requested_qty: Decimal, desc: str = "") -> None:
    inputs = SizingInputs(
        decision_type="BUY",
        side=OrderSide.BUY,
        requested_quantity=requested_qty,
        requested_price=None,  # MARKET order
        reference_price=REFERENCE_PRICE,
        sizing_hint=SizingHint(),
        current_position_qty=POSITION_QTY,
        current_position_avg_price=POSITION_AVG_PRICE,
        available_cash=AVAILABLE_CASH,
        orderable_amount=ORDERABLE_AMOUNT,
        nav=NAV,
        max_single_position_pct=MAX_POSITION_PCT,
        min_cash_buffer_pct=CASH_BUFFER_PCT,
        max_order_value=MAX_ORDER_VALUE,
        min_order_qty=MIN_ORDER_QTY,
        max_order_qty=MAX_ORDER_QTY,
        lot_size=LOT_SIZE,
    )
    
    # Also manually trace the calculation for documentation
    effective_cash = ORDERABLE_AMOUNT if ORDERABLE_AMOUNT is not None else AVAILABLE_CASH
    
    # Stage 1: Allocation 20%
    target_notional = effective_cash * Decimal("0.2")
    target_qty_before_cap = int(target_notional / REFERENCE_PRICE)
    allocation_capped = min(target_qty_before_cap, int(requested_qty))
    
    result = calculate_sizing(inputs)
    
    print(f"\n{'='*70}")
    print(f"[{name}] requested_quantity = {requested_qty}")
    if desc:
        print(f"  Description: {desc}")
    print(f"{'='*70}")
    print(f"  Inputs:")
    print(f"    available_cash          : {AVAILABLE_CASH:>15,}")
    print(f"    orderable_amount        : {ORDERABLE_AMOUNT}")
    print(f"    nav                     : {NAV:>15,}")
    print(f"    reference_price         : {REFERENCE_PRICE:>15,}")
    print(f"    position_qty            : {POSITION_QTY}")
    print(f"    max_single_position_pct : {MAX_POSITION_PCT}%")
    print(f"    max_order_value         : {MAX_ORDER_VALUE}")
    print(f"    min/max_order_qty       : {MIN_ORDER_QTY} / {MAX_ORDER_QTY}")
    print(f"    lot_size                : {LOT_SIZE}")
    print(f"\n  Manual Calculation Trace:")
    print(f"    [Step 1-2: Allocation]")
    print(f"      effective_cash      = {effective_cash:>15,}")
    print(f"      ALLOCATION_PCT      = 20%")
    print(f"      target_notional     = {effective_cash} × 0.2 = {target_notional:>15,.0f}")
    print(f"      target_qty          = floor({target_notional} / {REFERENCE_PRICE}) = {target_qty_before_cap}")
    print(f"      requested_quantity  = {requested_qty}")
    print(f"      base_qty            = min({target_qty_before_cap}, {int(requested_qty)}) = {allocation_capped}")
    print(f"\n    [Step 3: Max Order Value]")
    print(f"      max_order_value     = {MAX_ORDER_VALUE} → SKIP (not set)")
    print(f"\n    [Step 4: Min/Max Qty]")
    print(f"      min_order_qty       = {MIN_ORDER_QTY} → SKIP (not set)")
    print(f"      max_order_qty       = {MAX_ORDER_QTY} → SKIP (not set)")
    
    # Cash constraint manual calculation
    cash_notional = effective_cash
    if CASH_BUFFER_PCT is not None:
        cash_notional = cash_notional * (Decimal("1") - CASH_BUFFER_PCT / Decimal("100"))
    # Safety factor 0.95 for MARKET order with reference_price
    cash_notional_safe = int(cash_notional * Decimal("0.95"))
    max_qty_cash = int(cash_notional_safe / REFERENCE_PRICE) if REFERENCE_PRICE else 999999
    
    print(f"\n    [Step 5: Cash Constraint]")
    print(f"      effective_cash      = {effective_cash:>15,}")
    print(f"      buffer ({CASH_BUFFER_PCT}%)          = SKIP (not set)")
    print(f"      safety (0.95)       = {cash_notional_safe:>15,}")
    print(f"      max_qty_by_cash     = floor({cash_notional_safe} / {REFERENCE_PRICE}) = {max_qty_cash}")
    
    # Concentration manual calculation
    max_position_value = NAV * MAX_POSITION_PCT / Decimal("100")
    current_value = (POSITION_QTY * POSITION_AVG_PRICE) if (POSITION_QTY and POSITION_AVG_PRICE) else Decimal("0")
    remaining = max_position_value - current_value
    max_qty_conc = int(remaining / REFERENCE_PRICE) if (REFERENCE_PRICE and remaining > 0) else 0
    
    print(f"\n    [Step 6: Position Concentration]")
    print(f"      max_position_value  = {NAV} × {MAX_POSITION_PCT}% = {max_position_value:>15,.0f}")
    print(f"      current_value       = {current_value:>15,.0f}")
    print(f"      remaining_capacity  = {remaining:>15,.0f}")
    print(f"      max_additional_qty  = floor({remaining} / {REFERENCE_PRICE}) = {max_qty_conc}")
    
    print(f"\n    [Step 7-8: Lot Size & Zero Guard]")
    print(f"      lot_size            = {LOT_SIZE} → round down")
    
    print(f"\n  >> Final Result from calculate_sizing():")
    print(f"     quantity            : {result.quantity}")
    print(f"     max_order_value     : {result.max_order_value}")
    print(f"     applied_constraints : {result.applied_constraints}")
    print(f"     skip_reason         : {result.skip_reason}")
    print(f"  >> Output {'✅' if result.quantity > 0 else '❌'}")
    
    return result


def main() -> None:
    print("=" * 70)
    print("REAL SNAPSHOT-BASED SIZING CALCULATION")
    print(f"Account: available_cash={AVAILABLE_CASH:,}, NAV={NAV:,}, ref_price={REFERENCE_PRICE:,}")
    print(f"Position: 005930 = 0 shares (sold)")
    print("=" * 70)
    
    # Test 3 requested_quantity values
    results = {}
    for qty in [Decimal("10"), Decimal("50"), Decimal("100")]:
        results[qty] = run_case(
            f"REQ_{qty}",
            qty,
            desc="Real snapshot values from DB"
        )
    
    print("\n" + "=" * 70)
    print("SUMMARY: requested_quantity vs sized_quantity")
    print("=" * 70)
    print(f"  {'req_qty':>10} | {'sized_qty':>10} | {'constraints':<40}")
    print(f"  {'-'*10}-+-{'-'*10}-+-{'-'*40}")
    for qty in [Decimal("10"), Decimal("50"), Decimal("100")]:
        r = results[qty]
        print(f"  {str(qty):>10} | {str(r.quantity):>10} | {str(r.applied_constraints):<40}")
    
    print(f"\n  Limiting factor: 20% ALLOCATION POLICY")
    print(f"    allocation_qty = floor({AVAILABLE_CASH:,} × 0.2 / {REFERENCE_PRICE:,}) = 6")
    print(f"    This is the binding constraint for all requested_quantity values")
    
    print(f"\n  최종 판정: SMOKE TEST에서 적정 수량 = 6주")
    print(f"    (available_cash=9,109,140 기준 20% allocation = 1,821,828 / 291,500 = 6.25 → floor=6)")


if __name__ == "__main__":
    main()
