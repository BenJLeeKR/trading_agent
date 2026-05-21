# recent_events datetime 복원 누락 복구 보고서

## 문제 요약

`ExternalEventEntity`의 datetime 필드(`published_at`, `ingested_at`, `effective_at`, `created_at`)가 JSON 직렬화/역직렬화 과정에서 `str`로 유지되어, AI agent의 `_build_user_prompt()`에서 `strftime()` 호출 시 `AttributeError` 발생.

## 근본 원인 체인

1. [`_serialize_agent_input()`](src/agent_trading/services/decision_orchestrator.py:2368) → [`_dataclass_to_dict()`](src/agent_trading/services/decision_orchestrator.py:2278)가 `datetime` 객체를 변환 없이 dict에 저장
2. [`json.dumps(inp, default=_json_default)`](src/agent_trading/services/decision_orchestrator.py:2081) → `_json_default`에서 `datetime.isoformat()`으로 변환 → **string**
3. 서브프로세스 [`json.loads()`](scripts/run_agent_subprocess.py:337) → `_reconstruct_context()`에서 `ExternalEventEntity(**ev)`로 재구성 → datetime 필드가 **string으로 남음**
4. [`_build_user_prompt()`](src/agent_trading/services/ai_agents/event_interpretation.py:269) → `e.published_at.strftime('%Y-%m-%d')` → **AttributeError**
5. 모든 3개 agent fallback → `summary=""`, `confidence=0`, `decision_type="HOLD"`

## 영향받는 datetime 필드

### ExternalEventEntity ([entities.py:509-536](src/agent_trading/domain/entities.py:509))

| 필드 | 타입 | Required |
|------|------|----------|
| `published_at` | `datetime` | **Required** |
| `ingested_at` | `datetime \| None` | Optional |
| `effective_at` | `datetime \| None` | Optional |
| `created_at` | `datetime \| None` | Optional |

### DecisionContextEntity ([entities.py:155-169](src/agent_trading/domain/entities.py:155))

| 필드 | 타입 | Required |
|------|------|----------|
| `market_timestamp` | `datetime` | **Required** |
| `created_at` | `datetime \| None` | Optional |

## strftime 호출 위치 (3개 agent 모두 동일 패턴)

| Agent | 파일 | 라인 | 접근 필드 |
|-------|------|------|-----------|
| **EI** | [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:269) | 269 | `e.published_at.strftime('%Y-%m-%d')` |
| **EI** | [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:281) | 281 | `e.ingested_at` (stale check) |
| **AR** | [`ai_risk.py`](src/agent_trading/services/ai_agents/ai_risk.py:473) | 473 | `e.published_at.strftime('%Y-%m-%d')` |
| **AR** | [`ai_risk.py`](src/agent_trading/services/ai_agents/ai_risk.py:483) | 483 | `e.ingested_at` (stale check) |
| **FDC** | [`final_decision_composer.py`](src/agent_trading/services/ai_agents/final_decision_composer.py:441) | 441 | `e.published_at.strftime('%Y-%m-%d')` |
| **FDC** | [`final_decision_composer.py`](src/agent_trading/services/ai_agents/final_decision_composer.py:451) | 451 | `e.ingested_at` (stale check) |

## 수정 내용

### 파일: [`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py)

#### 1. `_reconstruct_external_event()` 함수 추가 (라인 156-183)

기존 snapshot reconstructor(`_reconstruct_position_snapshot`, `_reconstruct_cash_balance_snapshot`, `_reconstruct_risk_limit_snapshot`)와 동일한 패턴으로 `_safe_datetime()`과 `_safe_uuid()`를 사용하여 모든 datetime/UUID 필드를 복원:

- `published_at` → `_safe_datetime()`
- `ingested_at` → `_safe_datetime()`
- `effective_at` → `_safe_datetime()`
- `created_at` → `_safe_datetime()`
- `event_id` → `_safe_uuid()`
- `supersedes_event_id` → `_safe_uuid()`

#### 2. `_reconstruct_decision_context()` 함수 추가 (라인 186-208)

`DecisionContextEntity`의 datetime/UUID 필드 복원:

- `market_timestamp` → `_safe_datetime()`
- `created_at` → `_safe_datetime()`
- 모든 UUID 필드 → `_safe_uuid()`

#### 3. `_reconstruct_context()` 수정 (라인 316-327)

- `ExternalEventEntity(**ev)` → `_reconstruct_external_event(ev)`
- `DecisionContextEntity(**decision_context_raw)` → `_reconstruct_decision_context(decision_context_raw)`

## 검증

- Python import 테스트: 모든 함수 정상 import 및 동작 확인
- 단위 테스트: `_reconstruct_external_event()`로 생성된 객체의 `published_at.strftime('%Y-%m-%d')` 정상 동작 확인
- None/passthrough 처리 검증 완료
- 기존 pytest 60/61 통과 (1개 실패는 기존 코드 문제, 우리 변경과 무관)
- Docker build (`ops-scheduler`) 성공

## 배포 후 확인 사항

1. `docker compose up -d ops-scheduler`로 재시작
2. 로그에서 `strftime`/`AttributeError` 관련 에러가 사라졌는지 확인
3. EI/AR/FDC agent output에서 `summary`가 정상적으로 생성되는지 확인
