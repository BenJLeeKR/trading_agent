# Backlog — Future Work Candidates

> **목적**: 번호가 부여된 실행 계획(canonical numbered plan)과 아직 착수하지 않은 작업 아이디어를 분리하여 관리한다.
>
> **원칙**: "실행할 때만 번호 Plan 생성, 아직 시작하지 않을 작업은 BACKLOG에만 기록."

---

## 관리 원칙

1. **Backlog 항목이 실제 실행으로 전환될 때**: BACKLOG.md에서 해당 항목을 `[x]`로 표시하고, 새 numbered plan을 생성한다. BACKLOG.md에는 짧게 상태 업데이트 (예: `→ Plan 41로 승격`).
2. **새로운 아이디어는 항상 BACKLOG 우선**: numbered plan에 바로 포함하지 않는다. 일단 BACKLOG에 기록하고, 실행 시점에 평가 후 승격.
3. **정기적 검토**: Plan 완료 시 BACKLOG를 검토하여 다음 우선순위를 결정한다.
4. **기존 numbered plan 문서는 건드리지 않는다**: BACKLOG.md가 future work의 단일 진실 공급원(single source of truth).

---

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Paper Trading Loop 연속 실행**: 주기적 orchestrator loop + fill sync + position/cash refresh. `run_paper_decision_loop.py` (300s 간격, CLI 옵션 6종, graceful shutdown). `verify_paper_loop.py --interval`은 assemble/submit만 반복; fill polling, position/cash 자동 갱신은 미포함 | Paper Trading Loop Validation | ✅ 승격됨 |
| 1b | **Event Ingestion Loop**: 외부 이벤트 수집을 독립 운영 데몬으로 승격. `scripts/run_event_ingestion_loop.py` + `_build_polling_workers()` 재사용. Source isolation + cycle summary. 60s 간격. ~14 tests | [paper_trading_loop_validation.md](plans/paper_trading_loop_validation.md) | ✅ 승격됨 |
| 2 | **Replay-Style 검증 엔진 고도화**: 저장된 decision context 기반 결정론적 재현 검증 엔진. core replay engine (ReplayBundle + _build_repos + 5 scenarios + 2-run identity) 구현 완료. 전체 DB 기반 replay 경로는 후속 과제로 잔류 | Paper Trading Loop Validation | ✅ 승격됨 |
| 3 | **Snapshot Staleness Guardrail (Phase 5)**: submit 단계에서 position/cash snapshot freshness 검사. stale snapshot 시 RECONCILE_REQUIRED + status_reason_code="STALE_SNAPSHOT". `test_scenario_4_stale_snapshot_guard` 참조 | Paper Trading Loop Validation | ✅ 승격됨 |
| 4 | **Fill Sync / Post-Submit Update**: 주문 제출 후 broker로부터 fill 상태를 주기적으로 polling하는 루틴. `reconciliation_service.resolve_unknown_state()` 자동화 | Paper Trading Loop Validation | ✅ 승격됨 |
| 5 | **Plan 40 Phase 2 — API endpoints 확장**: `GET /orders/{id}/broker-orders`, `GET /accounts`, `GET /accounts/{id}`, `GET /clients/{id}`, `GET /instruments/{id}`, `GET /positions`, `GET /cash-balances`, `GET /guardrail-evaluations`, `GET /risk-limit-snapshots`, `GET /agent-runs` | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ❌ 미착수 |
| 6 | **Plan 40 Phase 2 — Postgres-backed API mode**: `create_app()`에 Postgres repository 주입 지원, `runtime_mode="postgres"` 모드 | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ❌ 미착수 |
| 7 | **Reconciliation blocking lock list API**: `GET /reconciliation/locks` 구현을 위해 reconciliation repository에 `list_locks()` 메서드 추가. 현재 `is_blocked()`만 존재 | [Plan 40](plans/40_fastapi_inspection_api.md) | ❌ 미착수 |
| 8 | **KIS real credential + combined submit smoke**: KIS 실제 API key 확보 후 `tests/smoke/test_kis_paper_smoke.py` 등 combined submit smoke 실행 | [Plan 36](plans/36_kis_paper_ai_runtime_smoke.md) | ❌ 미착수 |
| 9 | **Docs/OpenAPI 보호 옵션 (inspection API)**: `/docs`와 `/openapi.json`을 auth 보호 대상에 포함. 현재는 공개 유지 중 | Plan 47 | ❌ 미착수 |
| 10 | **Admin UI P1 — DecisionsView detail panel**: 특정 decision 행 클릭 시 TradeDecisionDetail 또는 DecisionContextDetail 내용을 inline panel 또는 modal로 표시. 현재는 단순 리스트만 존재 | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | ❌ 미착수 |
| 11 | **Admin UI P1 — AccountsView filter/selection 개선**: 계좌 목록 필터 (type, strategy) 및 선택 시 상세 영역 시각적 개선 | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | ❌ 미착수 |
| 12 | **Admin UI — Dashboard reconciliation metrics**: Dashboard에 정합성 점검 메트릭 (불일치 수, 마지막 실행 시각) 추가. 현재는 locks만 표시 | Plan 53 | ❌ 미착수 |
| 13 | **Admin UI — Dashboard/Accounts/Broker Capacity freshness visualization**: 데이터 신선도(freshness) 시각화. 각 데이터 소스별 마지막 업데이트 시각 표시 및 지연 경고 | Plan 53 | ❌ 미착수 |
| 14 | **Position/Cash Refresh After Fill**: Fill 발생 후 position snapshot/cash balance snapshot 자동 갱신 경로. Snapshot sync loop와 decision pipeline 연결 | Paper Trading Loop Validation | ❌ 미착수 |
| 15 | **Paper PnL / Performance Summary**: 체결/포지션/현금 데이터 기반 성과 집계. `AccountPerformanceSummary` + `StrategyPerformanceSummary`. Realized/Unrealized/Total PnL. `GET /performance-summary` API. 18개 신규 테스트 | Paper Trading Loop Validation | ✅ 승격됨 |
| 16 | **Postgres BrokerOrderRepository.update() 구현**: 현재 InMemory 전용 `update()`를 Postgres에도 구현. `PostgresBrokerOrderRepository.update()`에 SQL UPDATE + `last_synced_at` 반영 | Fill Sync / Post-Submit Update | ❌ 미착수 |
| 17 | **Scheduler 기반 정기 Post-Submit Sync**: `OrderSyncService`를 주기적으로 실행하는 scheduler loop. 미체결/부분체결 주기적 polling으로 상태 최신성 유지 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 18 | **FillEvent에 broker_fill_id 필드 추가**: 현재 fill dedup이 `(timestamp, price, quantity)` tuple 기반. broker 고유 fill ID로 dedup 강화 | Fill Sync / Post-Submit Update | ❌ 미착수 |
| 19 | **WebSocket 기반 실시간 order event 수신**: polling → WS event 기반 post-submit update 전환. KIS WS order event channel 연동 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 20 | **Pipeline Phase 5.5 Post-Submit Sync 연동**: `assemble_and_submit()`에서 submit 직후 첫 1회 `OrderSyncService.sync_order_post_submit()` 호출. 실패 무시, timeout 5s | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 21 | **Snapshot refresh 직접 통합**: `OrderSyncService`가 FILLED terminal 감지 시 snapshot refresh callback 직접 호출. 현재는 optional callback으로 위임 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 22 | **Paper PnL History / Trend**: 기간 필터 기반 일별 성과 시계열 조회. `DailyPerformancePoint` dataclass + `get_daily_history()` service method. `GET /performance-history` API. Per-fill PnL 계산. Snapshot 날짜 선택 로직. 15개 신규 테스트 | Paper Performance Summary | ✅ 승격됨 |
| 23 | **Paper Performance Metrics**: 기간 기반 성과 지표 추가. `PerformanceMetrics` dataclass(17 fields) + `_calc_equity_metrics()`/`_calc_win_loss_metrics()` pure helpers. Cumulative return/drawdown/win-rate/avg-win-avg-loss/profit-factor. `get_performance_metrics()` service method. `GET /performance-metrics` API. Per-order 기준 win/loss 정책. 10개 신규 테스트 | Paper Performance Summary | ✅ 승격됨 |

## Medium-term (다음 마일스톤)

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Admin UI**: 시스템 상태 모니터링, 주문/계좌 조회, 설정 관리 웹 UI | [ENTERPRISE_TRADING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | ✅ Plan 48로 승격 |
| 2 | **Auth / RBAC for admin API**: Static Bearer token 인증, viewer/admin RBAC, public/protected endpoint 정책 | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ✅ Plan 46으로 승격 |
| 3 | **Operator intervention workflow**: 사람이 개입하여 주문 상태 강제 변경, kill switch override, 수동 reconciliation | [ENTERPRISE_TRADING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | ❌ 미착수 |
| 4 | **Migration 0010: Drop legacy `decision` column**: `trade_decisions.decision` 컬럼 제거. Plan 39에서 nullable로 완화한 후 추가 검증 후 완전 삭제 | [Plan 39](plans/39_trade_decision_schema_alignment.md:294) | ❌ 미착수 |
| 5 | **E2E test with TradeDecisionEntity creation**: AI agent 통합 완료 후 E2E 테스트에서 실제 `TradeDecisionEntity` 생성 및 `trade_decision_id` 참조 검증 | [Plan 39](plans/39_trade_decision_schema_alignment.md:296) | ❌ 미착수 |

---

## Longer-term (아키텍처 개선 / 안정성)

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Soak / recovery / chaos tests**: 장기 실행 안정성, 장애 복구, 비정상 입력 내성 검증 | 여러 Plan | ❌ 미착수 |
| 2 | **Provider failover / fallback hardening**: LLM provider 장애 시 fallback 전략 고도화 (auto-retry, provider 전환) | [Plan 29](plans/29_ai_decision_backend_contract.md:471), [Plan 30](plans/30_runtime_three_agent_smoke.md:555) | ❌ 미착수 |
| 3 | **Replay UX / audit inspection 개선**: Replay Engine UX 개선, audit 로그 검색/필터 고도화 | [Plan 37](plans/37_long_path_end_to_end_integration.md) | ❌ 미착수 |
| 4 | **Event loop gap-fill path `transition_to()` 검토**: `trigger_gap_fill()`이 ExternalEvent persist만 수행. 향후 fill data → order state 반영 경로 필요 여부 검토 | [Plan 35](plans/35_reconciliation_authoritative_state_reflection.md:844) | ❌ 미착수 |
| 5 | **Reconciliation 결과로 PARTIALLY_FILLED 반영 검토**: 현재는 authoritative reflection에서 PARTIALLY_FILLED 제외. 실제 broker 사례 발생 시 재검토 | [Plan 35](plans/35_reconciliation_authoritative_state_reflection.md:845) | ❌ 미착수 |
| 6 | **Reconciliation Run에 order_id 직접 매핑**: `_resolve_order_for_reflection()`이 broker_order_id/client_order_id로 찾는 방식. 향후 run에 직접 order_id 저장 검토 | [Plan 35](plans/35_reconciliation_authoritative_state_reflection.md:846) | ❌ 미착수 |

---

## Deferred / Nice-to-have (현재 계획 없음)

| # | 항목 | 출처 | 비고 |
|---|------|------|------|
| 1 | KIS 실통신 (real API key + live trading) | [ENTERPRISE_TRA`DING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | Paper mode 우선 |
| 2 | 키움증권 Broker Adapter | [ENTERPRISE_TRA`DING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md:99) | KIS 우선 |
| 3 | Full reconciliation automation (auto-resolve) | [Plan 10](plans/10.milestone6_broker_contract_reconciliation_alignment.md) | 현재는 minimal recovery hook만 |
| 4 | Real event data ingestion (OpenDART/KRX polling, news feed) | [Plan 12](plans/12.milestone7_broker_capacity_and_event_data.md:428) | v1 제외 |
| 5 | Redis cache layer (rate limit, session cache) | [Enterprise Design](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | 현재는 in-memory |
| 6 | CI/CD pipeline (K8s, Terraform, GitHub Actions) | [Plan 01](plans/01.dev_infrastructure_plan.md:6) | v1 제외 |
| 7 | Observability stack (metrics, tracing, structured logging, alerting) | [Enterpris`e Design](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | v1 제외 |

---

## 상태 범례

| 표시 | 의미 |
|------|------|
| ❌ 미착수 | 아직 시작하지 않음 |
| 🔄 검토 중 | 우선순위 평가 중 |
| ✅ 승격됨 | Numbered plan으로 승격됨 (하단 기록 참조) |
| 🗑️ 폐기 | 더 이상 추진하지 않기로 결정 |

## 승격 기록

| 날짜 | 항목 | Plan 번호 | 비고 |
|------|------|-----------|------|
| 2026-05-04 | Auth / RBAC for Inspection API | [Plan 46](plans/46_auth_rbac_inspection_api.md) | Static Bearer token, viewer/admin RBAC, router-level dependency, safe default |
| 2026-05-04 | Auth Policy Hardening (Pre-UI Security Pass) | [Plan 47](plans/47_auth_policy_hardening.md) | Docs/OpenAPI 공개 정책 고정, token/role validation 강화, 운영 문서 정리 |
| 2026-05-05 | Admin UI Phase 1 (Read-Only Operations Dashboard) | [Plan 48](plans/48_admin_ui_phase1.md) | Vite + React + TypeScript + Pico CSS SPA. FastAPI static serve. 5 screens. sessionStorage token. Phase 1 read-only. |
| 2026-05-05 | Admin UI Smoke / Component Test Hardening | [Plan 49](plans/49_admin_ui_test_hardening.md) | Vitest + RTL + jsdom. 24 tests (P0 16 + P1 8). Auth flow, Dashboard/OrdersView smoke, common components. URL+Method 분기 명확화. |
| 2026-05-05 | Admin UI Test Coverage Phase 2 | [Plan 50](plans/50_admin_ui_test_coverage_phase2.md) | P0 19개 + P1 7개 = 26개 신규 테스트. OrderDetail (7), AccountsView (6), ReconciliationView (6), Layout (4), DecisionsView (3). Fixture 8종 추가. 총 50 tests. |
| 2026-05-05 | Admin UI Operations Workflow Enhancements (P0) | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | OrdersView filter/search, OrderDetail→Decisions drill-down, ReconciliationView quick-filter+lock 강조, Dashboard signal+drill-down. 8개 신규 테스트. 총 58 tests. Backend API 변경 없음. |
| 2026-05-05 | Admin UI Phase 1.5 (Decisions / Accounts UX Completion) | [Plan 52](plans/52_admin_ui_phase1_5.md) | DecisionsView detail panel + context lazy-load (stale guard) + side/symbol/confidence filter + empty placeholder. AccountsView search/type filter + detail clarity + filter-reset policy. DataTable selectedKey prop. 12개 신규 테스트. 총 69 tests. Backend API 변경 없음. |
| 2026-05-08 | Admin UI 전면 한글화 + Pretendard 폰트 적용 | [Plan 66](plans/66_admin_ui_korean_localization.md) | 모든 사용자 노출 텍스트 한국어 변환 (14개 컴포넌트 + 11개 테스트). Pretendard 폰트 CDN 적용. 80/80 테스트 통과. Backend API 변경 없음. |
| 2026-05-08 | KIS Snapshot Sync 운영화 | [kis_snapshot_sync_operationalization.md](plans/kis_snapshot_sync_operationalization.md) | 수동 스크립트 기반 적재를 정기 실행 가능한 백엔드 작업으로 승격. `BatchSyncResult` + `sync_kis_accounts_by_ids()` + `sync_all_kis_accounts()` 추가. `--account-id` N개 + `--all` 플래그. `AccountLookup.broker_account_id` 필드 추가. 5개 batch sync 테스트 추가. 총 18/18 테스트 통과. |
| 2026-05-08 | KIS Snapshot Sync 운영화 — CLI 고도화 | [kis_snapshot_sync_operationalization.md](plans/kis_snapshot_sync_operationalization.md) | `sync_all_kis_accounts()`에 `env`/`account_status` 필터 파라미터 추가. CLI에 `--env paper\|live`, `--status`, `--account-ref`, `--dry-run`, `--format json` 5개 옵션 추가. `BrokerAccountRepository.list_by_broker_and_env()` contract 추가. 신규 테스트 6개(env 3 + status 3). 총 24/24 테스트. |
| 2026-05-08 | KIS Snapshot Sync 실행 이력 저장 | [kis_snapshot_sync_run_history.md](plans/kis_snapshot_sync_run_history.md) | `SnapshotSyncRunEntity` + migration 0011 + `SnapshotSyncRunRepository`(Protocol/Postgres/InMemory) + `build_sync_run_entity()` helper. CLI(`sync_kis_snapshots.py`) 및 Scheduler(`run_snapshot_sync_loop.py`)에 실행 이력 저장 연결. 신규 테스트 3개 클래스(Entity 6 + helper 6 + Repository 2 = 14 tests). 총 38/38 테스트. |
| 2026-05-08 | Snapshot Sync Run Inspection API | [kis_snapshot_sync_inspection_api.md](plans/kis_snapshot_sync_inspection_api.md) | `SnapshotSyncRunRepository.list_runs()/get()` 추가 (Protocol + Postgres + InMemory). `SnapshotSyncRunSummary` Pydantic schema. `GET /snapshot-sync-runs`(목록 + 필터) + `GET /snapshot-sync-runs/{run_id}`(상세) 라우트. app.py Phase 4 등록. 신규 테스트 11개 (목록 6 + 상세 3 + 인증 3). |
| 2026-05-08 | Snapshot Sync Freshness / Health Summary | [kis_snapshot_sync_freshness.md](plans/kis_snapshot_sync_freshness.md) | `SnapshotSyncHealthSummary` dataclass + `get_sync_health_summary()` (Protocol/Postgres/InMemory). `KIS_SNAPSHOT_STALE_THRESHOLD_SECONDS` env config (default 900s). `SnapshotSyncRunHealthSummary` Pydantic schema. `GET /snapshot-sync-runs/summary` 라우트 (단일 엔드포인트, list보다 먼저 등록). 신규 테스트 7개 (empty, fresh, stale, consecutive_failures, auth_required, auth_passes). |
| 2026-05-08 | Snapshot Sync Freshness → Health/Readiness 신호 연결 | [kis_snapshot_sync_readiness.md](plans/kis_snapshot_sync_readiness.md) | HealthResponse에 snapshot sync freshness optional 필드 4개 추가. `/health`에 snapshot sync detail 포함. `/health/readyz`에 stale sync → degraded 정책 구현. 신규 테스트 4개 + 기존 readyz 테스트 degraded 반영. 27/27 통과. |
| 2026-05-08 | Snapshot Sync Startup Grace Period | [kis_snapshot_sync_grace.md](plans/kis_snapshot_sync_grace.md) | `KIS_SNAPSHOT_STARTUP_GRACE_SECONDS` env config (default 600s). `_app.state.started_at` in lifespan. Grace 내 readiness: `ok` + health detail: `starting_up`. Grace 경과 후 기존 degraded 정책 유지. Grace 무관 DB unreachable → `not_ready`. 신규 테스트 5개 + 기존 3개 수정. |
| 2026-05-08 | Broker-Agnostic Operations Runner | [broker_agnostic_operations_runner.md](plans/broker_agnostic_operations_runner.md) | `SnapshotFetchProvider` Protocol + `FetchedSnapshot` dataclass. `sync_account_snapshots()`/`sync_accounts_by_ids()`/`sync_all_accounts()` broker-agnostic runner. `KISSyncSnapshotProvider` (KIS 구현체). `scripts/sync_snapshots.py` 신규 CLI. `run_snapshot_sync_loop.py` broker-aware. `settings.py` env alias additive. `sync_kis_snapshots.py` deprecated wrapper 유지. 신규 테스트 33개 (공통 runner 24 + KIS provider 9). 총 113/113 통과. |
| 2026-05-08 | Broker-Aware Snapshot Client/Provider Factory | [broker_agnostic_operations_runner.md](plans/broker_agnostic_operations_runner.md) | `SnapshotSyncComponents` dataclass + `build_snapshot_sync_components()` factory. `scripts/sync_snapshots.py`에서 `_build_provider()` 제거 → factory 호출. `scripts/run_snapshot_sync_loop.py`에서 KIS 직접 wiring 제거 → factory 호출. `sync_kis_snapshots.py` deprecated wrapper 유지. 신규 테스트 8개. 총 121/121 테스트 통과. |
| 2026-05-08 | AuthenticatableSnapshotClient Protocol | [authenticatable_snapshot_client_protocol.md](plans/authenticatable_snapshot_client_protocol.md) | `SnapshotSyncComponents.client`를 `Any` → `AuthenticatableSnapshotClient` Protocol로 승격. Scheduler(`run_snapshot_sync_loop.py`)에서 `type: ignore[union-attr]` 제거, `\| None` 타입 제거. 신규 테스트 1개. 총 122/122 테스트 통과. |
| 2026-05-09 | **AI Decision → Order Submit 파이프라인 (Gap 1)** | [gap1_ai_decision_to_order_submit.md](plans/gap1_ai_decision_to_order_submit.md) | FDC 결과 → `TradeDecisionEntity` 저장 → `OrderManager` → broker submit 전 경로 연결. `SubmitResult` dataclass, `assemble_and_submit()` 5-phase pipeline, `build_submit_order_request_from_decision()` pure function, runtime wiring (`bootstrap.py` + `run_orchestrator_once.py --submit`). 20/20 신규 테스트 통과. |
| 2026-05-09 | **AI Agent comment/rationale 저장 한국어 강제** | [gap4_korean_text_enforcement.md](plans/gap4_korean_text_enforcement.md) | PostgreSQL 서술형 텍스트 한국어 강제. Dual Defense: Prompt 수준 + Backend 정규화. `korean_normalizer.py` (validate_or_normalize_korean, normalize_structured_output, contains_korean). 3개 Agent prompt 한국어 지시. `recorder.py` `normalize_structured_output()` 적용. `decision_orchestrator.py` `validate_or_normalize_korean()` 적용. 34/34 신규 테스트 통과 (26 unit + 8 integration). |
| 2026-05-09 | **Decision ↔ Order 추적성 강화 (Gap 2)** | [gap2_decision_order_traceability.md](plans/gap2_decision_order_traceability.md) | `decision_context_id` 6개 경로 전파: OrderManager.create_order() → OrderRequestEntity, PostgresOrderRepository.add() SQL INSERT, OrderQuery 필터 2종(trade_decision_id, decision_context_id), OrderSummary/GET /orders trace query params, TradeDecisionRepository.get() PK 조회, SubmitResult.decision_context_id 7개 return site. 20/20 pipeline + 82/82 관련 테스트 통과. |
| 2026-05-09 | **Safe Order Path E2E 검증 (Gap 3)** | [gap3_safe_order_path_e2e.md](plans/gap3_safe_order_path_e2e.md) | Fake broker adapter 기반 E2E 시나리오 7개 검증: happy path(SUBMITTED), uncertain(RECONCILE_REQUIRED+lock), blocking lock 차단(RECONCILE_REQUIRED+broker 0회), lock 재시도(차단+broker 1회), reject(REJECTED), duplicate guard(ERROR), requires_reconciliation(RECONCILE_REQUIRED+lock). 7/7 신규 + 40/40 기존 테스트 통과. |
| 2026-05-09 | **Backend Sizing Math 고도화 (Gap 4)** | [gap4_backend_sizing_math.md](plans/gap4_backend_sizing_math.md) | Position-aware/config-driven deterministic sizing engine 도입. `SizingInputs`(18-field) / `SizingResult`(4-field) dataclass. `calculate_sizing()` 8-step pure function pipeline. Phase 1.5 pipeline step (`_build_sizing_inputs()`+`calculate_sizing()`). 37/37 sizing engine 단위 테스트 + 2/2 pipeline 통합 테스트 + 444/444 기존 테스트 회귀 없음. 총 483/483 테스트 통과. |
| 2026-05-09 | **Paper Trading Loop Validation** | [paper_trading_loop_validation.md](plans/paper_trading_loop_validation.md) | Paper 운영 루프 검증 기반 완성. 사용자 통합테스트 5개 시나리오(`test_paper_trading_scenarios.py`), Replay 결정론적 검증(`test_decision_replay.py`), `run_orchestrator_once.py` 개선(`--dry-run`, `--output json`), `verify_paper_loop.py` 신규(반복 실행 전용), Go/No-Go 기준 문서화. |
| 2026-05-09 | **Fill Sync / Post-Submit Update** | [fill_sync_post_submit_update.md](plans/fill_sync_post_submit_update.md) | `OrderSyncService` 신규 생성. `sync_order_post_submit()` 진입점. chain transition (SUBMITTED→FILLED 3-step). Fill event ingestion + dedup. `BrokerOrderRepository.update()/get()` Protocol + InMemory. `last_synced_at` 초기값 설정. 11개 신규 테스트. 470/470 기존 테스트 회귀 없음. |
| 2026-05-09 | **Scheduler 기반 정기 Post-Submit Sync** | [post_submit_sync_scheduler_loop.md](plans/post_submit_sync_scheduler_loop.md) | `OrderQuery.statuses` 필드 추가 (filters/memory/postgres). `PostSubmitSyncRunner` + `SyncCycleResult` batch runner. `run_post_submit_sync_loop.py` scheduler script. Snapshot refresh callback 연결. 8개 신규 테스트. 19/19 테스트 통과. |
| 2026-05-09 | **WebSocket 기반 실시간 Order Event 수신** | [post_submit_sync_ws_event.md](plans/post_submit_sync_ws_event.md) | `RealTimeEventLoop.__init__()`에 `sync_service`/`account_ref`/`snapshot_refresh_cb` optional param 추가. `_handle_fill_notification()`에 WS-triggered sync (debounce 5s + fire-and-forget) 추가. 기존 10개 + 신규 5개 테스트 통과. polling fallback 유지. |
| 2026-05-09 | **Pipeline Phase 5.5 Post-Submit Sync 연동** | [pipeline_phase55_post_submit_sync.md](plans/pipeline_phase55_post_submit_sync.md) | `assemble_and_submit()` Phase 5.5: SUBMITTED만 호출, timeout 5s, 결과는 SubmitResult와 무관. WS/polling 공존. `_PHASE55_SYNC_TIMEOUT` 상수. `__init__()`에 `sync_service`/`snapshot_refresh_cb` optional param. 신규 테스트 7개 (호출/인자/timeout/exception/REJECTED skip/RECONCILE_REQUIRED skip/backward compat/콜백 전달). 36/36 테스트 통과. |
| 2026-05-09 | **Snapshot refresh 직접 통합** | [backlog_21_snapshot_refresh_integration.md](plans/backlog_21_snapshot_refresh_integration.md) | 세 경로 refresh 조건 통일(FILLED+status_changed+fills_synced>0). WS 직접 refresh 경로(`_filled_refresh_fired` dedup). SyncCycleResult.snapshots_refreshed 집계. runner summary log. 신규 테스트 6개(order_sync 3 + event_loop 3). 40/40 테스트 통과. |
| 2026-05-09 | **Snapshot Staleness Guardrail (Phase 5) — Account-Level Freshness** | [account_level_snapshot_freshness.md](plans/account_level_snapshot_freshness.md) | Run-level → Account-level freshness 정밀화. `AccountSnapshotFreshness` dataclass. `_check_account_snapshot_freshness()` private method. `STALE_SNAPSHOT_ACCOUNT` vs `STALE_SNAPSHOT` rule code 분리. Zero-position account policy. 6개 신규 테스트. |
| 2026-05-09 | **Replay/Backtest Validation 고도화 (Backlog Item 2)** | [replay_backtest_validation.md](plans/replay_backtest_validation.md) | `ReplayBundle` dataclass + `_build_repos()` factory + `_make_stub_fdc()` factory. 5개 parametrize 시나리오 (happy_buy/reduce/exit/stale_guard/cash_constraint). 2-run identity 검증. `replay_test_harness.py` 공유 모듈. `replay_verification.py` 운영 검증 스크립트. 19/19 replay 테스트 + 검증 스크립트 5/5 통과. |
| 2026-05-09 | **Paper Continuous Decision Loop (Backlog Item 1)** | [paper_continuous_decision_loop.md](plans/paper_continuous_decision_loop.md) | `scripts/run_paper_decision_loop.py` 신규 생성. 300s 간격, `--count`, `--dry-run`, `--submit`, `--interval`, `--output json` CLI. `_seed_if_empty` + seed constants 재사용. `get_sync_health_summary()` pre-check. cycle/aggregate summary. asyncio.Event graceful shutdown. `postgres_runtime` per-cycle. 17/17 단위 테스트 통과. `verify_paper_loop.py`와 역할 분리 (검증 vs 운영). |
| 2026-05-09 | **Event Ingestion Loop (외부 이벤트 수집 운영 데몬)** | [paper_trading_loop_validation.md](plans/paper_trading_loop_validation.md) | `scripts/run_event_ingestion_loop.py` 신규 생성. `_build_polling_workers()` 재사용. 60s 간격. source isolation. cycle/aggregate summary. graceful shutdown. ~14개 단위 테스트. |
| 2026-05-09 | **Paper PnL / Performance Summary** | [paper_performance_summary.md](plans/paper_performance_summary.md) | `PerformanceSummaryService` + `calc_realized_pnl_for_order()`/`calc_unrealized_pnl_from_positions()`/`calc_position_market_value()` pure functions. `AccountPerformanceSummary`(12 fields)/`StrategyPerformanceSummary`(7 fields) dataclasses. `GET /performance-summary` API. 18개 신규 테스트. 563/563 기존 테스트 회귀 없음. |
| 2026-05-09 | **Paper PnL History / Trend** | [paper_performance_history.md](plans/paper_performance_history.md) | `DailyPerformancePoint`(7 fields) + `_calc_per_fill_pnl()`/`_latest_cash_on_or_before()`/`_latest_positions_on_or_before()` pure helpers + `get_daily_history()` service method. `GET /performance-history` API. `CashBalanceSnapshotRepository.list_by_account()` contract/memory/postgres. 15개 신규 테스트(Pure helper 3 + snapshot selection 7 + service integration 5). 33/33 테스트 통과. |
| 2026-05-09 | **Paper Performance Metrics** | [paper_performance_metrics.md](plans/paper_performance_metrics.md) | `PerformanceMetrics` dataclass(17 fields) + `_calc_equity_metrics()`/`_calc_win_loss_metrics()` pure helpers. Cumulative return/drawdown/win-rate/avg-win-avg-loss/profit-factor. Per-order 기준 win/loss 정책. `get_performance_metrics()` service method. `GET /performance-metrics` API. 10개 신규 테스트 (6 pure + 4 통합). 44/44 + 86/86 테스트 통과. |
