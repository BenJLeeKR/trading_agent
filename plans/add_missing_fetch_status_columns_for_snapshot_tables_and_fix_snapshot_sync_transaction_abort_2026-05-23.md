# Snapshot Sync `fetch_status` 컬럼 Migration 누락 수정

## 1. 직접 원인

`cash_balance_snapshots`와 `position_snapshots` 테이블에 `fetch_status` 컬럼이 DB에 존재하지 않았음에도, Postgres Repository의 INSERT 구문에 `fetch_status`가 포함되어 있어 첫 INSERT 시도가 실패 → 트랜잭션 abort → 연쇄 오류 발생.

### 관련 코드

- [`src/agent_trading/repositories/postgres/cash_balance_snapshots.py`](../../src/agent_trading/repositories/postgres/cash_balance_snapshots.py:24) — INSERT에 `fetch_status` 포함 (13개 파라미터)
- [`src/agent_trading/repositories/postgres/position_snapshots.py`](../../src/agent_trading/repositories/postgres/position_snapshots.py:25) — INSERT에 `fetch_status` 포함 (12개 파라미터)
- [`src/agent_trading/domain/entities.py`](../../src/agent_trading/domain/entities.py) — `fetch_status: str = "success"` 필드 정의

## 2. 적용한 Migration

**파일**: [`db/migrations/0025_add_fetch_status_to_snapshot_tables.sql`](../../db/migrations/0025_add_fetch_status_to_snapshot_tables.sql)

```sql
ALTER TABLE trading.cash_balance_snapshots
    ADD COLUMN fetch_status VARCHAR(16) NOT NULL DEFAULT 'success';

ALTER TABLE trading.position_snapshots
    ADD COLUMN fetch_status VARCHAR(16) NOT NULL DEFAULT 'success';
```

- `VARCHAR(16)`: "success", "error", "partial" 등 상태값 수용
- `NOT NULL DEFAULT 'success'`: 기존 row는 `success`로, 신규 row도 명시적 값 없으면 `success`
- Migration runner가 `db/migrations/` 디렉토리에서 자동 발견하여 실행

## 3. 수정한 파일

| 파일 | 작업 | 비고 |
|------|------|------|
| `db/migrations/0025_add_fetch_status_to_snapshot_tables.sql` | **생성** | Migration 0025 신규 파일 |
| `src/agent_trading/repositories/postgres/cash_balance_snapshots.py` | **수정 없음** | INSERT는 이미 올바름 |
| `src/agent_trading/repositories/postgres/position_snapshots.py` | **수정 없음** | INSERT는 이미 올바름 |
| `src/agent_trading/domain/entities.py` | **수정 없음** | 엔티티는 이미 올바름 |

→ **Migration 1개만 생성** (코드 수정 불필요)

## 4. 테스트 결과

```text
tests/services/test_snapshot_sync.py  ..............                       [ 18%]
tests/services/test_kis_snapshot_sync.py .................................. [100%]
============================= 76 passed in 22.16s ==============================
```

모든 snapshot sync 관련 테스트 통과 (in-memory repository 사용으로 DB 컬럼 의존성 없음)

## 5. 런타임 검증

### Docker 재빌드 + Migration 적용

```text
Image agent_trading-app:latest Built
Image agent_trading-api Built
```

### Health Check

```json
{"status":"ok","database":"connected","runtime_mode":"postgres",...}
```

### Migration 로그

```text
api-1  | Running migration: 0025_add_fetch_status_to_snapshot_tables.sql
api-1  | Migration completed: 0025_add_fetch_status_to_snapshot_tables.sql
```

### DB 컬럼 확인 (information_schema)

| table_name | column_name | data_type | is_nullable | column_default |
|---|---|---|---|---|
| `cash_balance_snapshots` | `fetch_status` | `varchar` | `NO` | `'success'` |
| `position_snapshots` | `fetch_status` | `varchar` | `NO` | `'success'` |

## 6. 최종 판정

| 항목 | 상태 |
|------|------|
| Migration 0025 생성 | ✅ 완료 |
| 관련 테스트 통과 (76/76) | ✅ 통과 |
| Docker 재빌드 | ✅ 성공 |
| Migration 적용 | ✅ `Migration completed` |
| Health Check | ✅ `status: ok`, `database: connected` |
| DB 컬럼 존재 확인 | ✅ 양쪽 테이블 `fetch_status` 정상 생성 |

**코드-스키마 정합성 복구 완료.** INSERT 구문에 `fetch_status`가 포함되어 있어도 DB에 컬럼이 존재하므로 트랜잭션 abort가 더 이상 발생하지 않는다.
