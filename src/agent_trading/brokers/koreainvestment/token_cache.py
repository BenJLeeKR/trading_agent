"""KIS OAuth Token/Approval-key File Cache — 중앙화된 캐시 모듈.

3개 클라이언트 (``KISRestClient``, ``KISHolidayClient``, ``KisMarketStateClient``)에서
각각 구현했던 OAuth 토큰/승인키 파일 캐시 로직을 단일 ``KisTokenCache`` 클래스로 통합합니다.

사용 예::

    cache = KisTokenCache(KisTokenCacheConfig(
        enabled=True,
        cache_path=Path(".cache/kis_token.json"),
        cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN,
        fingerprint_input=api_key,
    ))
    token = await cache.load()
    if token is None:
        token = await fetch_token_from_api()
        await cache.save(token, expires_in=86400)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CachePurpose — 캐시 용도 식별자
# ---------------------------------------------------------------------------


class CachePurpose(str, Enum):
    """캐시 용도 enum — 저장/검증 시 ``cache_purpose`` 필드로 사용.

    각 클라이언트가 이 값을 통해 자신의 캐시인지 식별합니다.
    """

    PAPER_ACCESS_TOKEN = "paper_access_token"
    LIVE_HOLIDAY_OAUTH = "live_holiday_oauth"
    LIVE_APPROVAL_KEY = "live_approval_key"
    LIVE_DISCLOSURE_ACCESS_TOKEN = "live_disclosure_access_token"


# ---------------------------------------------------------------------------
# TokenData — 저장/로드 데이터 포맷
# ---------------------------------------------------------------------------


@dataclass
class TokenData:
    """캐시 파일에 저장되는 토큰 데이터.

    ``to_dict()`` / ``from_dict()`` 를 통해 JSON 직렬화/역직렬화하며,
    ``from_dict()`` 는 구 포맷 필드명을 자동으로 매핑합니다 (하위호환성).
    """

    access_token: str
    expires_at: float  # Unix timestamp
    credential_fingerprint: str  # 통일된 지문 필드명
    cache_purpose: str  # CachePurpose 값
    created_at: float  # time.time()
    extra: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # 직렬화
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """신규 통합 포맷으로 직렬화.

        저장 시 항상 이 메서드를 사용하므로, 파일은 항상 신규 포맷입니다.
        """
        d: dict[str, object] = {
            "access_token": self.access_token,
            "expires_at": self.expires_at,
            "credential_fingerprint": self.credential_fingerprint,
            "cache_purpose": self.cache_purpose,
            "created_at": self.created_at,
        }
        d.update(self.extra)
        return d

    # ------------------------------------------------------------------
    # 역직렬화 (하위호환성 포함)
    # ------------------------------------------------------------------

    OLD_FINGERPRINT_FIELDS = ("app_key_fingerprint", "fingerprint")
    """구 포맷에서 사용하던 지문 필드명 목록."""

    OLD_TOKEN_FIELDS = ("token", "approval_key")
    """구 포맷에서 사용하던 토큰 필드명 목록."""

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TokenData":
        """JSON 데이터에서 ``TokenData`` 로드 (하위호환성 매핑 포함).

        구 포맷 필드 매핑 규칙:
        - ``credential_fingerprint`` 가 없으면 ``app_key_fingerprint`` → ``fingerprint`` 순서로 fallback
        - ``access_token`` 이 없으면 ``token`` → ``approval_key`` 순서로 fallback
        - ``cache_purpose`` 가 없으면 빈 문자열 (검증 시 skip)
        """
        # 1. access_token (하위호환)
        access_token: str = _first_of(data, "access_token", *cls.OLD_TOKEN_FIELDS)

        # 2. expires_at
        expires_at = float(data["expires_at"])  # KeyError on missing

        # 3. credential_fingerprint (하위호환)
        credential_fingerprint: str = _first_of(
            data, "credential_fingerprint", *cls.OLD_FINGERPRINT_FIELDS
        )

        # 4. cache_purpose (신규, 없으면 빈 문자열)
        cache_purpose = str(data.get("cache_purpose", ""))

        # 5. created_at (없으면 현재 시각)
        created_at = float(data.get("created_at", time.time()))

        # 6. extra — 신규 필드를 제외한 나머지
        standard_keys = {
            "access_token",
            "token",
            "approval_key",
            "expires_at",
            "credential_fingerprint",
            "app_key_fingerprint",
            "fingerprint",
            "cache_purpose",
            "created_at",
        }
        extra: dict[str, str] = {}
        for k, v in data.items():
            if k not in standard_keys and isinstance(v, str):
                extra[k] = v

        return cls(
            access_token=access_token,
            expires_at=expires_at,
            credential_fingerprint=credential_fingerprint,
            cache_purpose=cache_purpose,
            created_at=created_at,
            extra=extra,
        )


def _first_of(data: dict[str, object], *keys: str) -> str:
    """주어진 키 중 첫 번째로 존재하는 값을 반환.

    Raises:
        KeyError: 모든 키가 데이터에 없을 경우.
    """
    for k in keys:
        v = data.get(k)
        if v is not None:
            return str(v)
    raise KeyError(f"None of {keys} found in data")


# ---------------------------------------------------------------------------
# KisTokenCacheConfig
# ---------------------------------------------------------------------------


@dataclass
class KisTokenCacheConfig:
    """``KisTokenCache`` 설정 dataclass.

    Attributes:
        enabled: 캐시 사용 여부.
        cache_path: 캐시 파일 경로.
        cache_purpose: 캐시 용도 (``CachePurpose`` enum).
        fingerprint_input: 지문 계산 입력값 (보통 api_key).
        fingerprint_prefix: 지문 prefix (예: ``"holiday_oauth_"``).
        fingerprint_secret: ``append_secret_suffix`` 사용 시 secret 값.
        append_secret_suffix: ``fingerprint_secret[-4:]`` 를 지문에 포함.
        append_secret_full: ``fingerprint_secret`` 전체를 지문에 포함.
        extra_validators: 추가 검증 필드 (예: ``{"kis_env": "paper"}``).
        load_expiry_buffer: 로드 시 만료 버퍼 (초). 기본 60s.
        save_expiry_buffer: 저장 시 만료 버퍼 (초). 기본 300s.
    """

    enabled: bool = True
    cache_path: Path = Path(".cache/kis_token.json")
    cache_purpose: CachePurpose = CachePurpose.PAPER_ACCESS_TOKEN
    fingerprint_input: str = ""
    fingerprint_prefix: str = ""
    fingerprint_secret: str = ""
    append_secret_suffix: bool = False
    append_secret_full: bool = False
    extra_validators: dict[str, str] = field(default_factory=dict)
    load_expiry_buffer: float = 60.0
    save_expiry_buffer: float = 300.0


# ---------------------------------------------------------------------------
# KisTokenCache
# ---------------------------------------------------------------------------


class KisTokenCache:
    """파일 기반 OAuth 토큰/승인키 캐시.

    7단계 로드 시퀀스와 저장 시퀀스를 구현합니다.
    스레드 안전성은 호출자 (asyncio.Lock 등) 에게 위임합니다.
    """

    def __init__(self, config: KisTokenCacheConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    async def load(self) -> str | None:
        """7단계 로드 시퀀스:

        1. ``enabled`` 확인 → disabled면 ``None``
        2. 캐시 파일 존재 확인 → 없으면 ``None``
        3. JSON 파싱 → 실패시 ``None`` (파일 삭제)
        4. ``credential_fingerprint`` 검증 → 불일치시 ``None``
        5. ``cache_purpose`` 검증 → 불일치시 ``None``
        6. ``extra_validators`` 검증 → 불일치시 ``None``
        7. ``expires_at`` 만료 확인 (+ buffer) → 만료시 ``None``

        성공시 ``access_token`` 반환.
        """
        # 1. enabled
        if not self.config.enabled:
            self._log_miss("disabled")
            return None

        # 2. 파일 존재
        path = self.config.cache_path
        if not path.exists():
            self._log_miss("file_missing")
            return None

        # 3. JSON 파싱
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._log_miss("read_error", error=str(exc))
            # 손상된 파일 삭제 — 다음 기회에 새로 생성
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

        # 역직렬화 + 검증
        try:
            data = TokenData.from_dict(raw)
        except (KeyError, ValueError, TypeError) as exc:
            self._log_miss("parse_error", error=str(exc))
            return None

        # 4. fingerprint 검증
        expected_fp = self._compute_fingerprint()
        if data.credential_fingerprint != expected_fp:
            self._log_miss(
                "fingerprint_mismatch",
                expected=expected_fp,
                got=data.credential_fingerprint,
            )
            return None

        # 5. cache_purpose 검증
        #    구 포맷(cache_purpose 필드 없음)은 빈 문자열 → 검증 skip
        if data.cache_purpose and self.config.cache_purpose.value != data.cache_purpose:
            self._log_miss(
                "purpose_mismatch",
                expected=self.config.cache_purpose.value,
                got=data.cache_purpose,
            )
            return None

        # 6. extra_validators 검증
        for key, expected_val in self.config.extra_validators.items():
            actual_val = data.extra.get(key)
            if actual_val != expected_val:
                self._log_miss(
                    "validator_mismatch",
                    key=key,
                    expected=expected_val,
                    got=actual_val,
                )
                return None

        # 7. 만료 확인
        now = time.time()
        if now >= data.expires_at - self.config.load_expiry_buffer:
            self._log_miss(
                "expired",
                expires_at=data.expires_at,
                buffer=self.config.load_expiry_buffer,
            )
            return None

        # 성공
        self._log_hit()
        return data.access_token

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    async def save(self, token: str, expires_in: float) -> None:
        """저장 시퀀스:

        1. ``enabled`` 확인 → disabled면 skip
        2. 디렉토리 생성
        3. ``TokenData`` 구성 → ``to_dict()`` → JSON 저장
        """
        # 1. enabled
        if not self.config.enabled:
            return

        path = self.config.cache_path

        # 2. 디렉토리 생성
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._log_miss("save_mkdir_failed")
            return

        # 3. TokenData 구성
        now = time.time()
        data = TokenData(
            access_token=token,
            expires_at=now + expires_in - self.config.save_expiry_buffer,
            credential_fingerprint=self._compute_fingerprint(),
            cache_purpose=self.config.cache_purpose.value,
            created_at=now,
            extra=dict(self.config.extra_validators),
        )

        # 4. JSON 저장
        try:
            path.write_text(json.dumps(data.to_dict(), indent=2))
        except OSError:
            self._log_miss("save_write_failed")
            return

        logger.info(
            "%s token cache: saved path=%s expires_at=%s",
            self.config.cache_purpose.value,
            path,
            data.expires_at,
        )

    # ------------------------------------------------------------------
    # Fingerprint
    # ------------------------------------------------------------------

    def _compute_fingerprint(self) -> str:
        """통합 지문 계산.

        구성 요소를 ``_`` 로 결합한 후 SHA-256 해시의 앞 16자를 반환:
        1. ``fingerprint_prefix`` (있을 경우)
        2. ``fingerprint_input``
        3. ``fingerprint_secret[-4:]`` (``append_secret_suffix=True`` 일 경우)
        4. ``fingerprint_secret`` 전체 (``append_secret_full=True`` 일 경우)

        Returns:
            16자리 16진수 SHA-256 fingerprint.
        """
        parts: list[str] = []
        if self.config.fingerprint_prefix:
            parts.append(self.config.fingerprint_prefix)
        parts.append(self.config.fingerprint_input)
        if self.config.append_secret_full and self.config.fingerprint_secret:
            parts.append(self.config.fingerprint_secret)
        elif self.config.append_secret_suffix and self.config.fingerprint_secret:
            secret = self.config.fingerprint_secret
            suffix = secret[-4:] if len(secret) >= 4 else secret
            parts.append(suffix)
        raw = "_".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_hit(self) -> None:
        """캐시 hit 로깅."""
        logger.info(
            "%s token cache: hit path=%s",
            self.config.cache_purpose.value,
            self.config.cache_path,
        )

    def _log_miss(self, reason: str, **extra: object) -> None:
        """캐시 miss 로깅 (구조화된 키-값 로그)."""
        parts = [
            f"{self.config.cache_purpose.value} token cache: miss",
            f"reason={reason}",
            f"path={self.config.cache_path}",
        ]
        for k, v in extra.items():
            parts.append(f"{k}={v}")
        logger.info(" ".join(parts))
