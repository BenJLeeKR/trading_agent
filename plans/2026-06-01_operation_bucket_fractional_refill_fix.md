# OperationBucket fractional refill 누적 버그 수정

## 배경

`VTTC8434R` snapshot 경로에 2초 대기를 넣었는데도
`snapshot-sync`가 계속 `BUDGET_FALLBACK VTTC8434R budget insufficient`로 떨어졌다.

이건 단순히 대기 시간이 짧아서가 아니라,
`OperationBucket._refill()`가 `0.5 rps` 같은 sub-token refill에서
fractional 누적을 잃어버리는 구조였기 때문이다.

## 문제

기존 구현:

- `elapsed * refill_rate`를 바로 `int()`로 잘랐다
- `refill_at`는 매 호출 시 갱신했다
- 하지만 잘려나간 fractional 부분은 저장하지 않았다

예시:

- inquiry refill rate = `0.5/s`
- 0.1초 polling 시마다 `0.05 token`씩 생겨야 함
- 기존 구현은 매번 `int(0.05) == 0`
- 그리고 fractional 0.05는 버려짐
- 결과적으로 2초를 기다려도 토큰이 차지 않을 수 있음

즉, sub-token polling에서 사실상 **영구 starvation**이 가능했다.

## 수정 내용

`OperationBucket`에 `_fractional_tokens: float` 상태를 추가했다.

새 refill 로직:

1. `elapsed * refill_rate` 계산
2. 기존 `_fractional_tokens`와 합산
3. 정수 부분만 `remaining`에 반영
4. 소수 부분은 `_fractional_tokens`에 유지
5. `refill_at`는 계속 현재 시각으로 갱신

핵심:

- `refill_at`는 advance
- fractional token도 누적 보존

즉, 짧은 polling을 여러 번 해도 결국 1 token이 차야 할 시점에 실제로 차게 된다.

## 검증

### 테스트

- `pytest -q tests/brokers/test_rate_limit.py tests/brokers/test_shared_budget.py tests/brokers/koreainvestment/test_rest_client_submit.py tests/brokers/koreainvestment/test_snapshot.py tests/services/test_kis_snapshot_sync.py -k "rate_limit or starvation or cash_and_positions or orderable_cash or budget"`
- 결과: `50 passed`

### 실측 스모크

`refill_rate=0.5`, `remaining=0` 상태에서 0.1초 간격으로 `_refill()` 호출:

- 0.5초 근처: 아직 0 token
- 1.0초 근처: fractional 누적 진행
- 2.0초 근처: `remaining=1` 확인

즉, `0.5 rps = 2초당 1토큰`이 실제로 반영됐다.

## 기대 효과

이 수정으로:

- shared paper global budget 환경
- inquiry 0.5 rps bucket
- 짧은 polling 기반 budget 대기

조합에서도 토큰이 정상적으로 누적된다.

특히 `VTTC8434R`처럼 startup snapshot 핵심 경로에서
짧게 기다린 뒤 실행하는 전략이 이제 실제로 동작할 수 있다.
