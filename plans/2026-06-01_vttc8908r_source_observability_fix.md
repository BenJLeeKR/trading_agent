# VTTC8908R source observability 보강

## 배경
`snapshot-sync` 로그에서 `orderable_amount=... (source: VTTC8908R)`가 남더라도, 실제로는 `VTTC8908R` 조회 성공이 아니라 `fallback_cash` 반환일 수 있었다. 특히 paper 공유 예산이 부족할 때 `get_orderable_cash()`가 pre-check fallback을 조용히 반환하면서 운영자가 실제 API 성공으로 오해할 수 있었다.

## 원인
- `KISRestClient.get_orderable_cash()`는 `Decimal | None`만 반환했다.
- 호출자(`snapshot.py`, `kis_snapshot_sync.py`)는 값만 보고 `source: VTTC8908R`로 기록했다.
- 따라서 아래 경우가 구분되지 않았다.
  - 실제 `VTTC8908R` 성공
  - inquiry pre-check fallback
  - runtime budget exhausted
  - API failure
  - 응답 필드 누락

## 적용한 수정
1. `rest_client.py`
- `OrderableCashResult(amount, source)` dataclass 추가
- `get_orderable_cash_result()` 신규 추가
- `get_orderable_cash()`는 기존 호환성을 위해 `result.amount`만 반환하는 wrapper로 유지
- `source` 값을 아래처럼 구조화
  - `vttc8908r`
  - `budget_precheck_fallback`
  - `budget_exhausted`
  - `api_failure`
  - `missing_field`

2. `snapshot.py`
- `get_orderable_cash_result()`를 사용하도록 변경
- `orderable_amount=%s (source: %s)` 형식으로 실제 source 기록

3. `kis_snapshot_sync.py`
- legacy sync path도 동일하게 `get_orderable_cash_result()` 사용
- `orderable_amount=%s (source: %s, legacy sync path)`로 기록

## 테스트
- `tests/brokers/koreainvestment/test_rest_client_submit.py`
  - `budget_precheck_fallback` source 검증
  - `vttc8908r` success source 검증
- `tests/brokers/koreainvestment/test_snapshot.py`
  - provider path 로그에 `source: budget_precheck_fallback` 노출 검증
- `tests/services/test_kis_snapshot_sync.py`
  - legacy sync path 로그에 `source: budget_precheck_fallback, legacy sync path` 노출 검증

## 기대 효과
- 운영자가 `orderable_amount` 로그만 보고도 실제 API 성공인지 fallback인지 구분할 수 있다.
- `VTTC8908R_pre_check=1`가 남아도 cash snapshot이 정상인지, fallback인지 해석이 쉬워진다.
- 이후 `snapshot-sync` budget 최적화 작업에서 관측성 기반 판단이 가능해진다.
