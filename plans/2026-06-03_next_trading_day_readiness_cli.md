# 2026-06-03 다음 거래일 readiness CLI 추가

## 목적

- `2026-06-03_remaining_work_priority_map.md`의
  `다음 거래일 장중 실운영 검증`을 실제 실행 가능한 형태로 준비한다.
- 비거래일에도 미리 돌려볼 수 있는 read-only CLI로,
  다음 거래일 오픈 전에 점검해야 할 핵심 신호를 한 번에 모은다.

## 추가한 스크립트

- `scripts/evaluate_next_trading_day_readiness.py`

## 평가 항목

### 1. 차단성 미해결 주문

- 대상 상태:
  - `pending_submit`
  - `submitted`
  - `acknowledged`
  - `reconcile_required`
- 하나라도 남아 있으면 `BLOCKED`

### 2. 부분체결 잔존

- 대상 상태:
  - `partially_filled`
- 남아 있으면 `WARN`

### 3. `truth_probe_fill_snapshot_incomplete`

- linked fill snapshot row는 있지만 아직 positive fill quantity가 없어
  다음 fill sync를 기다리는 주문 수
- 남아 있으면 `WARN`

### 4. snapshot sync freshness

- `snapshot_sync_runs.get_sync_health_summary()`
- stale 이면 `BLOCKED`

### 5. fill sync freshness

- `fill_sync_runs.get_sync_health_summary()`
- stale / 최근 실패 / last_status failed 이면 `BLOCKED`

### 6. fill sync retry

- 최근 fill sync가 retry로 복구된 경우 `WARN`

### 7. 비거래일 완화

- `market_sessions.run_date == target_date` 이고 `is_trading_day=false` 이면:
  - `snapshot sync stale`
  - `fill sync stale`
  - `fill sync retry`
  는 **차단 사유로 보지 않는다**
- 이유:
  - 비거래일에는 장중 체결/동기화가 기대되지 않으므로
    stale 신호만으로 readiness를 `BLOCKED`로 만들면 false alarm이 된다.
- 단, 미해결 주문(`submitted`, `reconcile_required` 등)은
  비거래일에도 계속 `BLOCKED`로 본다.

## overall 상태 규칙

- 하나라도 `BLOCKED` → `overall_status=BLOCKED`
- `BLOCKED`는 없고 `WARN`이 하나라도 있으면 → `WARN`
- 전부 정상 → `READY`

## 출력

- `--output text` (기본)
- `--output json`

## 검증

- `tests/scripts/test_evaluate_next_trading_day_readiness.py`
  - READY
  - BLOCKED
  - WARN

## 기대 효과

- 다음 거래일 장중 검증 전,
  운영자가 `미해결 주문 / truth probe pending / snapshot freshness / fill sync retry`
  를 하나의 명령으로 확인할 수 있다.
- 이후 실제 장중 실측 때는 이 스크립트 출력과 runtime 로그를 나란히 비교하면 된다.
