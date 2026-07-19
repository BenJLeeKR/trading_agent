# Holiday Client Live-info File Token Cache 구현 보고서

**작성일**: 2026-05-16  
**관련 PR/이슈**: live-info OAuth token file cache 통합

---

## 1. 기존 한계 (in-memory only)

[`KISHolidayClient`](src/agent_trading/brokers/koreainvestment/holiday_client.py)는 076 국내휴장일조회 API 호출을 위해 OAuth2 access token (`/oauth2/tokenP`)을 사용합니다. 

**기존 구조의 문제점**:
- Token을 **in-memory (`_access_token`, `_token_expires_at`)에만 보관**
- 프로세스 재시작 / 컨테이너 재기동 시 token이 완전히 소실됨
- 매번 재시작마다 `/oauth2/tokenP` HTTP 호출이 필요 → 불필요한 지연 + rate limit 소모

```python
# 기존: in-memory only
self._access_token: str | None = None
self._token_expires_at: float = 0.0
```

## 2. File Cache 설계

### 2.1 Cache Resolution Order

[`_ensure_token()`](src/agent_trading/brokers/koreainvestment/holiday_client.py:149) 메서드에서 3단계 cache resolution:

```
1. In-memory cache (fastest, per-process)
   ↓ miss
2. File cache (cross-restart persistence)
   ↓ miss
3. HTTP call (/oauth2/tokenP)
   ↓ success → save to file cache
```

### 2.2 File Cache Load

[`_load_cached_token()`](src/agent_trading/brokers/koreainvestment/holiday_client.py:213):

| 검증 단계 | 실패 시 로그 | 동작 |
|-----------|-------------|------|
| `_cache_enabled` check | `Token cache miss: disabled` | None 반환 |
| File exists check | `Token cache miss: file_missing` | None 반환 |
| Fingerprint match | `Token cache miss: fingerprint_mismatch` | None 반환 |
| Token purpose check | `Token cache miss: token_purpose_mismatch` | None 반환 |
| Expiry check (1분 buffer) | `Token cache miss: expired` | None 반환 |
| **모두 통과** | `Token cache hit for live-info holiday client` | token dict 반환 |

### 2.3 File Cache Save

[`_save_cached_token()`](src/agent_trading/brokers/koreainvestment/holiday_client.py:255):

- `path.parent.mkdir(parents=True, exist_ok=True)` — 디렉토리 자동 생성
- Expiry: `now + expires_in - 60` (1분 버퍼)
- 저장 형식:
  ```json
  {
    "access_token": "eyJ...",
    "token_type": "Bearer",
    "expires_at": 1712345678.0,
    "fingerprint": "a1b2c3d4e5f6g7h8",
    "token_purpose": "holiday_oauth",
    "created_at": 1712345678.0
  }
  ```

## 3. market_state_client.py와의 관계 (Cache 파일 분리 정책)

### 결정: **별도 파일 사용**

[`market_state_client.py`](src/agent_trading/brokers/koreainvestment/market_state_client.py)는 163 approval key를 위한 file cache (`kis_live_token.json`)를 사용합니다. 두 클라이언트의 token 타입이 완전히 다르므로:

| 항목 | `market_state_client.py` | `holiday_client.py` |
|------|-------------------------|---------------------|
| Token type | **Approval key** (WebSocket) | **OAuth2 access token** (REST) |
| API | `POST /oauth2/Approval` | `POST /oauth2/tokenP` |
| Cache file | `kis_live_token.json` | `kis_live_oauth_token.json` |
| `cache_type` / `token_purpose` | `approval_key` | `holiday_oauth` |
| Fingerprint | `live_info_{app_key}_{api_secret}` → SHA-256[:16] | `holiday_oauth_{app_key}_{secret[-4:]}_{base_url}` → SHA-256[:16] |

**분리 이유**:
1. Token 타입이 완전히 다름 (approval key vs OAuth2 Bearer token)
2. 만료 시간/정책이 다를 수 있음
3. 파일 내 `token_purpose` 필드로 이중 검증 가능
4. market_state의 cache 파일을 실수로 overwrite하는 버그 방지

### Cache Path 정책

[`create_session_provider()`](src/agent_trading/services/market_session.py:439)에서:

```python
# market_state_client.py와 동일한 base path 사용
cache_base_path = os.getenv("KIS_LIVE_TOKEN_CACHE_PATH", ".cache/kis_live_token.json")
cache_parent = os.path.dirname(cache_base_path) or ".cache"
oauth_cache_path = os.path.join(cache_parent, "kis_live_oauth_token.json")
```

→ **같은 `.cache/` 디렉토리**를 공유하지만 **별도 파일** 사용

## 4. Cache Path / Fingerprint 정책

### Default Path
- 환경 변수: `KIS_LIVE_TOKEN_CACHE_PATH`의 parent 디렉토리 사용
- 파일명: `kis_live_oauth_token.json` (고정)
- 최종 경로 예: `.cache/kis_live_oauth_token.json`

### Fingerprint 구성
```python
raw = f"holiday_oauth_{app_key}_{app_secret[-4:]}_{base_url}"
fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
```

**구성 요소**:
- `holiday_oauth_` — prefix (market_state와 구분)
- `app_key` — 전체 app key
- `app_secret[-4:]` — secret 마지막 4자리 (보안)
- `base_url` — API base URL (환경 구분)

## 5. Caller 수정 내역

### [`src/agent_trading/services/market_session.py`](src/agent_trading/services/market_session.py)

**수정 전**:
```python
client = KISHolidayClient(
    app_key=app_key,
    app_secret=app_secret,
    base_url=base,
)
```

**수정 후**:
```python
cache_enabled = os.getenv("KIS_LIVE_TOKEN_CACHE_ENABLED", "false").strip().lower() == "true"
cache_base_path = os.getenv("KIS_LIVE_TOKEN_CACHE_PATH", ".cache/kis_live_token.json")
cache_parent = os.path.dirname(cache_base_path) or ".cache"
oauth_cache_path = os.path.join(cache_parent, "kis_live_oauth_token.json")

client = KISHolidayClient(
    app_key=app_key,
    app_secret=app_secret,
    base_url=base,
    enable_token_cache=cache_enabled,
    token_cache_path=oauth_cache_path,
)
```

### [`KISHolidayClient`](src/agent_trading/brokers/koreainvestment/holiday_client.py) 생성자

신규 파라미터 (`__init__` 라인 97):
- `enable_token_cache: bool = False`
- `token_cache_path: str | None = None`

### 영향받는 파일 요약

| 파일 | 변경 내용 |
|------|----------|
| [`holiday_client.py`](src/agent_trading/brokers/koreainvestment/holiday_client.py) | file cache load/save/fingerprint 로직 추가, 생성자 파라미터 추가 |
| [`market_session.py`](src/agent_trading/services/market_session.py) | cache 설정 읽어서 `KISHolidayClient`에 전달 |
| [`test_holiday_client.py`](tests/brokers/koreainvestment/test_holiday_client.py) | file cache 테스트 9개 추가 |

영향받지 않은 파일:
- `adapter.py` — `KISHolidayClient` 생성 코드 없음
- `run_near_real_ops_scheduler.py` — `create_session_provider()` 호출만 함, 변경 불필요
- `market_state_client.py` — 변경 없음 (별도 파일 정책 유지)

## 6. 테스트 결과

### 실행 명령어
```bash
cd /workspace/agent_trading && python3 -m pytest tests/brokers/koreainvestment/test_holiday_client.py -v
```

### 결과: **32/32 통과** (기존 23 + 신규 9)

### 추가된 테스트 목록

| # | 테스트 | 설명 |
|---|--------|------|
| 1 | `test_oauth_file_cache_hit` | File cache 로드 성공 → HTTP 호출 없음 |
| 2 | `test_oauth_file_cache_missing` | File missing → OAuth 발급 + cache save |
| 3 | `test_oauth_file_cache_expired` | Expired cache → 재발급 |
| 4 | `test_oauth_file_cache_fingerprint_mismatch` | Fingerprint mismatch → 재발급 |
| 5 | `test_oauth_file_cache_token_purpose_mismatch` | token_purpose mismatch (approval_key) → 재발급 |
| 6 | `test_oauth_file_cache_disabled` | Cache disabled → file 무시 |
| 7 | `test_oauth_in_memory_cache_still_works` | In-memory cache 회귀 없음 |
| 8 | `test_holiday_lookup_still_works` | 076 holiday lookup 정상 동작 + cache file 생성 확인 |
| 9 | `test_cache_save_creates_directory` | 중첩 디렉토리 자동 생성 |

### 기존 테스트 회귀 없음

기존 23개 테스트(TestHolidayStatus 3, TestGetHolidayStatusSuccess 4, TestGetHolidayStatusErrors 5, TestParseResponse 5, TestEnsureToken 4, TestClientLifecycle 2) 모두 통과.

## 7. 운영 검증 결과

### Docker 재빌드/재기동

```bash
docker compose build ops-scheduler
docker compose up -d ops-scheduler
```

### /health 확인
```bash
curl -s http://localhost:8000/health
```
→ 정상 응답 확인 필요

### Cache 검증 (ops-scheduler 로그)
```bash
docker logs ops-scheduler --tail 100
```

예상 로그 패턴:
1. **첫 기동**: `Token cache miss: file_missing` → OAuth 발급 → `Token cache saved for live-info holiday client`
2. **재시작 후**: `Token cache hit for live-info holiday client`

### Cache 파일 확인
```bash
docker exec ops-scheduler ls -la /app/data/.cache/
docker exec ops-scheduler cat /app/data/.cache/kis_live_oauth_token.json
```

## 8. 남은 Follow-up

| 우선순위 | 항목 | 설명 |
|---------|------|------|
| P1 | **Docker 운영 검증** | 위 7번 항목 실제 실행 및 로그 확인 |
| P2 | **Cache file TTL 정책 문서화** | 24시간 만료 후 크론/스케줄러에서 자동 삭제 정책 고려 |
| P3 | **Cache file 암호화 검토** | token이 평문 저장되므로, Docker volume 접근 권한 재검토 |
| P4 | **Fallback 행동 테스트** | cache file corrupt 시 OAuth 재발급이 정상 동작하는지 E2E 확인 |

---

## Appendix: 변경된 파일 전체 diff

### [`holiday_client.py`](src/agent_trading/brokers/koreainvestment/holiday_client.py) 주요 변경 포인트

```diff
+ import hashlib
+ import json
+ import time
+ from pathlib import Path

  class KISHolidayClient:
      def __init__(
          self,
          app_key: str,
          app_secret: str,
          base_url: str = ...,
+         *,
+         enable_token_cache: bool = False,
+         token_cache_path: str | None = None,
      ):
          ...
+         self._cache_enabled = enable_token_cache
+         self._cache_path = token_cache_path
+         raw_fp = f"holiday_oauth_{app_key}_{app_secret[-4:]}_{self._base_url}"
+         self._fingerprint = hashlib.sha256(raw_fp.encode()).hexdigest()[:16]

      async def _ensure_token(self) -> str:
          async with self._auth_lock:
-             now = asyncio.get_event_loop().time()  # loop time (old)
+             now_wall = time.time()  # wall clock

              # 1. In-memory cache hit
-             if self._access_token is not None and now < self._token_expires_at:
+             if self._access_token is not None and now_wall < self._token_expires_at:
                  return self._access_token

+             # 2. File cache load
+             cached = self._load_cached_token()
+             if cached is not None:
+                 self._access_token = cached["access_token"]
+                 self._token_expires_at = cached["expires_at"]
+                 return self._access_token
+
              # 3. HTTP call
              ...
-             self._token_expires_at = now + expires_in - 300
+             self._token_expires_at = now_wall + expires_in - 300

+             # 4. Save to file cache
+             self._save_cached_token(data, now_wall, expires_in)

+     def _load_cached_token(self) -> dict | None: ...
+     def _save_cached_token(self, token_data, now_wall, expires_in) -> None: ...
```

### [`market_session.py`](src/agent_trading/services/market_session.py) 주요 변경 포인트

```diff
  async def create_session_provider() -> MarketSessionProvider:
      ...
      if enabled and app_key and app_secret:
          base = base_url or "..."
+         cache_enabled = os.getenv("KIS_LIVE_TOKEN_CACHE_ENABLED", "false") == "true"
+         cache_base_path = os.getenv("KIS_LIVE_TOKEN_CACHE_PATH", ".cache/kis_live_token.json")
+         cache_parent = os.path.dirname(cache_base_path) or ".cache"
+         oauth_cache_path = os.path.join(cache_parent, "kis_live_oauth_token.json")
+
          client = KISHolidayClient(
              app_key=app_key,
              app_secret=app_secret,
              base_url=base,
+             enable_token_cache=cache_enabled,
+             token_cache_path=oauth_cache_path,
          )
```
