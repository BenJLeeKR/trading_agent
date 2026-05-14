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
from agent_trading.services.symbol_resolver import OpenDartSymbolResolver


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

    @pytest.mark.asyncio
    async def test_fetch_with_symbol_resolver_fallback(self) -> None:
        """fetch() with symbol_resolver: empty stock_code → corp_code fallback."""
        # stock_code가 빈 항목이 포함된 응답
        response_with_empty_stock: dict[str, Any] = {
            "status": "000",
            "message": "정상",
            "list": [
                {
                    "corp_code": "00123456",
                    "corp_name": "삼성전자",
                    "corp_cls": "Y",
                    "stock_code": "005930",  # 정상 stock_code
                    "report_nm": "사업보고서 (2023)",
                    "rcept_no": "20230101000001",
                    "rcept_dt": "20230101",
                    "rm": "정기공시",
                },
                {
                    "corp_code": "00999999",
                    "corp_name": "비상장법인",
                    "corp_cls": "E",
                    "stock_code": "",  # 빈 stock_code → fallback 필요
                    "report_nm": "기타공시",
                    "rcept_no": "20230102000002",
                    "rcept_dt": "20230102",
                    "rm": "기타공시",
                },
            ],
        }

        # Mock SymbolResolver
        mock_resolver = AsyncMock(spec=OpenDartSymbolResolver)
        mock_resolver.resolve.return_value = "999999"  # fallback 성공

        adapter = OpenDartSourceAdapter(
            api_key="test_key",
            symbol_resolver=mock_resolver,
        )

        with patch.object(adapter, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=response_with_empty_stock)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            events = await adapter.fetch()

        assert len(events) == 2
        # 첫 번째 항목: stock_code가 있으므로 그대로 사용
        assert events[0].symbol == "005930"
        # 두 번째 항목: stock_code가 없으므로 fallback 호출
        assert events[1].symbol == "999999"
        mock_resolver.resolve.assert_awaited_once_with("00999999")

        await adapter.close()

    @pytest.mark.asyncio
    async def test_fetch_with_symbol_resolver_fallback_failure(self) -> None:
        """fetch() with symbol_resolver: fallback 실패 시 symbol=None 유지."""
        response_with_empty_stock: dict[str, Any] = {
            "status": "000",
            "message": "정상",
            "list": [
                {
                    "corp_code": "00999999",
                    "corp_name": "비상장법인",
                    "corp_cls": "E",
                    "stock_code": "",
                    "report_nm": "기타공시",
                    "rcept_no": "20230102000002",
                    "rcept_dt": "20230102",
                    "rm": "기타공시",
                },
            ],
        }

        # Mock SymbolResolver — fallback 실패
        mock_resolver = AsyncMock(spec=OpenDartSymbolResolver)
        mock_resolver.resolve.return_value = None  # 매핑 실패

        adapter = OpenDartSourceAdapter(
            api_key="test_key",
            symbol_resolver=mock_resolver,
        )

        with patch.object(adapter, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=response_with_empty_stock)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            events = await adapter.fetch()

        assert len(events) == 1
        assert events[0].symbol is None  # fallback 실패 → None 유지
        mock_resolver.resolve.assert_awaited_once_with("00999999")

        await adapter.close()

    @pytest.mark.asyncio
    async def test_fetch_without_symbol_resolver_preserves_old_behavior(self) -> None:
        """symbol_resolver 미주입 시 기존 동작 유지 (빈 stock_code → None)."""
        response_with_empty_stock: dict[str, Any] = {
            "status": "000",
            "message": "정상",
            "list": [
                {
                    "corp_code": "00999999",
                    "corp_name": "비상장법인",
                    "corp_cls": "E",
                    "stock_code": "",
                    "report_nm": "기타공시",
                    "rcept_no": "20230102000002",
                    "rcept_dt": "20230102",
                    "rm": "기타공시",
                },
            ],
        }

        # symbol_resolver 없이 생성 (기존 방식)
        adapter = OpenDartSourceAdapter(api_key="test_key")

        with patch.object(adapter, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=response_with_empty_stock)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            events = await adapter.fetch()

        assert len(events) == 1
        assert events[0].symbol is None  # 기존 동작: None 유지

        await adapter.close()

    @pytest.mark.asyncio
    async def test_fetch_with_symbol_resolver_no_corp_code(self) -> None:
        """stock_code도 없고 corp_code도 없으면 resolver 호출 없이 None."""
        response_no_corp_code: dict[str, Any] = {
            "status": "000",
            "message": "정상",
            "list": [
                {
                    # corp_code 자체가 없는 경우
                    "corp_name": "알수없음",
                    "corp_cls": "E",
                    "stock_code": "",
                    "report_nm": "기타공시",
                    "rcept_no": "20230102000002",
                    "rcept_dt": "20230102",
                    "rm": "기타공시",
                },
            ],
        }

        mock_resolver = AsyncMock(spec=OpenDartSymbolResolver)
        adapter = OpenDartSourceAdapter(
            api_key="test_key",
            symbol_resolver=mock_resolver,
        )

        with patch.object(adapter, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=response_no_corp_code)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            events = await adapter.fetch()

        assert len(events) == 1
        assert events[0].symbol is None
        assert events[0].issuer_code is None
        # corp_code가 없으므로 resolver 호출 안 함
        mock_resolver.resolve.assert_not_called()

        await adapter.close()


# ---------------------------------------------------------------------------
# Importance classification tests
# ---------------------------------------------------------------------------


class TestOpenDartImportanceClassification:
    """_classify_importance() unit tests — H/M/L signal detection."""

    @pytest.mark.asyncio
    async def test_high_signal_capital_increase(self) -> None:
        """유상증자결정 → high."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)
        raw = RawEvent(
            source_name="opendart",
            source_event_id="h001",
            event_type="Y|유상증자결정",
            published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"report_nm": "유상증자결정", "rm": "기타공시"},
            issuer_code="00123456",
            headline="유상증자결정",
        )
        entity = await adapter.normalize(raw)
        assert entity.metadata is not None
        assert entity.metadata.get("importance") == "high"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_high_signal_sales_contract(self) -> None:
        """단일판매계약 → high."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)
        raw = RawEvent(
            source_name="opendart",
            source_event_id="h002",
            event_type="Y|단일판매·공급계약체결",
            published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"report_nm": "단일판매·공급계약체결", "rm": "기타공시"},
            issuer_code="00123456",
            headline="단일판매·공급계약체결",
        )
        entity = await adapter.normalize(raw)
        assert entity.metadata is not None
        assert entity.metadata.get("importance") == "high"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_high_signal_earnings(self) -> None:
        """영업(잠정)실적 → high."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)
        raw = RawEvent(
            source_name="opendart",
            source_event_id="h003",
            event_type="Y|영업(잠정)실적",
            published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"report_nm": "영업(잠정)실적", "rm": "기타공시"},
            issuer_code="00123456",
            headline="영업(잠정)실적",
        )
        entity = await adapter.normalize(raw)
        assert entity.metadata is not None
        assert entity.metadata.get("importance") == "high"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_medium_signal_credit_rating(self) -> None:
        """신용등급변동 → medium."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)
        raw = RawEvent(
            source_name="opendart",
            source_event_id="m001",
            event_type="Y|신용등급변동",
            published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"report_nm": "신용등급변동", "rm": "기타공시"},
            issuer_code="00123456",
            headline="신용등급변동",
        )
        entity = await adapter.normalize(raw)
        assert entity.metadata is not None
        assert entity.metadata.get("importance") == "medium"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_low_signal_regular_report(self) -> None:
        """정기공시(사업보고서) → low."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)
        raw = RawEvent(
            source_name="opendart",
            source_event_id="l001",
            event_type="Y|사업보고서",
            published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"report_nm": "사업보고서", "rm": "정기공시"},
            issuer_code="00123456",
            headline="사업보고서",
        )
        entity = await adapter.normalize(raw)
        assert entity.metadata is not None
        assert entity.metadata.get("importance") == "low"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_low_signal_correction(self) -> None:
        """정정공시 (non-matching) → low."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)
        raw = RawEvent(
            source_name="opendart",
            source_event_id="l002",
            event_type="Y|정정공시",
            published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"report_nm": "정정공시", "rm": "기타공시"},
            issuer_code="00123456",
            headline="정정공시",
        )
        entity = await adapter.normalize(raw)
        assert entity.metadata is not None
        assert entity.metadata.get("importance") == "low"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_low_signal_empty_report_nm(self) -> None:
        """빈 report_nm → low."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)
        raw = RawEvent(
            source_name="opendart",
            source_event_id="l003",
            event_type="Y|",
            published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"report_nm": "", "rm": "기타공시"},
            issuer_code="00123456",
            headline="",
        )
        entity = await adapter.normalize(raw)
        assert entity.metadata is not None
        assert entity.metadata.get("importance") == "low"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_normalize_preserves_source_raw_event_type(self) -> None:
        """normalize() preserves source_raw_event_type alongside importance."""
        adapter = OpenDartSourceAdapter(api_key="test_key")
        now = datetime.now(timezone.utc)
        raw = RawEvent(
            source_name="opendart",
            source_event_id="h004",
            event_type="Y|유상증자결정",
            published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            raw_payload={"report_nm": "유상증자결정", "rm": "기타공시"},
            issuer_code="00123456",
            headline="유상증자결정",
        )
        entity = await adapter.normalize(raw)
        assert entity.metadata is not None
        assert entity.metadata.get("source_raw_event_type") == "Y|유상증자결정"
        assert entity.metadata.get("importance") == "high"
        await adapter.close()
