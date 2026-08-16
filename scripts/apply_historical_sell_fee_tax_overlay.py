#!/usr/bin/env python3
"""`007070` 파일럿 — 이미 원장에 존재하는 SELL fill_event에 historical

매도 수수료+매도세 추정 overlay를 append하고, 전체 recompute를 큐에
등록한다.

설계 근거: docs/00_foundational_design/detailed_design/16_broker_fill_
snapshot_historical_backfill_design.md §8.15.

이 스크립트는 **`fill_events` 원본을 절대 UPDATE하지 않는다.** 대신
``trading.historical_sell_fee_tax_overlays``에 별도 사실(append-only)을
얹고, 그 계좌×종목 전체를 ``realized_pnl_recompute_queue``에
``reason_code='manual_request'``로 등록한다 — 실제 재계산은 이미 운영
중인 ``realized-pnl-recompute-worker``가 수행한다(``apply_historical_
buy_fee_overlay.py``와 동일한 "apply는 등록만, 실제 계산은 기존 워커"
패턴).

BUY overlay 스크립트와 다른 점: 대상 fill의 ``side``가 SELL이어야 하고,
``compute_fee_tax()``를 ``OrderSide.SELL``로 호출해 매도 수수료+매도세를
함께 추정한다. 이 fill은 이미 ``realized_pnl_events``에 확정 기록이
존재하므로(체결 시각 기준 정책이 없어 ``assumed_zero``로 계산됨),
dry-run 미리보기는 "기존 실현손익 이력을 다시 바꾼다"는 점을 명시적으로
보여준다.

``--mode`` 미지정(기본 dry-run)이면 **DB에 아무것도 쓰지 않고**, 아래를
미리 계산해서 보여준다:
  - overlay로 들어갈 매도 수수료/매도세 추정값(현재 활성 정책 기준)
  - 이 SELL의 현재(overlay 반영 전) fee/tax/realized_pnl_net
  - overlay를 반영해 전체를 다시 replay했을 때의 예상 fee/tax/
    realized_pnl_net/일자 합계 변화(순수 in-memory 시뮬레이션 —
    replay_fills()는 부수효과가 없는 순수 함수라 DB에 전혀 쓰지 않고
    미리 계산 가능하다)

Usage
-----
.. code-block:: bash

    # dry-run(기본값) — 계산 결과만 리포트, DB 변경 없음
    python3 scripts/apply_historical_sell_fee_tax_overlay.py \\
        --account-id <uuid> --instrument-id <uuid> \\
        --broker-order-id <uuid> --fill-event-id <uuid> \\
        --reason "007070 파일럿 — 정책 등록 이전 SELL fee/tax 소급 추정" \\
        --created-by ops-jay

    # apply — overlay append + recompute_queue 등록(재계산은 기존 워커가 수행)
    python3 scripts/apply_historical_sell_fee_tax_overlay.py \\
        --account-id <uuid> --instrument-id <uuid> \\
        --broker-order-id <uuid> --fill-event-id <uuid> \\
        --reason "007070 파일럿 — 정책 등록 이전 SELL fee/tax 소급 추정" \\
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
from agent_trading.domain.entities import (
    HistoricalSellFeeTaxOverlayEntity,
    RealizedPnlRecomputeQueueEntity,
)
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
            "이미 원장에 존재하는 SELL fill_event에 historical 매도 "
            "수수료+매도세 추정 overlay를 append하고 recompute를 큐에 "
            "등록한다(007070 파일럿)."
        ),
    )
    parser.add_argument("--account-id", type=str, required=True)
    parser.add_argument("--instrument-id", type=str, required=True)
    parser.add_argument(
        "--broker-order-id", type=str, required=True,
        help="overlay 대상 SELL fill이 속한 broker_order_id",
    )
    parser.add_argument("--fill-event-id", type=str, required=True, help="overlay 대상 SELL fill_event_id")
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
    override_tax: Decimal,
):
    """이 계좌×종목의 전체 fill을 모아, 지정한 fill_event_id에만
    override_fee/override_tax를 적용한 뒤 ``replay_fills()``(순수 함수,
    DB 미접근)로 시뮬레이션한다. ``RealizedPnlRecomputeService.
    _collect_ordered_normalized_fills()``와 동일한 수집/정렬 로직을
    재사용하되(기존 BUY/SELL overlay 저장소 조회는 그대로 반영하고),
    이 스크립트가 미리보기하려는 SELL fill_event_id에만 아직 저장되지
    않은 가상의 override를 그 자리에서 직접 적용한다.
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

                buy_overlay = await repos.historical_buy_fee_overlays.get_by_fill_event_id(
                    fill_event.fill_event_id
                )
                if buy_overlay is not None:
                    effective = replace(
                        effective,
                        fill_fee=buy_overlay.estimated_fee,
                        fill_tax=Decimal("0"),
                        fee_tax_source=RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE.value,
                    )

                existing_sell_overlay = await repos.historical_sell_fee_tax_overlays.get_by_fill_event_id(
                    fill_event.fill_event_id
                )
                if existing_sell_overlay is not None:
                    effective = replace(
                        effective,
                        fill_fee=existing_sell_overlay.estimated_fee,
                        fill_tax=existing_sell_overlay.estimated_tax,
                        fee_tax_source=RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE.value,
                    )

                if fill_event.fill_event_id == override_fill_event_id:
                    effective = replace(
                        effective,
                        fill_fee=override_fee,
                        fill_tax=override_tax,
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

    existing_overlay = await repos.historical_sell_fee_tax_overlays.get_by_fill_event_id(fill_event_id)
    if existing_overlay is not None:
        logger.error(
            "이 fill_event_id에는 이미 SELL overlay가 등록돼 있다(overlay_id=%s) — "
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
        side=OrderSide.SELL,
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
    existing_target = existing_by_fill.get(fill_event_id)
    if existing_target is None:
        logger.error(
            "fill_event_id=%s에 대한 기존 realized_pnl_events 행을 찾을 수 없다 — "
            "이 스크립트는 이미 recompute를 통해 확정된 SELL 이벤트를 재해석하는 "
            "용도이며, 아직 계산된 적 없는 fill에는 쓰지 않는다.",
            fill_event_id,
        )
        return 1

    projected = await _simulate_full_recompute(
        repos,
        account_id=account_id,
        instrument_id=instrument_id,
        override_fill_event_id=fill_event_id,
        override_fee=estimate.fee,
        override_tax=estimate.tax,
    )

    print("=== historical_sell_fee_tax_overlay 미리보기 ===")
    print("  ⚠ 이 fill은 이미 recompute를 통해 realized_pnl_net이 한 번 확정된 SELL이다 —")
    print("    이번 overlay는 그 확정값을 두 번째로 재해석한다(신규 계산이 아니다).")
    print(f"  account_id:              {account_id}")
    print(f"  instrument_id:           {instrument_id}")
    print(f"  대상 fill_event_id:       {fill_event_id}")
    print(f"  fill_price × fill_quantity: {target_fill.fill_price} × {target_fill.fill_quantity}")
    print(f"  현재 활성 정책 config_version_id: {active_config.config_version_id}")
    print(f"  추정 매도 수수료(historical_policy_estimate): {estimate.fee}")
    print(f"  추정 매도세(historical_policy_estimate):      {estimate.tax}")
    print("  --- 이 SELL의 기존(overlay 반영 전) 상태 ---")
    print(
        f"    fee={existing_target.fee} tax={existing_target.tax} "
        f"fee_tax_source={existing_target.fee_tax_source.value} "
        f"realized_pnl_net={existing_target.realized_pnl_net}"
    )
    print("  --- overlay 반영 시뮬레이션(replay_fills, DB 미접근) ---")
    for projected_event in projected.realized_pnl_events:
        existing = existing_by_fill.get(projected_event.fill_event_id)
        marker = " <== 대상" if projected_event.fill_event_id == fill_event_id else ""
        print(
            f"    fill_event_id={projected_event.fill_event_id}{marker} "
            f"sell_qty={projected_event.sell_quantity} "
            f"fee: {existing.fee if existing else 'N/A'} -> {projected_event.fee} "
            f"tax: {existing.tax if existing else 'N/A'} -> {projected_event.tax} "
            f"realized_pnl_net: {existing.realized_pnl_net if existing else 'N/A'} -> "
            f"{projected_event.realized_pnl_net} "
            f"fee_tax_source -> {projected_event.fee_tax_source.value}"
        )
    existing_net_sum = sum((e.realized_pnl_net for e in existing_events), Decimal("0"))
    projected_net_sum = sum(
        (e.realized_pnl_net for e in projected.realized_pnl_events), Decimal("0")
    )
    print(
        f"  --- 예상 일자 합계(계좌×종목 전체 realized_pnl_net 합) --- "
        f"{existing_net_sum} -> {projected_net_sum}"
    )

    if args.mode == "dry-run":
        logger.info("dry-run 모드 — DB에 아무것도 쓰지 않았다.")
        return 0

    # --mode apply: overlay append + recompute_queue 등록만 수행한다.
    # 실제 recompute 실행은 이 스크립트가 하지 않는다 — 기존
    # realized-pnl-recompute-worker가 수행한다.
    overlay = HistoricalSellFeeTaxOverlayEntity(
        overlay_id=uuid4(),
        fill_event_id=fill_event_id,
        estimated_fee=estimate.fee,
        estimated_tax=estimate.tax,
        fee_tax_source=RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE.value,
        basis_config_version_id=active_config.config_version_id,
        reason=args.reason,
        created_by=args.created_by,
    )
    saved_overlay = await repos.historical_sell_fee_tax_overlays.add(overlay)

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
