"""Market session provider — 거래일/장운영 정보 추상화 레이어.

``MarketSessionProvider`` 인터페이스와 두 구현체를 제공합니다:

1. ``KisHolidayProvider``: KIS 076 API (국내휴장일조회)를 통해 실제 거래일 확인
2. ``FallbackSessionProvider``: 주말 heuristic + 시간표 기반 fallback

아키텍처 원칙
=============
- ``MarketSessionProvider``는 스케줄러가 phase 전이 전에 호출하는 session gate입니다.
- ``KisHolidayProvider``는 ``KISHolidayClient`` (076 전용)를 사용하며,
  ``KISRestClient``(주문/잔고/체결)와는 **완전히 분리**되어 있습니다.
- 076 API 실패 시 ``FallbackSessionProvider``로 체인 fallback합니다.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import AsyncGenerator

from agent_trading.brokers.koreainvestment.holiday_client import (
    KISHolidayClient,
    KISHolidayError,
    HolidayStatus,
)
from agent_trading.brokers.koreainvestment.market_state_client import (
    MarketPhaseCode,
    MarketStateProvider,
)

logger = logging.getLogger(__name__)

# Advisory lock key for scheduler duplicate execution prevention.
# Encoded "OPS_SCHEDULER" as int64 — 0x4E454152_5245414C
SCHEDULER_ADVISORY_LOCK_KEY: int = 0x4E454152_5245414C


@asynccontextmanager
async def try_scheduler_lock(pool) -> AsyncGenerator[bool, None]:
    """PostgreSQL advisory lock으로 scheduler 중복 실행 방지.

    사용법:
        async with try_scheduler_lock(pool) as acquired:
            if not acquired:
                logger.warning("Another ops-scheduler instance holds the lock — exiting")
                return
            # ... scheduler main loop ...

    Lock은 connection/session 레벨에서 유지되므로,
    - 컨테이너가 죽으면 자동 해제
    - 동일 컨테이너 내에서는 재진입 가능
    - 다른 컨테이너/호스트에서는 획득 불가
    """
    acquired = False
    try:
        # pg_try_advisory_lock: non-blocking lock attempt
        # Returns True if lock acquired, False if already held by another session
        row = await pool.fetchrow(
            "SELECT pg_try_advisory_lock($1) AS acquired",
            SCHEDULER_ADVISORY_LOCK_KEY,
        )
        acquired = row["acquired"] if row else False

        if acquired:
            logger.info("Ops-scheduler advisory lock acquired (key=0x%X)", SCHEDULER_ADVISORY_LOCK_KEY)

        yield acquired
    finally:
        if acquired:
            await pool.execute(
                "SELECT pg_advisory_unlock($1)",
                SCHEDULER_ADVISORY_LOCK_KEY,
            )
            logger.info("Ops-scheduler advisory lock released")

# ---------------------------------------------------------------------------
# SessionInfo — session gate 결과값 (P2: 163 필드 추가)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Session gate 평가 결과.

    Attributes:
        is_trading_day: 거래일 여부 (``opnd_yn == 'Y'``)
        opnd_yn: KIS 개장일여부 원본값 (API 응답 또는 fallback 추정)
        bzdy_yn: KIS 영업일여부 원본값
        tr_day_yn: KIS 거래일여부 원본값
        source: 정보 출처 (``"kis_holiday_api"`` / ``"fallback"`` /
                ``"combined"`` / ``"kis_163"``)
        reason: 상세 메시지 (skip 이유 등)
        market_phase: 163 WebSocket 실시간 장운영 phase (``None`` if not available)
        raw_opnd_yn: 076 API 응답의 opnd_yn 원본 값 (``None`` if not available)
        raw_mkop_cls_code: 163 WebSocket 응답의 mkop_cls_code 원본 값
        raw_antc_mkop_cls_code: 163 WebSocket 응답의 antc_mkop_cls_code 원본 값
        checked_at: 마지막 확인 시각 (UTC, ``None`` if not available)
    """

    is_trading_day: bool
    opnd_yn: str = "N"
    bzdy_yn: str = "N"
    tr_day_yn: str = "N"
    source: str = "unknown"
    reason_code: str | None = None
    reason: str = ""
    # P2: 163 WebSocket fields (None-default for backward compatibility)
    market_phase: str | None = None
    raw_opnd_yn: str | None = None
    raw_mkop_cls_code: str | None = None
    raw_antc_mkop_cls_code: str | None = None
    checked_at: datetime | None = None


# ---------------------------------------------------------------------------
# MarketSessionProvider (ABC)
# ---------------------------------------------------------------------------


class MarketSessionProvider(ABC):
    """거래일/장운영 정보 제공자 추상 베이스 클래스.

    스케줄러는 phase 전이 전에 ``is_trading_day()``를 호출하여
    오늘이 실제 거래일인지 확인합니다.
    """

    @abstractmethod
    async def is_trading_day(self, target_date: date) -> bool:
        """``target_date``가 거래일인지 확인.

        Returns:
            ``True``: 거래일 (pre-market/intraday/EOD 실행 가능)
            ``False``: 비거래일 (해당 phase skip)
        """
        ...

    @abstractmethod
    async def get_session_info(self, target_date: date) -> SessionInfo:
        """``target_date``의 상세 session 정보 반환.

        Returns:
            ``SessionInfo`` dataclass (출처, opnd_yn 등 포함)
        """
        ...


# ---------------------------------------------------------------------------
# KisHolidayProvider — 076 API 기반
# ---------------------------------------------------------------------------


class KisHolidayProvider(MarketSessionProvider):
    """KIS 076 국내휴장일조회 API 기반 거래일 제공자.

    ``KISHolidayClient``를 통해 실시간으로 휴장일 정보를 조회합니다.
    API 호출 실패 시 ``KISHolidayError``를 발생시키며,
    호출자(스케줄러)에서 ``FallbackSessionProvider``로 fallback해야 합니다.

    Note:
        KIS 권장사항: 076 API는 **1일 1회**만 호출할 것.
        단시간 내 다수 호출시 KIS 원장 서비스에 영향을 줄 수 있음.
    """

    def __init__(self, holiday_client: KISHolidayClient) -> None:
        self._client = holiday_client
        # Cache last result per date to avoid repeated calls (1일 1회 정책)
        self._cache: dict[date, SessionInfo] = {}

    async def is_trading_day(self, target_date: date) -> bool:
        info = await self.get_session_info(target_date)
        return info.is_trading_day

    async def get_session_info(self, target_date: date) -> SessionInfo:
        """076 API 호출 → ``SessionInfo`` 반환.

        동일 날짜에 대한 결과를 메모리 캐시하여 1일 1회 호출 정책을 준수합니다.
        """
        # Cache hit
        cached = self._cache.get(target_date)
        if cached is not None:
            logger.debug(
                "KisHolidayProvider: cache hit for %s (source=%s)",
                target_date.isoformat(),
                cached.source,
            )
            return cached

        date_str = target_date.strftime("%Y%m%d")
        try:
            status: HolidayStatus = await self._client.get_holiday_status(date_str)
        except KISHolidayError as exc:
            logger.error(
                "KisHolidayProvider: 076 API failed for %s — %s",
                date_str,
                exc,
            )
            raise  # 호출자에서 fallback 처리

        info = SessionInfo(
            is_trading_day=status.is_trading_day,
            opnd_yn=status.opnd_yn,
            bzdy_yn=status.bzdy_yn,
            tr_day_yn=status.tr_day_yn,
            source="kis_holiday_api",
            reason_code="KIS_HOLIDAY_TRADING_DAY" if status.is_trading_day else "KIS_HOLIDAY_CLOSED",
            reason=f"opnd_yn={status.opnd_yn} bzdy_yn={status.bzdy_yn} tr_day_yn={status.tr_day_yn}",
        )

        # Cache for the day
        self._cache[target_date] = info
        logger.info(
            "KisHolidayProvider: session_info date=%s is_trading_day=%s "
            "opnd_yn=%s bzdy_yn=%s tr_day_yn=%s source=%s",
            target_date.isoformat(),
            info.is_trading_day,
            info.opnd_yn,
            info.bzdy_yn,
            info.tr_day_yn,
            info.source,
        )
        return info


# ---------------------------------------------------------------------------
# FallbackSessionProvider — 주말 heuristic + 시간표 기반
# ---------------------------------------------------------------------------


class FallbackSessionProvider(MarketSessionProvider):
    """Weekday heuristic 기반 fallback 거래일 제공자.

    KIS API를 사용할 수 없을 때(``KIS_LIVE_INFO_ENABLED=false`` 또는
    credential 미설정 또는 API 호출 실패) 사용됩니다.

    Heuristic:
    - 월~금(weekday 0-4): 거래일로 간주
    - 토~일(weekday 5-6): 비거래일로 간주
    - 한국 공휴일(대체공휴일 포함)은 감지하지 못함 → P2 과제
    """

    async def is_trading_day(self, target_date: date) -> bool:
        info = await self.get_session_info(target_date)
        return info.is_trading_day

    async def get_session_info(self, target_date: date) -> SessionInfo:
        weekday = target_date.weekday()  # 0=Mon, 6=Sun
        is_weekend = weekday >= 5  # Sat(5), Sun(6)

        if is_weekend:
            wday_names = ["월", "화", "수", "목", "금", "토", "일"]
            return SessionInfo(
                is_trading_day=False,
                opnd_yn="N",
                bzdy_yn="N",
                tr_day_yn="N",
                source="fallback",
                reason_code="FALLBACK_WEEKEND",
                reason=f"주말 감지: weekday={weekday} ({wday_names[weekday]}요일)",
            )

        return SessionInfo(
            is_trading_day=True,
            opnd_yn="Y",
            bzdy_yn="Y",
            tr_day_yn="Y",
            source="fallback",
            reason_code="FALLBACK_WEEKDAY",
            reason=f"평일 감지: weekday={weekday}",
        )


# ---------------------------------------------------------------------------
# CombinedSessionProvider — 076 + 163 통합 제공자
# ---------------------------------------------------------------------------


class CombinedSessionProvider(MarketSessionProvider):
    """076 (국내휴장일조회) + 163 (WebSocket 실시간 장운영) 통합 제공자.

    076 API로 거래일 여부를 확인하고, 163 WebSocket으로 실시간 장운영
    phase를 결합하여 최종 ``SessionInfo``를 생성한다.

    Phase 결정 로직
    ===============
    1. 076 ``opnd_yn != 'Y'`` → ``is_trading_day=False`` (163 무시)
    2. 163 WebSocket 미연결 → 076만 사용 (``market_phase=None``)
    3. 163 phase == ``HALT`` or ``UNKNOWN`` → safe mode (``is_trading_day=False``)
    4. 163 phase == ``AFTER_HOURS`` → ``is_trading_day=True`` (after-hours 허용)
    5. 그 외 (``OPEN``, ``CLOSING``, ``PRE_MARKET``) → ``is_trading_day=True``
    """

    def __init__(
        self,
        holiday_provider: KisHolidayProvider | MarketSessionProvider,
        market_state_provider: MarketStateProvider,
    ) -> None:
        """Initialize combined provider.

        Args:
            holiday_provider: 076 기반 ``MarketSessionProvider`` (e.g. ``KisHolidayProvider``).
            market_state_provider: 163 WebSocket ``MarketStateProvider``.
        """
        self._holiday_provider = holiday_provider
        self._market_state_provider = market_state_provider

    async def is_trading_day(self, target_date: date) -> bool:
        info = await self.get_session_info(target_date)
        return info.is_trading_day

    async def get_session_info(self, target_date: date) -> SessionInfo:
        """076 + 163 결합 → ``SessionInfo`` 반환.

        Steps:
        1. 076으로 기초 거래일 정보 획득
        2. 163 WebSocket에서 현재 장상태 조회
        3. Phase 결정 로직 적용
        """
        # Step 1: 076 (holiday info)
        try:
            holiday_info = await self._holiday_provider.get_session_info(target_date)
        except Exception as exc:
            logger.error(
                "CombinedSessionProvider: 076 provider failed for %s — %s",
                target_date.isoformat(),
                exc,
            )
            # Fall back to a basic non-trading-day state
            holiday_info = SessionInfo(
                is_trading_day=False,
                source="combined_error",
                reason_code="COMBINED_076_ERROR",
                reason=f"076 provider error: {exc}",
            )

        # Step 2: 163 (real-time market state)
        market_state = None
        is_ws_connected = False
        try:
            is_ws_connected = self._market_state_provider.is_connected
            if is_ws_connected:
                market_state = await self._market_state_provider.get_current_state()
        except Exception as exc:
            logger.warning(
                "CombinedSessionProvider: 163 provider error — %s", exc
            )

        # Step 3: Phase decision logic
        now = datetime.now()
        raw_mkop = ""
        raw_antc = ""
        market_phase: str | None = None

        if market_state is not None and is_ws_connected:
            raw_mkop = market_state.mkop_cls_code
            raw_antc = (market_state.raw or {}).get("body", {}).get("antc_mkop_cls_code", "")
            market_phase = market_state.phase.value if market_state.phase else None

            # Phase decision
            if not holiday_info.is_trading_day:
                # 076 says not trading day — block regardless of 163
                result = SessionInfo(
                    is_trading_day=False,
                    opnd_yn=holiday_info.opnd_yn,
                    bzdy_yn=holiday_info.bzdy_yn,
                    tr_day_yn=holiday_info.tr_day_yn,
                    source="combined",
                    reason_code="COMBINED_076_NON_TRADING",
                    reason=(
                        f"076 not trading day; phase={market_phase} "
                        f"mkop={raw_mkop}"
                    ),
                    market_phase=market_phase,
                    raw_opnd_yn=holiday_info.opnd_yn,
                    raw_mkop_cls_code=raw_mkop,
                    raw_antc_mkop_cls_code=raw_antc,
                    checked_at=now,
                )
            elif market_state.phase in (MarketPhaseCode.HALT, MarketPhaseCode.UNKNOWN):
                # Safe mode
                result = SessionInfo(
                    is_trading_day=False,
                    opnd_yn=holiday_info.opnd_yn,
                    bzdy_yn=holiday_info.bzdy_yn,
                    tr_day_yn=holiday_info.tr_day_yn,
                    source="combined",
                    reason_code="COMBINED_163_SAFE_MODE",
                    reason=(
                        f"163 safe mode: phase={market_phase} "
                        f"mkop={raw_mkop}"
                    ),
                    market_phase=market_phase,
                    raw_opnd_yn=holiday_info.opnd_yn,
                    raw_mkop_cls_code=raw_mkop,
                    raw_antc_mkop_cls_code=raw_antc,
                    checked_at=now,
                )
            else:
                # Normal trading (OPEN, CLOSING, PRE_MARKET, AFTER_HOURS)
                result = SessionInfo(
                    is_trading_day=True,
                    opnd_yn=holiday_info.opnd_yn,
                    bzdy_yn=holiday_info.bzdy_yn,
                    tr_day_yn=holiday_info.tr_day_yn,
                    source="combined",
                    reason_code="COMBINED_TRADING",
                    reason=(
                        f"076 trading_day + 163 phase={market_phase} "
                        f"mkop={raw_mkop}"
                    ),
                    market_phase=market_phase,
                    raw_opnd_yn=holiday_info.opnd_yn,
                    raw_mkop_cls_code=raw_mkop,
                    raw_antc_mkop_cls_code=raw_antc,
                    checked_at=now,
                )
        else:
            # 163 not available — use 076 only
            result = SessionInfo(
                is_trading_day=holiday_info.is_trading_day,
                opnd_yn=holiday_info.opnd_yn,
                bzdy_yn=holiday_info.bzdy_yn,
                tr_day_yn=holiday_info.tr_day_yn,
                source=holiday_info.source,
                reason_code="KIS_076_ONLY_TRADING_DAY" if holiday_info.is_trading_day else "KIS_076_ONLY_NON_TRADING",
                reason=(
                    f"{holiday_info.reason} "
                    f"(163 WS connected={is_ws_connected})"
                ),
                market_phase=None,
                raw_opnd_yn=holiday_info.opnd_yn,
                raw_mkop_cls_code=None,
                raw_antc_mkop_cls_code=None,
                checked_at=now,
            )

        return result


# ---------------------------------------------------------------------------
# Provider factory — 환경변수 기반 초기화
# ---------------------------------------------------------------------------


async def create_session_provider() -> MarketSessionProvider:
    """환경변수에 따라 적절한 ``MarketSessionProvider``를 생성.

    Resolution 순서:
    1. ``KIS_LIVE_INFO_ENABLED=true`` 이고 모든 credential 존재
       → ``KisHolidayProvider`` (076 API)
    2. 그 외 → ``FallbackSessionProvider``

    ``KISHolidayClient``의 file-based token cache는
    ``KIS_LIVE_TOKEN_CACHE_ENABLED``와 ``KIS_LIVE_TOKEN_CACHE_PATH``
    환경 변수를 통해 설정되며, market_state_client.py와 **별도 파일**
    (``kis_live_oauth_token.json``)을 사용합니다.

    Returns:
        ``MarketSessionProvider`` 인스턴스
    """
    import os

    enabled = os.getenv("KIS_LIVE_INFO_ENABLED", "false").strip().lower() == "true"
    app_key = os.getenv("KIS_LIVE_INFO_APP_KEY", "").strip()
    app_secret = os.getenv("KIS_LIVE_INFO_APP_SECRET", "").strip()
    base_url = os.getenv("KIS_LIVE_INFO_BASE_URL", "").strip()

    if enabled and app_key and app_secret:
        base = base_url or "https://openapi.koreainvestment.com:9443"

        # Live-info token cache 설정 (holiday OAuth 전용, market_state와 별도 파일)
        cache_enabled = (
            os.getenv("KIS_LIVE_TOKEN_CACHE_ENABLED", "false").strip().lower() == "true"
        )
        cache_base_path = os.getenv(
            "KIS_LIVE_TOKEN_CACHE_PATH",
            ".cache/kis_live_token.json",
        ).strip()
        # market_state_client.py와 충돌 방지를 위해 별도 파일 사용
        cache_parent = os.path.dirname(cache_base_path) or ".cache"
        oauth_cache_path = os.path.join(cache_parent, "kis_live_oauth_token.json")

        client = KISHolidayClient(
            app_key=app_key,
            app_secret=app_secret,
            base_url=base,
            enable_token_cache=cache_enabled,
            token_cache_path=oauth_cache_path,
        )
        logger.info(
            "SessionProvider: KisHolidayProvider (076 API) base_url=%s "
            "token_cache=%s enabled=%s",
            base,
            oauth_cache_path,
            cache_enabled,
        )
        return KisHolidayProvider(holiday_client=client)
    else:
        logger.info(
            "SessionProvider: FallbackSessionProvider (weekday heuristic) "
            "enabled=%s app_key_set=%s app_secret_set=%s",
            enabled,
            bool(app_key),
            bool(app_secret),
        )
        return FallbackSessionProvider()
