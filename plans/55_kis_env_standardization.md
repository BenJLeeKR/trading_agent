# KIS 환경변수 표준화 — 구현 계획

## 현재 상태 요약

| 항목 | 현재 값 | 문제 |
|------|---------|------|
| API Key env var | `KIS_API_KEY` | 한국투자증권 실제 표기는 `KIS_APP_KEY` |
| API Secret env var | `KIS_API_SECRET` | 한국투자증권 실제 표기는 `KIS_APP_SECRET` |
| 계좌번호 env var | `KIS_ACCOUNT_NUMBER` | 한국투자증권 실제 표기는 `KIS_ACCOUNT_NO` |
| 실전 env 값 | `live` | 한국투자증권 실제 표기는 `real` |
| Base URL env var | `KIS_BASE_URL` (미연결) | 코드에서 전혀 읽히지 않음 |
| Environment enum | `PAPER="paper"`, `LIVE="live"` | `REAL` 없음 |
| KIS_API_BASE_URLS | hardcoded dict | `KIS_BASE_URL` override 불가 |
| KIS_WS_URLS | hardcoded dict | WebSocket URL override 불가 |

## 변경 파일 목록 (8개)

```
src/agent_trading/config/settings.py          — env resolver + KIS_BASE_URL 필드 추가
src/agent_trading/domain/enums.py             — Environment.REAL alias 추가
src/agent_trading/brokers/koreainvestment/rest_client.py  — base_url override + real→live 정규화
src/agent_trading/brokers/koreainvestment/websocket_client.py  — real→live 정규화
src/agent_trading/runtime/bootstrap.py        — kis_base_url 전달
.env.example                                  — 새 표기 우선 + fallback 주석
docker-compose.yml                            — 새 표기 우선 + fallback 유지
tests/smoke/test_kis_paper_smoke.py           — 새 env 이름 우선 + fallback
```

## 변경 상세

### 1. [`src/agent_trading/config/settings.py`](src/agent_trading/config/settings.py) — env resolver 표준화

**`AppSettings` 필드 변경:**

```python
# AS-IS:
kis_api_key: str = field(default_factory=lambda: os.getenv("KIS_API_KEY", ""))
kis_api_secret: str = field(default_factory=lambda: os.getenv("KIS_API_SECRET", ""))
kis_account_number: str = field(default_factory=lambda: os.getenv("KIS_ACCOUNT_NUMBER", ""))
kis_account_product_code: str = field(default_factory=lambda: os.getenv("KIS_ACCOUNT_PRODUCT_CODE", "01"))
kis_env: str = field(default_factory=lambda: os.getenv("KIS_ENV", "paper"))

# TO-BE:
kis_api_key: str = field(default_factory=_resolve_kis_api_key)
kis_api_secret: str = field(default_factory=_resolve_kis_api_secret)
kis_account_number: str = field(default_factory=_resolve_kis_account_number)
kis_account_product_code: str = field(default_factory=lambda: os.getenv("KIS_ACCOUNT_PRODUCT_CODE", "01"))
kis_env: str = field(default_factory=_resolve_kis_env)
kis_base_url: str = field(default_factory=lambda: os.getenv("KIS_BASE_URL", ""))
```

**새 resolver 함수들:**

```python
def _resolve_kis_api_key() -> str:
    """KIS_APP_KEY 우선, fallback KIS_API_KEY."""
    return os.getenv("KIS_APP_KEY") or os.getenv("KIS_API_KEY", "")

def _resolve_kis_api_secret() -> str:
    """KIS_APP_SECRET 우선, fallback KIS_API_SECRET."""
    return os.getenv("KIS_APP_SECRET") or os.getenv("KIS_API_SECRET", "")

def _resolve_kis_account_number() -> str:
    """KIS_ACCOUNT_NO 우선, fallback KIS_ACCOUNT_NUMBER."""
    return os.getenv("KIS_ACCOUNT_NO") or os.getenv("KIS_ACCOUNT_NUMBER", "")

def _resolve_kis_env() -> str:
    """Read KIS_ENV, normalize 'real' → 'live'."""
    raw = os.getenv("KIS_ENV", "paper")
    return raw.strip().lower().replace("real", "live")
```

### 2. [`src/agent_trading/domain/enums.py`](src/agent_trading/domain/enums.py) — Environment.REAL alias

```python
class Environment(str, Enum):
    PAPER = "paper"
    LIVE = "live"
    REAL = "real"  # KIS 실제 표기 alias — normalize to LIVE internally
```

> `REAL = "real"`은 외부 입력 수용용. 내부 로직은 `LIVE`를 canonical 값으로 사용.

### 3. [`src/agent_trading/brokers/koreainvestment/rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py) — base_url override + env 정규화

**`KISRestClient`에 `base_url_override` 필드 추가:**

```python
@dataclass(slots=True)
class KISRestClient:
    api_key: str
    api_secret: str
    account_number: str
    account_product_code: str
    env: str = "paper"  # "live" | "paper" — "real"은 외부에서 normalize됨
    budget_manager: RateLimitBudgetManager | None = None
    base_url: str = ""  # KIS_BASE_URL override; 빈 값이면 hardcoded mapping 사용
```

**`_base_url` property 변경:**

```python
@property
def _base_url(self) -> str:
    """KIS_BASE_URL override → hardcoded mapping fallback."""
    if self.base_url:
        return self.base_url.rstrip("/")
    return KIS_API_BASE_URLS[self.env]
```

**env 정규화 (__post_init__):**

```python
def __post_init__(self) -> None:
    # Normalize 'real' → 'live'
    if self.env == "real":
        object.__setattr__(self, "env", "live")
```

> `__post_init__`을 추가하려면 `from __future__ import annotations`로 인해 `slots=True` dataclass에서 `object.__setattr__`를 사용해야 함.

### 4. [`src/agent_trading/brokers/koreainvestment/websocket_client.py`](src/agent_trading/brokers/koreainvestment/websocket_client.py) — env 정규화

**`connect()` 메서드 내 URL lookup 전 정규화:**

```python
async def connect(self) -> None:
    import websockets
    
    # Normalize 'real' → 'live' for URL lookup
    env_key = "live" if self._env == "real" else self._env
    url = KIS_WS_URLS[env_key]
    ...
```

### 5. [`src/agent_trading/runtime/bootstrap.py`](src/agent_trading/runtime/bootstrap.py) — base_url 전달

```python
def _build_kis_adapter(settings: AppSettings) -> KoreaInvestmentAdapter:
    rest_client = KISRestClient(
        api_key=settings.kis_api_key,
        api_secret=settings.kis_api_secret,
        account_number=settings.kis_account_number,
        account_product_code=settings.kis_account_product_code,
        env=settings.kis_env,
        base_url=settings.kis_base_url,  # 추가
    )
    return KoreaInvestmentAdapter(rest_client=rest_client)
```

### 6. [`.env.example`](.env.example) — 새 표기 우선

```ini
# ---- Korea Investment & Securities (KIS) ----------------------------------
# Preferred naming (한국투자증권 actual env names):
KIS_ENV=paper                  # "paper" | "real" (or legacy "live")
KIS_BASE_URL=                  # Optional: override base URL
KIS_APP_KEY=                   # Preferred: 앱키 (App Key)
KIS_APP_SECRET=                # Preferred: 앱시크릿 (App Secret)
KIS_ACCOUNT_NO=                # Preferred: 계좌번호 (Account No)
KIS_ACCOUNT_PRODUCT_CODE=01    # 계좌상품코드 (기본 01)
#
# Legacy fallback names (deprecated, still supported):
# KIS_API_KEY=                  ← replaced by KIS_APP_KEY
# KIS_API_SECRET=               ← replaced by KIS_APP_SECRET
# KIS_ACCOUNT_NUMBER=           ← replaced by KIS_ACCOUNT_NO
```

### 7. [`docker-compose.yml`](docker-compose.yml) — 새 표기 추가

`app` 서비스와 `api` 서비스 모두에 새 env 이름 추가:

```yaml
environment:
  # KIS — preferred naming (한국투자증권 actual)
  KIS_ENV: "${KIS_ENV:-paper}"
  KIS_BASE_URL: "${KIS_BASE_URL:-}"
  KIS_APP_KEY: "${KIS_APP_KEY:-}"
  KIS_APP_SECRET: "${KIS_APP_SECRET:-}"
  KIS_ACCOUNT_NO: "${KIS_ACCOUNT_NO:-}"
  KIS_ACCOUNT_PRODUCT_CODE: "${KIS_ACCOUNT_PRODUCT_CODE:-01}"
  # KIS — legacy fallback (deprecated)
  KIS_API_KEY: "${KIS_API_KEY:-}"
  KIS_API_SECRET: "${KIS_API_SECRET:-}"
  KIS_ACCOUNT_NUMBER: "${KIS_ACCOUNT_NUMBER:-}"
```

### 8. [`tests/smoke/test_kis_paper_smoke.py`](tests/smoke/test_kis_paper_smoke.py) — 새 env 이름 허용

**`_REQUIRED_ENV_VARS`와 `_credentials_configured()` 업데이트:**

```python
_REQUIRED_ENV_VARS: tuple[str, ...] = (
    "KIS_APP_KEY",        # preferred
    "KIS_APP_SECRET",     # preferred
    "KIS_ACCOUNT_NO",     # preferred
)

def _credentials_configured() -> bool:
    """Check if KIS credentials are configured (new name or legacy fallback)."""
    # Check preferred names first, then legacy fallback
    for var in ("KIS_APP_KEY", "KIS_API_KEY"):
        if os.getenv(var):
            break
    else:
        return False
    for var in ("KIS_APP_SECRET", "KIS_API_SECRET"):
        if os.getenv(var):
            break
    else:
        return False
    for var in ("KIS_ACCOUNT_NO", "KIS_ACCOUNT_NUMBER"):
        if os.getenv(var):
            break
    else:
        return False
    return True
```

**Fixture에서 env 읽을 때 fallback:**

```python
api_key = os.environ.get("KIS_APP_KEY") or os.environ["KIS_API_KEY"]
api_secret = os.environ.get("KIS_APP_SECRET") or os.environ["KIS_API_SECRET"]
account_number = os.environ.get("KIS_ACCOUNT_NO") or os.environ["KIS_ACCOUNT_NUMBER"]
```

> **참고**: `test_kis_paper_ai_runtime_smoke.py`도 동일한 패턴으로 수정 필요.

## 테스트

### 추가할 테스트 (test_settings.py에 추가)

```python
class TestKisEnvResolver:
    """KIS env var resolver: preferred name priority + fallback + normalization."""

    def test_kis_api_key_preferred(self, monkeypatch):
        monkeypatch.setenv("KIS_APP_KEY", "preferred-key")
        monkeypatch.setenv("KIS_API_KEY", "fallback-key")
        assert _resolve_kis_api_key() == "preferred-key"

    def test_kis_api_key_fallback(self, monkeypatch):
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.setenv("KIS_API_KEY", "fallback-key")
        assert _resolve_kis_api_key() == "fallback-key"

    def test_kis_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_API_KEY", raising=False)
        assert _resolve_kis_api_key() == ""
    
    # ... similar for api_secret, account_number ...

    def test_kis_env_real_normalized(self, monkeypatch):
        monkeypatch.setenv("KIS_ENV", "real")
        assert _resolve_kis_env() == "live"

    def test_kis_env_live_stays(self, monkeypatch):
        monkeypatch.setenv("KIS_ENV", "live")
        assert _resolve_kis_env() == "live"

    def test_kis_env_paper_default(self, monkeypatch):
        monkeypatch.delenv("KIS_ENV", raising=False)
        assert _resolve_kis_env() == "paper"

    def test_kis_base_url_override(self, monkeypatch):
        monkeypatch.setenv("KIS_BASE_URL", "https://custom.url:9443")
        settings = AppSettings()
        assert settings.kis_base_url == "https://custom.url:9443"

    def test_kis_base_url_empty_default(self, monkeypatch):
        monkeypatch.delenv("KIS_BASE_URL", raising=False)
        settings = AppSettings()
        assert settings.kis_base_url == ""
```

### 기존 테스트에 미치는 영향
- `test_kis_paper_smoke.py`: env var 읽는 방식 변경 (fallback 체인) — 기존 `KIS_API_KEY`만 설정된 환경에서도 정상 동작
- `test_kis_paper_ai_runtime_smoke.py`: 동일
- `test_settings.py`: 기존 LLM Provider 테스트는 변경 없음. KIS resolver 테스트만 추가.

## 구현 순서

1. `domain/enums.py` — `REAL` alias 추가 (side-effect 없음)
2. `config/settings.py` — resolver 함수들 + `kis_base_url` 필드 추가
3. `brokers/koreainvestment/rest_client.py` — `base_url` 필드 + `__post_init__` + `_base_url` 변경
4. `brokers/koreainvestment/websocket_client.py` — `connect()`에서 `real` 정규화
5. `runtime/bootstrap.py` — `base_url` 전달
6. `.env.example` — 새 표기
7. `docker-compose.yml` — 새 표기 추가
8. `tests/smoke/test_kis_paper_smoke.py` — fallback env read
9. `tests/smoke/test_kis_paper_ai_runtime_smoke.py` — fallback env read
10. `tests/services/ai_agents/test_settings.py` — KIS resolver 테스트 추가

## 변경 금지 확인

- ✅ broker submit semantics — 변경 없음
- ✅ hard guardrail / reconciliation 경계 — 변경 없음
- ✅ admin UI — 변경 없음
- ✅ paper/live safety guard — 완화 없음
- ✅ 실전 주문 실행 — 추가 없음
