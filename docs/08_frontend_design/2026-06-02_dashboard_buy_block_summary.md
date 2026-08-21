# 2026-06-02 대시보드 오늘 BUY 차단 사유 요약 추가

## 배경
오늘 BUY 주문이 0건이었던 원인을 분석하는 데 DB와 로그를 수동으로 뒤져야 했다. 같은 문제가 재발했을 때 운영 화면에서 바로 원인을 볼 수 있도록, 일별 BUY 차단 사유를 구조적으로 집계해 대시보드에 노출할 필요가 있었다.

## 목표
- `GET /orders/buy-block-summary` endpoint 추가
- 오늘 BUY decision 대비 실제 주문 생성 수와 주요 차단 원인 집계
- Operations Dashboard에 `오늘 BUY 차단` 카드 추가

## 분류 기준
- `buy_orders_created_count`: 실제 order_request가 생성된 BUY decision 수
- `held_position_policy_blocked_count`: `held_position` + `approve|buy`인데 제출 요청이 생성되지 않은 건
- `general_dry_run_blocked_count`: `core|market_overlay` + `approve|buy`인데 제출 요청/실행시도 없이 dry-run으로 끝난 건
- `sizing_rejected_count`: 최신 execution_attempt의 `stop_reason = sizing_rejected`
- `decision_watch_count`: 최신 `stop_reason = decision_watch` 또는 decision_type=`watch`
- `missing_reference_price_count`: 최신 `stop_reason = missing_reference_price_for_market_buy`
- `other_blocked_count`: 위 조건에 해당하지 않는 나머지 BUY 미체결 건

## 구현 내용
- 백엔드
  - `BuyBlockSummaryResponse` 스키마 추가
  - `GET /orders/buy-block-summary` 추가
  - `trade_decisions.list_all_paginated()` 결과를 순회해 KST 당일 BUY decision 집계
  - In-memory 테스트 환경에서는 order/execution_attempt fallback 조회를 사용
- 프론트엔드
  - `BuyBlockSummary` 타입 및 API client 추가
  - Operations Dashboard에 `오늘 BUY 차단` StatusCard 추가
  - 카드 문구: `결정 X / 주문 Y | 정책 A · sizing B · watch C`

## 검증
- 백엔드: `pytest -q tests/api/test_inspection.py -k 'buy_block_summary or daily_summary'` → 2 passed
- 프런트: `cd admin_ui && npx vitest run src/__tests__/dashboard.test.tsx` → 15 passed
- 타입: `cd admin_ui && npx tsc --noEmit` 통과

## 기대 효과
- 장중/장후에 BUY가 왜 안 나갔는지 운영 화면에서 즉시 확인 가능
- 정책 차단과 시세/사이징 차단을 구분 가능
- 동일 분석을 반복하기 위한 수동 SQL/로그 확인 비용 감소
