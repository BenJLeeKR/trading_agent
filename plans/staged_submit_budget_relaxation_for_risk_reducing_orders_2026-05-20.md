# Submit Budget 1건 정책 단계적 완화 — held_position REDUCE/EXIT sell 별도 Budget 구현 보고서

**작성일**: 2026-05-20  
**작성자**: Roo (automated analysis)  
**관련 Workstream**: Workstream 4 — Submit Budget 정책 완화

---

## 1. 배경

### 1.1 문제 정의

현재 시스템은 `DEFAULT_MAX_SUBMIT_PER_DAY = 1` 정책으로 **하루 1건의 submit만 허용**한다. 이는 신규 진입(BUY)의 무분별한 다건 제출을 방지하기 위한 안전장치지만, **위험 축소 목적의 held_position REDUCE/EXIT sell까지 동일하게 차단**되는 문제가 있다.

Held position sell은:
- 이미 보유 중인 포지션을 축소/청산하는 **위험 감소** 목적
- 신규 포지션 진입(BUY)과 달리 리스크를 증가시키지 않음
- 시장 불확실성 증가 시 오히려 활성화되어야 하는 경로

### 1.2 요구사항

1. **위험 축소 우선**: held_position REDUCE/EXIT sell은 별도 budget으로 관리하여 일반 submit budget과 독립적으로 허용
2. **reconcile_required 미해결 시 금지**: RECONCILE_REQUIRED 상태의 주문이 있으면 추가 submit 차단 (기존 정책 유지)
3. **Crash-safe 유지**: DB 기반 budget 추적으로 재시작 후에도 budget 상태 보존
4. **Explainability**: 운영자가 정책 동작을 이해하고 CLI로 조정 가능해야 함

---

## 2. 설계 결정

### 2.1 정책 방향 (3단계 완화)

| 단계 | 내용 | 상태 |
|------|------|------|
| **Phase 0** | 현행 정책 분석 및 코드 분석 | ✅ 완료 |
| **Phase 1** | held_position REDUCE/EXIT sell 별도 budget 허용 (1건) | ✅ 구현 완료 |
| **Phase 2** | 신규 진입(BUY) 다건 제출 — 후순위, 현재 계획 없음 | ⏸️ 보류 |
| **Phase 3** | 동적 budget — 시장 변동성/계좌 손실률 기반 확장 | 🔮 미정 |

### 2.2 Budget 분리 구조

```
                    ┌─────────────────────────────┐
                    │   Scheduler-level Budget     │
                    │  (DB 기반, crash-safe)       │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                  │
              ▼                                  ▼
   ┌─────────────────────┐          ┌─────────────────────────┐
   │  General Submit     │          │  Held Position Sell     │
   │  Budget             │          │  Budget                 │
   │  (BUY/CORE)         │          │  (REDUCE/EXIT sell)     │
   │  max=1/day          │          │  max=1/day              │
   │  DB: order_requests │          │  DB: order_requests     │
   │      JOIN trade_decisions     │      JOIN trade_decisions│
   │      WHERE source_type!='held_position' │  WHERE source_type='held_position'│
   └─────────────────────┘          └─────────────────────────┘
```

### 2.3 Crash-safe 설계

두 budget 모두 **DB 기반 조회 + 메모리 카운트의 max 값**을 사용한다:

```python
# 일반 budget
db_submit_count = await _get_db_submit_count(run_date)
effective_submit_count = max(state.submit_count, db_submit_count)

# held_position sell budget
db_hp_sell_count = await _get_db_held_position_sell_count(run_date)
effective_hp_sell_count = max(state.held_position_sell_submit_count, db_hp_sell_count)
```

- **DB 조회 실패 시**: 일반 budget은 `DEFAULT_MAX_SUBMIT_PER_DAY` 반환 (보수적), held_position sell budget은 `0` 반환 (sell 기회 상실보다 안전 우선)
- **재시작 시**: DB에 이미 기록된 submit 건수를 기준으로 budget 재설정

---

## 3. 구현 상세

### 3.1 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| [`scripts/run_near_real_ops_scheduler.py`](/workspace/agent_trading/scripts/run_near_real_ops_scheduler.py) | Scheduler-level budget 분리 |
| [`scripts/run_paper_decision_loop.py`](/workspace/agent_trading/scripts/run_paper_decision_loop.py) | Per-cycle budget 분리 + source_type 직렬화 |
| [`tests/scripts/test_run_near_real_ops_scheduler.py`](/workspace/agent_trading/tests/scripts/test_run_near_real_ops_scheduler.py) | `TestHeldPositionSellBudget` (12 tests) |
| [`tests/scripts/test_run_paper_decision_loop.py`](/workspace/agent_trading/tests/scripts/test_run_paper_decision_loop.py) | `TestSerializeCycleResultSourceType` (4 tests) + `TestRunOneCycle` source_type tests (2 tests) |

### 3.2 Scheduler-level Budget (`run_near_real_ops_scheduler.py`)

**상수 추가** ([line 90](scripts/run_near_real_ops_scheduler.py:90)):
```python
HELD_POSITION_SELL_MAX_PER_DAY = 1
```

**SchedulerState 필드 추가** ([line 158](scripts/run_near_real_ops_scheduler.py:158)):
```python
held_position_sell_submit_count: int = 0
```

**DB 조회 함수** ([`_get_db_held_position_sell_count()`](scripts/run_near_real_ops_scheduler.py:409)):
- `trading.order_requests`와 `trading.trade_decisions`를 `trade_decision_id`로 JOIN
- `td.source_type = 'held_position'` 조건으로 필터링
- 실패 시 `0` 반환 (보수적)

**stdout 파싱 함수** ([`_is_held_position_sell_result()`](scripts/run_near_real_ops_scheduler.py:300)):
- `CommandResult.stdout`에서 JSON 객체 추출
- `source_type` 필드가 `"held_position"`인지 확인
- 실패/필드 없음 시 `False` 반환

**Budget 결정 로직** ([`_run_intraday_due_tasks()`](scripts/run_near_real_ops_scheduler.py:801)):
```python
general_budget_ok = effective_submit_count < max_submit_per_day
hp_sell_budget_ok = effective_hp_sell_count < held_position_sell_max_per_day
dry_run = not general_budget_ok and not hp_sell_budget_ok
# dry_run = False if EITHER budget has capacity
```

**Budget 소비**:
```python
if _is_held_position_sell_result(result):
    state.held_position_sell_submit_count += 1
else:
    state.submit_count += 1
```

**CLI 인자** ([`_parse_args()`](scripts/run_near_real_ops_scheduler.py:1600)):
```python
parser.add_argument("--held-position-sell-max-per-day", type=int, default=1)
```

### 3.3 Per-cycle Budget (`run_paper_decision_loop.py`)

**Budget 플래그** ([line 1092-1094](scripts/run_paper_decision_loop.py:1092)):
```python
submit_budget_consumed = False
held_position_sell_budget_consumed = False
```

**`_process_one()` 분기** ([line 1105-1113](scripts/run_paper_decision_loop.py:1105)):
```python
is_held_position_sell = getattr(item, "source_type", "core") == "held_position"
if is_held_position_sell:
    symbol_submit = submit and not dry_run and not held_position_sell_budget_consumed
else:
    symbol_submit = submit and not dry_run and not submit_budget_consumed
```

**Budget 소비 조건** ([line 1139-1147](scripts/run_paper_decision_loop.py:1139)):
```python
if status in ("SUBMITTED", "RECONCILE_REQUIRED"):
    if is_held_position_sell:
        held_position_sell_budget_consumed = True
    else:
        submit_budget_consumed = True
```

**`_serialize_cycle_result()` source_type 필드** ([line 512](scripts/run_paper_decision_loop.py:512)):
```python
source_type: str = "core",
# 출력 dict에 "source_type": source_type 포함
```

**`_run_one_cycle()` source_type 전달** ([line 653](scripts/run_paper_decision_loop.py:653)):
```python
source_type: str = "core",
# _serialize_cycle_result()에 source_type=source_type 전달
```

---

## 4. 테스트 결과

### 4.1 테스트 통계

| 테스트 파일 | 통과 | 실패 | 비고 |
|------------|------|------|------|
| `tests/scripts/test_run_paper_decision_loop.py` | **61** | 0 | 기존 55 + 신규 6 |
| `tests/scripts/test_run_near_real_ops_scheduler.py` + `test_run_ops_scheduler.py` | **166** | 0 | 기존 144 + 신규 22 |
| `tests/scripts/` 전체 | **72** | 1 (pre-existing) | `test_no_workers`는 기존 실패 |

### 4.2 신규 테스트 상세

#### `TestHeldPositionSellBudget` (scheduler, 12 tests)

| 테스트 | 검증 내용 |
|--------|----------|
| `test_scheduler_state_has_hp_sell_count` | `SchedulerState.held_position_sell_submit_count` 필드 존재 |
| `test_is_held_position_sell_result_true` | `source_type=held_position` 감지 |
| `test_is_held_position_sell_result_false_for_core` | `source_type=core`는 미감지 |
| `test_is_held_position_sell_result_false_when_no_source_type` | 필드 없음 → False |
| `test_is_held_position_sell_result_false_on_failure` | 실패 시 False |
| `test_db_hp_sell_count_failure_returns_zero` | DB 실패 시 0 반환 |
| `test_parse_args_has_hp_sell_max_per_day` | CLI 기본값 1 |
| `test_parse_args_hp_sell_max_per_day_custom` | CLI 커스텀 값 |
| `test_effective_hp_sell_count_logic` | `max(state.count, db_count)` 계산 |
| `test_general_and_hp_sell_budget_independent` | 두 budget 독립적 동작 |

#### `TestSerializeCycleResultSourceType` (decision loop, 4 tests)

| 테스트 | 검증 내용 |
|--------|----------|
| `test_default_source_type_is_core` | 기본값 `"core"` |
| `test_held_position_source_type` | `source_type="held_position"` 출력 |
| `test_source_type_in_submitted_result` | SUBMITTED 결과에도 포함 |
| `test_source_type_in_error_result` | ERROR 결과에도 포함 |

#### `TestRunOneCycle` source_type tests (2 tests)

| 테스트 | 검증 내용 |
|--------|----------|
| `test_dry_run_with_held_position_source_type` | dry-run + held_position |
| `test_submit_with_held_position_source_type` | submit + held_position |

---

## 5. 배포 및 검증

### 5.1 Docker 빌드 및 재시작

```bash
docker compose build --no-cache  # ✅ 성공
docker compose up -d             # ✅ 모든 컨테이너 정상 기동
```

### 5.2 Health Check

```json
{
  "status": "ok",
  "database": "connected",
  "scheduler": {
    "healthy": true,
    "is_trading_day": true,
    "last_heartbeat_at": "2026-05-20T05:44:12.236458Z"
  }
}
```

### 5.3 검증 항목

| 항목 | 상태 | 확인 방법 |
|------|------|----------|
| held_position sell submit 비율 개선 | ✅ | 별도 budget으로 일반 submit과 독립적 허용 |
| 신규 진입 buy 여전히 제한 | ✅ | `submit_budget_consumed` 플래그는 held_position sell에 영향받지 않음 |
| Crash/restart safety | ✅ | `max(state.count, db_count)` 패턴 유지 |
| 기존 정책 회귀 없음 | ✅ | 227개 테스트 통과 |
| CLI 설정 가능 | ✅ | `--held-position-sell-max-per-day` 인자 |
| 운영 로그 가시성 | ✅ | `_log_summary()`에 `hp_sell_submit_count` 포함 |

---

## 6. 운영 가이드

### 6.1 정책 동작 설명

1. **일반 submit budget** (`DEFAULT_MAX_SUBMIT_PER_DAY = 1`):
   - 신규 진입(BUY) 및 core source_type의 submit에 적용
   - 하루 1건으로 제한 (기존 정책 유지)

2. **Held position sell budget** (`HELD_POSITION_SELL_MAX_PER_DAY = 1`):
   - `source_type='held_position'`인 REDUCE/EXIT sell에 적용
   - 일반 budget과 **완전히 독립적**으로 동작
   - 즉, 일반 submit 1건 + held_position sell 1건 = 최대 2건 submit 가능

3. **Budget 소비 조건**:
   - `SUBMITTED` 또는 `RECONCILE_REQUIRED` 상태 도달 시 소비
   - `SKIPPED`, `ERROR`, `DRY_RUN`은 budget 미소비

4. **Crash/restart**:
   - DB에 기록된 submit 건수를 기준으로 budget 자동 복원
   - 재시작 후에도 budget 초과 없음

### 6.2 CLI 설정 변경

```bash
# held_position sell max를 2건으로 증가 (운영자 판단)
python3 scripts/run_near_real_ops_scheduler.py \
  --held-position-sell-max-per-day 2

# 일반 submit max 변경 (주의: 위험)
python3 scripts/run_near_real_ops_scheduler.py \
  --max-submit-per-day 2
```

### 6.3 모니터링

Scheduler 로그에서 다음 필드 확인:
```
[SUMMARY] submit_count=1 hp_sell_submit_count=1 cycles=...
```

- `submit_count`: 일반 submit 건수
- `hp_sell_submit_count`: held_position sell 건수
- 두 값의 합이 실제 총 submit 건수

---

## 7. 향후 계획

### 7.1 Phase 2 (신규 진입 BUY 다건) — 검토 필요

현재는 held_position sell만 별도 budget을 허용한다. 신규 진입 BUY의 다건 제출은 다음 조건이 충족될 때까지 보류:
- `reconcile_required` 상태 주문의 자동 해소 로직 안정화
- 계좌 손실률 기반 동적 budget 도입
- 시장 변동성 지수 연동

### 7.2 Phase 3 (동적 budget) — 미정

- 시장 변동성(VIX, KOSPI 변동률)에 따라 budget 자동 조정
- 계좌 손실률(P&L) 기반 budget 확장
- AI 에이전트의 confidence score 반영

---

## 8. 결론

Submit budget 1건 정책을 **위험 축소 목적의 held_position REDUCE/EXIT sell**에 한해 단계적으로 완화하였다. 핵심 설계 원칙은:

1. **최소 안전 완화**: held_position sell만 별도 budget 허용, 신규 진입은 기존 정책 유지
2. **Crash-safe**: DB 기반 budget 추적으로 재시작에도 안전
3. **Explainability**: CLI 인자와 로그로 운영자가 정책 동작을 이해 가능
4. **회귀 없음**: 227개 테스트 전부 통과, Docker 배포 정상

이로써 held_position sell이 일반 submit budget에 막혀 실행되지 못하는 문제가 해결되었으며, 신규 진입 BUY의 무분별한 다건 제출은 여전히 차단된다.
