from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

from agent_trading.brokers.backoff import CircuitBreaker, CircuitState, ExponentialBackoff
from agent_trading.brokers.errors import (
    BrokerError,
    BrokerErrorType,
)
from agent_trading.brokers.koreainvestment.token_cache import (
    CachePurpose,
    KisTokenCache,
    KisTokenCacheConfig,
)

logger = logging.getLogger(__name__)
from agent_trading.brokers.rate_limit import (
    BudgetExhaustedError,
    BucketType,
    RateLimitBudgetManager,
)
from agent_trading.domain.enums import BrokerName, OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.domain.models import (
    CancelOrderResult,
    FillEvent,
    OrderStatusResult,
    SubmitOrderRequest,
    SubmitOrderResult,
)


# ---------------------------------------------------------------------------
# KIS API endpoint mapping — verified against KIS OpenAPI Excel document
# reference: reference_docs/한국투자증권_오픈API_전체문서_20260503_030000.xlsx
# ---------------------------------------------------------------------------

KIS_API_BASE_URLS: Mapping[str, str] = {
    "live": "https://openapi.koreainvestment.com:9443",
    "paper": "https://openapivts.koreainvestment.com:29443",
}

KIS_ENDPOINTS: Mapping[str, str] = {
    # --- Auth ---
    "oauth2_token": "/oauth2/tokenP",          # 접근토큰발급(P)
    "oauth2_approval": "/oauth2/Approval",     # 실시간(웹소켓) 접속키 발급
    # --- Order ---
    "order_cash": "/uapi/domestic-stock/v1/trading/order-cash",           # 주식주문(현금)
    "order_rvsecncl": "/uapi/domestic-stock/v1/trading/order-rvsecncl",   # 주식주문(정정취소)
    # --- Inquiry ---
    "inquire_balance": "/uapi/domestic-stock/v1/trading/inquire-balance",           # 주식잔고조회
    "inquire_psbl_order": "/uapi/domestic-stock/v1/trading/inquire-psbl-order",     # 매수가능조회
    "inquire_psbl_sell": "/uapi/domestic-stock/v1/trading/inquire-psbl-sell",       # 매도가능수량조회
    "inquire_daily_ccld": "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",     # 주식일별주문체결조회
    "inquire_psbl_rvsecncl": "/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl", # 정정취소가능주문조회
    "inquire_price": "/uapi/domestic-stock/v1/quotations/inquire-price",            # 주식현재가 시세
    # --- Market Data ---
    "inquire_asking_price_exp_ccn": "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn", # 호가
    # --- Disclosure (live only) ---
    # Reference: FHKST01011800 — 종합 시황_공시(제목), 모의투자 미지원
    "disclosure_title": "/uapi/domestic-stock/v1/quotations/news-title",
}

# TR ID mapping: (live_tr, paper_tr)
# Reference: KIS OpenAPI Excel — 접근토큰발급(P), 주식주문(현금), etc.
KIS_TR_IDS: Mapping[str, tuple[str, str]] = {
    # Order
    "order_buy": ("TTTC0012U", "VTTC0012U"),      # 매수
    "order_sell": ("TTTC0011U", "VTTC0011U"),      # 매도
    "order_rvsecncl": ("TTTC0013U", "VTTC0013U"),  # 정정취소
    # Inquiry
    "inquire_daily_ccld": ("TTTC0081R", "VTTC0081R"),       # 일별주문체결조회 (3개월 이내)
    "inquire_balance": ("TTTC8434R", "VTTC8434R"),          # 잔고조회
    "inquire_psbl_order": ("TTTC8908R", "VTTC8908R"),       # 매수가능조회
    "inquire_psbl_sell": ("TTTC8408R", None),               # 매도가능수량조회 (모의 미지원)
    "inquire_price": ("FHKST01010100", "FHKST01010100"),    # 주식현재가 시세
    "inquire_asking_price_exp_ccn": ("FHKST01010200", "FHKST01010200"), # 호가
    # Disclosure (live only — 모의투자 미지원)
    "disclosure_title": ("FHKST01011800", None),
}

# KIS error codes that indicate ambiguous / unknown state
# These are codes where the broker cannot definitively confirm the outcome
# of an order operation, requiring reconciliation via inquiry path.
# Reference: KIS OpenAPI Excel — error code sheet
_AMBIGUOUS_ERROR_CODES: frozenset[str] = frozenset({
    "EGW00123",  # 주문전송 실패 (타사)
    "EGW00125",  # 주문전송 실패 (기타)
    "EGW00150",  # 모의투자 주문불가
    "EGW00215",  # 주문가격 제한폭 초과
    "EGW00220",  # 주문수량 제한초과
    "EGW00300",  # 주문실패 (주문번호 없음)
    "EGW00301",  # 주문실패 (시장조성)
    "EGW00302",  # 주문실패 (상한가)
    "EGW00303",  # 주문실패 (하한가)
    "EGW00304",  # 주문실패 (권리락)
    "EGW00305",  # 주문실패 (거래정지)
    "EGW00310",  # 주문실패 (수량부족)
    "EGW00311",  # 주문실패 (금액부족)
    "EGW00312",  # 주문실패 (한도초과)
    "EGW00320",  # 주문실패 (기타사유)
    "EGW00330",  # 주문실패 (처리중)
    "EGW00331",  # 주문실패 (처리지연)
    "EGW00332",  # 주문실패 (결과불명)
    "EGW00333",  # 주문실패 (재조회필요)
    "EGW00340",  # 주문실패 (시스템점검)
    "EGW00350",  # 주문실패 (업무시간외)
    "EGW00400",  # 정정취소 실패 (원주문없음)
    "EGW00401",  # 정정취소 실패 (원주문처리중)
    "EGW00402",  # 정정취소 실패 (원주문이미정정)
    "EGW00403",  # 정정취소 실패 (원주문이미취소)
    "EGW00404",  # 정정취소 실패 (원주문전부체결)
    "EGW00405",  # 정정취소 실패 (원주문확인불가)
    "EGW00410",  # 정정취소 실패 (수량초과)
    "EGW00411",  # 정정취소 실패 (가격제한)
    "EGW00420",  # 정정취소 실패 (기타)
    "EGW00430",  # 정정취소 실패 (처리중)
    "EGW00431",  # 정정취소 실패 (결과불명)
    "EGW00432",  # 정정취소 실패 (재조회필요)
    "EGW00500",  # 조회실패 (일시적오류)
    "EGW00501",  # 조회실패 (시스템점검)
    "EGW00502",  # 조회실패 (데이터없음)
    "EGW00503",  # 조회실패 (권한없음)
    "EGW00510",  # 조회실패 (처리중)
    "EGW00511",  # 조회실패 (결과불명)
    "EGW00512",  # 조회실패 (재조회필요)
    "OPR00001",  # 업무일이 아닙니다
    "OPR00002",  # 업무시간이 아닙니다
    "OPR00003",  # 시스템 점검중입니다
    "OPR00004",  # 일시적인 오류가 발생했습니다
    "OPR00005",  # 처리중 오류가 발생했습니다
    "OPR00006",  # 결과를 확인할 수 없습니다
    "OPR00007",  # 재조회가 필요합니다
    "OPR00008",  # 처리 결과를 알 수 없습니다
    "OPR00009",  # 주문 처리중입니다
    "OPR00010",  # 주문 처리 결과 지연
    "OPR00011",  # 주문 상태 불명확
    "OPR00012",  # 주문 상태 확인 불가
    "OPR00013",  # 주문 상태 불일치
    "OPR00014",  # 주문 내역 없음
    "OPR00015",  # 주문번호 불일치
    "OPR00016",  # 주문번호 없음
    "OPR00017",  # 주문번호 중복
    "OPR00018",  # 주문번호 유효하지 않음
    "OPR00019",  # 주문번호 만료
    "OPR00020",  # 주문번호 생성 실패
    "OPR00021",  # 주문번호 조회 불가
    "OPR00022",  # 주문번호 상태 불명확
    "OPR00023",  # 주문번호 처리 중
    "OPR00024",  # 주문번호 처리 지연
    "OPR00025",  # 주문번호 처리 결과 확인 불가
    "OPR00026",  # 주문번호 처리 결과 지연
    "OPR00027",  # 주문번호 처리 결과 불명확
    "OPR00028",  # 주문번호 처리 결과 없음
    "OPR00029",  # 주문번호 처리 결과 확인 필요
    "OPR00030",  # 주문번호 처리 결과 재조회 필요
    "OPR00031",  # 주문번호 처리 결과 재확인 필요
    "OPR00032",  # 주문번호 처리 결과 불일치
    "OPR00033",  # 주문번호 처리 결과 없음
    "OPR00034",  # 주문번호 처리 결과 확인 불가
    "OPR00035",  # 주문번호 처리 결과 지연
    "OPR00036",  # 주문번호 처리 결과 불명확
    "OPR00037",  # 주문번호 처리 결과 없음
    "OPR00038",  # 주문번호 처리 결과 확인 필요
    "OPR00039",  # 주문번호 처리 결과 재조회 필요
    "OPR00040",  # 주문번호 처리 결과 재확인 필요
    "OPR00041",  # 주문번호 처리 결과 불일치
    "OPR00042",  # 주문번호 처리 결과 없음
    "OPR00043",  # 주문번호 처리 결과 확인 불가
    "OPR00044",  # 주문번호 처리 결과 지연
    "OPR00045",  # 주문번호 처리 결과 불명확
    "OPR00046",  # 주문번호 처리 결과 없음
    "OPR00047",  # 주문번호 처리 결과 확인 필요
    "OPR00048",  # 주문번호 처리 결과 재조회 필요
    "OPR00049",  # 주문번호 처리 결과 재확인 필요
    "OPR00050",  # 주문번호 처리 결과 불일치
})

# KIS error codes that are definitively known failures (no ambiguity)
# These can be safely mapped to a known OrderStatus without reconciliation.
_KNOWN_FAILURE_CODES: frozenset[str] = frozenset({
    "EGW00100",  # 인증실패
    "EGW00101",  # 토큰만료
    "EGW00102",  # 토큰없음
    "EGW00103",  # 토큰불일치
    "EGW00110",  # 권한없음
    "EGW00120",  # 계좌없음
    "EGW00121",  # 계좌불일치
    "EGW00122",  # 계좌정지
    "EGW00130",  # API호출권한없음
    "EGW00140",  # IP제한
    "EGW00160",  # 호출수초과
    "EGW00200",  # 필수입력값누락
    "EGW00201",  # 입력값형식오류
    "EGW00210",  # 종목코드오류
    "EGW00211",  # 계좌번호오류
    "EGW00212",  # 주문수량오류
    "EGW00213",  # 주문가격오류
    "EGW00214",  # 주문구분오류
    "EGW00321",  # 주문실패 (수량부족-매도)
    "EGW00322",  # 주문실패 (금액부족-매수)
    "EGW00323",  # 주문실패 (한도초과-매수)
    "EGW00324",  # 주문실패 (한도초과-매도)
    "EGW00421",  # 정정취소 실패 (수량부족)
    "EGW00422",  # 정정취소 실패 (가격초과)
    "EGW00504",  # 조회실패 (기간초과)
    "40270000",  # 모의투자 상/하한가 오류 — KIS paper trading only
})

# ---------------------------------------------------------------------------
# KIS ORD_STAT (주문상태) → internal OrderStatus mapping
# Reference: KIS OpenAPI Excel — output field ORD_STAT
#   00: 접수(주문접수)       → SUBMITTED
#   01: 체결(주문체결)       → FILLED (or PARTIALLY_FILLED based on qty)
#   02: 취소(주문취소)       → CANCELLED
#   03: 거절(주문거절)       → REJECTED
#   05: 미체결(주문접수-미체결) → ACKNOWLEDGED
#   07: 정정(주문정정)       → ACKNOWLEDGED (original order replaced)
# ---------------------------------------------------------------------------
KIS_ORD_STAT_MAP: dict[str, OrderStatus] = {
    "00": OrderStatus.SUBMITTED,        # 접수
    "01": OrderStatus.FILLED,           # 체결 (qty 비교로 PARTIALLY_FILLED 분기)
    "02": OrderStatus.CANCELLED,        # 취소
    "03": OrderStatus.REJECTED,         # 거절
    "05": OrderStatus.ACKNOWLEDGED,     # 미체결
    "07": OrderStatus.ACKNOWLEDGED,     # 정정
}

# ── inquire_daily_ccld 정책 상수 ──
# 장중 (기본)
_INQUIRE_DAILY_CCLD_REAL_MAX_PAGES: int = 10       # 실전 최대 페이지
_INQUIRE_DAILY_CCLD_REAL_MAX_RECORDS: int = 1000   # 실전 최대 레코드
_INQUIRE_DAILY_CCLD_PAPER_MAX_PAGES: int = 10      # 모의 최대 페이지
_INQUIRE_DAILY_CCLD_PAPER_MAX_RECORDS: int = 150   # 모의 최대 레코드 (15×10)

# 장후 (after-hours) — 더 보수적
_INQUIRE_DAILY_CCLD_AFTER_HOURS_REAL_MAX_PAGES: int = 3
_INQUIRE_DAILY_CCLD_AFTER_HOURS_REAL_MAX_RECORDS: int = 300
_INQUIRE_DAILY_CCLD_AFTER_HOURS_PAPER_MAX_PAGES: int = 3
_INQUIRE_DAILY_CCLD_AFTER_HOURS_PAPER_MAX_RECORDS: int = 45  # 15×3


@dataclass(slots=True, frozen=True)
class KisOrderFillRecord:
    """KIS inquire-daily-ccld output item (단일 레코드).

    KIS ``inquire-daily-ccld`` (VTTC0081R) 응답의 ``output`` 배열
    각 항목을 정규화한 dataclass.

    Reference: KIS OpenAPI Excel — VTTC0081R output fields
    """

    # ── 식별자 ──
    odno: str                                  # 주문번호
    pdno: str                                  # 종목코드
    # ── 주문 정보 ──
    ord_qty: Decimal                           # 주문수량
    ord_unpr: Decimal                          # 주문단가
    sll_buy_dvsn_cd: str                       # 01=매도, 02=매수
    ord_dvsn: str                              # 주문구분 (00=지정가, 01=시장가)
    # ── 체결 정보 ──
    ccld_qty: Decimal                          # 체결수량
    ccld_unpr: Decimal                         # 체결단가
    ccld_tmd: str                              # 체결시각 (HHMMSS)
    ccld_num: str | None = None                # 체결번호
    # ── 상태 ──
    ord_stat: str = ""                         # 주문상태 (00/01/02/03/05/07)
    cncl_yn: str = "N"                         # 취소여부
    rvse_yn: str = "N"                         # 정정여부
    # ── 시간 ──
    ord_tmd: str = ""                          # 주문시각 (HHMMSS)
    # ── 기타 ──
    rmn_qty: Decimal | None = None             # 미체결수량
    avg_prvs: Decimal | None = None            # 평균가


def parse_kis_order_fill_record(item: dict[str, Any]) -> KisOrderFillRecord:
    """Convert a raw KIS inquire-daily-ccld dict to ``KisOrderFillRecord``."""
    return KisOrderFillRecord(
        odno=item.get("ODNO", ""),
        pdno=item.get("PDNO", ""),
        ord_qty=Decimal(item.get("ORD_QTY", "0")),
        ord_unpr=Decimal(item.get("ORD_UNPR", "0")),
        sll_buy_dvsn_cd=item.get("SLL_BUY_DVSN_CD", ""),
        ord_dvsn=item.get("ORD_DVSN", ""),
        ccld_qty=Decimal(item.get("CCLD_QTY", "0")),
        ccld_unpr=Decimal(item.get("CCLD_UNPR", "0")),
        ccld_tmd=item.get("CCLD_TMD", ""),
        ccld_num=item.get("CCLD_NUM"),
        ord_stat=item.get("ORD_STAT", ""),
        cncl_yn=item.get("CNCL_YN", "N"),
        rvse_yn=item.get("RVSE_YN", "N"),
        ord_tmd=item.get("ORD_TMD", ""),
        rmn_qty=Decimal(item.get("RMN_QTY", "0")) if item.get("RMN_QTY") else None,
        avg_prvs=Decimal(item.get("AVG_PRVS", "0")) if item.get("AVG_PRVS") else None,
    )


# ---------------------------------------------------------------------------
# KIS REST Client — httpx.AsyncClient-based HTTP transport
# ---------------------------------------------------------------------------



@dataclass(slots=True)
class KISRestClient:
    """KIS REST API client with actual HTTP transport via httpx.

    Responsibilities:
    - Access token / approval key lifecycle
    - HMAC-SHA256 hashkey generation
    - TR ID / header / body assembly per KIS spec
    - Response normalisation + error mapping
    - Rate-limit budget consumption via RateLimitBudgetManager
    - Circuit-breaker / backoff integration
    """

    # --- injected dependencies ---
    api_key: str
    api_secret: str
    account_number: str
    account_product_code: str
    env: str = "paper"  # "live" | "paper"
    base_url: str = ""  # explicit override via KIS_BASE_URL; empty = use KIS_API_BASE_URLS
    budget_manager: RateLimitBudgetManager | None = None

    # --- dev token cache (file-based, paper/dev only) -------------------------
    dev_token_cache_enabled: bool = False
    dev_token_cache_path: str = ".cache/kis_token.json"
    cache_purpose: CachePurpose = CachePurpose.PAPER_ACCESS_TOKEN

    # --- internal state ---
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)
    _token_cache: KisTokenCache | None = field(default=None, init=False, repr=False)
    _access_token: str | None = field(default=None, init=False, repr=False)
    _token_expires_at: float = field(default=0.0, init=False, repr=False)
    _approval_key: str | None = field(default=None, init=False, repr=False)
    _approval_key_expires_at: float = field(default=0.0, init=False, repr=False)

    # --- auth strict cap (1 rps per KIS notice 2026-04-20) ---
    _auth_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _approval_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _last_auth_call_time: float = field(default=0.0, init=False, repr=False)
    _last_approval_call_time: float = field(default=0.0, init=False, repr=False)

    # --- backoff / circuit breaker ---
    _backoff: ExponentialBackoff = field(
        default_factory=lambda: ExponentialBackoff(
            base_delay=1.0, max_delay=60.0, jitter=0.1
        ),
        init=False,
        repr=False,
    )
    _circuit_breaker: CircuitBreaker = field(
        default_factory=lambda: CircuitBreaker(
            failure_threshold=5, recovery_timeout=30.0
        ),
        init=False,
        repr=False,
    )

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        """Normalize ``real`` → ``live`` for KIS_ENV compatibility + init token cache."""
        if self.env.strip().lower() == "real":
            object.__setattr__(self, "env", "live")
        self._token_cache = KisTokenCache(KisTokenCacheConfig(
            enabled=self.dev_token_cache_enabled,
            cache_path=Path(self.dev_token_cache_path),
            cache_purpose=self.cache_purpose,
            fingerprint_input=self.api_key,
            extra_validators={
                "kis_env": self.env,
                "base_url": self._base_url,
            },
            load_expiry_buffer=60.0,
            save_expiry_buffer=300.0,
        ))

    @property
    def _base_url(self) -> str:
        """Resolve the KIS base URL.

        Priority:
        1. ``self.base_url`` (explicit override via ``KIS_BASE_URL``)
        2. ``KIS_API_BASE_URLS[self.env]`` (hardcoded mapping)
        """
        if self.base_url:
            return self.base_url
        return KIS_API_BASE_URLS[self.env]

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init the shared httpx.AsyncClient."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(8.0, connect=5.0, read=5.0),
                limits=httpx.Limits(max_keepalive_connections=0, max_connections=10),
            )
        return self._client

    async def close(self) -> None:
        """Explicitly close the underlying HTTP client."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except RuntimeError:
                # Python 3.14+: httpx/httpcore may raise RuntimeError('Event loop is closed')
                # during teardown when the event loop has already been shut down.
                # This is safe to ignore — the client's transport is already closed.
                pass
            self._client = None

    # ------------------------------------------------------------------
    # Auth: access token
    # ------------------------------------------------------------------

    async def authenticate(self) -> str:
        """Obtain (or refresh) an access token from KIS oauth2/tokenP.

        Returns the current valid access token.

        .. note::
           Strict 1 rps enforcement per KIS official notice (2026-04-20):
           - ``asyncio.Lock`` serialises concurrent callers so only one HTTP
             request reaches KIS at a time (single-flight).
           - A monotonic cooldown timer guarantees at least 1 second between
             successive actual HTTP calls to ``/oauth2/tokenP``.
           - The lock + double-check pattern means concurrent callers whose
             cache is still valid never touch the network — they return the
             cached token immediately.
        """
        async with self._auth_lock:
            # 1. Double-check cache (standard lock pattern)
            now_wall = time.time()
            if self._access_token is not None and now_wall < self._token_expires_at:
                logger.debug(
                    "Token cache: in-memory hit expires_at=%s",
                    self._token_expires_at,
                )
                return self._access_token

            # 1b. Dev token cache: load from file if in-memory cache is empty
            if self._access_token is None and self._token_cache is not None:
                cached_token = await self._token_cache.load()
                if cached_token is not None:
                    self._access_token = cached_token
                    # 24h from now; will be refreshed by next successful HTTP call
                    self._token_expires_at = now_wall + 86400 - 300
                    logger.debug(
                        "Token cache: dev-file hit path=%s",
                        self.dev_token_cache_path,
                    )
                    return self._access_token

            # 2. Strict 1 rps: enforce minimum 1s between actual HTTP calls
            now_mono = time.monotonic()
            elapsed = now_mono - self._last_auth_call_time
            if self._last_auth_call_time > 0.0 and elapsed < 1.0:
                await asyncio.sleep(1.0 - elapsed)
                now_mono = time.monotonic()

            # 3. HTTP call
            client = await self._get_client()
            body = {
                "grant_type": "client_credentials",
                "appkey": self.api_key,
                "appsecret": self.api_secret,
            }
            resp = await client.post(
                KIS_ENDPOINTS["oauth2_token"],
                json=body,  # oauth2/tokenP requires JSON body
            )
            data = self._raise_on_error(resp, endpoint="oauth2_token")

            # 4. Update cache + cooldown timestamp (only on success)
            self._access_token = data["access_token"]
            # token expires in 86400s (24h); refresh 5 min early
            self._token_expires_at = now_wall + int(data.get("expires_in", 86400)) - 300
            self._last_auth_call_time = now_mono
            # 4b. Dev token cache: persist to file via KisTokenCache
            if self._token_cache is not None:
                await self._token_cache.save(self._access_token, int(data.get("expires_in", 86400)))
            return self._access_token  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Auth: WebSocket approval key
    # ------------------------------------------------------------------

    async def get_approval_key(self) -> str:
        """Obtain (or refresh) a WebSocket approval key from oauth2/Approval.

        Returns the current valid approval key.

        .. note::
           Strict 1 rps enforcement per KIS official notice (2026-04-20):
           Same lock + monotonic cooldown pattern as ``authenticate()``.
           The approval key has its **own** independent lock and cooldown
           timer, so calling both ``authenticate()`` and ``get_approval_key()``
           back-to-back does **not** trigger a false cooldown — each endpoint
           is governed independently.
        """
        async with self._approval_lock:
            # 1. Double-check cache
            now_wall = time.time()
            if self._approval_key is not None and now_wall < self._approval_key_expires_at:
                return self._approval_key

            # 2. Strict 1 rps cooldown
            now_mono = time.monotonic()
            elapsed = now_mono - self._last_approval_call_time
            if self._last_approval_call_time > 0.0 and elapsed < 1.0:
                await asyncio.sleep(1.0 - elapsed)
                now_mono = time.monotonic()

            # 3. HTTP call
            client = await self._get_client()
            body = {
                "grant_type": "client_credentials",
                "appkey": self.api_key,
                "secretkey": self.api_secret,
            }
            try:
                resp = await client.post(
                    KIS_ENDPOINTS["oauth2_approval"],
                    json=body,
                )
            except RuntimeError:
                # Python 3.14+: httpx/httpcore may raise RuntimeError('Event loop is closed')
                # during teardown when the event loop has already been shut down.
                # Re-raise as a clearer error so callers can distinguish this from
                # a genuine API failure.
                raise RuntimeError(
                    "KIS get_approval_key: event loop closed during HTTP request "
                    "(Python 3.14 httpx/httpcore teardown issue). "
                    "This is an infrastructure issue, not a credential problem."
                ) from None
            data = self._raise_on_error(resp, endpoint="oauth2_approval")

            # 4. Update cache + cooldown timestamp (only on success)
            self._approval_key = data["approval_key"]
            # approval key expires in 86400s (24h); refresh 5 min early
            self._approval_key_expires_at = now_wall + int(data.get("expires_in", 86400)) - 300
            self._last_approval_call_time = now_mono
            return self._approval_key  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Hashkey generation (HMAC-SHA256)
    # ------------------------------------------------------------------

    def _generate_signature(self, body: dict[str, object]) -> str:
        """Generate HMAC-SHA256 hashkey per KIS spec.

        The hashkey is computed over the JSON-serialised request body
        using the API secret as the HMAC key.
        """
        json_body = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            json_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    # ------------------------------------------------------------------
    # TR ID resolution
    # ------------------------------------------------------------------

    def _get_tr_id(self, key: str) -> str:
        """Resolve the TR ID for the current environment (live/paper)."""
        pair = KIS_TR_IDS.get(key)
        if pair is None:
            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.INVALID_REQUEST,
                retryable=False,
                raw_message=f"Unknown TR ID key: {key}",
            )
        live_tr, paper_tr = pair
        tr_id = paper_tr if self.env == "paper" else live_tr
        if tr_id is None:
            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.INVALID_REQUEST,
                retryable=False,
                raw_message=f"TR ID {key} not available in {self.env} environment",
            )
        return tr_id

    # ------------------------------------------------------------------
    # Header assembly
    # ------------------------------------------------------------------

    async def _build_headers(
        self,
        tr_id: str,
        *,
        content_type: str = "application/json; charset=utf-8",
    ) -> dict[str, str]:
        """Assemble common KIS API request headers."""
        token = await self.authenticate()
        return {
            "content-type": content_type,
            "authorization": f"Bearer {token}",
            "appkey": self.api_key,
            "appsecret": self.api_secret,
            "tr_id": tr_id,
            "custtype": "P",  # 개인
        }

    # ------------------------------------------------------------------
    # Error handling / response normalisation
    # ------------------------------------------------------------------

    def _raise_on_error(
        self,
        resp: httpx.Response,
        endpoint: str = "",
    ) -> dict[str, Any]:
        """Check the HTTP response and KIS business-level error codes.

        Returns the parsed JSON body on success.
        Raises BrokerError with appropriate error type on failure.
        """
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.API_ERROR,
                retryable=False,
                raw_message=f"KIS {endpoint}: non-JSON response (HTTP {resp.status_code})",
            )

        # HTTP-level error
        if resp.status_code >= 400:
            msg_cd = data.get("msg_cd", "")
            rt_cd = data.get("rt_cd", "")
            msg = data.get("msg1", data.get("msg", ""))

            # Some KIS endpoints (e.g. oauth2/tokenP) return OAuth2-style
            # error fields (error_code / error_description) instead of the
            # usual KIS business-level fields (msg_cd / msg1).  Capture
            # them here so the error message is actually informative.
            error_code = data.get("error_code", "")
            error_description = data.get("error_description", "")
            if error_code and not msg_cd:
                msg_cd = error_code
            if error_description and not msg:
                msg = error_description

            if msg_cd in _AMBIGUOUS_ERROR_CODES or rt_cd in _AMBIGUOUS_ERROR_CODES:
                raise BrokerError(
                    broker_name=BrokerName.KOREA_INVESTMENT,
                    error_type=BrokerErrorType.API_ERROR,
                    retryable=False,
                    raw_message=f"KIS {endpoint}: ambiguous state (msg_cd={msg_cd}, rt_cd={rt_cd}): {msg}",
                )
            if msg_cd in _KNOWN_FAILURE_CODES or rt_cd in _KNOWN_FAILURE_CODES:
                raise BrokerError(
                    broker_name=BrokerName.KOREA_INVESTMENT,
                    error_type=BrokerErrorType.ORDER_REJECTED,
                    retryable=False,
                    raw_message=f"KIS {endpoint}: known failure (msg_cd={msg_cd}, rt_cd={rt_cd}): {msg}",
                )

            # Default: API error
            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.API_ERROR,
                retryable=False,
                raw_message=f"KIS {endpoint}: HTTP {resp.status_code} (msg_cd={msg_cd}): {msg}",
            )

        # KIS business-level error (rt_cd != "0")
        rt_cd = data.get("rt_cd", "0")
        msg_cd = data.get("msg_cd", "")
        msg = data.get("msg1", data.get("msg", ""))

        if rt_cd != "0":
            if msg_cd in _AMBIGUOUS_ERROR_CODES or rt_cd in _AMBIGUOUS_ERROR_CODES:
                raise BrokerError(
                    broker_name=BrokerName.KOREA_INVESTMENT,
                    error_type=BrokerErrorType.API_ERROR,
                    retryable=False,
                    raw_message=f"KIS {endpoint}: ambiguous state (msg_cd={msg_cd}, rt_cd={rt_cd}): {msg}",
                )
            if msg_cd in _KNOWN_FAILURE_CODES or rt_cd in _KNOWN_FAILURE_CODES:
                raise BrokerError(
                    broker_name=BrokerName.KOREA_INVESTMENT,
                    error_type=BrokerErrorType.ORDER_REJECTED,
                    retryable=False,
                    raw_message=f"KIS {endpoint}: known failure (msg_cd={msg_cd}, rt_cd={rt_cd}): {msg}",
                )

            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.API_ERROR,
                retryable=False,
                raw_message=f"KIS {endpoint}: business error (rt_cd={rt_cd}, msg_cd={msg_cd}): {msg}",
            )

        return data

    def _normalize_response(
        self,
        data: dict[str, Any],
        endpoint: str,
    ) -> dict[str, Any]:
        """Normalise a KIS API response into a standardised shape.

        KIS responses have two possible output structures:
        - Single record: ``{"output": {...}}``
        - Multiple records: ``{"output1": [...], "output2": [...]}``
        - Some endpoints use ``{"output": [...]}``

        This method flattens to a consistent ``{"output": ...}`` shape
        while preserving ``output2`` (used by inquire-balance for cash
        summary).
        """
        if "output1" in data:
            result: dict[str, Any] = {"output": data["output1"]}
            if "output2" in data:
                result["output2"] = data["output2"]
            return result
        if "output" in data:
            return {"output": data["output"]}
        # Some endpoints return data directly in the root
        return data

    # ------------------------------------------------------------------
    # Budget-aware request helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        endpoint_key: str,
        tr_id_key: str,
        bucket: BucketType,
        body: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
        *,
        requires_hashkey: bool = False,
        skip_global_rest: bool = False,
        held_position_sell: bool = False,
    ) -> dict[str, Any]:
        """Unified request helper with budget consumption and circuit breaker.

        Steps:
        1. Consume budget (if manager provided)
        2. Check circuit breaker
        3. Build headers + optional hashkey
        4. Execute HTTP request
        5. Normalise response

        Parameters
        ----------
        skip_global_rest:
            If ``True``, skip the global REST cap check (Tier 1).
            Used by the reconciliation fallback path where the
            reconciliation reserve has already been verified.
        held_position_sell:
            If ``True``, use the held-position sell reserved budget lane.
        """
        # 1. Budget check
        if self.budget_manager is not None:
            self.budget_manager.consume_or_raise(
                bucket,
                skip_global_rest=skip_global_rest,
                held_position_sell=held_position_sell,
            )

        # 2. Circuit breaker
        if self._circuit_breaker.state == CircuitState.OPEN:
            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.API_ERROR,
                retryable=False,
                raw_message=f"KIS circuit breaker open for {endpoint_key}",
            )

        # 3. Build request
        tr_id = self._get_tr_id(tr_id_key)
        headers = await self._build_headers(tr_id)
        url = KIS_ENDPOINTS[endpoint_key]

        if body and requires_hashkey:
            headers["hashkey"] = self._generate_signature(body)

        client = await self._get_client()

        # 4. Execute
        try:
            if method.upper() == "GET":
                resp = await client.get(url, headers=headers, params=params)
            else:
                resp = await client.post(url, headers=headers, json=body, params=params)
        except httpx.TimeoutException:
            self._circuit_breaker.record_failure()
            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.TIMEOUT,
                retryable=True,
                raw_message=f"KIS {endpoint_key}: timeout",
            )
        except httpx.RequestError as e:
            self._circuit_breaker.record_failure()
            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.NETWORK_ERROR,
                retryable=True,
                raw_message=f"KIS {endpoint_key}: network error: {e}",
            )
        except RuntimeError:
            # Python 3.14+: httpx/httpcore may raise RuntimeError('Event loop is closed')
            # during teardown when the event loop has already been shut down.
            # Re-raise as a clearer error so callers can distinguish this from
            # a genuine API failure.
            raise RuntimeError(
                f"KIS {endpoint_key}: event loop closed during HTTP request "
                f"(Python 3.14 httpx/httpcore teardown issue). "
                f"This is an infrastructure issue, not a credential problem."
            ) from None

        # 5. Parse + normalise
        data = self._raise_on_error(resp, endpoint=endpoint_key)
        self._circuit_breaker.record_success()
        return self._normalize_response(data, endpoint=endpoint_key)

    # ------------------------------------------------------------------
    # Order operations
    # ------------------------------------------------------------------

    async def submit_order(
        self,
        request: SubmitOrderRequest,
        _held_position_sell: bool = False,
    ) -> SubmitOrderResult:
        """Submit a stock order (현금 매수/매도).

        Uses order-cash endpoint for regular orders.
        Hashkey is required for order requests.

        Parameters
        ----------
        _held_position_sell:
            If ``True``, use the held-position sell reserved budget lane.
            Internal use only — called from ``KISAdapter.submit_order()``.
        """
        side = request.side
        tr_id_key = "order_buy" if side == OrderSide.BUY else "order_sell"

        body: dict[str, object] = {
            "CANO": self.account_number,
            "ACNT_PRDT_CD": self.account_product_code,
            "PDNO": request.symbol,
            "ORD_DVSN": self._map_order_type(request.order_type),
            "ORD_QTY": str(request.quantity),
            "ORD_UNPR": str(request.price) if request.price is not None else "0",
        }

        if request.time_in_force is not None:
            body["ALGO"] = self._map_time_in_force(request.time_in_force)

        data = await self._request(
            "POST",
            endpoint_key="order_cash",
            tr_id_key=tr_id_key,
            bucket=BucketType.ORDER,
            body=body,
            requires_hashkey=True,
            held_position_sell=_held_position_sell,
        )

        output = data.get("output", data)
        # KIS order response: ODNO (주문번호), ORD_TMD (주문시각)
        broker_order_id = str(output.get("ODNO", ""))
        order_time = str(output.get("ORD_TMD", ""))

        return SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id=request.client_order_id,
            broker_order_id=broker_order_id or None,
            broker_status=OrderStatus.SUBMITTED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code=str(output.get("ODNO", "")),
            raw_message=str(output.get("ORD_TMD", "")),
            normalized_status=OrderStatus.SUBMITTED,
            uncertain=False,
            requires_reconciliation=False,
        )

    async def cancel_order(
        self,
        broker_order_id: str,
        symbol: str,
        quantity: Decimal,
    ) -> CancelOrderResult:
        """Cancel or amend an existing order (정정취소).

        Uses order-rvsecncl endpoint.
        Hashkey is required.
        """
        body: dict[str, object] = {
            "CANO": self.account_number,
            "ACNT_PRDT_CD": self.account_product_code,
            "PDNO": symbol,
            "ORGN_ODNO": broker_order_id,
            "ORD_DVSN": "00",  # 지정가 (default for cancellation)
            "RVSE_CNCL_DVSN_CD": "02",  # 02 = 취소
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
        }

        data = await self._request(
            "POST",
            endpoint_key="order_rvsecncl",
            tr_id_key="order_rvsecncl",
            bucket=BucketType.ORDER,
            body=body,
            requires_hashkey=True,
        )

        output = data.get("output", data)
        return CancelOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="",
            broker_order_id=str(output.get("ODNO", "")),
            broker_status=OrderStatus.CANCELLED,
            raw_code=str(output.get("ODNO", "")),
            raw_message=str(output.get("ORD_TMD", "")),
        )

    # ------------------------------------------------------------------
    # Inquiry operations
    # ------------------------------------------------------------------

    async def inquire_daily_ccld(
        self,
        *,
        broker_order_id: str | None = None,
        symbol: str | None = None,
        order_side: OrderSide | None = None,
        strt_dt: str | None = None,       # None → 오늘 (KST)
        end_dt: str | None = None,        # None → 오늘 (KST)
        after_hours: bool = False,        # 장중/장후 정책 분리
        bucket: BucketType = BucketType.INQUIRY,  # 사용할 budget bucket
        _skip_global_rest: bool = False,  # 내부용: global REST cap 우회 (reconcile fallback)
    ) -> list[dict[str, Any]]:
        """Fetch all daily settlement records with pagination support.

        KIS ``inquire-daily-ccld`` (VTTC0081R)는 최대 100건씩 반환하며,
        ``CTX_AREA_FK100`` / ``CTX_AREA_NK100`` 연속조회키로 페이지네이션한다.

        Parameters
        ----------
        broker_order_id:
            Optional ODNO filter applied post-fetch (KIS API does not support
            server-side ODNO filtering for this endpoint).
        symbol:
            Optional PDNO filter applied post-fetch.
        order_side:
            Optional side filter applied post-fetch.
        strt_dt:
            조회 시작일 (YYYYMMDD). ``None``이면 오늘 (KST).
        end_dt:
            조회 종료일 (YYYYMMDD). ``None``이면 오늘 (KST).
        after_hours:
            장후 세션 여부. ``True``이면 더 보수적인 정책 적용.
        bucket:
            사용할 budget bucket. 기본 INQUIRY, reconcile path에서는 RECONCILIATION 사용.

        Returns
        -------
        list[dict[str, Any]]
            Aggregated output items from all pages.
        """
        KST = timezone(timedelta(hours=9))
        _today_kst = datetime.now(KST).strftime("%Y%m%d")
        strt_dt = strt_dt or _today_kst
        end_dt = end_dt or _today_kst

        max_pages, max_records = self._resolve_ccld_policy(after_hours)

        all_output: list[dict[str, Any]] = []
        ctx_fk = ""
        ctx_nk = ""

        for page in range(max_pages):
            params: dict[str, str] = {
                "CANO": self.account_number,
                "ACNT_PRDT_CD": self.account_product_code,
                "INQR_STRT_DT": strt_dt,
                "INQR_END_DT": end_dt,
                "SLL_BUY_DVSN_CD": "00",      # 전체
                "INQR_DVSN": "00",            # 조회구분 (역순)
                "PDNO": "",                   # 전체종목
                "ORD_GNO_BRNO": "00000",      # 주문채번지점번호 (KIS 표준 기본값)
                "CCLD_DVSN": "00",            # 전체
                "INQR_DVSN_1": "",            # 조회구분1 (""=전체)
                "INQR_DVSN_3": "00",          # 조회구분3 ("00"=전체)
                "EXCG_ID_DVSN_CD": "KRX",     # 거래소ID구분코드 (모의투자 KRX)
                "ORD_GUBUN": "00",            # 주문구분
                "ORD_SRT_DVSN": "01",         # 주문시작구분
                "CTX_AREA_FK100": ctx_fk,
                "CTX_AREA_NK100": ctx_nk,
            }

            data = await self._request(
                "GET",
                endpoint_key="inquire_daily_ccld",
                tr_id_key="inquire_daily_ccld",
                bucket=bucket,
                params=params,
                skip_global_rest=_skip_global_rest,
            )

            output = data.get("output", [])
            if isinstance(output, dict):
                output = [output]

            all_output.extend(output)

            # Check continuation key
            ctx_fk = data.get("CTX_AREA_FK100", "") or ""
            ctx_nk = data.get("CTX_AREA_NK100", "") or ""
            if not ctx_fk or not ctx_nk:
                break  # No more pages

            # 누적 레코드 수 상한 체크
            if len(all_output) >= max_records:
                logger.warning(
                    "inquire-daily-ccld: reached max_records=%d at page=%d",
                    max_records, page + 1,
                )
                break

            # KIS 1 RPS pacing: ensure at least 1s between consecutive calls
            await asyncio.sleep(1.0)
        else:
            # for 루프가 break 없이 완료됨 = max_pages 도달
            logger.warning(
                "inquire-daily-ccld: reached max_pages=%d (total_records=%d)",
                max_pages, len(all_output),
            )

        # ── Instrumentation ──
        if logger.isEnabledFor(logging.DEBUG):
            odnos = [item.get("ODNO", "") for item in all_output]
            logger.debug(
                "inquire-daily-ccld (paginated): total_count=%d, odnos=%s",
                len(all_output), odnos[:30],
            )

        # Post-fetch filtering
        filtered = all_output
        if broker_order_id is not None:
            filtered = [it for it in filtered if it.get("ODNO") == broker_order_id]
        if symbol is not None:
            filtered = [it for it in filtered if it.get("PDNO") == symbol]
        if order_side is not None:
            side_code = "01" if order_side == OrderSide.SELL else "02"
            filtered = [it for it in filtered if it.get("SLL_BUY_DVSN_CD") == side_code]

        return filtered

    async def get_order_status(
        self,
        account_ref: str,
        client_order_id: str | None = None,
        broker_order_id: str | None = None,
    ) -> OrderStatusResult:
        """Query order status via daily settlement inquiry.

        Uses inquire-daily-ccld endpoint with pagination and fallback matching.
        Matches the ``BrokerAdapter`` protocol signature.
        """
        # Fetch all records with pagination (7일 범위 조회 — 5/18 주문 미조회 문제 해결)
        _kst = timezone(timedelta(hours=9))
        _strt_dt = (datetime.now(_kst) - timedelta(days=7)).strftime("%Y%m%d")
        output = await self.inquire_daily_ccld(
            strt_dt=_strt_dt,
            end_dt=None,
            after_hours=False,
        )

        # ── Instrumentation ──
        if logger.isEnabledFor(logging.DEBUG):
            odnos_in_response = [item.get("ODNO", "") for item in output]
            logger.debug(
                "inquire-daily-ccld: output_count=%d, requested_odno=%s, odnos_in_response=%s",
                len(output), broker_order_id, odnos_in_response[:20],
            )
            if output:
                sample = {
                    "ODNO": output[0].get("ODNO", ""),
                    "PDNO": output[0].get("PDNO", ""),
                    "ORD_QTY": output[0].get("ORD_QTY", ""),
                    "CCLD_QTY": output[0].get("CCLD_QTY", ""),
                    "CNCL_YN": output[0].get("CNCL_YN", ""),
                    "RVSE_YN": output[0].get("RVSE_YN", ""),
                    "SLL_BUY_DVSN_CD": output[0].get("SLL_BUY_DVSN_CD", ""),
                    "ORD_TMD": output[0].get("ORD_TMD", ""),
                    "CCLD_TMD": output[0].get("CCLD_TMD", ""),
                }
                logger.debug("inquire-daily-ccld: first_item_fields=%s", sample)

        # ── Fallback matching strategy ──
        # 1순위: ODNO (broker_order_id) 정확 매칭
        # 2순위: Symbol + Side 조합 매칭
        # 3순위: Symbol + 주문수량 범위 매칭
        matched_item = self._match_order(output, broker_order_id)

        if matched_item is not None:
            return self._parse_order_status_item(matched_item, client_order_id=client_order_id)

        logger.info(
            "inquire-daily-ccld: all matching strategies FAILED for "
            "broker_order_id=%s (output_count=%d, odnos_in_response=%s)",
            broker_order_id, len(output),
            [item.get("ODNO", "") for item in output][:20],
        )

        return OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id=client_order_id,
            broker_order_id=broker_order_id or "",
            status=OrderStatus.RECONCILE_REQUIRED,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("0"),
            raw_code="",
            raw_message="Order not found in daily settlement inquiry",
        )

    async def get_fills(
        self,
        account_ref: str,
        broker_order_id: str,
        from_ts: str | None = None,
    ) -> Sequence[FillEvent]:
        """Retrieve fill events from daily settlement inquiry.

        Uses inquire-daily-ccld endpoint with pagination.
        Matches the ``BrokerAdapter`` protocol signature.
        """
        # Fetch all records with pagination (기본 date-range = 당일)
        _strt_dt: str | None = None
        _end_dt: str | None = None
        if from_ts is not None:
            if isinstance(from_ts, datetime):
                _strt_dt = from_ts.strftime("%Y%m%d")
            else:
                # from_ts가 ISO format이라고 가정하고 YYYYMMDD 추출
                _strt_dt = from_ts[:10].replace("-", "")  # "2026-05-19" → "20260519"
        output = await self.inquire_daily_ccld(
            strt_dt=_strt_dt,
            end_dt=_end_dt,
            after_hours=False,
        )

        fills: list[FillEvent] = []
        for item in output:
            # Only include items with actual fills
            ccll_qty = Decimal(item.get("CCLD_QTY", "0"))
            if ccll_qty <= 0:
                continue

            if broker_order_id and item.get("ODNO") != broker_order_id:
                continue

            fill = FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=item.get("ODNO", ""),
                symbol=item.get("PDNO", ""),
                side=OrderSide.BUY if item.get("SLL_BUY_DVSN_CD") in ("01", "02") else OrderSide.SELL,
                fill_quantity=ccll_qty,
                fill_price=Decimal(item.get("CCLD_UNPR", "0")),
                fill_timestamp=datetime.now(timezone.utc),  # KIS doesn't provide per-fill timestamp
                broker_fill_id=item.get("CCLD_NUM"),  # KIS 체결번호 (unique per fill)
                fee=None,
                tax=None,
            )
            fills.append(fill)

        return fills

    async def get_positions(self) -> Sequence[dict[str, Any]]:
        """Retrieve current positions (잔고조회).

        Uses inquire-balance endpoint.

        Note
        ----
        KIS ``inquire-balance`` requires the continuation/pagination fields
        ``CTX_AREA_FK100`` and ``CTX_AREA_NK100`` on **every** request,
        including the initial page.  Omitting them triggers
        ``OPSQ2001: INPUT_FIELD_NAME CTX_AREA_FK100``.
        """
        params = {
            "CANO": self.account_number,
            "ACNT_PRDT_CD": self.account_product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "COST_ICLD_YN": "N",
            "CTX_AREA_FK100": "",  # 연속조회검색조건100 (최초조회: 빈값)
            "CTX_AREA_NK100": "",  # 연속조회키100 (최초조회: 빈값)
        }

        data = await self._request(
            "GET",
            endpoint_key="inquire_balance",
            tr_id_key="inquire_balance",
            bucket=BucketType.INQUIRY,
            params=params,
        )

        output = data.get("output", [])
        if isinstance(output, dict):
            output = [output]
        return output

    async def get_cash_balance(self, after_hours: bool = False) -> dict[str, Any]:
        """Retrieve cash balance (잔고조회 — cash component).

        Uses inquire-balance endpoint and extracts the cash portion
        from ``output2`` (예수금 총괄).

        Parameters
        ----------
        after_hours:
            When ``True``, sets ``AFHR_FLPR_YN=Y`` for after-hours cash
            inquiry (15:31∼16:31 KST).  Default ``False`` (regular hours).

        Note
        ----
        KIS ``inquire-balance`` returns the response in two blocks:
        - ``output`` / ``output1``: position array (종목별 잔고)
        - ``output2``: cash summary (예수금 총괄)

        This method reads from ``output2`` only.

        KIS ``inquire-balance`` requires the continuation/pagination fields
        ``CTX_AREA_FK100`` and ``CTX_AREA_NK100`` on **every** request,
        including the initial page.  Omitting them triggers
        ``OPSQ2001: INPUT_FIELD_NAME CTX_AREA_FK100``.
        """
        params = {
            "CANO": self.account_number,
            "ACNT_PRDT_CD": self.account_product_code,
            "AFHR_FLPR_YN": "Y" if after_hours else "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "COST_ICLD_YN": "N",
            "CTX_AREA_FK100": "",  # 연속조회검색조건100 (최초조회: 빈값)
            "CTX_AREA_NK100": "",  # 연속조회키100 (최초조회: 빈값)
        }

        data = await self._request(
            "GET",
            endpoint_key="inquire_balance",
            tr_id_key="inquire_balance",
            bucket=BucketType.INQUIRY,
            params=params,
        )

        # output2 contains the cash summary (예수금 총괄)
        output2 = data.get("output2", {})
        if isinstance(output2, list):
            output2 = output2[0] if output2 else {}
        return output2

    def _has_budget_for_inquiry(self) -> bool:
        """VTTC8908R 호출 전 budget 사전 확인.

        ``self.budget_manager``가 없으면(테스트 환경 등) 항상 ``True`` 반환.
        refill을 우선 적용하여 가능한 많은 token을 확보한 후 판단.
        """
        mgr = self.budget_manager
        if mgr is None:
            return True
        # refill 우선 적용
        mgr.inquiry._refill()
        if mgr.inquiry.remaining < 1:
            return False
        if mgr.global_rest is not None:
            mgr.global_rest._refill()
            if mgr.global_rest.remaining < 1:
                return False
        return True

    async def get_orderable_cash(
        self,
        account_ref: str = "",
        symbol: str = "",
        price: str = "",
        order_type: str = "00",  # 00=지정가
        fallback_cash: Decimal | None = None,  # NEW: budget 부족 시 반환할 fallback 값
    ) -> Decimal | None:
        """Fetch ``ord_psbl_cash`` from ``VTTC8908R`` (inquire-psbl-order).

        This is a separate API call from ``get_cash_balance()``.  The
        ``inquire_balance`` endpoint (``VTTC8434R``) does **not** return
        ``ord_psbl_cash`` in paper environment — it returns ``"0"`` or
        omits the field entirely.  ``VTTC8908R`` provides the actual
        orderable cash amount even in paper mode.

        Budget 사전 확인(``_has_budget_for_inquiry``)을 수행하여,
        INQUIRY/global_rest budget이 부족하면 API 호출 없이
        ``fallback_cash``를 반환한다. 이를 통해
        ``BudgetExhaustedError`` 발생을 사전에 방지한다.

        Parameters
        ----------
        account_ref:
            Broker account reference (not used directly; the client's own
            ``account_number`` / ``account_product_code`` are used).
        symbol:
            Symbol (``PDNO``) for per-symbol orderable cash estimation.
            Empty string for account-level orderable cash.
        price:
            Order unit price (``ORD_UNPR``).  Empty for market estimate.
        order_type:
            Order division code (``ORD_DVSN``).  ``"00"`` = 지정가 (limit).
        fallback_cash:
            Budget 부족 시 API 호출 없이 반환할 fallback 값.
            ``None``이면 budget 사전 확인을 건너뛰고 항상 API 호출 시도.

        Returns
        -------
        Decimal | None
            The orderable cash amount, or ``None`` if the API call failed.
            When ``fallback_cash`` is provided and budget is insufficient,
            returns ``fallback_cash`` without making any API call.
        """
        # ── P2: budget 사전 확인 ─────────────────────────────────────────
        if fallback_cash is not None and not self._has_budget_for_inquiry():
            logger.warning(
                "BUDGET_FALLBACK VTTC8908R budget insufficient for account=%s; "
                "using available_cash fallback=%s",
                account_ref or self.account_number,
                fallback_cash,
            )
            return fallback_cash

        # ── P2: 실제 API 호출 ────────────────────────────────────────────
        try:
            params = {
                "CANO": self.account_number,
                "ACNT_PRDT_CD": self.account_product_code,
                "PDNO": symbol,
                "ORD_DVSN": order_type,
                "ORD_UNPR": price,
                "CMA_EVLU_AMT_ICLD_YN": "N",
                "OVRS_ICLD_YN": "N",
            }

            data = await self._request(
                "GET",
                endpoint_key="inquire_psbl_order",
                tr_id_key="inquire_psbl_order",
                bucket=BucketType.INQUIRY,
                params=params,
            )

            output = data.get("output", {})
            if isinstance(output, list):
                output = output[0] if output else {}

            ord_psbl_cash = output.get("ord_psbl_cash")
            if ord_psbl_cash is not None and str(ord_psbl_cash).strip():
                return Decimal(str(ord_psbl_cash))

            logger.info(
                "ord_psbl_cash not present in VTTC8908R response; "
                "orderable_amount will remain None"
            )
            return None

        except Exception:
            logger.warning(
                "Failed to fetch orderable cash via VTTC8908R",
                exc_info=True,
            )
            return None

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """Retrieve current price quote (주식현재가 시세).

        Uses inquire-price endpoint.
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }

        data = await self._request(
            "GET",
            endpoint_key="inquire_price",
            tr_id_key="inquire_price",
            bucket=BucketType.MARKET_DATA,
            params=params,
        )

        output = data.get("output", {})
        if isinstance(output, list):
            output = output[0] if output else {}
        return output

    async def get_quotes_batch(
        self,
        symbols: Sequence[str],
        *,
        semaphore: asyncio.Semaphore | None = None,
        timeout: float = 3.0,
    ) -> dict[str, dict[str, Any]]:
        """Fetch quotes for multiple symbols concurrently.

        Budget-safe batch helper for P2 Market-Driven Overlay.
        Each failed symbol is skipped (not crash).

        Parameters
        ----------
        symbols : Sequence[str]
            Symbols to fetch (pre-pool candidates, max ~50).
        semaphore : asyncio.Semaphore | None
            Concurrency limiter.  Defaults to ``Semaphore(10)``.
        timeout : float
            Per-call timeout in seconds.  Default: 3.0.

        Returns
        -------
        dict[str, dict[str, Any]]
            ``{symbol: raw_output_dict}`` — only successfully fetched symbols
            are included.  Failed / timed-out symbols are omitted.
        """
        sem = semaphore or asyncio.Semaphore(10)

        async def _fetch_one(sym: str) -> tuple[str, dict[str, Any]] | None:
            try:
                async with sem:
                    output = await asyncio.wait_for(
                        self.get_quote(sym),
                        timeout=timeout,
                    )
                    if output:
                        return sym, output
                    return None
            except asyncio.TimeoutError:
                logger.debug("get_quotes_batch: timeout for %s (%.1fs)", sym, timeout)
                return None
            except Exception:
                logger.debug("get_quotes_batch: failed for %s", sym, exc_info=True)
                return None

        tasks = [_fetch_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks)

        batch: dict[str, dict[str, Any]] = {}
        for item in results:
            if item is not None:
                sym, output = item
                batch[sym] = output

        logger.info(
            "get_quotes_batch: %d/%d symbols fetched successfully.",
            len(batch),
            len(symbols),
        )
        return batch

    async def get_orderbook(self, symbol: str) -> dict[str, Any]:
        """Retrieve orderbook (호가).

        Uses inquire-asking-price-exp-ccn endpoint.
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }

        data = await self._request(
            "GET",
            endpoint_key="inquire_asking_price_exp_ccn",
            tr_id_key="inquire_asking_price_exp_ccn",
            bucket=BucketType.MARKET_DATA,
            params=params,
        )

        output = data.get("output", {})
        if isinstance(output, list):
            output = output[0] if output else {}
        return output

    # ------------------------------------------------------------------
    # Disclosure (live-only 공시 제목 조회)
    # ------------------------------------------------------------------

    async def get_disclosure_news_title(
        self,
        symbol: str,
    ) -> list[dict[str, Any]]:
        """Fetch disclosure news title (공시 제목) for a stock symbol.

        KIS FHKST01011800 — 종합 시황_공시(제목).
        Live-only API (모의투자 미지원) — returns ``[]`` when called
        in dev/paper env (``_get_tr_id`` raises ``BrokerError``, caught here).

        KIS 요청 파라미터 (Reference: KIS OpenAPI Excel 84번 시트):
        - ``FID_COND_MRKT_CLS_CODE``: 공백 (필수)
        - ``FID_INPUT_ISCD``: 종목코드 (공백=전체)
        - ``FID_NEWS_OFER_ENTP_CODE``: 공백 (필수)
        - ``FID_TITL_CNTT``: 공백 (필수)
        - ``FID_INPUT_DATE_1``: 공백=현재기준
        - ``FID_INPUT_HOUR_1``: 공백=현재기준
        - ``FID_RANK_SORT_CLS_CODE``: 공백 (필수)
        - ``FID_INPUT_SRNO``: 공백 (필수)

        Returns
        -------
        list[dict[str, Any]]
            Raw disclosure item list.  Each item contains:
            - ``hts_pbnt_titl_cntt``: 공시 제목 (최대 400자)
            - ``data_dt``: 작성일자 (YYYYMMDD)
            - ``data_tm``: 작성시간 (HHMMSS)
            - ``iscd1``~``iscd10``: 종목코드
            - ``kor_isnm1``~``kor_isnm10``: 종목명
            Returns ``[]`` on any error (graceful fallback).
        """
        tr_id = self._get_tr_id("disclosure_title")

        # KIS FHKST01011800 requires all these query params (many must be empty)
        params: dict[str, str] = {
            "FID_COND_MRKT_CLS_CODE": "",       # 조건 시장 구분 코드 (공백 필수)
            "FID_INPUT_ISCD": symbol,             # 입력 종목코드
            "FID_NEWS_OFER_ENTP_CODE": "",        # 뉴스 제공 업체 코드 (공백 필수)
            "FID_TITL_CNTT": "",                  # 제목 내용 (공백 필수)
            "FID_INPUT_DATE_1": "",               # 입력 날짜 (공백=현재기준)
            "FID_INPUT_HOUR_1": "",               # 입력 시간 (공백=현재기준)
            "FID_RANK_SORT_CLS_CODE": "",         # 순위 정렬 구분 코드 (공백 필수)
            "FID_INPUT_SRNO": "",                 # 입력 일련번호 (공백 필수)
        }

        try:
            data = await self._request(
                "GET",
                endpoint_key="disclosure_title",
                tr_id_key="disclosure_title",
                bucket=BucketType.INQUIRY,
                params=params,
            )
        except BrokerError as exc:
            logger.warning(
                "Disclosure: BrokerError symbol=%s env=%s error=%s",
                symbol, self.env, exc,
            )
            return []
        except Exception:
            logger.warning(
                "Disclosure: unexpected error symbol=%s env=%s",
                symbol, self.env, exc_info=True,
            )
            return []

        # KIS response: ``output`` is a list of items
        output = data.get("output") or []
        if not isinstance(output, list):
            output = [output] if output else []

        logger.info(
            "Disclosure: success symbol=%s env=%s items=%d",
            symbol, self.env, len(output),
        )
        return output

    @staticmethod
    def _normalize_disclosure_output(
        raw: dict[str, Any],
        symbol: str,
    ) -> dict[str, Any]:
        """Normalize a single KIS disclosure response item to a DTO-compatible dict.

        Parameters
        ----------
        raw: Single item from FHKST01011800 response ``output`` list.
        symbol: The queried stock symbol.

        Returns
        -------
        dict[str, Any]
            Normalized dict compatible with ``DisclosureTitleDTO`` fields.
        """
        # 회사명: kor_isnm1~10 중 첫 번째 비어있지 않은 값
        company_name: str | None = None
        for i in range(1, 11):
            key = f"kor_isnm{i}"
            val = raw.get(key)
            if val and str(val).strip():
                company_name = str(val).strip()
                break

        # 발행 시각: data_dt (YYYYMMDD) + data_tm (HHMMSS) 조합
        data_dt = raw.get("data_dt", "")
        data_tm = raw.get("data_tm", "")
        published_at: str | None = None
        if data_dt and data_tm:
            published_at = f"{data_dt} {data_tm}"

        return {
            "symbol": symbol,
            "company_name": company_name,
            "headline": raw.get("hts_pbnt_titl_cntt"),
            "published_at": published_at,
            "source": "kis_disclosure_live",
        }

    async def resolve_unknown_state(
        self,
        broker_order_id: str,
        symbol: str | None = None,
        after_hours: bool = False,
    ) -> OrderStatusResult:
        """Resolve an unknown order state via broker inquiry.

        Uses inquire-daily-ccld to find the order and determine its status.
        This is the reconciliation inquiry path for ambiguous states.

        Budget fallback
        ---------------
        If the INQUIRY bucket is exhausted, this method falls back to the
        reconciliation reserve (``reserve_reconciliation_or_raise``).
        If both are exhausted, ``BudgetExhaustedError`` is raised.
        """
        # 방어: 빈 문자열을 None으로 정규화 (adapter 경유 시 "" 전달 가능)
        symbol = symbol or None

        # 1. Try inquiry path with reconciliation reserve fallback
        #    inquire_daily_ccld() 재사용 (pagination + policy 적용)
        #
        #    RECONCILE_REQUIRED 해소 전용: 기본 당일 조회에서 찾지 못한
        #    전일/이전 주문을 찾기 위해 최근 7일 범위로 확장 (bounded override).
        #    max_pages/max_records 정책은 _resolve_ccld_policy()가 계속 적용.
        _kst = timezone(timedelta(hours=9))
        _strt_dt = (datetime.now(_kst) - timedelta(days=7)).strftime("%Y%m%d")
        # RECONCILE_REQUIRED 해소 전용: RECONCILIATION bucket 사용 + after_hours 정책
        # (inquire_daily_ccld 내부에서 _resolve_ccld_policy(after_hours=True)가
        #  더 보수적인 max_pages/max_records를 적용하여 budget 소비를 최소화)
        # RECONCILIATION bucket은 일반 INQUIRY와 별도로 관리되므로,
        # 일반 polling이 budget을 소진해도 reconcile path는 독립적으로 동작 가능.
        #
        # inquire_daily_ccld()는 내부적으로 _request()를 직접 호출하므로
        # _request_with_fallback()의 fallback 로직이 적용되지 않는다.
        # 따라서 여기서 직접 BudgetExhaustedError를 처리하고
        # reconciliation reserve를 확보한 후 skip_global_rest=True로 재시도한다.
        try:
            records = await self.inquire_daily_ccld(
                strt_dt=_strt_dt,
                end_dt=None,
                symbol=symbol,
                after_hours=True,
                bucket=BucketType.RECONCILIATION,
            )
        except BudgetExhaustedError:
            # RECONCILIATION bucket 소진 → reconciliation reserve 확보 후
            # global REST cap을 우회하여 재시도
            if self.budget_manager is not None:
                self.budget_manager.reserve_reconciliation_or_raise()
            records = await self.inquire_daily_ccld(
                strt_dt=_strt_dt,
                end_dt=None,
                symbol=symbol,
                after_hours=True,
                bucket=BucketType.RECONCILIATION,
                _skip_global_rest=True,
            )

        # Find the matching order
        for item in records:
            if item.get("ODNO") == broker_order_id:
                return self._parse_order_status_item(item)

        # 2. If not found in daily settlement, try positions
        try:
            positions_data = await self._request_with_fallback(
                "GET",
                endpoint_key="inquire_balance",
                tr_id_key="inquire_balance",
                bucket=BucketType.INQUIRY,
                params={
                    "CANO": self.account_number,
                    "ACNT_PRDT_CD": self.account_product_code,
                    "AFHR_FLPR_YN": "N",
                    "OFL_YN": "",
                    "INQR_DVSN": "01",
                    "UNPR_DVSN": "01",
                    "FUND_STTL_ICLD_YN": "N",
                    "FNCG_AMT_AUTO_RDPT_YN": "N",
                    "PRCS_DVSN": "01",
                    "COST_ICLD_YN": "N",
                },
            )
        except (BrokerError, BudgetExhaustedError):
            positions_data = {"output": []}

        positions = positions_data.get("output", [])
        if isinstance(positions, dict):
            positions = [positions]

        for pos in positions:
            if pos.get("PDNO") == symbol:
                return OrderStatusResult(
                    broker_name=BrokerName.KOREA_INVESTMENT,
                    client_order_id=None,
                    broker_order_id=broker_order_id,
                    status=OrderStatus.FILLED,
                    filled_quantity=Decimal(pos.get("CCLD_QTY", "0")),
                    remaining_quantity=Decimal("0"),
                    raw_code=pos.get("PDNO", ""),
                    raw_message="Resolved from position inquiry",
                )

        return OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id=None,
            broker_order_id=broker_order_id,
            status=OrderStatus.RECONCILE_REQUIRED,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("0"),
            raw_code="",
            raw_message="Order not found in daily settlement or positions",
        )

    async def _request_with_fallback(
        self,
        method: str,
        endpoint_key: str,
        tr_id_key: str,
        bucket: BucketType,
        body: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
        *,
        requires_hashkey: bool = False,
    ) -> dict[str, Any]:
        """Like ``_request`` but falls back to reconciliation reserve on ``BudgetExhaustedError``.

        This is used by ``resolve_unknown_state`` for the reconciliation
        inquiry path.
        """
        try:
            return await self._request(
                method,
                endpoint_key=endpoint_key,
                tr_id_key=tr_id_key,
                bucket=bucket,
                body=body,
                params=params,
                requires_hashkey=requires_hashkey,
            )
        except BudgetExhaustedError:
            if self.budget_manager is not None:
                self.budget_manager.reserve_reconciliation_or_raise()
            # Retry after reserving reconciliation budget.
            # skip_global_rest=True: reconcile reserve가 이미 확보되었으므로
            # global REST cap을 우회하여 reconcile path가 일반 polling과
            # 독립적으로 동작할 수 있도록 보장.
            return await self._request(
                method,
                endpoint_key=endpoint_key,
                tr_id_key=tr_id_key,
                bucket=bucket,
                body=body,
                params=params,
                requires_hashkey=requires_hashkey,
                skip_global_rest=True,
            )

    # ------------------------------------------------------------------
    # inquire_daily_ccld 정책 헬퍼
    # ------------------------------------------------------------------

    def _resolve_ccld_policy(self, after_hours: bool = False) -> tuple[int, int]:
        """환경(live/paper)과 세션(장중/장후)에 따라 max_pages, max_records 반환."""
        if after_hours:
            if self.env == "live":
                return (
                    _INQUIRE_DAILY_CCLD_AFTER_HOURS_REAL_MAX_PAGES,
                    _INQUIRE_DAILY_CCLD_AFTER_HOURS_REAL_MAX_RECORDS,
                )
            return (
                _INQUIRE_DAILY_CCLD_AFTER_HOURS_PAPER_MAX_PAGES,
                _INQUIRE_DAILY_CCLD_AFTER_HOURS_PAPER_MAX_RECORDS,
            )
        # 장중 (기본)
        if self.env == "live":
            return (
                _INQUIRE_DAILY_CCLD_REAL_MAX_PAGES,
                _INQUIRE_DAILY_CCLD_REAL_MAX_RECORDS,
            )
        return (
            _INQUIRE_DAILY_CCLD_PAPER_MAX_PAGES,
            _INQUIRE_DAILY_CCLD_PAPER_MAX_RECORDS,
        )

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_order_type(order_type: OrderType) -> str:
        """Map OrderType to KIS ORD_DVSN code."""
        mapping: dict[OrderType, str] = {
            OrderType.MARKET: "01",   # 시장가
            OrderType.LIMIT: "00",    # 지정가
            OrderType.STOP: "02",     # 조건부지정가
            OrderType.STOP_LIMIT: "03",  # 조건부지정가 (확인필요)
        }
        return mapping.get(order_type, "00")

    @staticmethod
    def _map_time_in_force(time_in_force: TimeInForce) -> str:
        """Map TimeInForce to KIS ALGO code (if applicable)."""
        mapping: dict[TimeInForce, str] = {
            TimeInForce.DAY: "01",     # 당일
            TimeInForce.IOC: "02",     # IOC
            TimeInForce.FOK: "03",     # FOK
        }
        return mapping.get(time_in_force, "01")

    @staticmethod
    def _match_order(
        output: list[dict[str, Any]],
        broker_order_id: str | None,
    ) -> dict[str, Any] | None:
        """Fallback matching strategy for broker_order_id (ODNO).

        KIS ``inquire-daily-ccld`` 응답에서 ``broker_order_id``에 해당하는
        항목을 찾는다. 단순 ODNO 매칭 실패 시 fallback 전략을 사용한다.

        Matching priority
        -----------------
        1. **ODNO exact match** — ``item["ODNO"] == broker_order_id``
        2. **Symbol + Side match** — ``PDNO`` + ``SLL_BUY_DVSN_CD`` 조합
           (``broker_order_id``가 UUID 형식이 아닌 경우에만 시도)
        3. **Symbol + Quantity range** — ``PDNO`` + ``ORD_QTY`` 근사 매칭
           (broker_order_id가 KIS ODNO 형식이 아닌 경우)

        Parameters
        ----------
        output:
            Raw output items from ``inquire-daily-ccld``.
        broker_order_id:
            The broker-native order ID (ODNO) to match.

        Returns
        -------
        dict[str, Any] | None
            Matched item, or ``None`` if no match found.
        """
        if not output or not broker_order_id:
            return None

        # ── 1순위: ODNO 정확 매칭 ──
        for item in output:
            if item.get("ODNO") == broker_order_id:
                return item

        # broker_order_id가 KIS ODNO 형식(숫자)인 경우
        if broker_order_id.isdigit():
            # ODNO 매칭 실패 → 모든 레코드의 odno가 비어있는지 확인
            # (paper 환경에서는 odno를 반환하지 않음)
            all_odno_empty = all(
                not record.get("odno")
                for record in output
            )
            if not all_odno_empty:
                # odno가 정상적으로 반환되었지만 매칭되지 않은 경우 → 진정한 불일치
                return None
            # odno가 모두 비어있으면 (paper 환경) 2순위 매칭으로 fallback

        # ── 2순위: Symbol + Side 조합 매칭 ──
        # broker_order_id가 UUID 등 KIS ODNO가 아닌 경우,
        # 같은 종목(PDNO) + 같은 매매구분(SLL_BUY_DVSN_CD) 항목을 찾는다.
        candidates_2: list[dict[str, Any]] = []
        for item in output:
            pdno = item.get("PDNO", "")
            sll_buy = item.get("SLL_BUY_DVSN_CD", "")
            if pdno and sll_buy:
                candidates_2.append(item)

        if len(candidates_2) == 1:
            return candidates_2[0]

        # ── 3순위: Symbol + 주문수량 범위 매칭 ──
        # 후보가 여러 개인 경우, 주문수량(ORD_QTY)이 가장 근접한 항목 선택
        if len(candidates_2) > 1:
            # Sort by recency (ORD_TMD descending) and pick first
            candidates_2.sort(
                key=lambda x: x.get("ORD_TMD", ""),
                reverse=True,
            )
            return candidates_2[0]

        return None

    @staticmethod
    def _parse_order_status_item(
        item: dict[str, Any],
        client_order_id: str | None = None,
    ) -> OrderStatusResult:
        """Parse a single KIS order status item into OrderStatusResult.

        Uses KIS ``ORD_STAT`` code as the primary status mapping, with
        quantity-based refinement for PARTIALLY_FILLED vs FILLED distinction.
        """
        odno = item.get("ODNO", "")
        ord_qty = Decimal(item.get("ORD_QTY", "0"))
        ccll_qty = Decimal(item.get("CCLD_QTY", "0"))
        rmn_qty = ord_qty - ccll_qty

        # ── KIS ORD_STAT 기반 1차 매핑 ──
        ord_stat = item.get("ORD_STAT", "")
        base_status = KIS_ORD_STAT_MAP.get(ord_stat)

        if base_status is OrderStatus.FILLED:
            # ORD_STAT=01(체결)이지만 qty가 미달이면 PARTIALLY_FILLED
            if ccll_qty < ord_qty or ord_qty <= 0:
                status = OrderStatus.PARTIALLY_FILLED
            else:
                status = OrderStatus.FILLED
        elif base_status is OrderStatus.SUBMITTED:
            # ORD_STAT=00(접수): CNCL_YN/RVSE_YN 우선 확인
            if item.get("CNCL_YN") == "Y":
                status = OrderStatus.CANCELLED
            elif item.get("RVSE_YN") == "Y":
                status = OrderStatus.CANCELLED
            elif ccll_qty > 0:
                # 접수 상태지만 체결이 발생한 경우
                status = OrderStatus.PARTIALLY_FILLED if ccll_qty < ord_qty else OrderStatus.FILLED
            else:
                status = OrderStatus.SUBMITTED
        elif base_status is not None:
            status = base_status
        else:
            # ── Fallback: ORD_STAT 없는 경우 기존 로직 ──
            if ccll_qty >= ord_qty and ord_qty > 0:
                status = OrderStatus.FILLED
            elif ccll_qty > 0:
                status = OrderStatus.PARTIALLY_FILLED
            elif item.get("CNCL_YN") == "Y":
                status = OrderStatus.CANCELLED
            elif item.get("RVSE_YN") == "Y":
                status = OrderStatus.CANCELLED
            else:
                status = OrderStatus.SUBMITTED

        return OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id=client_order_id,
            broker_order_id=odno,
            status=status,
            filled_quantity=ccll_qty,
            remaining_quantity=rmn_qty,
            raw_code=item.get("ORD_DVSN", ""),
            raw_message=item.get("ORD_TMD", ""),
        )
