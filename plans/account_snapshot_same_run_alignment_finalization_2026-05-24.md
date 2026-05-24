# Account Snapshot Same-Run Alignment 최종 마무리

**작성일:** 2026-05-24

## 1. Same-Run 정합성 현재 상태

### 발견된 P0 버그
- `get_latest_sync_run_id()`가 `position_snapshots`만 참조 (`CashBalanceSnapshotRepository`에 해당 메서드 없음)
- after-hours cash-only sync run 데이터가 API에 절대 반영되지 않음
- 9/10 최근 sync run이 after-hours (cash-only) — 운영 영향 큼

### 수정 사항
1. `CashBalanceSnapshotRepository.get_latest_sync_run_id()` 메서드 추가 (Protocol + PostgreSQL + InMemory)
2. 5-way alignment_detail 로직 구현 (`account_snapshots.py`)
3. `AccountSnapshotResponse`에 `snapshot_sync_run_id` + `alignment_detail` 필드 추가
4. UI alignment 배지 5가지 상태별 개선 (한글 레이블 + 색상)

## 2. 적용한 API/UI/Read-Model 개선

### API (Backend)
- `GET /accounts/{account_id}/snapshot` 응답에 `snapshot_sync_run_id` 추가
- `alignment_detail` 필드로 5가지 상태 제공:
  - `same_run`: position + cash 동일 sync-run 기준 ✅
  - `after_hours_cash_updated`: position 기준 run보다 cash가 최신 (after-hours cash update)
  - `cash_only`: cash snapshot만 존재 (position 없음)
  - `partial_position_only`: position snapshot만 존재 (cash 없음)
  - `timestamp_proximity`: 명시적 sync-run 연결 없이 시간 기준 근사

### Read-Model
- `CashBalanceSnapshotRepository` Protocol 확장 (contracts.py)
- PostgreSQL 구현 (cash_balance_snapshots.py)
- InMemory 구현 (memory.py)

### UI (Frontend)
- `AccountSnapshotResponse` 타입 확장 (api.ts)
- 5가지 alignment 상태별 배지 표시:
  - 🟢 "동일 sync-run 기준" (same_run)
  - 🟢 "after-hours cash 업데이트 반영" (after_hours_cash_updated)
  - 🟡 "현금만 조회됨" (cash_only)
  - 🔵 "포지션 기준 조회" (partial_position_only)
  - 🟡 "시간 기준 근사" (timestamp_proximity)

## 3. 테스트 결과

### Backend 테스트
- 실행 명령어: `python3 -m pytest tests/api/test_inspection.py -v`
- 결과: **62 passed** (100% 통과, 1.15s 소요)

### Frontend 테스트
- 실행 명령어: `npx vitest run --reporter=verbose`
- 결과: **266 passed** across 16 test files (3.77s 소요)
  - accounts.test.tsx 관련 테스트 포함하여 모두 통과

### Docker Health Check
- API 상태: **healthy**
- Database: **connected**
- Runtime mode: **postgres**
- Scheduler: **healthy** (trading day)

## 4. 운영에서 어떻게 달라졌는지

### Before
- after-hours cash-only sync run → UI에서 position 기준 이전 sync-run의 cash 표시 (정합성 깨짐)
- `get_latest_sync_run_id()`가 position만 참조 → cash 최신 sync-run 무시
- alignment 상태 구분 불가 (항상 동일한 것으로 표시)

### After
- after-hours cash-only → `cash_only` 또는 `after_hours_cash_updated` 상태로 정확히 표시
- position + cash 동시 sync-run → `same_run`으로 정확히 표시
- 운영자가 alignment 상태를 UI에서 직접 확인 가능
- cash-only after-hours run의 cash 데이터가 API에 반영됨

## 5. 남은 후속 과제

없음 — Same-Run Alignment Phase 4 (테스트 + 검증 + 보고서) 완료.
