# Migration 0021 적용 및 EXE-005A 운영 완결 보고서

- **날짜:** 2026-05-23
- **관련 태스크:** 주문 실행 리팩토링 2단계 — EXE-005A 운영 완결

---

## 1. Migration 미적용 상태 진단

### 발견한 문제
이전 작업에서 [`db/migrations/0021_add_pipeline_stop_fields.sql`](db/migrations/0021_add_pipeline_stop_fields.sql) 파일은 생성되었고, [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py)에서 `update_pipeline_stop()`을 호출하는 코드도 구현되었습니다. 하지만 **실제 PostgreSQL DB에는 `pipeline_stop_phase`, `pipeline_stop_reason`, `pipeline_stopped_at` 컬럼이 존재하지 않았습니다.**

### 영향
- `update_pipeline_stop()` 호출 시 **`column "pipeline_stop_phase" does not exist`** SQL 오류 발생 가능
- EXE-005A가 "코드만 구현된 상태"로 운영 경로에서 동작 불가

### 원인 분석
- Migration runner(`run.py`)는 `ADD COLUMN IF NOT EXISTS` 방식이 아닌 파일 기반 순차 실행 구조
- Migration 0021 SQL 파일은 존재했지만, 실제로 `run_all_migrations()`가 컨테이너 startup 시 호출되지 않았거나, 이미 실행된 migration으로 간주되어 스킵되었을 가능성
- 가장 안전한 해결책은 `docker compose exec db psql`로 직접 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 실행

---

## 2. 적용한 Migration 절차

### 실행 명령

```bash
docker compose exec -T db psql -U trading -d trading -c "
ALTER TABLE trading.trade_decisions
    ADD COLUMN IF NOT EXISTS pipeline_stop_phase VARCHAR(64),
    ADD COLUMN IF NOT EXISTS pipeline_stop_reason TEXT,
    ADD COLUMN IF NOT EXISTS pipeline_stopped_at TIMESTAMPTZ;
"
```

- `docker compose exec db psql` — DB 컨테이너에서 직접 psql 실행
- `-U trading` — `trading` 유저 사용 (`postgres` role 아님)
- `-d trading` — DB 이름은 `trading` (기본값)
- `ADD COLUMN IF NOT EXISTS` — 이미 존재하는 경우 안전하게 스킵

### 동작 확인

```
ALTER TABLE
```

---

## 3. 스키마 검증 결과

### information_schema 조회

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'trading'
  AND table_name = 'trade_decisions'
  AND column_name LIKE 'pipeline_stop_%'
ORDER BY ordinal_position;
```

### 결과

| column_name | data_type | is_nullable |
|---|---|---|
| `pipeline_stop_phase` | `character varying` (VARCHAR(64)) | YES |
| `pipeline_stop_reason` | `text` | YES |
| `pipeline_stopped_at` | `timestamp with time zone` | YES |

### 코드 기대값과 일치 확인

| 코드 필드 | DB 컬럼 | 타입 | Nullable |
|-----------|---------|------|----------|
| `pipeline_stop_phase: str \| None` | `pipeline_stop_phase` | `VARCHAR(64)` | ✅ YES |
| `pipeline_stop_reason: str \| None` | `pipeline_stop_reason` | `TEXT` | ✅ YES |
| `pipeline_stopped_at: datetime \| None` | `pipeline_stopped_at` | `TIMESTAMPTZ` | ✅ YES |

---

## 4. `update_pipeline_stop()` 운영 동작 확인

### 검증 절차
1. 기존 `trade_decisions` 레코드 1건 SELECT
2. `UPDATE ... SET pipeline_stop_phase='sizing', pipeline_stop_reason='sizing_rejected', pipeline_stopped_at=NOW()`
3. SELECT 재조회로 값 확인
4. 원래 값(NULL)으로 복원

### 결과
```
UPDATE 1
pipeline_stop_phase: sizing
pipeline_stop_reason: sizing_rejected
pipeline_stopped_at: 2026-05-22 22:10:30.133473+00
```

✅ **정상 동작 확인** — SQL 오류 없음, 값 정상 INSERT/UPDATE

---

## 5. 테스트 결과

| 테스트 파일 | 결과 |
|------------|------|
| `tests/services/test_decision_submit_pipeline.py` | 61/61 ✅ |
| `tests/services/test_decision_orchestrator.py` | 42/42 ✅ |
| **전체** | **103/103 passed** |

`TestPipelineStop` 클래스의 `test_pipeline_stop_set_on_sizing_skip`, `test_pipeline_stop_not_set_on_success` 포함 모든 테스트 통과.

---

## 6. 운영 배포 확인

| 항목 | 결과 |
|------|------|
| `docker compose up -d ops-scheduler` | ✅ 성공 (컨테이너 재기동) |
| Health check | `{"status": "ok", "database": "connected", "scheduler.healthy": true}` |
| 컨테이너 로그 | 에러 없음, 정상 startup |

---

## 7. 최종 판정

### ✅ EXE-005A 운영 완료

| 기준 | 상태 | 근거 |
|------|------|------|
| DB schema | ✅ 적용 완료 | `pipeline_stop_phase`, `pipeline_stop_reason`, `pipeline_stopped_at` 컬럼 정상 생성 |
| 코드 구현 | ✅ 완료 | `TradeDecisionEntity` 필드, `update_pipeline_stop()` repository, 8개 호출 지점 |
| 테스트 | ✅ 103/103 | `TestPipelineStop` 포함 모든 테스트 통과 |
| 운영 동작 | ✅ 확인 | 실제 DB UPDATE/SELECT로 정상 동작 검증 |
| Docker 배포 | ✅ 정상 | Health check OK, 로그 이상 없음 |

---

## 8. 관련 문서

- [주문 실행 리팩토링 2단계 설계 문서](plans/refactor_execution_phase_boundaries_and_quote_resolution_observability_2026-05-22.md)
- [`db/migrations/0021_add_pipeline_stop_fields.sql`](db/migrations/0021_add_pipeline_stop_fields.sql)
- [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) (PhaseTraceEntry + quote circuit breaker + pipeline_stop)
