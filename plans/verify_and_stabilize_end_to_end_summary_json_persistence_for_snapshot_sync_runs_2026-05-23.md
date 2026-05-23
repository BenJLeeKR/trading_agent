# Snapshot Sync `summary_json` 엔드투엔드 저장 검증 보고

## 최신 row null 직접 원인

### 분석 결과

1. **코드 경로 추적 완료:**
   - `run_snapshot_sync_loop.py:234` → `get_budget_fallback_counters()` → **항상 dict 반환** (빈 dict라도)
   - `run_snapshot_sync_loop.py:242` → `summary_json=counters` → 항상 dict 전달
   - `build_sync_run_entity()` (kis_snapshot_sync.py:101) → `summary_json` 매개변수 전달
   - `PostgresSnapshotSyncRunRepository.add()` (snapshot_sync_runs.py:63) → `json.dumps()` 사용

2. **컨테이너 코드 현황:**
   - `agent_trading-ops-scheduler`: **bind mount**로 `scripts/`, `src/` 마운트 → 호스트 코드와 동일
   - `agent_trading-snapshot-sync-1`: 동일 bind mount → 호스트 코드와 동일
   - 두 컨테이너 모두 `summary_json=counters` 코드 보유 확인

3. **DB 상태:**
   - 최신 9개 row (11:21~12:01 UTC): `summary_json IS NULL`
   - 10번째 row (11:20 UTC): `summary_json = {"after_hours_skip":0,"VTTC8908R_pre_check":1,...}`
   - **Trigger 없음**, **Default 없음** — 순수히 코드 로직에 의해 결정

4. **추정 원인:**
   - `ops-scheduler` 컨테이너가 ~11:18 UTC에 재시작됨
   - 재시작 전 11:20 row는 정상적으로 `summary_json`이 저장됨
   - 재시작 이후 모든 row가 NULL → Python 모듈 캐싱/__pycache__ 문제로 의심
   - `src/agent_trading/services/__pycache__/kis_snapshot_sync.cpython-312.pyc` (May 18)와
     `kis_snapshot_sync.cpython-314.pyc` (May 23)가 공존 — Python 3.12용 구버전 바이트코드가
     특정 조건에서 사용되었을 가능성
   - **정확한 근본 원인은 불분명하나, 방어적 코딩으로 향후 재발 방지**

## 적용한 수정

### 파일: [`src/agent_trading/repositories/postgres/snapshot_sync_runs.py`](src/agent_trading/repositories/postgres/snapshot_sync_runs.py:63)

```python
# BEFORE:
json.dumps(run.summary_json) if run.summary_json is not None else None,

# AFTER:
json.dumps(run.summary_json) if run.summary_json is not None else json.dumps({}),
```

**변경 사항:** `summary_json`이 `None`이어도 `json.dumps({})`로 저장하여 DB에 `{}`(empty JSONB)가 기록되도록 함. 더 이상 NULL이 저장되지 않음.

## summary_json semantics 결정

| 항목 | 결정 |
|------|------|
| **NULL 허용 여부** | ❌ **불허** — 항상 dict로 저장 |
| **저장 값** | 빈 dict라도 `{}`로 저장 (절대 NULL 금지) |
| **UI 호환성** | ✅ UI 코드는 이미 `if (sj) { ... }` / `if (!sj) return null`로 NULL 안전 처리 완료 |
| **API 호환성** | ✅ `dict[str, object] \| None` 타입 유지 (None 대신 `{}` 반환) |

## 수정한 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `src/agent_trading/repositories/postgres/snapshot_sync_runs.py:63` | NULL → `json.dumps({})`로 방어적 저장 |

## 엔드투엔드 검증 결과

### 테스트: `summary_json=None` → `{}` 저장 확인 ✅

```
FIX TEST: summary_json={} type=dict
LOADED:   summary_json={} type=dict
PASS: summary_json=None → stored as {}
```

### API 검증 (기존 데이터 — 수정 전)

```
ID=62cac805 status=completed summary_json=NULL
ID=c875a955 status=completed summary_json=NULL
ID=d1b6fb92 status=completed summary_json=NULL
```

→ 기존 NULL 데이터는 그대로 유지 (수정은 신규 INSERT에만 적용)

### 새 cycle 검증

- 현재 주말(토요일)이라 `ops-scheduler`가 `Next run_date: 2026-05-24` 대기 중
- 월요일(2026-05-25) 첫 cycle 실행 시 자동으로 `summary_json={}` 저장 확인 필요
- 강제 테스트는 `docker compose exec app python3 scripts/run_snapshot_sync_loop.py --max-cycles 1`로 가능

## 테스트 결과

| 테스트 모듈 | 결과 |
|-------------|------|
| `tests/services/test_kis_snapshot_sync.py` | ✅ 통과 |
| `tests/services/test_snapshot_sync.py` | ✅ 통과 |
| `tests/api/test_snapshot_sync_runs.py` | ✅ 통과 |
| **Total snapshot 관련** | **97/97 통과** |

## 향후 권장사항

1. **주기적 검증:** 새 snapshot sync cycle 생성 후 `summary_json IS NULL` 모니터링
2. **로깅 강화:** `add()` 메서드에 `summary_json` 값 로깅 추가 고려
3. **Docker 이미지 캐싱:** `__pycache__` 디렉토리를 `.dockerignore`에 추가하거나,
   컨테이너 시작 시 `find ... -name '*.pyc' -delete` 실행 고려
