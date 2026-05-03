# LLM_PROVIDER 기반 Env Resolver 일반화

## 현재 문제

[`settings.py`](src/agent_trading/config/settings.py:25-38)의 내부 필드는 provider-agnostic하지만, `default_factory`가 `DEEPSEEK_*` env var로 하드코딩되어 있음:

```python
provider_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
provider_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
provider_model_id: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL_ID", "deepseek-chat"))
```

`LLM_PROVIDER=openai`로 설정해도 여전히 `DEEPSEEK_*` env var를 읽음.

## 설계

### Provider Env Map

```python
_SUPPORTED_PROVIDERS = frozenset({"deepseek", "openai"})

_PROVIDER_ENV_MAP: dict[str, dict[str, str]] = {
    "deepseek": {
        "api_key": "DEEPSEEK_API_KEY",
        "base_url": "DEEPSEEK_BASE_URL",
        "model_id": "DEEPSEEK_MODEL_ID",
        "timeout": "DEEPSEEK_TIMEOUT_SECONDS",
    },
    "openai": {
        "api_key": "OPENAI_API_KEY",
        "base_url": "OPENAI_BASE_URL",
        "model_id": "OPENAI_MODEL_ID",
        "timeout": "OPENAI_TIMEOUT_SECONDS",
    },
}

_PROVIDER_BASE_URL_DEFAULTS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
}

_PROVIDER_MODEL_ID_DEFAULTS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o",
}
```

### Resolver 함수

4개의 개별 resolver 함수 (`settings.py` 모듈 레벨):

| 함수 | 반환 | 동작 |
|------|------|------|
| `_resolve_llm_provider()` | `str` | `LLM_PROVIDER` 값을 읽고 소문자 변환 + trim. 지원되지 않으면 `""` 반환 |
| `_resolve_provider_api_key()` | `str` | `_resolve_llm_provider()` 결과에 따라 `DEEPSEEK_API_KEY` 또는 `OPENAI_API_KEY` 읽음. 없으면 `""` |
| `_resolve_provider_base_url()` | `str` | provider-specific env var. 없으면 `_PROVIDER_BASE_URL_DEFAULTS` 사용 |
| `_resolve_provider_model_id()` | `str` | provider-specific env var. 없으면 `_PROVIDER_MODEL_ID_DEFAULTS` 사용 |
| `_resolve_provider_timeout()` | `int` | provider-specific env var. 없으면 `30` |

### 지원되지 않는 provider 처리

`_resolve_llm_provider()`가 `""`를 반환하면, 모든 provider resolver가 빈 문자열/기본값을 반환 → `_build_provider_agent()`의 triple validation에서 `None` → stub fallback.

### AppSettings 변경

```python
@dataclass(slots=True, frozen=True)
class AppSettings:
    ...
    llm_provider: str = field(default_factory=_resolve_llm_provider)
    provider_api_key: str = field(default_factory=_resolve_provider_api_key)
    provider_base_url: str = field(default_factory=_resolve_provider_base_url)
    provider_model_id: str = field(default_factory=_resolve_provider_model_id)
    provider_timeout_seconds: int = field(default_factory=_resolve_provider_timeout)
```

### 변경 영향도

| 파일 | 변경 | 영향 |
|------|------|------|
| `settings.py` | `DEEPSEEK_*` 하드코딩 → `_resolve_*()` 함수 | 스키마 변경 없음, 내부 필드명 유지 |
| `.env.example` | `OPENAI_*` 주석 예시 추가 | 문서 변경 |
| `bootstrap.py` | **변경 없음** — 이미 `settings.provider_*` 사용 | 0 |
| `test_bootstrap.py` | `LLM_PROVIDER=openai` 분기 테스트 추가 | 확장 |
| `test_settings.py` (신규) | resolver 단위 테스트 | 신규 |

### bootstrap.py는 왜 변경이 필요 없는가

`_build_provider_agent()`는 이미 `settings.provider_api_key`, `settings.provider_base_url` 등 provider-agnostic 필드를 사용. 설정이 어디서 왔는지(DeepSeek/OpenAI)는 신경 쓰지 않음. `AppSettings` 생성 시점에 resolver가 올바른 env var를 읽어주므로 `bootstrap.py`는 변경 불필요.

### 테스트 케이스

**settings resolver 테스트** (`tests/services/ai_agents/test_settings.py` 또는 기존 `test_bootstrap.py`에 통합):

| # | 시나리오 | LLM_PROVIDER | DEEPSEEK_* | OPENAI_* | 기대 결과 |
|---|----------|-------------|------------|----------|----------|
| 1 | deepseek + complete | deepseek | 모두 설정 | - | api_key=sk-ds, base_url=ds.url |
| 2 | openai + complete | openai | - | 모두 설정 | api_key=sk-oa, base_url=oa.url |
| 3 | deepseek + missing key | deepseek | key="" | - | api_key="" (stub fallback) |
| 4 | openai + missing key | openai | - | key="" | api_key="" (stub fallback) |
| 5 | unsupported provider | claude | - | - | api_key="" (stub fallback) |
| 6 | deepseek + default base_url | deepseek | key만 설정 | - | base_url=https://api.deepseek.com |

**bootstrap wiring 테스트** (기존 `test_bootstrap.py` 확장):

| # | 시나리오 | LLM_PROVIDER | 환경 | 기대 결과 |
|---|----------|-------------|------|----------|
| 7 | deepseek → real agent | deepseek | DS env 완전 | `EventInterpretationAgent` |
| 8 | openai → real agent | openai | OA env 완전 | `EventInterpretationAgent` |
| 9 | deepseek → stub | deepseek | DS key="" | agent None |
| 10 | openai → stub | openai | OA key="" | agent None |
| 11 | unsupported → stub | claude | - | agent None |

## 실행 순서

1. `settings.py`에 `_PROVIDER_ENV_MAP`, `_SUPPORTED_PROVIDERS`, `_PROVIDER_BASE_URL_DEFAULTS`, `_PROVIDER_MODEL_ID_DEFAULTS` 상수 추가
2. `settings.py`에 5개 resolver 함수 추가 (`_resolve_llm_provider`, `_resolve_provider_api_key`, `_resolve_provider_base_url`, `_resolve_provider_model_id`, `_resolve_provider_timeout`)
3. `AppSettings` 필드의 `default_factory`를 resolver 함수로 교체
4. `settings.py`에 `import logging` + `logger = logging.getLogger(__name__)` 추가
5. `.env.example`에 `OPENAI_*` 주석 예시 추가
6. `test_settings.py` 신규 생성 — resolver 단위 테스트 6개
7. `test_bootstrap.py`에 `LLM_PROVIDER=openai` 분기 테스트 5개 추가
8. 전체 테스트 실행
