# T3 Degraded Persist 경로 `_db_transaction` 스코프 버그 수정

## 배경

운영 로그에서 아래 오류가 반복 확인되었다.

- 위치: `scripts/run_decision_loop.py`
- 시점: NAVER quota exhausted 이후 T3 degraded persist 경로
- 오류: `UnboundLocalError: cannot access local variable '_db_transaction' where it is not associated with a value`

즉, T3 live pipeline이 degraded fallback으로 KIS disclosure seed를 저장하려고 할 때,
DB transaction 진입 전에 지역 변수 스코프 오류로 실패하고 있었다.

## 원인

`_run_t3_live_pipeline()` 내부에서 `_db_transaction`과
`PostgresExternalEventRepository`를 함수 전역이 아니라 특정 분기에서만 import하고 있었다.

문제 구조:

1. `naver_quota_exhausted == True`인 초기 degraded branch에서는 import가 존재
2. 하지만 `process_seeds()` 수행 후
   `metrics.quota_exhausted_count > 0`로 들어오는 후반 degraded branch에서는
   같은 이름을 참조하면서 import가 보장되지 않음
3. Python은 함수 내부 대입/import가 있으면 그 이름을 지역변수로 취급하므로
   후반 branch에서 `_db_transaction` 참조 시 `UnboundLocalError` 발생

즉, 기능 오류가 아니라 **지역 스코프 구성 오류**였다.

## 수정 내용

### 1. 함수 상단으로 import 이동

`_run_t3_live_pipeline()`에서 서비스 availability 확인 직후 아래 import를 공통으로 수행하도록 변경했다.

- `from agent_trading.db.transaction import transaction as _db_transaction`
- `from agent_trading.repositories.postgres.external_events import PostgresExternalEventRepository`

이후 각 분기에서는 이미 바인딩된 이름만 사용한다.

### 2. 중복 local import 제거

아래 경로에 흩어져 있던 중복 import를 제거했다.

- 초기 degraded branch
- `metrics.quota_exhausted_count > 0` branch
- normal persist branch

## 테스트

### 추가한 회귀 테스트

`tests/scripts/test_run_decision_loop.py`

- `test_process_quota_exhausted_degraded_persist_does_not_crash`

검증 내용:

- 초기 `NaverDailyQuotaTracker.is_exhausted()`는 `False`
- `process_seeds()`는 `PipelineMetrics(quota_exhausted_count=1)` 반환
- 즉, 실제로 문제였던 **후반 degraded branch**로 진입
- `_run_t3_live_pipeline()`가 예외 없이 종료되는지 확인

### 실행 결과

- `pytest -q tests/scripts/test_run_decision_loop.py -k "T3LivePipeline or degraded or quota_exhausted"`
- 결과: `12 passed`

추가로:

- `python3 -m py_compile scripts/run_decision_loop.py tests/scripts/test_run_decision_loop.py`
- 결과: 통과

## 기대 효과

이제 NAVER quota 소진 시에도 T3 degraded fallback이 스코프 오류로 죽지 않고:

- KIS disclosure seeds를 degraded T3 이벤트로 저장
- 다음 cycle freshness 판단에 반영
- 로그에 불필요한 `UnboundLocalError`를 남기지 않음

## 비고

이번 수정은 **T3 degraded persist 스코프 버그**만 다룬다.  
NAVER quota 자체의 소진 문제나 T3 정책 자체는 별도 이슈다.
