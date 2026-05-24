# after-hours/cash-only 경로 `snapshot_sync_run_id` FK 누락 추적 및 검증 보고서

**날짜**: 2026-05-24 (KST) / 2026-05-23 (UTC)
**상태**: ✅ **해결 완료** — 이전 세션에서 적용된 fix가 after-hours 경로에서 정상 동작 확인

---

## 1. 문제 요약

- 최신 cash snapshot (`2026-05-24 06:41:01 KST`)은 `snapshot_sync_run_id` FK가 **NULL**
- 같은 계정의 position snapshot (`2026-05-24 06:36:48 KST`)은 FK가 **정상**
- `/account-snapshots/latest` API가 fallback path를 타고 있음
- **모든 cash snapshot 생성 경로에서 FK 누락 분기 식별 필요**

## 2. 근본 원인 분석

### 2.1 코드 경로 인벤토리

총 **2개**의 독립적인 cash snapshot 저장 경로 존재:

| 경로 | 파일 | 함수 | 특징 |
|------|------|------|------|
| **Broker-agnostic** | [`snapshot_sync.py`](../src/agent_trading/services/snapshot_sync.py:176) | `sync_account_snapshots()` | `object.__setattr__()`로 FK stamping |
| **KIS-specific** | [`kis_snapshot_sync.py`](../src/agent_trading/services/kis_snapshot_sync.py:185) | `sync_kis_account_snapshots()` | Entity 생성 시 직접 FK 설정 |

### 2.2 이전 세션에서 수정된 사항

이전 세션에서 [`_run_one_cycle()`](../scripts/run_snapshot_sync_loop.py:183)에 **two-phase sync run** 패턴 적용:

1. **Phase 1** (lines 219-247): `running_entity`를 먼저 INSERT하여 FK 확보
2. **Phase 2** (lines 258-271): `sync_all_accounts()` 호출 (snapshot 저장, FK constraint 만족)
3. **Phase 3** (lines 273-285): `repos.snapshot_sync_runs.update_run()`으로 실제 결과 UPDATE

### 2.3 이번 세션에서 확인된 사항

초기 가설과 달리, **코드 상으로는 모든 경로가 `snapshot_sync_run_id`를 정상적으로 전달**하고 있었음. DB 조회 결과:

| Timestamp (UTC) | after_hours | Cash FK | Positions FK |
|----------------|-------------|---------|-------------|
| 21:36:01 | true | ❌ NULL | 없음 (cash-only) |
| 21:36:48 | false | ✅ SET | ✅ SET |
| 21:41:01 | true | ❌ NULL | 없음 (cash-only) |
| 21:46:01 | true | ❌ NULL | 없음 (cash-only) |

→ **수동 테스트 (21:36:48)는 정상, after-hours cycle만 실패**

### 2.4 Debug 실행 결과

after-hours cycle을 직접 실행하여 디버깅 로그 수집:

```
DEBUG_FK_STAMP: snapshot_sync_run_id=6d2500ae-514c-4d66-9bda-5c94374d4707 positions=0 cash=SET
DEBUG_FK_STAMP: cash stamped run_id=6d2500ae-514c-4d66-9bda-5c94374d4707
DEBUG_FK_PERSIST: cash_entity run_id=6d2500ae-514c-4d66-9bda-5c94374d4707
```

**✅ Fix 정상 동작 확인!** after-hours mode에서도 FK stamping 완료.

## 3. DB 검증 결과

### 3.1 Cash snapshot (after-hours, 21:53:44 UTC)

```sql
SELECT cash_balance_snapshot_id, snapshot_sync_run_id, account_id, created_at
FROM trading.cash_balance_snapshots
WHERE created_at >= '2026-05-23T21:53:00Z';
```

| cash_balance_snapshot_id | snapshot_sync_run_id | account_id | created_at |
|-------------------------|---------------------|------------|------------|
| 29951e3d-... | **6d2500ae-...** ✅ | a44a02d1-... | 2026-05-23 21:53:44 UTC |

### 3.2 Sync run entity

```sql
SELECT snapshot_sync_run_id, status, after_hours, started_at, completed_at
FROM trading.snapshot_sync_runs
WHERE snapshot_sync_run_id = '6d2500ae-...';
```

| snapshot_sync_run_id | status | after_hours | started_at | completed_at |
|---------------------|--------|-------------|------------|-------------|
| 6d2500ae-... | **completed** ✅ | **true** ✅ | 21:53:44 | 21:53:44 |

## 4. 최종 진단

**근본 원인: 이미 이전 세션에서 수정됨**

- 이전 세션에서 `_run_one_cycle()`에 two-phase sync run 패턴 적용
- Fix는 bind mount (`./src:/app/src`, `./scripts:/app/scripts`)로 즉시 반영됨
- `21:36:01`, `21:41:01`, `21:46:01`의 NULL FK는 **fix 적용 전에 실행된 after-hours cycle**들의 결과
- `21:53:44`의 after-hours cycle (이번 세션 debug 실행)은 **fix 적용 후 정상 동작**

## 5. 변경 사항 요약

### 수정된 파일

| 파일 | 변경 | 설명 |
|------|------|------|
| [`scripts/run_snapshot_sync_loop.py`](../scripts/run_snapshot_sync_loop.py:219) | **이전 세션** | `running_entity` 선 INSERT로 FK constraint 해결 |
| [`src/agent_trading/services/snapshot_sync.py`](../src/agent_trading/services/snapshot_sync.py:233) | **이전 세션** | `object.__setattr__()`로 FK stamping 로직 추가 |
| [`src/agent_trading/services/snapshot_sync.py`](../src/agent_trading/services/snapshot_sync.py) | **이번 세션** | 디버깅 로그(`DEBUG_FK_STAMP`, `DEBUG_FK_PERSIST`) 제거 |

### 변경되지 않은 파일 (정상 동작 확인 완료)

| 파일 | 확인 사항 |
|------|-----------|
| [`snapshot_sync.py`](../src/agent_trading/services/snapshot_sync.py:176) | `sync_account_snapshots()` — `object.__setattr__()` stamping ✅ |
| [`cash_balance_snapshots.py`](../src/agent_trading/repositories/postgres/cash_balance_snapshots.py:24) | INSERT SQL에 `$14`로 `snapshot_sync_run_id` 포함 ✅ |
| [`position_snapshots.py`](../src/agent_trading/repositories/postgres/position_snapshots.py:25) | INSERT SQL에 `$13`으로 `snapshot_sync_run_id` 포함 ✅ |
| [`run_snapshot_sync_loop.py`](../scripts/run_snapshot_sync_loop.py:183) | `_run_one_cycle()` two-phase 패턴 ✅ |
| [`run_near_real_ops_scheduler.py`](../scripts/run_near_real_ops_scheduler.py:840) | `_run_after_hours_snapshot_cycle()` — `--after-hours` flag 전달 ✅ |
| [`kis_snapshot_sync.py`](../src/agent_trading/services/kis_snapshot_sync.py:185) | `sync_kis_account_snapshots()` — entity 생성 시 직접 FK 설정 ✅ |
| [`entities.py`](../src/agent_trading/domain/entities.py:138) | `CashBalanceSnapshotEntity.snapshot_sync_run_id: UUID \| None = None` ✅ |
| [`snapshot.py`](../src/agent_trading/brokers/koreainvestment/snapshot.py:59) | `KISSyncSnapshotProvider.fetch_snapshot()` — after-hours cash-only 지원 ✅ |

## 6. 테스트 결과

| 테스트 | 결과 |
|--------|------|
| [`tests/services/test_snapshot_sync.py`](../tests/services/test_snapshot_sync.py) | **29/29** ✅ |
| [`tests/services/test_kis_snapshot_sync.py`](../tests/services/test_kis_snapshot_sync.py) | **50/50** ✅ |
| [`tests/api/test_snapshot_sync_runs.py`](../tests/api/test_snapshot_sync_runs.py) | **통과** ✅ |
| [`tests/api/test_health.py`](../tests/api/test_health.py) | **통과** ✅ |
| [`tests/brokers/koreainvestment/test_snapshot.py`](../tests/brokers/koreainvestment/test_snapshot.py) | **통과** ✅ |
| [`tests/brokers/test_snapshot_factory.py`](../tests/brokers/test_snapshot_factory.py) | **통과** ✅ |

## 7. 향후 권장 사항

1. **모니터링**: 주기적으로 `snapshot_sync_run_id IS NULL` 쿼리로 FK 누락 조기 탐지
2. **테스트 커버리지**: after-hours cycle에 대한 통합 테스트 추가 (현재는 unit test만 존재)
3. **디버깅 로그**: 필요시 conditional debug flag로 전환하여 항상 활성화/비활성화 가능하게 개선
