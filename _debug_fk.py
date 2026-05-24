#!/usr/bin/env python3
"""Debug: check if snapshot_sync_run_id is actually passed through the chain."""
import asyncio
from uuid import uuid4
from unittest.mock import AsyncMock
from decimal import Decimal
from datetime import datetime, timezone

from agent_trading.services.snapshot_sync import sync_account_snapshots, FetchedSnapshot
from agent_trading.domain.entities import PositionSnapshotEntity, CashBalanceSnapshotEntity


class MockProvider:
    async def fetch_snapshot(self, account_id, instrument_repo, *, after_hours=False, fetch_positions=True):
        pos = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account_id,
            instrument_id=uuid4(),
            quantity=Decimal('10'),
            average_price=Decimal('50000'),
            market_price=Decimal('51000'),
            unrealized_pnl=Decimal('10000'),
            source_of_truth='broker',
            snapshot_at=datetime.now(timezone.utc),
        )
        cash = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account_id,
            currency='KRW',
            available_cash=Decimal('1000000'),
            settled_cash=Decimal('1000000'),
            unsettled_cash=None,
            source_of_truth='broker',
            snapshot_at=datetime.now(timezone.utc),
        )
        print(f"  Provider created pos.snapshot_sync_run_id={pos.snapshot_sync_run_id}")
        print(f"  Provider created cash.snapshot_sync_run_id={cash.snapshot_sync_run_id}")
        return FetchedSnapshot(positions=[pos], cash_balance=cash, errors=[])


async def main():
    run_id = uuid4()
    print(f"Test run_id = {run_id}")

    provider = MockProvider()
    mock_repo = AsyncMock(spec=['add'])
    mock_repo.add = AsyncMock(return_value=None)

    result = await sync_account_snapshots(
        fetch_provider=provider,
        instrument_repo=mock_repo,
        position_snapshot_repo=mock_repo,
        cash_balance_snapshot_repo=mock_repo,
        risk_limit_snapshot_repo=mock_repo,
        account_id=uuid4(),
        snapshot_sync_run_id=run_id,
    )

    print(f"\nResult: positions_synced={result.positions_synced}, cash_synced={result.cash_balance_synced}")
    print(f"add() called {mock_repo.add.call_count} times")

    for i, call in enumerate(mock_repo.add.call_args_list):
        args, kwargs = call
        entity = args[0]
        etype = type(entity).__name__
        rid = entity.snapshot_sync_run_id
        match = "✅ MATCH" if rid == run_id else f"❌ MISMATCH (expected {run_id})"
        print(f"  add call #{i}: {etype} snapshot_sync_run_id={rid} {match}")

    # Now test with None
    print("\n--- Test with snapshot_sync_run_id=None ---")
    mock_repo2 = AsyncMock(spec=['add'])
    mock_repo2.add = AsyncMock(return_value=None)
    result2 = await sync_account_snapshots(
        fetch_provider=provider,
        instrument_repo=mock_repo2,
        position_snapshot_repo=mock_repo2,
        cash_balance_snapshot_repo=mock_repo2,
        risk_limit_snapshot_repo=mock_repo2,
        account_id=uuid4(),
        snapshot_sync_run_id=None,
    )
    for i, call in enumerate(mock_repo2.add.call_args_list):
        args, kwargs = call
        entity = args[0]
        etype = type(entity).__name__
        rid = entity.snapshot_sync_run_id
        print(f"  add call #{i}: {etype} snapshot_sync_run_id={rid} {'✅ None' if rid is None else '❌ NOT None'}")


if __name__ == '__main__':
    asyncio.run(main())
