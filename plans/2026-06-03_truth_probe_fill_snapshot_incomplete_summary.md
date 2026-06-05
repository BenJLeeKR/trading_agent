# 2026-06-03 `truth_probe_fill_snapshot_incomplete` 운영 집계 추가

## 목적

- `[PRIORITY_MAP] remaining_work_priority_map.md` 기준으로,
  `FILL_SNAPSHOT_INCOMPLETE` 주문의 후속 수렴 상태를 운영자가 바로 확인할 수 있게 한다.
- Admin UI 작업은 뒤로 미루고, 먼저 **read-only 백엔드 집계 API**를 제공한다.

## 문제

- 현재 `order_sync_service`는 linked fill snapshot row가 들어왔지만 아직 positive fill quantity가 없는 경우,
  주문 row에 `status_reason_code="truth_probe_fill_snapshot_incomplete"`를 저장한다.
- 하지만 이 상태를 한 번에 모아 보는 API가 없어,
  운영자가 “다음 fill sync를 기다리는 주문”이 몇 건인지 바로 알기 어렵다.

## 선택한 구현

- 신규 endpoint:
  - `GET /orders/truth-probe-pending-summary`
- 기준:
  - KST 날짜 범위 (`date` query, 기본값 오늘)
  - `status_reason_code == "truth_probe_fill_snapshot_incomplete"`
- 반환:
  - 총 건수
  - 현재 주문 상태별 건수
  - 최근 주문 목록 (심볼, 상태, ODNO, reason message 포함)

## 구현 내용

### 1. API 스키마 추가

- `TruthProbePendingOrderItem`
- `TruthProbePendingSummaryResponse`

### 2. Orders route 추가

- `src/agent_trading/api/routes/orders.py`
  - `get_truth_probe_pending_summary()`
  - 날짜 범위 내 주문 조회 후 `status_reason_code`로 필터
  - 최근 항목은 심볼과 `broker_native_order_id`를 enrich 해서 반환

### 3. 테스트 추가

- `tests/api/test_inspection.py`
  - pending summary 정상 집계 케이스
  - empty 케이스

## 기대 효과

- 운영자는 이제 “fill snapshot은 들어왔지만 아직 체결 진실이 수렴하지 않은 주문”을
  하루 기준으로 바로 집계해서 볼 수 있다.
- hard conflict와 `pending convergence` 상태를 분리해서 추적할 수 있다.

## 비고

- 이번 작업은 DB 스키마 변경 없음
- repository contract 변경 없음
- UI 연결은 후속 작업으로 둔다
