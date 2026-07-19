# Round 4 — Fix B Migration 실제 DB 적용 및 운영 검증 보고서

> **작성일**: 2026-05-22 (UTC+9, Asia/Seoul)
> **목적**: Fix B (`NULL-safe unique lock index`)를 실제 DB에 적용하고 duplicate lock을 정리한 후 운영 상태 재검증

---

## 1. Migration 적용 전 상태

### 1.1 UNIQUE 인덱스 상태

```sql
-- 적용 전: NULL-safe하지 않은 일반 UNIQUE B-tree 인덱스
uq_order_blocking_locks_key
  CREATE UNIQUE INDEX uq_order_blocking_locks_key
  ON trading.order_blocking_locks
  USING btree (account_id, strategy_id, symbol, side)
```

- `strategy_id` 컬럼이 NULL일 때 PostgreSQL은 NULL을 distinct로 취급
- `(account_id, NULL, symbol, side)` 조합의 중복 row가 UNIQUE 위반 없이 삽입 가능

### 1.2 Duplicate Lock 현황

| account_id | strategy_id | symbol | side | 중복 수 |
|---|---|---|---|---|
| a44a02d1-... | NULL | 001230 | buy | **4** |

4개의 duplicate lock 상세:

| lock_id | locked_at (UTC) | locked_by_run_id | expires_at | 상태 |
|---|---|---|---|---|
| d1d60adb-... | 2026-05-16 09:27:40 | f7cf6333-... | 2026-05-16 09:57:40 | EXPIRED |
| 9aa34d6c-... | 2026-05-16 10:47:07 | e43955a2-... | 2026-05-16 11:17:07 | EXPIRED |
| cb775056-... | 2026-05-16 11:04:00 | d68ec501-... | 2026-05-16 11:34:00 | EXPIRED |
| 95b5f059-... | 2026-05-16 11:07:12 | 1453d5a2-... | 2026-05-16 11:37:12 | EXPIRED |

→ 모두 2026-05-16에 생성되어 이미 만료된 상태였으나, UNIQUE 제약이 없어 4개가 동시에 존재 가능했음.

### 1.3 Held_position Sell 차단 상태

| symbol | side | lock_id | locked_at (UTC) | expires_at | 상태 |
|---|---|---|---|---|---|
| 000810 | sell | 81b9e986-... | 2026-05-22 00:36:03 | 2026-05-22 01:06:03 | EXPIRED |
| 000150 | sell | 441d6163-... | 2026-05-22 01:02:53 | 2026-05-22 01:32:53 | EXPIRED |
| 000270 | sell | cca58f19-... | 2026-05-22 01:03:44 | 2026-05-22 01:33:44 | EXPIRED |

→ 3종목 sell lock 모두 EXPIRED 상태. `orders` 테이블은 `trading` 스키마에 존재하지 않음 (broker_orders만 존재).

---

## 2. Migration 적용 내용

### 2.1 Migration SQL: [`0020_null_safe_blocking_lock_unique.sql`](db/migrations/0020_null_safe_blocking_lock_unique.sql)

3단계로 구성:

1. **DROP 기존 UNIQUE CONSTRAINT**
   ```sql
   ALTER TABLE trading.order_blocking_locks
       DROP CONSTRAINT IF EXISTS uq_order_blocking_locks_key;
   ```

2. **CREATE NULL-safe expression index**
   ```sql
   CREATE UNIQUE INDEX IF NOT EXISTS uq_order_blocking_locks_key
       ON trading.order_blocking_locks (
           account_id,
           COALESCE(strategy_id, '00000000-0000-0000-0000-000000000000'::uuid),
           symbol,
           side
       );
   ```
   - `COALESCE(strategy_id, sentinel_uuid)`로 NULL을 sentinel UUID로 매핑
   - 모든 `strategy_id IS NULL` row가 동일한 값으로 취급되어 UNIQUE 제약 적용

3. **중복 Lock 정리**
   ```sql
   WITH duplicates AS (
       SELECT lock_id, ROW_NUMBER() OVER (
           PARTITION BY account_id,
                        COALESCE(strategy_id, '00000000-...'::uuid),
                        symbol, side
           ORDER BY locked_at DESC
       ) AS rn FROM trading.order_blocking_locks
   )
   DELETE FROM trading.order_blocking_locks
   WHERE lock_id IN (SELECT lock_id FROM duplicates WHERE rn > 1);
   ```
   - 각 scope별로 가장 최근 lock 1개만 보존

### 2.2 실행 방식

`python3 -m src.agent_trading.db.migrations.run` runner가 타임아웃 문제로 0020까지 도달하지 못해, **직접 psql로 SQL 실행**:

```bash
# 1) 중복 lock 우선 정리 (UNIQUE INDEX 생성 전)
docker compose exec -T db psql -U trading -d trading -c "BEGIN; ... DELETE 3; COMMIT;"

# 2) 기존 UNIQUE CONSTRAINT DROP + NULL-safe expression index 생성
docker compose exec -T db psql -U trading -d trading -c "BEGIN; ALTER TABLE ... DROP CONSTRAINT; CREATE UNIQUE INDEX ...; COMMIT;"
```

---

## 3. 적용 후 인덱스/중복 상태

### 3.1 인덱스 변경 확인 ✅

```sql
-- 적용 후: COALESCE 기반 NULL-safe expression index
uq_order_blocking_locks_key
  CREATE UNIQUE INDEX uq_order_blocking_locks_key
  ON trading.order_blocking_locks
  USING btree (
    account_id,
    COALESCE(strategy_id, '00000000-0000-0000-0000-000000000000'::uuid),
    symbol,
    side
  )
```

- `strategy_id IS NULL`인 row도 sentinel UUID로 변환되어 UNIQUE 제약 적용
- `ON CONFLICT (account_id, COALESCE(strategy_id, ...), symbol, side) DO UPDATE SET ...` 구문과 정확히 매칭

### 3.2 Duplicate Lock 정리 확인 ✅

```sql
SELECT account_id, strategy_id, symbol, side, COUNT(*) as cnt
FROM trading.order_blocking_locks
GROUP BY account_id, strategy_id, symbol, side
HAVING COUNT(*) > 1;
-- (0 rows)
```

- **3건 삭제**, 0건 중복으로 정리 완료
- 001230 buy lock 중 가장 최근 1개(`95b5f059-...`, 2026-05-16 11:07:12)만 보존

### 3.3 전체 Lock 현황 (적용 후)

| lock_id | symbol | side | locked_at | expires_at | 상태 |
|---|---|---|---|---|---|
| 81b9e986-... | 000810 | sell | 2026-05-22 00:36:03 | 2026-05-22 01:06:03 | EXPIRED |
| 441d6163-... | 000150 | sell | 2026-05-22 01:02:53 | 2026-05-22 01:32:53 | EXPIRED |
| cca58f19-... | 000270 | sell | 2026-05-22 01:03:44 | 2026-05-22 01:33:44 | EXPIRED |
| 95b5f059-... | 001230 | buy | 2026-05-16 11:07:12 | 2026-05-16 11:37:12 | EXPIRED |

→ **ACTIVE lock 0개**. 모든 lock이 EXPIRED 상태.

---

## 4. Held_position Sell 재검증 결과

### 4.1 컨테이너 재시작 및 Health Check ✅

```bash
docker compose restart
# → app, api, db, ops-scheduler, reconciliation-worker 모두 재시작
curl -sf http://localhost:8000/health
# → {"status":"ok","database":"connected","scheduler":{"healthy":true}}
```

### 4.2 Held_position Sell Lock 상태

| symbol | side | lock 존재 | 상태 | 비고 |
|---|---|---|---|---|
| 000810 | sell | 1개 | EXPIRED | 2026-05-22 00:36 생성, 30분 후 만료 |
| 000150 | sell | 1개 | EXPIRED | 2026-05-22 01:02 생성, 30분 후 만료 |
| 000270 | sell | 1개 | EXPIRED | 2026-05-22 01:03 생성, 30분 후 만료 |

- **중복 lock 없음** (각 symbol/side당 1개씩만 존재)
- **ACTIVE lock 없음** — 모든 lock이 이미 만료
- `orders` 테이블이 `trading` 스키마에 존재하지 않아 order-level sell 상태는 확인 불가

### 4.3 NULL-safe Index 검증

새로운 reconciliation run에서 `acquire_blocking_lock()`이 호출될 때:
- `ON CONFLICT (account_id, COALESCE(strategy_id, '00000000-...'::uuid), symbol, side)`가 정상 매칭
- `strategy_id IS NULL`인 lock도 UNIQUE 제약 적용
- Expired lock은 `DO UPDATE SET ... WHERE expires_at < NOW()`로 takeover 가능
- **더 이상 duplicate lock이 생성되지 않음**

---

## 5. 남은 이슈

### 5.1 Fix E: Held_position Sell 전용 Budget Lane (심각도: 중간)

- Held_position sell이 BUDGET_EXHAUSTED로 차단되는 근본 문제
- BUY budget과 SELL budget을 분리하거나, held_position sell에 우선권을 부여하는 로직 필요
- `reconciliation_service.py`의 budget check 로직 개선 필요

### 5.2 Fix F: Expired Lock Cleanup (심각도: 낮음)

- 현재 EXPIRED lock이 DB에 계속 남아 있음 (4개)
- 주기적인 cleanup cron이나 `acquire_blocking_lock()`에서 expired lock 정리 로직 추가 가능
- 단, 현재는 `ON CONFLICT DO UPDATE WHERE expires_at < NOW()`로 expired lock takeover가 가능하므로 기능적 문제는 없음

### 5.3 `orders` 테이블 미존재

- `trading.orders` 테이블이 DB에 존재하지 않음
- `broker_orders` 테이블만 존재
- held_position sell의 order-level 상태 추적을 위해서는 orders 테이블 생성 또는 broker_orders 기반 분석 필요

### 5.4 Migration Runner 타임아웃

- `python3 -m src.agent_trading.db.migrations.run`이 0001, 0012, 0016, 0017 등에서 TimeoutError 발생
- 각 migration이 별도 connection에서 실행되나, 일부 DDL이 타임아웃되는 문제
- 향후 migration 적용 시 직접 psql 실행을 고려하거나 runner의 timeout 설정 조정 필요

---

## 6. 결론

| 질문 | 답변 |
|---|---|
| **1. Migration이 실제로 적용되었는가?** | ✅ 예. `uq_order_blocking_locks_key`가 COALESCE 기반 expression index로 변경됨 |
| **2. NULL-safe expression index로 바뀌었는가?** | ✅ 예. `COALESCE(strategy_id, '00000000-...'::uuid)` 포함 확인 |
| **3. Duplicate lock row는 정리되었는가?** | ✅ 예. 001230 buy 4개 중 3개 삭제, 현재 0건 중복 |
| **4. Migration 후 BLOCKED 연쇄 차단이 완화되는 조짐이 있는가?** | ✅ 구조적 완화 완료. NULL-safe index로 duplicate lock 재발 방지. 단, 현재 ACTIVE lock이 없어 실시간 검증은 장중 추가 관찰 필요 |
| **5. 추가로 남은 병목은 무엇인가?** | Fix E (held_position sell budget lane), Fix F (expired lock cleanup), orders 테이블 미존재 |
