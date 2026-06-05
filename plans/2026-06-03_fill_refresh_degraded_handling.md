# 2026-06-03 fill-triggered snapshot refresh degraded 처리 기준 정리

## 목적

- `plans/[PRIORITY_MAP] remaining_work_priority_map.md`의
  `Fill 발생 후 position/cash refresh 자동화` 남은 세부 작업 중
  `refresh 중 quota 소진 시 degraded 처리 기준 명확화`를 1차 구현한다.
- fill-triggered snapshot refresh 결과가
  단순 성공/실패가 아니라
  **완전 수렴 / 일부 수렴(degraded) / 실패**
  로 구분되도록 만든다.

## 문제

기존 `snapshot_refresh_cb`는 `sync_account_snapshots()` 결과를 받아도
다음 정도만 로그로 남겼다.

```text
Snapshot refresh complete for account=...
positions=...
cash=...
```

한계:

1. `risk_limit_snapshot`이 같이 수렴했는지 알 수 없음
2. cash는 동기화됐지만 positions/orderable이 budget 때문에 일부 누락된 경우를
   별도로 구분하지 못함
3. `result.errors`가 있어도 “complete”로 보일 수 있음

즉, quota 부족으로 일부만 맞춘 경우를
운영자가 로그만 보고 바로 판단하기 어려웠다.

## 변경 내용

### 1. `SyncResult`에 `risk_limit_snapshot_synced` 추가

파일:
- `src/agent_trading/services/kis_snapshot_sync.py`
- `src/agent_trading/services/snapshot_sync.py`

변경:
- `SyncResult`에 `risk_limit_snapshot_synced: bool = False` 추가
- `sync_account_snapshots()`에서
  `risk_limit_snapshot_repo.add(...)` 성공 시
  `result.risk_limit_snapshot_synced = True` 설정

효과:
- fill-triggered refresh 결과가
  `positions / cash / risk_limit`
  세 축으로 모두 관측 가능해진다.

### 2. refresh callback 로그를 `complete / degraded / failed`로 구분

파일:
- `scripts/run_post_submit_sync_loop.py`

새 기준:

#### complete
- `result.errors == []`

로그 예시:

```text
Snapshot refresh complete for account=...
positions=2 cash=True risk_limit=True after_hours_cycle=False
```

#### degraded
- `result.errors`는 있지만
- `positions_synced > 0` 또는
- `cash_balance_synced == True` 또는
- `risk_limit_snapshot_synced == True`

즉, 일부는 맞췄지만 전부는 못 맞춘 상태

로그 예시:

```text
Snapshot refresh degraded for account=...
positions=0 cash=True risk_limit=False errors=1 after_hours_cycle=False
Snapshot refresh detail account=...: VTTC8908R budget exhausted
```

#### failed
- 동기화된 핵심 데이터가 하나도 없고
- 예외가 발생했을 때

이 경우는 기존처럼 `Snapshot refresh failed ...` warning 경로로 처리

### 3. 상세 에러 로그 제한

degraded 시:
- `result.errors[:5]`만 detail warning으로 출력

효과:
- sync loop 로그가 과도하게 길어지는 것을 방지
- 동시에 어떤 degraded 사유였는지는 남긴다

## 테스트

파일:
- `tests/services/test_snapshot_sync.py`
- `tests/scripts/test_run_post_submit_sync_loop.py`

### 추가 검증

1. `risk_limit_snapshot_synced`가 실제 `SyncResult`에 반영되는지
2. refresh callback이
   - broker-agnostic sync를 사용하고
   - dedupe되며
   - partial sync + errors 조합일 때
     `Snapshot refresh degraded ...` 로그를 남기는지

## 검증 결과

```bash
pytest -q tests/services/test_snapshot_sync.py tests/scripts/test_run_post_submit_sync_loop.py \
  -k 'risk_limit_snapshot or refresh_callback or parse_args_after_hours'
```

결과:
- `9 passed`

정적 검증:

```bash
python3 -m py_compile \
  src/agent_trading/services/kis_snapshot_sync.py \
  src/agent_trading/services/snapshot_sync.py \
  scripts/run_post_submit_sync_loop.py \
  tests/scripts/test_run_post_submit_sync_loop.py
```

결과:
- 통과

## 효과

이제 fill-triggered refresh는 다음처럼 해석 가능하다.

1. `complete`
   - positions/cash/risk_limit이 에러 없이 수렴
2. `degraded`
   - 일부 핵심 데이터는 맞췄지만 budget/API 이슈로 완전 수렴은 아님
3. `failed`
   - refresh 자체가 동작하지 못함

즉, 운영자는 “budget 때문에 일부만 맞췄다”와
“진짜 refresh 실패”를 구분할 수 있다.

## 다음 작업

1. 장중 실데이터에서 degraded refresh 발생 빈도 측정
2. `orderable_amount` 수렴 여부를 별도 관측값으로 노출할지 검토
3. fill-triggered refresh 이후 sizing/guard 재평가 timing 측정
