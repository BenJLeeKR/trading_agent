# 남은 작업 우선순위 정리

## 목적

- `plans/[BACKLOG] backlog.md`와 2026-06-01 ~ 2026-06-03 사이의 최근 작업 문서를 함께 기준으로 삼아,
  지금 시점에서 **실제로 남은 작업**을 우선순위별로 재정리한다.
- 추가로 `plan_docs/agents/`의 agent 설계 문서
  - `01_agent_inventory_and_status.md`
  - `02_agent_target_shapes.md`
  - `03_risk_role_boundaries.md`
  도 함께 반영한다.
- 이미 해결된 장애성 이슈와, 아직 구조적으로 남아 있는 과제를 구분한다.
- 사용자가 요청한 방향에 맞춰 **Admin UI 추가 고도화는 후순위**로 내리고, 백엔드/운영 안정화 과제를 앞에 둔다.

## 현재 기준선

최근 완료된 핵심 작업:

1. `VTTC0081R` 체결내역 화면 Phase 1
   - [`plans/2026-06-02_vttc0081r_fill_history_screen_phase1.md`](./2026-06-02_vttc0081r_fill_history_screen_phase1.md)
2. fill snapshot ↔ order_request 직접 연결 + order sync truth source 전환 (Phase 2)
   - [`plans/2026-06-03_vttc0081r_fill_history_phase2_order_link.md`](./2026-06-03_vttc0081r_fill_history_phase2_order_link.md)
3. fill sync budget retry 및 retry observability
   - [`plans/2026-06-03_fill_sync_budget_retry.md`](./2026-06-03_fill_sync_budget_retry.md)
   - [`plans/2026-06-03_fill_sync_retry_summary_json.md`](./2026-06-03_fill_sync_retry_summary_json.md)
4. fill-history API 서버 필터 추가
   - [`plans/2026-06-03_fill_history_server_filters.md`](./2026-06-03_fill_history_server_filters.md)
5. BUY/SELL 제출 경로, after-hours recovery, false expired 복구, shared budget, scheduler submit gate 관련 긴급 장애 다수 정리
   - 2026-06-01 ~ 2026-06-02 문서군 참조
6. 일반 submit cap 의미를 `일반 BUY cap`으로 명확화
   - [`plans/2026-06-04_general_buy_cap_split.md`](./2026-06-04_general_buy_cap_split.md)

즉, 현재는 “기본 기능이 아예 없는 상태”가 아니라:

- 체결내역은 수집/조회 가능
- 체결 snapshot은 주문과 연결 가능
- 주문 상태 복구는 fill snapshot을 truth source로 일부 사용 가능
- fill sync budget retry와 health summary도 있음

상태다.

따라서 다음 우선순위는 **운영 진실(source of truth) 강화**, **동기화 안정화**, **장중 운영 검증**, **구조적 기술부채 정리** 순서로 잡는 것이 맞다.

## 상태 표기

- `완료`: 문서에 적은 세부 작업이 현재 범위에서 모두 반영됨
- `진행중`: 핵심 구조는 들어갔지만 실측/잔여 세부 작업이 남음
- `미완료`: 아직 본격 구현 전
- `보류`: 의도적으로 후순위로 미룸

---

## Agent 설계 문서 반영 기준

`plan_docs/agents/` 문서를 반영하면, 남은 작업의 성격을 다음처럼 더 명확히 볼 수 있다.

### 1. 모든 Agent가 LLM일 필요는 없다

`Agent`는 책임 단위이지, 모두가 provider LLM 호출 단위는 아니다.

- `Data Collector`, `Data Quality`, `Execution`, `Performance`, `Model Monitor`는
  상당 부분이 deterministic service/worker로 구현되는 것이 맞다.
- 반대로 AI는
  - Event Interpretation
  - AI Risk
  - 향후 일부 Compliance/정책 해석
  같은 해석 계층에 우선 배치되어야 한다.

### 2. Execution / Guardrail / Compliance 집행은 deterministic이 우선이다

`03_risk_role_boundaries.md` 기준 현재 가장 중요한 원칙:

- `AI Risk Agent`는 **리스크 해석기**
- `Sizing Engine`은 **결정적 수량 계산기**
- `Hard Guardrail`은 **최종 강제 차단기**
- `AI Compliance Agent`가 생기더라도 **authoritative enforcement는 deterministic validator**

즉, 남은 작업 우선순위도 “AI를 더 붙이는 것”보다
“execution truth / guardrail / sync / reconciliation을 deterministic하게 더 닫는 것”이 먼저여야 한다.

### 3. 현재 진짜 미구현인 Agent 축은 전략/신호/포트폴리오 계층이다

`01_agent_inventory_and_status.md` 기준:

- 이미 일부 구현/운영 중인 축
  - Data Collector: 부분 구현
  - Data Quality: 부분 구현
  - News/RAG(Event Interpretation): 부분 구현
  - AI Risk: 구현
  - Execution: 부분 구현
- 아직 미구현인 핵심 축
  - Market Regime
  - Universe Selection
  - Strategy Selection
  - Signal
  - Portfolio
  - AI Compliance
  - Model Monitor

따라서 P2 이후 구조화 작업은 단순 backlog가 아니라,
**현재 v1에서 Final Decision Composer에 임시 흡수된 책임을 분리하는 과정**으로 해석해야 한다.

### 4. 현재 P0/P1 우선순위가 왜 agent 분해보다 앞서는가

agent 설계 문서 기준으로도 순서는 다음이 맞다.

1. 체결/주문/정합성 진실원 안정화
2. guardrail / snapshot / reconciliation / fill sync 안정화
3. 그 다음에 Market/Universe/Strategy/Signal/Portfolio 계층 분리

이 순서가 맞는 이유는, 상위 전략 계층을 세분화하더라도
하위 execution truth와 state convergence가 불안정하면 운영 가치가 떨어지기 때문이다.

---

## P0 — 즉시 진행할 백엔드/운영 과제

### 1. Fill History Phase 3 — `완료`

### 목표
- `fill snapshot`을 단순 조회 데이터가 아니라 **주문/정합성 복구의 1급 진실원**으로 끌어올린다.

### 세부 작업 상태
- [x] `order_request_id → trade_decision_id`까지 API/조회 경로 확장
- [x] 주문 상세 API에 linked fill snapshot 요약 추가
- [x] `order_sync_service`의 부분체결 판정을 `position_delta`보다 `fill snapshot` 우선으로 더 확대
- [x] 같은 `ODNO`의 다회 조회/누적 체결 표현 차이를 흡수하는 규칙 정리

### 근거 문서
- [`plans/2026-06-03_vttc0081r_fill_history_phase2_order_link.md`](./2026-06-03_vttc0081r_fill_history_phase2_order_link.md)
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

### 우선순위 이유
- 현재 시스템의 가장 중요한 남은 리스크는 “실제 체결 진실을 얼마나 직접적으로 아느냐”다.
- 이 축이 안정돼야 `submitted/reconcile_required/partially_filled` 판단이 더 이상 snapshot 추론에 과하게 의존하지 않게 된다.
- agent 설계 문서 기준으로도 이것은 `Execution Agent`와 `Data Quality Agent`의 미완성 영역에 해당한다.

---

### 2. 부분체결 자동 판정 고도화 — `완료`

### 목표
- 현재 보수적으로 남겨둔 `partially_filled`/`submitted` 복구 케이스를 더 정확하게 자동 판정한다.

### 세부 작업 상태
- [x] fill snapshot의 `filled_quantity` 변화 패턴을 이용한 누적/증분 해석 규칙 추가
- [x] 같은 종목 연속 주문 cohort에서 `fill snapshot + order_time` 기준 안전한 매핑 규칙 정리
- [x] `position_delta` fallback은 마지막 수단으로만 사용하도록 축소
- [x] 부분체결 잔여 수량 계산과 후속 상태 전이(`partially_filled` 유지 vs `filled`) 테스트/수렴 보강
  - [`plans/2026-06-04_fill_snapshot_partial_progress_convergence.md`](./2026-06-04_fill_snapshot_partial_progress_convergence.md)

### 근거 문서
- [`plans/2026-06-03_vttc0081r_fill_history_phase2_order_link.md`](./2026-06-03_vttc0081r_fill_history_phase2_order_link.md)
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 의 reconciliation / partially filled 관련 항목
- `plan_docs/agents/03_risk_role_boundaries.md`

### 우선순위 이유
- false expired는 상당 부분 복구됐지만, 부분체결은 아직 가장 보수적인 영역이다.
- 이 부분이 해결돼야 operator 개입 없이 상태 수렴 품질이 올라간다.
- 또한 부분체결 판정은 AI가 아니라 deterministic truth/reflection 계층이 맡아야 하는 대표 영역이다.

---

### 3. 다음 거래일 장중 실운영 검증 — `완료`

### 목표
- 최근 수정들이 실제 장중 흐름에서 정상 작동하는지 **실측**한다.

### 현재 상태
- 장중 검증용 CLI 추가 완료:
  - [`plans/2026-06-04_intraday_operational_validation_cli.md`](./2026-06-04_intraday_operational_validation_cli.md)
- `operations_day_runs.summary_json`에 최근 `decision_submit_gate` / `decision_dry_run` 결과를 저장하도록 보강
- 현재는 아래를 한 번에 평가 가능
  - 거래일 판정
  - `operations_day_runs` heartbeat / phase
  - 최근 decision loop 결과
  - 오늘 BUY submit lane 상태
  - 차단성 미해결 주문
  - `truth_probe_fill_snapshot_incomplete`
  - snapshot/fill sync freshness

### 확인 포인트
1. `decision_submit_gate`가 `timeout=False`로 끝나는지
2. 일반 BUY lane이 실제로 열리는지
3. held-position SELL이 일반 BUY budget을 잠그지 않는지
4. fill sync가 budget retry 후 정상 completed 되는지
5. 주문이 다시 `expired`로 잘못 닫히지 않는지
6. `order_submission_attempts`, `fill snapshots`, `order sync`가 같은 주문에 대해 일관된지

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `8a`
- [`plans/2026-06-01_paper_order_stability_measurement.md`](./2026-06-01_paper_order_stability_measurement.md)

### 우선순위 이유
- 최근 수정의 상당수는 장후/비거래일 기준 검증까지는 끝났지만, 장중 실측이 아직 남아 있다.
- 운영 시스템은 결국 장중 실동작이 최종 기준이다.

### 세부 작업 상태
- [x] 장중 첫 `decision_submit_gate` 이후 `decision_loop` summary 자동 적재 재확인
  - [`plans/2026-06-04_intraday_decision_loop_immediate_persist.md`](./2026-06-04_intraday_decision_loop_immediate_persist.md)
- [x] BUY submit 이후 추가 cycle에서 `submit_budget_consumed_*` 편향 감지 자동화
  - [`plans/2026-06-04_intraday_buy_lane_bias_check.md`](./2026-06-04_intraday_buy_lane_bias_check.md)
- [x] command별 최근 성공/실패 카운터를 `operations_day_runs.summary_json`에 구조화

---

### 4. Fill 발생 후 position/cash refresh 자동화 — `완료`

### 목표
- fill 확인 직후 계좌 snapshot이 더 빨리 최신화되도록 연결한다.

### 세부 작업 상태
- [x] fill snapshot 또는 post-submit sync 성공 시 snapshot refresh 직접 연결
  - [`plans/2026-06-04_partial_fill_snapshot_refresh.md`](./2026-06-04_partial_fill_snapshot_refresh.md)
- [x] cash / positions / orderable amount 갱신 우선순위 1차 정리
- [x] refresh 중 quota 소진 시 degraded 처리 기준 1차 명확화
- [x] 장중 실측 기준 수렴 속도 재검증
  - [`plans/2026-06-05_fill_refresh_convergence_measurement.md`](./2026-06-05_fill_refresh_convergence_measurement.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `14`
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

### 우선순위 이유
- 주문 truth와 계좌 truth가 더 빨리 수렴해야 다음 주문 sizing/guard도 안정화된다.
- 이는 `Data Collector` / `Data Quality` / `Execution` 경계가 실제 운영에서 닫히는 작업이다.

---

## P1 — 높은 우선순위의 운영/플랫폼 과제

### 5. KIS 실계정/실운영 smoke 검증 — `완료`

### 목표
- paper에서 정리한 제출/동기화 경로를 실제 KIS credential 환경에서도 검증한다.

### 세부 작업 상태
- [x] KIS real credential + operator 승인 하의 실제 combined submit smoke 실행
  - 실제 KIS 응답 확인: `KIOK0320 / 장운영시간이 아닙니다`
- [x] live-info read-only smoke(`auth / approval / quote`) 경로 추가
  - [`plans/2026-06-05_kis_live_readonly_smoke_phase1.md`](./2026-06-05_kis_live_readonly_smoke_phase1.md)
- [x] live submit preflight(read-only)
  - [`plans/2026-06-05_kis_live_submit_preflight_phase3.md`](./2026-06-05_kis_live_submit_preflight_phase3.md)
- [x] guarded combined submit smoke runner
  - [`plans/2026-06-05_kis_live_combined_submit_smoke_runner.md`](./2026-06-05_kis_live_combined_submit_smoke_runner.md)
- [x] guarded combined submit dry-run smoke 검증
  - `status=READY`, `submitted=False`
- [x] live info / paper submit 경로의 budget 분리 1차 정리
  - live quote client 전용 live budget manager 주입
- [x] fill sync와의 실제 budget 경쟁 실측
  - [`plans/2026-06-05_kis_budget_isolation_smoke_phase2.md`](./2026-06-05_kis_budget_isolation_smoke_phase2.md)
- [x] paper 전용 우회 정책이 live에도 불필요하게 남아 있지 않은지 확인
  - [`plans/2026-06-05_kis_budget_isolation_smoke_phase2.md`](./2026-06-05_kis_budget_isolation_smoke_phase2.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `8`

---

### 6. KIS token/approval cache 공통 모듈화 — `완료`

### 목표
- paper/live/disclosure/holiday/approval key 경로에 흩어진 토큰 캐시 로직을 정리한다.

### 세부 작업 상태
- [x] 공통 cache contract 1차 정리
- [x] cache purpose 표준화 1차 정리
- [x] expiry/fingerprint/validator helper 추출
- [x] rest/holiday/market_state client 통합 적용
- [x] approval key를 REST client 쪽에서도 파일 cache까지 확장
  - [`plans/2026-06-08_kis_rest_approval_key_file_cache.md`](./2026-06-08_kis_rest_approval_key_file_cache.md)
- [x] token cache health를 운영 관측값에 직접 노출
  - [`plans/2026-06-08_kis_token_cache_health_observability.md`](./2026-06-08_kis_token_cache_health_observability.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `34`
- [`plans/2026-06-05_kis_token_cache_common_module_phase1.md`](./2026-06-05_kis_token_cache_common_module_phase1.md)

### 우선순위 이유
- 지금 당장 장애는 아니지만, KIS 관련 운영 안정성의 중기 핵심 기술부채다.

---

### 7. 운영일 상태 관리(`operations_day_runs`) — `완료`

### 목표
- 운영 대시보드가 “추정 상태”가 아니라 DB 기반 운영일 상태를 보여주게 만든다.

### 현재 상태
- 1차 저장 경로는 완료
- latest 조회 API도 완료
- `summary_json`에 snapshot/fill-sync/recovery health 구조화도 완료
- 운영 대시보드 `Scheduler Status` 카드 연결도 완료
- `by-date` / `history` 조회 API도 완료
- 관련 문서:
  - [`plans/2026-06-03_operations_day_runs_phase1.md`](./2026-06-03_operations_day_runs_phase1.md)
  - [`plans/2026-06-03_operations_day_runs_api_phase1.md`](./2026-06-03_operations_day_runs_api_phase1.md)
  - [`plans/2026-06-03_operations_day_runs_summary_json_health.md`](./2026-06-03_operations_day_runs_summary_json_health.md)
  - [`plans/2026-06-03_operations_day_runs_dashboard_status_card.md`](./2026-06-03_operations_day_runs_dashboard_status_card.md)
  - [`plans/2026-06-04_operations_day_runs_history_api.md`](./2026-06-04_operations_day_runs_history_api.md)

### 세부 작업 상태
- [x] `summary_json` 내부 command health 세분화 완료
  - [`plans/2026-06-04_operations_day_runs_command_health_granularity.md`](./2026-06-04_operations_day_runs_command_health_granularity.md)
- [x] readiness / 장중 검증 결과와 `operations_day_runs history`를 직접 연결 완료
  - [`plans/2026-06-04_operations_day_runs_validation_summary_link.md`](./2026-06-04_operations_day_runs_validation_summary_link.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `10`

### 우선순위 이유
- 비거래일/장종료/운영중 상태를 더 명확히 표시할 수 있어 operator 혼선을 줄인다.

---

### 8. 장 운영 세션 정보 수집/저장 — `완료`

### 목표
- 휴장/조기종료/특수 세션 정보를 정식 데이터로 보유하고 운영 정책에 반영한다.

### 현재 상태
- `market_sessions` latest 조회 API는 이미 있음
- `market_sessions` 날짜별 단건 조회 / 기간 history 조회도 완료
- `market_sessions.reason_code` 구조화 저장도 완료
- `market_sessions.reason_metadata` 구조화 저장도 완료
- `session_events`도 `run_date` 기준 drill-down 가능
- 관련 문서:
  - [`plans/2026-06-03_market_sessions_history_api.md`](./2026-06-03_market_sessions_history_api.md)
  - [`plans/2026-06-03_market_sessions_reason_code_structuring.md`](./2026-06-03_market_sessions_reason_code_structuring.md)
  - [`plans/2026-06-03_session_events_run_date_drilldown.md`](./2026-06-03_session_events_run_date_drilldown.md)
  - [`plans/2026-06-08_market_sessions_reason_metadata_structuring.md`](./2026-06-08_market_sessions_reason_metadata_structuring.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `7`

### 세부 작업 상태
- [x] `market_sessions` latest / by-date / history API 정비 완료
- [x] `reason_code` 구조화 저장 완료
- [x] `reason_metadata` 구조화 저장 완료
- [x] `session_events` run-date drill-down 완료
- [x] `market_sessions`와 readiness / next-trading-day 상태 직접 연결 완료

---

### 9. KIS 기본종목정보 instrument master 적재/갱신 — `완료`

### 목표
- 종목 메타데이터를 KIS 기준으로 더 안정적으로 관리한다.

### 세부 작업 상태
- [x] 정규화된 KIS master CSV 기반 기본종목정보 수집 파이프라인 1차 완료
  - [`plans/2026-06-08_kis_instrument_master_sync_pipeline_phase1.md`](./2026-06-08_kis_instrument_master_sync_pipeline_phase1.md)
- [x] instrument master 갱신 정책
  - [`plans/[POLICY] kis_instrument_master_update_policy.md`](./[POLICY]%20kis_instrument_master_update_policy.md)
  - KOSDAQ 종목은 `instrument master`에 적재되기 전에는
    Universe Selection에서 `unknown_instrument`로 제외되므로,
    시장 확장 전제 조건을 문서/코드에 명시했다.
- [x] snapshot/event mapping과의 정합성 확보
  - [x] recent `external_events` / `broker_fill_snapshots` unmapped symbol audit CLI
    - [`plans/2026-06-08_instrument_mapping_consistency_audit.md`](./2026-06-08_instrument_mapping_consistency_audit.md)
  - [x] unmapped symbol summary inspection API
    - [`plans/2026-06-08_instrument_mapping_consistency_summary_api.md`](./2026-06-08_instrument_mapping_consistency_summary_api.md)
  - [x] snapshot sync unknown-instrument 오류를 mapping summary와 연결
    - [`plans/2026-06-11_instrument_mapping_snapshot_sync_error_link.md`](./2026-06-11_instrument_mapping_snapshot_sync_error_link.md)
  - [x] unmapped symbol auto-seed / placeholder instrument 생성 정책
    - [`plans/2026-06-11_placeholder_instrument_policy.md`](./2026-06-11_placeholder_instrument_policy.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `8`

### 우선순위 이유
- symbol / market / 이름 / 활성상태의 authoritative source가 강화되면 universe, fill history, event mapping 품질이 같이 올라간다.

### KOSDAQ 확장 후속 우선순위

현재 판단 기준:

- `instrument master` 미등록 종목이 `unknown_instrument`로 제외되는 경계는 유지하는 것이 맞다.
- `core universe가 active KRX 전체를 그대로 먹는다`는 과거 문제 제기는 현재 구현 기준으로는 상당 부분 완화됐다.
  - 현재는 `approved core universe seed` 기반으로 축소되어 있다.
- `market overlay가 항상 알파벳 순 50개만 본다`는 진단도 현재 기준으로는 일부만 유효하다.
  - 현재는 KIS ranking seed 우선, fallback pre-pool 보조 구조다.
- 따라서 KOSDAQ 확장의 실제 선결과제는 `시장 구분이 보존된 instrument master 적재`와
  `적재 이후 운영 경로 실측`이다.

#### 9-a. KOSPI/KOSDAQ 통합 instrument master CSV 확보 및 장전 배치 연결 — `최우선`

- 목표
  - 장이 열리는 날 장전 시점에 KOSPI/KOSDAQ 구분이 보존된 CSV로
    `instrument master`를 자동 갱신한다.
- 이유
  - master가 비어 있으면 Universe Selection 단계에서 그대로 탈락하므로,
    이 단계가 없으면 이후 KOSDAQ 확장은 모두 무의미하다.
- 완료 기준
  - scheduler에서 거래일 `07:50 KST`에 instrument master sync가 1회 실행된다.
  - 입력 CSV가 실제로 KOSDAQ row를 포함하고, `market_code`가 `KOSDAQ`로 보존된다.
- 현재 진행 상태
  - [x] `sync_kis_instrument_master.py`가 `market_code=KOSDAQ`를 보존하는 적재 경로를 가진다.
  - [x] `ops-scheduler`에 거래일 `07:50 KST` 1회 실행 경로를 연결했다.
  - [x] 원본 CSV 여러 개를 `data/instrument_master/normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv`로 합치는
    정규화 전처리 스크립트와 scheduler 선행 실행 경로를 추가했다.
  - [x] 운영 원본 CSV 입력 경로와 보관 경로를 코드로 고정했다.
    - 입력: `data/instrument_master/source/kospi_master.csv`
    - 입력: `data/instrument_master/source/kosdaq_master.csv`
    - 정규화 출력: `data/instrument_master/normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv`
    - 원본 보관: `data/instrument_master/archive/<YYYY-MM-DD>/...`
  - [x] csv 미존재 / sync 실패 시에는 `done` 처리하지 않고 다음 tick에 재시도하도록 보정했다.
  - [x] scheduler summary/runtime에 `instrument_master_sync` 상태와 기본 CSV 경로를 노출한다.

#### 9-b. KOSDAQ master 적재 후 universe/feature 경로 실측 — `상`

- 목표
  - KOSDAQ row가 적재된 뒤 실제 운영 경로가 깨지지 않는지 확인한다.
- 점검 범위
  - Universe Selection에서 등록된 KOSDAQ 종목이 `unknown_instrument`로 잘못 차단되지 않는지
  - `signal_feature_snapshot_input` 생성이 `KOSDAQ` market을 수용하는지
  - decision loop / preview API / coverage summary에서 시장 코드가 일관되게 보이는지
- 이유
  - instrument master 적재만 되고 후속 배치/판단 경로가 `KRX` 고정이면
    운영상 부분 실패가 발생한다.
- 현재 진행 상태
  - [x] Universe Selection에서 등록된 `KOSDAQ` 종목이 `unknown_instrument`로 잘못 차단되지 않는
    경로를 테스트로 재확인했다.
  - [x] `generate_signal_feature_snapshot_input.py`가 `market=KOSDAQ` universe row를
    그대로 수용하는 경로를 테스트로 고정했다.
  - [x] `run_decision_loop._read_trading_universe()`의 DB fallback이
    `KOSDAQ` market_code를 유지하는 경로를 테스트로 고정했다.
  - [x] `/instruments/trading-universe/preview` 응답이 `market=KOSDAQ`를 그대로 노출하는
    경로를 테스트로 고정했다.
  - [x] `/instruments/trading-universe/coverage-summary`에 `market_counts`를 추가해
    최근 판단 시장 분포(`KOSPI/KOSDAQ/KRX`)를 운영에서 직접 확인할 수 있게 했다.

#### 9-c. KOSDAQ 탐색 대상과 주문 가능 대상을 분리한 단계적 편입 — `상`

- 목표
  - KOSDAQ을 바로 `core universe`로 넣지 않고,
    `market discovery seed pool` 또는 `event overlay` 쪽부터 단계적으로 편입한다.
- 원칙
  - `탐색 풀`과 `주문 가능 풀`을 동일시하지 않는다.
  - KOSDAQ 확장은 우선 `탐색/랭킹/계측` 계층에서 시작하고,
    execution 안정성 검증 후 주문 가능 풀로 승격한다.
- 이유
  - 기대수익률 확대 기회는 크지만,
    현재 단계에서 즉시 주문 universe까지 넓히면 체결 리스크가 먼저 커진다.
- 현재 진행 상태
  - [x] `APPROVED_CORE_UNIVERSE_SYMBOLS`에서 KOSDAQ `090150` 직접 core 편입을 제거했다.
  - [x] `APPROVED_DISCOVERY_UNIVERSE_SYMBOLS`를 추가해 KOSDAQ 시범 종목은
    `market overlay fallback seed`로만 진입하도록 분리했다.
  - [x] 명시적 `core_universe=true`가 없으면 KOSDAQ discovery seed가
    `compose()` 결과의 주문 core에 포함되지 않는 테스트를 고정했다.
  - [x] KOSDAQ discovery seed가 `compose_with_diagnostics()`의
    `market overlay fallback seed`에는 포함되는 테스트를 고정했다.

#### 9-d. instrument master의 KOSPI/KOSDAQ/segment authoritative source화 — `중`

- 목표
  - `KRX`는 `exchange_code` 역할로 유지하되,
    `market_segment=KOSPI|KOSDAQ`와 `index_memberships`를 별도 기준 데이터로 승격한다.
  - `market_segment`, `segment`, `universe_segment`, 필요 시 `exchange_code`까지
    instrument master의 정식 기준 데이터로 고정한다.
- 이유
  - 현재 일부 로직은 allowlist와 metadata fallback에 의존한다.
  - 장기적으로는 `KOSPI100`, `KOSDAQ150`, `KOSPI_LARGE`, `KOSDAQ_GROWTH`
    같은 segment 기준으로 탐색 풀과 core seed를 더 정교하게 분리해야 한다.
  - `KRX`를 바로 제거하면 기존 `position/order/snapshot/replay` FK와
    과거 운영 데이터 정합성이 깨질 수 있으므로,
    삭제보다 `역할 분리`가 먼저다.
- 현재 진행 상태
  - [x] `build_kis_instrument_master_sync_csv.py`가 normalized CSV에
    `exchange_code`, `metadata_market_segment`, `metadata_segment`,
    `metadata_universe_segment`, `metadata_index_memberships`를 함께 기록하도록 확장했다.
  - [x] source CSV의 `market_segment/segment/universe_segment` 별칭과
    `is_kospi200` / `is_kosdaq150` 플래그를
    `KOSPI100`, `KOSPI200`, `KOSDAQ150`, `KOSPI_LARGE`, `KOSDAQ_GROWTH` 형태의
    membership metadata로 정규화하는 경로를 추가했다.
  - [x] 현재 원본 CSV에는 `KOSPI100`, `KOSDAQ50` 직접 플래그가 없으므로
    별도 원천 데이터 전까지는 자동 생성하지 않는 정책을 문서화했다.
  - [x] `sync_kis_instrument_master.py`가 위 필드들을 instrument metadata의
    authoritative source로 적재하는 테스트를 고정했다.
  - [x] `trading.instruments`에 `exchange_code`, `market_segment`
    정식 컬럼 추가 여부를 확정한다.
  - [x] `index_memberships`는
    `metadata 배열` fallback을 유지하되,
    `instrument_index_memberships` 별도 테이블을 authoritative history로 승격한다.
  - [x] universe / sell_guard / snapshot sync에서
    `market_code` 대신 `exchange_code + market_segment`를 우선 참조하는
    점진 이행 계획을 문서화한다.
    - UniverseSelection은 `instrument_index_memberships` 우선 / metadata fallback으로 전환
    - sell_guard, snapshot sync는 canonical instrument lookup 유지 상태에서 후속 전환
  - [x] 과거 `market_code='KRX'` row와 신규 `market_segment='KOSPI|KOSDAQ'`
    row를 중복 생성하지 않도록 canonical instrument 정책을 확정한다.

#### 9-f. 국내주식 instrument canonical model 정규화 — `상`

- 목표
  - `trading.instruments`에서
    `exchange_code`, `market_segment`, `index_memberships`의 역할을 분리해
    국내주식 canonical model을 정립한다.
- 원칙
  - `KRX`는 삭제하지 않고 `exchange_code` 의미로 유지한다.
  - `KOSPI`, `KOSDAQ`는 `market_segment`로 분리한다.
  - `KOSPI100`, `KOSPI200`, `KOSDAQ50`, `KOSDAQ150`은
    단일 bool 컬럼 난립 대신
    `index_memberships` authoritative source로 관리한다.
  - 기존 `position/order/snapshot` FK를 깨지 않는
    backward-compatible migration 순서를 유지한다.
- 권장 구현 순서
  - [x] 1차: `instruments`에 `exchange_code`, `market_segment` nullable 정식 컬럼 추가
  - [x] 1차: sync pipeline이 위 컬럼을 metadata가 아니라 정식 컬럼에도 적재
  - [x] 1차: `index_memberships`는 `metadata.index_memberships` 배열로 우선 적재
  - [x] 2차: UniverseSelectionService가
    allowlist보다 `market_segment + index_memberships + metadata flag`를 우선 사용
    - `core_universe` explicit flag를 최우선으로 유지
    - 그 다음 `index_memberships`와 `market_segment`로
      `KOSPI100/KOSPI200/KOSDAQ50/KOSDAQ150` seed를 판정
    - 코드 allowlist는 fallback 경로로만 유지
  - [x] 2차: `get_by_symbol_any_market()`류 조회는
    `exchange_code='KRX'` + canonical precedence를 사용하도록 정리
  - [x] 3차: `instrument_index_memberships` 시계열 테이블로 승격
  - [x] 3차: 그 이후에만 `market_code='KRX'` legacy 경로 축소 여부를 재검토
    - `sell_guard`는 이미 `get_by_symbol_any_market()` 기반 canonical lookup 사용
    - `kis_snapshot_sync`도 `get_by_symbol_any_market()`로 전환
    - 저장 canonical row는 `market_code='KRX'`를 유지하고,
      read path에서만 `exchange_code + market_segment` 우선 해석을 적용
  - [x] 3차: `trade_decisions.instrument_id`도
    canonical instrument row와 연결되도록 저장 경로를 보강
    - `DecisionOrchestratorService`가 `symbol + market` 우선,
      실패 시 `get_by_symbol_any_market()` fallback으로
      canonical instrument를 조회한 뒤
      `TradeDecisionEntity.instrument_id`를 채우도록 수정했다.
    - 기존 누적 데이터는 backfill을 수행해
      instrument master에 존재하는 건은 대부분 연결 완료했다.
    - 남은 `instrument_id IS NULL` 건은
      당시 `trading.instruments`에 row가 없던 종목(`000030`, `003410`, test symbol) 위주다.
  - [x] 4차 리팩토링 검토:
    `market_code='KRX'` canonical 저장 모델을 유지할지,
    아니면 `market_code='KOSPI'|'KOSDAQ'` + `exchange_code='KRX'`로
    더 직관적인 저장 모델로 재정의할지 결정한다.
    - 결론:
      현재 단계에서는 `market_code='KRX'` canonical 저장 모델을 유지한다.
    - 이유:
      `market_segment`와 `instrument_index_memberships`가
      이미 `KOSPI/KOSDAQ/지수편입` 의미를 분리하고 있고,
      반대로 저장 모델 전환은
      FK, replay, snapshot, order history, 테스트 fixture 수정 범위가 크다.
    - 근거 문서:
      [`plans/[DESIGN] instrument_market_code_canonical_model_decision.md`](./[DESIGN]%20instrument_market_code_canonical_model_decision.md)
    - 재검토는
      authoritative membership source 안정화와
      read path 전환이 충분히 끝난 뒤
      별도 migration/reconciliation 계획이 있을 때만 수행한다.
  - [x] 4차 리팩토링 검토:
    `KOSPI100`, `KOSDAQ50`, `KOSDAQ150` membership authoritative source를
    KIS 기본종목정보 CSV 외 별도 원천으로 보강한다.
    - 현재 원본 CSV는 `is_kospi200=True/False`, `is_kosdaq150=False`만 제공해
      `KOSPI200`만 직접 생성 가능하다.
    - [x] KIS `FHPUP02140000` 연동 경로를 추가해
      `KOSPI100`, `KOSPI200` 등 지수/업종 코드 카탈로그를
      KIS 기준으로 조회/덤프할 수 있게 했다.
      - 메서드:
        `KISRestClient.get_index_category_quotes()`
      - 보조 스크립트:
        `scripts/export_kis_index_category_catalog.py`
      - 단, 이 TR은 `구성종목 목록`이 아니라 `지수/업종 전체시세 목록`이므로
        membership authoritative source로 직접 사용하지 않는다.
    - [x] `FHPUP02140000` dump를
      `index_membership_seed` 운영 검증 자료로 연결하는
      보조 절차를 추가했다.
      - `scripts/validate_kis_index_membership_catalog.py`가
        export 결과(`json/csv`)를 읽어
        seed CSV의 membership code가
        `코스피 100`, `코스피 200`, `코스닥 50`, `코스닥150`
        alias와 매칭되는지 자동 점검한다.
      - 이 절차는 구성종목 authoritative source를 생성하는 것이 아니라,
        seed 파일 provenance와 코드 오기입을
        운영자가 장전/장후에 빠르게 검증하기 위한
        보조 안전장치다.
    - `KOSPI100`, 실제 `KOSDAQ150` 구성종목은
      별도 지수 구성종목 원천 파일 또는 승인 리스트 확보가 필요하다.
    - 2026-06-24 운영 업로드 원천
      (`kospi100_constituents.csv`, `kospi200_constituents.csv`,
      `kosdaq150_constituents.csv`)을
      `index_membership_source_manifest.json`로 묶어
      실제 authoritative source package 반영을 완료했다.
    - 반영 경로는
      `scripts/run_index_membership_source_package_pipeline.py`
      + `--replace-membership-code-snapshot` 플래그를 사용해
      membership code 단위 stale active row까지 함께 종료한다.
    - 실측 결과 현재 active membership은
      `KOSPI100=100`, `KOSPI200=200`, `KOSDAQ150=150`이다.
    - `KOSDAQ50`은 현재 운영 원천 파일이 없으므로
      지원 코드만 유지하고 실제 active set은 비워둔다.
    - [x] 중첩 membership 해석 규칙을 추가했다.
      - 원본 membership 집합은 삭제하지 않고 유지한다.
      - 대신 Universe/Decision/AI 프롬프트에서 공통으로
        `primary_index_membership`을 파생해 사용한다.
      - 현재 우선순위는
        `KOSPI100 > KOSDAQ50 > KOSPI200 > KOSDAQ150 > 기타`
        순이다.
    - [x] 외부 authoritative source package 수용 경로를 추가했다.
      - `scripts/build_index_membership_seed_from_source_package.py`
      - `data/instrument_master/source/index_membership_source_manifest.example.json`
      - 외부 원천은 membership별 `symbol` CSV 묶음 + manifest로 받고,
        이를 seed CSV로 정규화한 뒤
        기존 import/validation 절차로 연결하도록 운영 경로를 고정했다.
    - [x] import 전 instrument master 해상도 검증과 runbook을 추가했다.
      - `scripts/validate_index_membership_seed_resolution.py`
      - `plans/[RUNBOOK] index_membership_source_package_apply.md`
      - 실제 반영 순서를
        `source package build -> catalog validation -> resolution validation -> import`
        로 고정하고,
        unresolved symbol / placeholder symbol을
        import 전에 차단할 수 있게 했다.
    - [x] 통합 파이프라인 실행기를 추가했다.
      - `scripts/run_index_membership_source_package_pipeline.py`
      - 외부 원천 반영 시
        `source package build -> catalog validation -> resolution validation -> import`
        4단계를 하나의 명령으로 순차 실행하고,
        어느 단계에서 실패했는지 바로 식별할 수 있게 했다.
    - [x] 운영 보조 경로로
      `index_membership_seed.csv` import 스크립트와 템플릿을 추가했다.
      - 스크립트: `scripts/import_instrument_index_membership_seed.py`
      - 템플릿: `data/instrument_master/source/index_membership_seed.example.csv`
      - 기본 동작은 기존 active membership과 `merge`,
        `--replace-listed-symbols` 지정 시 listed symbol만 authoritative overwrite
      - import contract를 강화해
        허용 membership code를
        `KOSPI100`, `KOSPI200`, `KOSDAQ50`, `KOSDAQ150`
        로 고정하고,
        `source_name`, `source_ref`, `as_of_date`, `note`
        provenance 컬럼을 함께 저장하도록 보강했다.
      - 같은 symbol에 대해 provenance가 다르거나
        지원하지 않는 membership code가 들어오면
        import를 즉시 실패시켜
        잘못된 운영 seed 파일이 조용히 적재되지 않게 했다.
  - [x] 4차 운영 정리:
    `trade_decisions.instrument_id`가 비어 있던 잔여 종목
    (`000030`, `003410`, `TEST` 등)은
    canonical placeholder row 보강 + backfill로 정리했다.
    - `seed_placeholder_instruments_from_mapping_gaps.py`가
      `trade_decisions.instrument_id IS NULL` 심볼도
      mapping gap source로 인식하도록 확장했다.
    - placeholder row는 `exchange_code`, `market_segment`,
      `metadata.index_memberships`를 함께 가질 수 있도록 보강했다.
    - 운영 DB 기준 `trade_decisions.instrument_id IS NULL`은 `0건`까지 정리됐다.
  - [x] 후속 운영 정리:
    placeholder canonical row로 남아 있는 심볼을
    실제 instrument master row로 언제/어떻게 치환할지
    별도 정리한다.
    - [x] app 컨테이너에도 `./data:/app/data` 마운트를 추가해
      `index_membership_seed.csv` 같은 원천 파일을
      수동 배치/운영 스크립트가 컨테이너 내부에서 직접 읽을 수 있게 보완했다.
    - `sync_kis_instrument_master.py`가
      동일 `symbol + market_code='KRX'` canonical row를
      authoritative KIS master 데이터로 **승격(promote)** 하도록
      정책을 확정했다.
    - 이 승격 경로는 `instrument_id`를 유지하므로
      기존 `trade_decisions`, `signal_feature_snapshots`,
      `order_requests` 등 FK 참조를 깨지 않는다.
    - placeholder metadata
      (`placeholder`, `placeholder_source`, `canonical_master_pending`)는
      authoritative master metadata로 교체되고,
      같은 sync cycle에서
      `instrument_index_memberships` active row도 함께 동기화된다.
    - 관련 테스트로
      placeholder row가 실제 master row로 승격되며
      membership table까지 함께 갱신되는 케이스를 고정했다.
- 우선순위 이유
  - universe selection, sell guard, snapshot sync가
    동일 symbol의 다중 market row에 흔들리지 않게 만드는 기반 작업이다.
  - `최대 기대수익률`을 위해 KOSDAQ/segment 확장을 하더라도
    먼저 canonical instrument model이 안정돼야 한다.

#### 9-e. market overlay seed 품질의 장중 실측 및 보정 — `중`

- 목표
  - 현재의 `KIS ranking seed 우선 + fallback pre-pool` 구조가
    실제 장중에 KOSDAQ 하이알파 후보를 충분히 포착하는지 실측한다.
- 점검 항목
  - seed source별 후보 수
  - quotes requested / received
  - filtered out 수
  - 최종 overlay capture rate
- 이유
  - 현재 구조는 과거의 “알파벳 순 고정” 문제를 일부 해소했지만,
    seed 품질이 낮으면 기대수익률 확대 효과가 제한될 수 있다.
- 현재 진행 상태
  - [x] `GET /instruments/trading-universe/preview`의
    `market_overlay_diagnostics`에 기본 count 계측
    (`seed_pool_source`, `seed_pool_count`, `quotes_requested_count`,
    `quotes_received_count`, `filtered_out_count`,
    `scored_candidate_count`, `added_count`)이 노출되도록 유지했다.
  - [x] 장중 실측용 비율 지표
    (`quote_success_rate`, `filter_pass_rate`, `scored_capture_rate`)를 추가해
    운영자가 raw count를 직접 계산하지 않고도 seed 품질을 즉시 판단할 수 있게 했다.
  - [x] preview API와 `UniverseSelectionService.compose_with_diagnostics()` 테스트에
    위 계측 필드를 고정했다.

---

## P2 — 정책/전략 계층의 구조화 작업

이 범주는 당장 운영 장애보다 덜 급하지만, 시스템을 “작동하는 도구”에서 “확장 가능한 트레이딩 엔진”으로 끌어올리려면 반드시 필요하다.

이 영역은 `plan_docs/agents/01_agent_inventory_and_status.md`에서
**Planned**로 남아 있는 agent 축을 실제 구현 단위로 옮기는 작업이다.

### P2 공통 원칙

`plan_docs/agents/02_agent_target_shapes.md` 기준:

- `Market Regime`, `Strategy Selection`은 hybrid 가능
- `Universe Selection`, `Signal`, `Portfolio`, `Order Construction`은 deterministic backbone이 우선
- `AI Compliance`는 해석 보조일 수 있지만 최종 차단은 deterministic validator가 맡아야 함
- `Model Monitor`는 운영 모니터링/오프라인 평가 서비스로 보는 것이 맞음

### 10. Universe Selection Agent 분해 — `진행중`

### 핵심
- instrument master와 trading universe 분리
- core / held_position / event_overlay / market_overlay 합성
- liquidity filter와 market-driven overlay 정식화

### 세부 작업 상태
- [x] `UniverseSelectionService` 기반 deterministic composition 경로 정착
- [x] `source_type` / `inclusion_reason`를 포함한 trading universe preview inspection API 추가
  - [`plans/2026-06-12_trading_universe_preview_api.md`](./2026-06-12_trading_universe_preview_api.md)
- [x] `source_type`별 decision → order 전환 현황 coverage summary API 추가
  - [`plans/2026-06-13_trading_universe_coverage_summary_api.md`](./2026-06-13_trading_universe_coverage_summary_api.md)
- [x] trading universe preview에 `market_overlay` 진단 정보 추가
  - `enabled/skipped_reason/quotes_requested_count/quotes_received_count/added_count` 등 운영 확인용 수치 노출
- [x] `market_overlay` 전용 funnel inspection API 추가
  - 최근 판단 건수 / 주문 전환 건수 / decision_type 분포 / order_status 분포 / 최근 샘플 확인 가능
  - [`plans/2026-06-14_market_overlay_funnel_api.md`](./2026-06-14_market_overlay_funnel_api.md)
- [x] market_overlay 실운영 편입/효과 장중 실측
  - `evaluate_market_overlay_runtime_validation.py`로 preview/decision/order/bottleneck stage를 1회 평가 가능
  - 결과를 `operations_day_runs.summary_json.market_overlay_runtime_validation`에 적재 가능
  - [`plans/2026-06-14_market_overlay_runtime_validation_cli.md`](./2026-06-14_market_overlay_runtime_validation_cli.md)
- [x] universe selection 결과의 운영 UI 연계
  - 운영 대시보드에 `Universe Selection / Market Overlay` 패널 추가
  - [`plans/2026-06-14_universe_selection_ops_dashboard_panel.md`](./2026-06-14_universe_selection_ops_dashboard_panel.md)
- [x] manual watchlist/override 계층의 운영 정책 확정
  - `manual`은 기본 비활성 / watchlist 용도 / cap·filter·submit gate 우회 없음
  - preview query + decision loop env 기반의 최소 입력 경로 추가
  - [`plans/2026-06-14_manual_watchlist_override_policy.md`](./2026-06-14_manual_watchlist_override_policy.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `28`
- [`plans/[POLICY] trading_universe_policy_v1.md`](./[POLICY]%20trading_universe_policy_v1.md)
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

### 정책 대비 현재 불일치 요약

- 현재 `core universe`는 정책 권고인 `KOSPI100` / 내부 승인 대형주 리스트가 아니라
  `active KRX 전체`를 그대로 사용하고 있다.
- `Operational Eligibility Filter`는 정책 요구 대비 약하다.
  - 현재 공통 필터는 사실상 `unknown/inactive/tick_size` 위주다.
  - `iscd_stat_cls_code`, `low volume`, 운영 금지 리스트, 브로커 미지원, 정보 불완전 차단이
    공통 계층으로 닫혀 있지 않다.
- 정책상 강제 포함 대상인
  `미체결/정합성 확인 필요 주문`, `reconcile_required`, `recent_order_context`
  계층이 아직 universe composition에 반영되지 않았다.
- `market_overlay`는 정책상 “core 밖의 장중 강한 흐름 종목 탐지” 역할이어야 하나,
  현재 구현은 `core pre-pool` 내부 quote 평가에 가깝다.
- `inclusion_reason=kospi200_core`는 실제 구현(`KRX active core`)과 불일치한다.

### 우선순위별 수정안

#### 10-a. Core Universe 정의를 정책 기준으로 축소/명시화 — `완료`

- 목표
  - `core universe`를 `KRX active 전체`에서 분리한다.
  - v1 정책대로 `KOSPI100` 또는 `내부 승인 대형주 리스트`를 authoritative source로 만든다.
- 수정 방향
  - instrument master 적재 시 `KOSPI/KOSDAQ/segment` 구분값을 보존한다.
  - `UniverseSelectionService._add_core_universe()`는
    `market_code='KRX'` 전체 조회 대신
    `core watchlist` 또는 `segment + 시가총액/유동성 기준` 조회로 교체한다.
  - `INCLUSION_REASON_CORE`는 실제 구현과 일치하는 명칭으로 정리한다.
- 이번 작업 반영
  - `active KRX 전체` 대신 코드 관리형 `approved core universe seed` allowlist를 도입했다.
  - `INCLUSION_REASON_CORE`를 `approved_core_universe`로 변경했다.
  - `market_overlay` pre-pool도 동일한 core seed 기준으로만 구성되도록 맞췄다.
- 잔여 보완
  - 현재는 `segment`/`index_memberships` 정식 컬럼 또는 membership table이 없어
    allowlist 기반 운영 구현이다.
  - 후속으로 instrument master에
    `exchange_code`, `market_segment`, `index_memberships`
    authoritative source를 정식 적재해
    정책 테이블/DB authoritative source로 대체해야 한다.
- 우선순위 이유
  - 현재 `000227` 같은 저유동성/우선주가 `core`로 들어오는 가장 근본 원인이다.
  - universe 상류를 먼저 좁혀야 downstream trigger / AI / execution이 불필요하게 소모되지 않는다.

#### 10-b. 공통 Operational Eligibility Filter 강화 — `완료`

- 목표
  - 정책의 Layer 2를 universe 공통 deterministic pre-gate로 승격한다.
- 수정 방향
  - `core/event/manual/market` 전 계층에 동일하게 적용되는 공통 eligibility 필터 추가
  - 포함 항목
    - 거래정지/관리/감리/투자경고 계열 상태 차단
    - 내부 운영 금지 리스트 차단
    - 브로커 미지원/주문 불가 상품 차단
    - 종목 메타데이터 불완전 차단
    - 초저유동성/우선주/특수 share class 차단 여부를 정책으로 명시
  - 현재 `market_overlay` 전용인 `F4/F5` 중 공통화 가능한 부분은 universe 공통 계층으로 이동
- 이번 작업 반영
  - 공통 eligibility에 다음 항목을 추가했다.
    - `market != KRX` 차단
    - `asset_class != kr_stock` 차단
    - `exclude_from_trading_universe=true` metadata 차단
    - `broker_supported=false` metadata 차단
    - `instrument_complete=false` metadata 차단
    - `6자리 숫자 symbol`이 아닌 비표준 symbol 차단
    - 우선주/특수주 명칭 패턴 차단
  - 다만 `held_position`은 관리 대상 강제 포함 원칙 때문에 공통 필터를 우회하도록 유지했다.
- 잔여 보완
  - `iscd_stat_cls_code` 등 브로커 상태값의 공통 적격성 계층 승격은
    snapshot/quote 기반 데이터 결합 설계와 함께 추가 정리 필요하다.
- 우선순위 이유
  - `core`를 바로 못 바꾸더라도, execution 부적합 종목을 universe 단계에서 먼저 제거할 수 있다.
  - 저유동성 종목이 판단/주문까지 내려오는 구조적 누수를 줄이는 데 가장 즉효다.

#### 10-c. 정합성/미체결 관리 대상 강제 포함 계층 추가 — `완료`

- 목표
  - 정책상 강제 포함 대상인 `reconcile_required`, 미체결 관리, lineage 점검 종목을
    universe authoritative source에 포함한다.
- 수정 방향
  - 신규 source_type 후보
    - `order_context`
    - 또는 `reconciliation_overlay`
  - 포함 대상
    - open order 존재 종목
    - `reconcile_required` 주문 종목
    - 최근 체결/취소/실패 후 후속 상태 확인이 필요한 종목
  - cap 정책
    - held_position과 동일하게 일반 cap보다 우선 또는 별도 reserve를 둔다.
- 이번 작업 반영
  - `reconciliation_overlay` source type을 추가했다.
  - 다음 대상이 universe에 강제 포함되도록 연결했다.
    - `pending_submit/submitted/acknowledged/partially_filled/cancel_pending/reconcile_required` 등 활성 주문 종목
    - 진행 중 reconciliation run에 링크된 주문 종목
    - active blocking lock이 걸린 symbol
  - `reconciliation_overlay`는 held_position과 동일하게 일반 `max_cap`에서 제외되도록 처리했다.
  - deterministic trigger에서는 `reconciliation_overlay`를 신규 BUY eligibility에서 차단해
    “관리/상태확인 대상”이 신규 진입 후보로 오인되지 않게 했다.
- 잔여 보완
  - `recent_order_context`의 시간창/상태 범위는 아직 최소 구현 수준이다.
  - 후속으로 `최근 취소/실패 후 재확인 대상`, `broker truth pending` 같은 세분 source reason을
    추가 계측하는 작업이 필요하다.
- 우선순위 이유
  - 현재 정책 문서상 필수인데 구현 누락 상태다.
  - unknown state / reconciliation 우선 원칙과 직접 연결된다.

#### 10-d. Event Overlay 확장 및 중요도 정책 정합화 — `완료`

- 목표
  - 현재 `disclosure + severity=high` 단일 경로를 정책 수준으로 확장한다.
- 수정 방향
  - 최근 1~3영업일 의미 있는 공시 범위 반영
  - 내부 이벤트 정책상 우선 관찰 대상 타입 반영
  - `event_type`별 inclusion reason 표준화
  - 필요 시 OpenDART 외 이벤트 source와의 병합 우선순위 정리
- 이번 작업 반영
  - 기존 `disclosure + severity=high` 단일 경로를 확장해,
    정책상 의미 있는 event type taxonomy를 event overlay 승격 기준으로 반영했다.
  - 현재 반영된 주요 type:
    - `disclosure_material`
    - `disclosure_correction`
    - `earnings`
    - `capital_change`
    - `governance`
    - `trading_halt`
    - `investment_warning`
    - `management_issue`
    - `macro_release`
    - `sector_policy`
    - `broker_report_change`
    - `news_breaking`
  - legacy 저장값도 같이 흡수하도록 alias를 추가했다.
    - `disclosure`, `Y|disclosure`, `K|disclosure`, `N|disclosure`
      → `disclosure_material`
    - `seeded_news`, `Y|seeded_news`, `N|seeded_news`
      → `news_breaking`
  - severity만 보지 않고 `metadata.importance`도 함께 반영해,
    seeded news처럼 기본 severity가 `medium`인 소스도 중요도 승격 시
    event overlay에 편입될 수 있도록 맞췄다.
  - inclusion reason은 `high_importance_event:<normalized_event_type>` 형식으로 표준화했다.
- 잔여 보완
  - 현재는 repository contract 제약상 `list_by_type()` exact match 기반 구현이다.
  - 후속으로 `external_events` recent scan/query contract를 추가하면
    더 다양한 공시 subtype과 source를 한 번에 흡수하는 방향으로 개선할 수 있다.
- 우선순위 이유
  - 현재 event overlay가 지나치게 좁아 정책 문서의 전략 relevance filter 역할을 충분히 못 한다.

#### 10-e. Market Overlay를 “core pre-pool scoring”에서 “시장 발굴 overlay”로 재정의 — `완료`

- 목표
  - 정책의 Layer 4 의도대로, core 밖의 장중 강한 흐름 종목을 동적으로 편입한다.
- 수정 방향
  - KIS 순위분석/동급 랭킹 기반 seed pool 확보
  - 현재의 `core pre-pool -> quote batch` 경로는 보조 경로로 격하하거나 fallback으로 유지
  - `quotes_requested_count / received_count / filtered_out_count` 외에
    `seed_pool_source`, `seed_pool_count`, `overlay_capture_rate`를 추가 계측
- 이번 작업 반영
  - KIS REST client에 실전 전용 랭킹 seed helper를 추가했다.
    - `ranking_volume` (`FHPST01710000`)
    - `ranking_volume_power` (`FHPST01680000`)
  - `market_overlay`는 우선 `KIS ranking`에서 seed symbol을 수집하고,
    seed가 비었을 때만 `approved core universe` fallback pre-pool을 사용하도록 변경했다.
  - ranking/core 어느 경로로 오더라도 quote batch 전 단계에서
    universe 공통 eligibility를 다시 적용해 비표준/비지원/운영제외 종목을 미리 제거하도록 맞췄다.
  - trading universe preview 진단 정보에 다음 필드를 추가했다.
    - `seed_pool_source`
    - `seed_pool_count`
    - `overlay_capture_rate`
- 잔여 보완
  - 현재 ranking seed는 `거래대금 상위 + 체결강도 상위` 2개 소스만 사용한다.
  - 후속으로 `등락률 순위`, 시간대별 pacing, seed cache, overlay source별 품질 실측을 추가해
    실제 alpha discovery 품질을 더 정교화해야 한다.
- 우선순위 이유
  - 현재 구조는 정책 문서의 “market-driven alpha 후보 발굴”과 다르다.
  - 기대수익률 최대화 관점에서도 `market overlay`는 core 내부 재정렬이 아니라
    별도 alpha discovery lane이어야 한다.

#### 10-f. Universe 우선순위와 cap 정책의 source별 reserve 정교화 — `완료`

- 목표
  - held / reconciliation / event / market / manual / core 간 예산 충돌을 줄인다.
- 수정 방향
  - `core_cap` 외에
    - `event_overlay_cap`
    - `market_overlay_cap`
    - `reconciliation_overlay_reserve`
    같은 source별 reserve 검토
  - 시장 과열 구간에서 `market_overlay`가 `core/event`를 과도하게 침범하지 않도록 명시적 상한 정리
- 이번 작업 반영
  - `CompositionContext`에 다음 source-aware cap/reserve 필드를 추가했다.
    - `event_overlay_cap`
    - `reconciliation_overlay_reserve`
  - `market_overlay_cap`은 이미 overlay 생성 단계에서 적용되고 있으므로,
    이번 작업에서는 universe 최종 cap 단계와 충돌하지 않도록 현행 구조를 유지했다.
  - `UniverseSelectionService._apply_cap()`에 다음 규칙을 반영했다.
    - `held_position`은 계속 일반 `max_cap`에서 제외
    - `reconciliation_overlay`는 `reconciliation_overlay_reserve` 범위까지는
      일반 `max_cap`에서 제외
    - reserve를 초과한 `reconciliation_overlay`부터는 일반 `max_cap`을 소비
    - `event_overlay_cap`이 설정되면 event source가 해당 상한을 넘지 않도록 제한
    - 기존 `core_cap`은 그대로 유지
- 잔여 보완
  - 현재 `seen` 구조는 symbol당 최고 우선순위 source 하나만 유지하므로,
    `event_overlay_cap`에 의해 제외된 symbol이 자동으로 `core`로 복귀하지는 않는다.
  - 후속으로 “동일 symbol의 fallback source 복원”이 필요하면
    단일 `seen` 맵이 아니라 multi-candidate staging 구조로 바꿔야 한다.
- 우선순위 이유
  - 현재는 `core_cap`만 있고 나머지는 상대적으로 느슨하다.
  - source별 목표 역할을 유지하려면 cap도 source-aware 해야 한다.

### 권장 구현 순서

1. `10-a` core universe 재정의
2. `10-b` 공통 eligibility filter 강화
3. `10-c` 정합성/미체결 강제 포함 계층 추가
4. `10-e` market overlay sourcing 재정의
5. `10-d` event overlay 확장
6. `10-f` source별 reserve/cap 정교화

### 구현 메모

- `10-a`와 `10-b`는 별도 작업으로 분리하지 말고 함께 설계하는 것이 좋다.
  - core를 좁히는 기준 자체가 eligibility 정책과 맞물리기 때문이다.
- `10-c`는 execution/reconciliation 경계와 직접 연결되므로
  universe selection 단독 작업이 아니라 order/reconciliation 문맥과 같이 검증해야 한다.
- `10-e`는 KIS rate limit / market data budget 제약과 함께 설계해야 하며,
  paper 환경에서는 pacing/seed pool 축소/캐시 전략을 반드시 동반해야 한다.

---

### 11. Signal Agent 분해 — `진행중`

### 핵심
- 기술/수급/모멘텀/변동성 점수의 deterministic backbone 구축
- fast/slow layer score 분리
- 최근 `n개월` 시세를 기반으로 한 기술지표/추세 feature를 장전 판단 입력으로 정착

### 추가 구현 메모
- 장중에 원시 시세를 길게 AI에 넣는 대신, 새벽 또는 장후 배치로 최근 `n개월` 시세를 수치 feature로 미리 계산해 DB에 저장한다.
- 예시 feature:
  - 이동평균(5/20/60/120)
  - 이격도
  - RSI
  - ATR
  - 변동성 percentile
  - 기간 수익률(`1M/3M/6M`)
  - 거래량/거래대금 급증률
- 장 시작 전 decision loop / AI 판단은 이 구조화 수치를 읽어서 사용하도록 한다.
- 목적:
  - AI prompt 토큰 사용량 절감
  - 장중 계산 부하 감소
  - replay/backtest 가능한 deterministic signal backbone 강화
- 구조 리팩토링 관점에서 남은 핵심은
  `feature를 prompt input으로만 쓰는 상태`에서
  `deterministic trigger / candidate 생성 계층`으로 승격하는 것이다.
  관련 분석은
  [`plans/[ANALYSIS] expected_return_architecture_refactor_analysis.md`](./%5BANALYSIS%5D%20expected_return_architecture_refactor_analysis.md)
  를 기준 문서로 사용한다.
- 다음 설계/구현 기준은
  [`plans/[DESIGN] deterministic_trigger_engine_v1.md`](./%5BDESIGN%5D%20deterministic_trigger_engine_v1.md)
  이다.

### 추가 우선 반영 항목

#### 11-a. 상대 거래량/거래대금 급증률 feature의 deterministic 승격 — `완료`

- 배경
  - 절대 거래대금 상위만으로는 이미 큰 종목 위주로 후보가 고정되기 쉽고,
    장중에 새로 강해지는 종목을 늦게 포착한다.
- 반영 방향
  - 기존 `거래량 급증률`을 단순 참고 feature가 아니라
    `WATCH / BUY_CANDIDATE` 생성의 핵심 deterministic backbone으로 승격한다.
  - 우선 도입 대상
    - `당일 거래량 / 최근 20일 평균 거래량`
    - `당일 거래대금 / 최근 20일 평균 거래대금`
    - 필요 시 `체결강도`, `단기 수익률`, `변동성 조정 점수`와 결합
  - 적용 위치
    - `signal_feature_snapshot` 장후/새벽 배치 계산
    - `deterministic_trigger_engine`의 eligibility / ranking / top-k candidate projection
- 이번 작업 반영
  - `signal_feature_snapshot`에 다음 필드를 추가했다.
    - `average_turnover_20d`
    - `turnover_surge_ratio`
  - signal backbone 계산 시
    - `최근 20일 평균 거래대금`
    - `당일 거래대금 / 최근 20일 평균 거래대금`
    을 함께 계산하도록 보강했다.
  - `volume_confirmation` 점수는 이제
    `volume_surge_ratio`와 `turnover_surge_ratio`를 함께 반영한다.
  - `deterministic_trigger_engine`의 BUY eligibility에
    `eligibility_low_relative_activity` 차단을 추가해
    상대 활동성이 너무 낮은 종목은 신규 진입 후보에서 제외하도록 했다.
  - `deterministic_trigger_engine`의 entry/ranking score에
    relative activity bonus를 추가해
    거래량/거래대금 급증 종목이 `WATCH / BUY_CANDIDATE` 상단으로 더 빨리 올라오도록 맞췄다.
  - inspection/API에도 신규 필드를 노출하도록 연결했다.
- 잔여 보완
  - 현재는 일봉 배치 기준의 상대 급증률만 반영했다.
  - 후속으로 live quote의 `acml_vol`, `acml_tr_pbmn`과 결합한
    장중 intraday relative activity 계측/랭킹으로 확장할 필요가 있다.
- 우선순위 이유
  - 기대수익률 관점에서 가장 직접적인 개선축이며,
    universe를 무리하게 넓히지 않고도 “새로 주도주가 되는 종목”을 조기 포착할 수 있다.
  - 현재 진행 중인 `Signal Agent 분해` 및 `feature 기반 deterministic trigger` 강화와
    정확히 같은 방향의 작업이다.

#### 11-b. Market Discovery Pool의 조건부 확장 준비 — `완료`

- 배경
  - 정책 문서상 `market-driven overlay`는 core 밖의 하이알파 후보 탐지가 목적이며,
    장기적으로는 KOSDAQ/중소형 성장주까지 탐색 범위를 넓힐 필요가 있다.
- 반영 방향
  - 즉시 주문 universe를 넓히는 것이 아니라,
    `탐색 풀`과 `주문 가능 풀`을 분리하는 구조를 우선 유지한다.
  - 후속으로 instrument master에 `KOSPI/KOSDAQ/segment`를 정식 적재한 뒤,
    `market discovery seed pool`에 한해 다음 후보군을 단계적으로 편입 검토한다.
    - `KOSDAQ 150`
    - `거래대금 상위 후보군`
  - 단, 편입 조건은 공통 eligibility와 별도 liquidity gate를 통과하는 경우로 제한한다.
- 이번 작업 반영
  - `UniverseSelectionService`에 `market discovery seed pool` 판단 helper를 추가했다.
  - 현재는 다음 metadata가 있는 경우에 한해
    core seed 외 종목도 `market_overlay` fallback seed 후보로 편입될 수 있도록 준비했다.
    - `market_discovery_pool=true`
    - `market_segment` / `segment` / `universe_segment` in
      `KOSPI100`, `KOSDAQ150`, `KOSPI_LARGE`, `KOSDAQ_GROWTH`
  - 이 경로는 `market_overlay`의 fallback seed pool에만 적용되며,
    `core universe`나 즉시 주문 가능 풀을 직접 넓히지는 않는다.
  - 즉, 현재 단계에서는 “탐색 범위 확장 준비”만 반영하고,
    주문/판단 안정성 경계는 유지했다.
- 우선순위 이유
  - KOSDAQ/중소형 탐색 자체는 기대수익률 확대 여지가 있지만,
    현재 단계에서 곧바로 주문 universe까지 넓히면 체결 리스크와 운영 복잡도가 더 빨리 커진다.
  - 따라서 `feature 기반 ranking backbone` 정교화 이후의 차상위 과제로 두는 것이 합리적이다.

#### 11-c. 기대수익률 중심 보유기간 / Churn 제어 리팩토링 — `진행중`

- 배경
  - 장중 실측 기준 일부 종목에서
    `BUY -> REDUCE/SELL -> BUY -> REDUCE/SELL`이
    짧은 간격으로 반복되는 churn 패턴이 확인됐다.
  - 특히 `reconciliation_overlay`와 `held_position`이
    동일 종목에서 번갈아 진입/축소를 정당화하는 구조는
    `최고 기대수익률`보다 거래비용과 노이즈를 키울 가능성이 높다.
- 설계 기준 문서
  - [`plans/[DESIGN] expected_return_holding_horizon_and_churn_control_refactor.md`](./%5BDESIGN%5D%20expected_return_holding_horizon_and_churn_control_refactor.md)
- 핵심 방향
  - `source_type`를 단순 label이 아니라
    `허용 action envelope`로 승격한다.
  - `reconciliation_overlay`는
    flat 상태 신규 BUY source가 아니라
    상태 관리/관찰 source로 제한한다.
  - actionable decision은
    `expected_return_bps`, `net_expected_value_bps`,
    `final_trade_score`, `minimum_required_edge_bps`
    를 갖는 `expected value anchor`를 필수로 한다.
  - 동일 종목의 `SELL/REDUCE -> BUY`,
    `BUY -> REDUCE/SELL`에는
    `cooldown + feature/event 변화 + edge 개선`을 함께 요구하는
    hysteresis를 도입한다.
  - `1주 시장가 probe`가 churn을 만드는 조합은
    submit 전 hard guard로 차단한다.
- 세부 작업 상태
  - [x] `reconciliation_overlay` flat 신규 BUY 전면 차단
  - [x] pre-submit 잔존 주문이 `reconciliation_overlay`로 오인 편입되는 경로 차단
    - `DRAFT`, `VALIDATED`, `PENDING_SUBMIT` 상태는
      장중 active overlay source에서 제외했다.
    - prior-day `DAY + PARTIALLY_FILLED + SELL` 잔존은
      현재 보유 수량이 0이면
      universe compose 단계에서 stale residual로 건너뛴다.
    - after-hours post-submit sync에서
      위 residual 주문을 `expired`로 terminalize 하는 경로를 추가했다.
  - [x] `services.source_policy` action envelope helper 추가
  - [x] actionable decision의 expected value 필수 anchor 강제
    - `services.expected_value_gate`를 추가해
      actionable decision에 대한
      `expected_return_bps`, `expected_downside_bps`,
      `net_expected_value_bps`, `final_trade_score`,
      `minimum_required_edge_bps` 1차 anchor를 공통 계산하도록 정리했다.
    - `AIDecisionInputs`에 expected value 필드와
      `expected_value_gate_passed`, `expected_value_gate_reason_codes`
      계약을 추가했다.
    - `decision_factory`가 위 필드를
      `trade_decisions` row와 `decision_json.expected_value_gate`
      에 함께 저장하도록 반영했다.
    - `build_submit_order_request_from_decision()`는
      actionable decision이라도 expected value anchor가 비어 있거나
      gate가 false이면 submit request를 만들지 않도록 강제했다.
  - [x] `edge_after_cost_bps` 계산/저장 경로 추가
    - `services.expected_value_gate`가
      `estimated_round_trip_cost_bps`,
      `slippage_buffer_bps`,
      `edge_after_cost_bps`
      를 1차 deterministic 규칙으로 계산하고,
      `edge_after_cost_bps < minimum_required_edge_bps`
      인 actionable decision은 gate를 false로 내리도록 연결했다.
    - `AIDecisionInputs`와 pre-AI short-circuit / subprocess fallback 경로에도
      위 세 필드를 함께 주입해,
      AI 경로와 deterministic fallback 경로의 contract를 맞췄다.
    - `decision_json.expected_value_gate`에
      after-cost edge와 비용 추정 필드를 저장하고,
      submit translation은 해당 필드가 비어 있으면
      actionable request를 생성하지 않도록 강화했다.
  - [x] same-symbol reentry cooldown 1차 추가
    - `pre_ai_gate`에
      `same_symbol_reentry_cooldown`을 추가해,
      `core/event_overlay/market_overlay`의
      no-position 신규 BUY 후보가
      최근 `SELL/REDUCE/EXIT` 주문 직후에는
      AI 호출 전 deterministic하게 차단되도록 반영했다.
    - 최근 sell order 수,
      직전 held-position sell decision type/시각,
      직전 anchored position quantity,
      직전 `signal_feature_snapshot_id`
      를 details로 함께 남겨
      이후 `signal_feature_snapshot_id` 변화 기반 hysteresis 확장에
      바로 이어질 수 있게 했다.
  - [x] BUY 직후 SELL/REDUCE cooldown 1차 추가
    - `services.pre_ai_gate.evaluate_held_position_skip_reason()`에
      최근 same-symbol BUY order + 최근 same-symbol BUY/APPROVE 판단 +
      보유수량 감소 없음 조건을 추가해,
      조기 `held_position` 위험축소 SELL 경로를
      `held_position_recent_buy_sell_cooldown`으로 pre-AI skip 하도록 반영했다.
    - 최근 buy order 수,
      직전 buy decision type/시각,
      직전 anchored position quantity,
      직전 `signal_feature_snapshot_id`
      를 details에 함께 남겨,
      다음 단계의 `signal_feature_snapshot_id` 불변 reverse-trade 차단과
      자연스럽게 이어지도록 정리했다.
  - [x] `signal_feature_snapshot_id` 불변 상태 reverse trade 차단
    - `services.pre_ai_gate`가 현재 종목의 최신
      `signal_feature_snapshot_id`를 조회해,
      직전 BUY/SELL 판단에 앵커된
      `signal_feature_snapshot_id`와 동일하면
      일반 cooldown 대신
      `reverse_trade_same_signal_feature_snapshot`
      reason code로 pre-AI 차단하도록 반영했다.
    - `BUY -> SELL/REDUCE`와
      `SELL/REDUCE -> BUY`
      두 방향 모두에 대해
      `current_signal_feature_snapshot_id`,
      직전 anchor id,
      unchanged 여부를 details에 남겨
      이후 `event novelty` / `edge_after_cost_bps` 개선 조건 추가 시
      그대로 재사용할 수 있게 정리했다.
  - [x] `quantity=1` 신규 BUY probe churn guard 추가
    - `services.execution_service`에
      `execution_probe_churn_guard_v1`를 추가해,
      최종 submit 직전
      `quantity=1` 신규 BUY를
      일반 규칙이 아니라 예외 규칙으로만 허용하도록 반영했다.
    - `reconciliation_overlay + BUY + quantity=1`은
      `overlay_single_share_buy_blocked`,
      최근 same-symbol SELL 직후 1주 BUY는
      `reverse_trade_single_share_blocked`,
      저가치/고변동 risk-off 1주 BUY는
      `probe_churn_single_share_blocked`
      으로 guardrail audit까지 남기도록 정리했다.
    - `core/event_overlay`의
      `edge_after_cost_bps >= 35`
      는 1차 high-edge 예외 규칙으로 허용해
      핵심 기대수익률 기회까지 같이 막지 않도록 했다.
  - [x] `symbol_trade_states` 테이블 설계/도입
    - 신규 migration
      `db/migrations/0044_add_symbol_trade_states.sql`
      를 추가해,
      `account_id + instrument_id` 기준
      심볼 단위 authoritative 상태 캐시 테이블을 도입했다.
    - 저장 컬럼은
      `state`, `holding_profile`, `position_quantity`,
      `last_entry/exit/reduce_at`,
      `minimum_hold_until`,
      `reentry_cooldown_until`,
      `sell_cooldown_until`,
      `last_signal_feature_snapshot_id`,
      `last_decision_context_id`,
      `last_reason_codes`,
      `thesis_state_hash`,
      `metadata_json`
      까지 포함해
      다음 단계의 holding-profile 저장 경로를 바로 연결할 수 있게 준비했다.
    - repository 계층에도
      `SymbolTradeStateEntity`,
      `SymbolTradeStateRepository`,
      in-memory / postgres 구현,
      repository container wiring을 반영했다.
  - [x] `holding_profile`, `minimum_hold_until`,
    `reentry_cooldown_until` 저장 경로 추가
    - 신규 helper
      `services/holding_profile_policy.py`
      를 추가해
      `source_type + decision_type + time_horizon`
      기준으로
      `event_probe / event_swing / core_swing / position_trade / risk_reduction_only`
      프로필과
      `minimum_hold_until`,
      `sell_cooldown_until`,
      `reentry_cooldown_until`,
      `thesis_state_hash`
      를 결정론적으로 계산하도록 반영했다.
    - `build_trade_decision_entity()`가
      `decision_json.holding_profile_policy`
      에 해당 정책을 저장하도록 보강해
      replay / audit 시
      당시 보유기간 의도와 cooldown anchor를 같이 추적할 수 있게 했다.
    - `DecisionOrchestratorService._ensure_trade_decision()` 이후
      `symbol_trade_states`
      에
      `holding_profile`,
      `minimum_hold_until`,
      `reentry_cooldown_until`,
      `sell_cooldown_until`
      및 `entry_pending / reduce_pending / exit_pending`
      상태를 저장하도록 연결했다.
    - `assemble()`가
      `SubmitOrderRequest.metadata.holding_profile_policy`
      를 함께 실어 보내고,
      `ExecutionService`는 주문 생성 후
      `last_entry_order_request_id / last_exit_order_request_id`
      까지 `symbol_trade_states`에 연결하도록 반영했다.
  - [x] AI override 허용 범위를
    `eligibility + expected value + symbol state` 통과 시로 축소
    - `DecisionOrchestratorService._check_ai_buy_override_gate()`를 추가해
      deterministic trigger가 `buy_candidate=False`인 상황에서
      AI가 `APPROVE/BUY`로 승격하려면
      `eligibility_passed=True`,
      `expected_value_gate_passed=True`,
      `source_type` action envelope 허용,
      `symbol_trade_states`의 pending state 부재,
      `reentry_cooldown_until` 만료
      조건을 모두 통과하도록 강제했다.
    - 실행 infeasible 성격의 eligibility reason
      (`eligibility_low_average_volume`,
      `eligibility_low_turnover`,
      `eligibility_participation_rate_blocked`)
      이 남아 있으면
      AI override를 `WATCH/HOLD`로 강등하도록 연결했다.
    - 관련 테스트로
      `market_overlay`의 정상 override 허용 케이스와
      `symbol_trade_state reentry cooldown` 차단 케이스를 추가해
      override가 기대수익률 anchor와 상태기계 제약을 동시에 따르도록 고정했다.
- 우선순위 이유
  - 현재의 짧은 보유기간은
    의도된 단기 전략 결과라기보다
    `심볼 상태 기억 부재`와 `충돌하는 source`의 결과일 가능성이 높다.
  - 이 항목은 단순 threshold 조정보다
    기대수익률 개선에 직접적인 리팩토링 축이다.

### 세부 작업 상태
- [x] 순수 helper 기반 deterministic signal backbone 1차 추가
  - `services.signal_backbone`에 `PriceBar` / `TechnicalFeatureSnapshot` / `SignalScoreCard` 추가
  - 최근 일봉 기준 `SMA(5/20/60)`, `1M/3M 수익률`, `RSI(14)`, `ATR(14)%`, `20일 변동성`, `거래량 급증률` 계산
  - fast/slow layer 분리 score(`fast_score`, `slow_score`, `overall_score`)와 reason code 1차 규칙 추가
- [x] feature snapshot DB 저장 기반 1차 추가
  - `trading.signal_feature_snapshots` 테이블 migration 추가
  - `SignalFeatureSnapshotEntity` / repository contract / in-memory / Postgres 저장소 추가
  - 최신 snapshot 조회(`get_latest_by_instrument`) 및 이력 조회(`list_by_instrument`) 경로 추가
- [x] signal feature snapshot inspection API 추가
  - `GET /signal-feature-snapshots`
  - `GET /signal-feature-snapshots/latest`
  - 종목(`symbol + market + timeframe`) 기준으로 최신/이력 snapshot 조회 가능
- [x] 새벽/장후 배치 계산 경로
  - `SignalFeaturePipelineService` 추가
  - `build_signal_feature_snapshots.py` CLI로 JSON 일봉 입력 기반 계산/적재 가능
- [x] decision loop / AI prompt read-only 주입 경로
  - `DecisionOrchestratorService.assemble()`가 최신 `signal_feature_snapshot`을 로드
  - AI Risk / FDC prompt에 fast/slow/overall score, RSI, ATR, 수익률, reason code를 read-only로 주입
- [x] deterministic trigger / candidate 계층 1차 추가
  - `services.deterministic_trigger_engine`에 `DeterministicTriggerAssessment`,
    `assess_deterministic_triggers()` 추가
  - `signal_feature_snapshot + market_regime + strategy_selection + portfolio_allocation`
    기반으로 `WATCH / BUY_CANDIDATE / SELL_CANDIDATE / REDUCE_CANDIDATE`
    후보를 deterministic하게 생성
  - `AssembledContext.deterministic_trigger`에 주입하고
    AI Risk / FDC prompt에 read-only로 노출
  - `TradeDecisionEntity.decision_json.deterministic_trigger`에 1차 반영
- [x] candidate vs final decision 분리 저장 1차 추가
  - `TradeDecisionEntity.decision_json.candidate_vs_final`에
    `candidate_intent`, `final_intent`, `alignment_status`, `override_applied`
    를 기록해 deterministic candidate와 AI 최종 판단의 차이를 구조화
  - 향후 `override 효과 측정`, `candidate 분포 대비 최종 decision 분포 비교`의
    최소 분석 기반 확보
- [x] deterministic derivation stage 분리 1차 추가
  - `DecisionOrchestratorService` 내부에서
    `signal_feature_snapshot → market_regime → strategy_selection → portfolio_allocation → deterministic_trigger`
    계산을 `_derive_deterministic_context_components()` helper로 분리
  - 향후 `Context Assembly Stage` / `Deterministic Derivation Stage` /
    `AI Policy Stage` 분리의 첫 단계 구조 정리
- [x] prompt context projection 공통화 1차 추가
  - `services.ai_agents.prompt_context_projection`에
    signal / regime / strategy / portfolio / trigger 공통 렌더링 helper 추가
  - `Final Decision Composer`는 전체 deterministic context section을 공통 helper로 재사용
  - `AI Risk`는 별도 concentration 문맥을 유지하기 위해
    portfolio section만 제외한 공통 projection 경로를 사용
- [x] AI policy context view 분리 1차 추가
  - `AIPolicyContextView`를 추가해
    내부 조립용 `AssembledContext`와 AI 입력용 읽기 전용 뷰를 분리
  - `DecisionOrchestratorService`가
    `_build_ai_policy_context_view()`로 AI 입력 뷰를 명시적으로 조립한 뒤
    in-process / subprocess agent runner에 동일하게 전달
  - 향후 `policy input schema versioning`, `attribution`, `prompt contract 고정`
    작업의 최소 구조 경계 확보
- [x] after-market signal feature batch 자동화 1차 추가
  - `ops-scheduler`가 장 마감 후 배치 시각인 `20:10 KST` 이후
    `signal feature input 생성 → snapshot batch 적재`를 순차 실행
  - `generate_signal_feature_snapshot_input.py`가
    trading universe 기준 KIS 일봉을 조회해
    `data/signal_feature_snapshot_input.json`을 생성
  - `build_signal_feature_snapshots.py`가 같은 입력 파일을 읽어
    `signal_feature_snapshots` 테이블 적재를 수행
- [x] signal feature batch 운영 요약 노출 1차 추가
  - `operations_day_runs.summary_json`에
    `signal_feature_input` / `signal_feature_batch`의
    `last_error`, 입력 생성 집계(`universe_count`, `generated_count`, `error_count`)를 기록
  - `/market-sessions/operations-day/*` API에서 기존 `summary_json` 경로만으로
    장후 feature 배치 실패 원인을 바로 확인할 수 있게 정리
- [x] ops-scheduler runtime 식별 정보 노출 1차 추가
  - `operations_day_runs.summary_json.scheduler_runtime`에
    `script_path`, `python_bin`, `pid`,
    `signal_feature_batch_supported`, `signal_feature_batch_time`를 기록
  - 운영 중인 scheduler 프로세스가
    실제로 signal feature batch 지원 코드를 로드했는지
    DB 요약만으로 즉시 식별할 수 있게 정리
- [x] signal feature batch 적재 runtime bug 수정 및 전일 누락분 수동 적재
  - `build_signal_feature_snapshots.py`가
    `postgres_runtime()`의 `repositories` 경로를 직접 사용하도록 수정해
    운영 컨테이너에서 `db_pool` KeyError로 실패하던 문제를 제거
  - 전일(`2026-06-16`) 장후 누락분은
    `generate_signal_feature_snapshot_input.py` 수동 실행 후
    `signal_feature_snapshots`에 47건 적재까지 완료
  - 자동 배치 정상 동작 여부는
    오늘 `20:10 KST` 이후 `operations_day_runs.summary_json`과
    `signal_feature_snapshots` 적재 건수로 재확인 필요
- [x] signal feature after-market 배치 운영 안정화 / 리팩토링 2차
  - 배경
    - 2026-06-18~2026-06-19 실측 기준
      `signal_feature_snapshot` 장후 배치는
      `input import 실패`, `schema drift`, `거래대금 overflow`,
      `개별 row 실패가 batch 전체 transaction을 오염시키는 구조`
      문제를 순차적으로 드러냈다.
    - 현재는 hotfix와 수동 검증으로
      `배치 전체 붕괴` 가능성은 낮아졌지만,
      외부 KIS live 시세/일봉 API의 rate limit / 5xx 때문에
      일부 종목 누락 가능성은 여전히 남아 있다.
  - 권장 방향
    - 단순 retry 증설보다
      `universe freeze -> fetch stage -> persist stage -> failed-symbol tail-retry`
      구조로 리팩토링해
      운영 안정성, audit, replay, manual recovery를 함께 확보한다.
  - `P0`
    - [x] 장후 `20:10 KST` 배치의 대상 유니버스를 먼저 freeze 하고,
      이후 재시도/재실행 중에도 같은 대상 집합을 유지하도록 만든다.
      - `generate_signal_feature_snapshot_input.py`가
        `universe_freeze_runs` / `universe_freeze_run_items`를 우선 조회해
        기존 freeze가 있으면 재사용하고,
        없으면 새 freeze를 materialize 하도록 반영
    - [x] `universe freeze` PostgreSQL 스키마를 먼저 확정한다.
      - [x] `trading.universe_freeze_runs` 테이블 설계
      - [x] `trading.universe_freeze_run_items` 테이블 설계
      - [x] `signal_feature_batch_runs.universe_freeze_run_id` FK 연결 설계 및 구현
      - [x] `(business_date, freeze_purpose, freeze_sequence)` unique 정책 확정
      - [x] `(freeze_run_id, instrument_id)` unique 정책 확정
      - [x] `business_date`, `freeze_purpose`, `frozen_at`, `selection_version`,
        `selection_params_json`, `target_count`, `status` 필수 컬럼 확정
      - [x] item row의 `instrument_id`, `symbol`, `market_code`,
        `source_type`, `inclusion_reason`, `priority_score`, `rank`,
        `cap_bucket`, `metadata_json` 필수 컬럼 확정
      - [x] replay / manual rerun 시
        `same freeze run reuse`와 `new freeze run create` 기준 확정
    - [x] `signal_feature_snapshot_input` 생성 경로를
      `fetch 성공 row / fetch 실패 row / 대상 universe metadata`로 분리 기록한다.
      - 입력 JSON을 `signal_feature_input.v2` 구조로 확장해
        `universe_metadata`, `fetch_success_rows`, `fetch_error_rows`를 분리 저장
      - `build_signal_feature_snapshots.py`는
        신구 포맷을 모두 읽을 수 있게 backward-compatible 유지
    - [x] `generate_signal_feature_snapshot_input.py`에
      `rate limit`, `5xx`, `timeout`을 구분한 재시도 정책을 추가한다.
    - [x] 1차 본배치 후 실패 종목만 재시도하는
      `tail-retry` 실행 경로를 추가한다.
      - `generate_signal_feature_snapshot_input.py`에
        `--retry-from-input` 경로를 추가해
        기존 `signal_feature_input.v2`의 `fetch_error_rows`만 다시 조회하도록 반영
      - `run_ops_scheduler.py`가
        1차 `after_market_signal_feature_input` 완료 후
        `fetch_error_count > 0`이면
        `after_market_signal_feature_input_tail_retry` →
        `after_market_signal_feature_batch_tail_retry`
        순서로 동일 거래일 tail-retry를 자동 실행
      - 운영 요약은 primary + tail-retry 누적 기준으로
        `fetch_success_count`, `persist_success_count`, `final_missing_count`
        집계를 보도록 보강
    - [x] `operations_day_runs.summary_json`에
      `target_count`, `fetch_success_count`, `fetch_error_count`,
      `persist_success_count`, `persist_error_count`,
      `final_missing_count`, `failed_symbols_sample`
      를 남기도록 확장한다.
  - [x] 장후 실행 후
      `summary_json`과 `signal_feature_snapshots` 적재 건수를 대조하는
      운영 검증 절차를 문서화한다.
      - [`plans/[RUNBOOK] signal_feature_after_market_batch_validation.md`](./%5BRUNBOOK%5D%20signal_feature_after_market_batch_validation.md)
        문서에
        `operations_day_runs.summary_json` →
        `signal_feature_batch_runs` →
        `signal_feature_batch_run_items` →
        `signal_feature_snapshots`
        순서의 운영 판정 절차를 정리했다.
  - `P0-추가`
    - [x] decision loop도 `feature freeze`와 별개로 실시간 compose만 하지 않고,
      `intraday universe freeze`를 우선 anchor로 읽도록 확장한다.
      - 배경:
        현재는 `signal_feature` 장후 배치만
        `universe_freeze_runs` / `universe_freeze_run_items`를 사용하고,
        장중 `run_decision_loop`는 매 cycle마다
        `UniverseSelectionService.compose()`를 다시 호출한다.
        이 구조는 feature/audit/replay 경로와
        실제 장중 판단 경로의 universe 기준이 분리되는 문제가 있다.
      - 목표:
        `decision loop`, `feature batch`, `운영 진단`이
        가능한 한 동일한 universe anchor 개념을 공유하게 만든다.
      - [x] 1차:
        `decision loop intraday freeze` 목적값과 생성 시점을 확정한다.
        - 권장 `freeze_purpose`:
          `decision_loop_intraday`
        - 확정 생성 시점:
          scheduler가 장중 due 상태의 첫 `decision` task를 실행하기 직전
          1회 materialize / reuse
        - 같은 거래일/같은 목적 내에서는
          기존 freeze run 재사용을 기본값으로 한다.
      - [x] 1차:
        `run_decision_loop.py`에
        `latest freeze run 우선 -> compose fallback` read path를 추가한다.
        - `TRADING_UNIVERSE_SYMBOLS` env override는 여전히 최우선 유지
        - 그 다음 `universe_freeze_run_items(decision_loop_intraday)` 조회
        - 마지막 fallback만 `UniverseSelectionService.compose()`
      - [x] 1차:
        freeze 미존재 시 새 freeze를 materialize 할지,
        아니면 compose 결과를 1회성으로만 사용할지 정책을 고정한다.
        - 확정:
          freeze가 없으면 먼저 materialize 한 뒤
          그 결과를 decision loop가 읽는다.
        - 구현:
          `ops-scheduler`가 `decision_submit_gate` 직전에
          기존 freeze reuse를 먼저 시도하고,
          없으면 `UniverseSelectionService.compose()` 결과를
          `universe_freeze_runs` / `universe_freeze_run_items`에 저장한 뒤
          같은 거래일 anchor로 사용한다.
      - [x] 1차:
        decision cycle 요약과 audit 메타데이터에
        `universe_freeze_run_id`, `freeze_purpose`, `freeze_reused`
        를 남긴다.
        - 최소 범위:
          decision loop summary JSON
        - 추가 반영:
          per-symbol cycle JSON에도 같은 anchor를 남긴다.
        - 권장 확장:
          `decision_context` 또는 `trade_decisions.decision_json`
          에도 anchor 기록
        - 구현:
          `run_decision_loop.py`가
          `universe_anchor_source`, `universe_freeze_run_id`,
          `freeze_purpose`, `freeze_reused`를
          cycle result / aggregate summary metrics에 기록하고,
          `SubmitOrderRequest.metadata["universe_anchor"]`를 통해
          `trade_decisions.decision_json.universe_anchor`까지 전파한다.
      - [x] 2차:
        preview/ops API가
        현재 live compose 결과와
        현재 active intraday freeze 결과를 구분해서 보여주도록 확장한다.
        - 구현:
          `GET /instruments/trading-universe/preview` 응답에
          `active_intraday_freeze`,
          `active_intraday_freeze_comparison`를 추가해
          live compose 결과와 같은 거래일의
          `decision_loop_intraday` freeze 결과를 한 번에 비교할 수 있게 한다.
      - [x] 2차:
        재시작/장애 복구 시
        기존 intraday freeze 재사용,
        수동 새 freeze 생성,
        stale freeze 감지 기준을 runbook에 정리한다.
      - 구현:
        [`plans/[RUNBOOK] decision_loop_intraday_freeze_operations.md`](./%5BRUNBOOK%5D%20decision_loop_intraday_freeze_operations.md)
          문서에
          상태 확인 API,
          재기동 후 reuse 절차,
          수동 `ensure`,
          수동 `force-new`,
          hard stale / soft drift 판정 기준을 고정했다.
      - [x] 운영 버그 수정:
        재기동 후 stale `run_date`를 들고 있는 scheduler가
        잘못된 거래일 freeze를 재사용/생성하지 않도록
        intraday freeze materialize 시점에
        현재 `KST` 날짜로 run date를 재결정하게 수정했다.
      - [x] 실운영 검증:
        2026-06-25 장중 기준
        `decision_loop_intraday` freeze를 수동 materialize 한 뒤
        `ops-scheduler` 로그와
        `operations_day_runs.summary_json.decision_loop.metrics`
        에서
        `universe_anchor_source='intraday_freeze'`,
        `freeze_reused=true`,
        `universe_freeze_run_id` 반영까지 확인했다.
      - 구현 범위 고정:
        이번 후속 작업은
        `universe schema 추가`가 아니라
        기존 `universe_freeze_runs` / `universe_freeze_run_items`
        재사용을 전제로 한다.
        신규 핵심 범위는
        `decision loop read path`, `scheduler freeze materialization`,
        `audit anchor propagation`, `ops visibility` 4가지다.
  - `P1`
    - [x] `signal_feature_batch_runs`
      실행 단위 테이블 도입 여부를 확정하고 구현했다.
      - 실행 메타데이터:
        `business_date`, `universe_freeze_run_id`, `trigger_type`,
        `timeframe`, `feature_set_version`, `input_uri`,
        `target_count`, `fetch_success_count`, `fetch_error_count`,
        `persist_success_count`, `persist_error_count`,
        `skipped_count`, `final_missing_count`, `status`, `summary_json`
    - [x] `signal_feature_batch_run_items`
      종목 단위 상태 테이블 도입 여부를 확정하고 구현했다.
      - 종목별 상태:
        `persisted`, `computed`, `error`, `fetch_error`,
        `skipped_instrument_not_found`
      - `signal_feature_snapshot_id`, `snapshot_at`, `error_code`,
        `error_message`, `metadata_json`를 함께 저장
    - [x] file 기반 중간 산출물과 DB run-state 중
      어느 쪽을 authoritative source로 둘지 결정한다.
      - [x] freeze 이후의 authoritative source는
        file이 아니라 `universe_freeze_run_items`를 기본값으로 둔다.
      - [x] 실행 메타데이터 authoritative source는
        `signal_feature_batch_runs` /
        `signal_feature_batch_run_items`로 고정한다.
      - [x] 최종 feature payload authoritative source는
        `signal_feature_snapshots`로 고정한다.
      - [x] JSON 입력 파일은
        transport / tail-retry / 수동 재실행 artifact로만 취급하고
        audit 기준 source로 사용하지 않도록 정책 문서와 runbook에 반영했다.
    - [x] 동일 `(instrument_id, timeframe, snapshot_at, feature_set_version)` 기준
      idempotent re-run / upsert 정책을 확정하고 구현했다.
      - `signal_feature_snapshots`에 natural key unique index를 추가했다.
      - 재실행 시 duplicate insert 대신 동일 natural key row를 update 하도록
        repository `add()`를 upsert로 전환했다.
      - 기존 `signal_feature_snapshot_id`는 유지되고,
        feature payload만 최신 계산값으로 갱신된다.
    - [x] 장중 intraday relative activity 확장 시에도
      같은 batch runtime을 재사용하도록
      공통 orchestration 계층으로 정리한다.
      - `services.signal_feature_batch_runtime`에
        `SignalFeatureBatchRuntimeSpec`와
        tail-retry 판정 helper를 추가해
        `input -> batch -> tail-retry input -> tail-retry batch`
        흐름을 재사용 가능한 runtime spec으로 추출했다.
      - `run_ops_scheduler.py`는
        장후 전용 하드코딩 대신
        `_run_signal_feature_batch_runtime(...)` 공통 실행 경로를 사용하도록 정리했다.
      - `generate_signal_feature_snapshot_input.py`,
        `build_signal_feature_snapshots.py`는
        `freeze_purpose`, `trigger_type`를 명시적으로 주고받아
        향후 intraday relative activity 배치도
        같은 저장 경로와 run-state를 재사용할 수 있게 맞췄다.
  - 선행 완료 항목
    - [x] signal feature input / batch 실행 경로를
      `python3 -m scripts....` 구조로 통일
    - [x] `average_turnover_20d`, `turnover_surge_ratio` schema 반영
    - [x] 대형 거래대금 수용을 위한 DB precision 완화
    - [x] `signal_feature_snapshots.add()` savepoint 적용
    - [x] 수동 실반영 기준 `processed=96`, `persisted=96`, `errors=[]` 검증
- [x] decision context ↔ signal feature snapshot point-in-time anchor 1차 추가
  - `trading.decision_contexts.signal_feature_snapshot_id` nullable FK를 추가해
    실제 판단에 사용한 `signal_feature_snapshot` 식별자를 context에 고정
  - `DecisionOrchestratorService.assemble()`가
    최신 signal snapshot을 로드한 뒤 해당 `decision_context`에
    `signal_feature_snapshot_id`를 attach하도록 보강
  - `GET /decision-contexts/{id}` 응답에
    `signal_feature_snapshot_id`를 노출해
    replay / 운영 점검 시 사용 snapshot 추적 경로를 확보
- [x] signal feature anchor coverage 진단 API 1차 추가
  - `GET /signal-feature-snapshots/decision-context-coverage` 추가
  - 최근 `decision_contexts` 기준
    `recent_context_count`, `anchored_context_count`,
    `missing_context_count`, `coverage_rate`를 집계
  - `sampled_missing_context_ids`를 함께 노출해
    장후 batch 이후 어떤 판단 컨텍스트가 아직 anchor 없이 생성됐는지
    운영 기준으로 즉시 확인 가능하게 정리
- [x] trade decision read-path에 signal feature anchor 노출 1차 추가
  - `GET /trade-decisions` 응답에
    `signal_feature_snapshot_id`를 포함해
    각 판단 row에서 참조한 signal feature snapshot을 직접 확인 가능하게 정리
  - 운영자가 `decision_context` 상세를 별도로 다시 조회하지 않아도
    판단 단위에서 point-in-time feature anchor 추적이 가능하도록 보강
- [x] deterministic candidate vs final decision 진단 API 1차 추가
  - `GET /trade-decisions/candidate-alignment-diagnostics` 추가
  - 최근 의사결정의 `candidate_tracked_count`, `override_applied_count`,
    `matched_count`, `candidate_coverage_rate`, `match_rate`를 집계
  - `alignment_status`, `candidate_intent`, `final_intent` 분포와
    최근 misaligned sample을 함께 노출해
    deterministic trigger가 실제 final decision에서 어떻게 override되는지
    운영 기준으로 즉시 점검 가능하게 정리
- [x] trigger / override execution attribution API 1차 추가
  - `GET /performance-trigger-attribution` 추가
  - 계좌 기준 최근 의사결정의
    `tracked_decision_count`, `actionable_decision_count`,
    `ordered_decision_count`, `filled_decision_count`,
    `decision_to_order_rate`, `decision_to_fill_rate`를 집계
  - `alignment_status` / `candidate_intent` bucket별로
    주문 전환율과 체결 전환율을 함께 노출해
    deterministic trigger와 override가 실제 실행으로 얼마나 이어지는지
    최소 성과 attribution 기반을 마련
- [x] trigger / override performance attribution 설계 문서 1차 추가
  - [`plans/[DESIGN] performance_attribution_for_trigger_and_override.md`](./%5BDESIGN%5D%20performance_attribution_for_trigger_and_override.md)
    문서 추가
  - 현재 구조에서 가능한 `execution attribution`과
    아직 별도 설계가 필요한 `realized pnl attribution`의 경계를 명시
  - 다음 구현 단위를
    `post-decision return proxy attribution`으로 정의해
    복잡한 포지션 close 귀속 이전에 deterministic 성과 관찰 경로를 먼저 여는 방향으로 정리
- [x] deterministic trigger 계측 필드 1차 추가
  - `coverage_score`, `eligibility_passed`, `eligibility_reasons`,
    `ranking_score`, `candidate_mode`를
    `DeterministicTriggerAssessment`와 `decision_json.deterministic_trigger`에 추가
  - projection 변경 전 단계에서
    `WATCH 급증 / BUY_CANDIDATE 부족`이
    eligibility 병목인지 ranking 병목인지 분해 관측 가능한 최소 계측 기반 확보
- [x] decision loop `core_cap` 도입으로 저우선순위 core LLM 부하 완화 1차 적용
  - `max_cap`은 유지하되 `source_type=core`에만 별도 상한(`core_cap`)을 추가해
    held / event / market / manual 우선순위는 유지하면서
    비행동성 core 종목의 장중 assemble 부하를 줄이는 경로를 추가
  - decision loop 기본값은 `core_cap=12`, feature 장후 배치는 별도 `core_cap=80`으로 분리
  - [`plans/[IMPLEMENTATION] 2026-06-18_decision_loop_core_cap.md`](./%5BIMPLEMENTATION%5D%202026-06-18_decision_loop_core_cap.md)
- [x] pre-AI short-circuit 2차 리팩토링
  - 목적
    - 이미 계산된 `deterministic_trigger`와 `recent_events`를 이용해
      `EI -> AR -> FDC` 전부를 호출할 필요가 없는 신규 진입 후보를
      AI 호출 전단에서 더 많이 잘라낸다.
    - 토큰 절감 자체가 목적이 아니라,
      `명백한 비적격 BUY 후보에 대한 불필요한 AI 해석`을 줄여
      기대수익률과 장중 latency를 동시에 개선하는 것이 목적이다.
  - 우선순위
    - [x] `P1-1`: `core` 등 신규 BUY 후보 경로에서
      `eligibility_low_average_volume`, `eligibility_low_turnover`,
      `eligibility_allocation_blocked`, `eligibility_risk_off_block`,
      `eligibility_participation_rate_blocked`가 있는 경우
      EI/AR/FDC 호출 전 `HOLD` 또는 `WATCH`로 조기 종료
    - [x] `P1-2`: `recent_events == 0`이면 EI를 생략하고
      empty structured output으로 downstream을 계속 진행
    - [x] `P1-3`: `primary_candidate == NO_ACTION` 이고 `recent_events == 0`인
      신규 진입 후보에 한해 AR/FDC까지 생략하는 cut-out 적용
    - [x] `P1-4`: AR 결과가 `reject` 또는 고위험 점수면
      FDC 호출을 조건부 생략
  - 이번 반영
    - `DecisionOrchestratorService`에 pre-agent short-circuit을 추가했다.
    - 적용 범위는 우선 `source_type=core` + `실보유 없음` 경로로 제한했다.
    - `P1-1`, `P1-3` 조건에 해당하면 subprocess/in-process 경로에 들어가기 전에
      synthetic `HOLD/WATCH` bundle을 조립해 AI 호출 자체를 생략한다.
    - `DecisionAgentRunner`에 EI conditional skip을 추가했다.
    - `source_type=core` + `실보유 없음` + `deterministic_trigger 존재` + `recent_events=0`
      인 경우 EI provider 호출은 생략하고,
      default structured EI output만 recorder/AR/FDC downstream에 전달한다.
    - `DecisionAgentRunner`에 FDC conditional skip을 추가했다.
    - `source_type=core` + `실보유 없음` 경로에서
      AR 결과가 `risk_opinion=reject` 또는 `risk_score >= 0.85`이면
      FDC provider 호출은 생략하고 synthetic `HOLD/WATCH` 결과로 종료한다.
    - `TradeDecisionEntity.decision_json.ai_call_path`를 추가했다.
    - `ei_skipped`, `ar_skipped`, `fdc_skipped`, `skip_reason_codes`를 저장해
      short-circuit 적용 결과를 DB 조회만으로 바로 실측할 수 있게 했다.
    - `run_decision_loop` 결과 직렬화와 운영 요약 집계에도
      동일한 `ai_call_path` 계측을 반영했다.
    - cycle result 단위로 `ei_skipped`, `ar_skipped`, `fdc_skipped`,
      `skip_reason_codes`가 포함되며,
      summary metrics에는 tracked count / 단계별 skip count /
      skip reason 분포가 함께 기록된다.
    - 기존 `WATCH guard` / `BUY eligibility guard`도
      `core + 기존 보유 종목`에는 적용하지 않도록 보정해
      신규 진입 제한과 보유종목 관리 경계를 분리했다.
  - 적용 범위 제약
    - 위 short-circuit은 우선 `source_type=core` 등
      `신규 BUY 검토 경로`에만 적용한다.
    - `held_position`, `reconciliation_overlay`,
      상태 복구/정합성 확인 경로에는 동일 규칙을 적용하지 않는다.
    - 이유:
      보유종목의 `REDUCE/EXIT` 기회나
      정합성 복구 우선 원칙을 토큰 절감 논리로 잘라내면
      핵심 목표인 기대수익률 최대화와 운영 안전성을 함께 훼손할 수 있다.
  - 선행 작업
    - [x] skip/reject 사유를 `decision_json`에 구조화해
      어떤 단계에서 EI/AR/FDC가 생략됐는지 실측 가능하게 만들 것
    - [x] 운영 요약에도 같은 skip 계측을 반영할 것
    - 계측 없이 `60~80% 절감` 같은 정성 기대치로 바로 고정하지 않을 것
  - 기준 문서
    - [`plans/[ADVICE] ai_token_optimization.md`](./%5BADVICE%5D%20ai_token_optimization.md)
    - [`plans/2026-06-05_pre_ai_decision_skip_gate.md`](./2026-06-05_pre_ai_decision_skip_gate.md)
    - [`plans/[ANALYSIS] expected_return_architecture_refactor_analysis.md`](./%5BANALYSIS%5D%20expected_return_architecture_refactor_analysis.md)
- [x] `core 신규 진입 비적격` risk-off 차단 완화 1차 보정
  - 실측 배경
    - `2026-06-24` decision:
      총 `2529`건 중 `eligibility_risk_off_block` `838`건,
      `source_policy_buy_blocked` `1203`건
    - `2026-06-25` decision:
      총 `1759`건 중 `eligibility_risk_off_block` `726`건,
      `source_policy_buy_blocked` `614`건
    - `2026-06-24` 실제 주문:
      `BUY 1건`, `SELL 7건`
      - 유일한 BUY는 `core`가 아니라 `event_overlay` 경로였음
    - `2026-06-25` 실제 주문:
      `order_requests=0`
    - 결론:
      현재 `core` 신규 진입 차단은
      “버그성 오차”보다 “정책 과도”에 가까우며,
      특히 `risk_off + bearish_trend`일 때
      core BUY가 AI 이전 단계에서 과도하게 잘리는 상태다.
  - 현재 코드 진단
    - `DecisionOrchestratorService`는
      `pre_ai_short_circuit + eligibility_risk_off_block`이면
      AI 호출 없이 `HOLD/WATCH`로 종료한다.
    - `DeterministicTriggerEngine`의 BUY eligibility는
      `market_regime.risk_tone == risk_off`
      그리고 `regime_label == bearish_trend`이면
      즉시 탈락시킨다.
    - 이 규칙은
      `range_bound`나 `bullish_trend + high_volatility`가 아니라
      `bearish_trend + risk_off`에만 적용되지만,
      실제 장중에서는 이 조합 비중이 높아
      core BUY path가 사실상 마비될 수 있다.
  - 수정 원칙
    - 전면 해제는 하지 않는다.
      `risk_off` 구간의 execution risk와 churn 증가는
      여전히 deterministic하게 억제해야 한다.
    - 다만 `core`의 기대수익률 상단 후보까지
      AI 이전 단계에서 일괄 차단하는 것은
      핵심 목표인 `최고 기대수익률`에 부합하지 않는다.
    - 따라서 `blanket block`을
      `ranked exception + WATCH 우선` 구조로 바꾼다.
  - 권장 수정안
    - [x] `P1`:
      `eligibility_risk_off_block`을
      “전면 BUY 탈락”에서
      “일반 core BUY 탈락 + 예외 후보만 AI 통과”로 변경
      - 기본값:
        기존처럼 `HOLD/WATCH` short-circuit 유지
      - 예외 허용 조건:
        아래를 모두 만족하는 상위 core 후보만
        AI 호출 경로로 통과
        - `source_type == core`
        - `watch_candidate == true` 또는 `entry_score >= buy_threshold * 0.85`
        - `ranking_score >= 0.55` 또는 `ranking_percentile <= 0.15`
        - `overall_score >= 0`
        - `slow_score >= -0.05`
        - `volume_surge_ratio >= 1.2` 또는
          `turnover_surge_ratio >= 1.2`
        - `recommended_max_order_value > 0`
        - `eligibility_low_average_volume`,
          `eligibility_low_turnover`,
          `eligibility_participation_rate_blocked`
          는 없어야 함
    - [x] `P1`:
      `risk_off + bearish_trend`에서도
      예외 통과 후보는
      즉시 `BUY_CANDIDATE`가 아니라
      `WATCH/AI reassessment` 우선으로 제한
      - FDC가 최종 `APPROVE`로 올리더라도
        `minimum_required_edge_bps`를 평시보다 높게 적용
      - 권장:
        `minimum_required_edge_bps`
        `+5 ~ +10bps` 가산
    - [x] `P1`:
      `event_overlay`는
      `core risk_off exception` 경로에 태우지 않고
      기존 regime gate 경로를 유지
      - 실측상 `2026-06-24` 실제 BUY `1건`은
        `event_overlay`에서 발생했으므로
        `core` 완화와 `event` 완화는 분리해야 한다.
      - 회귀 방지:
        `tests/services/test_deterministic_trigger_engine.py`에
        `event_overlay`가 `risk_off_exception_eligible`로
        승격되지 않는 테스트를 추가했다.
    - [x] `P2`:
      `market_regime`의 `risk_off` 판정과
      `core BUY eligibility`를 완전히 동일시하지 않도록 분리
      - `risk_tone`은 portfolio de-risk 용도로 유지
      - BUY eligibility는
        `regime + ranking + feature + execution feasibility`
        조합으로 별도 판정
      - 구현 반영:
        `core + bearish_trend + risk_off`에서는
        기존 blanket block 대신
        `core_risk_off_guard`를 적용한다.
      - 현재 guard 기준:
        `ranking_score >= 0.48`
        + `overall >= 0`
        + `slow >= -0.05`
        + `max(volume_surge_ratio, turnover_surge_ratio) >= 1.20`
        + 허용 전략
        (`defensive_low_volatility_rotation`,
        `mean_reversion_bounce`,
        `event_continuation`)
      - guard 실패 시에는
        `eligibility_core_risk_off_*_blocked`
        세부 사유를 남기고
        pre-AI short-circuit 대상에 포함한다.
      - 회귀 방지:
        `tests/services/test_deterministic_trigger_engine.py`,
        `tests/services/test_decision_orchestrator.py`,
        `tests/services/test_expected_value_gate.py`
        기준으로 검증한다.
  - 기대 효과
    - `core` 신규 진입 후보가
      전부 AI 이전 단계에서 사라지는 현상 완화
    - `risk_off` 구간에서도
      상위 극소수 후보는 재평가 가능
    - `event_overlay`와 `held_position`의 기존 운영 안정성은 유지
    - 무차별 BUY 재개가 아니라
      `top-ranked exception`만 허용하므로
      churn 및 저유동성 오진입 리스크를 제한 가능
  - 구현 순서
    - [x] `DeterministicTriggerResult`에
      `risk_off_exception_eligible` 필드 추가
    - [x] `deterministic_trigger_engine.py`에서
      위 예외 판정 helper 추가
    - [x] `decision_orchestrator.py`의
      `pre_ai_short_circuit` 분기에서
      `eligibility_risk_off_block`이어도
      `risk_off_exception_eligible=true`면
      AI 호출 경로로 통과
    - [x] `expected_value_gate`에서
      `risk_off_exception_path`에 대한
      추가 edge 요구치 적용
    - [x] 운영 계측:
      `risk_off_exception_eligible_count`,
      `risk_off_exception_ai_pass_count`,
      `risk_off_exception_submit_count`
      집계 추가
- [x] 초저유동성 `core` BUY 실행 구멍 보완
  - 기대수익률 관점에서 부합하는 범위만 우선 반영:
    - [x] `core` BUY eligibility에도 저유동성 / execution feasibility gate 1차 추가
      - `signal_feature_snapshot.average_volume_20d`
      - `portfolio_allocation.recommended_max_order_value`
      를 이용해 `eligibility_low_average_volume`, `eligibility_low_turnover`,
      `eligibility_participation_rate_blocked`를 판단하도록 반영
    - [x] `eligibility 실패`, 특히 execution infeasible 상태에서는
      `NO_ACTION -> AI APPROVE` 승격 금지 1차 반영
      - `buy_eligibility_guard`로 `core` BUY 승격을 `HOLD/WATCH`로 제한
    - [x] 전면 `MARKET` 정책은 유지하지 않고,
      저유동성 구간은 `LIMIT 강제` 또는 `submit 금지`로 1차 분기
      - `ExecutionService`에서 `buy_execution_liquidity_v1` 적용
      - 중간 저유동성: `quote.ask` / `reference_price` 기반 `LIMIT` 강제
      - 심각 저유동성 또는 trigger execution infeasible: submit 차단
    - [x] sizing에 participation cap 1차 추가
      - live quote의 `acml_vol`, `acml_tr_pbmn`
      - feature의 `average_volume_20d`
      를 이용해 `intraday_volume_participation_cap`,
      `intraday_turnover_participation_cap`,
      `average_daily_volume_participation_cap` 적용
  - blanket `NO_ACTION override 금지`는
    기대수익률 저해 가능성이 있어 채택하지 않음
  - 검증 상태
    - 관련 회귀 테스트로 아래 경로를 재확인했다.
      - deterministic trigger의 `low_average_volume`, `participation_rate_blocked`
      - orchestrator의 `buy_eligibility_guard`, pre-agent short-circuit
      - execution 단계의 `LIMIT 강제` / `submit 차단`
      - sizing 단계의 participation cap 3종
  - 기준 문서:
    - [`plans/[DESIGN] deterministic_trigger_eligibility_and_ranking_v1.md`](./%5BDESIGN%5D%20deterministic_trigger_eligibility_and_ranking_v1.md)
    - [`plans/[ANALYSIS] expected_return_architecture_refactor_analysis.md`](./%5BANALYSIS%5D%20expected_return_architecture_refactor_analysis.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `30`
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `30a`
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

---

### 12. Market Regime / Strategy Selection / Portfolio Agent 분해 — `완료`

### 핵심
- 시장 국면, 전략 선택, 포트폴리오 배분 책임을 명시적 계층으로 분리

### 세부 작업 상태
- [x] Market Regime deterministic backbone 1차 추가
  - `services.market_regime`에 `MarketRegimeAssessment`, `classify_market_regime()` 추가
  - `signal_feature_snapshot` 기반 `bullish_trend` / `bearish_trend` / `range_bound` / `event_driven_unstable`
    및 `high_volatility` / `risk_on` / `risk_off` 분류 규칙 1차 구현
  - 전략군 가중치(`strategy_weights`), `confidence`, `half_life_hours`, `reason_codes` 산출
- [x] decision pipeline 입력 연결 1차 완료
  - `DecisionOrchestratorService.assemble()`가 최신 signal snapshot에서 market regime를 계산해
    `AssembledContext.market_regime`에 주입
  - AI Risk / FDC prompt에 regime label / volatility regime / risk tone / strategy weights를 read-only로 노출
  - 생성되는 `TradeDecisionEntity.regime_label`에 1차 반영
- [x] Strategy Selection deterministic registry / selector 1차 추가
  - `services.strategy_selection`에 `StrategySelectionAssessment`, `select_strategy()` 추가
  - `market_regime + source_type` 기반으로 `preferred_strategy`, `allowed_strategies`,
    `preferred_entry_style`, `preferred_time_horizon`, `confidence`, `reason_codes` 산출
  - `AssembledContext.strategy_selection`에 주입하고 AI Risk / FDC prompt에 read-only로 노출
  - `TradeDecisionEntity.strategy_fit_score` 및 `decision_json.strategy_selection`에 1차 반영
- [x] Portfolio allocation / concentration budget 계층 분리
  - `services.portfolio_allocation`에 `PortfolioAllocationAssessment`,
    `assess_portfolio_allocation()` 추가
  - `DecisionOrchestratorService.assemble()`가 `config + snapshot + regime + strategy`
    입력을 이용해 종목별 `target_weight_pct`, `remaining_concentration_pct`,
    `remaining_gross_budget_pct`, `max_new_capital_pct`,
    `recommended_max_order_value`를 계산해
    `AssembledContext.portfolio_allocation`에 주입
  - AI Risk / FDC prompt가 포트폴리오 배분 결과를 read-only로 노출하고,
    `TradeDecisionEntity.decision_json.portfolio_allocation`에 1차 반영

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `27`, `29`, `31`
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

---

### 13. AI Compliance / Model Monitor 분해 — `미완료`

### 핵심
- ambiguous policy risk와 deterministic hard validation 분리
- provider drift / fallback / replay divergence 모니터링 체계 구축

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `32`, `33`
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`
- `plan_docs/agents/03_risk_role_boundaries.md`

### 14. Data Quality / Hard Guardrail 일원화 — `완료`

### 핵심
- stale snapshot, blocked reason, kill switch, risk check, submit/reconcile 차단 규칙을
  명시적 deterministic 계층으로 더 정리
- 현재 orchestrator / sizing / sync / snapshot 계층에 분산된 hard guardrail 책임을 수렴

### 세부 작업 상태
- [x] decision loop의 `pre-AI skip` 규칙을 공용 서비스 계층으로 승격
  - `held_position` 무보유 skip
  - 일반 BUY `orderable_amount` / general BUY budget 기반 skip
  - late-session / recent-event / recent-order 기반 held-position stable-hold skip
- [x] `pre-AI gate` / `execution_service` 공통 `PipelineStopReason` 코드 집합 1차 정리
  - `stop_reason`를 `SubmitResult`/cycle serialization에도 직접 노출
- [x] scheduler `dry_run_reason` / general submit gate 사유도 canonical helper로 정리
  - dry-run 결과에도 `stop_reason` 동시 노출
- [x] `pre-AI deterministic gate` 차단 결과를 `guardrail_evaluations`에 저장
  - `rule_set_version=pre_ai_gate_v1`
  - `symbol/account/source_type/skip_details` audit trail 보존
- [x] `scheduler gate` dry-run 차단 결과도 `guardrail_evaluations`에 저장
  - `rule_set_version=scheduler_gate_v1`
  - `submit_budget_consumed_*` / `general_submit_disabled_*` 류 사유 audit trail 보존
- [x] execution `sell_guard` / `buy_duplicate_guard` 차단 결과도 `guardrail_evaluations`에 저장
  - `rule_set_version=sell_guard_v1`, `buy_duplicate_guard_v1`
- [x] execution `stale_snapshot_guard` 차단 결과도 공통 helper로 수렴
  - `rule_set_version=stale_snapshot_guard_v1`
  - account-level / run-level stale 차단 모두 `_record_blocking_guardrail_evaluation()` 경유
- [x] execution 최종 broker outcome도 canonical `stop_reason`으로 수렴
  - `SUBMITTED → order_submitted`
  - `RECONCILE_REQUIRED → order_reconcile_required`
  - `REJECTED → order_rejected`
- [x] stale snapshot guardrail blocking code도 canonical 소문자 코드로 수렴
  - `STALE_SNAPSHOT_ACCOUNT → stale_snapshot_account`
  - `STALE_SNAPSHOT → stale_snapshot_run`
- [x] scheduler submit lane gate를 공통 helper로 추출해 중복 계산 제거
  - `scripts/run_decision_loop.py`의 submit/dry-run/reason 계산을
    `services.submit_lane_gate.evaluate_symbol_submit_lane()`로 수렴
- [x] execution의 `RECONCILE_REQUIRED` / `REJECTED` broker outcome도 guardrail audit로 저장
  - `rule_set_version=broker_submit_outcome_v1`
  - `order_reconcile_required`, `order_rejected`를 `guardrail_evaluations`에서 직접 추적 가능
- [x] guardrail evaluation 저장 스키마를 공통 helper로 수렴
  - `services.guardrail_audit.persist_blocking_guardrail_evaluation()`
  - pre-AI / scheduler / execution 경로가 동일한 저장 함수 사용
- [x] `held_position` 위험축소 SELL 경계를 공통 helper로 수렴
  - `services.held_position_policy.is_held_position_sell_path()`
  - scheduler와 execution, ops scheduler가 동일하게 `held_position + REDUCE/EXIT + SELL`만
    quote/stale bypass 및 전용 lane 대상으로 취급
- [x] held-position 전용 submit lane의 cycle cap 차단 제거
  - `services.submit_lane_gate.evaluate_symbol_submit_lane()`에서
    `source_type=held_position`만으로 `held_position_sell_cycle_cap`을
    선적용하던 경로를 제거
  - held-position 종목은 같은 cycle 내 동일 symbol 중복만 차단하고,
    위험축소 SELL submit은 cycle count와 무관하게 진행되도록 정리
- [x] held-position 반복 `REDUCE/EXIT` 판단 suppression 1차 추가
  - `services.pre_ai_gate.evaluate_held_position_skip_reason()`가
    최근 same-symbol SELL order + 최근 held-position `REDUCE/EXIT/SELL` 판단 +
    포지션 증가 없음 조건에서
    `held_position_recent_risk_sell_cooldown`으로 pre-AI skip
  - 최근 이벤트가 있거나 장 마감 임박 이후에는 suppression을 적용하지 않음
  - 후속 운영 검증:
    `2거래일` 정도 장중 모니터링으로
    `held_position_recent_risk_sell_cooldown` 분포,
    동일 종목 반복 `REDUCE/EXIT` 감소율,
    위험축소 SELL 지연/누락 부작용 유무를 먼저 실측한 뒤
    `signal_feature_snapshot_id` 동일 여부까지 포함한 stricter duplicate policy 검토 진행
- [x] stale snapshot / submit cap / sell guard / reconcile gate의 공통 reason code 체계 수렴
  - `PipelineStopReason` + `general_submit_disabled_reason()` +
    `submit_budget_consumed_reason()` 기준으로 canonical code 정리
  - `stale_snapshot_account`, `stale_snapshot_run`,
    `order_reconcile_required`, `order_rejected`까지 수렴 완료
- [x] scheduler / decision loop / execution_service 간 중복 gate 제거
  - pre-AI skip은 `services.pre_ai_gate`
  - submit lane gate는 `services.submit_lane_gate`
  - held-position risk-reducing SELL 판별은 `services.held_position_policy`
  - ops scheduler도 동일 helper 사용
- [x] execution/scheduler 전 구간의 guardrail evaluation 저장 정책 최종 수렴
  - `services.guardrail_audit.persist_blocking_guardrail_evaluation()`로 저장 경로 통일
  - pre-AI / scheduler / execution / broker submit outcome이 동일 audit 축으로 기록

### 근거 문서
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`
- `plan_docs/agents/03_risk_role_boundaries.md`

### 비고
- 본 항목은 구현 관점에서는 닫힌 상태다.
- 이후 추가 변경이 생기면 새 guardrail이 위 공통 helper/enum 체계를 따르는지만 검토하면 된다.
- 이 항목은 AI agent 추가가 아니라 execution safety 계층 정리이므로,
  전략/신호 agent 분해와 병렬로 보는 것이 아니라 오히려 일부 선행 과제로 해석할 수 있다.

---

## P3 — 후순위 또는 보류할 작업

### 15. Admin UI 추가 고도화 — `보류`

현재 상태:
- 최근 BUY 차단, 체결내역, 드릴다운 관련 UI 보강이 많이 들어갔다.
- 사용자가 별도로 “지금은 admin ui보다 다른 급한 우선순위를 먼저 하자”고 명시했다.

따라서 아래는 당분간 후순위로 둔다.

- [ ] `fill-sync-runs/summary` retry 정보의 UI 뱃지화
- [ ] 주문 상세 ↔ 체결내역 교차 링크 UI polish
- [ ] 계좌/대시보드 freshness indicator 추가 확장
- [ ] 에이전트 판단근거 UI 추가 노출
- [ ] 수동 배치 Admin UI
  - instrument master sync / placeholder seed 같은 운영 배치를
    `dry-run → apply → 실행 이력 조회` 구조로 다룰 수 있는 UI
  - 장중 override 권한 / 실행자 / 파라미터 / 결과 로그를 함께 남기는
    job 기반 실행 contract 선행 필요

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `8d`, `10`, `11`, `12`, `13`
- `plan_docs/agents/01_agent_inventory_and_status.md`

### 16. 멀티 사용자 공용 Plane / 개인 Credential Plane 분리 리팩토링 — `보류`

### 목표
- 사용자별 KIS / AI / NAVER credential은 분리하되,
  공통으로 공유 가능한 정책/데이터/계산 계층은 재사용하는
  멀티 사용자 운영 구조를 설계하고 후속 구현한다.

### 공용으로 유지할 대상
- [ ] instrument master
- [ ] market session / 휴장일 / 장상태 수집
- [ ] universe selection 정책과 freeze 생성 로직
- [ ] signal / feature 계산식과 deterministic backend math engine
- [ ] broker adapter 구현체와 오류 정규화 규칙
- [ ] audit / replay / reconciliation 프레임워크
- [ ] 운영 대시보드 공통 집계 로직

### 개인별로 반드시 분리할 대상
- [ ] KIS App Key / App Secret / 계좌번호 / 상품코드
- [ ] AI provider key / model override / provider 선택
- [ ] NAVER 등 외부 API credential
- [ ] 사용자별 live/paper 활성 상태
- [ ] 사용자별 계좌 매핑과 주문 권한
- [ ] 사용자별 리스크 / execution override

### 설계/개발 작업 범위
- [ ] secret manager 또는 동등 구조를 전제로 한 `credential profile` 데이터 모델 설계
- [ ] `AppSettings()` 전역 env 의존 경로를 `client runtime config + secret resolver` 구조로 전환하는 설계
- [ ] account별 broker adapter / AI agent / news adapter 동적 조립 경로 설계
- [ ] `ops-scheduler`가 account fan-out 실행을 하되
  rate limit budget / reconciliation lock / snapshot truth를 계좌 단위로 분리하는 실행 설계
- [ ] Admin UI의 사용자별 credential 등록/검증/회전 화면 설계
- [ ] 사용자 인증 / RBAC / client-account 권한 매핑 설계

### 선행 조건
- universe / feature / decision / reconciliation / scheduler 핵심 운영 구조가 더 이상 크게 흔들리지 않을 것
- 현재 P0 ~ P2의 운영 안정화와 정책 구조화가 충분히 마무리될 것

### 근거 문서
- `plan_docs/detailed_design/01_system_architecture.md`
- `plan_docs/detailed_design/06_config_schema.md`
- `plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md`

### 보류 이유
- 현재 단계에서 바로 멀티 사용자화에 들어가면
  execution truth, scheduler, decision runtime 안정화보다
  런타임 주입 구조 변경이 먼저 커져 운영 리스크가 커진다.
- 따라서 이 항목은 **모든 중요 개발 완료 후 P3 리팩토링 과제**로 유지하는 것이 맞다.

---

## P3 — 개발 완료 후 문서화 과제

### 17. 운영/업무자용 주문 흐름 문서 패키지 — `보류`

### 목표
- 핵심 백엔드/운영 안정화 개발이 모두 끝난 뒤, 비개발 업무자도 바로 읽을 수 있는 운영 문서 세트를 만든다.

### 작성 대상
- [ ] **매수 경로만 따로 분리한 요약본**
- [ ] **매도/체결/재조회 경로만 따로 분리한 운영 매뉴얼**
- [ ] **장애 대응 체크리스트 버전**

### 선행 조건
- 현재 남아 있는 핵심 개발 과제가 모두 마무리될 것
- 주문 생성 / 제출 / 체결 / 재조회 / recovery 정책이 더 이상 크게 바뀌지 않을 것

### 근거 문서
- [`plans/[GUIDE] end_to_end_order_flow_guide.md`](./[GUIDE]%20end_to_end_order_flow_guide.md)
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `13a`

### 보류 이유
- 지금 작성하면 이후 개발 변경으로 문서가 빠르게 낡을 가능성이 높다.
- 따라서 **모든 주요 개발 종료 후 최종 운영 매뉴얼 패키지로 작성**하는 것이 맞다.

### 우선순위 이유
- 이번 임시공휴일처럼 시장 캘린더 변동이 있을 때 운영 판단을 더 신뢰성 있게 할 수 있다.

### 세부 작업 상태
- [x] 조기종료/특수세션 reason 근거를 `reason_metadata`로 더 구조적으로 저장 완료
  - [`plans/2026-06-08_market_sessions_reason_metadata_structuring.md`](./2026-06-08_market_sessions_reason_metadata_structuring.md)
- [x] 비거래일 readiness / next-trading-day readiness와 session history를 더 직접 연결 완료
  - [`plans/2026-06-04_market_sessions_history_readiness_link.md`](./2026-06-04_market_sessions_history_readiness_link.md)

---


## 권장 실행 순서

### 1순위 묶음
1. Fill History Phase 3
2. 부분체결 자동 판정 고도화
3. fill 발생 후 snapshot refresh 자동화

### 2순위 묶음
4. 다음 거래일 장중 실운영 검증
5. KIS real credential smoke
6. 운영일 상태 관리

### 3순위 묶음
7. KIS token cache 공통 모듈화
8. 장 운영 세션 정보 저장
9. KIS 기본종목정보 적재/갱신

### 4순위 묶음
10. Data Quality / Hard Guardrail 일원화
11. Universe / Signal / Strategy / Portfolio / Compliance / Monitor 구조화
   - 단, 다음 단계는 단순 agent 추가가 아니라
     `deterministic trigger / candidate / attribution` 구조를 세우는 방향이어야 한다.
   - 기준 문서:
     [`plans/[ANALYSIS] expected_return_architecture_refactor_analysis.md`](./%5BANALYSIS%5D%20expected_return_architecture_refactor_analysis.md)

---

## 정리

현재 가장 중요한 남은 일은 UI가 아니라 다음 세 가지다.

1. **체결 진실을 더 직접적으로 쓰는 구조 완성**
   - fill snapshot을 주문 상태 수렴의 주 진실원으로 강화
2. **장중 운영 검증**
   - 최근 수정이 실제 다음 거래일에도 정상 동작하는지 실측
3. **운영 기반 데이터 정리**
   - 운영일 상태, 세션 정보, 종목 master, KIS token/config 기술부채 정리
4. **Agent 책임 분리**
   - 다만 이것은 AI agent 추가가 아니라, deterministic 계층과 hybrid 해석 계층을 올바르게 나누는 작업이어야 한다

즉, 앞으로의 우선순위는 다음 한 줄로 요약된다.

> **체결 진실 강화 → 장중 실운영 검증 → 운영 메타데이터 정리 → deterministic guardrail 정리 → 전략/에이전트 구조화**
