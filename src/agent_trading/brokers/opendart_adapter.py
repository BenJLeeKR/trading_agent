"""OpenDART (금융감독원 전자공시) source adapter.

OpenDART is the official electronic disclosure system of the
Financial Supervisory Service (FSS) of South Korea.

Source reliability: T1_REGULATORY (highest trust tier).

v1 Scope (Priority 2)
---------------------
* Fetch disclosure list from ``/api/list.json``.
* Normalise raw disclosure items into ``ExternalEventEntity``.
* Store only — no AI classification, no semantic interpretation.
* ``event_type`` preserves the original OpenDART ``report_nm``
  and ``corp_cls`` classification.

API Reference
-------------
* Base URL: ``https://opendart.fss.or.kr/api``
* Authentication: ``crtfc_key`` (API key, required for all endpoints)
* Endpoints:
  - ``/list.json`` — disclosure list by date range
  - ``/company.json`` — company basic info
  - ``/fnlttSinglAcntAll.json`` — single company financial statements

v1 uses only ``/list.json``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import httpx

from agent_trading.brokers.dedup import DedupKeyGenerator
from agent_trading.brokers.source_adapter import RawEvent, SourceAdapter
from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.domain.enums import SourceReliabilityTier

logger = logging.getLogger(__name__)

OPENDART_BASE_URL = "https://opendart.fss.or.kr/api"

# OpenDART status codes
_STATUS_SUCCESS = "000"

# ── Disclosure importance classification ──────────────────────────────
# High-signal keywords — disclosures with direct price impact potential.
_HIGH_SIGNAL_KEYWORDS: set[str] = {
    "유상증자결정",
    "무상증자결정",
    "단일판매",  # 단일판매ㆍ공급계약체결
    "영업(잠정)실적",
    "영업실적",
    "최대주주변경",
    "합병결정",
    "분할결정",
    "영업양수도",
    "자기주식취득",
    "자기주식처분",
    "배당결정",
    "횡령",  # 횡령ㆍ배임발생
    "배임",
    "대규모손실",
    "회생",  # 회생절차개시
    "파산",
    "감사의견비적정",
    "전환사채권발행결정",
    "신주인수권부사채발행결정",
    "주식관련사채권발행결정",
    "기업결합신고",
    "대량보유상황보고서",
}

# Medium-signal keywords — situation-dependent relevance.
_MEDIUM_SIGNAL_KEYWORDS: set[str] = {
    "액면변경",
    "신규시장상장",
    "신용등급변동",
    "사업재편",
    "주주총회소집",
    "증권신고서",
    "임원",  # 임원ㆍ주요주주소유
    "주요사항보고서",
    "주식매수선택권",
    "채권발행",
}

# Low-signal disclosure types (rm field).
_LOW_SIGNAL_RM_TYPES: set[str] = {
    "정기공시",
}


def _classify_importance(report_nm: str, rm: str | None) -> str:
    """Classify disclosure importance based on ``report_nm`` and ``rm``.

    Returns one of ``"high"``, ``"medium"``, or ``"low"``.

    Rules
    -----
    1. High signal: ``report_nm`` contains any keyword from
       ``_HIGH_SIGNAL_KEYWORDS``.
    2. Medium signal: ``report_nm`` contains any keyword from
       ``_MEDIUM_SIGNAL_KEYWORDS``.
    3. Low signal: ``rm`` is ``"정기공시"`` (regular disclosure).
    4. Default: ``"low"`` (catch-all for unmatched disclosures).
    """
    if not report_nm:
        return "low"

    # 1. High signal — keyword match
    for kw in _HIGH_SIGNAL_KEYWORDS:
        if kw in report_nm:
            return "high"

    # 2. Medium signal — keyword match
    for kw in _MEDIUM_SIGNAL_KEYWORDS:
        if kw in report_nm:
            return "medium"

    # 3. Low signal — regular disclosure type
    if rm and rm in _LOW_SIGNAL_RM_TYPES:
        return "low"

    # 4. Default: low (catch-all)
    return "low"


class OpenDartSourceAdapter:
    """Source adapter for OpenDART (금융감독원 전자공시).

    Parameters
    ----------
    api_key : str
        OpenDART API authentication key (``crtfc_key``).
    base_url : str
        OpenDART API base URL (default: production).
    request_timeout : int
        HTTP request timeout in seconds.

    v1 scope: fetch disclosure list → normalise → store.
    No AI classification, no semantic interpretation.
    """

    source_name = "opendart"
    reliability_tier = SourceReliabilityTier.T1_REGULATORY

    def __init__(
        self,
        api_key: str,
        base_url: str = OPENDART_BASE_URL,
        request_timeout: int = 30,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._request_timeout = request_timeout
        self._client: httpx.AsyncClient | None = None
        self._last_poll: datetime | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._request_timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self) -> Sequence[RawEvent]:
        """Fetch new disclosures since the last poll.

        Calls ``/api/list.json`` with a date range from the last poll
        timestamp (or yesterday if first poll) to now.

        Returns
        -------
        Sequence[RawEvent]
            Raw disclosure events. Empty if no new disclosures or API error.
        """
        now = datetime.now(timezone.utc)
        bgn_de = (self._last_poll or (now - timedelta(days=1))).strftime("%Y%m%d")
        end_de = now.strftime("%Y%m%d")
        self._last_poll = now

        client = await self._get_client()

        try:
            response = await client.get(
                "/list.json",
                params={
                    "crtfc_key": self._api_key,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                    "page_no": 1,
                    "page_count": 100,
                },
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except Exception:
            logger.exception(
                "OpenDART API request failed (bgn_de=%s, end_de=%s)",
                bgn_de,
                end_de,
            )
            return []

        status = data.get("status", "")
        if status != _STATUS_SUCCESS:
            message = data.get("message", "Unknown error")
            logger.warning(
                "OpenDART API returned non-success status=%s message=%s",
                status,
                message,
            )
            return []

        items: list[dict[str, Any]] = data.get("list", [])
        if not items:
            return []

        return [self._raw_from_item(item, now) for item in items]

    def _raw_from_item(self, item: dict[str, Any], ingested_at: datetime) -> RawEvent:
        """Convert an OpenDART API item into a ``RawEvent``.

        v1: preserves original OpenDART classification (``corp_cls``,
        ``report_nm``) as ``event_type``. No AI classification.
        """
        corp_cls = item.get("corp_cls", "")
        report_nm = item.get("report_nm", "")
        # event_type = original OpenDART classification (v1: no AI)
        event_type = f"{corp_cls}|{report_nm}" if corp_cls else report_nm

        rcept_dt_str = item.get("rcept_dt", "")
        published_at: datetime
        try:
            published_at = datetime.strptime(rcept_dt_str, "%Y%m%d").replace(
                tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            published_at = ingested_at

        return RawEvent(
            source_name=self.source_name,
            source_event_id=item.get("rcept_no", ""),
            event_type=event_type,
            published_at=published_at,
            ingested_at=ingested_at,
            source_reliability_tier=self.reliability_tier.value,
            raw_payload=item,
            symbol=item.get("stock_code") or None,
            issuer_code=item.get("corp_code"),
            market=None,
            headline=report_nm,
            body=None,
        )

    async def normalize(self, raw: RawEvent) -> ExternalEventEntity:
        """Convert a ``RawEvent`` into a normalised ``ExternalEventEntity``.

        v1 scope: field mapping only — no AI classification.
        Importance classification is computed from the raw payload.
        """
        dedup_key = self.generate_dedup_key(raw)

        # Classify importance from raw payload fields
        report_nm = raw.raw_payload.get("report_nm", "") or ""
        rm = raw.raw_payload.get("rm", None)
        importance = _classify_importance(report_nm, rm)

        return ExternalEventEntity(
            event_id=uuid4(),
            event_type=raw.event_type,
            source_name=raw.source_name,
            published_at=raw.published_at,
            source_reliability_tier=raw.source_reliability_tier,
            source_event_id=raw.source_event_id,
            issuer_code=raw.issuer_code,
            symbol=raw.symbol,
            market=raw.market,
            ingested_at=raw.ingested_at,
            effective_at=raw.published_at,
            severity="medium",
            direction="neutral",
            headline=raw.headline,
            body_summary=raw.body,
            raw_payload_uri=None,
            dedup_key_hash=dedup_key,
            supersedes_event_id=None,
            metadata={
                "source_raw_event_type": raw.event_type,
                "importance": importance,
            },
            created_at=None,
        )

    def generate_dedup_key(self, raw: RawEvent) -> str:
        """Generate a deterministic dedup key for an OpenDART raw event.

        Uses source-specific stable fields:
        ``opendart|{rcept_no}|{event_type}|{corp_code}``

        The same ``rcept_no`` (접수번호) + ``event_type`` → same event,
        even if payload content differs (e.g. amended disclosure).
        """
        return DedupKeyGenerator.generate_from_raw(
            source_name=raw.source_name,
            source_event_id=raw.source_event_id,
            event_type=raw.event_type,
            symbol=raw.symbol,
            issuer_code=raw.issuer_code,
        )
