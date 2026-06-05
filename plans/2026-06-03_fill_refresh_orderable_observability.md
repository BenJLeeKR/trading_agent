# 2026-06-03 fill-triggered refresh의 `orderable_amount` 관측성 보강

## 목적

- `plans/2026-06-03_remaining_work_priority_map.md`의
  `Fill 발생 후 position/cash refresh 자동화` 세부 작업 중
  `cash / positions / orderable amount 갱신 우선순위 정리`
  를 한 단계 더 진행한다.
- fill-triggered snapshot refresh가
  `cash는 동기화됐지만 orderable_amount는 비어 있는 상태`
  를 별도로 드러내도록 만든다.

## 문제

기존 refresh callback 로그는 대략 다음 정도만 남겼다.

```text
positions=...
cash=True/False
risk_limit=True/False
```

한계:

1. BUY sizing의 실제 우선 현금 source는 `orderable_amount`인데,
   refresh 결과에서 이 값이 확보됐는지 바로 알 수 없었다.
2. `cash_balance_synced=True`라도
   `orderable_amount is None`이면 BUY sizing 품질이 낮아질 수 있는데,
   기존 로그에서는 `complete`처럼 보일 수 있었다.

즉, 계좌 truth가 “현금 총액은 맞았지만 실제 주문가능금액은 아직 비었는지”를
운영자가 구분하기 어려웠다.

## 변경 내용

### 1. `SyncResult`에 `orderable_amount_synced` 추가

파일:
- `src/agent_trading/services/kis_snapshot_sync.py`

변경:
- `SyncResult.orderable_amount_synced: bool = False` 추가

### 2. cash snapshot persist 시 `orderable_amount` 동기화 여부 반영

파일:
- `src/agent_trading/services/snapshot_sync.py`

변경:
- `cash_balance_snapshot_repo.add(cash)` 성공 시
  `result.orderable_amount_synced = (cash.orderable_amount is not None)`

의미:
- cash row는 저장됐지만 `orderable_amount`가 비어 있으면
  이 값은 `False`

### 3. refresh callback degraded 기준 보강

파일:
- `scripts/run_post_submit_sync_loop.py`

새 기준:

- 기존 degraded:
  - `result.errors`가 있는 경우
- 추가 degraded:
  - `cash_balance_synced == True` 이지만
  - `orderable_amount_synced == False`

즉:
- cash는 확보했지만 BUY sizing에 중요한 `orderable_amount`는 아직 비어 있으면
  `Snapshot refresh degraded ...`로 본다.

### 4. 로그 항목 확장

이제 refresh 로그에는 다음이 모두 표시된다.

- `positions`
- `cash`
- `orderable`
- `risk_limit`
- `errors`
- `after_hours_cycle`

예시:

```text
Snapshot refresh degraded for account=...
positions=0 cash=True orderable=False risk_limit=True errors=0 after_hours_cycle=False
```

## 테스트

파일:
- `tests/services/test_snapshot_sync.py`
- `tests/scripts/test_run_post_submit_sync_loop.py`

### 추가한 검증

1. cash snapshot에 `orderable_amount`가 있으면
   `result.orderable_amount_synced == True`
2. `fetch_positions=False` + cash row만 저장된 케이스에서
   `orderable_amount`가 없으면 `False`
3. refresh callback이
   - `cash=True`
   - `orderable=False`
   - `risk_limit=True`
   조합일 때 `degraded` 로그를 남기는지 검증

## 검증 결과

```bash
pytest -q tests/services/test_snapshot_sync.py tests/scripts/test_run_post_submit_sync_loop.py \
  -k 'orderable_amount_synced or refresh_callback or risk_limit_snapshot or parse_args_after_hours'
```

결과:
- `11 passed`

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

이제 fill-triggered refresh 결과는 다음 관점으로 읽을 수 있다.

1. `cash` 확보 여부
2. `orderable_amount` 확보 여부
3. `risk_limit` 확보 여부
4. 일부만 수렴한 degraded 상태인지 여부

즉, 이후 BUY sizing 품질에 영향을 줄 수 있는
`cash는 맞았지만 orderable_amount는 아직 비어 있음`
상태를 운영 로그에서 바로 확인할 수 있다.

## 다음 작업

1. 장중 실데이터에서 `orderable=False` degraded 빈도 측정
2. `FILL_SNAPSHOT_INCOMPLETE` 주문의 후속 수렴 경로 정리
3. 필요 시 `orderable_amount_synced`를 health summary/API까지 노출 검토
