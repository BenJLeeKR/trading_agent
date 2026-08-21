# 2026-06-02 BUY 차단 gate vs budget 분리

## 배경
`오늘 BUY 차단` 카드는 이미 core/overlay dry-run을 구분하고 있었지만, 운영자가 실제 원인을 보려면 한 단계 더 필요했다.

- `general submit disabled`
- `submit budget consumed`

두 경우 모두 기존에는 `core` 또는 `overlay` 숫자 안에 섞여 있었다.

## 목표
- `GET /orders/buy-block-summary` 응답에 `gate`와 `budget` 집계를 추가
- 운영 대시보드에서 core/overlay와 함께 `gate`, `budget`을 즉시 확인 가능하게 보강
- 과거 데이터 호환성은 유지하고, 신규 데이터부터는 DB stop reason 기반으로 정확히 분리

## 구현

### 백엔드
- `src/agent_trading/api/schemas.py`
  - `BuyBlockSummaryResponse`에 다음 필드 추가
    - `general_submit_disabled_count`
    - `submit_budget_consumed_count`

- `src/agent_trading/api/routes/orders.py`
  - `execution_attempts.stop_reason` 기준 분기 추가
    - `general_submit_disabled_core`
    - `general_submit_disabled_market_overlay`
      - `general_submit_disabled_count += 1`
    - `submit_budget_consumed_core`
    - `submit_budget_consumed_market_overlay`
      - `submit_budget_consumed_count += 1`
  - 기존 `general_dry_run_blocked_count`, `core_dry_run_blocked_count`, `market_overlay_dry_run_blocked_count`도 그대로 유지

### 프런트엔드
- `admin_ui/src/types/api.ts`
  - `BuyBlockSummary` 타입에 신규 필드 반영

- `admin_ui/src/components/OperationsDashboardView.tsx`
  - 카드 subtitle을 다음 구조로 확장
  - `결정 X / 주문 Y | core A · overlay B · gate C · budget D · hp정책 E · sizing F · hold G · watch H`

## 테스트
- `tests/api/test_inspection.py`
  - core `general_submit_disabled`
  - market overlay `submit_budget_consumed`
  - 두 경로가 서로 다른 집계 필드로 반영되는지 확인

- `admin_ui/src/__tests__/dashboard.test.tsx`
  - 대시보드 subtitle에 `gate`, `budget` 숫자가 노출되는지 확인

## 기대 효과
- 운영자가 `BUY가 왜 안 나갔는지`를 더 직접적으로 해석 가능
- `core/overlay` 규모와 함께 `정책상 비활성`인지 `예산 소진`인지 바로 구분 가능
- 과거 데이터는 기존 수준(core/overlay)으로 보이고, 신규 데이터부터 정밀도가 올라감
