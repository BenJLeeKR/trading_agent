# Phase 7d Subtask 1 — 실행 계획 보고서

## 1. DB Snapshot 결과 요약

| 항목 | 값 |
|------|-----|
| `broker_status='reconcile_required'` 주문 | **16건** |
| Fallback-eligible (age > 30분) | **16/16 (100%)** |
| 최소 경과 시간 | 65분 (1건) |
| 최대 경과 시간 | 4170분 (~69시간, 3건) |
| `status=expired` + `broker_status=reconcile_required` 이상 케이스 | **74건** |
| `reconciliation_runs` 총계 | **18건** |
| └ `status=failed` | 17건 |
| └ `status=halted` | 1건 |
| └ `status=started` 또는 `pending` | **0건** |
| `reconciliation_order_links` | 18건 (모두 `mismatch_type='pending_inquiry'`) |

## 2. Worker Runner 분석

### 2.1 `scripts/run_reconciliation_worker.py` 구조

- **`ReconciliationRunProcessor` 생성 시 `order_manager` 미주입** (`order_manager=None`)
- `list_pending_runs()` 호출 → `WHERE status = 'started'` 조건으로 조회
- 실행 모드: `--once` (1회), `--count N` (N회), `--dry-run`, `--run-id <uuid>`, `--account-id <uuid>`, `--limit N`
- `_run_one_cycle()`에서 `process_run()` 호출 → 각 run의 order link 순회

### 2.2 `ReconciliationRunProcessor.process_run()` 흐름

```
process_run()
  └─ run.status 확인 → 'started'만 처리
  └─ _get_or_create_broker() → broker_account 조회
  └─ _build_adapter_for_broker_account() → KIS adapter 생성 + authenticate()
  └─ _process_order_link() 각 링크에 대해:
       └─ adapter.resolve_unknown_state() → broker에 상태 조회
       └─ broker_status == 'RECONCILE_REQUIRED' → _try_expired_fallback()
            ├─ age >= 30분 OR after-hours 체크
            ├─ self.order_manager 있음 → transition_to_authoritative()
            └─ self.order_manager 없음 → repos.orders.update_status() 직접 호출
       └─ broker_status == 'EXPIRED' 등 → mark_resolved()
```

### 2.3 `_try_expired_fallback()` 두 가지 코드 경로

| 조건 | 실행 코드 | 특징 |
|------|----------|------|
| `order_manager is not None` | `order_manager.transition_to_authoritative(order, OrderStatus.EXPIRED, ...)` | 풍부한 감사 추적, version 관리 |
| `order_manager is None` (**현재**) | `repos.orders.update_status(order_request_id, status=EXPIRED, expected_version=..., reason_code=...)` | 직접 DB update, 감사 추적 제한적 |

**현재 `run_reconciliation_worker.py`는 `order_manager`를 넘기지 않으므로 두 번째 경로(fallback)로 동작한다.**

## 3. Runtime Injection 분석

### 3.1 Runner 스크립트 비교

| 스크립트 | `OrderManager` 주입 여부 |
|----------|------------------------|
| `scripts/run_reconciliation_worker.py` | **❌ 미주입** |
| `scripts/run_post_submit_sync_loop.py` (ref) | ✅ 주입 완료 (`OrderManager(repos=repos)`) |

### 3.2 `scripts/run_ops_scheduler.py`와의 관계

- 스케줄러는 reconciliation worker를 직접 실행하지 않음
- `_post_submit_command(recovery=True)`가 after-hours (16:00 KST)에 recovery batch 실행
- Recovery 모드는 EXPIRED fallback 조건 활성화 관련

## 4. 기존 Failed Run 재처리 가능성

### 4.1 핵심 문제: `status='started'` Run 부재

```
reconciliation_runs status distribution:
  failed: 17
  halted: 1
  started: 0  ← Worker가 처리할 run 없음
  pending: 0
```

- `list_pending_runs()`는 `WHERE status = 'started'`로 조회
- 현재 모든 run이 `failed`/`halted` terminal 상태
- **Worker를 실행해도 처리할 run이 없어 아무 일도 일어나지 않음**

### 4.2 재처리를 위한 전제 조건

1. **Failed run을 `started`로 리셋해야 함** — DB UPDATE 필요 (Subtask 2에서 처리)
2. 리셋 시 `started_at`, `completed_at` 필드도 함께 초기화 필요
3. 재처리 전 blocking lock 상태 확인 필요 — failed run은 `_mark_run_failed()`에서 lock 해제하므로 보통 문제 없음

### 4.3 Fallback 조건

- Age 조건: 모든 16개 reconcile_required 주문이 30분 초과 → **조건 충족**
- After-hours 조건: 현재 KST 12:35 PM (장중) → 미충족, 그러나 age 조건만으로도 충분
- `_try_expired_fallback()`이 호출되면 fallback 경로(`order_manager=None`)로 EXPIRED 전이 가능

## 5. 실행 계획 (Subtask 2)

### 5.1 사전 준비

| 단계 | 작업 | 명령어 | 비고 |
|------|------|--------|------|
| 1 | Failed run → `started` 리셋 | `UPDATE reconciliation_runs SET status='started', started_at=NULL, completed_at=NULL WHERE status='failed'` | DB write 필요 |
| 2 | Broker API 연결 확인 | KIS paper token 발급 테스트 | `.env`에 KIS paper credentials 존재 |

### 5.2 Dry-Run 실행 (1차 검증)

```bash
cd /workspace/agent_trading
set -a && . ./.env && set +a
python3 scripts/run_reconciliation_worker.py --once --dry-run --account-id <account_uuid>
```

- `--dry-run`: 실제 DB 변경 없이 로그만 출력
- 예상 결과: `_try_expired_fallback()` 조건 로그, `repos.orders.update_status()` 호출 직전 로그
- 검증 항목: KIS adapter 인증 성공 여부, `resolve_unknown_state()` 응답, fallback eligibility 판정

### 5.3 실제 실행 (Dry-Run 성공 시)

```bash
cd /workspace/agent_tracing  # ← 주의: 기존 명령어 기준
```

실제 명령어:

```bash
cd /workspace/agent_trading
python3 scripts/run_reconciliation_worker.py --once --count 1  # 1개 run만 처리
```

### 5.4 Order Manager 주입 옵션 (선택 사항)

`_try_expired_fallback()`이 `OrderManager.transition_to_authoritative()`를 사용하도록 하려면:

1. `scripts/run_reconciliation_worker.py`의 `_run_one_cycle()` 함수 내에서 `OrderManager` 생성 후 주입
2. 또는 `ReconciliationRunProcessor.__init__`에 `order_manager` 파라미터 전달

**현재 fallback 경로(direct repos update)로도 EXPIRED 전이는 가능하나, `OrderManager` 경로가 더 안전함.**

### 5.5 위험 요소 및 대비책

| 위험 | 영향 | 대비책 |
|------|------|--------|
| KIS paper API 장애/인증 실패 | `resolve_unknown_state()` 실패 → run 실패 | `--dry-run`으로 사전 검증 |
| `reconciliation_run_orders` vs `reconciliation_order_links` 테이블명 불일치 | 쿼리 오류 | 실제 테이블명(`reconciliation_order_links`) 사용 확인 |
| 이미 처리된 주문 재처리 | Version 충돌 가능성 | `expected_version` 체크, `version` 불일치 시 조용히 스킵 |
| After-hours가 아닌 장중 실행 | Fallback 조건 age 기반으로 충분 | 16개 모두 30분 초과로 문제 없음 |

### 5.6 권장 실행 순서

```
Step 1: Failed run → started 리셋 (SQL UPDATE)
Step 2: Dry-run 수행 (--dry-run --once)
Step 3: Dry-run 로그 분석
Step 4: 실제 실행 (--once --count 1)
Step 5: 결과 검증 (DB 재조회)
Step 6: 나머지 run 순차 처리
```

## 6. 권고사항

1. **`OrderManager` 주입을 권장** — `run_reconciliation_worker.py`에 `from agent_trading.services.order_manager import OrderManager` 추가 후 `_run_one_cycle()` 내에서 생성하여 주입
2. **Failed run 리셋 전 원복 계획 수립** — 만약을 대비해 리셋 전 `status` 스냅샷 백업
3. **Broker API Health Check 선행** — KIS paper env가 실제로 응답하는지 확인 후 진행
4. **`reconciliation_order_links`에 `mismatch_type='pending_inquiry'`** 만 존재 — broker가 `reconcile_required`를 반환해야 fallback 트리거 가능
