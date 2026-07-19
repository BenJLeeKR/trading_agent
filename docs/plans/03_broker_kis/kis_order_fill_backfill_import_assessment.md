# KIS 주문/체결 이력 Backfill/Import 실행 여부 판단

작성일: 2026-05-14

## 1. 목적

DB cleanup 이후 `order_requests`, `broker_orders`, `fill_events`, `order_state_events`가 0건이 되면서, KIS paper 계좌에 실제 포지션은 존재하지만 주문 lineage가 사라진 상태가 되었다.

이 문서는 KIS broker API를 통해 삭제된 주문/체결 이력을 복구할 수 있는지 판단하고, 가능할 경우 어떤 import 설계가 필요한지 정리한다.

## 2. 현재 DB 상태

| 테이블 | 현재 건수 | 판단 |
|---|---:|---|
| `order_requests` | 0 | 주문 lineage 없음 |
| `broker_orders` | 0 | broker ODNO linkage 없음 |
| `fill_events` | 0 | 체결 이벤트 없음 |
| `order_state_events` | 0 | 주문 상태 전이 이력 없음 |
| `position_snapshots` | 177 | KIS snapshot 재적재됨 |
| `cash_balance_snapshots` | 131 | KIS snapshot 재적재됨 |
| `snapshot_sync_runs` | 177 | sync 이력 존재 |

최신 포지션:

| symbol | quantity | average_price | 판단 |
|---|---:|---:|---|
| `005930` | 10 | 267,000 | KIS 잔고에는 포지션 존재 |

## 3. KIS read-only probe 결과

### 3.1 사용 엔드포인트

| 항목 | 값 |
|---|---|
| Endpoint | `/uapi/domestic-stock/v1/trading/inquire-daily-ccld` |
| TR ID | `VTTC0081R` |
| 환경 | `KIS_ENV=paper` |
| Base URL | `https://openapivts.koreainvestment.com:29443` |
| 조회 범위 1 | 2026-04-14 ~ 2026-05-14 |
| 조회 범위 2 | 2026-02-13 ~ 2026-05-14 |
| Pagination fields | 2차 probe에서 `CTX_AREA_FK100=""`, `CTX_AREA_NK100=""` 포함 |

### 3.2 응답

두 번 모두 동일하게 주문/체결 row가 없었다.

```text
output_count=0
output2={
  "tot_ord_qty": "0",
  "tot_ccld_qty": "0",
  "tot_ccld_amt": "0",
  "prsm_tlex_smtl": "0",
  "pchs_avg_pric": "0.0000"
}
```

## 4. 실행 여부 판정

### 판정: KIS paper API 기반 자동 backfill은 현재 No-Go

사유:

1. `inquire-daily-ccld`가 30일/90일 범위 모두 `output: []`를 반환한다.
2. 이 결과는 기존 Phase C 분석과 일치한다. KIS paper mock은 주문 접수 후 ODNO를 발급해도 일별주문체결조회에 settlement/order rows를 생성하지 않는다.
3. 주문 복구에 필요한 최소 키인 `ODNO`, `PDNO`, `ORD_QTY`, `ORD_UNPR`, `CCLD_QTY`, `CCLD_UNPR`, `CCLD_NUM`을 API에서 확보할 수 없다.
4. 현재 포지션 snapshot만으로는 broker native order id, 주문 시각, 실제 체결번호를 복원할 수 없다.

따라서 지금 즉시 DB에 주문/체결 이력을 자동 import하면, KIS 원장 기반 복구가 아니라 추정 데이터 삽입이 된다. 운영 정합성 관점에서는 금지하는 것이 맞다.

## 5. 가능한 대안

### A. KIS API 자동 backfill

| 항목 | 판단 |
|---|---|
| 현재 실행 가능성 | 불가 |
| 필요 조건 | `inquire-daily-ccld.output_count > 0` |
| 장점 | broker 원장 기반, 신뢰도 높음 |
| 한계 | paper mock에서는 현재 빈 배열 |

이 경로는 live 또는 paper mock 개선 이후에만 사용 가능하다.

### B. 로컬 증적 기반 수동 backfill

| 항목 | 판단 |
|---|---|
| 현재 실행 가능성 | 조건부 가능 |
| 데이터 출처 | 과거 `plans/*report.md`, 로그, 운영 캡처 |
| 확인된 증적 | `50c7032e...`, ODNO `0000011317`, 005930 10주, 267,000원 |
| 장점 | UI lineage 불일치를 해소할 수 있음 |
| 한계 | KIS API 원장 복구가 아니라 운영 증적 기반 재구성 |

이 방식은 반드시 `status_reason_code='manual_backfill_from_ops_evidence'` 같은 명시적 marker를 남겨야 한다.

### C. 포지션 기반 synthetic fill 생성

| 항목 | 판단 |
|---|---|
| 현재 실행 가능성 | 기술적으로 가능 |
| 데이터 출처 | 최신 position snapshot |
| 장점 | 포지션-주문 lineage를 빠르게 맞출 수 있음 |
| 한계 | 주문번호/체결번호/주문시각이 모두 추정값 |

운영 DB에서는 권장하지 않는다. 테스트/demo 목적이라면 가능하지만, near-real 운영 데이터와 섞이면 안 된다.

## 6. Backfill import 설계안

KIS API가 rows를 반환하거나, 사용자가 명시적으로 로컬 증적 기반 수동 backfill을 승인할 경우에만 아래 구조로 import한다.

### 6.1 입력 row

필수:

| 필드 | 설명 |
|---|---|
| `ODNO` | KIS broker native order id |
| `PDNO` | 종목 코드 |
| `ORD_QTY` | 주문 수량 |
| `ORD_UNPR` | 주문 가격 |
| `SLL_BUY_DVSN_CD` | 매수/매도 구분 |
| `ORD_DT` 또는 증적 일자 | 주문 일자 |

체결 row 생성 시 추가 필요:

| 필드 | 설명 |
|---|---|
| `CCLD_QTY` | 체결 수량 |
| `CCLD_UNPR` | 체결 단가 |
| `CCLD_NUM` | 체결 번호 |
| `CCLD_TMD` | 체결 시각 |

### 6.2 삽입 대상

1. `order_requests`
   - `client_order_id = 'kis-backfill-{ODNO}'`
   - `idempotency_key = 'kis-backfill-{ODNO}'`
   - `correlation_id = 'kis-backfill-{ODNO}'`
   - `trade_decision_id = NULL`
   - `decision_context_id = NULL`
   - `status = filled | partially_filled | submitted | cancelled | reconcile_required`
   - `status_reason_code = 'kis_api_backfill'` 또는 `manual_backfill_from_ops_evidence`

2. `broker_orders`
   - `broker_name = 'korea_investment'`
   - `broker_native_order_id = ODNO`
   - `broker_status = order_requests.status`
   - `response_payload_uri = 'kis-backfill://inquire-daily-ccld/{ODNO}'` 또는 증적 파일 URI
   - `last_synced_at = now()`

3. `fill_events`
   - `broker_fill_id = CCLD_NUM` 또는 deterministic fallback
   - `source_channel = 'backfill'`
   - `fill_price = CCLD_UNPR`
   - `fill_quantity = CCLD_QTY`

4. `order_state_events`
   - 최소 1건: `previous_status=NULL`, `new_status=<final_status>`
   - `event_source='system'`
   - `reason_code='kis_api_backfill'` 또는 `manual_backfill_from_ops_evidence`
   - `raw_event_uri`에 원천 증적 URI 기록

### 6.3 멱등성

중복 방지 기준:

| 테이블 | 기준 |
|---|---|
| `order_requests` | `idempotency_key = 'kis-backfill-{ODNO}'` |
| `broker_orders` | `(broker_name, broker_native_order_id)` unique |
| `fill_events` | `(broker_order_id, broker_fill_id)` unique |

### 6.4 실행 모드

반드시 두 단계로 실행한다.

1. `--dry-run`
   - KIS/API/CSV rows 파싱
   - DB에 이미 존재하는 ODNO 제외
   - insert 예정 row 출력
   - write 없음

2. `--commit`
   - transaction 내 insert
   - commit 전 row count 검증
   - 실패 시 rollback

## 7. 이번 턴 실행 결론

이번 턴에서는 DB write를 실행하지 않는다.

사유:

1. KIS paper API가 주문/체결 이력을 반환하지 않아 broker 원장 기반 import의 필수 조건이 미충족이다.
2. 로컬 보고서 기반으로 일부 주문을 재구성할 수는 있으나, 이는 KIS 원장 backfill이 아니라 수동 증적 backfill이다.
3. 수동 증적 backfill은 운영 데이터에 명시적 marker를 남기는 별도 승인 후 실행해야 한다.

## 8. 권장 다음 액션

1. 지금 당장은 DB에 주문/체결 backfill을 넣지 않는다.
2. UI에서는 `positions > 0 && orders = 0` 상태를 lineage warning으로 계속 표시한다.
3. 장 종료 후 별도 작업으로 `scripts/backfill_kis_orders.py`를 설계/구현한다.
   - 기본은 `--dry-run`
   - KIS API rows가 0이면 exit code 0 + "No broker rows available" 출력
   - `--source manual-json` 옵션으로 사용자 승인된 증적만 수동 import 허용
4. 수동 backfill을 원하면, 최소 증적 row를 별도 JSON으로 준비한다.
   - 예: `ODNO=0000011317`, `symbol=005930`, `side=buy`, `qty=10`, `price=267000`, `submitted_at=2026-05-13T00:44:35Z`

