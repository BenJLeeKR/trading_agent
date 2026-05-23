# Snapshot Sync `summary_json` Runtime 미반영 문제 분석 및 수정 보고서

**작성일:** 2026-05-23  
**관련자:** @Roo

---

## 1. 문제

로컬 소스 파일(`scripts/run_snapshot_sync_loop.py`, `scripts/sync_kis_snapshots.py`)에는  
`get_budget_fallback_counters()` 호출과 `summary_json=counters` 전달이 이미 추가되어 있었으나,  
실제 실행되는 Docker 컨테이너에서는 `asyncpg.exceptions.DataError`가 발생하여  
`snapshot_sync_runs.summary_json`이 계속 `NULL`로 저장되었다.

### 증상

- `run_snapshot_sync_loop.py --max-cycles 1` 실행 시 아래 에러 발생:
  ```
  asyncpg.exceptions.DataError: invalid input for query argument $19:
  {'VTTC8908R_pre_check': 1, ...} (expected str, got dict)
  ```
- 이 에러로 인해 DB 트랜잭션이 롤백되어 해당 sync run row 자체가 INSERT되지 않음
- 이전에 정상 INSERT된 row들은 `summary_json`이 `NULL`인 상태

---

## 2. 직접 원인: asyncpg JSONB 코덱 불일치

**`PostgresSnapshotSyncRunRepository.add()`** 에서 `summary_json` (Python `dict`)을  
`json.dumps()` 없이 asyncpg에 직접 전달했기 때문.

```python
# ❌ 수정 전 (snapshot_sync_runs.py:62)
run.summary_json,

# ✅ 수정 후
json.dumps(run.summary_json) if run.summary_json is not None else None,
```

### asyncpg JSONB 처리 방식

asyncpg의 `jsonb` 코덱은 Python `str` (JSON-encoded string)을 기대하며,  
Python `dict`를 직접 받지 못한다(`TypeError: expected str, got dict`).

동일 코드베이스 내 다른 Repository들에서는 모두 `json.dumps()`를 사용:

| Repository | 파일 | 처리 방식 |
|---|---|---|
| `reconciliation` | `reconciliation.py:38` | `json.dumps(run.summary_json) if ...` |
| `audit_logs` | `audit_logs.py:44-45` | `json.dumps(obj) if obj is not None else None` |
| `trade_decisions` | `trade_decisions.py:107-122` | `json.dumps(...)` |
| `risk_limit_snapshots` | `risk_limit_snapshots.py:53-55` | `json.dumps(...)` |
| `agent_runs` | `agent_runs.py:46` | `json.dumps(...) if ... is not None else None` |
| **`snapshot_sync_runs`** | **`snapshot_sync_runs.py:62`** | **`run.summary_json`** (❌ 누락) |

---

## 3. 영향 범위

### 서비스/컨테이너

| 컨테이너 | bind mount | 영향 |
|---|---|---|
| `agent_trading-ops-scheduler` | `./scripts:/app/scripts` ✅ | `summary_json` 저장 실패 (DataError) |
| `agent_trading-snapshot-sync-1` | `./scripts:/app/scripts` ✅ | `summary_json` 저장 실패 (DataError) |
| `agent_trading-app-1` | `./scripts:/app/scripts` ✅ | 간접적 (스크립트 import 경로로만 사용) |

### DB

- `trading.snapshot_sync_runs.summary_json` 컬럼: 2026-05-23 11:20 UTC 이전 모든 row가 `NULL`
- migration `0011_add_snapshot_sync_runs.sql`에서 `summary_json JSONB` 컬럼은 정상 생성됨

### API/UI

- API `/snapshot-sync-runs` 엔드포인트: `summary_json` 필드는 DB 값 그대로 반환
- 기존 row: `summary_json: null`, 신규 row: `summary_json: {...}`

---

## 4. 해결 방법

### 4.1 핵심 수정

[`src/agent_trading/repositories/postgres/snapshot_sync_runs.py`](../../src/agent_trading/repositories/postgres/snapshot_sync_runs.py:28)

```python
import json  # ← 추가

async def add(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity:
    row = await self._tx.connection.fetchrow(
        """... summary_json, ... VALUES (... $19, ...)""",
        ...
        json.dumps(run.summary_json) if run.summary_json is not None else None,  # ← 수정
        ...
    )
```

### 4.2 검증

```bash
# 1회 sync 실행
docker compose run --rm ops-scheduler python3 scripts/run_snapshot_sync_loop.py --max-cycles 1

# DB 확인
docker compose exec db psql -U trading -d trading \
  -c "SELECT snapshot_sync_run_id, status, summary_json, started_at \
      FROM trading.snapshot_sync_runs ORDER BY started_at DESC LIMIT 3;"

# API 확인
docker compose exec api python3 -c "
import urllib.request, json, os
token = os.environ.get('INSPECTION_API_TOKEN', 'dev-token')
req = urllib.request.Request('http://127.0.0.1:8000/snapshot-sync-runs?limit=3')
req.add_header('Authorization', f'Bearer {token}')
r = urllib.request.urlopen(req)
data = json.loads(r.read())
for run in data:
    print(f'summary_json={run.get(\"summary_json\")}')
"
```

---

## 5. 재발 방지

### 5.1 근본 원인: JSONB 컬럼 처리 누락

`PostgresSnapshotSyncRunRepository.add()`가 `summary_json` 파라미터 추가 시  
`json.dumps()` 직렬화를 함께 처리하지 않았다.  
asyncpg의 JSONB 코덱이 `dict` → `str` 변환을 자동으로 수행하지 않음.

### 5.2 방지 대책

| # | 대책 | 설명 |
|---|---|---|
| 1 | **신규 JSONB 컬럼 추가 시 Repository 템플릿 리뷰** | 기존 repo(`reconciliation`, `audit_logs`, `trade_decisions`)에서 `json.dumps()` 패턴을 반드시 참조 |
| 2 | **asyncpg JSONB 핸들링 문서화** | 모든 `dict` → `str(json.dumps)` 직렬화가 필요함을 팀 내 공유 |
| 3 | **통합 테스트 강화** | `summary_json` 필드가 포함된 `build_sync_run_entity()` → DB 저장 → 조회 검증 테스트 케이스 추가 |
| 4 | **CI/CD 파이프라인에서 실제 DB 연동 테스트** | staging 환경에서 실제 asyncpg를 통한 JSONB 저장/조회 검증 |

### 5.3 Docker compose volume mount 매트릭스

| 서비스 | `context` / `build` | `./scripts` | `./src` | `./logs` | `./data` | `.cache` | 비고 |
|---|---|---|---|---|---|---|---|
| **api** | `Dockerfile.api` | ✅ | ❌ | ❌ | ❌ | ❌ | COPY 방식 |
| **app** | `Dockerfile` | ❌ | ❌ | ❌ | ❌ | ❌ | bind mount 없음 |
| **snapshot-sync** | `Dockerfile.snapshot-sync` | ✅ | ✅ | ❌ | ❌ | ✅ | restart: "no" |
| **ops-scheduler** | `Dockerfile` | ✅ | ✅ | ✅ | ✅ | ✅ | restart: unless-stopped |
| **reconciliation-worker** | `Dockerfile` | ✅ | ✅ | ❌ | ❌ | ✅ | - |

> `ops-scheduler`와 `snapshot-sync`는 bind mount(`./scripts:/app/scripts`)로 동기화되므로  
> 별도의 이미지 재빌드 없이 스크립트 변경사항이 즉시 반영됨.  
> `app` 서비스는 bind mount가 없어 `docker compose build app` 필요.

---

## 6. 수정 파일 요약

| 파일 | 변경 내용 |
|---|---|
| [`src/agent_trading/repositories/postgres/snapshot_sync_runs.py`](../../src/agent_trading/repositories/postgres/snapshot_sync_runs.py) | `import json` 추가, `run.summary_json` → `json.dumps(...)` 직렬화 |
| [`plans/fix_runtime_mismatch_for_snapshot_sync_summary_json_persistence_and_ui_visibility_2026-05-23.md`](./fix_runtime_mismatch_for_snapshot_sync_summary_json_persistence_and_ui_visibility_2026-05-23.md) | 본 보고서 |

---

## 7. DB 상태 (수정 후)

### 최신 3개 row

```
         snapshot_sync_run_id         |  status   |                                                  summary_json
--------------------------------------+-----------+---------------------------------------------------------------------------------------------------------------
 31fcdb0c-c640-42fd-a514-faf2e46fc7ee | completed | {"after_hours_skip": 0, "VTTC8908R_pre_check": 1, "VTTC8908R_api_failure": 0, "VTTC8908R_budget_exhausted": 0}
 da984204-67a0-428b-a09f-fe0f41f5240e | completed | <NULL>  ← 수정 전 데이터
 76a16793-434d-4924-bbd6-13735cd8e69c | completed | <NULL>  ← 수정 전 데이터
```

> `summary_json`은 수정 시점 이후 신규 생성되는 sync run부터 정상 저장됨.  
> 기존 `NULL` row들은 백필(backfill)이 필요한 경우 별도 작업 필요.
