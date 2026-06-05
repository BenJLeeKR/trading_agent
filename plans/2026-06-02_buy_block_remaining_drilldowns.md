# 2026-06-02 BUY 차단 나머지 드릴다운 링크 추가

## 배경
이전 단계에서 BUY 차단 카드에 `core / overlay / gate / budget / sizing` 드릴다운 링크를 추가했다.

하지만 운영자가 자주 확인해야 하는 나머지 범주가 아직 남아 있었다.

- held_position 정책 차단
- hold 결정
- watch 결정
- quote 실패

## 목표
- BUY 차단 카드의 모든 주요 범주를 드릴다운 가능하게 맞춘다.

## 구현
- `admin_ui/src/components/OperationsDashboardView.tsx`
  - 다음 링크 추가
    - `hp정책 보기`
    - `hold 보기`
    - `watch 보기`
    - `quote 실패 보기`

## 링크 규칙
- `hp정책 보기`
  - `date + side=buy + source_type=held_position + decision_type=approve + has_order=false`
- `hold 보기`
  - `date + side=buy + decision_type=hold`
- `watch 보기`
  - `date + side=buy + decision_type=watch`
- `quote 실패 보기`
  - `date + side=buy + latest_stop_reason=missing_reference_price_for_market_buy`

## 테스트
- `admin_ui/src/__tests__/dashboard.test.tsx`
  - 신규 링크들의 `href`를 직접 검증

## 기대 효과
- BUY 차단 카드의 대부분 숫자에서 바로 상세 목록으로 이동 가능
- 운영자가 “왜 BUY가 안 나갔는지”를 한 화면 내에서 더 완결적으로 추적 가능
