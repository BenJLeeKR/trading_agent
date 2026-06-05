# 2026-06-02 의사결정 드릴다운 배너 prefix 문구 정리

## 배경
드릴다운 배너에서 `latest_stop_reason_prefix`와 `has_order`는 여전히 raw query 값이 그대로 보였다.

- `general_submit_disabled`
- `submit_budget_consumed`
- `has_order=false`

운영 화면 기준으로는 사람이 읽는 문구로 바꾸는 편이 맞다.

## 목표
- 드릴다운 배너에서 prefix와 has_order를 사람이 읽는 문구로 치환

## 구현
- `admin_ui/src/components/DecisionsView.tsx`
  - `stopReasonPrefixLabel()` 추가
    - `general_submit_disabled` → `제출 비활성`
    - `submit_budget_consumed` → `예산 소진`
  - `hasOrderLabel()` 추가
    - `true` → `주문 있음`
    - `false` → `주문 없음`

## 테스트
- `admin_ui/src/__tests__/decisions.test.tsx`
  - prefix + has_order 조합에서
    - `사유 제출 비활성`
    - `주문 없음`
  - 노출 검증

## 기대 효과
- 드릴다운 배너에 raw query string이 덜 보임
- 운영자가 필터 상태를 더 빠르게 읽을 수 있음
