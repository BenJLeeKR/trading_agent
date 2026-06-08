"""Tests for KisTokenCache — 중앙화된 OAuth 토큰 캐시 모듈.

14개 단위 테스트가 포함됩니다:
- 로드 성공/실패 시나리오 (7개)
- 저장 시나리오 (2개)
- 하위호환성 (4개)
- extra_validators (1개)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent_trading.brokers.koreainvestment.token_cache import (
    CachePurpose,
    KisTokenCache,
    KisTokenCacheConfig,
    TokenData,
    build_holiday_oauth_cache_config,
    build_live_approval_key_cache_config,
    build_rest_approval_key_cache_config,
    build_rest_access_token_cache_config,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _make_cache_file(
    path: Path,
    *,
    access_token: str = "test-access-token",
    expires_at: float | None = None,
    credential_fingerprint: str = "abc123def456",
    cache_purpose: str = "paper_access_token",
    created_at: float | None = None,
    **extra: str,
) -> None:
    """Write a cache file in new unified format."""
    data: dict[str, object] = {
        "access_token": access_token,
        "expires_at": expires_at or (time.time() + 3600),
        "credential_fingerprint": credential_fingerprint,
        "cache_purpose": cache_purpose,
        "created_at": created_at or time.time(),
    }
    data.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _make_old_format_file(
    path: Path,
    *,
    token_field: str = "access_token",
    fp_field: str = "app_key_fingerprint",
    access_token: str = "old-format-token",
    fingerprint: str = "old-fp-123456",
    cache_purpose: str = "",
    **extra: str,
) -> None:
    """Write a cache file in old format (backward compatibility tests)."""
    data: dict[str, object] = {
        token_field: access_token,
        "expires_at": time.time() + 3600,
        fp_field: fingerprint,
        "created_at": time.time(),
    }
    if cache_purpose:
        data["cache_purpose"] = cache_purpose
    data.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def cache(tmp_path: Path) -> KisTokenCache:
    """Basic KisTokenCache fixture with tmp_path cache file."""
    return KisTokenCache(KisTokenCacheConfig(
        enabled=True,
        cache_path=tmp_path / "kis_token.json",
        cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN,
        fingerprint_input="test-api-key",
        load_expiry_buffer=60.0,
        save_expiry_buffer=300.0,
    ))


@pytest.fixture
def cache_disabled(tmp_path: Path) -> KisTokenCache:
    """Disabled KisTokenCache fixture."""
    return KisTokenCache(KisTokenCacheConfig(
        enabled=False,
        cache_path=tmp_path / "kis_token.json",
        cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN,
        fingerprint_input="test-api-key",
    ))


@pytest.fixture
def holiday_cache(tmp_path: Path) -> KisTokenCache:
    """Holiday-like KisTokenCache fixture (fingerprint_prefix + append_secret_suffix)."""
    return KisTokenCache(KisTokenCacheConfig(
        enabled=True,
        cache_path=tmp_path / "holiday_token.json",
        cache_purpose=CachePurpose.LIVE_HOLIDAY_OAUTH,
        fingerprint_input="holiday_oauth_test-app-key_test_secret_https://api.test.com:9443",
        fingerprint_prefix="holiday_oauth_",
        fingerprint_secret="test_secret",
        append_secret_suffix=True,
        extra_validators={"token_purpose": "holiday_oauth"},
        load_expiry_buffer=60.0,
        save_expiry_buffer=60.0,
    ))


@pytest.fixture
def approval_cache(tmp_path: Path) -> KisTokenCache:
    """Approval-key-like KisTokenCache fixture (fingerprint_prefix)."""
    return KisTokenCache(KisTokenCacheConfig(
        enabled=True,
        cache_path=tmp_path / "approval_key.json",
        cache_purpose=CachePurpose.LIVE_APPROVAL_KEY,
        fingerprint_input="live_info_live-key_live-secret",
        fingerprint_prefix="live_info_",
        extra_validators={"cache_type": "approval_key"},
        load_expiry_buffer=60.0,
        save_expiry_buffer=300.0,
    ))


# ===========================================================================
# Load tests
# ===========================================================================


class TestLoad:
    """KisTokenCache.load() 테스트."""

    @pytest.mark.asyncio
    async def test_load_hit(self, cache: KisTokenCache, tmp_path: Path) -> None:
        """유효한 캐시 → 토큰 반환."""
        fp = cache._compute_fingerprint()
        _make_cache_file(
            tmp_path / "kis_token.json",
            access_token="cached-token-abc",
            credential_fingerprint=fp,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN.value,
        )
        result = await cache.load()
        assert result == "cached-token-abc"

    @pytest.mark.asyncio
    async def test_load_missing_file(self, cache: KisTokenCache) -> None:
        """파일 없음 → None 반환."""
        result = await cache.load()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_expired(self, cache: KisTokenCache, tmp_path: Path) -> None:
        """만료된 캐시 → None 반환."""
        fp = cache._compute_fingerprint()
        _make_cache_file(
            tmp_path / "kis_token.json",
            access_token="expired-token",
            expires_at=time.time() - 120,  # 2분 전 만료
            credential_fingerprint=fp,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN.value,
        )
        result = await cache.load()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_fingerprint_mismatch(
        self, cache: KisTokenCache, tmp_path: Path
    ) -> None:
        """지문 불일치 → None 반환."""
        _make_cache_file(
            tmp_path / "kis_token.json",
            access_token="wrong-fp-token",
            credential_fingerprint="wrong-fingerprint",
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN.value,
        )
        result = await cache.load()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_purpose_mismatch(
        self, cache: KisTokenCache, tmp_path: Path
    ) -> None:
        """cache_purpose 불일치 → None 반환."""
        fp = cache._compute_fingerprint()
        _make_cache_file(
            tmp_path / "kis_token.json",
            access_token="wrong-purpose-token",
            credential_fingerprint=fp,
            cache_purpose=CachePurpose.LIVE_APPROVAL_KEY.value,  # mismatch!
        )
        result = await cache.load()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_disabled(
        self, cache_disabled: KisTokenCache, tmp_path: Path
    ) -> None:
        """enabled=False → None 반환 (파일이 있어도)."""
        _make_cache_file(tmp_path / "kis_token.json")
        result = await cache_disabled.load()
        assert result is None


class TestInspect:
    """KisTokenCache.inspect() 테스트."""

    def test_inspect_ready(self, cache: KisTokenCache, tmp_path: Path) -> None:
        fp = cache._compute_fingerprint()
        _make_cache_file(
            tmp_path / "kis_token.json",
            access_token="cached-token-abc",
            credential_fingerprint=fp,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN.value,
        )
        result = cache.inspect()
        assert result.status == "ready"
        assert result.exists is True
        assert result.enabled is True
        assert result.actual_purpose == CachePurpose.PAPER_ACCESS_TOKEN.value
        assert result.actual_fingerprint == fp
        assert result.remaining_seconds is not None
        assert result.remaining_seconds > 0

    def test_inspect_disabled(self, cache_disabled: KisTokenCache) -> None:
        result = cache_disabled.inspect()
        assert result.status == "disabled"
        assert result.enabled is False
        assert result.exists is False

    @pytest.mark.asyncio
    async def test_load_invalid_json(
        self, cache: KisTokenCache, tmp_path: Path
    ) -> None:
        """손상된 JSON → None 반환 (파일 삭제)."""
        path = tmp_path / "kis_token.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{invalid json!!!}")
        result = await cache.load()
        assert result is None
        # 파일이 삭제되었는지 확인
        assert not path.exists()


# ===========================================================================
# Disclosure purpose tests
# ===========================================================================


class TestDisclosurePurpose:
    """LIVE_DISCLOSURE_ACCESS_TOKEN 전용 테스트."""

    @pytest.mark.asyncio
    async def test_load_disclosure_purpose(
        self, tmp_path: Path
    ) -> None:
        """LIVE_DISCLOSURE_ACCESS_TOKEN purpose로 저장 → 로드 성공."""
        cache = KisTokenCache(KisTokenCacheConfig(
            enabled=True,
            cache_path=tmp_path / "disclosure_token.json",
            cache_purpose=CachePurpose.LIVE_DISCLOSURE_ACCESS_TOKEN,
            fingerprint_input="live-disclosure-key",
            load_expiry_buffer=60.0,
            save_expiry_buffer=300.0,
        ))
        await cache.save("disclosure-token-abc", expires_in=86400)
        result = await cache.load()
        assert result == "disclosure-token-abc"

    @pytest.mark.asyncio
    async def test_load_disclosure_purpose_mismatch(
        self, tmp_path: Path
    ) -> None:
        """LIVE_DISCLOSURE_ACCESS_TOKEN으로 저장 → PAPER_ACCESS_TOKEN으로 로드 시 miss."""
        disclosure_cache = KisTokenCache(KisTokenCacheConfig(
            enabled=True,
            cache_path=tmp_path / "disclosure_mismatch.json",
            cache_purpose=CachePurpose.LIVE_DISCLOSURE_ACCESS_TOKEN,
            fingerprint_input="live-disclosure-key",
            load_expiry_buffer=60.0,
            save_expiry_buffer=300.0,
        ))
        await disclosure_cache.save("disclosure-token-xyz", expires_in=86400)

        paper_cache = KisTokenCache(KisTokenCacheConfig(
            enabled=True,
            cache_path=tmp_path / "disclosure_mismatch.json",
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN,
            fingerprint_input="live-disclosure-key",  # 동일 지문
            load_expiry_buffer=60.0,
            save_expiry_buffer=300.0,
        ))
        result = await paper_cache.load()
        assert result is None  # purpose 불일치로 miss


# ===========================================================================
# Save tests
# ===========================================================================


class TestSave:
    """KisTokenCache.save() 테스트."""

    @pytest.mark.asyncio
    async def test_save_success(self, cache: KisTokenCache, tmp_path: Path) -> None:
        """저장 후 다시 로드 → 성공."""
        await cache.save("new-token", expires_in=86400)
        result = await cache.load()
        assert result == "new-token"

    @pytest.mark.asyncio
    async def test_save_disabled(
        self, cache_disabled: KisTokenCache, tmp_path: Path
    ) -> None:
        """enabled=False → 저장 안함."""
        await cache_disabled.save("should-not-save", expires_in=86400)
        path = tmp_path / "kis_token.json"
        assert not path.exists()


# ===========================================================================
# Backward compatibility tests
# ===========================================================================


class TestBackwardCompat:
    """구 포맷 파일 로드 하위호환성 테스트."""

    @pytest.mark.asyncio
    async def test_backward_compat_old_fingerprint_field(
        self, cache: KisTokenCache, tmp_path: Path
    ) -> None:
        """``app_key_fingerprint`` 필드 사용 구 포맷 → 정상 로드."""
        fp = cache._compute_fingerprint()
        _make_old_format_file(
            tmp_path / "kis_token.json",
            token_field="access_token",
            fp_field="app_key_fingerprint",
            access_token="old-fp-token",
            fingerprint=fp,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN.value,
        )
        result = await cache.load()
        assert result == "old-fp-token"

    @pytest.mark.asyncio
    async def test_backward_compat_old_fingerprint_field2(
        self, cache: KisTokenCache, tmp_path: Path
    ) -> None:
        """``fingerprint`` 필드 사용 구 포맷 → 정상 로드."""
        fp = cache._compute_fingerprint()
        _make_old_format_file(
            tmp_path / "kis_token.json",
            token_field="access_token",
            fp_field="fingerprint",
            access_token="old-fp2-token",
            fingerprint=fp,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN.value,
        )
        result = await cache.load()
        assert result == "old-fp2-token"

    @pytest.mark.asyncio
    async def test_backward_compat_old_token_field(
        self, cache: KisTokenCache, tmp_path: Path
    ) -> None:
        """``token`` 필드명 사용 구 포맷 → 정상 로드."""
        fp = cache._compute_fingerprint()
        _make_old_format_file(
            tmp_path / "kis_token.json",
            token_field="token",  # old field name
            fp_field="credential_fingerprint",
            access_token="old-token-field-val",
            fingerprint=fp,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN.value,
        )
        result = await cache.load()
        assert result == "old-token-field-val"

    @pytest.mark.asyncio
    async def test_backward_compat_approval_key_field(
        self, cache: KisTokenCache, tmp_path: Path
    ) -> None:
        """``approval_key`` 필드명 사용 구 포맷 → 정상 로드."""
        fp = cache._compute_fingerprint()
        _make_old_format_file(
            tmp_path / "kis_token.json",
            token_field="approval_key",  # old field name
            fp_field="credential_fingerprint",
            access_token="old-approval-key-val",
            fingerprint=fp,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN.value,
        )
        result = await cache.load()
        assert result == "old-approval-key-val"


# ===========================================================================
# Extra validators test
# ===========================================================================


class TestExtraValidators:
    """extra_validators 검증 테스트."""

    @pytest.mark.asyncio
    async def test_extra_validators(
        self, cache: KisTokenCache, tmp_path: Path
    ) -> None:
        """extra_validators 불일치 → None 반환."""
        fp = cache._compute_fingerprint()
        # 캐시에 extra_validators가 설정되어 있으므로 (없으면 기본 빈 dict)
        # extra_validators가 비어있으므로 항상 통과
        # 여기서는 extra_validators가 있는 별도 캐시로 테스트
        cache_with_validators = KisTokenCache(KisTokenCacheConfig(
            enabled=True,
            cache_path=tmp_path / "kis_token_validated.json",
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN,
            fingerprint_input="test-api-key",
            extra_validators={"kis_env": "paper", "base_url": "https://example.com"},
            load_expiry_buffer=60.0,
            save_expiry_buffer=300.0,
        ))
        fp2 = cache_with_validators._compute_fingerprint()

        # 잘못된 extra 값으로 저장
        _make_cache_file(
            tmp_path / "kis_token_validated.json",
            access_token="wrong-extra-token",
            credential_fingerprint=fp2,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN.value,
            kis_env="wrong_env",  # mismatch!
            base_url="https://example.com",
        )
        result = await cache_with_validators.load()
        assert result is None

        # 올바른 extra 값으로 저장
        _make_cache_file(
            tmp_path / "kis_token_validated.json",
            access_token="correct-extra-token",
            credential_fingerprint=fp2,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN.value,
            kis_env="paper",  # matches
            base_url="https://example.com",  # matches
        )
        result = await cache_with_validators.load()
        assert result == "correct-extra-token"


# ===========================================================================
# Fingerprint computation tests
# ===========================================================================


class TestFingerprint:
    """_compute_fingerprint() 단위 테스트."""

    def test_fingerprint_default(self, cache: KisTokenCache) -> None:
        """기본: sha256(fingerprint_input)[:16]."""
        fp = cache._compute_fingerprint()
        expected_fp = __import__("hashlib").sha256(
            "test-api-key".encode()
        ).hexdigest()[:16]
        assert fp == expected_fp

    def test_fingerprint_with_prefix(self, holiday_cache: KisTokenCache) -> None:
        """prefix 포함: sha256(prefix + input + secret_suffix)."""
        fp = holiday_cache._compute_fingerprint()
        parts = [
            "holiday_oauth_",
            "holiday_oauth_test-app-key_test_secret_https://api.test.com:9443",
            "cret",  # test_secret[-4:]
        ]
        raw = "_".join(parts)
        expected_fp = __import__("hashlib").sha256(raw.encode()).hexdigest()[:16]
        assert fp == expected_fp

    def test_fingerprint_with_secret_suffix(self, tmp_path: Path) -> None:
        """append_secret_suffix: sha256(input + secret[-4:])[:16]."""
        c = KisTokenCache(KisTokenCacheConfig(
            enabled=True,
            cache_path=tmp_path / "test.json",
            cache_purpose=CachePurpose.LIVE_HOLIDAY_OAUTH,
            fingerprint_input="test-input",
            fingerprint_secret="my-super-secret",
            append_secret_suffix=True,
            fingerprint_prefix="",
        ))
        fp = c._compute_fingerprint()
        raw = "test-input_cret"  # "my-super-secret"[-4:] = "ret" → wait, "my-super-secret"[-4:] is "cret"
        # Actually "my-super-secret" has 15 chars. [-4:] = "cret"
        expected_fp = __import__("hashlib").sha256(raw.encode()).hexdigest()[:16]
        assert fp == expected_fp

    def test_fingerprint_wo_prefix(self, approval_cache: KisTokenCache) -> None:
        """prefix만 있고 suffix 없는 경우."""
        fp = approval_cache._compute_fingerprint()
        parts = [
            "live_info_",
            "live_info_live-key_live-secret",
        ]
        raw = "_".join(parts)
        expected_fp = __import__("hashlib").sha256(raw.encode()).hexdigest()[:16]
        assert fp == expected_fp


# ===========================================================================
# TokenData unit tests
# ===========================================================================


class TestTokenData:
    """TokenData.to_dict() / from_dict() 단위 테스트."""

    def test_to_from_dict_default(self) -> None:
        """기본 라운드트립."""
        td = TokenData(
            access_token="tok",
            expires_at=12345.0,
            credential_fingerprint="fp123",
            cache_purpose="test",
            created_at=10000.0,
            extra={"k": "v"},
        )
        d = td.to_dict()
        td2 = TokenData.from_dict(d)
        assert td2.access_token == "tok"
        assert td2.expires_at == 12345.0
        assert td2.credential_fingerprint == "fp123"
        assert td2.cache_purpose == "test"
        assert td2.extra.get("k") == "v"


class TestStandardConfigBuilders:
    """공통 cache config builder 검증."""

    def test_build_rest_access_token_cache_config(self, tmp_path: Path) -> None:
        config = build_rest_access_token_cache_config(
            enabled=True,
            cache_path=tmp_path / "rest.json",
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN,
            api_key="rest-key",
            kis_env="paper",
            base_url="https://openapivts.koreainvestment.com:29443",
        )
        assert config.cache_purpose == CachePurpose.PAPER_ACCESS_TOKEN
        assert config.fingerprint_input == "rest-key"
        assert config.extra_validators == {
            "kis_env": "paper",
            "base_url": "https://openapivts.koreainvestment.com:29443",
        }
        assert config.load_expiry_buffer == 60.0
        assert config.save_expiry_buffer == 300.0

    def test_build_holiday_oauth_cache_config(self, tmp_path: Path) -> None:
        config = build_holiday_oauth_cache_config(
            enabled=True,
            cache_path=tmp_path / "holiday.json",
            app_key="holiday-key",
            app_secret="holiday-secret",
            base_url="https://api.test.com:9443",
        )
        assert config.cache_purpose == CachePurpose.LIVE_HOLIDAY_OAUTH
        assert config.fingerprint_input == (
            "holiday_oauth_holiday-key_cret_https://api.test.com:9443"
        )
        assert config.extra_validators == {
            "token_purpose": "holiday_oauth",
            "base_url": "https://api.test.com:9443",
        }
        assert config.load_expiry_buffer == 60.0
        assert config.save_expiry_buffer == 60.0

    def test_build_live_approval_key_cache_config(self, tmp_path: Path) -> None:
        config = build_live_approval_key_cache_config(
            enabled=True,
            cache_path=tmp_path / "approval.json",
            app_key="live-key",
            api_secret="live-secret",
            base_ws_url="ws://ops.koreainvestment.com:21000",
        )
        assert config.cache_purpose == CachePurpose.LIVE_APPROVAL_KEY
        assert config.fingerprint_input == "live_info_live-key_live-secret"
        assert config.extra_validators == {
            "cache_type": "approval_key",
            "base_ws_url": "ws://ops.koreainvestment.com:21000",
        }
        assert config.load_expiry_buffer == 60.0
        assert config.save_expiry_buffer == 300.0

    def test_build_rest_approval_key_cache_config(self, tmp_path: Path) -> None:
        config = build_rest_approval_key_cache_config(
            enabled=True,
            cache_path=tmp_path / "rest_approval.json",
            api_key="rest-key",
            api_secret="rest-secret",
            kis_env="paper",
            base_url="https://openapivts.koreainvestment.com:29443",
        )
        assert config.cache_purpose == CachePurpose.TRADING_APPROVAL_KEY
        assert config.fingerprint_input == "trading_approval_rest-key_rest-secret"
        assert config.extra_validators == {
            "cache_type": "approval_key",
            "kis_env": "paper",
            "base_url": "https://openapivts.koreainvestment.com:29443",
        }
        assert config.load_expiry_buffer == 60.0
        assert config.save_expiry_buffer == 300.0

    def test_from_dict_old_fingerprint_field(self) -> None:
        """``app_key_fingerprint`` → ``credential_fingerprint`` 매핑."""
        td = TokenData.from_dict({
            "access_token": "tok",
            "expires_at": 12345.0,
            "app_key_fingerprint": "old-fp",
            "cache_purpose": "test",
        })
        assert td.credential_fingerprint == "old-fp"

    def test_from_dict_old_fingerprint_field2(self) -> None:
        """``fingerprint`` → ``credential_fingerprint`` 매핑."""
        td = TokenData.from_dict({
            "access_token": "tok",
            "expires_at": 12345.0,
            "fingerprint": "old-fp2",
            "cache_purpose": "test",
        })
        assert td.credential_fingerprint == "old-fp2"

    def test_from_dict_old_token_field(self) -> None:
        """``token`` → ``access_token`` 매핑."""
        td = TokenData.from_dict({
            "token": "old-token",
            "expires_at": 12345.0,
            "credential_fingerprint": "fp",
        })
        assert td.access_token == "old-token"

    def test_from_dict_approval_key_field(self) -> None:
        """``approval_key`` → ``access_token`` 매핑."""
        td = TokenData.from_dict({
            "approval_key": "old-approval",
            "expires_at": 12345.0,
            "credential_fingerprint": "fp",
        })
        assert td.access_token == "old-approval"
