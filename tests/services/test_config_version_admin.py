"""``config_version_admin.publish_max_single_position_pct()`` 단위 테스트.

immutable append-only 계약(기존 row 미변경, 새 row만 추가), 검증 규칙
(0 초과/100 이하/중복 방지/활성 버전 없음), audit trail 기록을 확인한다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.domain.entities import ConfigVersionEntity
from agent_trading.domain.enums import Environment
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.config_version_admin import (
    ConfigVersionAdminError,
    publish_max_single_position_pct,
)


def _seed_active_config_version(repos, *, client_id, environment=Environment.PAPER):
    version = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=client_id,
        environment=environment,
        version_tag="v1.0",
        config_json={
            "risk": {
                "max_single_position_pct": "10",
                "min_cash_buffer_pct": "5",
            },
            "execution": {
                "max_order_value": "50000000",
            },
        },
        checksum="seed-checksum",
        activated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        activated_by="seed-script",
    )
    asyncio.run(repos.config_versions.add(version))
    return version


class TestPublishMaxSinglePositionPct:
    def test_publishes_new_version_with_only_target_key_changed(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()
        original = _seed_active_config_version(repos, client_id=client_id)

        result = asyncio.run(
            publish_max_single_position_pct(
                repos,
                client_id=client_id,
                environment=Environment.PAPER,
                max_single_position_pct=Decimal("15"),
                activated_by="test-operator",
                reason="risk appetite increase",
            )
        )

        assert result.previous_max_single_position_pct == "10"
        assert result.new_max_single_position_pct == "15"
        assert result.new.config_version_id != original.config_version_id

        # 새 config_json은 target 키만 바뀌고 나머지는 보존된다.
        assert result.new.config_json["risk"]["max_single_position_pct"] == "15"
        assert result.new.config_json["risk"]["min_cash_buffer_pct"] == "5"
        assert result.new.config_json["execution"]["max_order_value"] == "50000000"

        # 기존 row는 전혀 바뀌지 않았다(immutable append-only).
        stored_original = asyncio.run(repos.config_versions.get(original.config_version_id))
        assert stored_original is not None
        assert stored_original.config_json["risk"]["max_single_position_pct"] == "10"
        assert stored_original.activated_at == original.activated_at

        # get_active()는 새 버전을 가리킨다.
        active = asyncio.run(repos.config_versions.get_active(client_id, Environment.PAPER))
        assert active is not None
        assert active.config_version_id == result.new.config_version_id

    def test_writes_audit_log_entry(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()
        _seed_active_config_version(repos, client_id=client_id)

        asyncio.run(
            publish_max_single_position_pct(
                repos,
                client_id=client_id,
                environment=Environment.PAPER,
                max_single_position_pct=Decimal("20"),
                activated_by="test-operator",
                reason="widen concentration cap",
            )
        )

        # 이 서비스는 correlation_id를 세팅하지 않는다 — list_by_correlation_id()로는
        # 조회할 수 없어(그 필터는 str만 받음) 기존 테스트 관례대로 내부 저장소를
        # 직접 확인한다(예: tests/services/test_decision_orchestrator.py 등도 동일 패턴).
        entries = list(repos.audit_logs._items.values())  # type: ignore[attr-defined]
        assert len(entries) == 1
        entry = entries[0]
        assert entry.action == "config_version.risk.max_single_position_pct.update"
        assert entry.actor_id == "test-operator"
        assert entry.before_json["max_single_position_pct"] == "10"
        assert entry.after_json["max_single_position_pct"] == "20"
        assert entry.metadata["reason"] == "widen concentration cap"

    def test_rejects_zero(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()
        _seed_active_config_version(repos, client_id=client_id)

        with pytest.raises(ConfigVersionAdminError, match="constraint disabled"):
            asyncio.run(
                publish_max_single_position_pct(
                    repos,
                    client_id=client_id,
                    environment=Environment.PAPER,
                    max_single_position_pct=Decimal("0"),
                    activated_by="test-operator",
                )
            )

    def test_rejects_negative(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()
        _seed_active_config_version(repos, client_id=client_id)

        with pytest.raises(ConfigVersionAdminError):
            asyncio.run(
                publish_max_single_position_pct(
                    repos,
                    client_id=client_id,
                    environment=Environment.PAPER,
                    max_single_position_pct=Decimal("-5"),
                    activated_by="test-operator",
                )
            )

    def test_rejects_over_100(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()
        _seed_active_config_version(repos, client_id=client_id)

        with pytest.raises(ConfigVersionAdminError):
            asyncio.run(
                publish_max_single_position_pct(
                    repos,
                    client_id=client_id,
                    environment=Environment.PAPER,
                    max_single_position_pct=Decimal("100.01"),
                    activated_by="test-operator",
                )
            )

    def test_rejects_duplicate_of_current_active_value(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()
        _seed_active_config_version(repos, client_id=client_id)

        with pytest.raises(ConfigVersionAdminError, match="already 10"):
            asyncio.run(
                publish_max_single_position_pct(
                    repos,
                    client_id=client_id,
                    environment=Environment.PAPER,
                    max_single_position_pct=Decimal("10"),
                    activated_by="test-operator",
                )
            )

    def test_rejects_when_no_active_version_exists(self) -> None:
        repos = build_in_memory_repositories()
        client_id = uuid4()  # 시딩하지 않음 — 활성 버전 없음

        with pytest.raises(ConfigVersionAdminError, match="No active config_version"):
            asyncio.run(
                publish_max_single_position_pct(
                    repos,
                    client_id=client_id,
                    environment=Environment.PAPER,
                    max_single_position_pct=Decimal("10"),
                    activated_by="test-operator",
                )
            )

    def test_different_environment_is_independent(self) -> None:
        """같은 client라도 environment가 다르면 별개의 활성 버전을 본다."""
        repos = build_in_memory_repositories()
        client_id = uuid4()
        _seed_active_config_version(repos, client_id=client_id, environment=Environment.PAPER)

        with pytest.raises(ConfigVersionAdminError, match="No active config_version"):
            asyncio.run(
                publish_max_single_position_pct(
                    repos,
                    client_id=client_id,
                    environment=Environment.LIVE,
                    max_single_position_pct=Decimal("10"),
                    activated_by="test-operator",
                )
            )
