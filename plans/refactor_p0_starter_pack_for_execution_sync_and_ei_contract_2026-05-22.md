# 보고서: 리팩토링 P0 Starter Pack — 주문 실행 / KIS Sync / EI Output Contract

## 1. 이번 턴의 리팩토링 범위

### 배경
시스템 전체를 갈아엎는 전면 재설계가 아닌, 기존 큰 설계는 유지하되 장애와 진실 훼손이 반복되는 핵심 경계를 정리하는 1차 리팩토링.

### 3대 목표 영역

| 영역 | Backlog 항목 | 목표 |
|------|-------------|------|
| A. KIS Sync Truth 보호 | SYNC-001, SYNC-002 | zero-out 금지, fetch_status 상태 모델 도입 |
| B. 주문 실행 경계 가시화 | EXE-002 | symbol별 PHASE_TRACE 로깅 표준화 |
| C. EI Output Contract 명시화 | EI-001, EI-003 | degraded/interpretation_incomplete 상태 분리 |

## 2. Zero-out / Partial Truth 변경 내용

### 2.1 PositionSnapshotEntity / CashBalanceSnapshotEntity에 fetch_status 필드 추가

**파일:** [`src/agent_trading/domain/entities.py`](src/agent_trading/domain/entities.py)

```python
# PositionSnapshotEntity
fetch_status: str = "success"
"""'success' | 'partial' | 'stale' | 'fetch_failed' | 'zeroed_out'"""

# CashBalanceSnapshotEntity
fetch_status: str = "success"
"""'success' | 'stale' | 'fetch_failed'"""
```

### 2.2 Postgres INSERT 쿼리에 fetch_status 컬럼 추가

**파일:**
- [`src/agent_trading/repositories/postgres/position_snapshots.py`](src/agent_trading/repositories/postgres/position_snapshots.py)
- [`src/agent_trading/repositories/postgres/cash_balance_snapshots.py`](src/agent_trading/repositories/postgres/cash_balance_snapshots.py)

`VARCHAR(20) NOT NULL DEFAULT 'success'` — 기존 row와 하위 호환 유지.

### 2.3 Zero-out Gate 추가

**파일:** [`src/agent_trading/services/kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py)

KIS API 응답 유효성 확인 gate 추가:
- `had_actual_positions` 또는 `had_cash_response`가 있을 때만 zero-out 실행
- fetch 완전 실패 시 `SKIP_ZERO_OUT` 로그 출력, zero-out 생략

### 2.4 FetchedSnapshot에 fetch_success 필드 추가

**파일:** [`src/agent_trading/services/snapshot_sync.py`](src/agent_trading/services/snapshot_sync.py) / [`src/agent_trading/brokers/koreainvestment/snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py)

## 3. Execution Phase Trace 변경 내용

### 3.1 PHASE_TRACE 로깅 표준화

**파일:** [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py)

`assemble_and_submit()` 메서드의 주요 phase에 key-value 로깅 추가:

| Phase ID | 설명 |
|----------|------|
| `assemble_start` / `assemble_done` | 어셈블 시작/완료 |
| `sizing_start` / `sizing_done` / `sizing_skip_held_position` | 사이징 |
| `sell_guard_start` / `sell_guard_done` | 매도 가드 |
| `validate_start` / `validate_skip_hold` / `validate_skip_watch` / `validate_done` | 검증 |
| `order_create_start` / `order_create_done` | 주문 생성 |
| `stale_snapshot_guard_start` / `stale_snapshot_guard_blocked` / `stale_snapshot_guard_passed` | Stale snapshot 가드 |
| `submit_start` / `submit_done` | 제출 |

## 4. EI Output Contract 1차 변경 내용

### 4.1 AggregateEventView에 degraded 필드 추가

**파일:** [`src/agent_trading/services/ai_agents/schemas.py`](src/agent_trading/services/ai_agents/schemas.py)

```python
interpretation_incomplete: bool = False
degraded_reason: str | None = None  # 'timeout' | 'provider_error' | 'self_contradiction_corrected' | None
```

`EventInterpretationOutput.is_degraded` property 추가.

### 4.2 Self-contradiction guard 명시화

**파일:** [`src/agent_trading/services/ai_agents/event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py)

LLM이 input events > 0임에도 event_count=0 반환 시:
- `interpretation_incomplete=True`
- `degraded_reason="self_contradiction_corrected"`

### 4.3 Timeout/fallback 시 degraded 플래그 설정

**파일:** [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py)

- TimeoutError → `degraded_reason="timeout"`
- Exception fallback → `degraded_reason="provider_error"`

### 4.4 Subprocess FDC skip 시 degraded 플래그

**파일:** [`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py)

## 5. 수정된 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|---------|------|
| [`domain/entities.py`](src/agent_trading/domain/entities.py) | 필드 추가 | `fetch_status` 2개 entity에 추가 |
| [`postgres/position_snapshots.py`](src/agent_trading/repositories/postgres/position_snapshots.py) | SQL 수정 | INSERT에 `fetch_status` 컬럼 |
| [`postgres/cash_balance_snapshots.py`](src/agent_trading/repositories/postgres/cash_balance_snapshots.py) | SQL 수정 | INSERT에 `fetch_status` 컬럼 |
| [`services/snapshot_sync.py`](src/agent_trading/services/snapshot_sync.py) | 필드 추가 | `FetchedSnapshot.fetch_success` |
| [`brokers/koreainvestment/snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py) | 로직 추가 | `fetch_success` 설정 |
| [`services/kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py) | gate 추가 | zero-out 방지 gate + fetch_status 설정 |
| [`services/ai_agents/schemas.py`](src/agent_trading/services/ai_agents/schemas.py) | 필드 추가 | `interpretation_incomplete`, `degraded_reason`, `is_degraded` |
| [`services/ai_agents/event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py) | guard 강화 | self-contradiction에 degraded 플래그 |
| [`services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | 플래그+로깅 | EI degraded 플래그 + PHASE_TRACE 로깅 |
| [`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py) | 플래그 | FDC skip degraded 플래그 |
| [`tests/services/test_kis_snapshot_sync.py`](tests/services/test_kis_snapshot_sync.py) | 신규 테스트 | 3개 추가 |
| [`tests/services/ai_agents/test_event_interpretation.py`](tests/services/ai_agents/test_event_interpretation.py) | 신규 테스트 | 3개 추가 + 회귀 버그 수정 |
| [`tests/services/test_decision_orchestrator.py`](tests/services/test_decision_orchestrator.py) | 신규 테스트 | 1개 추가 |

## 6. 테스트 결과

| 테스트 스위트 | 결과 |
|--------------|:----:|
| `test_kis_snapshot_sync.py` | ✅ Passed (신규 3 포함) |
| `test_event_interpretation.py` | ✅ Passed (신규 3 포함) |
| `test_decision_orchestrator.py` | ✅ Passed (신규 1 포함) |
| 기존 서비스 테스트 | ✅ 회귀 없음 |
| 프론트엔드 전체 | ✅ 259 passed |

## 7. 배포 검증 결과

- Docker API 컨테이너 재빌드 완료
- 컨테이너 재기동 완료
- `/health` endpoint: `status: "ok"`, `database: "connected"`

## 8. 다음 리팩토링 단계 제안

| 우선순위 | 영역 | 내용 |
|---------|------|------|
| P1 | Stale Guard (SYNC-004) | `fetch_status`를 stale guard에서 참조하여 stale snapshot 보호 |
| P1 | Phase Trace 구조화 (EXE-003) | `SubmitResult`에 `symbol_phases` 필드 도입 |
| P1 | EI Summary 규칙 정리 (EI-004) | `_build_ei_summary()` 계약 기반 정리 |
| P1 | Quote Resolution Hang (EXE-001) | quote_resolution이 held_position sell의 order_request 생성을 막는 추적 |
| P2 | Snapshot Cadence 분리 (SYNC-003) | scheduler timeout과 독립적인 snapshot cadence |
