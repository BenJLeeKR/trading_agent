# 인계 문서: 차기 Roo Code 세션 핸드오버

> **작성일**: 2026-05-22 (UTC+9:00, Asia/Seoul)
> **대상**: 차기 Roo Code 세션 작업자
> **목적**: 이번 세션(2026-05-22)의 모든 작업 상황과 의사결정 맥락을 인계하여 끊김 없는 작업 연속성 확보

---

## 1. Current Status (현재 상태)

이번 세션에서는 **Round 4: Reconciliation Lock 연쇄 차단 근본 원인 분석 및 Fix A+B+C+D 구현 + Fix B Migration 실제 DB 적용**을 완료했습니다. 모든 코드 변경은 테스트(93/94 통과, 1건 pre-existing failure)까지 완료되었으며, **Migration 0020이 실제 DB에 적용되어 코드와 DB가 일치하는 상태**입니다.

---

### A. Round 4 — Reconciliation Lock 연쇄 차단 근본 원인 분석 및 Fix A+B+C+D ✅ 완료

#### 문제 상황
2026-05-22 10:17 KST에서 000810/000150/000270 held_position sell 주문이 **BLOCKED** 상태로 지속됨. Round 3 Fix(`release_blocking_lock()` 호출 + ORDER bucket 3x)가 적용되었음에도 lock이 해제되지 않음.

#### 근본 원인 (3-layer)
1. **PostgreSQL UNIQUE + NULL 버그**: `ON CONFLICT DO NOTHING`이 `strategy_id IS NULL`일 때 절대 발동하지 않음 (PostgreSQL은 NULL을 distinct로 취급). 증거: 001230(buy)에 동일 scope lock 4개 존재.
2. **`release_blocking_lock()` silent failure**: DELETE 0 rows여도 예외만 catch하고 로그만 남김 → `locked_by_run_id` 불일치를 감지하지 못함.
3. **`locked_by_run_id` mismatch**: `get_active_run()`은 `status='started'`만 반환 → worker가 run을 `failed`로 마킹 후 `trigger()`가 새 run 생성 → 새 run의 `release_blocking_lock(locked_by_run_id=new_run_id)`가 원래 lock 소유자와 불일치.

#### 해결 방법 (Fix A+B+C+D)

| Fix | 파일 | 변경 내용 |
|-----|------|-----------|
| **Fix A** | [`reconciliation_service.py:187-258`](src/agent_trading/services/reconciliation_service.py:187) | `acquire_blocking_lock()`: `ON CONFLICT DO NOTHING` → `ON CONFLICT ... DO UPDATE SET ... WHERE expires_at < NOW()`. COALESCE 기반 conflict target으로 NULL-safe matching. **Active lock은 덮어쓰지 않음** (expired만 takeover). |
| **Fix B** | [`db/migrations/0020_null_safe_blocking_lock_unique.sql`](db/migrations/0020_null_safe_blocking_lock_unique.sql) | NULL-safe unique migration: DROP old UNIQUE constraint → CREATE COALESCE-based expression index → Clean up duplicate locks. |
| **Fix C** | [`reconciliation_service.py:260-342`](src/agent_trading/services/reconciliation_service.py:260) | `release_blocking_lock()`: DELETE 결과 검증 추가 — 0행 삭제 + non-expired lock 존재 시 warning 로그. |
| **Fix D** | [`reconciliation_worker.py:480-528`](src/agent_trading/services/reconciliation_worker.py:480) | `_mark_run_failed()` + `_mark_run_reflection_failed()`: `completed_at=now` 파라미터 추가. |

#### 테스트 결과
- **93/94 통과** (1건 pre-existing failure: `test_get_recent_events_with_data` — 0 == 2 assertion, 본 변경과 무관)

#### 분석 문서
- [`plans/trace_real_budget_source_and_lock_owner_for_1017_held_position_sell_blocking_2026-05-22.md`](plans/trace_real_budget_source_and_lock_owner_for_1017_held_position_sell_blocking_2026-05-22.md)
- [`plans/apply_null_safe_blocking_lock_migration_and_reverify_held_position_sell_blocking_2026-05-22.md`](plans/apply_null_safe_blocking_lock_migration_and_reverify_held_position_sell_blocking_2026-05-22.md) — Migration 적용 및 검증 보고서

---

### B. (이전 세션 작업 — 참고용) User Request 13/13b/13c — BUY sizing 개선 ✅ 완료

이전 세션(2026-05-21)에서 완료된 작업으로, 현재 운영 환경에 반영되어 있습니다.

| 작업 | 설명 |
|------|------|
| **User Request 13** | Reference price 기반 MARKET 주문 sizing + 10주 하드코딩 제거 |
| **User Request 13b** | 고가주 sub-10 BUY baseline + `_resolve_buy_target_quantity()` |
| **User Request 13c** | `requested_quantity=10` 상한 제거 + 완전 동적 BUY 수량 |
| **AR 2-layer guard** | 코드 배포 완료, 장중 검증 pending |

---

## 2. Work In Progress (진행 중인 작업)

### ✅ P0: Reconciliation Lock Fix — Migration 적용 + 컨테이너 재시작 완료 (2026-05-22)

**상태**: **Migration 0020 실제 DB 적용 완료. 컨테이너 재시작 및 health check 통과.**

#### 완료된 작업

1. **Migration 0020 적용** ✅
   - `python3 -m src.agent_trading.db.migrations.run` runner가 TimeoutError로 0020까지 도달하지 못해 **직접 psql로 SQL 실행**
   - 중복 lock 3건 우선 정리 후 NULL-safe expression index 생성
   - `uq_order_blocking_locks_key`: `(account_id, strategy_id, symbol, side)` → `(account_id, COALESCE(strategy_id, '00000000-...'::uuid), symbol, side)`

2. **Duplicate Lock 정리** ✅
   - 001230 buy lock 4개 중 3개 삭제 (가장 최근 1개만 보존)
   - 현재 중복 0건

3. **컨테이너 재시작 + Health Check** ✅
   ```bash
   docker compose restart
   curl -sf http://localhost:8000/health
   # → {"status":"ok","database":"connected","scheduler":{"healthy":true}}
   ```

4. **Held_position Sell 재검증** ✅
   - 000810/000150/000270 sell lock 모두 EXPIRED 상태 (ACTIVE lock 없음)
   - 각 symbol/side당 1개씩만 존재 (중복 없음)

#### 차기 세션에서 수행해야 할 작업

1. **장중 검증** (운영 시간에만 가능)
   - reconciliation worker 로그에서 `"Blocking lock released"` 메시지 확인
   - `release_blocking_lock: DELETE affected 0 rows` warning 로그 발생 여부 확인
   - BLOCKED 상태 주문이 정상적으로 해소되는지 확인
   - NULL-safe index로 인해 duplicate lock이 더 이상 생성되지 않는지 확인

2. **Fix E 검토** (held_position sell 전용 budget lane)
   - BUY budget과 SELL budget 분리 또는 held_position sell 우선권 부여 로직

3. **Fix F 검토** (expired lock cleanup)
   - 주기적인 cleanup cron 또는 `acquire_blocking_lock()` 내 정리 로직

### 🔴 알려진 이슈

| 이슈 | 심각도 | 상태 |
|------|--------|------|
| `test_get_recent_events_with_data` failure (0 == 2) | 낮음 | Pre-existing, 본 변경과 무관 |
| Fix E (held_position sell 전용 budget lane) | 중간 | 차기 라운드에서 검토 예정 |
| Fix F (expired lock cleanup) | 낮음 | P2, deferred |
| Migration runner TimeoutError (0001, 0012, 0016, 0017) | 낮음 | 직접 psql 실행으로 우회 가능 |
| `trading.orders` 테이블 미존재 | 낮음 | broker_orders만 존재, order-level sell 추적 제한적 |

---

## 3. Implicit Context (숨은 맥락 및 의사결정)

### A. Reconciliation Lock 설계 결정사항

#### Fix A: `ON CONFLICT DO UPDATE WHERE expires_at < NOW()`

- **의도**: Active lock은 절대 덮어쓰지 않음. 오직 **expired** lock만 takeover.
- **이유**: `locked_by_run_id` mismatch 문제의 근본 해결. 새 run이 expired lock을 takeover하면 `release_blocking_lock(locked_by_run_id=new_run_id)`가 정상 동작함.
- **Trade-off**: Active lock 기간(최대 30분) 동안은 새 reconciliation run이 lock을 획득할 수 없음. 이는 의도된 동작 — reconciliation이 아직 진행 중이면 새 run이 필요하지 않음.

#### Fix B: COALESCE-based expression index

- **Sentinel UUID**: `00000000-0000-0000-0000-000000000000`
- **이유**: PostgreSQL이 NULL을 distinct로 취급하는 근본적 한계를 우회. 실제 `strategy_id`와 충돌할 가능성이 극히 낮은 값 선택.
- **ON CONFLICT 구문 일치**: `acquire_blocking_lock()`의 `ON CONFLICT` 절도 동일한 COALESCE 표현식을 사용해야 함.

#### Fix C: DELETE 결과 검증

- **0행 삭제 + non-expired lock 존재** → `locked_by_run_id` mismatch
- **0행 삭제 + lock 없음** → 정상 (이미 해제됨)
- **>0행 삭제** → 정상

#### Fix D: `completed_at=now`

- `update_run_status()`는 `completed_at`이 optional 파라미터. 전달하지 않으면 `completed_at IS NULL`로 저장됨.
- 이 값은 `get_active_run()`과 직접적 관련은 없지만, run의 완료 시점 추적과 사후 분석에 필요.

---

### B. (이전 세션) BUY Sizing 설계 결정사항

*이전 세션(2026-05-21)의 결정사항은 유효합니다. 자세한 내용은 이전 HANDOVER 문서 참조.*

| 결정 | 내용 |
|------|------|
| `reference_price` | MARKET 주문용 sizing 기준 가격, quote 기반 |
| `safety_factor=0.95` | MARKET BUY 전용, 현금 여유분 확보 |
| `_ALLOCATION_PCT = 0.2` | 단일 BUY에 orderable_amount의 20% 할당 |
| `requested_quantity` | 더 이상 BUY의 절대적 상한이 아님 |

---

### C. Docker 운영 참고사항

| 항목 | 내용 |
|------|------|
| **이미지 빌드** | `docker compose build` (4개 이미지: app, api, reconciliation-worker, ops-scheduler) |
| **Migration 실행** | `docker compose exec app python3 -m src.agent_trading.db.migrations.run` |
| **재시작** | `docker compose up -d` (모든 컨테이너) |
| **Health check** | `curl -sf http://localhost:8000/health` |
| **Python 명령어** | 반드시 `python3` 사용 (shebang 포함) |
| **Shell** | 반드시 `/bin/bash` 기준 |
| **주의** | `.env` 파일 수정 금지 |

---

## 4. Plans 디렉토리 문서 목록 (이번 세션 생성)

| 파일 | 설명 |
|------|------|
| [`plans/trace_real_budget_source_and_lock_owner_for_1017_held_position_sell_blocking_2026-05-22.md`](plans/trace_real_budget_source_and_lock_owner_for_1017_held_position_sell_blocking_2026-05-22.md) | **Round 4**: Reconciliation Lock 근본 원인 분석 + Fix A+B+C+D 설계 |

---

## 5. 요약 체크리스트 — 차기 세션 시작 시

### P0 (즉시 수행)
- [ ] **Migration 0020 적용**: `docker compose exec app python3 -m src.agent_trading.db.migrations.run`
- [ ] **Docker rebuild + 재시작**: `docker compose build && docker compose up -d`
- [ ] **Health check**: `curl -sf http://localhost:8000/health`

### P1 (장중 확인)
- [ ] **Reconciliation lock 정상 해제 확인**: worker 로그에서 `"Blocking lock released"` 검색
- [ ] **`release_blocking_lock` warning 확인**: `"DELETE affected 0 rows"` 로그 발생 여부
- [ ] **BLOCKED 상태 주문 해소 확인**: `is_blocked()` 쿼리로 lock 존재 여부 확인

### P2 (참고)
- [ ] (선택) Fix E: held_position sell 전용 budget lane 검토
- [ ] (선택) Fix F: expired lock cleanup 스케줄러 검토
- [ ] (선택) AR Layer 2 guard 생산 검증 (이전 세션 pending)

---

*인계 완료. 이 문서는 [`plans/HANDOVER_TO_NEW_SESSION.md`](plans/HANDOVER_TO_NEW_SESSION.md)에 저장되어 있습니다.*
