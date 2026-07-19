# HANDOVER TO NEW SESSION

## Current Status

이 세션에서 가장 크게 진척된 축은 4개다.

1. **주문 제출 경로 복구**
- `run_paper_decision_loop.py`의 전역 `KIS_SMOKE_PRICE` 의존을 줄이고 symbol별 quote 기반 가격 경로를 넣었다.
- `src/agent_trading/brokers/koreainvestment/adapter.py`에서 `get_quote()`/`get_orderbook()` 파싱 버그를 수정했다.
  - `last <- stck_prpr`
  - `bid <- stck_bidp`
  - `ask <- stck_askp`
- host에서 직접 돌던 scheduler가 Docker 반영 코드를 타지 않던 문제를 확인했고, host scheduler 재시작으로 hotfix 반영 여부를 검증했다.
- `source=live_quote` 로그가 실제로 찍히는 것까지 확인됐다.

2. **submit budget / cleanup / reconcile 정책 P0 구현**
- `scripts/run_near_real_ops_scheduler.py`
  - `_BUDGET_CONSUMING_STATUSES`에서 `reconcile_required` 제거
  - `reconcile_required`가 submit gate를 닫지 않도록 수정
- `_cleanup_pending_submit.py`
  - 일반 stale cleanup 24h
  - `40270000` known failure fast cleanup 1h
  - `broker_orders`가 있는 주문 보호
- `src/agent_trading/services/order_sync_service.py`
  - `RECONCILE_REQUIRED`를 sync 대상에 포함
  - broker truth 조회 후 상태 전이 가능한 경로 추가

3. **broker truth 복구 및 이벤트 API 500 hotfix**
- `000880` 주문 1건은 실제로 체결되었음이 broker position snapshot으로 확인되었고, 잘못된 reject 정리를 복구했다.
- 복구 provenance:
  - `broker_truth_recovery`
  - `position-derived recovery`
- 그 후 `/orders/{id}/events`가 `event_source.value` 가정 때문에 500을 냈고, `src/agent_trading/api/routes/orders.py`에 `_safe_str()` 방어를 넣어 enum/str 혼용을 안전하게 직렬화하도록 수정했다.

4. **Admin UI 시간/KRW/AccountsView 금액 정합성**
- `admin_ui/src/lib/utils.ts`
  - `formatKstDateTime()`
  - `formatKstTime()`
  - `formatKrw()`
  - `formatKstElapsed()`
- 주요 운영 화면의 시간 표시를 KST 기준으로 통일했다.
- KRW 표기를 `원` suffix로 통일했다.
- `AccountsView` 상단 요약은 KIS `주식잔고조회 output2` 기준으로 연결하도록 작업했다.
  - `tot_evlu_amt` → `total_asset`
  - `prvs_rcdl_excc_amt` → `settlement_amount`
  - `evlu_pfls_smtl_amt` → `total_unrealized_pnl`
- 관련 주요 파일:
  - `src/agent_trading/domain/entities.py`
  - `src/agent_trading/brokers/koreainvestment/snapshot.py`
  - `src/agent_trading/services/kis_snapshot_sync.py`
  - `src/agent_trading/repositories/postgres/cash_balance_snapshots.py`
  - `src/agent_trading/api/schemas.py`
  - `admin_ui/src/types/api.ts`
  - `admin_ui/src/components/AccountsView.tsx`
  - `db/migrations/0012_add_kis_output2_fields.sql`

### 이번 세션에서 중요하게 변경된 파일

- `src/agent_trading/brokers/koreainvestment/adapter.py`
- `src/agent_trading/brokers/koreainvestment/rest_client.py`
- `scripts/run_paper_decision_loop.py`
- `scripts/run_near_real_ops_scheduler.py`
- `_cleanup_pending_submit.py`
- `src/agent_trading/services/order_sync_service.py`
- `src/agent_trading/api/routes/orders.py`
- `src/agent_trading/domain/entities.py`
- `src/agent_trading/brokers/koreainvestment/snapshot.py`
- `src/agent_trading/services/kis_snapshot_sync.py`
- `src/agent_trading/repositories/postgres/cash_balance_snapshots.py`
- `src/agent_trading/api/schemas.py`
- `admin_ui/src/lib/utils.ts`
- `admin_ui/src/components/OrdersView.tsx`
- `admin_ui/src/components/OrderTrackingView.tsx`
- `admin_ui/src/components/AccountsView.tsx`
- `admin_ui/src/components/OperationsAlertsView.tsx`
- `plans/submit_budget_and_order_cleanup_policy.md`
- `plans/event_source_type_policy.md`

## Work In Progress

### 1. cash snapshot 최신화 문제

가장 큰 미해결 이슈는 **position은 최신인데 cash snapshot은 늦게 멈추는 현상**이다.

- 보고서:
  - `plans/cash_snapshot_freshness_gap_analysis_2026-05-15.md`
  - `plans/cash_sync_count_mismatch_root_cause_2026-05-15.md`
- 현재까지 판정:
  - 코드상 `cash=1` vs DB `cash_synced_count=0` 불일치는 집계 버그가 아니라 **관측 window 차이**
  - 장 마감 후 KIS paper cash 응답이 끊기는 현상이 관측됨
  - 하지만 아직 확정하지 말고, **KIS 장후 cash 조회가 원래 불가능한지 vs 현재 요청 파라미터/호출 방식이 잘못된 건지**를 다시 검증해야 함
- 다음 턴 우선 과제:
  - `KIS cash balance 장후 조회 가능 여부 및 요청 파라미터 검증`
  - 이미 Roo prompt 초안이 존재하고, 장후 문서 기반 + 실측 기반 비교를 해야 함

### 2. AccountsView 상단 금액이 여전히 기대와 다를 수 있음

매핑/저장 경로는 보완됐지만, **최신 cash snapshot 자체가 생성되지 않으면** 상단 값은 최신 포지션과 어긋나 보일 수 있다.

- 즉, 이건 프런트 버그보다 운영 데이터 freshness 문제에 더 가깝다.
- `cash_balance_snapshots` 최신 row 생성 시각과 `position_snapshots` 최신 row 생성 시각을 계속 비교해야 함.

### 3. HOLD bias 후속 과제는 아직 미완료

Backlog에 추가는 했지만 구현은 안 됐다.

- `WATCH decision 부재 원인 분석 및 정책 보완`
- `core + no_event 100% HOLD 완화`
- `market_overlay 실운영 반영 검증`

관련 문서:
- `plans/ei_fdc_hold_bias_analysis.md`
- `plans/hold_bias_mitigation_effect_report.md`
- `plans/intraday_market_overlay_dryrun_report_2026-05-15.md`

### 4. 장중 실주문 경로 재검증 필요

여러 hotfix 이후에도 장중 운영 상태는 **관측으로 재확인**해야 한다.

중요 포인트:
- `APPROVE -> submitted / reconcile_required / filled`
- `source=live_quote` 유지 여부
- `40270000` 재발 여부
- `reconcile_required`가 budget을 막지 않는지

### 5. event_source 타입 정책은 문서화만 끝났고 구현은 P0 hotfix 수준

- 문서: `plans/event_source_type_policy.md`
- 현재 정책:
  - core domain은 enum 유지
  - recovery / ops artifact는 string escape hatch 허용
- 장기적으로 row mapper / schema / DB comment / 공통 serializer 정리를 할 수 있음

## Implicit Context

### 1. 사용자 협업 원칙

- 사용자는 **직접 구현 요청이 없으면 Roo Code용 프롬프트만 원함**
- 단, 이번 턴처럼 사용자가 명시적으로 “Codex가 직접 작성해달라”고 하면 직접 작업 가능

### 2. dry-run / backend prompt 규칙

- dry-run이 포함되는 프롬프트에는 반드시 `TZ=Asia/Seoul`
- backend 수정 프롬프트에는 반드시 Docker rebuild/restart + `/health` 확인 지시 포함

### 3. 장중 backend 수정 금지 원칙의 예외

원칙적으로 장중 backend 수정은 피하지만, 아래는 예외로 합의됨.

- 주문 제출 경로가 막히는 경우
- stale snapshot guardrail로 전 주문이 막히는 경우
- broker submit/reconcile 경로의 critical 장애
- 로그/관측만으로 원인 분리가 안 되고 즉시 수정 없이는 운영이 불가능한 경우

이번 세션의 `pending_submit`, `get_quote()` 파싱 버그, scheduler host process hotfix 적용, `/orders/{id}/events` 500 등은 이 예외에 해당했다.

### 4. scheduler는 Docker가 아니라 host process일 수 있음

이게 매우 중요하다.

- Docker rebuild를 해도 실제 `run_near_real_ops_scheduler.py`가 **host에서 직접 실행 중이면** hotfix가 반영되지 않는다.
- 실제로 이번 세션에서 그 문제를 겪었고, host scheduler를 재시작해야 live quote hotfix가 반영됐다.
- 새 세션에서도 운영 장애 조사 시:
  1. Docker 코드 반영 여부
  2. 실제 host scheduler PID / command line
둘 다 확인해야 한다.

### 5. broker truth > internal inferred state

운영/정합성 원칙은 명확하다.

- broker fill / broker position / broker order status가 최상위 truth
- internal inferred state, cleanup heuristic, stale pending 자동 정리는 그 아래
- 000880 주문은 이 원칙 때문에 reject 복구가 필요했다.

### 6. `reconcile_required`는 실패가 아니라 미확정 상태

- submit budget consuming에서 제외하는 쪽으로 정책 전환
- 자동 reject 금지
- broker truth 조회 후 상태 수렴 시도
- paper 한계로 바로 filled로 안 갈 수 있어도 상태 유지가 더 안전

### 7. KIS `주식잔고조회 output2` 매핑의 authoritative source

다음 3개는 이미 문서/코드 상 기준이 합의됨.

- `tot_evlu_amt` → 총자산 (`total_asset`)
- `prvs_rcdl_excc_amt` → 현금잔고 (`settlement_amount`)
- `evlu_pfls_smtl_amt` → 미실현손익 (`total_unrealized_pnl`)

참고:
- `output1.evlu_pfls_amt`는 종목별 평가손익
- `output2.evlu_pfls_smtl_amt`는 계좌 총괄 평가손익

### 8. Admin UI 시간 문제의 본질

- DB는 UTC 저장으로 정상
- 문제는 화면별 formatter 불일치였음
- 특히 처음에는 Roo가 “전부 고쳤다”고 했지만, 실제로는
  - `OrdersView.tsx`
  - `AccountsView.tsx`
  - `OperationsAlertsView.tsx`
에 raw UTC 누락이 남아 있었고, 후속으로 추가 보완함

### 9. 아직 문서화는 됐지만 구현이 안 된 후속 과제

가장 가능성 높은 다음 작업:

1. `KIS cash balance 장후 조회 가능 여부 및 요청 파라미터 검증`
2. `WATCH=0`, `core+no_event=100% HOLD`, `market_overlay 실운영 반영` 후속
3. `AccountsView` stale cash snapshot 경고/표시 정책

### 10. 바로 참조하면 좋은 문서

- `plans/submit_budget_and_order_cleanup_policy.md`
- `plans/event_source_type_policy.md`
- `plans/cash_snapshot_freshness_gap_analysis_2026-05-15.md`
- `plans/cash_sync_count_mismatch_root_cause_2026-05-15.md`
- `plans/ei_fdc_hold_bias_analysis.md`
- `plans/hold_bias_mitigation_effect_report.md`
- `plans/intraday_reconcile_required_convergence_observation_2026-05-15.md`
- `plans/recover_000880_broker_truth_order_2026-05-15.md`
