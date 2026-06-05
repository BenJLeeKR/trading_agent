# 장후 첫 1회 포지션 스냅샷 보장

## 배경

- 계좌 포지션 스냅샷의 마지막 기록이 `2026-06-04 15:27 KST`에서 멈춰 있었음
- 장후에도 `snapshot-sync`는 계속 실행됐지만, 현재 로직이 `after_hours=true`이면 포지션 조회를 무조건 건너뛰고 `cash-only`로만 동작했음
- 이 때문에 `15:30` 이후 KRX 종가가 반영된 포지션 스냅샷이 저장되지 않았음

## 원인

1. `run_ops_scheduler.py`의 `eod_snapshot_sync`와 `after_hours_snapshot_cycle`이 모두 `--after-hours`만 전달
2. `run_snapshot_sync_loop.py` / `snapshot_sync.py` / `KISSyncSnapshotProvider.fetch_snapshot()` 경로에서 `after_hours=true`이면 포지션 fetch를 항상 skip
3. 장후 첫 1회 full snapshot이라는 개념 자체가 없었음
4. 추가 버그:
   - `allow_after_hours_positions` override 분기를 넣은 뒤에도 `cp_result.positions`를 실제로 `raw_positions`에 대입하지 않아 포지션이 비어 있었음

## 수정 내용

### 1. 장후 포지션 허용 플래그 추가

- `allow_after_hours_positions: bool = False`를 다음 경로에 추가
  - `scripts/run_snapshot_sync_loop.py`
  - `src/agent_trading/services/snapshot_sync.py`
  - `src/agent_trading/brokers/koreainvestment/snapshot.py`

### 2. 장후 첫 1회 full snapshot 상태 관리

- `SchedulerState.after_hours_full_snapshot_done: bool = False` 추가
- `run_ops_scheduler.py`에서:
  - 장후 진입 시 플래그 리셋
  - `eod_snapshot_sync`는 `--allow-after-hours-positions`로 실행
  - 결과 요약에서 `total_positions_synced > 0`이면 `after_hours_full_snapshot_done=True`
  - 이후 after-hours cycle도 동일 플래그를 보고, 아직 성공한 full snapshot이 없으면 다시 full snapshot 시도
  - 성공 후에는 다시 `cash-only`로 복귀

### 3. provider 분기 버그 수정

- `KISSyncSnapshotProvider.fetch_snapshot()`에서
  - `after_hours and allow_after_hours_positions` 분기에서도
  - `cp_result.positions`를 실제 `raw_positions`에 대입하도록 수정

## 검증

### 테스트

```bash
pytest -q tests/brokers/koreainvestment/test_snapshot.py \
  tests/services/test_snapshot_sync.py \
  tests/scripts/test_run_ops_scheduler.py \
  -k 'after_hours or snapshot_command or allow_after_hours_positions'
```

- 결과: `10 passed`

### 정적 검증

```bash
python3 -m py_compile \
  src/agent_trading/brokers/koreainvestment/snapshot.py \
  src/agent_trading/services/snapshot_sync.py \
  scripts/run_snapshot_sync_loop.py \
  scripts/run_ops_scheduler.py
```

- 결과: 통과

## 기대 효과

- `15:30` 이후 최소 1회는 `positions + cash`가 함께 저장됨
- 장후 첫 full snapshot이 성공한 뒤에는 기존처럼 `cash-only`로 돌아가 budget 낭비를 막음
- 종가 반영 포지션 스냅샷 부재 문제를 구조적으로 해소

## 후속 확인 포인트

1. 다음 장후 cycle에서 `snapshot_sync_runs.positions_synced_total > 0`가 실제로 1회 이상 발생하는지 확인
2. `position_snapshots.snapshot_at` 최신값이 `15:30 KST` 이후로 저장되는지 확인
3. scheduler 재시작 직후에도 `after_hours_full_snapshot_done` 복원이 필요한지 운영 로그로 재평가

## 추가 조정

- 랜덤엔드 및 종가 반영 지연을 감안해 scheduler 기본 `market_close` 기준을 `15:30:00`에서 `15:30:30 KST`로 조정
- 따라서 end-of-day 진입 및 장후 첫 full snapshot 시도도 기본적으로 `15:30:30` 이후에 시작됨
