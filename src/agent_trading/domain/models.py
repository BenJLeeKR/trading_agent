from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from agent_trading.domain.enums import (
    AssetClass,
    BrokerName,
    MarketDataChannel,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)


@dataclass(slots=True, frozen=True)
class RateLimitProfile:
    requests_per_second: int | None = None
    burst_limit: int | None = None
    notes: str | None = None


@dataclass(slots=True, frozen=True)
class BrokerCapability:
    broker_name: BrokerName
    supports_paper_trading: bool
    supports_live_trading: bool
    supports_websocket: bool
    supported_asset_classes: tuple[AssetClass, ...]
    supported_order_types: tuple[OrderType, ...]
    supported_time_in_force: tuple[TimeInForce, ...]
    supports_order_amend: bool = False
    supports_order_cancel: bool = True
    rate_limit_profile: RateLimitProfile | None = None


@dataclass(slots=True, frozen=True)
class BrokerHealth:
    broker_name: BrokerName
    healthy: bool
    checked_at: datetime
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class BrokerSession:
    broker_name: BrokerName
    authenticated_at: datetime
    expires_at: datetime | None = None
    approval_key_expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class Quote:
    symbol: str
    market: str
    bid: Decimal | None
    ask: Decimal | None
    last: Decimal | None
    as_of: datetime
    currency: str = "KRW"


@dataclass(slots=True, frozen=True)
class OrderBookLevel:
    price: Decimal
    quantity: Decimal


@dataclass(slots=True, frozen=True)
class OrderBook:
    symbol: str
    market: str
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    as_of: datetime


@dataclass(slots=True, frozen=True)
class Position:
    account_ref: str
    symbol: str
    quantity: Decimal
    average_price: Decimal
    market_price: Decimal | None
    currency: str = "KRW"


@dataclass(slots=True, frozen=True)
class CashBalance:
    account_ref: str
    available_cash: Decimal
    settled_cash: Decimal | None = None
    currency: str = "KRW"
    as_of: datetime | None = None


@dataclass(slots=True, frozen=True)
class SubmitOrderRequest:
    """Order submission request sent to a broker adapter.

    Extended in Milestone 5 with fields for idempotency, decision tracing,
    price bands, slippage control, and metadata.
    """

    account_ref: str
    client_order_id: str
    correlation_id: str
    strategy_id: str
    symbol: str
    market: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    time_in_force: TimeInForce = TimeInForce.DAY
    price: Decimal | None = None
    # --- Milestone 5 extensions ---
    idempotency_key: str | None = None
    decision_id: str | None = None
    decision_context_id: str | None = None
    order_intent_id: str | None = None
    price_band_lower: Decimal | None = None
    price_band_upper: Decimal | None = None
    max_slippage_bps: int | None = None
    allow_partial_fill: bool = True
    client_timestamp: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SubmitOrderResult:
    """Result returned by a broker adapter after order submission.

    Extended in Milestone 5 with fields for idempotency, normalized status,
    exchange timestamps, uncertainty flags, and reconciliation hints.
    """

    accepted: bool
    broker_name: BrokerName
    client_order_id: str
    broker_order_id: str | None
    broker_status: OrderStatus
    ack_timestamp: datetime | None
    raw_code: str | None = None
    raw_message: str | None = None
    # --- Milestone 5 extensions ---
    idempotency_key: str | None = None
    normalized_status: OrderStatus | None = None
    exchange_timestamp: datetime | None = None
    raw_payload_uri: str | None = None
    uncertain: bool = False
    requires_reconciliation: bool = False


@dataclass(slots=True, frozen=True)
class CancelOrderRequest:
    account_ref: str
    client_order_id: str
    broker_order_id: str | None
    correlation_id: str
    reason: str | None = None


@dataclass(slots=True, frozen=True)
class CancelOrderResult:
    accepted: bool
    broker_name: BrokerName
    client_order_id: str
    broker_order_id: str | None
    broker_status: OrderStatus
    raw_code: str | None = None
    raw_message: str | None = None


@dataclass(slots=True, frozen=True)
class AmendOrderRequest:
    account_ref: str
    client_order_id: str
    broker_order_id: str | None
    correlation_id: str
    new_quantity: Decimal | None = None
    new_price: Decimal | None = None


@dataclass(slots=True, frozen=True)
class AmendOrderResult:
    accepted: bool
    broker_name: BrokerName
    client_order_id: str
    broker_order_id: str | None
    broker_status: OrderStatus
    raw_code: str | None = None
    raw_message: str | None = None


@dataclass(slots=True, frozen=True)
class OrderStatusResult:
    broker_name: BrokerName
    client_order_id: str | None
    broker_order_id: str | None
    status: OrderStatus
    filled_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal | None = None
    average_fill_price: Decimal | None = None
    last_updated_at: datetime | None = None
    raw_code: str | None = None
    raw_message: str | None = None


@dataclass(slots=True, frozen=True)
class FillEvent:
    broker_name: BrokerName
    broker_order_id: str
    symbol: str
    side: OrderSide
    fill_quantity: Decimal
    fill_price: Decimal
    fill_timestamp: datetime
    broker_fill_id: str | None = None  # broker-native fill identifier (e.g. KIS CCLD_NUM)
    fee: Decimal | None = None
    tax: Decimal | None = None


@dataclass(slots=True, frozen=True)
class DisclosureTitleDTO:
    """KIS FHKST01011800 공시 제목 정규화 응답.

    Attributes
    ----------
    symbol: 종목코드 (ex: 005930)
    company_name: 종목명 (ex: 삼성전자, KIS 응답 kor_isnm1~10에서 추출)
    headline: 공시 제목 (hts_pbnt_titl_cntt, 최대 400자)
    published_at: 발행 시각 (data_dt + data_tm 조합, KIS 응답 형식 그대로)
    source: 데이터 출처 식별자 (NAVER SourceAdapter 연결 포인트)
    """
    symbol: str
    """종목코드 (ex: 005930)"""
    company_name: str | None = None
    """종목명 (ex: 삼성전자)"""
    headline: str | None = None
    """공시 제목 (hts_pbnt_titl_cntt, 최대 400자)"""
    published_at: str | None = None
    """공시 일시 (KIS 응답 data_dt + data_tm 조합)"""
    source: str = "kis_disclosure_live"
    """데이터 출처 식별자 (NAVER SourceAdapter 연결 포인트)"""


@dataclass(slots=True, frozen=True)
class MarketDataSubscription:
    channel: MarketDataChannel
    symbol: str
    market: str


@dataclass(slots=True, frozen=True)
class SeededNewsCandidate:
    """KIS-seeded NAVER news candidate for EI consumption.

    This is a **transient** DTO — stored in memory only until EI integration.
    KIS 공시 제목을 seed로 NAVER 뉴스 검색 API를 호출한 결과를 정규화한 DTO.
    Scoring, Dedupe, Hard Gate 통과 후 EI Agent에 전달된다.

    Attributes
    ----------
    symbol: 종목코드 (ex: 005930)
    company_name: 종목명 (ex: 삼성전자)
    seed_headline: KIS disclosure title (the search seed)
    related_news_title: NAVER news title (HTML stripped)
    related_news_summary: NAVER news description/summary (HTML stripped)
    link: original article URL (NAVER ``link`` 필드)
    published_at: article publication datetime (RFC 3339, 정규화 완료)
    source: data source identifier (기본값 ``naver_news_seeded``)
    confidence_score: computed relevance score (0-100)
    seed_source: origin of the seed (기본값 ``kis_disclosure_live``)
    query_used: 검색에 사용된 query string (logging 용)
    originallink: NAVER ``originallink`` (언론사 원본 URL, dedupe 용)
    """
    symbol: str
    """종목코드 (ex: 005930)"""
    company_name: str | None = None
    """종목명 (ex: 삼성전자)"""
    seed_headline: str | None = None
    """KIS disclosure title (the search seed)"""
    related_news_title: str = ""
    """NAVER news title (HTML stripped)"""
    related_news_summary: str | None = None
    """NAVER news description/summary (HTML stripped)"""
    link: str = ""
    """Original article URL (NAVER ``link`` field)"""
    published_at: datetime | None = None
    """RFC 3339 datetime (정규화 완료). 외부 표시 시에만 문자열 변환."""
    source: str = "naver_news_seeded"
    """데이터 출처 식별자 (기본값 ``naver_news_seeded``)"""
    confidence_score: float = 0.0
    """Computed relevance score (0-100)"""
    seed_source: str = "kis_disclosure_live"
    """Origin of the seed (기본값 ``kis_disclosure_live``)"""
    query_used: str | None = None
    """검색에 사용된 query string (logging/diagnostics 용)"""
    originallink: str | None = None
    """NAVER ``originallink`` (언론사 원본 URL, dedupe 용)"""

