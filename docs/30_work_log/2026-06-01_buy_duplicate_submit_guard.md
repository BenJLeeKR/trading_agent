# 2026-06-01 최근 BUY 중복 제출 원인 분석 및 긴급 방어

## 배경

최근 20분 내 BUY 주문이 과도하게 제출된 것으로 보여 원인을 확인했다.
DB와 `ops-scheduler` 로그를 함께 확인했다.

## 최근 20분 BUY 주문 현황

확인 시점 DB 기준 `now() = 2026-06-01 02:17:05 UTC`였다.

최근 20분 BUY 주문은 총 8건이었다.

| 종목 | 주문 수 | 총 수량 | 상태 |
|---|---:|---:|---|
| 001740 SK네트웍스 | 1 | 205 | submitted |
| 004990 롯데지주 | 2 | 116 | submitted |
| 000660 SK하이닉스 | 1 | 1 | submitted |
| 005380 현대차 | 2 | 4 | submitted |
| 005930 삼성전자 | 2 | 2 | submitted |

동일 종목 재주문은 `004990`, `005380`, `005930`에서 확인됐다.

## 보유 수량 반영 여부

주문 생성 시점의 `decision_context.position_snapshot_id`와 최신 position snapshot을 확인했다.

| 종목 | 첫 주문 전 context 보유 | 이후 context 보유 | 최신 보유 |
|---|---:|---:|---:|
| 001740 | 2 | - | 207 |
| 004990 | 1 | 99 | 117 |
| 005380 | 없음 | 3 | 4 |
| 005930 | 0 | 1 | 1 |
| 000660 | 0 | - | 1 |

결론:

- 일부 주문은 보유 수량을 반영하고 있었다.
- 특히 `004990`은 첫 주문 후 스냅샷에서 99주를 확인하고 다음 주문을 18주로 줄였다.
- 하지만 “방금 같은 종목 BUY를 제출했다”는 recent active order 기준의 재진입 방어가 없어 다음 cycle에서 다시 BUY가 제출될 수 있었다.

## 직접 원인

### 원인 1: cycle 내 submit budget race

`scripts/run_decision_loop.py`는 종목을 최대 5개 병렬 처리한다.
기존 코드는 `submit_budget_consumed`를 실제 제출 결과가 돌아온 뒤에만 `True`로 바꿨다.

따라서 병렬로 시작한 여러 종목이 동시에 `submit_budget_consumed=False`를 보고
모두 실제 submit 경로로 진입할 수 있었다.

### 원인 2: held_position source_type이 BUY에도 special lane을 열어줌

기존 주석은 held-position SELL만 별도 lane으로 처리하려는 의도였지만,
실제 submit 여부를 결정하는 시점에는 아직 decision_type/side를 모른다.

그 결과 `source_type=held_position`이라는 이유만으로 BUY도 held-position sell lane을 타고
일반 submit budget을 우회할 수 있었다.

### 원인 3: BUY 재진입 쿨다운 부재

SELL에는 duplicate sell guard가 있었지만 BUY에는 동일 계좌/동일 종목의 최근 active order를 막는 guard가 없었다.
그래서 직전 주문이 아직 submitted/partially_filled 상태여도 다음 cycle에서 같은 종목 BUY가 다시 제출될 수 있었다.

## 수정 내용

### 1. cycle submit 권한을 실행 전 예약

`scripts/run_decision_loop.py`에서 `symbol_submit=True`로 결정되는 즉시 `submit_budget_consumed=True`로 예약한다.

효과:

- 병렬 task가 동시에 `False`를 보고 여러 주문을 제출하는 race를 제거한다.
- 한 decision_submit_gate 실행에서 일반 BUY submit은 최대 1개로 제한된다.

### 2. held_position BUY의 special lane 우회 제거

실제 side를 모르는 사전 단계에서 `source_type=held_position`만으로 submit 권한을 부여하지 않도록 변경했다.

효과:

- held-position 종목이라도 BUY는 일반 submit budget을 따른다.
- 위험 축소 SELL 집계는 result 수신 후 scheduler 계층에서만 판단한다.

### 3. BUY recent active order guard 추가

`ExecutionService`에 동일 계좌/동일 종목의 최근 15분 active BUY 주문이 있으면 SKIP하는 guard를 추가했다.

active 상태:

- `draft`
- `validated`
- `pending_submit`
- `submitted`
- `acknowledged`
- `partially_filled`
- `filled`
- `reconcile_required`

효과:

- 직전 주문의 broker/account snapshot이 수렴하기 전에 같은 종목을 반복 매수하는 것을 막는다.
- 다음 cycle 재진입 중복을 막는다.

## 변경 파일

- `scripts/run_decision_loop.py`
- `src/agent_trading/services/execution_service.py`
- `tests/services/test_decision_orchestrator.py`
- `tests/services/test_decision_submit_pipeline.py`

## 테스트

실행:

```bash
python3 -m py_compile scripts/run_decision_loop.py src/agent_trading/services/execution_service.py
pytest -q tests/services/test_decision_orchestrator.py::TestBuildSizingInputs tests/services/test_decision_submit_pipeline.py tests/scripts/test_run_decision_loop.py -q
```

결과:

- py_compile 통과
- 관련 테스트 통과

## 운영 반영

코드 반영 후 `ops-scheduler` 재시작이 필요하다.

```bash
docker compose restart ops-scheduler
```

## 남은 확인

- 다음 20분 동안 BUY 주문이 한 decision_submit_gate 실행당 1개 이하로 제한되는지 확인한다.
- 같은 종목 BUY가 15분 안에 다시 승인될 경우 `recent_active_buy_order`로 SKIP되는지 로그를 확인한다.
- 긴급 SELL 축소 주문을 별도 lane으로 유지하려면, 사전 submit 권한 부여 방식이 아니라 먼저 dry-run decision을 얻은 뒤 SELL일 때만 submit하는 2단계 구조가 필요하다.
