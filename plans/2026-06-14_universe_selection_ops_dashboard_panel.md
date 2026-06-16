# Universe Selection Ops Dashboard Panel

## 목적
- 운영 대시보드에서 `Universe Selection`과 `market_overlay` 상태를 별도 API 호출 없이 바로 확인할 수 있게 한다.
- 장중/장후에 운영자가 아래 질문에 즉시 답할 수 있도록 한다.
  - `market_overlay가 preview에 실제 편입됐는가`
  - `최근 decision이 발생했는가`
  - `order 전환까지 이어졌는가`
  - `최근 샘플 심볼은 무엇인가`

## 반영 화면
- `admin_ui/src/components/OperationsDashboardView.tsx`

## 사용 API
- `GET /instruments/trading-universe/preview`
- `GET /instruments/trading-universe/coverage-summary`
- `GET /instruments/trading-universe/market-overlay-funnel`

## 화면 구성
- `Preview 편입`
  - 현재 preview 기준 `market_overlay` 편입 개수
  - quote 요청/수신 수
- `최근 판단`
  - 최근 N일 `market_overlay` decision 수
- `주문 전환`
  - 최근 N일 `market_overlay` order 수 / 전환율
- `Coverage 상태`
  - `market_overlay_active`
  - source_type 기준 decision / order 수
- `Overlay 진단`
  - enabled / skipped_reason / pre-pool / scored / filtered out
- `판단 / 주문 분포`
  - decision_type_counts
  - order_status_counts
- `최근 샘플 테이블`
  - 판단시각 / 종목 / 판단 / 매매 / 편입사유 / 주문상태

## 의미
- 이제 `market_overlay 실운영 편입/효과 장중 실측`의 운영 화면 경로가 생겼다.
- 별도 admin 메뉴를 추가하지 않고, 기존 `운영 대시보드` 안에서 바로 관측할 수 있게 유지했다.
