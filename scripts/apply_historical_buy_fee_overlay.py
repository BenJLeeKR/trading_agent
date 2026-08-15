#!/usr/bin/env python3
"""`007070` 파일럿 — 이미 원장에 존재하는 BUY fill_event에 historical fee

추정 overlay를 append하고, 전체 recompute를 큐에 등록한다.

설계 근거: docs/00_foundational_design/detailed_design/16_broker_fill_
snapshot_historical_backfill_design.md §8.13.

이 스크립트는 **`fill_events` 원본을 절대 UPDATE하지 않는다.** 대신
``trading.historical_buy_fee_overlays``에 별도 사실(append-only)을 얹고,
그 계좌×종목 전체를 ``realized_pnl_recompute_queue``에
``reason_code='manual_request'``로 등록한다 — 실제 재계산은 이미 운영
중인 ``realized-pnl-recompute-worker``가 수행한다(이 스크립트가 직접
recompute를 실행하지 않는다 — 001450/004370/13종목 initial-entry
파일럿과 동일한 "apply는 등록만, 실제 계산은 기존 워커" 패턴).

``--mode`` 미지정(기본 dry-run)이면 **DB에 아무것도 쓰지 않고**, 아래를
미리 계산해서 보여준다:
  - overlay로 들어갈 BUY fee 추정값(현재 활성 정책 기준)
  - 기존 SELL 이벤트들의 현재 allocated_buy_fee/realized_pnl_net
  - overlay를 반영해 전체를 다시 replay했을 때의 예상 allocated_buy_fee/
    realized_pnl_net/최종 pool(순수 in-memory 시뮬레이션 — replay_fills()
    는 부수효과가 없는 순수 함수라 DB에 전혀 쓰지 않고 미리 계산 가능하다)

Usage
-----
.. code-block:: bash

    # dry-run(기본값) — 계산 결과만 리포트, DB 변경 없음
    python3 scripts/apply_historical_buy_fee_overlay.py \\
        --account-id <uuid> --instrument-id <uuid> \\
        --broker-order-id <uuid> --fill-event-id <uuid> \\
        --reason "007070 파일럿 — 정책 등록 이전 BUY fee 소급 추정" \\
        --created-by ops-jay

    # apply — overlay append + recompute_queue 등록(재계산은 기존 워커가 수행)
    python3 scripts/apply_historical_buy_fee_overlay.py \\
        --account-id <uuid> --instrument-id <uuid> \\
        --broker-order-id <uuid> --fill-event-id <uuid> \\
        --reason "007070 파일럿 — 정책 등록 이전 BUY fee 소급 추정" \\
        --created-by ops-jay --mode apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import transaction
from agent_trading.domain.entities import HistoricalBuyFeeOverlayEntity, RealizedPnlRecomputeQueueEntity
from agent_trading.domain.enums import OrderSide, RealizedPnlFeeTaxSource
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.kis_fee_tax_policy import compute_fee_tax
from agent_trading.services.realized_pnl_engine import replay_fills
from agent_trading.services.realized_pnl_ledger_service import build_normalized_fill
from agent_trading.services.realized_pnl_recompute_service import (
    _ORDER_LOOKUP_LIMIT,
    _fill_sort_key,
)

logger = logging.getLogger(__name__)


def _load_local_dotenv() -> bool:
    if load_dotenv is None:
        return False
    return load_dotenv()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "이미 원장에 존재하는 BUY fill_event에 historical fee 추정 "
            "overlay를 append하고 recompute를 큐에 등록한다(007070 파일럿)."
        ),
    )
    parser.add_argument("--account-id", type=str, required=True)
    parser.add_argument("--instrument-id", type=str, required=True)
    parser.add_argument("--broker-order-id", type=str, required=True, help="overlay 대상 BUY fill이 속한 broker_order_id")
    parser.add_argument("--fill-event-id", type=str, required=True, help="overlay 대상 BUY fill_event_id")
    parser.add_argument("--reason", type=str, required=True)
    parser.add_argument("--created-by", type=str, required=True)
    parser.add_argument(
        "--mode",
        choices=("dry-run", "apply"),
        default="dry-run",
        help="dry-run(기본값): 계산 결과만 리포트, DB 변경 없음. "
        "apply: overlay append + recompute_queue 등록(재계산 자체는 기존 워커가 수행).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


async def _simulate_full_recompute(
    repos: RepositoryContainer,
    *,
    account_id: UUID,
    instrument_id: UUID,
    override_fill_event_id: UUID,
    override_fee: Decimal,
):
    """이 계좌×종목의 전체 fill을 모아, 지정한 fill_event_id에만 override_fee를

    적용한 뒤 ``replay_fills()``(순수 함수, DB 미접근)로 시뮬레이션한다.
    ``RealizedPnlRecomputeService._collect_ordered_normalized_fills()``와
    동일한 수집/정렬 로직을 재사용하되, overlay를 DB에서 조회하는 대신
    이 함수 인자로 받은 가상의 override를 그 자리에서 직접 적용한다 —
    아직 저장되지 않은 상태에서도 미리보기가 가능하게 하기 위함이다.
    """
    orders = await repos.orders.list(OrderQuery(account_id=account_id, limit=_ORDER_LOOKUP_LIMIT))
    matching_orders = [o for o in orders if o.instrument_id == instrument_id]

    fill_rows = []
    for order in matching_orders:
        broker_orders = await repos.broker_orders.list_by_order_request(order.order_request_id)
        for broker_order in broker_orders:
            fills = await repos.fill_events.list_by_broker_order(broker_order.broker_order_id)
            for fill_event in fills:
                effective = fill_event
                if fill_event.fill_event_id == override_fill_event_id:
                    effective = replace(
                        fill_event,
                        fill_fee=override_fee,
                        fill_tax=Decimal("0"),
                        fee_tax_source=RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE.value,
                    )
                normalized = build_normalized_fill(
                    effective,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    order_request_id=order.order_request_id,
                    side=order.side,
                )
                fill_rows.append((fill_event, normalized))

    fill_rows.sort(key=lambda pair: _fill_sort_key(pair[0]))
    ordered = [normalized for _fill_event, normalized in fill_rows]
    return replay_fills(ordered, computation_run_id=uuid4())


async def run(repos: RepositoryContainer, args: argparse.Namespace) -> int:
    account_id = UUID(args.account_id)
    instrument_id = UUID(args.instrument_id)
    broker_order_id = UUID(args.broker_order_id)
    fill_event_id = UUID(args.fill_event_id)

    account = await repos.accounts.get(account_id)
    if account is None:
        logger.error("account_id를 찾을 수 없다: %s", account_id)
        return 1
    instrument = await repos.instruments.get(instrument_id)
    if instrument is None:
        logger.error("instrument_id를 찾을 수 없다: %s", instrument_id)
        return 1

    fills = await repos.fill_events.list_by_broker_order(broker_order_id)
    target_fill = next((f for f in fills if f.fill_event_id == fill_event_id), None)
    if target_fill is None:
        logger.error(
            "broker_order_id=%s 안에서 fill_event_id=%s를 찾을 수 없다",
            broker_order_id, fill_event_id,
        )
        return 1

    existing_overlay = await repos.historical_buy_fee_overlays.get_by_fill_event_id(fill_event_id)
    if existing_overlay is not None:
        logger.error(
            "이 fill_event_id에는 이미 overlay가 등록돼 있다(overlay_id=%s) — "
            "재정정은 이 스크립트의 범위 밖이다.",
            existing_overlay.overlay_id,
        )
        return 1

    now = datetime.now(timezone.utc)
    estimate = await compute_fee_tax(
        repos,
        client_id=account.client_id,
        environment=account.environment,
        asset_class=instrument.asset_class,
        market_segment=instrument.market_segment,
        side=OrderSide.BUY,
        fill_price=target_fill.fill_price,
        fill_quantity=target_fill.fill_quantity,
        fill_timestamp=now,
    )
    if estimate.fee_tax_source != RealizedPnlFeeTaxSource.CALCULATED_FROM_POLICY:
        logger.error(
            "현재 활성 정책 기준으로 이 fill을 CALCULATED_FROM_POLICY로 "
            "계산할 수 없다(실제 결과=%s) — 활성 정책이 없거나 이 자산군/"
            "시장군이 지원 대상이 아니다. overlay를 등록할 근거가 없다.",
            estimate.fee_tax_source.value,
        )
        return 1

    active_config = await repos.config_versions.get_active_at(
        account.client_id, account.environment, now
    )
    if active_config is None:
        logger.error("활성 config_version을 찾을 수 없다(compute_fee_tax는 성공했는데 재조회 실패).")
        return 1

    existing_events = await repos.realized_pnl_events.list_by_account_and_instrument(
        account_id, instrument_id
    )
    existing_by_fill = {e.fill_event_id: e for e in existing_events}

    projected = await _simulate_full_recompute(
        repos,
        account_id=account_id,
        instrument_id=instrument_id,
        override_fill_event_id=fill_event_id,
        override_fee=estimate.fee,
    )

    print("=== historical_buy_fee_overlay 미리보기 ===")
    print(f"  account_id:              {account_id}")
    print(f"  instrument_id:           {instrument_id}")
    print(f"  대상 fill_event_id:       {fill_event_id}")
    print(f"  fill_price × fill_quantity: {target_fill.fill_price} × {target_fill.fill_quantity}")
    print(f"  현재 활성 정책 config_version_id: {active_config.config_version_id}")
    print(f"  추정 BUY fee(historical_policy_estimate): {estimate.fee}")
    print("  --- 기존 realized_pnl_events(현재 저장값) ---")
    for event in sorted(existing_events, key=lambda e: e.fill_timestamp):
        print(
            f"    fill_event_id={event.fill_event_id} sell_qty={event.sell_quantity} "
            f"allocated_buy_fee={event.allocated_buy_fee} realized_pnl_net={event.realized_pnl_net} "
            f"buy_fee_allocation_source={event.buy_fee_allocation_source.value}"
        )
    print("  --- overlay 반영 시뮬레이션(replay_fills, DB 미접근) ---")
    for projected_event in projected.realized_pnl_events:
        existing = existing_by_fill.get(projected_event.fill_event_id)
        print(
            f"    fill_event_id={projected_event.fill_event_id} "
            f"sell_qty={projected_event.sell_quantity} "
            f"allocated_buy_fee: {existing.allocated_buy_fee if existing else 'N/A'} -> "
            f"{projected_event.allocated_buy_fee} "
            f"realized_pnl_net: {existing.realized_pnl_net if existing else 'N/A'} -> "
            f"{projected_event.realized_pnl_net} "
            f"buy_fee_allocation_source -> {projected_event.buy_fee_allocation_source.value}"
        )
    if projected.final_state is not None:
        print(
            f"  --- 예상 최종 상태 --- quantity={projected.final_state.quantity} "
            f"average_cost={projected.final_state.average_cost} "
            f"remaining_buy_fee_pool={projected.final_state.remaining_buy_fee_pool} "
            f"buy_fee_pool_provenance={projected.final_state.buy_fee_pool_provenance.value}"
        )

    if args.mode == "dry-run":
        logger.info("dry-run 모드 — DB에 아무것도 쓰지 않았다.")
        return 0

    # --mode apply: overlay append + recompute_queue 등록만 수행한다.
    # 실제 recompute 실행은 이 스크립트가 하지 않는다 — 기존
    # realized-pnl-recompute-worker가 수행한다.
    overlay = HistoricalBuyFeeOverlayEntity(
        overlay_id=uuid4(),
        fill_event_id=fill_event_id,
        estimated_fee=estimate.fee,
        fee_tax_source=RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE.value,
        basis_config_version_id=active_config.config_version_id,
        reason=args.reason,
        created_by=args.created_by,
    )
    saved_overlay = await repos.historical_buy_fee_overlays.add(overlay)

    queue_item = await repos.realized_pnl_recompute_queue.add(
        RealizedPnlRecomputeQueueEntity(
            recompute_queue_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            reason_code="manual_request",
            triggering_fill_event_id=fill_event_id,
        )
    )
    print(
        "=== apply 결과 ===\n"
        f"  overlay_id:              {saved_overlay.overlay_id}\n"
        f"  recompute_queue_item_id: {queue_item.recompute_queue_id}"
    )
    logger.info("overlay append + recompute_queue 등록 완료. 실제 재계산은 워커 처리 대기 중.")
    return 0


async def _run(args: argparse.Namespace) -> int:
    config = DatabaseConfig()
    await create_pool(config)
    try:
        async with transaction() as tx:
            repos: RepositoryContainer = build_postgres_repositories(tx)
            exit_code = await run(repos, args)
            if args.mode == "apply" and exit_code == 0:
                await tx.commit()
            return exit_code
    finally:
        await close_pool()


def main() -> None:
    if _load_local_dotenv():
        logger.info("Loaded environment from project .env")
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    exit_code = asyncio.run(_run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
