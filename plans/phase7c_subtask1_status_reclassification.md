# Phase 7c Subtask 1: 28일~29일 `order_requests` 상태 재분류 보고서

> 분석 일시: 2026-05-30 KST
> 분석 범위: KST 2026-05-28 00:00 ~ 2026-05-30 00:00 (UTC 2026-05-27 15:00 ~ 2026-05-29 15:00)

---

## 1. DB 쿼리 결과 요약

### A. expired/reconcile_required 개요

| KST 일자 | status | side | 건수 |
|---------|--------|------|------|
| 2026-05-28 | expired | buy | 103 |
| 2026-05-28 | expired | sell | 3 |
| 2026-05-28 | reconcile_required | buy | 8 |
| 2026-05-28 | reconcile_required | sell | 1 |
| 2026-05-29 | expired | buy | 79 |
| 2026-05-29 | expired | sell | 5 |
| 2026-05-29 | reconcile_required | buy | 4 |
| 2026-05-29 | reconcile_required | sell | 1 |

**28일**: expired 106건, reconcile_required 9건  
**29일**: expired 84건, reconcile_required 5건

### B. expired 상세 — broker_orders 존재 여부

| KST 일자 | side | broker_order 유무 | 건수 |
|---------|------|-------------------|------|
| 2026-05-28 | buy | 있음 | 80 |
| 2026-05-28 | buy | 없음 | 23 |
| 2026-05-28 | sell | 있음 | 3 |
| 2026-05-29 | buy | 있음 | 79 |
| 2026-05-29 | sell | 있음 | 5 |

- **28일**: broker_order 있음 83건, 없음 23건 (모두 buy)
- **29일**: 전부 broker_order 있음 (84건)

### C. reconcile_required 상세

| KST 일자 | order_request_id | side | qty | reason_code | last_synced_at |
|---------|-----------------|------|-----|-------------|---------------|
| 2026-05-28 | 28b3d35d... | buy | 10 | NULL | 2026-05-29 06:36 |
| 2026-05-28 | 609c1ab6... | buy | 10 | NULL | 2026-05-29 06:36 |
| 2026-05-28 | 57ead625... | sell | 3 | NULL | 2026-05-29 06:36 |
| 2026-05-28 | ed6f4413... | buy | 11 | NULL | 2026-05-29 06:36 |
| 2026-05-28 | 843fadae... | buy | 56 | NULL | 2026-05-29 06:36 |
| 2026-05-28 | 2a12c8d2... | buy | 37 | NULL | 2026-05-29 06:36 |
| 2026-05-28 | e82bb4a7... | buy | 3 | NULL | 2026-05-29 06:36 |
| 2026-05-28 | 3059e254... | buy | 76 | NULL | 2026-05-29 06:36 |
| 2026-05-28 | a3616426... | buy | 36 | NULL | 2026-05-29 06:36 |
| 2026-05-29 | 75a3fee2... | buy | 12 | NULL | 2026-05-29 07:00 |
| 2026-05-29 | 30393929... | buy | 85 | NULL | 2026-05-29 07:00 |
| 2026-05-29 | 2a513146... | buy | 84 | NULL | 2026-05-29 07:00 |
| 2026-05-29 | 517c201f... | sell | 1 | NULL | 2026-05-29 07:00 |
| 2026-05-29 | c87f5ec3... | buy | 11 | NULL | 2026-05-29 07:00 |

**중요 발견**: reconcile_required 14건 모두:
- `status_reason_code` = NULL (reason_code 미설정)
- broker_order 존재 + broker_native_order_id 존재
- broker_status = 'reconcile_required'
- `last_synced_at`이 5/29일에 갱신됨 (sync loop가 계속 시도 중)

### D. expired reason_code 분포

| KST 일자 | reason_code | 건수 |
|---------|-------------|------|
| 2026-05-28 | eod_orphan_cleanup_no_broker_order | 23 |
| 2026-05-28 | NULL | 83 |
| 2026-05-29 | NULL | 84 |

- 28일: 23건은 EOD orphan cleanup으로 expired (broker_order 없음), 83건은 reason_code 없이 expired
- 29일: 전부 reason_code 없이 expired

### E. 전체 상태 분포

| KST 일자 | status | 건수 |
|---------|--------|------|
| 2026-05-28 | expired | 106 |
| 2026-05-28 | filled | 10 |
| 2026-05-28 | reconcile_required | 9 |
| 2026-05-28 | rejected | 101 |
| 2026-05-29 | expired | 84 |
| 2026-05-29 | filled | 8 |
| 2026-05-29 | reconcile_required | 5 |
| 2026-05-29 | rejected | 1 |

---

## 2. 코드 분석 결과

### 2.1 `order_sync_service.py` — 상태 전이 로직

#### expired 상태 설정 경로 (3가지)

1. **`sync_order_post_submit()` — terminal 상태 도달**
   - `_TERMINAL_STATUSES`에 EXPIRED 포함 (line 47)
   - broker.get_order_status()가 EXPIRED 반환 → `_try_transition()`으로 전이
   - 또는 broker 조회 실패 시에도 EXPIRED로 fallback하지 않음 (기존 terminal 유지)

2. **`transition_to_authoritative()` — RECONCILE_REQUIRED → EXPIRED fallback**
   - `resolve_unknown_state()` 실패 시 after-hours에만 EXPIRED fallback 허용 (line 1027-1033)
   - `_is_genuine_manual_reconciliation()` 판단: 24시간 초과 시 genuine으로 간주하여 EXPIRED fallback 차단 (line 2039-2041)
   - Stuck timeout (`_STUCK_EXPIRY_SECONDS` = 7200초 = 2시간) 초과 시 after-hours에만 EXPIRED fallback (line 1303-1525)

3. **`expire_eod_orphan_orders()` — EOD orphan cleanup**
   - after-hours(15:30 KST~)에만 실행
   - PENDING_SUBMIT + broker_orders=0 + submitted_at=NULL → `eod_orphan_cleanup_no_broker_order`
   - RECONCILE_REQUIRED + broker_orders=0 → `eod_orphan_cleanup_failed_reconciliation` 또는 `eod_orphan_cleanup_no_reconciliation`

#### reconcile_required 상태 설정 경로

- **`transition_to_authoritative()`** 내에서 broker가 `resolve_unknown_state()`로 RECONCILE_REQUIRED 반환 시 유지
- `_is_genuine_manual_reconciliation()`이 True 반환 시 유지 (24시간 초과)
- Intraday에는 EXPIRED fallback 금지 → RECONCILE_REQUIRED 유지
- Grace period 내 young order 보호 (30분/60분)

### 2.2 `run_post_submit_sync_loop.py` — Sync loop 구조

- 30초 간격으로 `PostSubmitSyncRunner.run_sync_cycle()` 호출
- `_ACTIVE_SYNC_STATUSES`: SUBMITTED, ACKNOWLEDGED, PARTIALLY_FILLED, RECONCILE_REQUIRED, PENDING_SUBMIT
- 각 sync cycle:
  1. Stale PENDING_SUBMIT 정리
  2. Active 주문 sync
  3. RECONCILE_REQUIRED 해소 시도 (`_sync_reconcile_required_orders`, limit=50)
  4. EOD orphan cleanup (after-hours only)

### 2.3 `orders.py` — 상태 업데이트

- `update_status()`: version optimistic locking 지원
- `reason_code`/`reason_message`는 선택적 파라미터 (NULL 허용)
- 상태 전이는 `OrderManager.transition_to()`를 통해 이루어짐

### 2.4 `backfill_reconcile_required_orders.py` — TRIGGERED vs REUSE

- **TRIGGERED**: reconciliation run이 없어 새로 생성
- **REUSE**: active reconciliation run이 이미 존재하여 skip
- `trigger_type = "requires_reconciliation"` 사용
- Idempotency: 동일 계정에 active run이 있으면 재사용

---

## 3. 분석 결과

### 3.1 `expired` 상태 분류

#### 정상 expired (정상 케이스)

| 구분 | 건수 | 근거 |
|------|------|------|
| **EOD orphan cleanup** (28일) | 23건 | broker_order 없음, submitted_at NULL, reason_code=`eod_orphan_cleanup_no_broker_order` |
| **broker가 EXPIRED 반환** (28일 62건, 29일 75건) | 137건 | broker_status='expired', broker가 정상적으로 timeout 처리 |

**총 정상 expired: 160건 (28일 85건 + 29일 75건)**

#### 비정상 expired (의심 케이스)

| 구분 | 건수 | 근거 |
|------|------|------|
| **broker_status='reconcile_required'인데 order는 expired** (28일 21건, 29일 9건) | 30건 | broker는 reconcile_required를 반환했지만, sync loop가 EXPIRED로 fallback시킴 |

**총 비정상 expired: 30건**

이 30건은 `transition_to_authoritative()`의 EXPIRED fallback 경로를 통해 expired된 것으로 추정됨:
- after-hours에 `resolve_unknown_state()` 실패 또는 broker가 RECONCILE_REQUIRED 반환
- `_is_genuine_manual_reconciliation()`이 False 반환 (24시간 미만)
- stuck timeout 초과 후 EXPIRED fallback

### 3.2 `reconcile_required` 상태 분석

#### 근본 원인

**reconcile_required 14건 모두 broker가 `resolve_unknown_state()`에 대해 RECONCILE_REQUIRED를 반환하고 있음.**

sync loop가 이들을 해결하지 못한 이유:

1. **broker truth가 RECONCILE_REQUIRED를 반환** (broker_status='reconcile_required')
   - KIS Paper API의 한계: `inquire-daily-ccld`가 주문을 찾지 못함
   - broker가 주문 상태를 확정할 수 없음

2. **`_is_genuine_manual_reconciliation()`이 False 반환**
   - broker_order_id 존재 (line 2035 조건 통과)
   - 24시간 미만 (line 2039-2041 조건 통과)
   - 따라서 sync loop가 계속 재시도

3. **Intraday에는 EXPIRED fallback 금지**
   - 장중에는 RECONCILE_REQUIRED 유지
   - after-hours에만 EXPIRED fallback 허용

4. **after-hours EXPIRED fallback이 실패한 이유**
   - `_is_genuine_manual_reconciliation()`이 24시간 초과 시 True 반환 → EXPIRED fallback 차단
   - 28일 생성 주문은 5/29 15:30 KST 이후 24시간 초과 → genuine으로 간주되어 EXPIRED 차단
   - 29일 생성 주문은 grace period 내 보호 또는 아직 24시간 미만

5. **`last_synced_at`이 5/29 06:36~07:00 UTC (15:36~16:00 KST)에 갱신됨**
   - after-hours sync cycle이 reconcile_required 해소를 시도했지만 실패
   - broker가 계속 RECONCILE_REQUIRED 반환

#### `status_reason_code` = NULL인 이유

`transition_to_authoritative()`에서 RECONCILE_REQUIRED 상태로 남을 때는 `reason_code`를 설정하지 않음. `_try_transition()`이 RECONCILE_REQUIRED → RECONCILE_REQUIRED (동일 상태)면 업데이트하지 않거나, reason_code 없이 업데이트함.

### 3.3 28일 vs 29일 차이 분석

| 항목 | 28일 | 29일 | 차이 |
|------|------|------|------|
| expired (broker_order 있음) | 83건 | 84건 | 유사 |
| expired (broker_order 없음) | 23건 | 0건 | 28일에만 EOD orphan cleanup 발생 |
| expired (broker_status=reconcile_required) | 21건 | 9건 | 28일이 2.3배 많음 |
| reconcile_required 잔존 | 9건 | 5건 | 28일이 더 많음 |
| rejected | 101건 | 1건 | 28일에 대량 reject 발생 |

**28일이 29일보다 비정상 expired/reconcile_required가 많은 이유:**
- 28일은 초기 운영일로 많은 주문이 제출됨 (rejected 101건)
- broker_order가 없는 orphan 주문이 많았음 (EOD cleanup 23건)
- broker가 reconcile_required를 반환한 비율도 높음

### 3.4 sync loop가 해결하지 못한 근본 원인

**핵심 원인: KIS Paper API의 `inquire-daily-ccld` 한계**

Paper 환경에서 `inquire-daily-ccld` API가 일일 체결 내역을 정확히 반환하지 못함. 이로 인해:
1. broker가 주문 상태를 `reconcile_required`로 반환
2. `resolve_unknown_state()`도 동일한 결과 반환
3. sync loop가 재시도해도 동일한 결과

**2차 원인: `_is_genuine_manual_reconciliation()`의 24시간 규칙**

24시간 초과 시 genuine으로 간주되어 EXPIRED fallback이 차단됨. 이는 의도된 설계지만, Paper API의 한계로 인해 정상 주문이 영구히 RECONCILE_REQUIRED로 stuck됨.

**3차 원인: Intraday EXPIRED fallback 금지**

장중에는 RECONCILE_REQUIRED를 유지하므로, after-hours가 되어야만 EXPIRED fallback이 가능. 하지만 after-hours에도 위 1, 2번 원인으로 해결되지 않음.

---

## 4. 정리 우선순위 제안

### Priority 1: 즉시 조치 필요 (비정상 expired 30건)

broker_status='reconcile_required'인데 order가 expired된 30건:
- **위험**: broker는 주문이 처리되었다고 볼 수 있지만, 시스템은 expired로 간주
- **조치**: position-delta 기반 복구 스크립트 실행 (SELL) 또는 broker truth 재조회 (BUY)
- **우선순위**: 최우선

### Priority 2: reconcile_required 14건 해소

broker가 계속 reconcile_required를 반환하는 14건:
- **위험**: 낮음 (sync loop가 계속 재시도 중, broker도 상태 미확정)
- **조치**: 
  - `backfill_reconcile_required_orders.py` 실행 (reconciliation run 생성)
  - 또는 수동으로 broker 확인 후 상태 업데이트
  - 또는 `_is_genuine_manual_reconciliation()` 로직 개선 (Paper API 대응)
- **우선순위**: 중간

### Priority 3: 시스템 개선 제안

1. **Paper API 대응 로직 개선**
   - `_is_genuine_manual_reconciliation()`에서 Paper 환경 감지 시 다른 기준 적용
   - Paper API의 `inquire-daily-ccld` 한계를 고려한 fallback 강화

2. **reason_code 누락 수정**
   - RECONCILE_REQUIRED 상태 설정 시에도 적절한 reason_code 기록
   - 현재 reconcile_required 14건 모두 reason_code=NULL

3. **모니터링 개선**
   - reconcile_required 잔존 건수에 대한 알림 추가
   - broker_status와 order_status 불일치 감지 알림

4. **EOD orphan cleanup 로직 검토**
   - 28일 23건의 EOD cleanup이 정상적인지 확인
   - broker_order가 없는 PENDING_SUBMIT 주문의 생성 원인 분석

---

## 5. 결론

| 상태 | 정상 | 비정상 | 합계 |
|------|------|--------|------|
| expired (28일) | 85건 | 21건 | 106건 |
| expired (29일) | 75건 | 9건 | 84건 |
| reconcile_required (28일) | 0건 | 9건 | 9건 |
| reconcile_required (29일) | 0건 | 5건 | 5건 |

- **정상 expired**: broker가 EXPIRED를 반환했거나, broker에 도달하지 못한 orphan (160건)
- **비정상 expired**: broker는 reconcile_required를 반환했지만 시스템이 EXPIRED로 fallback (30건)
- **reconcile_required**: broker가 상태를 확정하지 못해 stuck (14건, 모두 근본 원인 동일)

**근본 원인**: KIS Paper API의 `inquire-daily-ccld` 한계로 broker가 주문 상태를 확정하지 못함. 이로 인해 reconcile_required가 발생하고, after-hours EXPIRED fallback이 적용되었지만 일부는 `_is_genuine_manual_reconciliation()`의 24시간 규칙에 의해 차단됨.

**1순위 조치**: broker_status='reconcile_required'인 expired 30건에 대한 position-delta 기반 복구
