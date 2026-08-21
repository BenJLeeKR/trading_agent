# 2026-06-02 BUY 차단 요약에서 general_dry_run 세분화

## 배경
`오늘 BUY 차단` 카드에 `general_dry_run_blocked_count`만 표시되면, 실제로 어떤 경로가 막혔는지 해석하기 어렵다. 2026-06-02 데이터상 이 수치는 `core approve dry-run`과 `market_overlay approve dry-run`이 합쳐진 값이었고, 운영 판단에는 이 둘을 분리해서 보는 편이 훨씬 직접적이다.

## 목표
- `general_dry_run_blocked_count`는 유지하되
- 내부 구성인 `core_dry_run_blocked_count`, `market_overlay_dry_run_blocked_count`를 추가
- 대시보드 카드 subtitle에서 바로 노출

## 구현 내용
- 백엔드
  - `BuyBlockSummaryResponse`에 다음 필드 추가
    - `core_dry_run_blocked_count`
    - `market_overlay_dry_run_blocked_count`
  - `GET /orders/buy-block-summary`에서
    - `source_type == 'core'` 인 dry-run BUY 승인건을 `core_dry_run_blocked_count`
    - `source_type == 'market_overlay'` 인 dry-run BUY 승인건을 `market_overlay_dry_run_blocked_count`
    로 분리 집계
- 프런트
  - `BuyBlockSummary` 타입에 두 필드 추가
  - `오늘 BUY 차단` 카드 subtitle을 아래 형식으로 변경
    - `core X · overlay Y · hp정책 Z · sizing A · hold B · watch C`

## 검증
- 백엔드: `pytest -q tests/api/test_inspection.py -k 'buy_block_summary or daily_summary'` → 2 passed
- 프런트: `cd admin_ui && npx vitest run src/__tests__/dashboard.test.tsx` → 15 passed
- 타입: `cd admin_ui && npx tsc --noEmit` 통과

## 기대 효과
- 같은 `general_dry_run`이라도 core 전략 차단과 market overlay 차단을 구분 가능
- 운영자가 BUY 0건 원인을 더 직접적으로 해석 가능
