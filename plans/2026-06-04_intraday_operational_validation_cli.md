# 2026-06-04 장중 실운영 검증 CLI 추가

## 배경

`plans/2026-06-03_remaining_work_priority_map.md`의 P0 항목 중
`다음 거래일 장중 실운영 검증`은 여전히 수동 쿼리/로그 확인 의존도가 높았다.

특히 최근에는 다음 신호를 함께 봐야 장중 상태를 판단할 수 있었다.

- `market_sessions` / `operations_day_runs`
- 최근 `decision_submit_gate` 상태
- 오늘 BUY decision → order 전환 상태
- 차단성 미해결 주문
- `truth_probe_fill_snapshot_incomplete`
- snapshot sync / fill sync freshness

이를 반복 가능하게 만들기 위해 장중 검증용 CLI를 추가했다.

## 구현 내용

### 1. `operations_day_runs.summary_json`에 decision loop 요약 추가

파일: [`scripts/run_ops_scheduler.py`](../scripts/run_ops_scheduler.py)

추가 필드:

- `summary_json["decision_loop"]`
  - `name`
  - `ok`
  - `returncode`
  - `timed_out`
  - `duration_seconds`

즉, `decision_submit_gate` 또는 `decision_dry_run`의 최신 결과를
DB 기반 운영 상태에서 직접 읽을 수 있게 했다.

### 2. 장중 검증 CLI 추가

파일: [`scripts/evaluate_intraday_operational_validation.py`](../scripts/evaluate_intraday_operational_validation.py)

평가 항목:

1. 거래일 판정
2. `operations_day_runs` heartbeat / phase 상태
3. 최근 decision loop 결과
4. 오늘 BUY submit lane 상태
5. 차단성 미해결 주문
6. `truth_probe_fill_snapshot_incomplete`
7. snapshot sync freshness
8. fill sync freshness / retry

출력 형식:

- `--output text`
- `--output json`

반환 코드:

- `READY` → `0`
- `WARN` / `BLOCKED` → `1`

## 검증 규칙

### BUY lane

- 오늘 BUY approve decision이 있고, `buy_orders_created_count > 0`이면 `READY`
- 오늘 BUY approve decision은 있으나
  - `submit_budget_consumed_*`
  - `general_submit_disabled_*`
  가 주원인이면 `BLOCKED`
- sizing / reference price 문제가 주원인이면 `WARN`

### operations day phase mismatch

장중(KST 09:00~15:30)인데 `scheduler_status=pre_market` 같은 상태면
`WARN`으로 본다.

이는 재시작 직후 warm-up 또는 phase 전이 지연을 빠르게 드러내기 위함이다.

## 테스트

파일:

- [`tests/scripts/test_run_ops_scheduler.py`](../tests/scripts/test_run_ops_scheduler.py)
- [`tests/scripts/test_evaluate_intraday_operational_validation.py`](../tests/scripts/test_evaluate_intraday_operational_validation.py)

실행:

```bash
pytest -q tests/scripts/test_run_ops_scheduler.py -k 'PersistOperationsDayRun'
pytest -q tests/scripts/test_evaluate_intraday_operational_validation.py
python3 -m py_compile \
  scripts/run_ops_scheduler.py \
  scripts/evaluate_intraday_operational_validation.py \
  tests/scripts/test_run_ops_scheduler.py \
  tests/scripts/test_evaluate_intraday_operational_validation.py
```

결과:

- `test_run_ops_scheduler.py`: `2 passed`
- `test_evaluate_intraday_operational_validation.py`: `4 passed`

## 실제 실행 결과

실행:

```bash
docker compose exec -T app python3 scripts/evaluate_intraday_operational_validation.py --output text
```

당시 결과:

- `overall = WARN`
- `operations_day_status = intraday`
- `buy_orders_created = 2 / 778`
- `decision_loop = missing`
- `fill sync = WARN (recent retry)`

해석:

- BUY lane 자체는 더 이상 전면 차단 상태가 아님 (`2건 생성`)
- 다만 `decision_loop` 요약은 scheduler 재기동 직후 첫 submit cycle 전이라 아직 비어 있었음
- fill sync는 최근 retry 복구가 있어 경고 상태

## 의미

이제 장중 실운영 검증은 수동 SQL/로그 조합이 아니라, 하나의 CLI로 반복 가능해졌다.

다음 단계에서는:

1. `decision_loop` 요약이 첫 submit cycle 이후 자동으로 채워지는지 장중 재확인
2. 필요 시 `operations_day_runs`에 command별 최근 성공/실패 카운터를 더 구조화
3. 이 CLI를 dashboard/ops runbook과 연결

