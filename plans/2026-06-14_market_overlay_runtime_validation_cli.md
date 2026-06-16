# Market Overlay Runtime Validation CLI

## 목적
- `market_overlay 실운영 편입/효과 장중 실측`을 반복 가능하게 만든다.
- 장중 또는 장후에 CLI 1회 실행만으로 아래를 확인한다.
  - 현재 preview에 `market_overlay`가 실제 편입되는가
  - quote fetch 품질은 어떤가
  - 최근 lookback 구간에 `market_overlay` decision이 있었는가
  - order 전환까지 이어졌는가
  - 병목 단계가 `universe_selection / decision_loop / order_conversion / active` 중 어디인가

## 실행
```bash
python3 -m scripts.evaluate_market_overlay_runtime_validation
python3 -m scripts.evaluate_market_overlay_runtime_validation --output json
python3 -m scripts.evaluate_market_overlay_runtime_validation --account-id <ACCOUNT_UUID>
```

## 출력 핵심
- `overall_status`
- `bottleneck_stage`
- `preview_market_overlay_count`
- `decision_count`
- `order_count`
- `checks[]`
- `recent_samples[]`

## persisted summary
- 기본값으로 `operations_day_runs.summary_json.market_overlay_runtime_validation`에 compact summary를 적재한다.
- 이 값은 이후 운영 대시보드/운영 리포트에서 재사용할 수 있다.

## 병목 해석
- `account_resolution`
  - preview용 활성 계좌를 찾지 못함
- `universe_selection`
  - preview 비활성 / quote 0건 / 후보 생성 실패
- `decision_loop`
  - preview에는 overlay가 있으나 최근 decision 없음
- `order_conversion`
  - decision은 있으나 order 전환 없음
- `active`
  - preview, decision, order 전환이 모두 관측됨
