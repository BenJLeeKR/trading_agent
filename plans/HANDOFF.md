# 인수인계 — Agent Trading System 현재 상태 요약

> **작성일**: 2026-05-11  
> **직전 완료 Task**: "paper submit smoke 후속 정리 — smoke 전용 가격 원복/파라미터화 + KIS submit 회귀 테스트 추가"  
> **직전 Task 결과**: [`plans/paper_submit_smoke_cleanup.md`](plans/paper_submit_smoke_cleanup.md) 설계 + 구현 완료, 테스트 9/9 PASS

---

## 1. 현재까지 구현/정리된 상태 요약

### 1.1 인프라 / 저장소 / 핵심 서비스

| 항목 | 상태 | 설명 |
|------|------|------|
| PostgreSQL 저장소 | ✅ **완료** | 모든 Entity에 대한 PostgresRepository 구현 완료 (accounts, broker_accounts, orders, broker_orders, fill_events, trade_decisions, decision_contexts, guardrail_evaluations, risk_limit_snapshots, agent_runs, audit_logs, snapshot_sync_runs 등) |
| DB 마이그레이션 | ✅ **완료** | `db/migrations/0001` ~ `0011`까지 순차 적용. Migration runner(`run.py`) 구현 완료 |
| In-memory 저장소 | ✅ **완료** | 테스트용 InMemoryRepository 전 entity 구현 |
| RepositoryContainer + UnitOfWork | ✅ **완료** | `RepositoryContainer` dataclass + `transaction()` context manager |
| Runtime Bootstrap | ✅ **완료** | `build_default_runtime()`(in-memory) + `postgres_runtime()`(async context manager) |
| Config/AppSettings | ✅ **완료** | `AppSettings` dataclass (18 env config fields). Paper/Live mode switch 내장 |
| API 서버 (FastAPI) | ✅ **완료** | Inspection API 20+ endpoints. Auth(RBAC)/health/readyz 포함 |
| Admin UI | ✅ **완료** | Vite+React+TypeScript SPA. Phase 1 read-only. 69+ tests. 전면 한글화 완료 |

### 1.2 브로커 / 실행 경로

| 항목 | 상태 | 설명 |
|------|------|------|
| KISRestClient | ✅ **완료** | REST API client with HTTP transport. `submit_order()`/`cancel_order()`/`get_order_status()`/`get_fills()`/`get_positions()`/`get_cash_balance()`/`get_quote()`/`get_orderbook()`/`resolve_unknown_state()` |
| KISWebSocketClient | ✅ **완료** | WebSocket client with auto-reconnect. `ws_parser()` 포함 |
| KoreaInvestmentAdapter | ✅ **완료** | BrokerAdapter 구현. `submit_order()` pre-validation + `_normalize_submit_result()` 정규화 |
| Rate Limit Budget | ✅ **완료** | 5-bucket (AUTH/ORDER/INQUIRY/MARKET_DATA/RECONCILIATION) + circuit breaker + backoff |
| BrokerError | ✅ **완료** | `BrokerError`(ORDER_REJECTED/API_ERROR) + `AmbiguousOrderStateError` |
| Dedup | ✅ **완료** | 브로커 레벨 요청 중복 방지 (`_DedupKey` + `_dedup_cache`) |
| Snapshot Sync | ✅ **완료** | `KISSyncSnapshotProvider` + broker-agnostic `sync_account_snapshots()` runner. CLI 6종 옵션. 실행 이력 저장 + freshness/health/readiness 연동 |
| OpenDart Adapter | ✅ **완료** | 외부 이벤트 수집용 OpenDart adapter |
| **KIS submit 성공 응답 회귀 테스트** | ✅ **금회 완료** | `test_rest_client_submit.py` (9 tests): 성공/실패/body 구조/price resolve |
| **Smoke 전용 가격 env override** | ✅ **금회 완료** | `run_orchestrator_once.py:_resolve_smoke_price()` — `KIS_SMOKE_PRICE` env → fallback 50000 |

### 1.3 External Event / Polling

| 항목 | 상태 | 설명 |
|------|------|------|
| PollingWorker | ✅ **완료** | Generic polling worker base |
| SourceAdapter | ✅ **완료** | 외부 데이터 소스 adapter protocol |
| Event Ingestion Loop | ✅ **완료** | `scripts/run_event_ingestion_loop.py` — 60s 간격, source isolation, graceful shutdown |
| ExternalEventRepository | ✅ **완료** | Protocol + Postgres + InMemory |

### 1.4 AI Decision Layer

| 항목 | 상태 | 설명 |
|------|------|------|
| DecisionOrchestratorService | ✅ **완료** | `assemble()`(Phase 1-1.5) + `assemble_and_submit()`(Phase 1-6 전체 파이프라인) |
| SizingEngine | ✅ **완료** | `calculate_sizing()` 8-step pure function pipeline. Position-aware/config-driven |
| OrderManager | ✅ **완료** | `create_order()` + `submit_order_to_broker()` + reconciliation lock |
| OrderSyncService | ✅ **완료** | Post-submit fill sync. Chain transition(SUBMITTED→FILLED). Fill dedup(broker_fill_id 우선) |
| ReconciliationService | ✅ **완료** | `resolve_unknown_state()` + authoritative state reflection + blocking lock |
| PaperGateService | ✅ **완료** | 8개 check + GO/HOLD/NO_GO 판정 |
| PaperExitEvaluator | ✅ **완료** | 3-Layer (Auto/Semi-Auto/Manual). CLI 4개 output mode |
| LiveGateEvaluator | ✅ **완료** | PaperExit 재사용 + live-specific 8개 auto check + 6개 manual checklist |
| PerformanceSummaryService | ✅ **완료** | Realized/Unrealized/Total PnL. Account/Strategy level |
| BenchmarkComparisonService | ✅ **완료** | Benchmark daily relative trend + risk-adjusted metrics(Sharpe/Sortino/Calmar) |
| PostSubmitSyncRunner | ✅ **완료** | `run_post_submit_sync_loop.py` scheduler. Batch sync cycle. Snapshot refresh callback |
| RealTimeEventLoop WS-triggered sync | ✅ **완료** | WS fill notification → debounce 5s → fire-and-forget sync. Phase 5.5 pipeline 연동 |

### 1.5 Provider 연결

| 항목 | 상태 | 설명 |
|------|------|------|
| LLM Provider 설정 | ✅ **완료** | `LLM_PROVIDER` env로 DeepSeek/OpenAI 전환. API key/base_url/model_id/timeout 전부 env 기반 |
| Provider Client | ✅ **완료** | OpenAI-compatible HTTP client |
| Token Cache | ✅ **완료** | KIS dev token file cache (paper/dev only) |

### 1.6 AI Agent 실제 구현 상태

| 항목 | 상태 | 설명 |
|------|------|------|
| EventInterpretationAgent | ✅ **완료** | v1 agent. 시장 이벤트 해석. Structured output |
| AIRiskAgent | ✅ **완료** | v1 agent. 리스크 평가. Ordered risk level |
| FinalDecisionComposer | ✅ **완료** | v1 agent. 최종 결정(APPROVE/HOLD). DecisionType 매핑 |
| Korean Normalizer | ✅ **완료** | Agent 출력 한국어 강제. prompt + backend 이중 방어 |
| Agent Run 기록 | ✅ **완료** | Agent 실행 내역 DB 저장(`agent_runs` table) |

### 1.7 Smoke / Test 상태

| 항목 | 상태 | 카운트 | 설명 |
|------|------|--------|------|
| 전체 테스트 | ✅ **ALL PASS** | ~850+ | 최근 확인 시 services 671 + broker 167 = 838+ ALL PASS |
| KIS Paper Read-Only Smoke | ✅ **구현 완료** | 8 tests | Auth/Approval Key/Market Data/Account/WebSocket. `tests/smoke/test_kis_paper_smoke.py` |
| KIS Paper AI Runtime Smoke | ✅ **구현 완료** | ~20 tests | Scenario A/B/C1/C2. `tests/smoke/test_kis_paper_ai_runtime_smoke.py` |
| KIS Submit 회귀 테스트 | ✅ **금회 추가** | 9 tests (신규) | 성공/실패/body 구조/price resolve. `tests/brokers/koreainvestment/test_rest_client_submit.py` |
| DeepSeek Provider Smoke | ✅ **구현 완료** | Smoke | `tests/smoke/test_deepseek_provider.py` |
| Broker 테스트 | ✅ **ALL PASS** | 167 tests | Rate limit, auth, websocket, adapter validation, snapshot, dedup, budget exhaustion 등 |
| Service 테스트 | ✅ **ALL PASS** | 671 tests | Decision pipeline, order submit, order sync, sizing, reconciliation, performance, paper gate, exit criteria, live gate, snapshot sync 등 |
| AI Agent 테스트 | ✅ **ALL PASS** | ~50 tests | Agent base, bootstrap, korean enforcement, orchestrator agents, provider client, settings |
| API 테스트 | ✅ **ALL PASS** | ~60 tests | Health, auth, inspection, performance, agent runs 등 |
| Admin UI 테스트 | ✅ **ALL PASS** | 80 tests | Vitest + RTL component tests |
| Integration/E2E 테스트 | ✅ **ALL PASS** | ~15 tests | Long path E2E, orchestrator entrypoint |

---

## 2. 미구현 리스트 및 다음 구현 대상 후보

### 2.1 Paper Submit Smoke — 후속 검증 (P0, 금회 작업 직후)

| # | 항목 | 설명 | 비고 |
|---|------|------|------|
| 1 | **Paper submit smoke 재실행** | `KIS_SMOKE_PRICE=268500` 설정 후 `run_orchestrator_once.py --submit` 실행. ODNO 정상 수신 확인 | 금회 price 정리 완료. 실행은 env 설정만 하면 됨 |
| 2 | **Post-submit sync 검증** | Submit 성공 후 OrderSyncService가 fill/sync 정상 동작하는지 검증 | smoke 시나리오 C4에 해당 |

### 2.2 결정되지 않은 아키텍처 결정 (P1)

| # | 항목 | 설명 | 관련 문서 |
|---|------|------|-----------|
| 3 | **동적 가격 산정 (C안)** | `KIS_SMOKE_PRICE` 대신 KIS 현재가/전일종가를 조회해 price 자동 산정. B안(env override)보다 정교하지만 scope가 큼 | [`plans/paper_submit_smoke_cleanup.md`](plans/paper_submit_smoke_cleanup.md):37 |
| 4 | **Paper → Live 전환 결정** | Paper Exit 통과 여부 확인 후 Live Gate 평가 → Live mode 실제 전환. 전환 시 checklist 9항목 필요 | [`plans/mode_boundary_paper_live.md`](plans/mode_boundary_paper_live.md):135 |
| 5 | **Live credential 확보 + combined submit smoke** | KIS 실제 API key 확보 후 `test_kis_paper_smoke.py` + submit smoke를 live 대상으로 combined 실행 | [`plans/BACKLOG.md`](plans/BACKLOG.md):28 |

### 2.3 Backlog — 다음 마일스톤 후보 (P2)

| # | 항목 | 설명 | BACKLOG # |
|---|------|------|-----------|
| 6 | **Admin UI P1 — DecisionsView detail panel** | Decision 행 클릭 시 TradeDecisionDetail 또는 DecisionContextDetail inline/modal 표시 | BACKLOG #10 |
| 7 | **Admin UI P1 — AccountsView filter/selection 개선** | 계좌 목록 필터 + 선택 시 상세 영역 시각적 개선 | BACKLOG #11 |
| 8 | **Admin UI — Dashboard reconciliation metrics** | 정합성 점검 메트릭 (불일치 수, 마지막 실행 시각) 추가 | BACKLOG #12 |
| 9 | **Admin UI — Freshness visualization** | 데이터 신선도 시각화 + 지연 경고 | BACKLOG #13 |
| 10 | **Position/Cash Refresh After Fill** | Fill 발생 후 position/cash snapshot 자동 갱신 | BACKLOG #14 |
| 11 | **Migration 0010: Drop legacy `decision` column** | `trade_decisions.decision` 컬럼 제거 | BACKLOG #4 (Medium-term) |
| 12 | **E2E test with TradeDecisionEntity creation** | 실제 TradeDecisionEntity 생성 및 trade_decision_id 참조 검증 E2E | BACKLOG #5 (Medium-term) |

### 2.4 Longer-term / Nice-to-have (P3)

| # | 항목 | 설명 | BACKLOG # |
|---|------|------|-----------|
| 13 | **Operator intervention workflow** | 사람 개입 kill switch, 강제 상태 변경, 수동 reconciliation | Medium-term #3 |
| 14 | **Soak / recovery / chaos tests** | 장기 실행 안정성, 장애 복구, 비정상 입력 내성 검증 | Longer-term #1 |
| 15 | **Provider failover / fallback hardening** | LLM provider 장애 시 auto-retry, provider 전환 | Longer-term #2 |
| 16 | **KIS 실통신 (real API key + live trading)** | 실제 KIS API key + live 환경 trading | Deferred #1 |
| 17 | **키움증권 Broker Adapter** | Kiwoom broker adapter 추가 | Deferred #2 |
| 18 | **Full reconciliation automation** | Auto-resolve reconciliation | Deferred #3 |
| 19 | **Redis cache layer** | Rate limit, session cache Redis 이전 | Deferred #5 |
| 20 | **CI/CD pipeline** | K8s, Terraform, GitHub Actions | Deferred #6 |
| 21 | **Observability stack** | Metrics, tracing, structured logging, alerting | Deferred #7 |

---

## 3. 현재까지의 주요 Plan 번호 참조

| 범위 | Plan 번호 |
|------|-----------|
| 초기 인프라 ~ Milestone 8 | [`plans/01`](plans/01.dev_infrastructure_plan.md) ~ [`plans/16`](plans/16.post_milestone8_plan.md) |
| LLM Provider 연결 | [`plans/24`](plans/24_llm_provider_resolver.md) ~ [`plans/30`](plans/30_runtime_three_agent_smoke.md) |
| Broker Submit 경로 | [`plans/32`](plans/32_ai_broker_boundary_pre_submit_verification.md) ~ [`plans/38`](plans/38_postgres_long_path_execution.md) |
| Inspection API + Auth | [`plans/40`](plans/40_fastapi_inspection_api.md) ~ [`plans/47`](plans/47_auth_policy_hardening.md) |
| Admin UI | [`plans/48`](plans/48_admin_ui_phase1.md) ~ [`plans/66`](plans/66_admin_ui_korean_localization.md) |
| Snapshot Sync 운영화 | [`kis_snapshot_sync_operationalization.md`](plans/kis_snapshot_sync_operationalization.md) ~ [`kis_snapshot_sync_readiness.md`](plans/kis_snapshot_sync_readiness.md) |
| Gap Pipeline (AI→Order) | [`plans/gap1`](plans/gap1_ai_decision_to_order_submit.md) ~ [`plans/gap4`](plans/gap4_backend_sizing_math.md) |
| Paper Trading Loop | [`paper_trading_loop_validation.md`](plans/paper_trading_loop_validation.md) ~ [`pipeline_phase55_post_submit_sync.md`](plans/pipeline_phase55_post_submit_sync.md) |
| Paper 성과/Gate/Exit | [`paper_performance_summary.md`](plans/paper_performance_summary.md) ~ [`live_gate_canary_readiness.md`](plans/live_gate_canary_readiness.md) |
| **금회 작업** | [`paper_submit_smoke_cleanup.md`](plans/paper_submit_smoke_cleanup.md) (설계) + [`kis_paper_submit_price_fix_report.md`](plans/kis_paper_submit_price_fix_report.md) (이전 smoke 결과) |

---

## 4. 금회 변경 사항 요약

| 파일 | 변경 | 상세 |
|------|------|------|
| [`scripts/run_orchestrator_once.py`](scripts/run_orchestrator_once.py) | 수정 | `_resolve_smoke_price()` 함수 추가. `price=Decimal("268500")` 하드코딩 제거. submit 경로 경고 로그 추가 |
| [`tests/brokers/koreainvestment/test_rest_client_submit.py`](tests/brokers/koreainvestment/test_rest_client_submit.py) | 신규 생성 | 9 tests: 성공 응답(2), business error(2), body 구조(2), price resolve(3) |

### 알려진 이슈
- `KISRestClient`는 `@dataclass(slots=True)` → mock 시 class-level `patch.object(KISRestClient, "_request", ...)` 사용해야 함 (instance patch 불가)
- `KIS_SMOKE_PRICE` 미설정 시 `--submit` fallback=50000은 KIS price validation error(`msg_cd=40270000`) 유발 가능 → WARNING 로그 추가됨
