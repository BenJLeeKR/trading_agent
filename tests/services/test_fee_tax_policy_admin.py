"""``fee_tax_policy_admin`` 서비스 계층 단위 테스트.

immutable append-only 발행, ``activated_at`` 충돌/역행 거부, 구조 검증,
dry-run/preview, active/at 조회를 확인한다. API 계층(HTTP shape/RBAC)은
``tests/api/test_config_versions_admin.py``의 ``TestExecutionFeeTaxPolicyAdmin``
에서 다룬다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agent_trading.domain.enums import Environment
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.fee_tax_policy_admin import (
    FeeTaxPolicyAdminError,
    FeeTaxPolicyPreview,
    FeeTaxPolicyPublishResult,
    get_active_fee_tax_policy,
    get_fee_tax_policy_at,
    publish_fee_tax_policy,
    validate_and_preview_fee_tax_policy,
)

_VALID_INPUT = {
    "enabled": True,
    "supported_asset_classes": ["kr_stock"],
    "supported_market_segments": ["KOSPI", "KOSDAQ"],
    "buy_commission_rate_pct": "0.0140527",
    "sell_commission_rate_pct": "0.0140527",
    "sell_tax_rate_pct": "0.2000",
    "sell_agri_tax_rate_pct": "0.0000",
    "rounding_mode": "round_half_up",
    "rounding_unit": "1",
    "reason": "initial live fee/tax policy",
    "operator_note": "verified against operator contract sheet",
    "source_note": "manual operator input",
}


class TestValidateAndPreview:
    def test_valid_policy_returns_normalized_preview(self) -> None:
        preview = validate_and_preview_fee_tax_policy(_VALID_INPUT)
        assert isinstance(preview, FeeTaxPolicyPreview)
        assert preview.normalized_fee_tax["enabled"] is True
        assert preview.normalized_fee_tax["reason"] == "initial live fee/tax policy"
        assert preview.sample_price == "100000"
        assert preview.sample_quantity == "10"
        # 0.0140527% of 1,000,000 = 140.527 -> round_half_up to unit 1 -> "141"
        assert preview.sample_buy_fee == "141"

    def test_missing_reason_is_rejected(self) -> None:
        bad = dict(_VALID_INPUT)
        bad["reason"] = ""
        with pytest.raises(FeeTaxPolicyAdminError):
            validate_and_preview_fee_tax_policy(bad)

    def test_invalid_rounding_mode_is_rejected(self) -> None:
        bad = dict(_VALID_INPUT)
        bad["rounding_mode"] = "round_to_nearest_moon"
        with pytest.raises(FeeTaxPolicyAdminError):
            validate_and_preview_fee_tax_policy(bad)

    def test_non_decimal_rate_is_rejected(self) -> None:
        bad = dict(_VALID_INPUT)
        bad["buy_commission_rate_pct"] = "not-a-number"
        with pytest.raises(FeeTaxPolicyAdminError):
            validate_and_preview_fee_tax_policy(bad)

    def test_excessive_rate_is_rejected(self) -> None:
        """0.147% 대신 14.7을 실수로 넣는 등 명백한 오입력 방지."""
        bad = dict(_VALID_INPUT)
        bad["buy_commission_rate_pct"] = "14.7"
        with pytest.raises(FeeTaxPolicyAdminError):
            validate_and_preview_fee_tax_policy(bad)

    def test_negative_rate_is_rejected(self) -> None:
        bad = dict(_VALID_INPUT)
        bad["sell_tax_rate_pct"] = "-0.2"
        with pytest.raises(FeeTaxPolicyAdminError):
            validate_and_preview_fee_tax_policy(bad)


class TestPublishFeeTaxPolicy:
    def test_first_time_registration_succeeds_without_prior_active_version(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()

        result = asyncio.run(
            publish_fee_tax_policy(
                repos,
                client_id=client_id,
                environment=Environment.LIVE,
                fee_tax_input=_VALID_INPUT,
                activated_by="test-operator",
            )
        )
        assert isinstance(result, FeeTaxPolicyPublishResult)
        assert result.previous is None
        assert result.new.config_json["execution"]["fee_tax"]["enabled"] is True

        active = asyncio.run(repos.config_versions.get_active(client_id, Environment.LIVE))
        assert active is not None
        assert active.config_version_id == result.new.config_version_id

    def test_dry_run_does_not_persist_a_new_version(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()

        preview = asyncio.run(
            publish_fee_tax_policy(
                repos,
                client_id=client_id,
                environment=Environment.LIVE,
                fee_tax_input=_VALID_INPUT,
                activated_by="test-operator",
                dry_run=True,
            )
        )
        assert isinstance(preview, FeeTaxPolicyPreview)

        active = asyncio.run(repos.config_versions.get_active(client_id, Environment.LIVE))
        assert active is None

    def test_duplicate_activated_at_is_rejected(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()
        fixed_at = datetime(2026, 8, 14, 9, 0, 0, tzinfo=timezone.utc)

        asyncio.run(
            publish_fee_tax_policy(
                repos,
                client_id=client_id,
                environment=Environment.LIVE,
                fee_tax_input=_VALID_INPUT,
                activated_by="test-operator",
                activated_at=fixed_at,
            )
        )

        with pytest.raises(FeeTaxPolicyAdminError):
            asyncio.run(
                publish_fee_tax_policy(
                    repos,
                    client_id=client_id,
                    environment=Environment.LIVE,
                    fee_tax_input=_VALID_INPUT,
                    activated_by="test-operator",
                    activated_at=fixed_at,
                )
            )

    def test_backdated_activated_at_is_rejected(self) -> None:
        """새 activated_at은 현재 활성 버전보다 반드시 이후여야 한다(역행 등록 금지)."""
        repos = build_in_memory_repositories()
        client_id = uuid4()
        current_at = datetime(2026, 8, 14, 9, 0, 0, tzinfo=timezone.utc)
        earlier_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        asyncio.run(
            publish_fee_tax_policy(
                repos,
                client_id=client_id,
                environment=Environment.LIVE,
                fee_tax_input=_VALID_INPUT,
                activated_by="test-operator",
                activated_at=current_at,
            )
        )

        with pytest.raises(FeeTaxPolicyAdminError):
            asyncio.run(
                publish_fee_tax_policy(
                    repos,
                    client_id=client_id,
                    environment=Environment.LIVE,
                    fee_tax_input=_VALID_INPUT,
                    activated_by="test-operator",
                    activated_at=earlier_at,
                )
            )

    def test_real_environment_is_rejected(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()

        with pytest.raises(Exception):
            asyncio.run(
                publish_fee_tax_policy(
                    repos,
                    client_id=client_id,
                    environment=Environment.REAL,
                    fee_tax_input=_VALID_INPUT,
                    activated_by="test-operator",
                )
            )


class TestGetFeeTaxPolicy:
    def test_get_active_returns_none_when_nothing_registered(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()

        config, policy = asyncio.run(
            get_active_fee_tax_policy(repos, client_id=client_id, environment=Environment.LIVE)
        )
        assert config is None
        assert policy is None

    def test_get_active_returns_latest_published_policy(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()
        asyncio.run(
            publish_fee_tax_policy(
                repos,
                client_id=client_id,
                environment=Environment.LIVE,
                fee_tax_input=_VALID_INPUT,
                activated_by="test-operator",
            )
        )

        config, policy = asyncio.run(
            get_active_fee_tax_policy(repos, client_id=client_id, environment=Environment.LIVE)
        )
        assert config is not None
        assert policy is not None
        assert policy.enabled is True

    def test_get_at_returns_version_active_at_that_timestamp(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()
        earlier = datetime(2026, 1, 1, tzinfo=timezone.utc)
        later = datetime(2026, 6, 1, tzinfo=timezone.utc)

        asyncio.run(
            publish_fee_tax_policy(
                repos,
                client_id=client_id,
                environment=Environment.LIVE,
                fee_tax_input=_VALID_INPUT,
                activated_by="test-operator",
                activated_at=earlier,
            )
        )
        later_input = dict(_VALID_INPUT)
        later_input["buy_commission_rate_pct"] = "0.02"
        asyncio.run(
            publish_fee_tax_policy(
                repos,
                client_id=client_id,
                environment=Environment.LIVE,
                fee_tax_input=later_input,
                activated_by="test-operator",
                activated_at=later,
            )
        )

        config, policy = asyncio.run(
            get_fee_tax_policy_at(
                repos,
                client_id=client_id,
                environment=Environment.LIVE,
                at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            )
        )
        assert config is not None
        assert policy is not None
        assert str(policy.buy_commission_rate_pct) == "0.0140527"
