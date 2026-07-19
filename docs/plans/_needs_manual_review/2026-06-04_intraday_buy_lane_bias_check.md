# 장중 BUY lane 차단 편향 자동 점검

## 배경

- `[PRIORITY_MAP] remaining_work_priority_map.md`의 `3. 다음 거래일 장중 실운영 검증`은 아직 진행중 상태였다.
- 최근 수정으로 일반 BUY lane은 다시 열렸지만, 장중에
  - `submit_budget_consumed_*`
  - `general_submit_disabled_*`
  가 실주문 수에 비해 과도하게 누적되는 편향이 남아 있는지 자동으로 보지는 못했다.
- 또한 scheduler 장중/장후 경계 기준이 최근 `15:30:30 KST`로 조정됐으므로, 장중 검증 CLI도 같은 cutoff를 따라야 했다.

## 수정 내용

### 1. BUY lane bias 체크 추가

- 파일: [`scripts/evaluate_intraday_operational_validation.py`](../scripts/evaluate_intraday_operational_validation.py)
- 신규 체크:
  - `INTRA_BUY_LANE_BIAS`
- 규칙:
  - 거래일이고
  - 실제 `buy_orders_created_count > 0`인데
  - `submit_budget_consumed_count + general_submit_disabled_count >= max(3, buy_orders_created_count * 3)`
  이면 `WARN`
- 의도:
  - BUY 주문은 일부 생성됐는데도 gate/budget 차단 수가 과도하면
  - submit slot 재할당/소비 편향이 남아 있는지 바로 알 수 있게 함

### 2. intraday cutoff 정렬

- `_INTRADAY_CUTOFF = 15:30:30`
- `IntradayOperationalEvaluator._expected_scheduler_status()`도 이제 `15:30:30` 전까지는 `intraday`, 이후는 `after_hours`로 판단
- scheduler의 `MARKET_CLOSE = 15:30:30`와 일치시켰다.

## 테스트

- 파일: [`tests/scripts/test_evaluate_intraday_operational_validation.py`](../tests/scripts/test_evaluate_intraday_operational_validation.py)
- 추가/보강:
  - healthy 케이스를 시간 독립적으로 고정
  - `buy_orders_created=2`, `blocked_total=7`이면 `INTRA_BUY_LANE_BIAS = WARN`
  - `_INTRADAY_CUTOFF == 15:30:30` 검증

## 검증

```bash
pytest -q tests/scripts/test_evaluate_intraday_operational_validation.py
python3 -m py_compile \
  scripts/evaluate_intraday_operational_validation.py \
  tests/scripts/test_evaluate_intraday_operational_validation.py
```

- 결과: `7 passed`
- `py_compile` 통과

## 기대 효과

- 장중 운영 검증 CLI가 단순히 `BUY 0건` 여부만 보는 것이 아니라,
  실제 BUY 주문이 일부 생성된 뒤에도 gate/budget 차단이 비정상적으로 많이 남는 패턴을 조기에 경고한다.
- `15:30:30` 기준 전환과 검증 로직이 일치해 장중/장후 phase mismatch 오탐을 줄인다.
