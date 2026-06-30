# 최초 시작부터 KIS 주문 제출·재조회까지 전체 경로 설명서

## 문서 목적

이 문서는 현재 코드 기준으로 아래를 한 번에 설명하기 위한 운영 가이드다.

1. 오늘 어떤 종목이 판단 대상으로 선정되는가
2. 선정된 종목이 어떤 정량 기준을 통과해야 `매수/매도` 판단 후보가 되는가
3. AI 판단과 deterministic 계산이 어떤 순서로 결합되는가
4. 주문이 실제로 어떤 가드레일을 통과한 뒤 KIS로 제출되는가
5. 제출 이후 체결/미체결/정합성 상태를 어떻게 다시 맞추는가

이 문서는 “정책 문서의 이상적인 목표”가 아니라, **현재 구현되어 운영 경로에 실제 반영된 내용**을 기준으로 쓴다.

---

## 1. 한눈에 보는 전체 흐름

```text
[ops-scheduler 시작]
        |
        v
[04:50 KST instrument master / membership 동기화]
        |
        v
[snapshot sync]
  - 현금 / 주문가능금액 / 포지션 / risk_limit_snapshot
  - symbol_trade_states authoritative 재수렴
        |
        v
[event ingestion]
  - 공시 / 뉴스 / seeded event 적재
        |
        v
[intraday universe freeze 보장]
  - decision_loop_intraday freeze 우선
        |
        v
[decision loop]
  - 종목별 pre-AI gate
  - signal_feature_snapshot attach
  - deterministic_trigger 계산
  - market_regime / strategy_selection / portfolio_allocation 계산
  - EI -> AR -> AI Compliance -> FDC
  - expected_value_gate
  - submit translation
        |
        v
[execution_service]
  - sizing
  - compliance_validator_v1
  - VaR / liquidity / probe churn / reverse trade / sell guard
  - OrderManager -> BrokerAdapter -> KIS submit
        |
        v
[post-submit sync / fill sync / reconciliation]
  - 제출 진실 확인
  - 체결 / 부분체결 / 미체결 / reconcile_required 수렴
  - snapshot refresh
        |
        v
[20:10 KST signal_feature_after_market batch]
  - snapshot_at = 해당 거래일 20:00 KST
  - 다음 거래일용 signal_feature_snapshots 고정
```

---

## 2. 스케줄러와 기준 시각

실행 진입점:

- [scripts/run_ops_scheduler.py](/workspace/agent_trading/scripts/run_ops_scheduler.py)

현재 중요한 기준 시각:

- `04:50 KST`
  - `instrument master`
  - `instrument_index_memberships`
  - 장전 기준 종목 마스터 준비
- 장중 첫 `decision` 직전
  - `decision_loop_intraday` freeze 보장
- `20:10 KST`
  - `signal_feature_after_market` 배치 실행
- `snapshot_at`
  - 장후 feature row는 해당 거래일 `20:00 KST`로 고정

핵심 원칙:

- 장중 판단은 live compose를 매번 즉석 계산하기보다 **intraday freeze**를 authoritative source로 우선 사용한다.
- 장후 feature는 장중과 분리된 배치 결과를 DB에 저장하고, 다음 판단 입력으로 재사용한다.

---

## 3. 장전 준비 계층

### 3-1. Instrument Master

관련 파일:

- [scripts/sync_kis_instrument_master.py](/workspace/agent_trading/scripts/sync_kis_instrument_master.py)
- [scripts/import_instrument_index_membership_seed.py](/workspace/agent_trading/scripts/import_instrument_index_membership_seed.py)

역할:

- `trading.instruments`를 오늘 판단 가능한 종목 기준 데이터로 맞춘다.
- `instrument_index_memberships`를 통해 `KOSPI100`, `KOSPI200`, `KOSDAQ150` membership을 보강한다.

중요 원칙:

- `instrument master`에 없는 종목은 universe 단계에서 제외된다.
- AI가 이 누락을 우회하지 않는다.
- `market_code` legacy 값이 남아 있어도, 실질 정책은 `exchange_code`, `market_segment`, `index_memberships`를 점진적으로 우선 사용한다.

### 3-2. Instrument Status Snapshot

관련 설계:

- [plans/[PLAN] instrument_status_snapshot_phase1.md](/workspace/agent_trading/plans/%5BPLAN%5D%20instrument_status_snapshot_phase1.md)

역할:

- 거래정지, 관리종목, 임시정지 같은 종목 상태성 fact를 별도로 저장한다.
- universe와 submit-time compliance가 이 정보를 읽어 차단한다.

즉:

- “종목이 존재하는가”는 `instrument master`
- “오늘 거래 가능한 상태인가”는 `instrument_status_snapshot`

으로 분리된다.

---

## 4. Universe 선정 기준

관련 코드:

- [src/agent_trading/services/universe_selection.py](/workspace/agent_trading/src/agent_trading/services/universe_selection.py)
- [src/agent_trading/services/universe_selection_types.py](/workspace/agent_trading/src/agent_trading/services/universe_selection_types.py)
- [plans/[POLICY] trading_universe_policy_v1.md](/workspace/agent_trading/plans/%5BPOLICY%5D%20trading_universe_policy_v1.md)

### 4-1. Universe 구성 순서

`UniverseSelectionService.compose_with_diagnostics()`는 아래 순서로 universe를 만든다.

1. `core`
2. `held_position`
3. `reconciliation_overlay`
4. `event_overlay`
5. `manual`
6. `market_overlay`
7. exclusion
8. priority sort
9. daily cap

### 4-2. source_type 우선순위

같은 종목이 여러 source에 동시에 걸리면 아래 우선순위를 따른다.

1. `held_position`
2. `reconciliation_overlay`
3. `event_overlay`
4. `market_overlay`
5. `manual`
6. `core`

의미:

- 보유 종목과 정합성 추적 대상은 알파보다 안전성이 우선이다.
- 같은 종목이 `core`이면서 `event_overlay`면 `event_overlay`로 승격된다.

### 4-3. Core Universe

현재 `core`는 아래 중 하나를 만족하는 종목을 seed로 쓴다.

- 승인된 core seed symbol
- `index_memberships` 또는 metadata 기준 core seed 판정
- 대형주 core universe flag

정책상 의미:

- 장기적으로 `KOSPI100` 중심 core를 유지
- `KOSDAQ`은 초기에는 core보다 `discovery / overlay / event` 계층에서 편입

### 4-4. Held Position

보유 수량 `> 0`인 종목은 무조건 편입된다.

특징:

- daily cap에서 제외 가능
- 이후 `sell/reduce` 판단 대상이 된다
- universe에서 빠져도 안 되는 mandatory 대상이다

### 4-5. Reconciliation Overlay

대상:

- `submitted`
- `acknowledged`
- `partially_filled`
- `cancel_pending`
- `reconcile_required`

또는 reconciliation pending run / blocking lock에 연결된 종목

의미:

- `unknown order state`에서는 신규 진입보다 상태 확인이 우선이다.
- 이 계층은 알파 탐색이 아니라 **주문 안전성**을 위한 강제 편입이다.

### 4-6. Event Overlay

최근 external event 중 의미 있는 이벤트만 편입한다.

핵심 기준:

- 이벤트 타입이 정책 whitelist에 있어야 한다
- `severity` 또는 `importance`가 정책상 요구 수준 이상이어야 한다

대표 예:

- `earnings`
- `disclosure_material`
- `capital_change`
- `governance`
- `macro_release`
- `sector_policy`
- `news_breaking`

### 4-7. Market Overlay

현재 구현 특징:

- `live` 환경에서만 실질 작동
- `paper`에서는 KIS mock quote 불안정성 때문에 skip
- `pre_pool_size = 50`
- `market_overlay_cap = 5`

구성 절차:

1. 가능하면 KIS ranking seed 사용
2. 없으면 discovery seed / core fallback 사용
3. `get_quotes_batch()`로 시세 조회
4. `F4/F5` 유동성 필터 적용
5. composite score 계산
6. 상위 `5`개 편입

market overlay 점수는 아래 3축 평균이다.

1. `acml_tr_pbmn`
   - 절대 누적 거래대금
   - `1조`를 `1.0`으로 정규화
2. `prdy_ctrt`
   - 등락률
   - `-5% ~ +10%`를 `0.0 ~ 1.0`으로 정규화
3. `stck_prpr / stck_hgpr`
   - 당일 고가 근접도
   - `80% 이하 = 0점`
   - `80% ~ 100%`를 `0.0 ~ 1.0`으로 정규화

### 4-8. Universe 유동성 필터

모든 일반 후보는 universe 단계에서 아래를 먼저 통과해야 한다.

대표 차단 사유:

- `unknown_instrument`
- `inactive_instrument`
- `unsupported_asset_class`
- `metadata_excluded`
- `broker_unsupported`
- `incomplete_instrument`
- `non_standard_symbol`
- `preferred_share_class`
- `tick_size_too_large`
- `status_snapshot_trading_halt`
- `status_snapshot_administrative_issue`
- `status_snapshot_next_session_halt`
- `status_snapshot_temporary_halt`

market overlay에는 추가로 아래가 붙는다.

- `acml_tr_pbmn < 1,000,000,000`
  - 당일 누적 거래대금 `10억 미만` 제외

### 4-9. Daily Cap

기본 cap:

- `max_cap = 30`
- held position은 cap에서 제외 가능
- `reconciliation_overlay`는 reserve 정책에 따라 cap 외로 취급 가능

의미:

- “오늘 판단할 종목 수”를 무한정 늘리지 않는다.
- 호출 예산, 판단 지연, 운영 복잡도를 통제한다.

---

## 5. Decision Loop가 읽는 입력

관련 파일:

- [scripts/run_decision_loop.py](/workspace/agent_trading/scripts/run_decision_loop.py)
- [src/agent_trading/services/decision_orchestrator.py](/workspace/agent_trading/src/agent_trading/services/decision_orchestrator.py)

종목별 판단 전에 붙는 입력:

1. 최신 `position_snapshot`
2. 최신 `cash_balance_snapshot`
3. 최신 `risk_limit_snapshot`
4. 최신 `signal_feature_snapshot`
5. `market_regime`
6. `strategy_selection`
7. `portfolio_allocation`
8. 최근 external event
9. `symbol_trade_state`
10. `instrument_status_snapshot`

---

## 6. Pre-AI 차단

AI 호출 전에 deterministic하게 먼저 막는 이유는 두 가지다.

1. 토큰 낭비 방지
2. 실행 불가능한 판단을 AI가 억지로 내리지 못하게 차단

대표 차단 축:

- stale snapshot
- held position 없음
- reentry cooldown
- same signal feature snapshot reverse trade
- holding_profile earliest reduce / reentry guard
- 일반 BUY budget 소진
- orderable amount 부족
- source policy상 신규 진입 금지

즉 AI는 “실행 가능한 후보”에 대해서만 의미 있게 쓰인다.

---

## 7. Signal Feature와 deterministic trigger

관련 파일:

- [src/agent_trading/services/signal_backbone.py](/workspace/agent_trading/src/agent_trading/services/signal_backbone.py)
- [src/agent_trading/services/deterministic_trigger_engine.py](/workspace/agent_trading/src/agent_trading/services/deterministic_trigger_engine.py)

### 7-1. signal_feature_snapshot 핵심 항목

현재 판단 backbone에 직접 연결되는 대표 feature:

- `overall_score`
- `fast_score`
- `slow_score`
- `average_volume_20d`
- `average_turnover_20d`
- `volume_surge_ratio`
- `turnover_surge_ratio`
- `atr_14_pct`
- `sma_5`, `sma_20`, `sma_60`

### 7-2. trigger 임계값

현재 고정 임계값:

- `BUY_CANDIDATE`
  - `entry_score >= 0.65`
- `WATCH`
  - `watch_score >= 0.45`
- `REDUCE_CANDIDATE`
  - `exit_score >= 0.60`
- `SELL_CANDIDATE`
  - `exit_score >= 0.75`

### 7-3. 매수 entry_score 계산식

`entry_score`는 대략 아래 가중치 합이다.

- `overall_score` 정규화값 `45%`
- `fast_score` 정규화값 `20%`
- `slow_score` 정규화값 `15%`
- bullish regime bonus
- `risk_on` bonus / `risk_off` penalty
- allocation budget bonus
- strategy alignment bonus
- `market_overlay` source bonus
- 상대 거래량/거래대금 급증 bonus

핵심 해석:

- 단순히 AI가 좋다고 말하는 것으로는 부족하다.
- 정량 backbone이 먼저 `entry_score`를 만들어야 한다.

### 7-4. 매수 eligibility 조건

`BUY_CANDIDATE`가 되려면 점수만 높아서는 안 되고 아래를 모두 통과해야 한다.

1. `source_type` 허용
   - `held_position`, `reconciliation_overlay`는 신규 BUY 차단
2. `coverage_score >= 0.50`
3. allocation budget 가능
4. 위험장 차단
   - `bearish_trend + risk_off`에서는 일반적으로 BUY 차단
   - 다만 core 일부는 예외 경로 허용 가능
5. signal floor
   - `overall_score < -0.10` 차단
   - `slow_score < -0.15` 차단
6. `average_volume_20d >= 3000`
7. 추정 `average_turnover_20d >= 50,000,000`
8. 상대 활동성
   - `max(volume_surge_ratio, turnover_surge_ratio) >= 1.10`
9. 참여율 제한
   - `recommended_max_order_value / average_turnover_20d <= 5%`
   - 추정 주문수량 / 평균거래량 `<= 3%`

즉 현재 매수는 **점수 + 실행 가능성**을 동시에 만족해야 한다.

### 7-5. risk_off core 예외 경로

`core` 종목이 `bearish_trend + risk_off`에서도 매수되려면 추가로 아래를 만족해야 한다.

- `ranking_score >= 0.48`
- `overall_score >= 0.0`
- `slow_score >= -0.05`
- `max(volume_surge_ratio, turnover_surge_ratio) >= 1.20`
- 선호 전략이 아래 중 하나
  - `defensive_low_volatility_rotation`
  - `mean_reversion_bounce`
  - `event_continuation`

### 7-6. 보유 종목 매도/축소 eligibility

`held_position` 경로는 아래를 본다.

- 실제 보유수량 존재
- `coverage_score >= 0.35`
- `exit_score > 0.30`

그 위에서:

- `exit_score >= 0.60`이면 `REDUCE_CANDIDATE`
- `exit_score >= 0.75`이면 `SELL/EXIT_CANDIDATE`

---

## 8. Expected Value Gate

관련 파일:

- [src/agent_trading/services/expected_value_gate.py](/workspace/agent_trading/src/agent_trading/services/expected_value_gate.py)

이 계층은 “점수상 좋아 보여도 비용 차감 후 기대값이 남는가”를 본다.

### 8-1. 적용 대상

아래 decision type에만 강제 적용된다.

- `APPROVE`
- `BUY`
- `SELL`
- `EXIT`
- `REDUCE`

`WATCH`, `HOLD`에는 기대값 게이트를 강제하지 않는다.

### 8-2. 핵심 계산

- `expected_return_bps`
  - 주로 trigger score anchor 기반
- `expected_downside_bps`
  - `risk_score * 40 + ATR penalty`
- `net_expected_value_bps`
  - `expected_return_bps - expected_downside_bps`
- `edge_after_cost_bps`
  - `net_expected_value_bps - round_trip_cost - slippage_buffer`

### 8-3. 최소 기준

- 신규 진입(`BUY`, `APPROVE`)
  - `minimum_required_edge_bps = 10.00`
- 축소/청산(`SELL`, `EXIT`, `REDUCE`)
  - `minimum_required_edge_bps = 5.00`
- `risk_off` 예외 진입 경로
  - 신규 진입 최소 기준에 `+7.50 bps`

즉:

- 매수는 비용 차감 후 최소 `10bps`
- 매도/축소는 비용 차감 후 최소 `5bps`

를 넘지 못하면 submit 단계로 가지 못한다.

---

## 9. AI 4단 체인

현재 AI 체인은 아래 순서다.

1. `Event Interpretation`
2. `AI Risk`
3. `AI Compliance`
4. `Final Decision Composer`

중요 원칙:

- AI는 계산기가 아니다.
- 계산과 차단의 authoritative source는 deterministic backend다.
- `AI Compliance`도 설명 보조 계층이지 최종 집행 계층이 아니다.

AI가 `BUY`를 말해도 아래 중 하나면 실제 주문으로 번역되지 않는다.

- deterministic trigger 미통과
- expected value gate 실패
- source policy 위반
- symbol state / cooldown 위반
- compliance hard rule 위반
- sizing 결과 0

---

## 10. Submit 직전 hard guardrail

관련 파일:

- [src/agent_trading/services/execution_service.py](/workspace/agent_trading/src/agent_trading/services/execution_service.py)
- [src/agent_trading/services/compliance_validator.py](/workspace/agent_trading/src/agent_trading/services/compliance_validator.py)

대표 차단 축:

1. `compliance_validator_v1`
   - 필수 필드 누락
   - invalid order shape
   - source policy 위반
   - reconciliation overlay flat BUY 차단
   - instrument status 차단
2. `VaR`
   - `risk_limit_snapshot.var_status == ready` 전제
3. low liquidity execution block
4. single-share probe churn block
5. reverse trade hysteresis
6. holding_profile earliest reduce / reentry guard
7. sell guard

### 10-1. compliance validator가 보는 종목 상태

차단 예:

- `tr_stop_yn = Y`
- `admn_item_yn = Y`
- `nxt_tr_stop_yn = Y`
- `temp_stop_yn = Y`
- `iscd_stat_cls_code in {01, 02, 03, 04, 05}`

단, 보유종목 `SELL`은 일부 unknown status에 대해 예외 허용 경로가 있다.

### 10-2. source_type별 신규 진입 정책

- `held_position`
  - 신규 BUY 금지
- `reconciliation_overlay`
  - 무포지션 flat 신규 BUY 금지

즉 `reconciliation_overlay`는 알파 진입 source가 아니라 상태 정리 source다.

---

## 11. Symbol State와 churn 제어

관련 파일:

- [src/agent_trading/services/holding_profile_policy.py](/workspace/agent_trading/src/agent_trading/services/holding_profile_policy.py)
- [src/agent_trading/services/reverse_trade_hysteresis.py](/workspace/agent_trading/src/agent_trading/services/reverse_trade_hysteresis.py)
- [src/agent_trading/services/symbol_trade_state_machine.py](/workspace/agent_trading/src/agent_trading/services/symbol_trade_state_machine.py)

현재 주문 churn을 막기 위해 심볼 단위 상태를 저장한다.

핵심 상태:

- `flat`
- `entry_pending`
- `held_active`
- `reduce_pending`
- `exit_pending`
- `flat_cooldown`

저장 정보:

- `holding_profile`
- `minimum_hold_until`
- `earliest_reduce_at`
- `earliest_reentry_at`
- `sell_cooldown_until`
- `reentry_cooldown_until`
- `last_signal_feature_snapshot_id`
- 직전 `edge_after_cost_bps`

핵심 의미:

- 방금 산 종목을 같은 thesis에서 곧바로 다시 팔지 못하게 한다.
- 방금 판 종목을 같은 signal snapshot에서 다시 곧바로 사지 못하게 한다.

---

## 12. 주문 제출과 제출 후 수렴

### 12-1. 주문 제출

경로:

- `DecisionOrchestratorService.assemble_and_submit()`
- `ExecutionService`
- `OrderManager`
- `BrokerAdapter`
- KIS REST submit

### 12-2. 제출 후 확인

관련 파일:

- [scripts/run_post_submit_sync_loop.py](/workspace/agent_trading/scripts/run_post_submit_sync_loop.py)
- [src/agent_trading/services/order_sync_service.py](/workspace/agent_trading/src/agent_trading/services/order_sync_service.py)

역할:

- 주문이 실제 제출되었는지
- 체결/부분체결/취소/거절인지
- `reconcile_required`인지

를 다시 맞춘다.

### 12-3. fill sync

추가 truth source:

- `fill snapshots`
- `broker fill`
- `position delta`

우선순위는 체결 truth를 더 직접적으로 아는 쪽이 우선이다.

### 12-4. snapshot refresh

fill 확인 이후:

- position
- cash
- orderable_amount
- risk_limit_snapshot

을 다시 최신화한다.

그리고 `symbol_trade_states`도 실제 포지션/주문 상태 기준으로 authoritative하게 재수렴시킨다.

---

## 13. 장후 feature batch

관련 파일:

- [scripts/generate_signal_feature_snapshot_input.py](/workspace/agent_trading/scripts/generate_signal_feature_snapshot_input.py)
- [scripts/build_signal_feature_snapshots.py](/workspace/agent_trading/scripts/build_signal_feature_snapshots.py)

역할:

1. 장후 universe freeze를 읽는다.
2. 시세/이벤트/기초 입력을 수집한다.
3. `signal_feature_snapshots`를 DB에 저장한다.
4. 다음 거래일 decision loop와 AI 판단의 공통 입력으로 재사용한다.

즉 장중 AI가 원시 시세를 길게 계산하는 구조가 아니라,
장후/장전 배치가 계산한 구조화 feature를 읽는 구조다.

---

## 14. 운영자가 “왜 주문이 안 나갔는가”를 볼 때 확인 순서

1. 오늘 종목이 `intraday universe freeze`에 있었는가
2. `source_type`이 무엇인가
3. universe 단계에서 liquidity/status로 탈락했는가
4. `deterministic_trigger`
   - `entry_score`, `exit_score`
   - `eligibility_passed`
   - `eligibility_reasons`
5. `expected_value_gate`
   - `edge_after_cost_bps`
   - `minimum_required_edge_bps`
6. `holding_profile_policy`
   - cooldown / earliest_reduce / earliest_reentry
7. `compliance_validator_v1`
8. `sizing_result`
9. `submit_result.stop_reason`
10. 제출 후에는 `order sync / fill sync / reconciliation`

실무적으로는 아래 순서가 가장 빠르다.

- `trade_decisions.decision_json`
- `decision_inspection`
- `guardrail_evaluations`
- `risk_limit_snapshots`
- `order_requests`
- `broker_orders`
- `fill snapshots`

---

## 15. 현재 구조를 한 문장으로 요약

현재 시스템은 **장전 종목 마스터와 장후 feature를 먼저 고정하고, 장중에는 freeze된 universe 안에서 deterministic trigger와 expected value gate로 후보를 좁힌 뒤, AI는 그 위의 해석 계층으로만 사용하고, 마지막 집행은 compliance·VaR·유동성·상태기계 guardrail이 authoritative하게 차단/허용하는 구조**다.
