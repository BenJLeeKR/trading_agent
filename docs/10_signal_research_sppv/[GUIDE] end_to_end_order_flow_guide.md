# 최초 시작부터 KIS 주문 제출·재조회까지 전체 경로 설명서

## 문서 목적

이 문서는 현재 코드 기준으로 아래를 한 번에 설명하기 위한 운영 가이드다.

1. 오늘 어떤 종목이 판단 대상으로 선정되는가
2. 선정된 종목이 어떤 정량 기준을 통과해야 `매수/매도` 판단 후보가 되는가
3. AI 판단과 deterministic 계산이 어떤 순서로 결합되는가
4. 주문이 실제로 어떤 가드레일을 통과한 뒤 KIS로 제출되는가
5. 제출 이후 체결/미체결/정합성 상태를 어떻게 다시 맞추는가

이 문서는 “정책 문서의 이상적인 목표”가 아니라, **현재 구현되어 운영 경로에 실제 반영된 내용**을 기준으로 쓴다.

이번 현행화에서는 기존 운영 흐름 설명 위에 아래 최신 진행사항을 추가 반영했다.

- `[DESIGN] signal_predictive_power_validation.md`에서 검증한 SPPV 결과
- `[DESIGN] regime_conditional_entry_signal_v1.md`에서 정리한 R3b(국면 분기형 alpha) 설계와 운영 반영 상태
- `[BACKLOG] backlog.md`, `[PRIORITY_MAP] remaining_work_priority_map.md`에 누적된 최근 구현/검증 진행 상황
- `§21 gate`, `mixedness`, `069500 benchmark`, `ENTRY_SCORE_R3B_ALPHA_ENABLED` 관련 실제 코드 반영 상태

쉽게 말해, 이 문서는 **기존 주문 흐름 설명서의 골격은 유지하되, 최근 “창 교체” 작업으로 달라진 판단 구조를 운영 담당자도 이해할 수 있게 덧붙인 버전**이다.

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
  - cycle 공통 준비
    · mixedness(국면 혼합도) 관측
    · R3b alpha percentile 선계산
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

### 1-1. 이번 개정에서 특히 달라진 핵심

기존 흐름만 보면 `entry_score`(신규 진입 후보 점수, 즉 “이 종목을 살 만한가”를 숫자로 요약한 값)가 단순히 `overall_score + fast_score + slow_score` 계열 점수 조합으로 계산되는 것처럼 이해하기 쉽다. 지금은 그 위에 아래 3개가 추가됐다.

1. **시장 공통 국면을 읽는 benchmark(069500) 경로**
2. **국면 혼합도(mixedness, 최근 시장이 한 방향인지 여러 방향이 섞였는지 보여주는 관측값) 관측 경로**
3. **R3b alpha를 cycle 단위로 선계산해 `entry_score`에 주입하는 경로**

즉 현재 decision loop는 “종목별 점수 계산”만 하는 것이 아니라, **그날 시장 상태를 먼저 읽고, 그 상태에 맞는 alpha를 종목별 판단에 넣는 구조**로 진화했다.

---

## 2. 스케줄러와 기준 시각

실행 진입점:

- [scripts/run_ops_scheduler.py](/workspace/agent_trading/scripts/run_ops_scheduler.py)
  (하루 운영 스케줄 전체를 시작하는 메인 실행 파일)

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

### 2-1. 운영 담당자가 새로 알아야 할 부분

최근 SPPV 반영 이후에는 장후 배치가 단순 참고 데이터 생산이 아니라, 아래 3가지를 동시에 책임진다.

1. 종목별 `signal_feature_snapshot` 생성(종목별 정량 feature 묶음, 다음 거래일 점수 계산의 원재료)
2. 시장 공통 국면 판정용 `069500` benchmark snapshot 생성
3. 다음 거래일 R3b alpha 선계산의 입력 데이터 준비

즉 예전보다 장후 배치의 중요도가 커졌다. 이제 장후 snapshot 배치가 비어 있거나 일부 종목이 누락되면, 단순 리포트 품질이 아니라 **다음 거래일 BUY 판단 품질 자체가 흔들린다**고 이해해야 한다.

---

## 3. 장전 준비 계층

### 3-1. Instrument Master

관련 파일:

- [scripts/sync_kis_instrument_master.py](/workspace/agent_trading/scripts/sync_kis_instrument_master.py)
  (KIS 기준 종목 기본정보를 DB에 맞추는 동기화 스크립트)
- [scripts/import_instrument_index_membership_seed.py](/workspace/agent_trading/scripts/import_instrument_index_membership_seed.py)
  (지수 편입 종목 정보를 시드 데이터로 넣는 스크립트)

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
  (거래정지·관리종목 등 “오늘 거래 가능한가” 상태를 따로 관리하는 설계 문서)

역할:

- 거래정지, 관리종목, 임시정지 같은 종목 상태성 fact를 별도로 저장한다.
- universe와 submit-time compliance가 이 정보를 읽어 차단한다.

즉:

- “종목이 존재하는가”는 `instrument master`
- “오늘 거래 가능한 상태인가”는 `instrument_status_snapshot`

으로 분리된다.

### 3-3. benchmark 종목(069500) 준비의 의미

최근 반영사항 중 중요한 변화는 `069500 (KODEX 200)`이 **거래 대상이라서가 아니라 시장 공통 국면을 읽기 위한 benchmark**로 별도 관리된다는 점이다.

운영 담당자 관점에서 이 종목은 다음 두 역할을 한다.

1. 오늘 시장이 `bullish_trend`, `range_bound`, `bearish_trend` 중 어느 쪽인지 판단
2. 최근 60거래일 동안 시장 국면이 얼마나 뒤섞였는지(`mixedness`) 계산

즉 069500는 “오늘 살 종목 후보”라기보다 **오늘 시장의 해석 기준점**이다.

---

## 4. Universe 선정 기준

관련 코드:

- [src/agent_trading/services/universe_selection.py](/workspace/agent_trading/src/agent_trading/services/universe_selection.py)
  (오늘 판단할 종목 목록을 실제로 조합하는 서비스 코드)
- [src/agent_trading/services/universe_selection_types.py](/workspace/agent_trading/src/agent_trading/services/universe_selection_types.py)
  (universe 구성에 쓰는 데이터 구조와 타입 정의)
- [plans/[POLICY] trading_universe_policy_v1.md](/workspace/agent_trading/plans/%5BPOLICY%5D%20trading_universe_policy_v1.md)
  (어떤 종목을 왜 universe에 넣는지에 대한 운영 정책 문서)

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

같은 종목이 여러 source(편입 사유 구분값, 즉 왜 이 종목이 오늘 판단 대상이 되었는가를 나타내는 라벨)에 동시에 걸리면 아래 우선순위를 따른다.

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

현재 `core`(평소 계속 추적하는 주력 종목군)는 아래 중 하나를 만족하는 종목을 seed로 쓴다.

- 승인된 core seed symbol
- `index_memberships` 또는 metadata 기준 core seed 판정
- 대형주 core universe flag

정책상 의미:

- 장기적으로 `KOSPI100` 중심 core를 유지
- `KOSDAQ`은 초기에는 core보다 `discovery / overlay / event` 계층에서 편입

### 4-4. Held Position

`held_position`(이미 계좌에 실제로 들고 있는 종목) 경로에서는 보유 수량 `> 0`인 종목을 무조건 편입한다.

특징:

- daily cap에서 제외 가능
- 이후 `sell/reduce` 판단 대상이 된다
- universe에서 빠져도 안 되는 mandatory 대상이다

### 4-5. Reconciliation Overlay

`reconciliation_overlay`(주문은 넣었지만 체결/취소/정합성이 아직 완전히 확정되지 않아 계속 추적해야 하는 종목 묶음)의 대상:

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

`event_overlay`(공시·뉴스·정책 이벤트 때문에 평소보다 우선 관찰해야 하는 종목 묶음)는 최근 external event 중 의미 있는 이벤트만 편입한다.

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

`market_overlay`(당일 시장에서 거래대금과 가격 움직임이 특히 강한 종목을 추가로 얹는 관찰 묶음)의 현재 구현 특징:

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

### 4-10. 최근 반영사항: Universe와 R3b의 관계

최근 SPPV 결과를 운영 설명에 반영하면서 분명해진 점은, **R3b는 universe를 대체하는 장치가 아니라, universe 안에서 더 잘 고르는 장치**라는 것이다.

즉 운영 관점에서는 질문이 두 단계로 나뉜다.

1. 오늘 어떤 종목을 판단 대상으로 올릴 것인가
2. 그 종목들 중 실제 BUY 후보를 누구로 고를 것인가

1번은 universe, 2번은 `entry_score`(신규 진입 후보 점수)와 그 안의 R3b alpha가 담당한다.

---

## 5. Decision Loop가 읽는 입력

관련 파일:

- [scripts/run_decision_loop.py](/workspace/agent_trading/scripts/run_decision_loop.py)
  (paper 운영에서 종목별 판단을 반복 실행하는 실제 decision loop 파일)
- [src/agent_trading/services/decision_orchestrator.py](/workspace/agent_trading/src/agent_trading/services/decision_orchestrator.py)
  (종목별 판단 입력을 모아 AI/정량/집행 경로를 묶는 오케스트레이터 서비스)

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

### 5-1. 최근 추가된 실질 입력

현재는 위 목록에 더해 아래 입력이 사실상 중요해졌다.

11. `r3b_alpha_percentile`(당일 후보군 안에서의 R3b 상대 순위 점수)
12. `§21 gate trigger_status`(국면 분기형 진입 로직을 잠글지 열지 판단하는 현재 게이트 상태)
13. `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`(paper 운영에서 위 게이트를 우회할지 정하는 설정값)
14. `mixedness` 관측 결과(직접 차단에는 미연결, 해석용)

운영 담당자는 이제 “종목 점수”만 보면 부족하다. 같은 종목이라도,

- 그날 시장 국면이 무엇이었는지
- R3b alpha percentile이 주입됐는지
- gate override가 켜져 있었는지

에 따라 실제 BUY 후보 여부가 달라질 수 있다.

### 5-2. cycle 공통 준비가 먼저 일어나는 이유

최근 R3b 반영으로 인해 decision loop는 종목별 판단 전에 아래 두 준비를 먼저 한다.

1. `mixedness` 계산
2. `R3b alpha percentile` 선계산

그 이유는 R3b가 종목 단독 점수가 아니라 **당일 후보군 전체 안에서의 상대 순위**를 써야 하기 때문이다.

---

## 6. Pre-AI 차단

AI 호출 전에 deterministic하게 먼저 막는 이유는 두 가지다.

1. 토큰 낭비 방지
2. 실행 불가능한 판단을 AI가 억지로 내리지 못하게 차단

대표 차단 축:

- stale snapshot(입력 데이터가 너무 오래되어 신뢰하기 어려운 상태)
- held position 없음(이미 들고 있는 종목 관리 경로가 필요한데 실제 보유가 없는 상태)
- reentry cooldown(방금 거래한 종목을 곧바로 다시 진입하지 못하게 하는 대기 구간)
- same signal feature snapshot reverse trade(같은 판단 기준 snapshot으로 바로 반대매매하는 것 방지)
- holding_profile earliest reduce / reentry guard(최소 보유 시간과 재진입 제한을 확인하는 보호 장치)
- 일반 BUY budget 소진
- orderable amount 부족
- source policy상 신규 진입 금지

즉 AI는 “실행 가능한 후보”에 대해서만 의미 있게 쓰인다.

### 6-1. 최근 반영사항: gate와 pre-AI 차단의 관계

현재 `§21 gate`는 실제 판단 경로에 연결돼 있다. 다만 paper 운영에서는 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true`일 때 BUY를 막지 않도록 우회할 수 있다.

업무적으로는 다음처럼 이해하면 된다.

- **gate 자체는 삭제되지 않았다.**
- 다만 paper 관측 단계에서는 override를 켜서 BUY 흐름을 막지 않는다.
- production 전환 전에는 이 override를 다시 점검해야 한다.

즉 지금 paper에서 BUY가 나오는 것은 “gate가 사라져서”가 아니라 **gate는 남아 있고, paper 관측을 위해 열어 둔 상태**다.

---

## 7. Signal Feature와 deterministic trigger

관련 파일:

- [src/agent_trading/services/signal_backbone.py](/workspace/agent_trading/src/agent_trading/services/signal_backbone.py)
  (가격·거래량·변동성 feature를 읽어 점수 계산의 재료를 만드는 신호 백본)
- [src/agent_trading/services/deterministic_trigger_engine.py](/workspace/agent_trading/src/agent_trading/services/deterministic_trigger_engine.py)
  (AI 이전에 BUY/WATCH/REDUCE/SELL 후보를 정량 규칙으로 판정하는 핵심 엔진)

### 7-1. signal_feature_snapshot 핵심 항목

현재 판단 backbone에 직접 연결되는 대표 feature:

- `overall_score`(종합 신호 점수)
- `fast_score`(단기 반응이 빠른 신호 점수)
- `slow_score`(중기 흐름 중심의 신호 점수)
- `average_volume_20d`
- `average_turnover_20d`
- `volume_surge_ratio`
- `turnover_surge_ratio`
- `atr_14_pct`
- `sma_5`, `sma_20`, `sma_60`

### 7-2. trigger 임계값

현재 고정 임계값:

- `BUY_CANDIDATE`(실제 매수 후보)
  - `entry_score >= 0.65`
- `WATCH`(당장 사지는 않지만 계속 볼 후보)
  - `watch_score >= 0.45`
- `REDUCE_CANDIDATE`(보유 비중 축소 후보)
  - `exit_score >= 0.60`
- `SELL_CANDIDATE`(청산 후보)
  - `exit_score >= 0.75`

### 7-3. 매수 entry_score 계산식

기존 `entry_score`(신규 진입 후보 점수, 즉 이 종목을 실제 매수 후보로 올릴 만큼 좋은가를 압축한 값)는 대략 아래 가중치 합으로 이해하면 된다.

- `overall_score` 정규화값 `45%`
- `fast_score` 정규화값 `20%`
- `slow_score` 정규화값 `15%`
- bullish regime bonus
- `risk_on` bonus / `risk_off` penalty
- allocation budget bonus
- strategy alignment bonus
- `market_overlay` source bonus(당일 시장 주도 종목으로 잡혔을 때 붙는 가점)
- 상대 거래량/거래대금 급증 bonus

핵심 해석:

- 단순히 AI가 좋다고 말하는 것으로는 부족하다.
- 정량 backbone이 먼저 `entry_score`를 만들어야 한다.

### 7-4. 최근 반영사항: 기존 alpha와 R3b alpha의 관계

지금은 위 설명에 중요한 단서가 하나 더 붙는다.

기존 alpha 항(`overall + fast + slow`)은 최근 SPPV 검증에서 한계가 반복 확인됐고, 그 대안으로 **R3b alpha percentile**(그날 후보군 안에서 국면 적합성이 얼마나 상위인지 보여주는 새 alpha 값)을 `entry_score` alpha 축에 넣는 경로가 실제 코드에 반영됐다.

쉽게 말하면 현재 `entry_score`는 두 층으로 이해하면 된다.

1. **alpha 중심축**
   - 기존 정적 alpha 또는 R3b alpha
2. **비 alpha 보정축**
   - risk tone, strategy, allocation, source, 활동성 등

즉 지금의 핵심 변화는 “전체 entry_score 공식을 다 바꿨다”기보다, **무엇을 더 잘 고를지 결정하는 alpha 중심축을 교체할 준비를 마쳤다**는 것이다.

### 7-5. 왜 R3b는 cycle 단위 선계산이 필요한가

기존 alpha는 종목 단위로 계산해도 됐지만, R3b는 **당일 candidate pool 안에서의 상대 percentile**이 필요하다.

그래서 현재는 cycle마다 universe 전체를 한 번 훑어,

- benchmark로 시장 공통 국면을 읽고
- 각 종목의 R3b 점수를 계산한 뒤
- 상위 candidate 안에서 percentile을 만들어
- 종목별 `request.metadata["r3b_alpha_percentile"]`(종목별 판단 함수로 넘기는 추가 입력칸)로 주입하는 구조

가 들어갔다.

운영 담당자 입장에서는 이것을 “R3b 점수표를 오늘 한 번 만들어 두고, 종목별 판단에서 재사용한다”고 이해하면 된다.

### 7-6. 매수 eligibility 조건

`BUY_CANDIDATE`가 되려면 점수만 높아서는 안 되고 아래를 모두 통과해야 한다.

1. `source_type` 허용
   - `held_position`, `reconciliation_overlay`는 신규 BUY 차단
2. `coverage_score >= 0.50`(입력 데이터가 충분히 갖춰져 있는지 보는 점수)
3. allocation budget 가능
4. 위험장 차단
   - `bearish_trend + risk_off`에서는 일반적으로 BUY 차단
   - 다만 core 일부는 예외 경로 허용 가능
5. signal floor
   - `overall_score < -0.10` 차단
   - `slow_score < -0.15` 차단
6. `average_volume_20d >= 3000`
7. 추정 `average_turnover_20d >= 50,000,000`
8. 상대 활동성(평소 대비 오늘 거래량/거래대금이 얼마나 살아 있는지)
   - `max(volume_surge_ratio, turnover_surge_ratio) >= 1.10`
9. 참여율 제한(우리 주문이 그 종목 하루 거래에서 너무 큰 비중을 차지하지 않도록 제한)
   - `recommended_max_order_value / average_turnover_20d <= 5%`
   - 추정 주문수량 / 평균거래량 `<= 3%`

즉 현재 매수는 **점수 + 실행 가능성**을 동시에 만족해야 한다.

### 7-7. risk_off core 예외 경로

`core` 종목이 `bearish_trend + risk_off`에서도 매수되려면 추가로 아래를 만족해야 한다.

- `ranking_score >= 0.48`
- `overall_score >= 0.0`
- `slow_score >= -0.05`
- `max(volume_surge_ratio, turnover_surge_ratio) >= 1.20`
- 선호 전략이 아래 중 하나
  - `defensive_low_volatility_rotation`
  - `mean_reversion_bounce`
  - `event_continuation`

### 7-8. 최근 반영사항: risk_off_penalty 해석

최근 검증에서 정리된 중요한 포인트는 다음과 같다.

- `eligibility` 축의 risk-off 차단은 R3b candidate pool에서는 사실상 거의 걸리지 않았다.
- 반면 `entry_score` 내부의 `risk_off_penalty`는 실제 기대수익을 깎는 병목으로 더 강하게 관측됐다.

운영 담당자 관점에서는 이것을 “위험장 차단 전체가 다 문제였다”가 아니라, **어느 차단은 실제로 영향이 작았고, 어느 차단은 실제로 수익 기회를 과하게 깎았는지 구분되기 시작했다**고 이해하면 된다.

### 7-9. 보유 종목 매도/축소 eligibility

`held_position` 경로(이미 보유 중인 종목을 계속 들고 갈지, 줄일지, 팔지 판단하는 경로)는 아래를 본다.

- 실제 보유수량 존재
- `coverage_score >= 0.35`
- `exit_score > 0.30`

그 위에서:

- `exit_score >= 0.60`이면 `REDUCE_CANDIDATE`
- `exit_score >= 0.75`이면 `SELL/EXIT_CANDIDATE`

### 7-10. 최근 반영사항: 실제 청산은 T+5보다 훨씬 늦다

최근 검증에서 확인된 사실은, 실제 `exit_score` 기반 청산은 생각보다 훨씬 늦게 일어나는 경우가 많다는 점이다.

업무적으로는 다음처럼 해석하면 된다.

- “신호가 T+5에서 약하면 곧바로 전략이 실패한다”는 뜻은 아니다.
- 실제 운영 로직은 대개 더 오래 보유하면서 회복/상승 구간을 기다리는 구조다.

다만 그 과정에서 MAE(중간 손실폭)가 커질 수 있으므로, 이 부분은 **수익 기회 확대와 변동성 감수의 교환관계**로 이해해야 한다.

---

## 8. Expected Value Gate

관련 파일:

- [src/agent_trading/services/expected_value_gate.py](/workspace/agent_trading/src/agent_trading/services/expected_value_gate.py)
  (좋아 보이는 거래라도 비용을 빼고 기대값이 남는지 마지막으로 점검하는 모듈)

이 계층은 “점수상 좋아 보여도 비용 차감 후 기대값이 남는가”를 본다.

### 8-1. 적용 대상

아래 decision type(실제로 포지션을 바꾸는 행동 제안)에만 강제 적용된다.

- `APPROVE`(AI/정량 기준상 진입 승인 제안)
- `BUY`(신규 매수)
- `SELL`(전량 또는 강한 청산 제안)
- `EXIT`(보유 종료)
- `REDUCE`(비중 축소)

`WATCH`, `HOLD`(당장 포지션을 바꾸지 않는 관찰/보류 상태)에는 기대값 게이트를 강제하지 않는다.

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

### 8-4. 최근 반영사항: R3b 이후에도 Expected Value Gate는 그대로 중요하다

R3b는 **더 잘 고르는 장치**이지, 거래 비용이나 슬리피지 문제를 없애는 장치는 아니다.

따라서 R3b가 들어와도 Expected Value Gate의 역할은 변하지 않는다.

- 후보를 더 잘 골라도
- 비용 대비 edge가 약하면
- 실제 주문으로 보내지지 않는다

즉 최근 작업의 방향은 “모든 차단을 없애자”가 아니라, **더 나은 후보를 고르되, 비용을 빼고도 남는 거래만 살리자**는 방향이라고 보면 된다.

---

## 9. AI 4단 체인

현재 AI 체인은 아래 순서다.

1. `Event Interpretation`
2. `AI Risk`(리스크 관점에서 보수/공격 정도를 다시 해석하는 단계)
3. `AI Compliance`(정책·제약 위반 가능성을 설명하는 단계)
4. `Final Decision Composer`(앞선 결과를 합쳐 최종 판단 문장을 만드는 단계)

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

### 9-1. 최근 반영사항: AI보다 앞서 바뀐 것은 deterministic 층이다

최근 SPPV/R3b 진행은 AI 프롬프트를 크게 바꾼 작업이 아니라, **AI 앞단의 deterministic 선별 구조를 바꾼 작업**이다.

즉 운영 담당자는 다음처럼 이해하면 된다.

- 최근 성과 개선의 핵심은 “AI가 더 똑똑해져서”가 아니다.
- 먼저 **정량적으로 더 좋은 후보를 AI 앞에 올리는 방식**이 개선된 것이다.

이 점을 이해해야 “왜 주문 흐름 설명서에 R3b, benchmark, mixedness가 중요하게 추가됐는지”가 자연스럽게 연결된다.

---

## 10. Submit 직전 hard guardrail

관련 파일:

- [src/agent_trading/services/execution_service.py](/workspace/agent_trading/src/agent_trading/services/execution_service.py)
  (판단 결과를 실제 주문 요청으로 바꾸고 제출 직전 검사를 수행하는 실행 서비스)
- [src/agent_trading/services/compliance_validator.py](/workspace/agent_trading/src/agent_trading/services/compliance_validator.py)
  (정책·상태·주문 형식 위반이 없는지 확인하는 규정 점검 모듈)

대표 차단 축:

1. `compliance_validator_v1`(제출 전 규정 위반 검사)
   - 필수 필드 누락
   - invalid order shape
   - source policy 위반
   - reconciliation overlay flat BUY 차단
   - instrument status 차단
2. `VaR`(계좌 전체 위험한도 검사)
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

즉 `reconciliation_overlay`는 알파 진입 source(좋아서 새로 사는 이유)가 아니라 상태 정리 source(주문 상태가 깔끔히 정리될 때까지 계속 추적해야 하는 이유)다.

### 10-3. 최근 반영사항: gate override와 compliance는 별개다

운영 담당자가 자주 혼동할 수 있는 부분이 있다.

- `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true`라고 해서 모든 가드레일이 풀리는 것은 아니다.
- 이것은 **§21 gate 한 축만 paper 관측용으로 우회**하는 설정이다.

즉 override를 켜도 아래는 그대로 살아 있다.

- compliance validator
- VaR
- liquidity
- reverse trade hysteresis
- sizing

따라서 현재 paper 운영은 “무방비 공격 모드”가 아니라, **R3b 관측을 위해 필요한 한 군데만 열어 둔 상태**라고 이해하는 것이 정확하다.

---

## 11. Symbol State와 churn 제어

관련 파일:

- [src/agent_trading/services/holding_profile_policy.py](/workspace/agent_trading/src/agent_trading/services/holding_profile_policy.py)
  (보유 직후 즉시 축소/재진입을 막는 보유 정책 모듈)
- [src/agent_trading/services/reverse_trade_hysteresis.py](/workspace/agent_trading/src/agent_trading/services/reverse_trade_hysteresis.py)
  (방금 산 종목을 곧바로 반대로 거래하지 못하게 완충 구간을 두는 모듈)
- [src/agent_trading/services/symbol_trade_state_machine.py](/workspace/agent_trading/src/agent_trading/services/symbol_trade_state_machine.py)
  (종목별 주문 상태를 flat/held/pending 등으로 관리하는 상태기계)

현재 주문 churn(같은 종목을 너무 자주 사고팔아 불필요한 흔들림이 생기는 현상)을 막기 위해 심볼 단위 상태를 저장한다.

핵심 상태:

- `flat`(미보유)
- `entry_pending`(진입 주문 진행 중)
- `held_active`(보유 중)
- `reduce_pending`(축소 주문 진행 중)
- `exit_pending`(청산 주문 진행 중)
- `flat_cooldown`(청산 직후 재진입 대기)

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

### 11-1. 최근 반영사항: 손절을 무조건 넣는 방향으로 가지 않은 이유

최근 검증에서는 `-15%`, `-20%` 고정 손절을 기계적으로 추가했을 때 오히려 총 기대수익이 나빠지는 결과가 확인됐다.

업무적으로는 다음처럼 이해하면 된다.

- 이 시스템은 조정 구간을 버틴 뒤 회복하는 구조가 일부 포함돼 있다.
- 그래서 단순 손절을 넣으면 좋아 보이는 리스크 관리가 실제로는 수익 기회를 더 많이 자를 수 있다.

즉 symbol state와 churn 제어는 여전히 중요하지만, **무조건 빠른 손절을 더 붙이는 쪽이 항상 정답은 아니다**는 사실이 최근 반영사항이다.

---

## 12. 주문 제출과 제출 후 수렴

### 12-1. 주문 제출

경로:

- `DecisionOrchestratorService.assemble_and_submit()`(판단 결과를 실제 제출 가능한 주문 요청으로 조립하는 상위 서비스)
- `ExecutionService`(주문 수량과 제출 가능 여부를 최종 점검하는 실행 서비스)
- `OrderManager`(내부 주문 요청을 브로커 호출 단위로 정리하는 관리자)
- `BrokerAdapter`(내부 주문 형식을 KIS 주문 호출 형식으로 번역하는 어댑터)
- KIS REST submit

### 12-2. 제출 후 확인

관련 파일:

- [scripts/run_post_submit_sync_loop.py](/workspace/agent_trading/scripts/run_post_submit_sync_loop.py)
  (주문 제출 후 실제 체결·미체결 상태를 재조회하는 후속 동기화 루프)
- [src/agent_trading/services/order_sync_service.py](/workspace/agent_trading/src/agent_trading/services/order_sync_service.py)
  (브로커 주문 상태와 내부 주문 상태를 다시 맞추는 동기화 서비스)

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

### 12-5. 최근 반영사항: paper 운영 관측의 의미

현재 paper 운영에서 중요한 것은 단순히 “주문이 나갔는가”가 아니라, **R3b 반영 후 어떤 후보가 BUY로 살아남고, 그 이유 코드가 실제 로그에 어떻게 남는가**다.

따라서 제출/체결 이후 확인 시에는 기존 주문 성공 여부 외에도 아래를 함께 보는 것이 좋다.

- `trigger_r3b_alpha_percentile` reason code가 실제 찍혔는가
- gate override가 켜진 상태였는가
- mixedness가 높은 날인지 낮은 날인지
- 기존 alpha 대비 `entry_score`가 얼마나 달라졌는가

---

## 13. 장후 feature batch

관련 파일:

- [scripts/generate_signal_feature_snapshot_input.py](/workspace/agent_trading/scripts/generate_signal_feature_snapshot_input.py)
  (어떤 종목으로 signal feature를 만들지 입력 목록을 생성하는 스크립트)
- [scripts/build_signal_feature_snapshots.py](/workspace/agent_trading/scripts/build_signal_feature_snapshots.py)
  (입력 목록을 바탕으로 실제 signal feature snapshot을 계산·저장하는 배치 스크립트)

역할:

1. 장후 universe freeze를 읽는다.
2. 시세/이벤트/기초 입력을 수집한다.
3. `signal_feature_snapshots`를 DB에 저장한다.
4. 다음 거래일 decision loop와 AI 판단의 공통 입력으로 재사용한다.

즉 장중 AI가 원시 시세를 길게 계산하는 구조가 아니라,
장후/장전 배치가 계산한 구조화 feature를 읽는 구조다.

### 13-1. 최근 반영사항: benchmark snapshot도 이 배치의 책임 범위다

이제 장후 feature batch는 일반 거래 종목 snapshot만 만드는 것이 아니다.

추가로:

- `069500` benchmark snapshot
- 시장 공통 국면 판정의 입력
- mixedness 계산의 입력
- R3b alpha 선계산의 공통 기준 데이터

까지 준비하는 역할을 가진다.

즉 배치 누락은 더 이상 “일부 리포트 누락” 수준의 문제가 아니라, **다음 거래일 alpha 계산이 비거나 왜곡될 수 있는 운영 리스크**다.

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

- `trade_decisions.decision_json`(그 cycle의 실제 판단 결과가 남는 핵심 기록)
- `decision_inspection`(판단 세부 항목을 사람이 읽기 좋게 풀어놓은 검사 뷰)
- `guardrail_evaluations`(어떤 차단 규칙이 발동했는지 남기는 기록)
- `risk_limit_snapshots`(그 시점 계좌 리스크 한도 상태 기록)
- `order_requests`(내부에서 생성된 주문 요청 기록)
- `broker_orders`(브로커로 실제 전달된 주문 기록)
- `fill snapshots`(실제 체결 결과 기록)

### 14-1. 최근 운영에서 추가로 확인할 항목

최근 진행 내용을 반영하면, 운영 담당자는 아래 5개를 추가로 보면 좋다.

1. `trigger_r3b_alpha_percentile`이 찍혔는가
2. `ENTRY_SCORE_R3B_ALPHA_ENABLED`가 실제 운영 프로세스에 반영된 상태였는가
3. `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`가 켜져 있었는가
4. 해당 cycle의 `mixedness` 버킷이 무엇이었는가
5. benchmark 069500 snapshot이 최신 상태였는가

즉 이제 “왜 주문이 안 나갔는가”는 단순히 점수와 compliance만이 아니라, **새 alpha가 실제로 작동한 날이었는지**까지 같이 봐야 정확히 해석된다.

---

## 15. 현재 구조를 한 문장으로 요약

현재 시스템은 **장전 종목 마스터와 장후 feature를 먼저 고정하고, 장중에는 freeze된 universe 안에서 deterministic trigger와 expected value gate로 후보를 좁힌 뒤, AI는 그 위의 해석 계층으로만 사용하고, 마지막 집행은 compliance·VaR·유동성·상태기계 guardrail이 authoritative하게 차단/허용하는 구조**다.

여기에 최근 추가된 운영적 핵심을 한 문장 더 붙이면 다음과 같다.

**이제 그 deterministic trigger의 핵심 alpha 축은 시장 공통 국면과 benchmark 기반 R3b percentile로 교체 가능한 상태까지 왔고, paper 운영에서는 gate override를 통해 이 새 alpha의 실제 BUY 관측을 쌓을 수 있게 됐다.**

---

## 16. 용어 사전

아래 용어 사전은 운영 담당자가 로그, 보고서, 설계 문서를 볼 때 자주 마주치는 표현을 빠르게 이해할 수 있도록 만든 참고 섹션이다.

### 16-1. 종목 묶음 / 편입 사유 관련 용어

- `source_type`
  - 그 종목이 왜 오늘 판단 대상에 들어왔는지를 나타내는 분류값
- `core`
  - 평소 계속 추적하는 주력 종목군
- `held_position`
  - 이미 계좌에 실제로 보유 중인 종목
- `reconciliation_overlay`
  - 주문은 넣었지만 체결·취소·정합성이 아직 완전히 확정되지 않아 계속 추적해야 하는 종목 묶음
- `event_overlay`
  - 공시, 뉴스, 정책 이벤트 때문에 평소보다 우선해서 봐야 하는 종목 묶음
- `market_overlay`
  - 당일 시장에서 거래대금과 가격 움직임이 강하게 살아 있는 종목을 추가로 얹는 관찰 묶음
- `manual`
  - 사람이 별도 사유로 직접 넣은 종목 묶음
- `benchmark`
  - 직접 거래하려는 종목이 아니라, 시장 상태를 읽기 위해 기준점으로 삼는 종목
- `069500 benchmark`
  - 현재 시장 공통 국면과 mixedness를 계산하는 기준 ETF인 `KODEX 200`

### 16-2. 점수 / 신호 관련 용어

- `signal_feature_snapshot`
  - 종목별 가격·거래량·변동성·이동평균·모멘텀 정보를 구조화해서 저장한 정량 입력 묶음
- `overall_score`
  - 종합 신호 점수
- `fast_score`
  - 단기 반응이 빠른 신호 점수
- `slow_score`
  - 중기 흐름 중심의 신호 점수
- `entry_score`
  - 이 종목을 실제 매수 후보로 올릴 만큼 좋은가를 압축한 신규 진입 점수
- `watch_score`
  - 당장 사지는 않지만 계속 지켜볼 가치가 있는지 보는 점수
- `exit_score`
  - 보유 종목을 줄이거나 팔아야 하는지 판단하는 점수
- `R3b alpha`
  - 시장 국면에 따라 다른 신호를 쓰는 국면 분기형 alpha 구조
- `r3b_alpha_percentile`
  - 당일 후보군 안에서 R3b 기준으로 상대적으로 얼마나 상위인지 나타내는 순위 점수
- `risk_off_penalty`
  - 위험장으로 판단될 때 `entry_score`에 감점을 주는 항목
- `coverage_score`
  - 판단에 필요한 입력 데이터가 충분히 갖춰졌는지를 보는 점수

### 16-3. 후보 / 판정 관련 용어

- `BUY_CANDIDATE`
  - 실제 매수 후보
- `WATCH`
  - 매수는 아니지만 계속 관찰할 후보
- `REDUCE_CANDIDATE`
  - 보유 비중을 줄일 후보
- `SELL_CANDIDATE`
  - 청산 후보
- `eligibility`
  - 점수 외에 유동성, 위험장, 활동성, 참여율 등 실무 조건까지 포함해 “실제로 진행 가능한가”를 보는 통과 조건
- `eligibility_passed`
  - 그 종목이 위 실무 조건까지 통과했는지 여부
- `eligibility_reasons`
  - 통과 또는 차단의 근거가 된 세부 사유 목록
- `reason_code`
  - 특정 점수 변화나 차단 사유가 왜 발생했는지 남기는 짧은 코드형 기록
- `trigger_r3b_alpha_percentile`
  - R3b alpha가 실제 `entry_score` 계산에 반영됐다는 직접 증거용 reason code

### 16-4. 시장 상태 / 국면 관련 용어

- `market_regime`
  - 오늘 시장이 상승 추세, 횡보, 하락 추세 중 어느 쪽에 가까운지 나타내는 상태값
- `bullish_trend`
  - 상승 추세 성격이 강한 시장 상태
- `range_bound`
  - 뚜렷한 방향 없이 박스권 성격이 강한 시장 상태
- `bearish_trend`
  - 하락 추세 성격이 강한 시장 상태
- `risk_on`
  - 공격적으로 진입을 보기 쉬운 시장 분위기
- `risk_off`
  - 진입에 보수적으로 접근해야 하는 시장 분위기
- `mixedness`
  - 최근 시장 국면이 한 방향인지, 여러 방향이 뒤섞였는지를 보여주는 관측값
- `저혼합`
  - 최근 시장이 비교적 한 방향으로 정리되어 있는 상태
- `중혼합`
  - 최근 시장이 어느 정도 섞여 있어 해석에 주의가 필요한 상태
- `고혼합`
  - 최근 시장이 많이 뒤섞여 있어 신호 신뢰도가 낮아질 수 있는 상태

### 16-5. gate / guardrail 관련 용어

- `§21 gate`
  - 하락장 검증이 충분하지 않을 때 국면 분기형 진입 로직을 바로 production 자본에 태우지 않도록 막는 잠금장치
- `trigger_status`
  - 현재 gate가 열려야 하는 상태인지, 닫혀야 하는 상태인지 나타내는 값
- `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`
  - paper 운영에서 `§21 gate`를 우회해 BUY 관측을 계속 흘려보낼지 정하는 설정값
- `expected_value_gate`
  - 점수가 좋아 보여도 비용과 위험을 빼고 실제 기대값이 남는지 보는 마지막 수익성 검사
- `compliance_validator_v1`
  - 정책·상태·주문 형식 위반이 없는지 확인하는 제출 전 규정 검사
- `VaR`
  - 계좌 전체 위험 한도를 넘는지 보는 리스크 검사
- `guardrail`
  - 무리한 거래나 잘못된 주문을 막기 위한 보호 규칙 전체

### 16-6. 주문 상태 / 실행 관련 용어

- `DecisionOrchestratorService`
  - 종목별 판단 입력을 모아 정량 판단, AI 판단, 주문 제출 경로를 묶는 상위 서비스
- `ExecutionService`
  - 판단 결과를 실제 주문 요청으로 바꾸고 제출 직전 검사를 수행하는 실행 서비스
- `OrderManager`
  - 내부 주문 요청을 브로커 호출 단위로 정리하는 관리자
- `BrokerAdapter`
  - 내부 주문 형식을 실제 KIS 주문 호출 형식으로 번역하는 어댑터
- `submit`
  - 주문을 브로커로 실제 전송하는 행위
- `post-submit sync`
  - 주문 제출 후 체결/미체결/거절 상태를 다시 확인해 내부 기록과 맞추는 작업
- `reconcile_required`
  - 내부 상태와 브로커 상태가 어긋났을 가능성이 있어 추가 확인이 필요한 상태
- `fill`
  - 실제 체결
- `partial fill`
  - 일부만 체결

### 16-7. 종목 상태기계 관련 용어

- `symbol_trade_state`
  - 종목별 주문/보유 상태를 관리하는 상태값
- `flat`
  - 미보유 상태
- `entry_pending`
  - 진입 주문 진행 중
- `held_active`
  - 보유 중
- `reduce_pending`
  - 축소 주문 진행 중
- `exit_pending`
  - 청산 주문 진행 중
- `flat_cooldown`
  - 청산 직후 재진입 대기 상태
- `reentry cooldown`
  - 방금 거래한 종목을 바로 다시 사지 못하게 하는 대기 구간
- `reverse trade hysteresis`
  - 방금 산 종목을 즉시 반대로 거래하지 못하게 완충 구간을 두는 장치

### 16-8. 운영 확인용 기록 / 로그 용어

- `trade_decisions.decision_json`
  - 그 cycle의 실제 판단 결과가 남는 핵심 기록
- `decision_inspection`
  - 판단 세부 항목을 사람이 읽기 좋게 풀어놓은 검사 뷰
- `guardrail_evaluations`
  - 어떤 차단 규칙이 발동했는지 남기는 기록
- `risk_limit_snapshots`
  - 그 시점 계좌 리스크 한도 상태 기록
- `order_requests`
  - 내부에서 생성된 주문 요청 기록
- `broker_orders`
  - 브로커로 실제 전달된 주문 기록
- `fill snapshots`
  - 실제 체결 결과 기록
