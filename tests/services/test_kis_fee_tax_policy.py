"""단위 테스트: 정책 기반 fee/tax 계산 (kis_fee_tax_policy.py).

설계 근거: docs/00_foundational_design/detailed_design/
12_realized_pnl_moving_average_ledger.md 13절.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.domain.entities import ConfigVersionEntity
from agent_trading.domain.enums import Environment, OrderSide, RealizedPnlFeeTaxSource
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.kis_fee_tax_policy import (
    FeeTaxPolicy,
    MalformedFeeTaxPolicyError,
    UnsupportedRoundingModeError,
    compute_fee_tax,
    parse_fee_tax_policy,
)

_KST = timezone(timedelta(hours=9))


def _valid_fee_tax_json(**overrides) -> dict:
    base = {
        "execution": {
            "fee_tax": {
                "enabled": True,
                "supported_asset_classes": ["kr_stock"],
                "supported_market_segments": ["KOSPI", "KOSDAQ"],
                "buy_commission_rate_pct": "0.0140527",
                "sell_commission_rate_pct": "0.0140527",
                "sell_tax_rate_pct": "0.2000",
                "sell_agri_tax_rate_pct": "0.0000",
                "rounding_mode": "round_half_up",
                "rounding_unit": "1",
            }
        }
    }
    base["execution"]["fee_tax"].update(overrides)
    return base


class TestParseFeeTaxPolicy:
    def test_valid_policy_parses(self):
        policy = parse_fee_tax_policy(_valid_fee_tax_json())
        assert policy == FeeTaxPolicy(
            enabled=True,
            supported_asset_classes=("kr_stock",),
            supported_market_segments=("KOSPI", "KOSDAQ"),
            buy_commission_rate_pct=Decimal("0.0140527"),
            sell_commission_rate_pct=Decimal("0.0140527"),
            sell_tax_rate_pct=Decimal("0.2000"),
            sell_agri_tax_rate_pct=Decimal("0.0000"),
            rounding_mode="round_half_up",
            rounding_unit=Decimal("1"),
        )

    def test_missing_execution_namespace_returns_none(self):
        assert parse_fee_tax_policy({"risk": {}}) is None

    def test_missing_fee_tax_namespace_returns_none(self):
        assert parse_fee_tax_policy({"execution": {}}) is None

    def test_missing_required_numeric_field_raises(self):
        raw = _valid_fee_tax_json()
        del raw["execution"]["fee_tax"]["sell_tax_rate_pct"]
        with pytest.raises(MalformedFeeTaxPolicyError):
            parse_fee_tax_policy(raw)

    def test_unparseable_numeric_field_raises(self):
        raw = _valid_fee_tax_json(buy_commission_rate_pct="not-a-number")
        with pytest.raises(MalformedFeeTaxPolicyError):
            parse_fee_tax_policy(raw)

    def test_supported_asset_classes_not_a_list_raises(self):
        raw = _valid_fee_tax_json(supported_asset_classes="kr_stock")
        with pytest.raises(MalformedFeeTaxPolicyError):
            parse_fee_tax_policy(raw)

    def test_missing_rounding_mode_raises(self):
        raw = _valid_fee_tax_json()
        del raw["execution"]["fee_tax"]["rounding_mode"]
        with pytest.raises(MalformedFeeTaxPolicyError):
            parse_fee_tax_policy(raw)


@pytest.fixture
def repos():
    return build_in_memory_repositories()


async def _seed_active_policy(repos, *, client_id, environment, config_json, activated_at=None):
    version = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=client_id,
        environment=environment,
        version_tag="test",
        config_json=config_json,
        checksum="test",
        activated_at=activated_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    await repos.config_versions.add(version)
    return version


class TestComputeFeeTax:
    @pytest.mark.asyncio
    async def test_no_active_policy_is_assumed_zero(self, repos):
        result = await compute_fee_tax(
            repos,
            client_id=uuid4(),
            environment=Environment.PAPER,
            asset_class="kr_stock",
            market_segment="KOSPI",
            side=OrderSide.BUY,
            fill_price=Decimal("10000"),
            fill_quantity=Decimal("10"),
            fill_timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
        )
        assert result.fee == Decimal("0")
        assert result.tax == Decimal("0")
        assert result.fee_tax_source == RealizedPnlFeeTaxSource.ASSUMED_ZERO

    @pytest.mark.asyncio
    async def test_active_policy_without_fee_tax_namespace_is_assumed_zero(self, repos):
        client_id = uuid4()
        await _seed_active_policy(
            repos, client_id=client_id, environment=Environment.PAPER,
            config_json={"risk": {"max_single_position_pct": "5"}},
        )
        result = await compute_fee_tax(
            repos,
            client_id=client_id,
            environment=Environment.PAPER,
            asset_class="kr_stock",
            market_segment="KOSPI",
            side=OrderSide.BUY,
            fill_price=Decimal("10000"),
            fill_quantity=Decimal("10"),
            fill_timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
        )
        assert result.fee_tax_source == RealizedPnlFeeTaxSource.ASSUMED_ZERO

    @pytest.mark.asyncio
    async def test_unsupported_asset_class_is_policy_not_applicable(self, repos):
        client_id = uuid4()
        await _seed_active_policy(
            repos, client_id=client_id, environment=Environment.PAPER,
            config_json=_valid_fee_tax_json(),
        )
        result = await compute_fee_tax(
            repos,
            client_id=client_id,
            environment=Environment.PAPER,
            asset_class="kr_etf",
            market_segment="KOSPI",
            side=OrderSide.BUY,
            fill_price=Decimal("10000"),
            fill_quantity=Decimal("10"),
            fill_timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
        )
        assert result.fee == Decimal("0")
        assert result.tax == Decimal("0")
        assert result.fee_tax_source == RealizedPnlFeeTaxSource.POLICY_NOT_APPLICABLE

    @pytest.mark.asyncio
    async def test_missing_market_segment_is_policy_not_applicable(self, repos):
        client_id = uuid4()
        await _seed_active_policy(
            repos, client_id=client_id, environment=Environment.PAPER,
            config_json=_valid_fee_tax_json(),
        )
        result = await compute_fee_tax(
            repos,
            client_id=client_id,
            environment=Environment.PAPER,
            asset_class="kr_stock",
            market_segment=None,
            side=OrderSide.SELL,
            fill_price=Decimal("10000"),
            fill_quantity=Decimal("10"),
            fill_timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
        )
        assert result.fee_tax_source == RealizedPnlFeeTaxSource.POLICY_NOT_APPLICABLE

    @pytest.mark.asyncio
    async def test_supported_but_disabled_policy_is_assumed_zero(self, repos):
        client_id = uuid4()
        await _seed_active_policy(
            repos, client_id=client_id, environment=Environment.PAPER,
            config_json=_valid_fee_tax_json(enabled=False),
        )
        result = await compute_fee_tax(
            repos,
            client_id=client_id,
            environment=Environment.PAPER,
            asset_class="kr_stock",
            market_segment="KOSPI",
            side=OrderSide.BUY,
            fill_price=Decimal("10000"),
            fill_quantity=Decimal("10"),
            fill_timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
        )
        assert result.fee_tax_source == RealizedPnlFeeTaxSource.ASSUMED_ZERO

    @pytest.mark.asyncio
    async def test_buy_computes_fee_only(self, repos):
        client_id = uuid4()
        await _seed_active_policy(
            repos, client_id=client_id, environment=Environment.PAPER,
            config_json=_valid_fee_tax_json(
                buy_commission_rate_pct="0.015", rounding_mode="round_down", rounding_unit="1",
            ),
        )
        result = await compute_fee_tax(
            repos,
            client_id=client_id,
            environment=Environment.PAPER,
            asset_class="kr_stock",
            market_segment="KOSPI",
            side=OrderSide.BUY,
            fill_price=Decimal("28000"),
            fill_quantity=Decimal("176"),
            fill_timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
        )
        # 28000*176*0.015/100 = 739.2 -> round_down -> 739
        assert result.fee == Decimal("739")
        assert result.tax == Decimal("0")
        assert result.fee_tax_source == RealizedPnlFeeTaxSource.CALCULATED_FROM_POLICY

    @pytest.mark.asyncio
    async def test_sell_computes_fee_and_combined_tax(self, repos):
        client_id = uuid4()
        await _seed_active_policy(
            repos, client_id=client_id, environment=Environment.PAPER,
            config_json=_valid_fee_tax_json(
                sell_commission_rate_pct="0.015",
                sell_tax_rate_pct="0.18",
                sell_agri_tax_rate_pct="0.02",
                rounding_mode="round_half_up",
                rounding_unit="1",
            ),
        )
        result = await compute_fee_tax(
            repos,
            client_id=client_id,
            environment=Environment.PAPER,
            asset_class="kr_stock",
            market_segment="KOSDAQ",
            side=OrderSide.SELL,
            fill_price=Decimal("26800"),
            fill_quantity=Decimal("88"),
            fill_timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
        )
        amount = Decimal("26800") * Decimal("88")  # 2,358,400
        expected_fee = (amount * Decimal("0.015") / 100).to_integral_value()
        expected_tax = (amount * Decimal("0.20") / 100).to_integral_value()
        assert result.fee == expected_fee
        assert result.tax == expected_tax
        assert result.fee_tax_source == RealizedPnlFeeTaxSource.CALCULATED_FROM_POLICY

    @pytest.mark.asyncio
    async def test_unsupported_rounding_mode_raises(self, repos):
        client_id = uuid4()
        await _seed_active_policy(
            repos, client_id=client_id, environment=Environment.PAPER,
            config_json=_valid_fee_tax_json(rounding_mode="round_to_nearest_hundred"),
        )
        with pytest.raises(UnsupportedRoundingModeError):
            await compute_fee_tax(
                repos,
                client_id=client_id,
                environment=Environment.PAPER,
                asset_class="kr_stock",
                market_segment="KOSPI",
                side=OrderSide.BUY,
                fill_price=Decimal("10000"),
                fill_quantity=Decimal("10"),
                fill_timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
            )

    @pytest.mark.asyncio
    async def test_malformed_policy_raises_not_silently_assumed_zero(self, repos):
        client_id = uuid4()
        raw = _valid_fee_tax_json()
        del raw["execution"]["fee_tax"]["sell_tax_rate_pct"]
        await _seed_active_policy(
            repos, client_id=client_id, environment=Environment.PAPER, config_json=raw,
        )
        with pytest.raises(MalformedFeeTaxPolicyError):
            await compute_fee_tax(
                repos,
                client_id=client_id,
                environment=Environment.PAPER,
                asset_class="kr_stock",
                market_segment="KOSPI",
                side=OrderSide.SELL,
                fill_price=Decimal("10000"),
                fill_quantity=Decimal("10"),
                fill_timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
            )

    @pytest.mark.asyncio
    async def test_get_active_at_respects_fill_timestamp_not_latest(self, repos):
        """get_active_at()이 fill_timestamp 시점 기준 정책을 복원하는지 확인."""
        client_id = uuid4()
        old_policy = await _seed_active_policy(
            repos, client_id=client_id, environment=Environment.PAPER,
            config_json=_valid_fee_tax_json(buy_commission_rate_pct="0.01"),
            activated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        await _seed_active_policy(
            repos, client_id=client_id, environment=Environment.PAPER,
            config_json=_valid_fee_tax_json(buy_commission_rate_pct="0.02"),
            activated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        # fill_timestamp이 두 번째 정책 활성화 이전이므로 첫 번째 정책(0.01%)을 써야 한다.
        result = await compute_fee_tax(
            repos,
            client_id=client_id,
            environment=Environment.PAPER,
            asset_class="kr_stock",
            market_segment="KOSPI",
            side=OrderSide.BUY,
            fill_price=Decimal("10000"),
            fill_quantity=Decimal("10"),
            fill_timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        expected = (Decimal("100000") * Decimal("0.01") / 100).to_integral_value()
        assert result.fee == expected
        assert old_policy.config_json["execution"]["fee_tax"]["buy_commission_rate_pct"] == "0.01"
