"""Tests for OpenDartSourceAdapter."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_trading.brokers.opendart_adapter import OpenDartSourceAdapter
from agent_trading.brokers.source_adapter import RawEvent
from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.domain.enums import SourceReliabilityTier


# ---------------------------------------------------------------------------
# Sample OpenDART API response
# ---------------------------------------------------------------------------

_SAMPLE_LIST_RESPONSE: dict[str, Any] = {
    "status": "000",
    "message": "정상",
    "list": [
        {
            "corp_code": "00123456",
            "corp_name": "삼성전자",
            "corp_cls": "Y",
            "stock_code": "005930",
            "report_nm": "사업보고서 (2023)",
            "rcept_no": "20230101000001",
            "rcept_dt": "20230101",
            "rm": "정기공시",
        },
        {
            "corp_code": "00765432",
            "corp_name": "SK하이닉스",
            "corp_cls": "Y",
            "stock_code": "000660",
            "report_nm": "반기보고서 (2023)",
            "rcept_no": "20230102000002",
            "rcept_dt": "20230102",
            "rm": "정기공시",
        },
    ],
}

_EMPTY_LIST_RESPONSE: dict[str, Any] = {
    "status": "000",
    "message": "정상",
    "list": [],
}

_ERROR_RESPONSE: dict[str, Any] = {
    "status": "999",
    "message": "조회된 데이터가 없습니다.",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOpenDartSourceAdapter:
    """OpenDartSourceAdapter fetch, normalize, dedup key."""

    @pytest.mark.asyncio
    async def test_source_name_and_tier(self) -> None:
        """source_name and reliability_tier are correctly set."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        assert adapter.source_name == "opendart"
        assert adapter.reliability_tier == SourceReliabilityTier.T1_REGULATORY
        await adapter.close()

    @pytest.mark.asyncio
    async def test_fetch_returns_raw_events(self) -> None:
        """fetch() returns RawEvent objects from API response."""
        adapter = OpenDartSourceAdapter(api_key="test_key")

        with patch.object(adapter, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=_SAMPLE_LIST_RESPONSE)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            events = await adapter.fetch()

        assert len(events) == 2
        assert all(isinstance(e, RawEvent) for e in events)
        assert events[0].source_name == "opendart"
        assert events[0].source_event_id == "20230101000001"
        assert events[0].issuer_code == "00123456"
        assert events[0].headline == "사업보고서 (2023)"
        # P0-1: stock_code → symbol 매핑 검증
        assert events[0].symbol == "005930"
        assert events[1].symbol == "000660"

        await adapter.close()

    @pytest.mark.asyncio
    async def test_fetch_empty_list(self) -> None:
        """fetch() returns empty list when API returns no items."""
        adapter = OpenDartSourceAdapter(api_key="test_key")

        with patch.object(adapter, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=_EMPTY_LIST_RESPONSE)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            events = await adapter.fetch()

        assert len(events) == 0
        await adapter.close()

    @pytest.mark.asyncio
    async def test_fetch_error_status(self) -> None:
        """fetch() returns empty list when API returns error status."""
        adapter = OpenDartSourceAdapter(api_key="test_key")

        with patch.object(adapter, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=_ERROR_RESPONSE)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            events = await adapter.fetch()

        assert len(events) == 0
        await adapter.close()

    @pytest.mark.asyncio
    async def test_fetch_http_error(self) -> None:
        """fetch() returns empty list on HTTP error."""
        adapter = OpenDartSourceAdapter(api_key="test_key")

        with patch.object(adapter, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection error"))
            mock_get_client.return_value = mock_client

            events = await adapter.fetch()

        assert len(events) == 0
        await adapter.close()

    @pytest.mark.asyncio
    async def test_normalize_returns_external_event_entity(self) -> None:
        """normalize() converts RawEvent to ExternalEventEntity."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)

        raw = RawEvent(
            source_name="opendart",
            source_event_id="20230101000001",
            event_type="Y|사업보고서 (2023)",
            published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"corp_code": "00123456", "report_nm": "사업보고서 (2023)"},
            issuer_code="00123456",
            headline="사업보고서 (2023)",
        )

        entity = await adapter.normalize(raw)

        assert isinstance(entity, ExternalEventEntity)
        assert entity.source_name == "opendart"
        assert entity.source_event_id == "20230101000001"
        assert entity.event_type == "Y|사업보고서 (2023)"
        assert entity.issuer_code == "00123456"
        assert entity.headline == "사업보고서 (2023)"
        assert entity.dedup_key_hash is not None
        assert entity.source_reliability_tier == SourceReliabilityTier.T1_REGULATORY.value

        await adapter.close()

    @pytest.mark.asyncio
    async def test_normalize_preserves_event_type(self) -> None:
        """normalize() preserves original OpenDART classification as event_type.

        v1: no AI classification — original corp_cls|report_nm is preserved.
        """
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)

        raw = RawEvent(
            source_name="opendart",
            source_event_id="20230101000001",
            event_type="Y|사업보고서 (2023)",
            published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={},
            issuer_code="00123456",
        )

        entity = await adapter.normalize(raw)
        assert entity.event_type == "Y|사업보고서 (2023)"

        await adapter.close()

    def test_generate_dedup_key_stable(self) -> None:
        """generate_dedup_key() uses source-specific stable fields."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)

        raw = RawEvent(
            source_name="opendart",
            source_event_id="20230101000001",
            event_type="Y|사업보고서 (2023)",
            published_at=now,
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={},
            issuer_code="00123456",
        )

        key1 = adapter.generate_dedup_key(raw)
        key2 = adapter.generate_dedup_key(raw)
        assert key1 == key2  # deterministic

    def test_generate_dedup_key_payload_independent(self) -> None:
        """generate_dedup_key() does NOT depend on payload content."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)

        raw1 = RawEvent(
            source_name="opendart",
            source_event_id="20230101000001",
            event_type="Y|사업보고서 (2023)",
            published_at=now,
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"original": "data"},
            issuer_code="00123456",
        )
        raw2 = RawEvent(
            source_name="opendart",
            source_event_id="20230101000001",  # same source_event_id
            event_type="Y|사업보고서 (2023)",  # same event_type
            published_at=now,
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"amended": "data"},  # different payload
            issuer_code="00123456",
        )

        key1 = adapter.generate_dedup_key(raw1)
        key2 = adapter.generate_dedup_key(raw2)
        assert key1 == key2  # same stable fields → same key

    @pytest.mark.asyncio
    async def test_fetch_sets_ingested_at(self) -> None:
        """fetch() sets ingested_at on each RawEvent."""
        adapter = OpenDartSourceAdapter(api_key="test_key")

        with patch.object(adapter, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=_SAMPLE_LIST_RESPONSE)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            events = await adapter.fetch()

        assert len(events) == 2
        for event in events:
            assert event.ingested_at is not None
            assert isinstance(event.ingested_at, datetime)

        await adapter.close()

    @pytest.mark.asyncio
    async def test_fetch_publishe_datetime_parsed(self) -> None:
        """fetch() parses rcept_dt string into datetime."""
        adapter = OpenDartSourceAdapter(api_key="test_key")

        with patch.object(adapter, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=_SAMPLE_LIST_RESPONSE)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            events = await adapter.fetch()

        assert len(events) == 2
        assert events[0].published_at == datetime(2023, 1, 1, tzinfo=timezone.utc)
        assert events[1].published_at == datetime(2023, 1, 2, tzinfo=timezone.utc)

        await adapter.close()
