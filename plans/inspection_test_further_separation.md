# test_inspection.py 추가 분리 계획

> **분리 대상**: [`TestAgentRuns`](../tests/api/test_inspection.py:428) → [`tests/api/test_agent_runs.py`](../tests/api/test_agent_runs.py)
> **분리 범위**: list-oriented tests 5개만 이동. `TestAgentRunsDetail`(detail endpoint)는 이번 턴에서 제외.

## 1. 4개 후보 분석표

| 클래스 | Lines | Tests | Fixture | Helper | 종속성 | 분리 난이도 |
|--------|-------|-------|---------|--------|--------|------------|
| [`TestBrokerOrders`](../tests/api/test_inspection.py:398) | 398-425 (28) | 3 | `client` | 없음 | 없음 | ⭐ 매우 쉬움 |
| [`TestAgentRuns`](../tests/api/test_inspection.py:428) | 428-487 (60) | **5** | `client` + `empty_client` | 없음 | 없음 | ⭐ 매우 쉬움 |
| [`TestGuardrailEvaluations`](../tests/api/test_inspection.py:525) | 525-585 (61) | 4 | `client` | 없음 | `/agent-runs` seeded data 필요 | ⭐⭐ 쉬움 |
| [`TestRiskLimitSnapshots`](../tests/api/test_inspection.py:588) | 588-647 (60) | 4 | `client` | `_get_account_id` (로컬) | 로컬 helper 이동 필요 | ⭐⭐ 보통 |

### 상세 분석

#### `TestBrokerOrders` (3 tests)
- `test_get_broker_orders(client)` — `/orders/{id}/broker-orders` 200 + field 검증
- `test_get_broker_orders_not_found(client)` — 404
- `test_get_broker_orders_invalid_uuid(client)` — 400
- **장점**: 가장 단순, helper 불필요, 독립적
- **단점**: 3 tests만 분리 (분리 효과 작음). `TestOrders`는 `test_inspection.py`에 잔류.

#### `TestAgentRuns` (5 tests) ← **선정**
- `test_list_agent_runs_empty(empty_client)` — `/agent-runs` 200 + `[]`
- `test_list_agent_runs(client)` — 200 + 3개 + DESC ordering
- `test_list_agent_runs_filter_by_decision_context(client)` — 200 + filter 정확성
- `test_list_agent_runs_filter_invalid_uuid(client)` — 400
- `test_list_agent_runs_filter_no_match(client)` — 200 + `[]`
- **장점**: 5 tests로 분리 효과 큼. `client` + `empty_client` 모두 사용 (import 패턴 2가지 시연). helper 불필요. domain이 명확히 분리됨.

#### `TestGuardrailEvaluations` (4 tests)
- `/agent-runs` seeded data에 암시적 의존 (fixture level에서 해결됨)
- `client` fixture로 seeded repos 사용하므로 문제 없음
- **단점**: Guardrail evaluation은 agent run 결과물에 의존적이므로 개념적으로 완전 독립적이지는 않음

#### `TestRiskLimitSnapshots` (4 tests)
- 로컬 helper `_get_account_id(self, client)` 존재 (lines 591-601)
- 분리 시 helper를 module-level로 승격 필요 (`test_performance_benchmark_history.py` 패턴과 동일)
- **단점**: helper 이동 필요 (변경 범위 증가)

## 2. 선정: `TestAgentRuns` → `tests/api/test_agent_runs.py`

### 선택 이유
1. **5 tests** — 분리 효과가 가장 큼 (다른 후보는 3-4 tests)
2. **helper 불필요** — 순수 `client`/`empty_client` fixture만 사용. `self` helper 제거 없음. 단순 클래스 이동만 있음.
3. **fixture 2종 사용** — `from tests.api.conftest import client  # noqa: F401` + `from tests.api.conftest import empty_client  # noqa: F401` (기존 분리 파일과 동일한 import 스타일)
4. **독립적 domain** — agent run은 다른 inspection endpoint와 개념적 결합 없음
5. **이전 분리와 동일한 패턴** — `test_performance_metrics.py`, `test_performance_benchmark_history.py` 분리와 완전히 동일한 접근

### `TestAgentRunsDetail` 유지 이유 (이번 턴에서 제외)
- `TestAgentRunsDetail`(3 tests, lines 490-522)는 **최소 분리 원칙**에 따라 이번 턴에서 제외.
- 같은 `/agent-runs` resource를 검증하지만, **list/filter 계열**과 **detail endpoint**(`GET /agent-runs/{id}`)는 다른 endpoint.
- 이번 턴은 list-oriented tests만 이동하고, detail endpoint는 `test_inspection.py`에 잔류.
- 향후 필요 시 `TestAgentRunsDetail`도 동일한 패턴으로 `test_agent_runs.py`에 합류 가능.

### 파일 구조 (변경 전 → 후)

**변경 전 `test_inspection.py`**: 13 classes, 53 tests
```
TestOrders (6) / TestAuditLogs (3) / TestReconciliation (7) / TestAccounts (5)
/ TestInstruments (3) / TestPositions (7) / TestClients (3) / TestBrokerOrders (3)
/ TestAgentRuns (5) / TestAgentRunsDetail (3) / TestGuardrailEvaluations (4)
/ TestRiskLimitSnapshots (4)
```

**변경 후 `test_inspection.py`**: 12 classes, 48 tests
→ inspection core + detail/resource-specific tests 위주. agent-runs list tests는 전용 파일로 이동.
```
TestOrders (6) / TestAuditLogs (3) / TestReconciliation (7) / TestAccounts (5)
/ TestInstruments (3) / TestPositions (7) / TestClients (3) / TestBrokerOrders (3)
/ TestAgentRunsDetail (3) / TestGuardrailEvaluations (4) / TestRiskLimitSnapshots (4)
```

**신규 `tests/api/test_agent_runs.py`**: 1 class, 5 tests
```
TestAgentRuns (5)
```

### 이번 분리 범위 기준 전체 테스트 분포

| 파일 | Tests |
|------|-------|
| `tests/api/test_inspection.py` | 48 |
| `tests/api/test_performance_metrics.py` | 3 |
| `tests/api/test_performance_benchmark_history.py` | 12 |
| `tests/api/test_agent_runs.py` (신규) | 5 |
| **Total (이번 분리 범위 기준)** | **68** |

> 분리 전: `test_inspection.py` 53 + `test_performance_metrics.py` 3 + `test_performance_benchmark_history.py` 12 = 68
> 분리 후: `test_inspection.py` 48 + `test_agent_runs.py` 5 + `test_performance_metrics.py` 3 + `test_performance_benchmark_history.py` 12 = 68

## 3. 신규 파일: `tests/api/test_agent_runs.py`

### Import 스타일 (기존 분리 파일과 일관성 유지)

```python
from tests.api.conftest import client  # noqa: F401
from tests.api.conftest import empty_client  # noqa: F401
```

### 전체 내용 (모든 assertion은 원본과 완전 동일)

```python
"""API-level contract tests for ``GET /agent-runs``.

Validates (5 tests):

1. **Empty result** — ``empty_client`` → 200 + ``[]``
2. **Seeded data** — ``client`` → 200 + 3 runs + DESC ``started_at`` ordering
3. **Filter by decision_context_id** — 200 + all results match filter
4. **Invalid decision_context_id UUID** — 400
5. **No-match decision_context_id** — 200 + ``[]``
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import client  # noqa: F401
from tests.api.conftest import empty_client  # noqa: F401


class TestAgentRuns:
    """``GET /agent-runs`` — agent run 목록 조회 API 계약 검증.

    별도 helper 없이 ``client``(seeded repos)와 ``empty_client``(빈 repos)
    fixture로 seeded data 존재 여부에 따른 동작을 검증. ``self`` helper
    제거 없이 단순 클래스 이동만 수행.
    """

    def test_list_agent_runs_empty(self, empty_client: TestClient) -> None:
        """``GET /agent-runs`` returns empty list when no runs exist."""
        ...  # (기존 assertion 그대로)

    def test_list_agent_runs(self, client: TestClient) -> None:
        """``GET /agent-runs`` returns seeded agent runs ordered by started_at DESC."""
        ...  # (기존 assertion 그대로)

    def test_list_agent_runs_filter_by_decision_context(
        self, client: TestClient
    ) -> None:
        """``GET /agent-runs?decision_context_id=...`` filters correctly."""
        ...  # (기존 assertion 그대로)

    def test_list_agent_runs_filter_invalid_uuid(
        self, client: TestClient
    ) -> None:
        """``GET /agent-runs?decision_context_id=...`` returns 400 for invalid UUID."""
        ...  # (기존 assertion 그대로)

    def test_list_agent_runs_filter_no_match(
        self, client: TestClient
    ) -> None:
        """``GET /agent-runs?decision_context_id=...`` returns empty for unknown UUID."""
        ...  # (기존 assertion 그대로)
```

> **중요**: 모든 assertion은 원본과 완전 동일. helper 호출 경로 변경 없음. 단순 클래스 이동만 수행.

## 4. `test_inspection.py` 변경 사항

- `TestAgentRuns` 클래스 (lines 428-487, 60 lines) 제거
- docstring: 변경 불필요 (이미 `GET /agent-runs` 포함)
- imports: 변경 불필요 (`client`는 다른 클래스에서도 사용 중)

## 5. 실행 단계

| 단계 | 작업 | 상세 |
|------|------|------|
| 1 | `test_agent_runs.py` 생성 | 위 내용대로 5 tests + docstring + imports |
| 2 | `test_inspection.py`에서 `TestAgentRuns` 제거 | lines 428-487 (빈 줄 포함) |
| 3 | docstring/imports 정합성 확인 | 변경 불필요 확인 |
| 4 | 검증 명령어 #1 | `python3 -m pytest tests/api/test_agent_runs.py -q` → 5 passed |
| 5 | 검증 명령어 #2 | `python3 -m pytest tests/api/test_inspection.py -q` → 48 passed |
| 6 | 검증 명령어 #3 | `python3 -m pytest tests/api/test_agent_runs.py tests/api/test_inspection.py tests/api/test_performance_metrics.py tests/api/test_performance_benchmark_history.py -q` → 68 passed |

## 6. 제약 조건 점검

| 조건 | 충족 여부 | 근거 |
|------|-----------|------|
| 테스트 의미 변경 금지 | ✅ | Assertion/로직 완전 동일 |
| endpoint 구현 변경 금지 | ✅ | routes 파일 수정 없음 |
| schema 변경 금지 | ✅ | schemas.py 수정 없음 |
| service 변경 금지 | ✅ | services 파일 수정 없음 |
| DB migration 금지 | ✅ | DB 변경 없음 |
| admin UI 변경 금지 | ✅ | admin_ui 변경 없음 |
| file split only | ✅ | 60 line 제거 + ~95 line 생성 |
| 기존 테스트명 / assertion / fixture 사용 방식 유지 | ✅ | 모두 원본 그대로 |
| TestAgentRunsDetail 건드리지 않음 | ✅ | test_inspection.py에 잔류 |
| conftest 공용화 하지 않음 | ✅ | 로컬 import 유지 |
| helper 호출 경로 변경 없음 | ✅ | TestAgentRuns는 self helper가 없었음. 단순 클래스 이동만 수행. |
