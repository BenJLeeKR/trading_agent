from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
})


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

    # --- internal state ---
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)
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
        """Normalize ``real`` → ``live`` for KIS_ENV compatibility."""
        if self.env.strip().lower() == "real":
            object.__setattr__(self, "env", "live")

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
                timeout=httpx.Timeout(30.0, connect=10.0),
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
    # Dev token cache (file-based, paper/dev only)
    # ------------------------------------------------------------------

    async def _load_dev_token_cache(self) -> None:
        """Load access token from file cache if valid.

        Validates fingerprint, env, base_url, and expiry.
        Silent on any failure — falls back to HTTP call.
        """
        if not self.dev_token_cache_enabled:
            return
        path = Path(self.dev_token_cache_path)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            expected_fp = hashlib.sha256(self.api_key.encode()).hexdigest()[:16]
            if data.get("app_key_fingerprint") != expected_fp:
                return
            if data.get("kis_env") != self.env:
                return
            if data.get("base_url") != self._base_url:
                return
            expires_at = float(data["expires_at"])
            if time.time() >= expires_at - 60:
                return
            self._access_token = data["access_token"]
            self._token_expires_at = expires_at
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
            return

    async def _save_dev_token_cache(self) -> None:
        """Save the current access token to file cache."""
        if not self.dev_token_cache_enabled:
            return
        if self._access_token is None:
            return
        path = Path(self.dev_token_cache_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fingerprint = hashlib.sha256(self.api_key.encode()).hexdigest()[:16]
            data: dict[str, object] = {
                "access_token": self._access_token,
                "token_type": "bearer",
                "expires_at": self._token_expires_at,
                "kis_env": self.env,
                "base_url": self._base_url,
                "app_key_fingerprint": fingerprint,
                "created_at": time.time(),
            }
            path.write_text(json.dumps(data, indent=2))
        except OSError:
            return

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
                return self._access_token

            # 1b. Dev token cache: load from file if in-memory cache is empty
            if self._access_token is None:
                await self._load_dev_token_cache()
                if self._access_token is not None and now_wall < self._token_expires_at:
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
            # 4b. Dev token cache: persist to file
            await self._save_dev_token_cache()
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
    ) -> dict[str, Any]:
        """Unified request helper with budget consumption and circuit breaker.

        Steps:
        1. Consume budget (if manager provided)
        2. Check circuit breaker
        3. Build headers + optional hashkey
        4. Execute HTTP request
        5. Normalise response
        """
        # 1. Budget check
        if self.budget_manager is not None:
            self.budget_manager.consume_or_raise(bucket)

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

    async def submit_order(self, request: SubmitOrderRequest) -> SubmitOrderResult:
        """Submit a stock order (현금 매수/매도).

        Uses order-cash endpoint for regular orders.
        Hashkey is required for order requests.
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

    async def get_order_status(
        self,
        account_ref: str,
        client_order_id: str | None = None,
        broker_order_id: str | None = None,
    ) -> OrderStatusResult:
        """Query order status via daily settlement inquiry.

        Uses inquire-daily-ccld endpoint.
        Matches the ``BrokerAdapter`` protocol signature.
        """
        params = {
            "CANO": self.account_number,
            "ACNT_PRDT_CD": self.account_product_code,
            "INQR_STRT_DT": "19700101",  # full range
            "INQR_END_DT": datetime.now(timezone.utc).strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00",  # 전체
            "INQR_DVSN": "00",  # 조회구분 (역순)
            "PDNO": "",  # 전체종목
            "CCLD_DVSN": "00",  # 전체
            "ORD_GUBUN": "00",  # 주문구분
            "ORD_SRT_DVSN": "01",  # 주문시작구분
        }

        data = await self._request(
            "GET",
            endpoint_key="inquire_daily_ccld",
            tr_id_key="inquire_daily_ccld",
            bucket=BucketType.INQUIRY,
            params=params,
        )

        output = data.get("output", [])
        if isinstance(output, dict):
            output = [output]

        # ── Instrumentation: capture inquire-daily-ccld response for paper mock analysis ──
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

        # Find the matching order by broker_order_id
        if broker_order_id is not None:
            for item in output:
                if item.get("ODNO") == broker_order_id:
                    return self._parse_order_status_item(item)

        logger.info(
            "inquire-daily-ccld: ODNO match FAILED for broker_order_id=%s "
            "(output_count=%d, odnos_in_response=%s)",
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

        Uses inquire-daily-ccld endpoint.
        Matches the ``BrokerAdapter`` protocol signature.
        """
        params = {
            "CANO": self.account_number,
            "ACNT_PRDT_CD": self.account_product_code,
            "INQR_STRT_DT": "19700101",
            "INQR_END_DT": datetime.now(timezone.utc).strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "ORD_GUBUN": "00",
            "ORD_SRT_DVSN": "01",
        }

        data = await self._request(
            "GET",
            endpoint_key="inquire_daily_ccld",
            tr_id_key="inquire_daily_ccld",
            bucket=BucketType.INQUIRY,
            params=params,
        )

        output = data.get("output", [])
        if isinstance(output, dict):
            output = [output]

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

    async def get_cash_balance(self) -> dict[str, Any]:
        """Retrieve cash balance (잔고조회 — cash component).

        Uses inquire-balance endpoint and extracts the cash portion
        from ``output2`` (예수금 총괄).

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

        # output2 contains the cash summary (예수금 총괄)
        output2 = data.get("output2", {})
        if isinstance(output2, list):
            output2 = output2[0] if output2 else {}
        return output2

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

    async def resolve_unknown_state(
        self,
        broker_order_id: str,
        symbol: str,
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
        # 1. Try inquiry path with reconciliation reserve fallback
        result = await self._request_with_fallback(
            "GET",
            endpoint_key="inquire_daily_ccld",
            tr_id_key="inquire_daily_ccld",
            bucket=BucketType.INQUIRY,
            params={
                "CANO": self.account_number,
                "ACNT_PRDT_CD": self.account_product_code,
                "INQR_STRT_DT": "19700101",
                "INQR_END_DT": datetime.now(timezone.utc).strftime("%Y%m%d"),
                "SLL_BUY_DVSN_CD": "00",
                "INQR_DVSN": "00",
                "PDNO": "",
                "CCLD_DVSN": "00",
                "ORD_GUBUN": "00",
                "ORD_SRT_DVSN": "01",
            },
        )

        output = result.get("output", [])
        if isinstance(output, dict):
            output = [output]

        # Find the matching order
        for item in output:
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
            # Retry after reserving reconciliation budget
            return await self._request(
                method,
                endpoint_key=endpoint_key,
                tr_id_key=tr_id_key,
                bucket=bucket,
                body=body,
                params=params,
                requires_hashkey=requires_hashkey,
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
    def _parse_order_status_item(
        item: dict[str, Any],
        client_order_id: str | None = None,
    ) -> OrderStatusResult:
        """Parse a single KIS order status item into OrderStatusResult."""
        odno = item.get("ODNO", "")
        ord_qty = Decimal(item.get("ORD_QTY", "0"))
        ccll_qty = Decimal(item.get("CCLD_QTY", "0"))
        rmn_qty = ord_qty - ccll_qty

        # Determine status from KIS fields
        ord_dvsn = item.get("ORD_DVSN", "")  # 주문구분
        ord_tmd = item.get("ORD_TMD", "")     # 주문시각
        ccll_tmd = item.get("CCLD_TMD", "")   # 체결시각

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
