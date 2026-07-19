# Market Overlay Funnel API

## 목적
- `market_overlay`가 실운영에서 실제로 판단과 주문까지 이어지는지 장중/장후에 바로 확인할 수 있게 한다.
- 기존 `coverage-summary`가 `source_type` 전체 집계라면, 이 API는 `market_overlay`만 분리해서 본다.

## 추가 endpoint
- `GET /instruments/trading-universe/market-overlay-funnel?lookback_days=14&sample_limit=20`

## 응답 핵심
- `decision_count`
- `order_count`
- `order_conversion_rate`
- `decision_type_counts`
- `order_status_counts`
- `recent_items[]`
  - `trade_decision_id`
  - `symbol`
  - `market`
  - `decision_type`
  - `side`
  - `inclusion_reason`
  - `rationale_summary`
  - `created_at`
  - `order_request_id`
  - `order_status`
  - `order_created_at`

## 의미
- `market_overlay가 아예 decision 0건인가`
- `decision은 나오지만 order 전환이 0건인가`
- `최근 실제 샘플 심볼/판단/주문상태가 무엇인가`

를 한 번에 확인할 수 있다.

## 운영 활용
- 장중에는 `recent_items`로 가장 최근 `market_overlay` 샘플을 본다.
- 장후에는 `decision_type_counts`, `order_status_counts`, `order_conversion_rate`로 품질을 요약한다.
- 이후 운영 UI 연계 시에는 이 endpoint를 그대로 카드/테이블 데이터 소스로 사용할 수 있다.
