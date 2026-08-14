# 상세 설계 문서 세트 v1

이 디렉터리는 `ENTERPRISE_TRADING_SYSTEM_DESIGN.md`를 구현 가능한 수준으로 분해한 상세 설계 초안 모음이다.

## 문서 목록

1. `01_system_architecture.md`
   - 시스템 경계
   - 컴포넌트 책임
   - 런타임 상호작용
   - 배포 단위

2. `02_order_execution_sequence.md`
   - 주문 생성부터 체결 정산까지의 시퀀스
   - 멱등성
   - 실패/재시도/정합성 복구

3. `03_data_model_erd.md`
   - 핵심 엔티티
   - 관계
   - 감사 및 재현성 저장 규칙

4. `04_broker_adapter_interface.md`
   - 공통 브로커 추상화
   - capability 모델
   - 공통 오류 계약

5. `05_koreainvestment_adapter_spec.md`
   - 한국투자증권 어댑터 책임
   - 인증/토큰/실시간 접속키 생명주기
   - 주문 및 시세 처리 규칙

6. `06_config_schema.md`
   - 클라이언트별 설정 구조
   - 환경 분리
   - 버전 관리 원칙

7. `07_mvp_scope_and_delivery_plan.md`
   - v1 범위
   - 단계별 구현 순서
   - 완료 기준

8. `08_ai_decision_policy.md`
   - 기대수익률 지향 AI 판단 구조
   - 시장 비효율 가설
   - regime/strategy/signal 통합 방식
   - sizing/exit/feedback 구조

9. `09_market_and_event_data_policy.md`
   - 공시/뉴스/리포트/거시 데이터 소스 정책
   - source reliability, polling, dedup, freshness
   - event classification과 RAG 저장 정책

10. `10_broker_rate_limit_and_capacity_policy.md`
   - 브로커 호출 제한의 주문 안전성 정책
   - order/inquiry/reconciliation 예산 분리
   - websocket capacity, cache TTL, throttling/backoff/circuit

11. `11_kis_realtime_quote_operations_screen.md`
   - Admin UI "기본 운영" 실시간 현재가 조회 화면 설계
   - 전용 계좌/appkey 분리, approval key/세션/구독 한도 정책
   - API contract, UI 구성, polling → relay 단계 전환 계획

12. `12_realized_pnl_moving_average_ledger.md` (설계안, 미구현)
   - KIS 실체결 기준 종목별 이동평균 매입원가·실현 손익 ledger
   - `position_cost_basis_state` / `realized_pnl_event` / `realized_pnl_daily_aggregate` 분리 설계
   - idempotency, out-of-order/중복/정정 처리, 장애 복구 계약
   - 13절: `fee_tax_source` provenance 4값(`reported`/`assumed_zero`/`calculated_from_policy`/`policy_not_applicable`) 확장 계약 확정(구현 미착수) — migration 방향, `provenance_breakdown` API 계약 포함
   - 실행 계획: [`docs/40_action_plans/kis_realized_pnl_moving_average_action_plan.md`](../../40_action_plans/kis_realized_pnl_moving_average_action_plan.md)

13. `13_loss_cut_policy_specification_and_config_path_design.md` (정책 명세 초안, 구현 미착수)
   - 손실률 기반(매수가 대비 -N%) Loss-cut 정책의 정책 명세 + 설정 경로 설계 초안 — 구현 직전 수준까지 구체화
   - 2단계(soft/hard) 손절 구조, 기존 held_position 청산 로직과의 합성/우선순위 규칙, 기준 가격, cooldown 설계
   - `risk.loss_cut` config_json 스키마 초안 + Admin API/CLI 입력 계약 초안, shadow 전용 `env` 허용 범위
   - 선행 조사(설계 조사/현황 분석): [`docs/20_system_analysis/loss_cut_policy_investigation.md`](../../20_system_analysis/loss_cut_policy_investigation.md) — 현재 운영 코드에 정량 손절이 없음을 소스 기준으로 확인, 정책안 3종(하드 손절/단계형/관측용 shadow) 비교
   - 실행 계획: [`docs/40_action_plans/loss_cut_policy_and_config_path_action_plan.md`](../../40_action_plans/loss_cut_policy_and_config_path_action_plan.md)
   - shadow inspection API 운영 해석 가이드(정책 실행 가이드 아님): [`docs/40_action_plans/loss_cut_shadow_inspection_operations_guide.md`](../../40_action_plans/loss_cut_shadow_inspection_operations_guide.md)

14. `14_kis_fill_normalization_and_incremental_interpretation_design.md` (설계안, 구현 미착수)
   - KIS `inquire-daily-ccld` 응답의 paper/live 필드명·대소문자 차이를 주문 유형별 분기 없이 흡수하는 범용 정규화 계층 설계
   - 누적 체결량(`TOT_CCLD_QTY`)을 증분 fill로 안전하게 변환하는 해석 계층(상태 테이블 기반 delta 계산) 설계, append-only ledger 보호를 위한 anomaly 분리 규칙
   - `fill_history_sync.py`의 기존 fallback 규칙과의 정합성, shadow 모드 선행 운용 권장
   - 실행 계획: [`docs/40_action_plans/kis_fill_normalization_action_plan.md`](../../40_action_plans/kis_fill_normalization_action_plan.md)

15. `15_truth_probe_and_kis_fill_sync_coexistence_design.md` (설계안, 구현 미착수)
   - 기존 `_try_truth_probe()`(주문 상태 확정)와 신규 `_sync_fills()`/KIS 누적→증분 해석 경로(체결 원장 적재)의 책임 분리 설계
   - linked `broker_fill_snapshots` truth 성공 시 조기 반환이 신규 경로 실행 기회를 영구히 차단하는 문제를 `FILL_SNAPSHOT` reason 한정 병행 호출로 해소하는 안 비교
   - shadow 모드 유지 전제, 과거 snapshot backfill 문제와의 선후관계/경계 명시
   - 실행 계획: [`docs/40_action_plans/truth_probe_kis_fill_sync_coexistence_action_plan.md`](../../40_action_plans/truth_probe_kis_fill_sync_coexistence_action_plan.md)

16. `16_broker_fill_snapshot_historical_backfill_design.md` (설계안, 구현 미착수)
   - `broker_fill_snapshots`에 남은 과거 체결 관측 흔적을 근거로, 이미 지나간 과거 매도(및 그 원가 형성에 필요한 매수)를 synthetic `fill_events`로 사후 재구성하는 backfill 설계
   - 14번/15번 문서의 "미래 체결 경로 정상화"와 명확히 구분되는 "과거 복원" 전용 축 — 매도만으로는 이동평균 원가 계산이 완결되지 않는다는 점을 반영해 계좌×종목 단위 원가 완결성 기준으로 모집단을 제한
   - snapshot→synthetic fill 변환은 14번 문서의 계산 공식을 재사용하되 실시간 폴링 전용 상태 테이블(`kis_fill_cumulative_state`)은 재사용하지 않음, `fill_events` 직접 append + dry-run/사람 승인 절차로 안전성 확보
   - 실행 계획: [`docs/40_action_plans/broker_fill_snapshot_historical_backfill_action_plan.md`](../../40_action_plans/broker_fill_snapshot_historical_backfill_action_plan.md)

## 설계 원칙

- 실전/모의 환경은 논리적으로만이 아니라 설정, 자격증명, 계좌, 라우팅 수준에서 분리한다.
- AI 의사결정은 주문 판단 주체지만 계좌 보호는 deterministic hard guardrail이 수행한다.
- 브로커 의존성은 `BrokerAdapter` 뒤에 격리한다.
- 같은 입력으로 같은 결과를 재현할 수 있도록 모든 의사결정 입력과 출력을 저장한다.
- 라이브 주문보다 먼저 백테스트와 페이퍼트레이딩 경로를 확정한다.
