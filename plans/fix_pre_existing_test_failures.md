# Pre-existing Test Failures 정상화

## 문제 분석

### 문제 1: 14 errors — `test_bootstrap.py`의 `ensure_schema` 누락

**원인**: [`src/agent_trading/runtime/bootstrap.py`](src/agent_trading/runtime/bootstrap.py:375)의 `build_postgres_runtime()` 함수가 `ensure_schema()`를 호출하지만, 해당 함수가 import되어 있지 않음.

```
375:    await ensure_schema(config)  # NameError: name 'ensure_schema' is not defined
```

현재 import는 `run_all_migrations`만 가져옴:
```python
from agent_trading.db.migrations.run import run_all_migrations
```

테스트에서 monkeypatch 경로 `agent_trading.runtime.bootstrap.ensure_schema`는 올바름 — 문제는 소스 코드의 import 누락.

**해결책**: [`runtime/bootstrap.py`](src/agent_trading/runtime/bootstrap.py:15) import 줄에 `ensure_schema` 추가:
```python
from agent_trading.db.migrations.run import ensure_schema, run_all_migrations
```

### 문제 2: 2 failed — `test_settings.py`의 `kis_ws_url` env 미삭제

**원인**: 시스템 환경에 `KIS_WS_URL=ws://ops.koreainvestment.com:31000`가 설정되어 있음. 두 테스트 메서드 (`test_fallback_names`, `test_all_missing`)가 `KIS_BASE_URL`은 삭제하지만 `KIS_WS_URL`은 삭제하지 않아 `settings.kis_ws_url`이 `""` 대신 실제 env 값을 반환함.

설정 코드 (`settings.py:220`):
```python
kis_ws_url: str = field(default_factory=lambda: os.getenv("KIS_WS_URL", ""))
```

**해결책**: 두 테스트 메서드에 `monkeypatch.delenv("KIS_WS_URL", raising=False)` 추가.

## 변경 파일 목록

| 파일 | 변경 |
|------|------|
| [`src/agent_trading/runtime/bootstrap.py`](src/agent_trading/runtime/bootstrap.py:15) | `ensure_schema` import 추가 |
| [`tests/services/ai_agents/test_settings.py`](tests/services/ai_agents/test_settings.py:361) | `test_fallback_names`에 `KIS_WS_URL` 삭제 추가 |
| [`tests/services/ai_agents/test_settings.py`](tests/services/ai_agents/test_settings.py:378) | `test_all_missing`에 `KIS_WS_URL` 삭제 추가 |

## 검증 계획

1. `pytest tests/services/ai_agents/test_settings.py::TestAppSettingsKisFields::test_fallback_names -v` → PASS
2. `pytest tests/services/ai_agents/test_settings.py::TestAppSettingsKisFields::test_all_missing -v` → PASS
3. `pytest tests/services/ai_agents/test_bootstrap.py -v` → 14 errors → 0 errors
4. `pytest tests/services/ -v --tb=short` → 2 failed → 0 failed, 14 errors → 0 errors
