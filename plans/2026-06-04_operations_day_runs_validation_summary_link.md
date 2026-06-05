# 2026-06-04 operations_day_runs 검증 요약 연결

## 목적

- `evaluate_next_trading_day_readiness.py`
- `evaluate_intraday_operational_validation.py`

두 CLI가 출력만 하고 끝나지 않도록, 결과를 `trading.operations_day_runs.summary_json`에 직접 저장한다.

이로써 `operations-day/latest`, `by-date`, `history` API만 조회해도
해당 날짜의 readiness / intraday validation 결과를 함께 확인할 수 있게 한다.

## 구현 내용

### 1. 공용 저장 helper 추가

- 파일: `scripts/operations_day_run_evaluation_store.py`
- 기능:
  - 환경변수 기반 DSN 생성
  - 평가 결과 compact payload 생성
  - `operations_day_runs.summary_json` 병합 저장

저장 key:

- `next_trading_day_readiness`
- `intraday_validation`

### 2. readiness CLI 저장 연동

- 파일: `scripts/evaluate_next_trading_day_readiness.py`
- 변경:
  - `_build_persisted_summary()` 추가
  - `--persist / --no-persist` 플래그 추가
  - 기본값은 `persist=True`
  - 평가 후 `operations_day_runs.summary_json["next_trading_day_readiness"]` 저장

저장 payload 핵심 필드:

- `overall_status`
- `generated_at`
- `check_counts`
- `blocked_codes`
- `warn_codes`
- `target_date`
- `is_trading_day`
- `blocking_unresolved_count`
- `warning_unresolved_count`
- `truth_probe_pending_count`

### 3. intraday validation CLI 저장 연동

- 파일: `scripts/evaluate_intraday_operational_validation.py`
- 변경:
  - `_build_persisted_summary()` 추가
  - `--persist / --no-persist` 플래그 추가
  - 기본값은 `persist=True`
  - 평가 후 `operations_day_runs.summary_json["intraday_validation"]` 저장

저장 payload 핵심 필드:

- `overall_status`
- `generated_at`
- `check_counts`
- `blocked_codes`
- `warn_codes`
- `target_date`
- `is_trading_day`
- `operations_day_status`
- `buy_orders_created_count`
- `total_buy_decisions`

## 검증

- `pytest -q tests/scripts/test_operations_day_run_evaluation_store.py tests/scripts/test_evaluate_next_trading_day_readiness.py tests/scripts/test_evaluate_intraday_operational_validation.py`
  - `12 passed`
- `python3 -m py_compile`
  - helper / readiness / intraday validation / 관련 테스트 통과

## 기대 효과

이제 `operations_day_runs`는 단순 scheduler 상태뿐 아니라,

- 다음 거래일 준비 상태
- 현재 장중 운영 검증 결과

를 같은 날짜 row의 `summary_json` 안에 함께 보관한다.

따라서 날짜별 운영 이력 분석 시

1. scheduler 상태
2. sync/recovery health
3. readiness / intraday validation 결과

를 한 row에서 함께 읽을 수 있다.
