# 주문가능금액 fallback 과매수 방지 수정

## 문제

2026-06-05 장중 `VTTC8908R` 주문가능금액 조회가 budget pre-check에 걸린 cycle에서,
시스템이 `available_cash`를 `orderable_amount`처럼 승격해서 저장했다.

그 결과 sizing이 실제 주문가능금액보다 큰 현금이 있다고 오판했고,
연속 BUY 체결 후 `settlement_amount` / `orderable_amount`가 음수로 내려가는
과매수 상황이 발생했다.

## 직접 원인

- `src/agent_trading/brokers/koreainvestment/snapshot.py`
- `src/agent_trading/services/kis_snapshot_sync.py`

두 경로 모두 다음 상황에서 `orderable_amount = available_cash` fallback을 사용했다.

1. `budget_precheck_fallback`
2. `budget_exhausted_fallback`
3. `api_failure_fallback`
4. `VTTC8908R`와 `VTTC8434R ord_psbl_amt`가 모두 없는 경우

## 수정 방침

BUY 안전성 우선:

- `VTTC8908R` 주문가능금액이 검증되지 않은 cycle에서는
  `available_cash`를 주문가능금액으로 승격하지 않는다.
- 대신 `orderable_amount = 0`으로 저장해서 해당 cycle의 BUY sizing을 막는다.
- snapshot `fetch_status`는 `stale`로 저장한다.

## 적용 내용

### 1. broker-agnostic snapshot provider

- 파일: `src/agent_trading/brokers/koreainvestment/snapshot.py`
- 변경:
  - 미검증 source(`budget_precheck_fallback`, `budget_exhausted_fallback`,
    `api_failure_fallback`)면 `orderable_amount=0`
  - `VTTC8908R`/`VTTC8434R` 모두 값이 없으면 `orderable_amount=0`
  - 위 경우 `fetch_status='stale'`

### 2. legacy KIS snapshot sync

- 파일: `src/agent_trading/services/kis_snapshot_sync.py`
- 변경:
  - 동일 정책 적용
  - `CashBalanceSnapshotEntity.fetch_status='stale'`

### 3. 테스트 정리

- `tests/brokers/koreainvestment/test_snapshot.py`
- `tests/services/test_kis_snapshot_sync.py`

기존 `available_cash fallback` 기대값을 모두 `0 / stale` 기준으로 수정.

## 검증

```bash
pytest -q tests/brokers/koreainvestment/test_snapshot.py \
  tests/services/test_kis_snapshot_sync.py \
  -k 'orderable_amount or orderable_cash or BudgetPreCheck or BudgetExhausted or after_hours'
```

결과:

- `14 passed`

추가:

```bash
python3 -m py_compile \
  src/agent_trading/brokers/koreainvestment/snapshot.py \
  src/agent_trading/services/kis_snapshot_sync.py \
  tests/brokers/koreainvestment/test_snapshot.py \
  tests/services/test_kis_snapshot_sync.py
```

통과.

## 기대 효과

- `VTTC8908R` budget pre-check 실패 cycle에서 더 이상
  `available_cash`가 BUY sizing 기준으로 오용되지 않는다.
- `orderable_amount` 검증이 안 된 순간에는 BUY가 보수적으로 차단된다.
- 같은 유형의 음수 `주문가능금액` 과매수 재발 가능성을 크게 낮춘다.
