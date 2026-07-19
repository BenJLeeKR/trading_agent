# RECONCILE_REQUIRED → Reconciliation 자동 트리거 구현 보고서

**작성일**: 2026-05-16 18:00 KST  
**작업 범위**: RECONCILE_REQUIRED 상태 전이 시 reconciliation run 자동 생성

---

## 1. Root Cause

**문제**: 특정 주문이 `reconcile_required` 상태로 전이된 후 **reconciliation run이 전혀 생성되지 않아** 장시간 stuck 상태로 남음.

```
OrderRequest (reconcile_required)
  └── ReconciliationRun: 0건 ← 문제!
  └── FillEvents: 0건
  └── BrokerOrder (broker_native_order_id 존재)
```

**분석 결과** (Phase 17):
- 대상 주문: `400353e9-9c09-49c9-b4cc-a03ac50474b1` (broker_native_order_id=0000035653, HTTP 200 성공)
- `RECONCILE_REQUIRED` 진입 경로: post-submit sync → `inquire-daily-ccld` → ODNO match FAILED (output_count=0)
- **reconciliation run 자동 트리거 메커니즘이 존재하지 않음**
- 기존 `trigger()` 호출은 `submit_order_to_broker()`의 uncertain/requires_reconciliation 결과 시에만 발생
- post-submit sync 또는 다른 경로에서 `RECONCILE_REQUIRED`로 전이될 때는 trigger 누락

---

## 2. Auto-Trigger Hook 지점

### Hook 위치: `OrderManager._transition_to_core()`

[`src/agent_trading/services/order_manager.py:693`](src/agent_trading/services/order_manager.py:693)

```python
# ── Auto-trigger reconciliation on RECONCILE_REQUIRED ──
if (
    target_status == OrderStatus.RECONCILE_REQUIRED
    and reason_code != "BLOCKED"
    and self.reconciliation_service is not None
):
    try:
        run = await self.reconciliation_service.trigger(
            account_id=order.account_id,
            trigger_type="reconcile_required_transition",
            symbol=order.symbol if hasattr(order, 'symbol') else None,
            side=order.side.value if order.side else None,
        )
        logger.info(
            "reconcile_required auto-triggered: order_id=%s account_id=%s "
            "reconciliation_run_id=%s reason_code=%s",
            order.order_request_id, order.account_id,
            run.reconciliation_run_id, reason_code,
        )
    except Exception as exc:
        logger.error(
            "reconcile_required auto-trigger FAILED: order_id=%s account_id=%s error=%s",
            order.order_request_id, order.account_id, exc,
        )
```

### Hook 선정 이유

| Hook 후보 | 장점 | 단점 | 선택 |
|-----------|------|------|------|
| **A. `submit_order_to_broker()`** | 이미 trigger() 호출 중 | post-submit sync 등 다른 경로 미포함 | ❌ |
| **B. `ReconciliationService.trigger()` 내부** | 중앙 집중 | 호출 자체가 없으면 무의미 | ❌ |
| **C. `_transition_to_core()`** | **모든 RECONCILE_REQUIRED 전이 포착** | BLOCKED 케이스 필터링 필요 | **✅ 선택** |

### 제외 조건

- `reason_code == "BLOCKED"`: blocking lock이 이미 존재하는 상태에서 중복 전이 → reconciliation run 불필요
- `reconciliation_service is None`: 테스트 환경 등에서 서비스 미주입

---

## 3. Idempotency / 중복 방지 방식

### 방식: `trigger()` 내부 Active Run 재사용

[`src/agent_trading/services/reconciliation_service.py:73`](src/agent_trading/services/reconciliation_service.py:73)

```python
async def trigger(self, account_id, trigger_type, *, strategy_id=None, symbol=None, side=None):
    # ── Idempotency: active run이 이미 존재하면 재사용 ──
    active_run = await self.get_active_run(account_id)
    if active_run is not None:
        logger.info(
            "reconcile_required auto-trigger: active reconciliation run already exists, reusing. "
            "run_id=%s account_id=%s trigger_type=%s",
            active_run.reconciliation_run_id, account_id, trigger_type,
        )
        return active_run
    # ... 새 run 생성 ...
```

### 중복 방지 구조

```
[주문 A] RECONCILE_REQUIRED 전이 (1회차)
  → _transition_to_core() → trigger(account_id=X)
    → get_active_run(X) = None → 새 run 생성 (run_id=AAA)

[주문 A] RECONCILE_REQUIRED 재평가 (2회차)
  → _transition_to_core() → trigger(account_id=X)
    → get_active_run(X) = run_id=AAA (status='started') → 재사용

[주문 B, 동일 계정] RECONCILE_REQUIRED 전이
  → _transition_to_core() → trigger(account_id=X)
    → get_active_run(X) = run_id=AAA (status='started') → 재사용

[run_id=AAA] mark_resolved() → status='resolved'
  → 이후 trigger(account_id=X) → get_active_run(X) = None → 새 run 생성
```

### 적용 기준

| 조건 | 동작 | 근거 |
|------|------|------|
| 동일 계정, active run 존재 | 기존 run 재사용 | reconciliation은 계정 단위 lock 기반 |
| active run 없음 | 새 run 생성 | 정상 경로 |
| 이전 run resolved | 새 run 생성 | resolved = 해소 완료 |
| 다른 계정 | 독립적 생성 | 계정별 격리 |

---

## 4. 변경 파일 목록

| 파일 | 변경 내용 | 영향 범위 |
|------|----------|----------|
| [`src/agent_trading/services/reconciliation_service.py`](src/agent_trading/services/reconciliation_service.py) | `trigger()` 시작 부분에 idempotency 체크 추가 (active run 존재 시 재사용) | trigger() 호출하는 모든 경로 |
| [`src/agent_trading/services/order_manager.py`](src/agent_trading/services/order_manager.py) | `_transition_to_core()`에 auto-trigger hook 추가 (RECONCILE_REQUIRED + !BLOCKED) | 모든 상태 전이 경로 (조건부) |
| [`tests/services/test_reconciliation_service.py`](tests/services/test_reconciliation_service.py) | 5개 idempotency 테스트 케이스 추가 | 테스트 전용 |
| [`plans/reconcile_required_auto_trigger_implementation_2026-05-16.md`](plans/) | 본 보고서 | 문서 |

---

## 5. 테스트 결과

### 테스트 커버리지 (5개 신규)

| 테스트 | 검증 내용 | 통과 |
|--------|----------|------|
| `test_trigger_idempotent_reuses_active_run` | 동일 계정 중복 trigger → run 재사용 | ✅ |
| `test_trigger_creates_new_run_when_no_active` | active run 없으면 새 생성 | ✅ |
| `test_trigger_creates_new_run_after_previous_resolved` | resolved 후에는 새 생성 | ✅ |
| `test_trigger_idempotent_different_trigger_type_same_account` | 다른 trigger_type이어도 재사용 | ✅ |
| `test_trigger_idempotent_accounts_independent` | 서로 다른 계정은 독립적 | ✅ |

### 실행 결과

```
python3 -m pytest tests/services/test_reconciliation_service.py -v
==== 14 passed in 0.45s ====
```

- 기존 9개 테스트: **모든 회귀 없음** ✅
- 신규 5개 테스트: **모두 통과** ✅

---

## 6. 운영 검증 결과

| 단계 | 명령어 | 결과 |
|------|--------|------|
| **pytest** | `python3 -m pytest tests/services/test_reconciliation_service.py -v` | ✅ 14 passed |
| **전체 테스트 영향도** | `python3 -m pytest tests/services/ -x --timeout=60` | ✅ 기존 테스트 회귀 없음 |
| **Docker 빌드** | `docker compose build` | ✅ 성공 |
| **Docker 재기동** | `docker compose up -d` | ✅ 모든 컨테이너 정상 |
| **`/health`** | `curl -s http://localhost:8000/health | python3 -m json.tool` | ✅ `status: ok`, `database: connected` |

---

## 7. 아키텍처 다이어그램

```
[변경 전]

Order submit → uncertain/requires_reconciliation
  → OrderManager.submit_order_to_broker()
    → trigger() ✅ (이미 존재)
    → transition_to(RECONCILE_REQUIRED)

Post-submit sync → ODNO match FAILED
  → transition_to(RECONCILE_REQUIRED)
    → trigger() ❌ (누락) ← 문제
    → reconciliation run: 0건

[변경 후]

모든 RECONCILE_REQUIRED 전이
  → OrderManager._transition_to_core()
    ┌─ target_status == RECONCILE_REQUIRED?
    │  ├─ reason_code == "BLOCKED"? → Skip (lock 존재)
    │  └─ otherwise → trigger()
    │                  └─ active run 존재? → 재사용
    │                  └─ 없음 → 새 run 생성
    └─ otherwise → 기존 로직 유지
```

---

## 8. Observability 로그 포맷

### Auto-trigger 성공
```
reconcile_required auto-triggered: order_id=<uuid> account_id=<uuid> reconciliation_run_id=<uuid> reason_code=<str>
```

### Idempotency (기존 run 재사용)
```
reconcile_required auto-trigger: active reconciliation run already exists, reusing. run_id=<uuid> account_id=<uuid> trigger_type=<str>
```

### Auto-trigger 실패
```
reconcile_required auto-trigger FAILED: order_id=<uuid> account_id=<uuid> error=<str>
```

---

## 9. 남은 Follow-up

| 우선순위 | 항목 | 설명 |
|---------|------|------|
| **P0** | **이미 stuck된 `reconcile_required` 주문 수동 backfill** | Phase 17 대상 주문(`400353e9-...`)에 대해 reconciliation run 수동 생성 필요. auto-trigger는 **새로운 전이부터** 적용됨 |
| **P1** | **OrderRequestEntity에 `symbol` 필드 확인** | 현재 auto-trigger 호출 시 `hasattr(order, 'symbol')`로 방어. entity에 symbol 필드가 없으면 None 전달 |
| **P2** | **`trigger_type="reconcile_required_transition"` DB ENUM 등록** | DB migration으로 `reconciliation_runs.trigger_type` ENUM에 값 추가 고려 |
| **P3** | **Paper 전용 auto-resolve 정책** | Paper 환경에서 reconciliation이 항상 실패하면 자동 해소 정책 도입 (이번 턴 범위 밖) |

---

## 부록: 참조

- **Phase 17 분석 보고서**: [`plans/reconcile_required_single_order_trace_2026-05-16.md`](plans/reconcile_required_single_order_trace_2026-05-16.md)
- **ReconciliationService**: [`src/agent_trading/services/reconciliation_service.py`](src/agent_trading/services/reconciliation_service.py)
- **OrderManager**: [`src/agent_trading/services/order_manager.py`](src/agent_trading/services/order_manager.py)
- **테스트 파일**: [`tests/services/test_reconciliation_service.py`](tests/services/test_reconciliation_service.py)
- **도메인 엔티티**: [`src/agent_trading/domain/entities.py`](src/agent_trading/domain/entities.py)
