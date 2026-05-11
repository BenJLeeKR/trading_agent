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

## 14-Agent 설계 vs 현재 구현/Backlog 정리

이 섹션은 `plan_docs/agents/`의 14-agent 책임 분해와 실제 구현/Backlog 분해 단위를 맞춰 보기 위한 보정표다.

- **중요**: 14개 `Agent`는 모두 provider LLM agent 구현 대상이 아니다.
- 현재 v1에서 **실제 런타임 AI core**로 연결된 것은 `Event Interpretation`, `AI Risk`, `Final Decision Composer` 3개다.
- 나머지 상당수는 설계상 `deterministic service/engine/worker` 또는 `hybrid`가 목표 형태이며, 일부는 이미 기능 축 기준으로 부분 구현돼 있다.
- 따라서 아래 표의 목적은 “왜 14개가 BACKLOG에 agent 이름 그대로 안 보이는가”를 설명하고, 아직 **별도 backlog 작업으로 재분해되지 않은 축**을 표시하는 것이다.

| Agent 책임 | 목표 형태 | 현재 상태 | 현재 구현/Backlog 앵커 | Backlog 분해 상태 |
|---|---|---|---|---|
| Data Collector Agent | Deterministic worker + adapter | 부분 구현 | KIS REST/WS, polling worker, source adapter, snapshot/event sync loop | 기존 backlog/plan에 기능 축으로 반영됨 |
| Data Quality Agent | Deterministic validator/service | 부분 구현 | freshness guard, stale snapshot guard, sync health, dedup, gap handling | 기존 backlog/plan에 기능 축으로 반영됨 |
| Market Regime Agent | Hybrid | 미구현 | 설계 문서상 개념만 존재 | **별도 backlog 재분해 필요** |
| Universe Selection Agent | Deterministic ranking/filter + optional AI | 미구현 | 설계 문서상 개념만 존재 | **별도 backlog 재분해 필요** |
| Strategy Selection Agent | Hybrid policy service | 미구현 | 설계 문서상 개념만 존재 | **별도 backlog 재분해 필요** |
| Signal Agent | Deterministic scoring engine | 미구현 | 설계 문서상 개념만 존재 | **별도 backlog 재분해 필요** |
| News/RAG Agent | Provider AI + retrieval/event pipeline hybrid | 부분 구현 | `EventInterpretationAgent`, OpenDART adapter, external event pipeline | 일부 반영됨, 전용 backlog로는 미분해 |
| Portfolio Agent | Deterministic portfolio construction | 미구현 | 설계 문서상 개념만 존재 | **별도 backlog 재분해 필요** |
| Order Construction Agent | Deterministic order-construction service | 미구현 | 현재는 FDC + sizing/order translation에 임시 흡수 | **별도 backlog 재분해 필요** |
| AI Risk Manager Agent | Provider AI + deterministic hard-limit 후단 | 구현 완료 | `services/ai_agents/ai_risk.py`, `decision_orchestrator.py` | 구현됨 |
| AI Compliance Agent | Hybrid policy/compliance + hard validator | 미구현 | 설계 문서상 개념만 존재 | **별도 backlog 재분해 필요** |
| Execution Agent | Deterministic execution pipeline | 부분 구현 | `order_manager.py`, broker adapter, reconciliation, post-submit sync | 기존 backlog/plan에 기능 축으로 반영됨 |
| Performance Agent | Deterministic analytics + optional AI commentary | 부분 구현 | performance summary/history/metrics/benchmark/gate/exit/live-readiness | 기능 축으로는 상당 부분 구현, “agent” 단위 backlog는 미분해 |
| Model Monitor Agent | Deterministic monitoring + offline analysis | 미구현 | provider failover/quality hardening 일부만 인접 구현 | **별도 backlog 재분해 필요** |

### 현재 해석 규칙

1. **EI / AR / FDC는 v1 실전 코어**다. 나머지 agent 역할 일부는 아직 FDC나 deterministic backend에 임시 흡수돼 있다.
2. **Execution Agent는 AI agent가 아니다.** 주문 제출, 체결 추적, 정합성 수렴은 `OrderManager + BrokerAdapter + ReconciliationService` 중심 deterministic path로 유지한다.
3. **Backlog 누락처럼 보이는 이유는 작업 분해 단위 차이**다. 현재 BACKLOG는 agent 이름보다 `snapshot sync`, `paper gate`, `event ingestion`, `performance`, `submit/sync/reconcile` 같은 기능 축으로 정리돼 있다.
4. 아래 7개 축은 추후 별도 backlog 항목으로 재분해 후보로 본다.
   - Market Regime Agent
   - Universe Selection Agent
   - Strategy Selection Agent
   - Signal Agent
   - Portfolio Agent
   - AI Compliance Agent
   - Model Monitor Agent

---

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Paper Trading Loop 연속 실행**: 주기적 orchestrator loop + fill sync + position/cash refresh. `run_paper_decision_loop.py` (300s 간격, CLI 옵션 6종, graceful shutdown). `verify_paper_loop.py --interval`은 assemble/submit만 반복; fill polling, position/cash 자동 갱신은 미포함 | Paper Trading Loop Validation | ✅ 승격됨 |
| 1b | **Event Ingestion Loop**: 외부 이벤트 수집을 독립 운영 데몬으로 승격. `scripts/run_event_ingestion_loop.py` + `_build_polling_workers()` 재사용. Source isolation + cycle summary. 60s 간격. ~14 tests | [paper_trading_loop_validation.md](plans/paper_trading_loop_validation.md) | ✅ 승격됨 |
| 2 | **Replay-Style 검증 엔진 고도화**: 저장된 decision context 기반 결정론적 재현 검증 엔진. core replay engine (ReplayBundle + _build_repos + 5 scenarios + 2-run identity) 구현 완료. 전체 DB 기반 replay 경로는 후속 과제로 잔류 | Paper Trading Loop Validation | ✅ 승격됨 |
| 3 | **Snapshot Staleness Guardrail (Phase 5)**: submit 단계에서 position/cash snapshot freshness 검사. stale snapshot 시 RECONCILE_REQUIRED + status_reason_code="STALE_SNAPSHOT". `test_scenario_4_stale_snapshot_guard` 참조 | Paper Trading Loop Validation | ✅ 승격됨 |
| 4 | **Fill Sync / Post-Submit Update**: 주문 제출 후 broker로부터 fill 상태를 주기적으로 polling하는 루틴. `reconciliation_service.resolve_unknown_state()` 자동화 | Paper Trading Loop Validation | ✅ 승격됨 |
| 5 | **Plan 40 Phase 2 — API endpoints 확장**: `GET /orders/{id}/broker-orders`, `GET /accounts`, `GET /accounts/{id}`, `GET /clients/{id}`, `GET /instruments/{id}`, `GET /positions`, `GET /cash-balances`, `GET /guardrail-evaluations`, `GET /risk-limit-snapshots`, `GET /agent-runs` | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ✅ 승격됨 |
| 6 | **Plan 40 Phase 2 — Postgres-backed API mode**: `create_app()`에 Postgres repository 주입 지원, `runtime_mode="postgres"` 모드 | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ✅ 승격됨 |
| 7 | **Reconciliation blocking lock list API**: `GET /reconciliation/locks` 구현을 위해 reconciliation repository에 `list_locks()` 메서드 추가. 현재 `is_blocked()`만 존재 | [Plan 40](plans/40_fastapi_inspection_api.md) | ✅ 승격됨 |
| 8 | **KIS real credential + combined submit smoke**: KIS 실제 API key 확보 후 `tests/smoke/test_kis_paper_smoke.py` 등 combined submit smoke 실행 | [Plan 36](plans/36_kis_paper_ai_runtime_smoke.md) | ❌ 미착수 |
| 9 | **Docs/OpenAPI 보호 옵션 (inspection API)**: `/docs`와 `/openapi.json`을 auth 보호 대상에 포함. 현재는 공개 유지 중 | Plan 47 | ❌ 미착수 |
| 10 | **Admin UI P1 — DecisionsView detail panel**: 특정 decision 행 클릭 시 TradeDecisionDetail 또는 DecisionContextDetail 내용을 inline panel 또는 modal로 표시. 현재는 단순 리스트만 존재 | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | ❌ 미착수 |
| 11 | **Admin UI P1 — AccountsView filter/selection 개선**: 계좌 목록 필터 (type, strategy) 및 선택 시 상세 영역 시각적 개선 | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | ❌ 미착수 |
| 12 | **Admin UI — Dashboard reconciliation metrics**: Dashboard에 정합성 점검 메트릭 (불일치 수, 마지막 실행 시각) 추가. 현재는 locks만 표시 | Plan 53 | ❌ 미착수 |
| 13 | **Admin UI — Dashboard/Accounts/Broker Capacity freshness visualization**: 데이터 신선도(freshness) 시각화. 각 데이터 소스별 마지막 업데이트 시각 표시 및 지연 경고 | Plan 53 | ❌ 미착수 |
| 14 | **Position/Cash Refresh After Fill**: Fill 발생 후 position snapshot/cash balance snapshot 자동 갱신 경로. Snapshot sync loop와 decision pipeline 연결 | Paper Trading Loop Validation | ❌ 미착수 |
| 15 | **Paper PnL / Performance Summary**: 체결/포지션/현금 데이터 기반 성과 집계. `AccountPerformanceSummary` + `StrategyPerformanceSummary`. Realized/Unrealized/Total PnL. `GET /performance-summary` API. 18개 신규 테스트 | Paper Trading Loop Validation | ✅ 승격됨 |
| 16 | **Postgres BrokerOrderRepository.update() 구현**: 현재 InMemory 전용 `update()`를 Postgres에도 구현. `PostgresBrokerOrderRepository.update()`에 SQL UPDATE + `last_synced_at` 반영 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 17 | **Scheduler 기반 정기 Post-Submit Sync**: `OrderSyncService`를 주기적으로 실행하는 scheduler loop. 미체결/부분체결 주기적 polling으로 상태 최신성 유지 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 18 | **FillEvent에 broker_fill_id 필드 추가**: 현재 fill dedup이 `(timestamp, price, quantity)` tuple 기반. broker 고유 fill ID로 dedup 강화 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 19 | **WebSocket 기반 실시간 order event 수신**: polling → WS event 기반 post-submit update 전환. KIS WS order event channel 연동 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 20 | **Pipeline Phase 5.5 Post-Submit Sync 연동**: `assemble_and_submit()`에서 submit 직후 첫 1회 `OrderSyncService.sync_order_post_submit()` 호출. 실패 무시, timeout 5s | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 21 | **Snapshot refresh 직접 통합**: `OrderSyncService`가 FILLED terminal 감지 시 snapshot refresh callback 직접 호출. 현재는 optional callback으로 위임 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 22 | **Paper PnL History / Trend**: 기간 필터 기반 일별 성과 시계열 조회. `DailyPerformancePoint` dataclass + `get_daily_history()` service method. `GET /performance-history` API. Per-fill PnL 계산. Snapshot 날짜 선택 로직. 15개 신규 테스트 | Paper Performance Summary | ✅ 승격됨 |
| 23 | **Paper Performance Metrics**: 기간 기반 성과 지표 추가. `PerformanceMetrics` dataclass(17 fields) + `_calc_equity_metrics()`/`_calc_win_loss_metrics()` pure helpers. Cumulative return/drawdown/win-rate/avg-win-avg-loss/profit-factor. `get_performance_metrics()` service method. `GET /performance-metrics` API. Per-order 기준 win/loss 정책. 10개 신규 테스트 | Paper Performance Summary | ✅ 승격됨 |
| 24 | **Paper Go/No-Go Gate**: 성과/안정성/운영 지표 기반 paper 운용 통과 여부 자동 판정. `PaperGateService` (8개 check) + `GET /paper-go-no-go` API. `PAPER_GATE_*` env 6개 threshold. `GateStatus`(PASS/WARN/FAIL) + `OverallStatus`(GO/HOLD/NO_GO). 7개 신규 테스트. | Paper Go/No-Go Gate | ✅ 승격됨 |
| 25 | **Paper Exit Criteria (3-Layer)**: Paper → Live Canary 전환 전 최종 합격 기준. Layer A (Auto, PaperGateService 8 checks + health/readyz 2 checks), Layer B (Semi-Auto, 5 checks), Layer C (Manual, 5 체크리스트). 최종 종합: A FAIL→FAIL(exit 2), A+B FAIL→HOLD(exit 1), A/B+C pending→HOLD(exit 1), all complete→PASS(exit 0). NOT_RUN/HOLD/FAIL/PASS 구분. [`scripts/evaluate_paper_exit.py`](scripts/evaluate_paper_exit.py) CLI 4개 출력 모드(text/json/manual-template). 8개 신규 테스트. | [paper_exit_criteria.md](plans/paper_exit_criteria.md) | ✅ 승격됨 |
| 26 | **Live Gate / Canary Readiness (Phase 3)**: Paper Exit 통과 후 Live 검토 자격 + 추가 보호 조건. `LiveGateEvaluator` (PaperExitEvaluator 재사용). Live-specific 8개 auto check (filled orders 10↑/drawdown 10%↓/excess return 0%p↑/win rate/reconcile failures/blocking locks/readyz/post-submit sync). 6개 manual checklist (credential/account masking/operator approval/paper log review/rate limit review/final decision). 5개 신규 env thresholds. Overall: BLOCKED/HOLD/READY. [`scripts/evaluate_live_gate.py`](scripts/evaluate_live_gate.py) CLI 4개 출력 모드(text/json/manual-template) + exit code 0/1/2. 10개 신규 테스트. | [live_gate_canary_readiness.md](plans/live_gate_canary_readiness.md) | ✅ 승격됨 |
| 27 | **Market Regime Agent 분해**: deterministic regime feature set + rule-based classifier + optional AI commentary. 우선 구현 범위는 변동성/추세/risk-on-off 3축 feature 정리, regime label contract 정의, decision pipeline 입력 연결, replay 가능한 pure helper 우선. 초기 목표는 provider agent 추가보다 deterministic backbone 구축. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md) | ❌ 미착수 |
| 28 | **Universe Selection Agent 분해**: 거래 가능 종목 풀 생성과 ranking/filter service. 유동성/슬리피지/시장/브로커 제약/이벤트 존재 여부를 기준으로 candidate universe를 만들고, paper/live 공통 contract로 orchestrator 입력에 주입. 초기 목표는 deterministic filter + ranking engine, optional AI commentary는 후순위. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md) | ❌ 미착수 |
| 29 | **Strategy Selection Agent 분해**: 현재 국면과 계좌 상태를 기준으로 허용 전략/실행 스타일을 고르는 hybrid policy service. 전략 registry, enable/disable gate, regime-aware selection contract, paper 성과 기반 감쇠/중지 기준을 포함. 현재 FDC에 임시 흡수된 “어떤 스타일로 진입할지” 책임을 별도 계층으로 분리. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md), [ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md) | ❌ 미착수 |
| 30 | **Signal Agent 분해**: 기술/수급/모멘텀/변동성 점수화 deterministic engine. feature registry + score aggregation + replay/backtest 친화적 pure helper 우선. Event/news 파생 factor는 News/RAG 입력과 결합하되, 최종 score는 수치 재현 가능한 backend가 authoritative source가 되도록 유지. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md), [08_ai_decision_policy.md](../plan_docs/detailed_design/08_ai_decision_policy.md) | ❌ 미착수 |
| 31 | **Portfolio Agent 분해**: 목표 비중, concentration budget, exposure budget, 계좌별 capital allocation을 담당하는 deterministic portfolio construction service. 현재 sizing/risk/decision 사이에 흩어진 배분 책임을 하나의 정책 계층으로 모으고, strategy-level target allocation과 account-level order budget을 분리한다. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md) | ❌ 미착수 |
| 32 | **AI Compliance Agent 분해**: 정책 위반 가능성 해석(AI)과 hard validator(deterministic)를 분리한 hybrid compliance layer. 금지 종목/권한 불일치/필수 필드 누락/브로커 제약 위반은 deterministic 차단, ambiguous policy/event risk만 AI가 의견을 제공. paper/live 공통 pre-submit verification chain에 read-only 또는 blocking gate로 연결. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md), [08_ai_decision_policy.md](../plan_docs/detailed_design/08_ai_decision_policy.md) | ❌ 미착수 |
| 33 | **Model Monitor Agent 분해**: provider drift, prompt drift, fallback rate, replay/live divergence, backtest-production 괴리 모니터링 service. 우선 구현 범위는 AI agent별 success/fallback/timeout/reason_code 집계, contract drift 알림, replay vs runtime 비교 보고서, model/provider별 품질 회귀 지표 수집. provider failover hardening과 연결되지만 별도 monitoring 관점의 backlog로 관리. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md), [ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md) | ❌ 미착수 |

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
| 2026-05-09 | **Paper Benchmark Comparison** | [paper_benchmark_comparison.md](plans/paper_benchmark_comparison.md) | `BenchmarkComparison` dataclass(13 fields) + `BenchmarkPriceRepository` Protocol + `InMemoryBenchmarkPriceRepository` + `_calc_benchmark_metrics()` pure function. Portfolio metrics reused from `PerformanceSummaryService`. `GET /performance-benchmark` API (4 required + 1 optional query params). 10개 신규 테스트 (5 pure + 5 통합). 54/54 + 96/96 회귀 없음. |
| 2026-05-09 | **Paper Go/No-Go Gate** | [paper_go_no_go_gate.md](plans/paper_go_no_go_gate.md) | 성과/안정성/운영 3축 자동 판정 Gate. `PAPER_GATE_*` env 6개 threshold. `PaperGateService.evaluate()` 8개 check (return/drawdown/excess_return/win_rate/filled_orders/snapshot_freshness/sync_failures/blocking_locks). `GET /performance/paper-go-no-go` API. 7개 신규 테스트 (GO/HOLD/NO_GO 각각 + benchmark 분기). 전체 회귀 없음. |
| 2026-05-09 | **테스트 스위트 정상화 — pre-existing 2 failed / 14 errors 제거** | [fix_pre_existing_test_failures.md](plans/fix_pre_existing_test_failures.md) | `runtime/bootstrap.py`에 `ensure_schema` import 누락 수정. `test_settings.py`에 `KIS_WS_URL` env cleanup 누락 수정. `tests/services/` 589/589 all green 달성. |
| 2026-05-09 | **Paper Exit Criteria — 3층 평가 체계** | [paper_exit_criteria.md](plans/paper_exit_criteria.md) | Layer A: PaperGateService 재사용(8개 check) + health/readyz. Layer B: pytest/script subprocess(B1-B3), snapshot sync health(B4). Layer C: 18개 manual checklist. 평가 CLI 4개 output mode(text/JSON/manual-template). 8개 테스트 시나리오(PASS/HOLD/FAIL). |
| 2026-05-09 | **Paper/Live Mode Boundary 정리 — 동일 시스템 + 설정 스위치 구조** | [mode_boundary_paper_live.md](plans/mode_boundary_paper_live.md) | 4분류 inventory(공통/env-specific/paper-only/paper-named-but-common). mode switch checklist 9항목. 설계 문서 mode-agnostic 표기 정리. **대규모 rename/refactor 없이 최소 변경으로 high-signal 정리.** |
| 2026-05-09 | **Live Gate / Canary Readiness (Phase 3)** | [live_gate_canary_readiness.md](plans/live_gate_canary_readiness.md) | Paper Exit 재사용 + live-specific 8개 auto check + 6개 manual checklist. `LiveGateEvaluator`(PaperExitEvaluator wrapping). 5개 신규 env thresholds. `_determine_overall()` 5 static rules. CLI 4개 출력 모드 + exit code. 10개 테스트(unit 6 + integration 4). 설계 문서 + settings.py + evaluate_live_gate.py + test_evaluate_live_gate.py. |
| 2026-05-09 | **Phase 2 Inspection API Expansion (Backlog #5, #6, #7)** | [phase2_inspection_api_expansion.md](plans/phase2_inspection_api_expansion.md) | `GET /agent-runs/{id}` detail endpoint. `GET /guardrail-evaluations` (list + detail + 3 filter params). `GET /risk-limit-snapshots` (list + /latest). `GuardrailEvaluationRepository.get()/list_by_account()` protocol + InMemory + Postgres. `AgentRunRepository.get()` protocol + InMemory + Postgres. `GuardrailEvaluationView`/`RiskLimitSnapshotView` Pydantic schemas. 신규 테스트 16개 (in-memory 9 + Postgres smoke 5 + 기존 수정 2). 총 53/53 테스트 통과. |
| 2026-05-09 | **Postgres BrokerOrderRepository.update() (Backlog #16)** | [postgres_broker_order_update.md](plans/postgres_broker_order_update.md) | `PostgresBrokerOrderRepository.get()` + `update()` 구현. 동적 SET clause SQL UPDATE. `updated_at` 항상 갱신. `ValueError` on not found (InMemory 일관성). `OrderSyncService` 3개 호출 지점 Postgres 경로 안전. 5개 신규 Postgres 테스트 추가. |
| 2026-05-10 | **FillEvent broker_fill_id + fill dedup 강화 (Backlog #18)** | [broker_fill_id_dedup.md](plans/broker_fill_id_dedup.md) | `FillEvent.domain`에 `broker_fill_id` 추가. `FillEventRepository.get_by_broker_fill_id()` Protocol/InMemory/Postgres 구현. `OrderSyncService._sync_fills()` two-tier dedup(broker_fill_id 우선 → 4-field composite fallback). KIS REST CCLD_NUM 매핑 + 기존 생성자 버그 수정. 8개 신규 테스트 전부 통과. |
| 2026-05-10 | **Benchmark Daily Relative Trend** | [benchmark_relative_trend.md](plans/benchmark_relative_trend.md) | `GET /performance-benchmark-history` 신규 엔드포인트. `RelativeBenchmarkPoint`(9 fields) + `_calc_relative_benchmark_points()` pure function + `get_benchmark_daily_history()` service method. 14개 pure + 5개 integration 테스트(29/29 통과). 설계 문서 6개 보정사항 반영(필드 고정/streak 규칙/기준선 선택/보간 금지/drawdown 부호/API 정책). 기존 API 회귀 없음(53/53 inspection API 테스트 통과). |
| 2026-05-10 | **Performance Metrics 심화 — Sharpe / Sortino / Calmar** | [paper_performance_risk_adjusted_metrics.md](plans/paper_performance_risk_adjusted_metrics.md) | `PerformanceMetrics` dataclass + `PerformanceMetricsView` schema에 3개 field 추가(sharpe_ratio/sortino_ratio/calmar_ratio). `_calc_sharpe_sortino()` pure helper. `get_performance_metrics()` step 5 통합. 비연율화(raw daily) 고정, rf=0. Sortino 음수 수익률 m>=2 조건. Calmar max_drawdown=0 → None. 12개 신규 테스트(pure 6 + service 3 + API 3). 53/53 performance + 56/56 inspection API 통과. |
