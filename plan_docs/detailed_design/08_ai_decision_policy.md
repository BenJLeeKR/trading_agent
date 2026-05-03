# 최고 기대수익률 지향 AI 매매 판단 설계 v1

## 1. 목적

이 문서는 엔터프라이즈급 매매 시스템에서 **매매 판단 AI가 어떤 과정을 통해 기대수익률을 추구할지**를 정의한다.

핵심 전제는 다음과 같다.

- 시스템의 목표는 단순 승률이 아니라 **위험조정 기대수익률의 장기 최대화**다.
- AI는 단순 설명 계층이 아니라 **전략 선택, 진입, 청산, 가격, 수량**을 판단하는 주체다.
- 그러나 AI는 무제한 자유 판단을 하지 않고, **시장 가설, feature 체계, regime 판단, sizing 규칙, 성과 피드백 루프** 위에서 동작해야 한다.

이 문서는 다음 질문에 답해야 한다.

1. 무엇을 시장 비효율로 보고 수익을 추구하는가
2. 어떤 입력을 어떤 순서로 해석하는가
3. 여러 Agent의 판단은 어떻게 통합되는가
4. 확신도와 기대수익은 어떻게 주문 크기와 연결되는가
5. 성과가 악화되면 어떤 전략이나 feature를 감쇠하는가

## 2. 설계 원칙

### 2.1 최우선 목표

- 절대 수익률보다 **위험조정 기대수익률**을 최대화한다.
- 고수익 신호라도 tail risk, 유동성 위험, 체결 위험이 크면 비중을 낮춘다.
- 단일 강신호보다 **다수 독립 신호의 일관성**을 더 높게 평가한다.

### 2.2 AI 판단 방식

- AI는 “좋아 보이는 종목 추천기”가 아니라 **확률적 의사결정기**다.
- 각 판단은 반드시 아래 형태를 가져야 한다.
  - 기대수익
  - 기대손실
  - 확신도
  - 보유기간 가설
  - 실패 시나리오
  - 반대 근거

### 2.3 기대수익률 정의

실무적으로는 다음 값을 직접 또는 근사치로 추정해야 한다.

```text
Expected Alpha Score
= regime-adjusted expected upside
- expected downside
- liquidity penalty
- slippage penalty
- volatility penalty
- crowding penalty
- event risk penalty
```

즉, “상승 가능성”만 보는 것이 아니라 **실현 가능한 순 기대값**을 봐야 한다.

### 2.4 Fast / Slow 계층 분리

- 모든 Agent를 동일 latency budget으로 다루면 안 된다.
- LLM 기반 분석 Agent와 실주문 직전 실행 Agent는 분리해야 한다.
- **Slow Agent**는 시장 해석, 전략 선택, 가중치 갱신을 담당한다.
- **Fast Agent**는 실시간 진입 타이밍, 가격, 수량, 주문 제출 직전 검증을 담당한다.

권장 분리:

- Slow Layer
  - Market Regime Agent
  - Universe Selection Agent
  - Strategy Selection Agent
  - News / Event Agent
  - 일부 Signal summarization Agent

- Fast Layer
  - Feature Generator
  - execution-oriented Signal scorer
  - Order Construction Agent
  - hard validation path
  - mathematical scoring engine

규칙:

- intraday breakout, opening range breakout, fast re-entry 같은 전략은 Slow Agent 단독 판단으로 주문하면 안 된다.
- LLM은 방향성과 컨텍스트를 제공하되, 초단기 체결 시점 결정은 더 빠른 계층이 맡아야 한다.
- Fast Layer는 Python rule engine, 전통적 ML 모델, 사전 계산된 score lookup 또는 deterministic backend calculator로 구현하는 것을 우선 권장한다.

### 2.5 수리 연산과 서술 추론 분리

- LLM은 텍스트 해석과 가설 생성에는 강하지만, 세밀한 수치 계산에는 취약할 수 있다.
- 따라서 **최종 사칙연산, 점수 합성, 사이징 계산, 한도 검증은 LLM이 아니라 backend math engine이 수행해야 한다.**

원칙:

- 각 Agent는 점수와 근거를 구조화된 JSON으로 출력한다.
- 최종 `Final Trade Score`, `Position Size`, `Expected Alpha Score`는 별도 수학 엔진이 계산한다.
- LLM Composer는 계산기가 아니라 **해석기, 조정기, 설명기**에 가깝게 사용한다.

### 2.6 고빈도 원시 데이터 압축

- 호가/체결, tick, 거래대금 변화 같은 원시 데이터는 그대로 LLM에 전달하지 않는다.
- Feature Generator가 이를 **핵심 통계량, percentile, z-score, 상태 라벨, 짧은 구조화 서술**로 압축해야 한다.

규칙:

- LLM 프롬프트에는 raw orderbook dump를 넣지 않는다.
- 고빈도 데이터는 먼저 숫자 요약과 이벤트 태그로 변환한다.
- 가능한 경우 feature snapshot 하나당 토큰 예산을 명시적으로 제한한다.

### 2.7 비용 및 Rate Limit 예산

- AI 판단 품질만 보지 말고, 토큰 비용과 API rate limit도 설계 변수로 본다.
- Universe Selection Agent는 **수익 기회 탐색기**이면서 동시에 **비용과 병목을 제어하는 gatekeeper**여야 한다.

원칙:

- 후보군은 과도하게 넓히지 않는다.
- 뒤단 Slow Agent 호출 대상은 하루 또는 세션 단위 예산 아래로 제한한다.
- 비용 초과 시 추가 분석보다 기존 후보군 재정렬을 우선한다.

## 3. 수익 창출 가설

AI 판단 계층은 아래 비효율을 공략하는 복합 알파 구조를 가진다.

### 3.1 가격 모멘텀

- 단기 및 중기 상대강도 우위 종목은 일정 기간 추가 초과수익을 낼 가능성이 있다.
- 단, 과열 구간에서는 리스크 패널티를 적용한다.

### 3.2 거래대금 및 수급 변화

- 거래대금 증가와 수급 쏠림은 추세 지속 가능성을 높인다.
- 기관/외국인 순매수, 순위 급상승, 거래량 급증은 돌파 지속 조건으로 사용한다.

### 3.3 이벤트/뉴스 재평가

- 공시, 실적, 정책, 업황 변화는 가격에 즉시 완전히 반영되지 않을 수 있다.
- 뉴스/공시는 단순 sentiment가 아니라 **earnings impact, horizon, uncertainty**로 구조화한다.

### 3.4 Regime-dependent edge

- 상승장과 횡보장과 하락장은 유효 전략이 다르다.
- 같은 feature도 regime에 따라 가중치를 바꿔야 한다.

### 3.5 Mean reversion 예외 구간

- 급락 후 유동성 회복과 과매도 해소 구간에서는 단기 반등 edge가 생길 수 있다.
- 이 전략은 모멘텀 전략과 분리된 별도 전략군으로 취급한다.

## 4. AI 판단 계층 구조

```text
Market Data / Account / News / External Data
  -> Data Quality Agent
  -> Feature Generator
  -> Market Regime Agent
  -> Universe Selection Agent
  -> Strategy Selection Agent
  -> Signal Agents
  -> News / Event Agent
  -> Portfolio Candidate Agent
  -> Order Construction Agent
  -> AI Risk Manager Agent
  -> AI Compliance Agent
  -> Final Trade Decision Composer
```

### 4.1 Agent별 책임

#### Market Regime Agent

- 현재 시장을 아래 중 하나 이상으로 분류
  - bullish trend
  - bearish trend
  - range-bound
  - high-volatility
  - low-liquidity
  - event-driven unstable

- 산출값:
  - regime label
  - regime confidence
  - regime half-life
  - 전략 가중치 추천

#### Universe Selection Agent

- 거래 가능성, 유동성, 이벤트 존재 여부, 거래정지 여부를 감안해 후보군 생성
- “좋은 종목”을 고르는 게 아니라 “오늘 검토할 가치가 있는 종목군”을 만든다.
- 동시에 뒤단 Agent 비용과 rate limit를 보호하는 **명시적 gatekeeper** 역할을 가진다.

권장 정책:

- 장중 정밀 분석 대상 종목 수 upper bound를 둔다.
- 예: 세션당 20~30개 이내 심층 분석
- 상위 후보군 바깥 종목은 lightweight filter만 통과시킨다.

#### Strategy Selection Agent

- regime와 시장 폭, 변동성, 회전율 환경을 보고 오늘 쓸 전략을 선택
- 전략 예시:
  - intraday breakout
  - swing momentum
  - mean reversion bounce
  - event continuation
  - defensive low-volatility rotation

#### Signal Agents

- 독립 신호를 분리 평가한다.
- 권장 분리:
  - technical signal
  - orderflow signal
  - volatility signal
  - liquidity signal
  - event/news signal
  - cross-sectional ranking signal

#### News / Event Agent

- 뉴스/공시를 점수 하나로 축약하지 않는다.
- 최소한 아래를 구조화한다.
  - event type
  - expected impact direction
  - impact horizon
  - uncertainty level
  - false positive risk

#### Portfolio Candidate Agent

- 종목 단위 강도뿐 아니라 상호 상관성과 포트폴리오 맥락을 고려한다.
- 동일 테마/동일 섹터 집중을 조정한다.

#### Order Construction Agent

- 최종 후보에 대해
  - side
  - entry style
  - limit/market
  - price band
  - quantity proposal
  - exit rules
  를 만든다.
- 단, intraday execution path에서는 가능하면 LLM 직접 호출 대신 Fast Layer 규칙/모델을 우선 사용한다.

### 4.2 v1 Provider AI Agent Set

v1에서는 전체 Agent 계층 중 아래 3개 Provider AI Agent를 우선 도입한다. 나머지 Agent(regime, universe selection, strategy selection, order construction 고도화 등)는 후속 단계에서 추가한다.

#### 공통 원칙

- AI는 **판단과 구조화된 해석**을 담당한다.
- 최종 수치 계산, threshold 판정, sizing, hard risk limit은 **deterministic backend**가 담당한다.
- 어떤 Agent도 **broker submit을 직접 호출할 수 없다**.
- 모든 Agent 출력은 자유 텍스트가 아니라 **JSON schema**를 준수한다.
- raw output과 structured output을 **모두 저장**하여 replay와 audit에 사용한다.

---

#### Agent 1. Event Interpretation Agent

**목적**: external events를 매매 판단 가능한 구조화 정보로 변환한다.

**입력**: `ExternalEventEntity`, `SourceReliabilityTier`, freshness/stale 상태, symbol/issuer, market timestamp

**책임**:
- 이벤트 성격 분류 (공시/뉴스/정책/실적)
- 영향 방향 (positive / negative / neutral)
- 영향 horizon (short / swing / long)
- uncertainty 추정
- reason code 생성

**비책임**:
- 주문 생성
- 수량 계산
- 최종 승인
- threshold 계산

JSON schema 초안:

```json
{
  "agent_name": "event_interpretation",
  "schema_version": "v1",
  "decision_context_id": "uuid-or-null",
  "symbol": "005930",
  "issuer_code": "00123456",
  "events": [
    {
      "source_event_id": "20230101000001",
      "event_type": "Y|사업보고서 (2023)",
      "source_name": "opendart",
      "source_reliability_tier": "T1",
      "stale": false,
      "impact_direction": "positive",
      "impact_horizon": "swing",
      "confidence": 0.72,
      "novelty": "high",
      "supports_entry": true,
      "supports_exit": false,
      "risk_flags": [],
      "reason_codes": [
        "official_disclosure",
        "positive_fundamental_signal"
      ],
      "summary": "공식 공시 기반의 긍정적 이벤트로 해석"
    }
  ],
  "aggregate_view": {
    "overall_bias": "positive",
    "event_conflict": false,
    "top_reason_codes": [
      "official_disclosure",
      "positive_fundamental_signal"
    ],
    "opposing_evidence": []
  }
}
```

---

#### Agent 2. AI Risk Agent

**목적**: 계좌/포지션/open order/변동성/이벤트 리스크를 종합해 리스크 의견을 제공한다.

**입력**: candidate order intent, position/cash snapshot, risk limit snapshot, recent event interpretation output, volatility/liquidity features

**책임**:
- allow / reduce / reject / review 중 하나의 risk opinion 반환
- risk reason code 생성
- size adjustment factor 제안 (0.0 ~ 1.0)

**비책임**:
- 실제 max size 계산
- hard guardrail 통과 여부 판정
- broker capability 검증
- 주문 제출

허용 `risk_opinion` 값:
- `allow`: 진입 허용, 조정 불필요
- `reduce`: 진입 가능하나 사이징/가격 보수적 조정 필요
- `reject`: 진입 차단
- `review`: 운영자 검토 필요

JSON schema 초안:

```json
{
  "agent_name": "ai_risk",
  "schema_version": "v1",
  "decision_context_id": "uuid-or-null",
  "symbol": "005930",
  "proposed_side": "BUY",
  "risk_opinion": "reduce",
  "risk_score": 0.64,
  "confidence": 0.78,
  "size_adjustment_factor": 0.5,
  "max_holding_horizon": "swing",
  "risk_flags": [
    "event_uncertainty",
    "elevated_volatility"
  ],
  "reason_codes": [
    "reduce_due_to_event_risk",
    "reduce_due_to_volatility"
  ],
  "opposing_evidence": [
    "단기 가격 변동성이 높아 진입 타이밍 리스크 존재"
  ],
  "summary": "진입 자체를 막을 수준은 아니나 보수적 사이징 필요"
}
```

---

#### Agent 3. Final Decision Composer

**목적**: event interpretation, risk opinion, feature/signal context를 종합해 최종 매매 의도를 구조화한다.

**입력**: feature/signal summary, event interpretation output, AI risk output, optional compliance output, config snapshot, position context

**책임**:
- 최종 방향성 결정
- reason codes / opposing evidence 통합
- backend 계산용 structured output 제공

**비책임**:
- expected value 계산
- threshold 통과 판정
- 실제 수량 확정
- hard guardrail 통과 여부 판정
- 주문 제출

허용 `decision_type` 값:
- `APPROVE`: 진입 승인
- `REJECT`: 진입 거부
- `HOLD`: 보류, 추가 정보 필요
- `WATCH`: 진입하지 않고 모니터링
- `EXIT`: 기존 포지션 청산
- `REDUCE`: 기존 포지션 축소

JSON schema 초안:

```json
{
  "agent_name": "final_decision_composer",
  "schema_version": "v1",
  "decision_context_id": "uuid-or-null",
  "symbol": "005930",
  "decision_type": "APPROVE",
  "side": "BUY",
  "entry_style": "LIMIT",
  "time_horizon": "swing",
  "confidence": 0.74,
  "conviction": 0.69,
  "reason_codes": [
    "positive_event_alignment",
    "trend_supportive",
    "risk_reduced_size_required"
  ],
  "opposing_evidence": [
    "변동성이 높아 공격적 진입은 부적절"
  ],
  "execution_preferences": {
    "use_limit_order": true,
    "price_band_hint": {
      "reference_type": "last_price",
      "max_slippage_bps": 15
    },
    "allow_partial_fill": true
  },
  "sizing_hint": {
    "size_mode": "fractional_reduce",
    "size_adjustment_factor": 0.5
  },
  "exit_plan_hint": {
    "stop_style": "volatility_based",
    "take_profit_style": "partial_scale_out",
    "max_holding_days": 20
  },
  "summary": "이벤트와 기본 시그널은 긍정적이나 리스크 의견 반영해 축소 진입"
}
```

---

### 4.3 Deterministic Backend Boundary

아래 항목은 AI Agent가 직접 확정하지 않으며, 반드시 deterministic backend가 계산/판정한다.

- `net_expected_value_bps`
- `minimum_required_edge_bps` 비교
- `final_trade_score` (수치 합산)
- 실제 주문 수량
- 계좌/종목/일별 한도 검증
- hard guardrail pass/fail
- broker capability pass/fail
- live submit 여부

backend가 AI Agent 출력에서 사용하는 입력 예시:

```json
{
  "backend_inputs": {
    "confidence": 0.74,
    "conviction": 0.69,
    "risk_opinion": "reduce",
    "size_adjustment_factor": 0.5,
    "reason_codes": [
      "positive_event_alignment",
      "trend_supportive",
      "risk_reduced_size_required"
    ]
  }
}
```

### 4.4 Storage and Replay Requirements

Agent 실행마다 아래 정보를 저장한다.

- `decision_context_id`
- `agent_name`
- `schema_version`
- `model_id`
- `prompt_id`
- `raw_output_uri` (LLM 원시 출력 저장 위치)
- `structured_output_json` (parsed JSON 출력)
- `started_at`
- `completed_at`

replay를 위해 함께 보존해야 할 정보:

- config version reference
- feature snapshot reference
- recent external events snapshot
- stale/freshness state
- backend calculation version

### 4.5 v1 Rollout Order

Provider AI Agent는 아래 순서로 도입한다. 각 Agent는 이전 단계의 출력 포맷과 저장 구조가 먼저 정의된 후 추가한다.

1. **Event Interpretation Agent** — external event를 구조화 JSON으로 변환하는 파이프라인 우선 확보
2. **AI Risk Agent** — 리스크 의견과 size adjustment factor를 구조화
3. **Final Decision Composer** — 앞선 두 Agent 출력을 종합해 최종 매매 의도 생성

## 5. Feature 체계

### 5.1 입력 범주

- 시세
- 호가/체결
- 거래량/거래대금
- 투자자별 수급
- 순위 변화
- 변동성
- 뉴스/공시
- 업종/시장 breadth
- 계좌 상태
- 기존 포지션 및 미체결

### 5.2 핵심 feature 예시

#### Trend / Momentum

- 1d, 3d, 5d, 20d returns
- moving average spread
- breakout distance
- relative strength percentile

#### Flow / Participation

- volume surge ratio
- turnover percentile
- investor net flow z-score
- 거래대금 가속도

#### Volatility / Risk

- realized volatility
- intraday range ratio
- gap risk
- downside volatility

#### Liquidity / Execution

- bid-ask spread
- top-of-book depth
- average fillable size estimate
- slippage estimate

#### Event / Narrative

- earnings surprise class
- disclosure materiality
- policy sensitivity
- news novelty score

### 5.3 Feature 사용 원칙

- feature는 많을수록 좋은 것이 아니다.
- 같은 정보를 중복 반영하는 feature는 줄인다.
- “예측력”과 함께 “실행 가능성”을 같이 봐야 한다.
- feature importance는 전략군별로 다르게 관리한다.

### 5.4 Feature Generator의 핵심 책임

Feature Generator는 단순 전처리기가 아니다. 이 계층은 **고빈도 데이터를 LLM이 소화 가능한 압축 표현으로 바꾸는 핵심 계층**이다.

필수 책임:

- raw tick/orderbook를 rolling statistics로 압축
- 거래대금, 수급, 변동성을 z-score와 percentile로 정규화
- 급변 이벤트를 짧은 event tag로 변환
- regime/context에 필요한 핵심 값만 남기고 나머지는 제거
- feature snapshot의 token budget을 관리

권장 출력 형태:

- numeric feature vector
- compact JSON summary
- short text descriptor

예:

```json
{
  "symbol": "005930",
  "microstructure_summary": {
    "spread_bps_pctile": 18,
    "depth_ratio_zscore": 1.4,
    "trade_imbalance_zscore": 2.1,
    "turnover_surge_ratio": 2.8
  },
  "event_tags": [
    "liquidity_improving",
    "buy_pressure_persistent"
  ],
  "text_summary": "체결 강도와 거래대금 가속도가 동반 상승 중이며 단기 유동성은 양호함"
}
```

## 6. 판단 절차

### 6.1 전체 절차

```text
1. 데이터 품질 검증
2. raw high-frequency data를 feature summary로 압축
3. market regime 판정
4. candidate universe 생성
5. strategy family 선택
6. 종목별 signal scoring
7. event/news 보정
8. liquidity/slippage/volatility penalty 반영
9. expected alpha inputs 산출
10. backend math engine이 최종 score 계산
11. portfolio context 조정
12. entry/exit/sizing 제안
13. AI risk/compliance 검토
14. 최종 주문 의도 생성
```

### 6.2 종목 점수화

각 종목은 전략별로 별도 점수를 가진다.

```text
Raw Opportunity Score
= weighted(alpha features)

Execution Adjusted Score
= Raw Opportunity Score
- slippage penalty
- liquidity penalty
- volatility penalty
- crowding penalty

Portfolio Adjusted Score
= Execution Adjusted Score
- correlation penalty
- sector concentration penalty
- existing exposure penalty
```

주의:

- 위 식은 LLM이 직접 계산하는 것이 아니라 backend math engine이 계산해야 한다.
- Agent는 식의 입력값과 근거를 공급한다.

### 6.3 진입 조건

다음 4개가 동시에 만족될 때만 진입 후보로 올린다.

1. regime 적합성
2. signal strength 임계치 초과
3. execution feasibility 확보
4. risk-adjusted expected alpha 양수

### 6.4 청산 조건

청산은 단순 stop loss 하나로 끝내지 않는다.

- thesis invalidation
- target reached
- signal decay
- regime shift
- liquidity collapse
- time stop

## 7. Agent 통합 방식

### 7.1 최종 결정 방식

최종 의사결정은 아래 두 단계를 권장한다.

#### Stage 1. Independent scoring

- 각 Agent는 독립 점수와 근거를 낸다.
- 서로의 출력에 바로 끌려가지 않도록 1차 평가는 독립 실행한다.

#### Stage 2. Structured ensemble

- 최종 Composer가 아래를 통합한다.
  - regime fit
  - signal alignment
  - expected alpha
  - execution cost
  - risk penalties
  - compliance status

단:

- Composer는 직접 부동소수점 계산을 수행하지 않는다.
- Composer는 입력 점수의 해석, 충돌 조정, 설명 생성을 담당한다.
- 숫자 계산은 backend score aggregator가 수행한다.

### 7.2 권장 통합식

```text
Final Trade Score
= regime_weight * regime_fit
+ strategy_weight * strategy_fit
+ alpha_weight * expected_alpha
+ signal_weight * multi_signal_alignment
+ event_weight * event_support
- cost_weight * estimated_cost
- risk_weight * risk_penalty
- concentration_weight * concentration_penalty
```

구현 원칙:

- 각 Agent는 `score_component`, `confidence`, `weight_hint`, `reason_codes`를 JSON으로 출력한다.
- 최종 합산식은 backend에서 deterministic하게 계산한다.
- 같은 입력이면 같은 최종 수치가 재현되어야 한다.

### 7.3 충돌 해결

예:

- technical strong buy
- event agent high uncertainty
- liquidity poor

이 경우 무조건 reject가 아니라:

- 비중 축소
- 진입 가격 보수화
- 보류
- 후보군 유지 후 재평가

중 하나를 선택한다.

## 8. 최고 기대수익률을 위한 핵심 정책

### 8.1 “많이 맞추는 것”보다 “크게 이기는 것”

- 승률보다 payoff asymmetry를 중시한다.
- 신호가 약하면 거래하지 않는다.
- 확신이 강하고 손익비가 좋을 때만 크게 간다.

### 8.2 Regime별 전략 전환

- 상승 추세장: breakout/momentum 비중 확대
- 횡보장: mean reversion 비중 확대
- 고변동성: 보유기간 단축, 사이징 축소
- 이벤트 불확실성 확대: 신규 진입 억제

### 8.3 체결 가능성 반영

- 이론상 수익보다 실현 가능 수익을 우선한다.
- 슬리피지와 체결 불확실성이 크면 점수를 낮춘다.

### 8.4 거래하지 않을 권리

- 최고의 기대수익률 전략은 “아무 때나 거래”가 아니다.
- edge가 없으면 현금 보유가 정답이다.

### 8.5 Latency-aware execution

- 빠른 전략일수록 해석 계층보다 실행 계층 latency를 더 중시한다.
- slow inference 때문에 edge가 사라질 수 있는 전략은 Slow Layer에서 방향만 정하고 Fast Layer가 실제 트리거를 잡아야 한다.
- signal half-life가 inference latency보다 짧으면 해당 전략은 LLM 직접 실행 경로에서 제외한다.

### 8.6 Hard Risk Limit & Kill-Switch Spec

- 아래 규칙은 AI Risk Manager나 AI Compliance Agent가 override할 수 없는 hard rule이다.
- 일간 손실 한도, 계좌 전체 drawdown 한도, 종목별 최대 비중, 섹터/테마 최대 노출, 미체결 주문 포함 exposure, 시세 지연, broker API 장애, 주문 응답 지연은 신규 진입 차단 조건이 될 수 있다.
- 거래정지, 투자경고, 관리종목, 비정상 공시 종목은 기본 차단 대상으로 본다.
- kill-switch 발동 후에는 신규 진입을 중단하고 위험 축소 주문만 허용할 수 있다.

## 9. 사이징 정책

### 9.1 입력

- final trade score
- confidence
- expected downside
- account drawdown state
- liquidity capacity
- existing exposure

### 9.2 권장 정책

```text
Position Size
= base_risk_budget
* confidence_multiplier
* regime_multiplier
* liquidity_multiplier
* drawdown_multiplier
```

주의:

- 위 계산식 역시 backend math engine이 수행한다.
- LLM은 multiplier 제안 또는 조정 의견만 제공한다.

규칙:

- confidence가 높아도 liquidity multiplier가 낮으면 size를 줄인다.
- drawdown state가 악화되면 전 전략 공통으로 risk budget을 줄인다.

### 9.3 피라미딩/분할진입

- 초기 진입은 보수적으로
- thesis가 확인되면 추가 진입 가능
- 단, 평균단가 낮추기용 무계획 물타기는 금지

### 9.4 Position Sizing Spec 구체화

실제 주문 수량 산출은 아래 순서를 따른다.

1. 허용 손실금액 계산
2. 진입가와 invalidation price 기준 1주당 위험 계산
3. risk-based max quantity 계산
4. liquidity cap 적용
5. exposure cap 적용
6. confidence / regime / drawdown multiplier 적용
7. 최종 주문 가능 수량 산출
8. 최소 주문 단위와 호가 단위 반영

## 10. 학습 및 피드백

### 10.1 저장해야 할 것

- regime 판정 결과
- 선택된 전략
- feature snapshot
- 각 Agent 점수
- 최종 trade score
- 주문 결과
- 체결 비용
- 보유 후 성과
- 청산 사유

### 10.2 사후 분석

다음 질문에 답해야 한다.

- 어떤 regime에서 어떤 전략이 실제로 먹혔는가
- 어떤 signal이 기대수익에 가장 기여했는가
- 어떤 signal은 과최적화였는가
- 비용 차감 후에도 edge가 남는가
- high-confidence trade가 실제로 outperform 했는가

### 10.3 가중치 업데이트

- 고정 규칙만 쓰지 않는다.
- 다만 실시간 자동학습으로 바로 실전 반영하는 것은 위험하다.
- 권장 흐름:
  - backtest
  - paper validation
- limited live canary
- staged rollout

### 10.4 Backtest / Paper / Canary / Live Validation Criteria

- historical backtest
- walk-forward validation
- out-of-sample validation
- paper trading
- limited live canary
- staged rollout
- full live with monitoring

## 11. 실패 모드

AI 판단 계층은 아래 실패 모드를 명시적으로 감시해야 한다.

- regime misclassification
- stale data driven trades
- overreaction to noisy news
- crowding into illiquid names
- too many correlated positions
- cost underestimation
- confidence inflation
- paper/live performance divergence

각 실패 모드는 별도 모니터링 지표와 연결한다.

### 11.1 Broker API Failure Handling Spec

- 주문 요청 timeout
- 주문 접수 여부 불명확
- 중복 주문 방지 idempotency key
- broker order id와 internal order id 매핑
- 주문 상태 reconciliation
- partial fill 처리
- cancel/replace 실패 처리
- 잔고/포지션 조회 실패
- 시세 데이터 지연
- 주문 가능 금액 불일치
- API rate limit 대응
- 장애 시 신규 주문 중단
- 위험 축소 주문만 허용하는 safe mode

핵심 원칙:

```text
When order state is unknown, do not submit a new order for the same symbol/strategy until reconciliation is completed.
```

### 11.2 Monitoring Metric -> Trigger -> Action 구조

각 실패 모드는 다음 구조로 관리한다.

- failure_mode
- monitoring_metric
- trigger_threshold
- automatic_action
- recovery_condition

### 11.3 Audit Log & Explainability Spec

- `decision_id`
- `feature_snapshot_id`
- agent output raw JSON
- backend score calculation result
- risk check result
- compliance check result
- final decision JSON
- broker order request
- broker order response
- fill report
- position change
- exit reason
- post-trade review result

### 11.4 Final Decision JSON Schema

필수 필드:

- `decision_id`
- `timestamp`
- `symbol`
- `market`
- `strategy_id`
- `side`
- `decision`
- `entry_style`
- `entry_price`
- `price_band`
- `quantity`
- `max_order_value`
- `expected_return_bps`
- `expected_downside_bps`
- `net_expected_value_bps`
- `final_trade_score`
- `confidence`
- `regime_label`
- `strategy_fit_score`
- `risk_checks`
- `compliance_checks`
- `execution_checks`
- `exit_plan`
- `reason_codes`
- `opposing_evidence`
- `audit`

명시:

- 이 JSON은 주문 API로 바로 전달되는 payload가 아니다.
- 실제 broker 주문 payload는 별도 Order Adapter가 변환한다.
- risk/compliance/execution check 중 하나라도 실패하면 주문 생성 불가다.

### 11.5 Expected Value와 Final Trade Score 분리

- `Final Trade Score`는 후보 랭킹과 의사결정 보조용이다.
- `Expected Value`는 실제 주문 여부 판단용이다.
- score가 높아도 `net_expected_value_bps`가 음수이면 주문하지 않는다.

원칙:

```text
IF net_expected_value_bps <= minimum_required_edge_bps
THEN reject trade regardless of final_trade_score
```

## 12. v1 권장 구현 범위

처음부터 모든 전략을 다 넣지 않는다.

### 12.1 v1 전략군

- swing momentum
- event continuation
- defensive filter

### 12.2 v1 Agent 최소 세트

v1에서는 전체 Agent 계층 중 아래 3개 Provider AI Agent를 우선 도입한다. 나머지 Agent는 후속 단계에서 추가한다.

- **Event Interpretation Agent** (4.2절 참고)
- **AI Risk Agent** (4.2절 참고)
- **Final Decision Composer** (4.2절 참고)

후속 단계에서 추가할 Agent:
- Market Regime Agent
- Universe Selection Agent
- Strategy Selection Agent
- Signal Agent
- News/Event Agent (일부 기능은 Event Interpretation Agent가 선점)
- Order Construction Agent
- AI Compliance Agent

### 12.3 v1 통합 방식

- weighted score
- confidence weighting
- regime-based weight switching

### 12.4 v1 Fast / Slow 구조

- Slow Layer
  - 15분, 30분, 1시간 또는 세션 단위 갱신
  - regime, strategy family, universe shortlist, event interpretation 담당

- Fast Layer
  - 초 단위 또는 분 단위 갱신
  - feature refresh, trigger detection, score calculation, order proposal 담당

v1에서는 이 구분을 반드시 유지해야 하며, intraday execution path에 고비용 LLM 호출을 직접 넣지 않는 것을 기본값으로 한다.

debate형 자유 토론은 v2 이후로 미뤄도 된다.

## 13. 필수 산출물

이 문서를 실제 구현 수준으로 내리기 위해 다음 산출물을 추가로 작성해야 한다.

1. strategy taxonomy 문서
2. regime classification spec
3. signal scoring formula spec
4. position sizing spec
5. exit policy spec
6. learning loop and monitoring spec
7. AI final decision JSON schema
8. fast/slow runtime orchestration spec
9. backend score calculation spec
10. hard risk limit & kill-switch spec
11. order lifecycle state machine spec
12. broker API failure handling spec
13. live/paper/backtest consistency spec
14. trade approval and override policy
15. audit log and explainability spec
16. capital allocation policy
17. market data freshness and integrity spec
18. incident response runbook

## 14. 결론

최고 기대수익률을 추구하는 핵심은 “AI를 붙인다”가 아니라 아래 네 가지다.

1. **어떤 시장 비효율을 먹는지 명확히 정의**
2. **regime에 따라 전략과 가중치를 바꾸는 구조**
3. **실현 가능 비용과 리스크를 반영한 기대값 판단**
4. **성과 피드백으로 feature와 전략을 감쇠/강화하는 폐쇄 루프**

이 시스템에서 AI는 설명기나 보조기능이 아니라, 위 구조를 바탕으로 **전략 선택과 주문 판단을 수행하는 확률적 의사결정 계층**이어야 한다.
