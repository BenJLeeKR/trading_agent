# Fill Sync Budget Retry 보강

## 목표

`VTTC0081R` 체결내역 sync가 paper inquiry/global budget이 잠깐 비어 있다는 이유만으로 계정 전체를 `failed`로 끝내지 않도록, 짧은 대기 후 1회 재시도 경로를 추가한다.

## 변경 내용

### 1. VTTC0081R bounded retry helper 추가

- 파일: `src/agent_trading/services/fill_history_sync.py`
- 추가 함수: `_fetch_daily_ccld_with_retry()`
- 정책:
  - `BudgetExhaustedError(bucket in {'inquiry','global'})` 발생 시만 재시도 대상
  - `_wait_for_inquiry_budget(timeout=3.0)`로 짧게 대기
  - 최대 2회 시도(초기 1회 + 재시도 1회)
  - 그 외 예외는 기존처럼 즉시 실패

### 2. account sync 경로에 helper 적용

- `sync_fill_history_for_account()`가 직접 `inquire_daily_ccld()`를 호출하지 않고 `_fetch_daily_ccld_with_retry()`를 사용
- background observability 성격인 fill sync에만 국소 적용
- snapshot/order submit 공용 rate limit 정책은 변경하지 않음

## 테스트

- 파일: `tests/services/test_fill_history_sync.py`
- 추가 검증:
  - 1차 호출에서 `BudgetExhaustedError('inquiry', ...)`
  - `_wait_for_inquiry_budget()` 성공
  - 2차 호출 성공
  - 최종적으로 fill 1건 적재
  - `inquire_daily_ccld.await_count == 2`

실행 결과:

- `pytest -q tests/services/test_fill_history_sync.py tests/api/test_fill_history.py tests/services/test_order_sync_service.py::TestLinkedFillSnapshotTruth`
- 결과: `5 passed`

## 실제 실행 검증

컨테이너 재빌드 후 수동 실행:

```bash
docker compose exec -T app python3 scripts/run_fill_sync_loop.py --once --after-hours
```

실제 로그:

- `VTTC0081R budget retry: order_day=2026-06-02 bucket=inquiry attempt=2/2`
- 이어서 `HTTP 200 OK`
- 최종 요약: `accounts=1 succeeded=1 fills=9 errors=0`

즉, 기존에는 `failed=1`로 종료되던 상황이, 이번 보강 후에는 1회 재시도로 정상 수집으로 복구됐다.

## 범위 밖

- 재시도 횟수 동적 조정
- long backoff / exponential backoff
- fill sync 전용 별도 reserve bucket
- scheduler summary/API에 retry count 노출

## 다음 권장 작업

1. `fill-sync-runs.summary_json`에 retry count 저장
2. `/fill-sync-runs` 응답에 `retried_accounts`, `retried_days` 같은 관측값 추가
3. 체결내역 화면에서 `order_request_id` 기반 주문 상세/제출 이력 점프 링크 연결
