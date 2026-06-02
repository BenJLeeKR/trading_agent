# VTTC0081R BUY 오분류 복구 및 자동 만료 방지

## 배경

- 2026-06-01 장중/장후 정리 과정에서 일부 BUY 주문이 `expired`로 정리되었음.
- 하지만 `VTTC0081R` exact query(`ODNO + PDNO + side + exact date`)로는 동일 주문 레코드가 존재했고,
  `position_snapshot`도 체결 가능성을 보여주는 사례가 확인됨.
- 문제는 KIS 응답에 `ORD_STAT=""`, `CCLD_QTY=0`처럼 불완전한 값이 들어올 때 이를 곧바로
  `expired_confirmed`로 읽던 진단/정리 로직이었음.

## 이번 수정

### 1. 진단 로직 보정

- `scripts/verify_order_truth.py`
  - `ORD_STAT` 공란 + `CCLD_QTY=0` + `ORD_QTY>0` 조합을
    `expired_confirmed`가 아니라 `paper_truth_missing`으로 분류.
  - 의미: exact ODNO 레코드는 있으나 broker truth가 완결적이지 않으므로,
    position delta와 함께 해석해야 함.

### 2. EXPIRED BUY 자동 복구 경로 추가

- `src/agent_trading/services/order_sync_service.py`
  - 최근 `EXPIRED` 주문 재동기화 시 broker truth가 `submitted/acknowledged/reconcile_required`
    로 돌아오고, `broker_native_order_id`가 있는 BUY 주문이면
    `EXPIRED -> RECONCILE_REQUIRED`로 재오픈.
  - 목적: 잘못 만료된 BUY를 terminal 상태에 고정하지 않고,
    보수적으로 `reconcile_required`로 복구해 후속 truth probe 대상으로 되돌림.

### 3. EXPIRED recovery 결과 반환값 정정

- 동일 파일에서 `EXPIRED` 복구 성공 시 `SyncOrderResult`가
  실제 변경 상태를 반영하도록 보정.

## 검증

- `pytest -q tests/scripts/test_verify_order_truth.py`
- `pytest -q tests/services/test_order_sync_service.py -k "expired_buy or recover_expired or expires or reconcile_required"`

## 운영 조치

1. `app`, `ops-scheduler` 재배포
2. 오늘 `expired` BUY 주문에 대해 recovery sync 재실행
3. `expired`에서 `reconcile_required`로 복구된 주문 목록 확인
4. 잔여 건은 개별 VTTC0081R + position snapshot 재검토

## 후속 보강

- `submitted`로 되돌아온 BUY 주문 중
  - exact ODNO truth record 존재
  - earliest post-snapshot 기준 position delta가 안전하게 분리 가능
  인 경우 `filled` / `partially_filled`로 자동 승격.
- 같은 종목의 다음 BUY 주문이 첫 post-snapshot 이전에 존재하면
  delta 오염 가능성이 있으므로 자동 승격하지 않음.
- 이 경로는 정상 복구이므로 sync summary에서 `truth_probe_conflict` 에러로
  보이지 않도록 observability도 함께 보정.
