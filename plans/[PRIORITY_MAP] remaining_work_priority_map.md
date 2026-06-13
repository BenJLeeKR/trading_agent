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

### 8. 장 운영 세션 정보 수집/저장 — `진행중`

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

---

## P3 — 개발 완료 후 문서화 과제

### 15. 운영/업무자용 주문 흐름 문서 패키지 — `보류`

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

### 9. KIS 기본종목정보 instrument master 적재/갱신 — `완료`

### 목표
- 종목 메타데이터를 KIS 기준으로 더 안정적으로 관리한다.

### 세부 작업 상태
- [x] 정규화된 KIS master CSV 기반 기본종목정보 수집 파이프라인 1차 완료
  - [`plans/2026-06-08_kis_instrument_master_sync_pipeline_phase1.md`](./2026-06-08_kis_instrument_master_sync_pipeline_phase1.md)
- [x] instrument master 갱신 정책
  - [`plans/2026-06-08_kis_instrument_master_update_policy.md`](./2026-06-08_kis_instrument_master_update_policy.md)
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
- [ ] market_overlay 실운영 편입/효과 장중 실측
- [ ] universe selection 결과의 운영 UI 연계
- [ ] manual watchlist/override 계층의 운영 정책 확정

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `28`
- [`plans/[POLICY] trading_universe_policy_v1.md`](./[POLICY]%20trading_universe_policy_v1.md)
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

---

### 11. Signal Agent 분해 — `미완료`

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

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `30`
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `30a`
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

---

### 12. Market Regime / Strategy Selection / Portfolio Agent 분해 — `미완료`

### 핵심
- 시장 국면, 전략 선택, 포트폴리오 배분 책임을 명시적 계층으로 분리

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

### 14. Data Quality / Hard Guardrail 일원화 — `진행중`

### 핵심
- stale snapshot, blocked reason, kill switch, risk check, submit/reconcile 차단 규칙을
  명시적 deterministic 계층으로 더 정리
- 현재 orchestrator / sizing / sync / snapshot 계층에 분산된 hard guardrail 책임을 수렴

### 세부 작업 상태
- [x] decision loop의 `pre-AI skip` 규칙을 공용 서비스 계층으로 승격
  - `held_position` 무보유 skip
  - 일반 BUY `orderable_amount` / general BUY budget 기반 skip
  - late-session / recent-event / recent-order 기반 held-position stable-hold skip
- [ ] stale snapshot / submit cap / sell guard / reconcile gate의 공통 reason code 체계 수렴
- [ ] scheduler / decision loop / execution_service 간 중복 gate 제거
- [ ] guardrail evaluation 저장 범위를 pre-AI deterministic gate까지 확장할지 결정

### 근거 문서
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`
- `plan_docs/agents/03_risk_role_boundaries.md`

### 비고
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
