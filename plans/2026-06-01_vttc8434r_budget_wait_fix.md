# VTTC8434R snapshot budget fallback 완화

## 배경

paper global REST 예산을 프로세스 간 공유하도록 바꾼 뒤,
startup 직후 `snapshot-sync`에서 아래 현상이 발생했다.

- `BUDGET_FALLBACK VTTC8434R budget insufficient`
- `CashAndPositionsResult`가 빈 값으로 반환
- 결과적으로 cash sync가 0건으로 끝남
- stale-snapshot guard가 submit을 막을 수 있음

즉, 공유 예산 자체는 맞았지만, `VTTC8434R` 같은 핵심 snapshot 조회가
토큰이 잠깐 비어 있다는 이유만으로 **즉시 포기**하는 게 문제였다.

## 원인

`KISRestClient.get_cash_and_positions()`는 호출 직전에
`_has_budget_for_inquiry()`를 동기 pre-check로 수행했다.

문제점:

- paper shared global bucket은 여러 프로세스가 함께 쓰므로
  startup 직후 잠깐 `remaining=0`일 수 있음
- 하지만 이 경우도 보통 1초 내로 refill 가능
- 그럼에도 `VTTC8434R`는 기다리지 않고 바로 빈 결과를 반환

즉, snapshot 핵심 경로에 대해서 pre-check가 너무 공격적이었다.

## 수정 내용

### 1. `get_cash_and_positions()` 전용 대기 helper 추가

`KISRestClient._wait_for_inquiry_budget(timeout=2.0)` 추가

- `budget_manager is None` → 즉시 `True`
- `_has_budget_for_inquiry()`가 `True`가 될 때까지 최대 2초 대기
- 0.1초 간격 polling
- 실제 token 소비는 하지 않음
- 실제 소비는 기존대로 `_request()`가 담당

핵심 포인트:

- `wait_until_global_rest_available()`는 토큰을 실제로 consume하므로 여기엔 부적합
- snapshot pre-check는 **기다리기만** 해야 함

### 2. `VTTC8434R`에만 완화 적용

`get_cash_and_positions()`는:

- 이전: `if not self._has_budget_for_inquiry(): fallback`
- 변경: `if not await self._wait_for_inquiry_budget(timeout=2.0): fallback`

즉:

- snapshot 핵심 경로는 짧게 기다림
- `VTTC8908R(get_orderable_cash)` 같은 보조 조회는 기존 fallback 전략 유지

## 테스트

### 추가 테스트

`tests/brokers/koreainvestment/test_rest_client_submit.py`

1. `test_cash_and_positions_waits_then_requests`
   - `_wait_for_inquiry_budget() == True`
   - `_request()`가 실제 호출되는지 확인

2. `test_cash_and_positions_returns_empty_on_budget_timeout`
   - `_wait_for_inquiry_budget() == False`
   - `_request()`는 호출되지 않고 빈 결과 반환

### 실행 결과

- `pytest -q tests/brokers/koreainvestment/test_rest_client_submit.py tests/brokers/koreainvestment/test_snapshot.py tests/services/test_kis_snapshot_sync.py -k "cash_and_positions or orderable_cash or budget"`
- 결과: `10 passed`

## 기대 효과

이제 paper shared budget 환경에서도:

- startup 직후 global token이 잠깐 비어 있어도
- `VTTC8434R`는 최대 2초까지 기다렸다가 실행 시도

즉시 빈 snapshot으로 포기하던 현상이 줄어든다.

## 범위 제한

이번 수정은 `VTTC8434R` 핵심 snapshot 경로에만 적용했다.

- cash/positions 통합 조회는 기다림
- 보조 조회(`VTTC8908R`)는 기존 fallback 유지

이렇게 해야 startup snapshot 성공률을 높이면서도
불필요한 budget 대기 전파를 최소화할 수 있다.
