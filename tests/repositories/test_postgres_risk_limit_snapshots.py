from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import AccountEntity, RiskLimitSnapshotEntity
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
async def seeded_account(
    seeded_postgres_data: RepositoryContainer,
    sample_account: AccountEntity,
) -> UUID:
    """Return the account_id already seeded by ``seeded_postgres_data``."""
    return sample_account.account_id


@pytest.mark.asyncio
async def test_add_and_get_latest_by_account(
    seeded_postgres_data: RepositoryContainer,
    seeded_account: UUID,
) -> None:
    account_id = seeded_account
    now = datetime.now(timezone.utc)

    snapshot = RiskLimitSnapshotEntity(
        risk_limit_snapshot_id=uuid4(),
        account_id=account_id,
        snapshot_at=now,
        nav=Decimal("100000000"),
        cash_available=Decimal("50000000"),
        gross_exposure_pct=Decimal("50.0000"),
        net_exposure_pct=Decimal("30.0000"),
        daily_realized_pnl=Decimal("1000000"),
        daily_unrealized_pnl=Decimal("500000"),
        daily_loss_used_pct=Decimal("10.0000"),
        max_daily_loss_limit_pct=Decimal("20.0000"),
        var_confidence_level=Decimal("0.950000"),
        var_horizon_days=1,
        var_lookback_days=20,
        portfolio_var_1d=Decimal("2150000.12500000"),
        portfolio_var_1d_adjusted=Decimal("2580000.15000000"),
        largest_var_symbol="005930",
        largest_var_contribution_pct=Decimal("41.2500"),
        concentration_penalty_pct=Decimal("20.0000"),
        var_status="ready",
        var_reason_codes=["phase1_ready"],
        symbol_var_json={"005930": 2150000.125},
        symbol_marginal_contribution_json={"005930": 41.25},
        kill_switch_active=False,
    )
    saved = await seeded_postgres_data.risk_limit_snapshots.add(snapshot)
    assert saved.risk_limit_snapshot_id == snapshot.risk_limit_snapshot_id
    assert saved.nav == Decimal("100000000")
    assert saved.portfolio_var_1d_adjusted == Decimal("2580000.15000000")
    assert saved.var_status == "ready"
    assert saved.symbol_var_json == {"005930": 2150000.125}

    latest = await seeded_postgres_data.risk_limit_snapshots.get_latest_by_account(account_id)
    assert latest is not None
    assert latest.nav == Decimal("100000000")
    assert latest.largest_var_symbol == "005930"


@pytest.mark.asyncio
async def test_get_latest_by_account_returns_most_recent(
    seeded_postgres_data: RepositoryContainer,
    seeded_account: UUID,
) -> None:
    account_id = seeded_account
    now = datetime.now(timezone.utc)

    # Add two snapshots at different times
    old = RiskLimitSnapshotEntity(
        risk_limit_snapshot_id=uuid4(),
        account_id=account_id,
        snapshot_at=now,
        nav=Decimal("50000000"),
        cash_available=Decimal("25000000"),
    )
    new = RiskLimitSnapshotEntity(
        risk_limit_snapshot_id=uuid4(),
        account_id=account_id,
        snapshot_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        nav=Decimal("100000000"),
        cash_available=Decimal("50000000"),
    )
    await seeded_postgres_data.risk_limit_snapshots.add(old)
    await seeded_postgres_data.risk_limit_snapshots.add(new)

    latest = await seeded_postgres_data.risk_limit_snapshots.get_latest_by_account(account_id)
    assert latest is not None
    assert latest.nav == Decimal("100000000")


@pytest.mark.asyncio
async def test_get_latest_by_account_nonexistent(
    seeded_postgres_data: RepositoryContainer,
) -> None:
    result = await seeded_postgres_data.risk_limit_snapshots.get_latest_by_account(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_list_by_account(
    seeded_postgres_data: RepositoryContainer,
    seeded_account: UUID,
) -> None:
    account_id = seeded_account
    now = datetime.now(timezone.utc)

    for i in range(3):
        await seeded_postgres_data.risk_limit_snapshots.add(
            RiskLimitSnapshotEntity(
                risk_limit_snapshot_id=uuid4(),
                account_id=account_id,
                snapshot_at=now,
                nav=Decimal(f"{i+1}00000000"),
            )
        )

    snapshots = await seeded_postgres_data.risk_limit_snapshots.list_by_account(
        account_id, limit=10
    )
    assert len(snapshots) == 3


@pytest.mark.asyncio
async def test_kill_switch_active_flag(
    seeded_postgres_data: RepositoryContainer,
    seeded_account: UUID,
) -> None:
    """Verify kill_switch_active BOOLEAN is stored and retrieved correctly."""
    account_id = seeded_account
    now = datetime.now(timezone.utc)

    snapshot = RiskLimitSnapshotEntity(
        risk_limit_snapshot_id=uuid4(),
        account_id=account_id,
        snapshot_at=now,
        kill_switch_active=True,
        blocked_reason_codes=["daily_loss_limit_exceeded", "max_drawdown_exceeded"],
    )
    await seeded_postgres_data.risk_limit_snapshots.add(snapshot)

    latest = await seeded_postgres_data.risk_limit_snapshots.get_latest_by_account(account_id)
    assert latest is not None
    assert latest.kill_switch_active is True
    assert latest.blocked_reason_codes == [
        "daily_loss_limit_exceeded",
        "max_drawdown_exceeded",
    ]


@pytest.mark.asyncio
async def test_var_fields_roundtrip_with_sparse_snapshot(
    seeded_postgres_data: RepositoryContainer,
    seeded_account: UUID,
) -> None:
    account_id = seeded_account
    now = datetime.now(timezone.utc)

    snapshot = RiskLimitSnapshotEntity(
        risk_limit_snapshot_id=uuid4(),
        account_id=account_id,
        snapshot_at=now,
        nav=Decimal("75000000"),
        cash_available=Decimal("22000000"),
        var_confidence_level=Decimal("0.950000"),
        var_horizon_days=1,
        var_lookback_days=20,
        portfolio_var_1d=None,
        portfolio_var_1d_adjusted=None,
        largest_var_symbol=None,
        largest_var_contribution_pct=None,
        concentration_penalty_pct=None,
        var_status="insufficient_data",
        var_reason_codes=["insufficient_history"],
        symbol_var_json={},
        symbol_marginal_contribution_json={},
    )
    await seeded_postgres_data.risk_limit_snapshots.add(snapshot)

    latest = await seeded_postgres_data.risk_limit_snapshots.get_latest_by_account(account_id)
    assert latest is not None
    assert latest.var_status == "insufficient_data"
    assert latest.var_reason_codes == ["insufficient_history"]
    assert latest.symbol_marginal_contribution_json == {}
