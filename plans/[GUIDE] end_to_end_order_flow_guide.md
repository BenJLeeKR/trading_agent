# 엔드투엔드 주문 흐름 설명서

작성 기준일: 2026-07-19  
대상 독자: 운영 담당자, 업무 담당자, 전략 검토자  
적용 범위: paper 운영 기준 현재 코드 경로 + SPPV 반영 이후의 목표 운영 구조

## 문서 목적

이 문서는 멀티 에이전트 트레이딩 시스템이 하루 동안 어떤 순서로 데이터를 준비하고, 어떤 종목을 판단 대상으로 올리며, 어떤 기준으로 `BUY / WATCH / REDUCE / SELL`을 결정하고, 주문 이후에는 어떻게 정합성을 맞추는지를 **업무 담당자도 이해할 수 있는 언어로** 설명하기 위한 운영 가이드다.

특히 이번 개정본은 아래 4가지 최신 변화까지 반영한다.

1. `signal_feature_snapshot` 기반 정량 신호 체계가 주문 흐름에 어떻게 들어가는지
2. SPPV 검증 결과를 반영한 **R3b(국면 분기형 alpha)** 가 기존 alpha를 어떤 방식으로 대체하도록 준비되었는지
3. `§21 gate`와 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`가 paper 운영에서 어떤 의미를 가지는지
4. `mixedness`(국면 혼합도) 관측이 왜 추가되었고 실제 decision loop에서 어디에 기록되는지

이 문서는 `[DESIGN] signal_predictive_power_validation.md`의 검증 결과가 운영 설계에 반영된 상태를 기준으로 설명한다. 다만 실제 거래일 관측이 더 쌓이기 전까지는 일부 항목이 “운영 경로에 반영 완료”와 “실거래 관측 축적 중”을 동시에 가질 수 있다.

---

## 1. 한눈에 보는 전체 흐름

```text
[장전/장후 배치 준비]
  ├─ instrument master / membership 동기화
  ├─ signal_feature_snapshot 입력 생성
  ├─ signal feature snapshot 적재
  └─ benchmark(069500) snapshot 포함

[decision loop 1회]
  ├─ universe 확정
  ├─ snapshot / position / cash / risk 데이터 로드
  ├─ market common regime 판정용 benchmark 조회
  ├─ mixedness(국면 혼합도) 관측
  ├─ R3b alpha candidate percentile cycle 1회 선계산
  ├─ 종목별 deterministic 판단
  │   ├─ pre-AI 차단
  │   ├─ signal feature attach
  │   ├─ entry_score / exit_score 계산
  │   ├─ BUY_CANDIDATE / WATCH / REDUCE / SELL 후보 판정
  │   └─ §21 gate / eligibility / expected value 검증
  ├─ AI 체인(EI → Risk → Compliance → FDC)
  ├─ submit translation
  └─ execution / reconciliation

[주문 후]
  ├─ post-submit sync
  ├─ fill / partial fill / reconcile_required 수렴
  └─ 다음 cycle용 상태 정리
```

핵심은 다음 한 문장으로 요약할 수 있다.

**이 시스템은 “아무 종목이나 AI가 사라고 말하면 주문하는 구조”가 아니라, 장전 배치로 만든 정량 신호와 장중 deterministic 차단을 먼저 통과한 종목만 AI 검토와 주문 단계로 보내는 구조다.**

---

## 2. 이번 개정에서 달라진 핵심 요약

기존 설명만 읽으면 이 시스템은 `overall_score + fast_score + slow_score` 중심의 정적 alpha와 일반적인 risk-off 차단을 쓰는 구조처럼 보이기 쉽다. 하지만 SPPV 검증을 거치면서 실제 운영 설계는 아래처럼 바뀌었다.

### 2-1. 기존 alpha 해석에서 바뀐 점

기존 `entry_score`의 alpha 축은 아래 3개 점수의 조합이었다.

- `overall_score`
- `fast_score`
- `slow_score`

SPPV 검증 결과, 이 조합은 상승/횡보/하락 국면을 한 덩어리로 처리할 때 기대수익률 최적화 측면에서 한계가 컸다. 특히 하락 국면에서 단기 추세형 성분이 구조적으로 약하다는 사실이 반복 확인됐다.

### 2-2. 새로 반영된 개념: R3b

이를 보완하기 위해 도입된 것이 **R3b alpha**다.

R3b는 간단히 말해,

- 시장이 비하락장일 때는 `risk_adj_momentum_3m` 계열 논리를 쓰고
- 하락장일 때는 `reversal_1m` 계열 논리를 쓰며
- 그 결과를 당일 후보군 안에서 `candidate_percentile`로 다시 순위화해
- `entry_score`의 alpha 항으로 넣는 구조

다시 말해, **“한 가지 점수로 모든 시장을 설명하려 하지 않고, 시장 국면에 따라 다른 성격의 신호를 쓰는 구조”**가 이번 설계의 핵심이다.

### 2-3. paper 운영에서 이미 정리된 부분

현재 paper 운영 기준으로는 아래 3가지가 코드상 준비되어 있다.

- `ENTRY_SCORE_R3B_ALPHA_ENABLED`가 켜지면 R3b alpha percentile을 실제 `entry_score`에 반영할 수 있다.
- `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`가 켜지면 paper 운영에서 `§21 gate` 때문에 BUY가 막히지 않는다.
- `mixedness`(국면 혼합도)는 실제 decision loop에서 매 cycle 관측/로그 기록된다.

즉 운영 흐름은 더 이상 “옛 설계만 문서에 있고 코드는 옛 상태인 단계”가 아니라, **새 설계가 실제 운영 경로 안으로 들어온 상태**로 이해하는 것이 맞다.

---

## 3. 운영자가 알아야 할 큰 구조

업무 담당자 입장에서 시스템은 아래 5개 층으로 보면 이해가 쉽다.

1. **준비층**: 오늘 판단에 필요한 종목/시세/feature를 미리 준비
2. **선별층**: 오늘 어떤 종목을 볼지 universe를 확정
3. **정량판단층**: 점수, 차단 규칙, 기대값으로 1차 판단
4. **AI판단층**: 정량판단을 통과한 후보에 대해 해석 보강
5. **집행·정합성층**: 실제 제출, 체결 확인, 상태 복구

이번 문서 개정은 특히 3번 정량판단층이 많이 바뀌었다. 그 바뀐 내용을 중심으로 아래에서 순서대로 설명한다.

---

## 4. 장전·장후 준비: 오늘 판단의 재료를 만드는 단계

### 4-1. instrument master / membership

관련 경로:

- `scripts/sync_kis_instrument_master.py`
- `scripts/import_instrument_index_membership_seed.py`

역할:

- 어떤 종목이 거래 가능한지 기본 정보를 맞춘다.
- 지수 편입 정보(`KOSPI100`, `KOSPI200`, `KOSDAQ150`)를 보강한다.
- 이후 universe 선정과 compliance가 이 정보를 기준으로 동작한다.

업무적으로는 “오늘 판단 가능한 종목의 모수”를 맞추는 단계라고 보면 된다.

### 4-2. signal feature snapshot 준비

관련 경로:

- `scripts/generate_signal_feature_snapshot_input.py`
- `scripts/build_signal_feature_snapshots.py`
- `src/agent_trading/api/routes/signal_feature_snapshots.py`

역할:

- 종목별 가격·거래량·변동성·이동평균·모멘텀 신호를 구조화된 snapshot으로 저장한다.
- 장중에 무거운 계산을 매번 다시 하지 않고, 읽기 전용 입력으로 재사용한다.

이 snapshot이 없으면 `entry_score`, `exit_score`, R3b alpha, mixedness 관측 모두 불완전해진다. 따라서 이 배치는 단순 보조 작업이 아니라 **주문 판단의 원재료 생산 단계**다.

### 4-3. 069500 benchmark가 왜 중요한가

관련 경로:

- `scripts/generate_signal_feature_snapshot_input.py`
- `scripts/run_decision_loop.py`

이번 SPPV에서 새로 분명해진 사실은, R3b alpha와 mixedness 관측은 일반 거래 종목만으로는 충분하지 않고 **시장 공통 국면을 읽는 벤치마크**가 반드시 필요하다는 점이다.

현재 그 역할을 하는 것이 `069500 (KODEX 200)`이다.

이 종목은 거래 후보 universe 자체를 넓히기 위한 것이 아니라 아래 두 목적을 가진다.

1. 오늘 시장이 `bullish / range_bound / bearish` 중 어느 쪽인지 판단
2. 최근 60거래일 동안 시장 국면이 얼마나 섞여 있는지(`mixedness`) 계산

즉 069500 snapshot은 “주문 대상 종목”이라기보다 **시장 온도계**에 가깝다.

### 4-4. 이번 기준으로 완료된 준비 상태

지금은 다음 조건이 충족된 상태를 기준으로 운영을 설명한다.

- benchmark 069500가 signal feature batch 입력에 포함된다.
- benchmark snapshot이 DB에 실제로 적재된다.
- decision loop는 그 benchmark snapshot을 읽어 국면과 mixedness를 계산할 수 있다.

---

## 5. Universe: 오늘 무엇을 볼 것인가

관련 경로:

- `src/agent_trading/services/universe_selection.py`
- `src/agent_trading/services/universe_selection_types.py`
- `plans/[POLICY] trading_universe_policy_v1.md`

Universe는 “오늘 AI와 점수 계산을 돌릴 대상 종목 목록”이다.

### 5-1. Universe 구성 순서

현재 구조는 대략 아래 우선순위를 따른다.

1. `core`
2. `held_position`
3. `reconciliation_overlay`
4. `event_overlay`
5. `manual`
6. `market_overlay`
7. exclusion / cap / priority sort

### 5-2. 업무적 해석

- `core`: 평소 지속 관찰할 주력 종목군
- `held_position`: 이미 들고 있는 종목, 반드시 계속 봐야 함
- `reconciliation_overlay`: 주문 상태가 애매한 종목, 안전성 때문에 강제 추적
- `event_overlay`: 공시/이벤트 때문에 별도 관찰이 필요한 종목
- `market_overlay`: 당일 시세/유동성 움직임이 강한 종목

즉 universe는 “알파 후보”만이 아니라, **안전하게 계속 추적해야 할 종목**까지 포함하는 운영 목록이다.

### 5-3. 왜 universe가 여전히 중요한가

R3b alpha가 좋아졌다고 해서 universe가 덜 중요해지는 것은 아니다.

R3b는 universe 안의 종목을 더 잘 고르는 장치이지, universe 자체를 대신하는 장치는 아니다. 따라서 운영 관점에서는 다음 두 질문이 분리된다.

1. 오늘 어떤 종목을 판단 대상으로 올릴 것인가?
2. 그 안에서 어떤 종목을 실제 BUY 후보로 올릴 것인가?

첫 번째가 universe, 두 번째가 R3b를 포함한 `entry_score` 계층이다.

---

## 6. Decision loop 시작 시 매 cycle마다 준비되는 것

관련 경로:

- `scripts/run_decision_loop.py`
- `src/agent_trading/services/decision_orchestrator.py`

Decision loop는 종목 하나씩 바로 판단하지 않는다. 먼저 cycle 단위로 공통 준비를 한다.

### 6-1. cycle 공통 준비 1: mixedness 체크

`_run_mixedness_check()`가 cycle마다 1회 실행된다.

이 함수는 benchmark 최근 60거래일을 보고,

- 저혼합
- 중혼합
- 고혼합

중 어디에 해당하는지 계산해 로그로 남긴다.

업무 의미:

- **저혼합**: 한 방향 시장이 비교적 뚜렷한 상태
- **고혼합**: 상승/횡보/하락이 자주 섞여 신호 신뢰도가 낮아질 수 있는 상태

이 값은 현재 BUY/SELL를 직접 막지는 않지만, **오늘 신호를 얼마나 신뢰할지 해석하는 보조 지표**다.

### 6-2. cycle 공통 준비 2: R3b alpha percentile 선계산

`_build_r3b_alpha_percentile_overrides_for_cycle()`가 cycle마다 1회 실행된다.

이 함수가 하는 일은 다음과 같다.

1. benchmark snapshot으로 시장 공통 국면을 본다.
2. 오늘 universe 전체를 순회하며 R3b 입력값을 모은다.
3. R3b 점수를 계산한다.
4. candidate pool 상위 20% 안에서 percentile을 만든다.
5. 종목별 percentile dict를 만든다.
6. 이후 종목별 판단 시 `request.metadata["r3b_alpha_percentile"]`로 주입한다.

업무적으로는 “오늘 한 번 만들어 둔 R3b 점수표를 종목별 판단에서 재사용한다”라고 이해하면 된다.

### 6-3. 왜 cycle 선계산이 필요한가

기존 `entry_score`는 종목 하나씩 계산해도 됐지만, R3b는 **당일 후보군 전체 안에서의 상대 순위**가 필요하다.

즉 R3b는 종목 단독 점수가 아니라,

- 오늘 누구와 같이 후보에 올랐는지
- 그 안에서 어느 정도 상위인지

를 알아야 한다. 그래서 cycle 단위 선계산이 필요하다.

---

## 7. 종목별 판단 직전 입력

종목 하나가 판단 단계로 들어가기 전에 붙는 대표 입력은 아래와 같다.

1. 최신 `position_snapshot`
2. 최신 `cash_balance_snapshot`
3. 최신 `risk_limit_snapshot`
4. 최신 `signal_feature_snapshot`
5. 시장 공통 국면(`market common regime`)
6. 전략 선택(`strategy_selection`)
7. 자본 배분 정보(`portfolio_allocation`, 가능할 때)
8. 최근 external event
9. `symbol_trade_state`
10. instrument status / trading halt 정보
11. `r3b_alpha_percentile` (활성 시)
12. `§21 gate` trigger status / override 상태

즉 한 종목의 BUY 여부는 단순히 “점수가 높다” 하나로 정해지지 않는다. **점수, 시장 상태, 자금 상태, 이벤트 상태, 주문 상태**가 함께 들어간다.

---

## 8. deterministic 판단: AI보다 먼저 하는 1차 선별

관련 경로:

- `src/agent_trading/services/deterministic_trigger_engine.py`
- `src/agent_trading/services/expected_value_gate.py`

업무 담당자가 가장 중요하게 봐야 할 부분이다.

### 8-1. 왜 AI 전에 deterministic 차단을 하는가

이유는 두 가지다.

1. 실행 불가능한 종목을 AI가 억지로 사라고 말하지 못하게 하기 위해
2. 토큰과 시간 낭비를 줄이기 위해

즉 deterministic 계층은 “보수 장치”만이 아니라, **실제로 주문 가능한 후보를 AI 앞에 정리해 주는 전처리 장치**다.

### 8-2. 주요 점수

대표 점수는 아래 3개다.

- `entry_score`: 신규 진입용 점수
- `watch_score`: 관심 유지용 점수
- `exit_score`: 축소/청산용 점수

실제 임계값은 대략 다음과 같다.

- `BUY_CANDIDATE`: `entry_score >= 0.65`
- `WATCH`: `watch_score >= 0.45`
- `REDUCE_CANDIDATE`: `exit_score >= 0.60`
- `SELL_CANDIDATE`: `exit_score >= 0.75`

### 8-3. 기존 entry_score와 현재 entry_score의 차이

#### 기존 해석

기존 entry alpha는 아래 3개 조합이 중심이었다.

- `overall_score` 45%
- `fast_score` 20%
- `slow_score` 15%

그리고 여기에 다음 보정이 붙었다.

- risk_on / risk_off
- allocation bonus
- strategy alignment bonus
- market_overlay bonus
- 상대 활동성 bonus

#### 현재 반영 상태

현재는 config가 켜지면 기존 alpha 자리에 **`0.80 * r3b_alpha_percentile`**이 들어갈 수 있도록 준비되어 있다.

즉 entry_score는 이제 아래처럼 이해하는 것이 맞다.

- **alpha 중심축**: 기존 정적 alpha 또는 R3b alpha
- **비 alpha 보정축**: strategy, allocation, source, 활동성, risk tone 등

이 구조 분리는 매우 중요하다. 이유는 다음과 같다.

- “무엇을 더 잘 고를 것인가”는 alpha 축 문제
- “실행 가능성과 운영 안전성은 어떤가”는 보정축 문제

이 둘을 같은 문제로 섞어 보면 판단이 계속 흐려진다.

---

## 9. R3b alpha가 실제로 하는 일

### 9-1. 쉬운 설명

R3b는 “시장이 어떤 상태인지에 따라 다른 성격의 좋은 종목을 찾는 방식”이다.

- 시장이 비교적 정상적이거나 상승/횡보 성격일 때는 **안정적 추세/모멘텀**을 더 믿는다.
- 시장이 하락 성격일 때는 **단기 반등/되돌림** 쪽이 더 잘 작동할 수 있다고 본다.

즉 “상승장에서도, 하락장에서도, 같은 기준으로 좋은 종목을 고르겠다”는 발상을 버린 것이 R3b다.

### 9-2. 왜 percentile을 쓰는가

R3b는 절대점수 하나보다 **오늘 후보군 안에서 상대적으로 얼마나 좋은가**가 중요하다.

그래서 최종적으로는 원시 점수를 그대로 쓰지 않고 candidate pool 안에서 percentile로 바꿔 `entry_score`에 넣는다.

이렇게 하면,

- 오늘 후보가 전반적으로 다 약한 날
- 오늘 후보가 전반적으로 다 강한 날

을 구분하면서도, **그날의 상대 우수 종목을 더 일관되게 고를 수 있다.**

### 9-3. 현재 운영 스위치

관련 설정:

- `ENTRY_SCORE_R3B_ALPHA_ENABLED`

의미:

- `false`: 기존 alpha 구조 유지
- `true`: R3b alpha percentile을 entry_score alpha 축에 반영

현재 paper 운영 설명은 이 값이 실제 운영 프로세스까지 전달된 상태를 기준으로 한다.

---

## 10. §21 gate와 override의 의미

관련 경로:

- `src/agent_trading/services/regime_switch_gate.py`
- `src/agent_trading/services/deterministic_trigger_engine.py`
- `src/agent_trading/services/decision_orchestrator.py`
- `scripts/run_decision_loop.py`

### 10-1. §21 gate가 원래 왜 있었는가

이 gate는 “하락장 검증이 아직 충분하지 않은 상태에서, 국면 분기형 진입 로직을 실운영 BUY 판단에 바로 반영하는 것을 막기 위한 잠금장치”다.

즉 목적은 단순 보수화가 아니라,

- 아직 검증이 덜 된 하락 국면 구간을 production 자본에 곧바로 태우지 않기 위한 것

이다.

### 10-2. 지금 paper에서는 왜 override를 쓰는가

현재는 paper / shadow 관측을 통해 데이터를 더 쌓아야 하는 단계다. 그런데 gate가 production과 동일하게 항상 잠겨 있으면, paper에서도 R3b BUY 흐름이 막혀 실제 관측이 불가능해진다.

그래서 현재는 다음 설정을 통해 paper 운영에서 gate 잠금을 우회할 수 있게 했다.

- `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true`

업무적으로는 다음처럼 이해하면 된다.

- **gate 로직 자체는 남겨둔다.**
- 다만 paper에서는 override를 켜서 BUY 관측을 계속 흘려보낸다.
- production 전환 전에는 override를 다시 검토한다.

### 10-3. 운영자가 알아야 할 점

현재 paper에서 BUY가 흐른다고 해서 gate가 없어졌다는 뜻은 아니다. 정확한 상태는 다음과 같다.

1. gate 판단 경로는 코드에 실제 연결돼 있다.
2. override가 켜져 있으므로 paper에서는 gate가 BUY를 막지 않는다.
3. production 전환 시에는 override 해제 여부를 다시 검토해야 한다.

즉 지금 상태는 **“게이트를 버린 것”이 아니라 “paper 관측을 위해 잠시 열어 둔 상태”**다.

---

## 11. mixedness(국면 혼합도)가 왜 필요한가

관련 경로:

- `src/agent_trading/services/regime_mixedness_monitor.py`
- `scripts/run_decision_loop.py`

SPPV 검증에서 확인된 중요한 사실 중 하나는, R3b가 항상 동일 강도로 잘 작동하지는 않고 **국면이 한 방향으로 뚜렷할 때 더 강하고, 여러 국면이 섞일수록 신뢰도가 약해지는 경향**이 있다는 점이다.

이 때문에 mixedness 관측이 추가됐다.

### 11-1. 업무적 의미

- `저혼합`: 오늘 시장 해석이 비교적 단순하다. R3b 신뢰도가 상대적으로 높을 수 있다.
- `중혼합`: 신호는 여전히 쓸 수 있지만 해석에 주의가 필요하다.
- `고혼합`: 시장이 뒤섞여 있어 같은 alpha라도 신뢰도가 낮아질 수 있다.

### 11-2. 현재 역할

중요한 점은 mixedness가 **현재는 관측용**이라는 것이다.

즉 현재는:

- BUY/SELL를 직접 막지 않고
- decision loop 로그에 남아
- 운영자가 “오늘은 혼합도가 높아 신호 해석에 주의가 필요하다”를 볼 수 있게 한다.

이 설계는 과도한 방어 로직 추가를 피하면서도, **해석 품질은 높이려는 절충안**이다.

---

## 12. BUY 후보가 되는 실제 조건

### 12-1. 단순히 점수만 높다고 BUY가 되지 않는 이유

`entry_score`가 높더라도 아래를 통과하지 못하면 실제 BUY 후보가 되지 않는다.

대표 조건:

1. source_type 허용 여부
2. coverage_score 기준 충족
3. allocation budget 가능 여부
4. 기본 유동성 기준
5. 평균 거래대금 기준
6. 상대 활동성 기준
7. 참여율 제한
8. signal floor(너무 약한 overall/slow 차단)
9. expected value gate 통과
10. 현재 gate / override / eligibility 규칙 충족

즉 BUY는 “좋아 보이는 종목”이 아니라,

**좋아 보이고 + 지금 계좌/시장/유동성 조건에서 실제로 들어가도 되는 종목**

만 올라오도록 설계돼 있다.

### 12-2. R3b 반영 이후의 업무 해석

R3b를 켠 뒤에는 BUY 후보의 의미가 조금 달라진다.

기존에는 “기존 alpha 조합에서 높은 점수를 받은 종목”이었다면,
이제는 “오늘 국면에 맞는 R3b 논리로 상위 percentile을 받은 종목”이 된다.

이 차이는 실무적으로 꽤 크다. 같은 종목이라도,

- 예전에는 fast/slow 조합에서 높은 점수를 받지 못해 탈락했을 수 있고
- 지금은 같은 날 후보군 안에서 상대적으로 더 좋은 국면 적합 신호를 받아 통과할 수 있다.

---

## 13. AI 4단 체인과 deterministic의 역할 분담

현재 AI 체인은 대략 다음 순서로 본다.

1. Event Interpretation
2. AI Risk
3. AI Compliance
4. Final Decision Composer

업무적으로 가장 중요한 원칙은 다음이다.

### 13-1. deterministic이 authoritative source다

이 시스템에서 authoritative source는 AI가 아니라 deterministic backend다.

의미:

- 점수 계산
- 유동성 차단
- budget 차단
- expected value 검증
- entry / exit candidate 판정

은 정량 코드가 우선한다.

AI는 그 위에서 해석과 설명, 추가 맥락 보강을 한다.

### 13-2. 왜 이렇게 나눴는가

이 구조가 필요한 이유는,

- AI가 강하게 BUY를 말해도 실행 불가능 종목은 막아야 하고
- 반대로 정량 backbone이 충분히 강한 종목은 AI가 과도하게 소심해도 운영 원칙이 흔들리지 않아야 하기 때문이다.

즉 AI는 **보조 판단 계층**, deterministic은 **집행 기준 계층**이다.

---

## 14. Expected Value Gate: “좋아 보여도 돈이 되는가?”

관련 경로:

- `src/agent_trading/services/expected_value_gate.py`

이 계층은 단순히 점수만 보는 것이 아니라,

- 기대 수익
- 예상 하방 위험
- 비용
- 슬리피지

를 같이 본다.

### 14-1. 업무적 의미

쉽게 말해,

“이 종목이 좋아 보여도 비용과 위험을 빼고 나면 실제로 남는 기대값이 있는가?”

를 검토하는 마지막 정량 게이트다.

### 14-2. 왜 R3b 이후에도 여전히 필요한가

R3b는 **더 잘 고르는 장치**이지, 비용과 슬리피지 문제를 없애는 장치는 아니다.

따라서 R3b가 들어와도 expected value gate는 그대로 중요하다.

- 종목 선별력이 좋아져도
- 유동성이 부족하거나
- 비용 대비 edge가 약하면
- submit 단계로 보내지 않는 구조는 유지된다.

즉 “창을 날카롭게 만든다”와 “손실이 큰 거래를 막는다”는 서로 다른 역할이다.

---

## 15. 주문 제출 직전: execution 계층이 마지막으로 보는 것

관련 경로:

- execution service
- compliance validator
- order manager / broker adapter

이 단계에서는 전략적 판단보다 **실제 제출 가능성**이 중심이다.

대표 확인 사항:

- 주문 수량 산정
- compliance validator 통과 여부
- VaR / liquidity / probe churn / reverse trade / sell guard
- broker adapter submit 가능 여부

업무적으로는 “좋은 아이디어인지”가 아니라 “지금 이 계좌에서 이 주문을 실제로 넣어도 되는지”를 다시 묻는 단계다.

---

## 16. 주문 후 정합성: submit이 끝이 아니다

주문 제출 이후에는 다음이 중요하다.

1. 제출 성공 여부 확인
2. 체결 / 부분체결 / 미체결 상태 추적
3. `reconcile_required` 여부 확인
4. snapshot refresh
5. 다음 cycle에서 보유/주문 상태를 authoritative truth로 재수렴

이 단계가 중요한 이유는, 주문이 실제로 나갔다고 해서 시스템 상태가 자동으로 맞아지는 것이 아니기 때문이다.

운영 담당자 입장에서는 **“주문 제출 성공”보다 “제출 후 상태가 시스템에 정확히 반영되었는지”**를 더 중요하게 봐야 한다.

---

## 17. 이번 개정 기준 paper 운영 해석

현재 paper 운영 기준으로는 다음처럼 이해하는 것이 가장 정확하다.

### 17-1. 이미 준비된 것

- R3b alpha 교체 코드 경로는 end-to-end로 구현돼 있다.
- benchmark 069500 snapshot 문제는 해소됐다.
- `ENTRY_SCORE_R3B_ALPHA_ENABLED`는 compose를 통해 ops-scheduler 컨테이너까지 전달된다.
- `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`도 동일하게 전달된다.
- mixedness 관측은 실제 decision loop에서 동작한다.

### 17-2. paper에서 현재 의미하는 것

따라서 paper 운영에서는,

- gate 때문에 BUY가 원천 차단되는 상태는 아니고
- R3b alpha가 실제 entry_score에 반영될 준비가 끝난 상태이며
- 다음 실제 거래일 cycle에서는 `trigger_r3b_alpha_percentile`이 관측될 수 있는 상태

로 이해하면 된다.

### 17-3. 아직 남아 있는 것

다만 아래는 여전히 후속 확인 대상이다.

- 다음 실제 거래일에서 reason_code / entry_score 변화가 실제 운영 로그에 관측되는지
- mixedness가 높을 때 BUY 품질이 어떻게 보이는지
- `portfolio_allocation`이 실제 계좌 상태와 결합될 때 영향이 있는지
- 실거래 전환 시 §21 gate override를 어떤 절차로 다시 잠글지

즉 구현은 많이 완료됐지만, 운영 담당자는 **“코드 완료”와 “실거래 검증 완료”를 같은 뜻으로 보면 안 된다.**

---

## 18. 운영자가 가장 자주 확인해야 할 설정값

### 18-1. R3b alpha 스위치

- `ENTRY_SCORE_R3B_ALPHA_ENABLED`

의미:

- `true`: R3b alpha percentile 반영
- `false`: 기존 alpha 유지

### 18-2. §21 gate override 스위치

- `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`

의미:

- `true`: paper 관측 단계에서 gate로 BUY를 막지 않음
- `false`: gate 상태에 따라 BUY 차단 가능

### 18-3. 운영 해석 원칙

현재 paper 운영에서는 두 값이 모두 중요하다.

- 첫 번째는 **새 신호를 실제로 쓸 것인가**를 결정하고
- 두 번째는 **그 신호를 gate 때문에 paper에서도 막을 것인가**를 결정한다.

---

## 19. 운영 로그에서 보면 좋은 포인트

업무 담당자가 다음 거래일에 실제로 확인하면 좋은 포인트는 아래다.

### 19-1. mixedness 로그

확인 목적:

- 오늘 시장이 저혼합 / 중혼합 / 고혼합 중 어디인지
- 오늘 신호 해석에 주의를 더 줘야 하는지

### 19-2. R3b reason code

대표 확인 포인트:

- `trigger_r3b_alpha_percentile`

의미:

- R3b alpha가 실제 entry_score 계산에 들어갔다는 직접 증거

### 19-3. entry_score 변화

동일 종목 기준으로,

- 기존 alpha일 때보다
- R3b 반영 시 entry_score가 어떻게 변했는지

를 보면 실제 영향도를 파악할 수 있다.

### 19-4. gate 관련 상태

대표 확인 포인트:

- 현재 trigger_status
- override 적용 여부
- BUY 차단이 gate 때문인지, 다른 eligibility 때문인지

운영에서 “BUY가 안 나왔다”는 결과만 보고 해석하면 안 되고, **왜 안 나왔는지 원인을 분리**해 보는 것이 중요하다.

---

## 20. 이 문서 기준으로 이해해야 할 현재 결론

현재 주문 흐름은 더 이상 단순한 “기존 alpha + 일반 차단 규칙” 체계가 아니다.

현행화된 흐름을 한 문장으로 정리하면 다음과 같다.

**시장 공통 국면과 benchmark 기반 신호를 읽어, cycle 단위로 R3b percentile을 선계산하고, 그 값을 entry_score alpha 축에 주입한 뒤, deterministic 차단과 기대값 검증을 통과한 후보만 AI와 주문 단계로 보내는 구조**다.

그리고 paper 운영 기준으로는,

- R3b alpha 경로는 코드상 연결 완료
- benchmark 결측 해결 완료
- env/compose 배선 완료
- gate override 반영 완료
- mixedness 관측 경로 반영 완료

상태로 보는 것이 맞다.

즉 지금 운영 설명의 초점은 “이 설계가 가능한가?”가 아니라,

**“이제 실제 거래일에서 이 설계가 어떤 관측값을 만들기 시작하는가?”**

로 넘어왔다.

---

## 21. 업무 담당자용 마지막 요약

### 21-1. 지금 시스템이 하는 일

- 오늘 볼 종목을 universe로 정한다.
- 장후 배치로 만든 signal feature snapshot을 읽는다.
- benchmark 069500로 시장 공통 국면과 mixedness를 읽는다.
- R3b를 켜면 당일 후보군 안에서 percentile을 계산해 entry_score alpha에 넣는다.
- deterministic 차단과 expected value gate를 통과한 종목만 AI 검토 및 주문 후보가 된다.
- 주문 후에는 체결/미체결/정합성을 다시 맞춘다.

### 21-2. 이번 개정의 실질적 의미

이번 개정으로 운영 문서는 이제 다음 질문에 답할 수 있게 됐다.

1. 왜 benchmark 069500가 필요한가?
2. 왜 R3b는 종목별 단일 계산이 아니라 cycle 선계산이 필요한가?
3. 왜 paper에서는 gate override를 켜 두는가?
4. mixedness는 BUY를 막는 장치인가, 관측 장치인가?
5. R3b가 기존 alpha를 어디서 어떻게 대체하는가?

### 21-3. 운영자가 다음으로 봐야 할 것

- 다음 실제 거래일에 `trigger_r3b_alpha_percentile`이 실제로 관측되는지
- mixedness 버킷과 BUY 후보 품질이 어떻게 같이 움직이는지
- R3b 반영 후 BUY / WATCH / HOLD 분포가 어떻게 달라지는지
- production 전환 전 gate override를 다시 잠글 시점과 조건이 무엇인지

이 네 가지가 앞으로의 paper 관측 단계에서 가장 중요한 확인 포인트다.
