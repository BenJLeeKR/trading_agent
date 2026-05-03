from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agent_trading.domain.entities import ClientEntity, ConfigVersionEntity
from agent_trading.domain.enums import Environment


@pytest.fixture
def sample_config_version(client_id) -> ConfigVersionEntity:
    return ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=client_id,
        environment=Environment.PAPER,
        version_tag="test-v1.0",
        config_json={"max_position_size": "0.1", "risk_limit": "0.05"},
        checksum="abc123def456",
        created_at=datetime.now(timezone.utc),
        activated_at=datetime.now(timezone.utc),
        activated_by="test-user",
    )


@pytest.fixture
def sample_config_version_v2(client_id) -> ConfigVersionEntity:
    return ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=client_id,
        environment=Environment.PAPER,
        version_tag="test-v2.0",
        config_json={"max_position_size": "0.2", "risk_limit": "0.03"},
        checksum="ghi789jkl012",
        created_at=datetime.now(timezone.utc),
        activated_at=datetime.now(timezone.utc),
        activated_by="test-user",
    )


@pytest.mark.asyncio
async def test_add_and_get(seeded_postgres_data, sample_config_version) -> None:
    added = await seeded_postgres_data.config_versions.add(sample_config_version)
    assert added.config_version_id == sample_config_version.config_version_id
    assert added.version_tag == "test-v1.0"
    assert added.config_json == {"max_position_size": "0.1", "risk_limit": "0.05"}

    fetched = await seeded_postgres_data.config_versions.get(
        sample_config_version.config_version_id
    )
    assert fetched is not None
    assert fetched.config_version_id == sample_config_version.config_version_id
    assert fetched.checksum == "abc123def456"


@pytest.mark.asyncio
async def test_get_nonexistent(seeded_postgres_data) -> None:
    fetched = await seeded_postgres_data.config_versions.get(uuid4())
    assert fetched is None


@pytest.mark.asyncio
async def test_get_active(
    seeded_postgres_data, sample_config_version, sample_config_version_v2, client_id
) -> None:
    # Add v1 first, then v2 (newer activated_at)
    await seeded_postgres_data.config_versions.add(sample_config_version)
    await seeded_postgres_data.config_versions.add(sample_config_version_v2)

    active = await seeded_postgres_data.config_versions.get_active(
        client_id, Environment.PAPER
    )
    assert active is not None
    # v2 should be returned (most recently activated)
    assert active.version_tag == "test-v2.0"


@pytest.mark.asyncio
async def test_get_active_no_activation(
    postgres_repos, sample_client: ClientEntity
) -> None:
    """A config version with NULL activated_at should sort after
    activated versions, so the activated version is returned."""
    # Seed the client first (FK target)
    await postgres_repos.clients.add(sample_client)

    # Add an activated version first
    activated = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=sample_client.client_id,
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={"max_position_size": "0.1"},
        checksum="activated",
        created_at=datetime.now(timezone.utc),
        activated_at=datetime.now(timezone.utc),
        activated_by="test-user",
    )
    await postgres_repos.config_versions.add(activated)

    # Add an unactivated version (NULL activated_at)
    unactivated = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=sample_client.client_id,
        environment=Environment.PAPER,
        version_tag="v0.9",
        config_json={"max_position_size": "0.05"},
        checksum="no-activation",
        created_at=datetime.now(timezone.utc),
        activated_at=None,
        activated_by=None,
    )
    await postgres_repos.config_versions.add(unactivated)

    active = await postgres_repos.config_versions.get_active(
        sample_client.client_id, Environment.PAPER
    )
    # NULL activated_at should sort last, so v1.0 is returned
    assert active is not None
    assert active.version_tag == "v1.0"


@pytest.mark.asyncio
async def test_get_active_nonexistent(seeded_postgres_data, client_id) -> None:
    active = await seeded_postgres_data.config_versions.get_active(
        client_id, Environment.LIVE
    )
    assert active is None
