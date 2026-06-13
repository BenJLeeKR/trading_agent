# Trading Universe Coverage Summary API

## 목적
- 최근 N일 기준으로 `source_type`별 universe→decision→order 전환 현황을 운영자가 바로 확인할 수 있게 한다.
- 특히 `market_overlay`가 실제로 decision과 order 생성까지 이어졌는지 장중/장후 점검할 수 있는 read-only 관측값을 제공한다.

## 추가 endpoint
- `GET /instruments/trading-universe/coverage-summary?lookback_days=14`

## 응답 핵심
- `total_decision_count`
- `total_order_count`
- `market_overlay_active`
- `items[]`
  - `source_type`
  - `decision_count`
  - `order_count`
  - `order_conversion_rate`
  - `first_decision_at`
  - `last_decision_at`
  - `last_order_at`

## 의미
- 이제 `market_overlay가 아예 안 돌고 있는가`와
  `돌긴 도는데 주문 전환이 막히는가`를 분리해서 볼 수 있다.
- Universe Selection 10번 항목의 `실운영 편입/효과 측정`을 위한
  최소 운영 계측 레이어로 사용한다.
