# 2026-06-02 BUY 주문 생성 드릴다운 링크 추가

## 배경
`오늘 BUY 차단` 카드는 차단 사유별 드릴다운 링크가 많이 보강되었지만, 같은 카드 안에서 실제로 주문이 생성된 BUY 경로는 바로 내려갈 수 없었다.

운영자는 차단 건뿐 아니라 `주문 생성된 BUY`도 같은 맥락에서 바로 확인할 수 있어야 한다.

## 목표
- `buy_orders_created_count`에 대응하는 드릴다운 링크를 BUY 차단 카드에 추가

## 구현
- `admin_ui/src/components/OperationsDashboardView.tsx`
  - `주문 생성 보기 →` 링크 추가
  - 경로:
    - `/decisions?date=<KST date>&side=buy&has_order=true`

## 테스트
- `admin_ui/src/__tests__/dashboard.test.tsx`
  - `주문 생성 보기 →` 링크의 `href` 검증

## 기대 효과
- BUY 차단 카드 하나에서
  - 차단된 BUY
  - 실제 주문 생성된 BUY
  를 모두 드릴다운 가능
- 운영자가 성공/차단 경로를 같은 화면 컨텍스트에서 비교 가능
