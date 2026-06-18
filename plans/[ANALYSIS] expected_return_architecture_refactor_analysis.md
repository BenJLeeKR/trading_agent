# 기대수익률 극대화 관점의 구조 리팩토링 분석

> 작성일: 2026-06-16
>
> 목적:
> 현재까지 구현된 시스템을 기준으로,
> `위험조정 기대수익률 최대화`라는 핵심 목표를 더 잘 달성하기 위해
> **리팩토링 수준의 구조 개선이 필요한 영역**을 식별하고 우선순위를 정리한다.

## 1. 요약

현재 구현은 다음 단계까지는 와 있다.

- signal feature snapshot 계산/저장
- market regime 분류
- strategy selection
- portfolio allocation / concentration budget
- AI Risk / FDC prompt에 위 deterministic 결과를 read-only 주입
- sizing / guardrail / reconciliation / broker boundary의 기본 deterministic 경계 유지

즉, 시스템은 이미 `feature를 모르는 AI` 상태는 아니다.
하지만 아직 구조의 중심은 여전히
`deterministic 계산 결과를 AI가 읽고 최종 판단을 생성하는 방식`에 가깝다.

이 구조는 v1 운영에는 유효하지만,
`기대수익률 극대화`를 위한 반복 실험, threshold 조정, backtest-replay 일치성,
AI override 효과 측정 측면에서는 한계가 분명하다.

핵심 결론:

1. **Trigger 생성 계층이 아직 없다.**
   - 현재 feature/regime/strategy/portfolio는 대부분 `판단 입력`으로만 쓰인다.
   - 수익률 개선의 핵심은 `입력 강화`보다 `후보 생성(candidate generation)`의 재현성 강화다.
2. **Decision Orchestrator와 prompt 조립 계층이 비대하다.**
   - 전략 실험 속도보다 운영 복잡도가 더 빠르게 증가하고 있다.
3. **판단 결과 스키마가 아직 실험/분석 친화적으로 정리되지 않았다.**
   - `candidate`, `AI override`, `final decision`, `execution result`, `PnL attribution`을 분리 저장해야 한다.
4. **현재 구조는 “안전한 운영”에는 점점 가까워지고 있지만,
   “무엇이 기대수익률을 만들었는가”를 분해 측정하기에는 아직 부족하다.**

따라서 다음 단계의 리팩토링은
`AI를 더 붙이는 작업`이 아니라,
**deterministic trigger / candidate / attribution 계층을 명시적으로 세우는 작업**이어야 한다.

---

## 2. 핵심 목표와 현재 구조의 불일치

기준 문서:

- [`plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md`](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md)
- [`plan_docs/agents/02_agent_target_shapes.md`](../plan_docs/agents/02_agent_target_shapes.md)
- [`plan_docs/agents/03_risk_role_boundaries.md`](../plan_docs/agents/03_risk_role_boundaries.md)

핵심 목표는 단순 자동주문이 아니라
`위험조정 기대수익률을 최대화하는 시스템`이다.

이 목표를 달성하려면 아래가 가능해야 한다.

1. 어떤 feature 조합이 실제 alpha 후보를 만들었는지 재현 가능해야 한다.
2. 어떤 trigger가 WATCH/BUY/SELL 후보를 만들었는지 수치로 설명 가능해야 한다.
3. AI가 후보를 뒤집은 경우, 그 override가 수익률에 실제로 도움이 되었는지 측정 가능해야 한다.
4. 같은 입력에 대해 backtest / replay / live가 최대한 동일한 candidate 분포를 내야 한다.

현재 구조는 1번의 일부만 만족하고, 2~4번은 아직 약하다.

이유는 다음과 같다.

- feature score는 존재하지만 `후보 결정`이 아니라 `프롬프트 입력` 비중이 더 크다.
- WATCH / BUY / SELL의 상당 부분이 아직 LLM prompt 해석에 남아 있다.
- `trade_decisions.decision_json`은 풍부해지고 있으나,
  실험 단위(`trigger`, `candidate`, `override`)가 분리 저장되지 않는다.
- 최종 성과를 feature threshold와 직접 연결하는 구조가 없다.

---

## 3. 현재 구현에서 이미 잘된 부분

이 문서는 부족한 점만 적는 문서가 아니다.
리팩토링이 필요한 이유를 분명히 하려면, 이미 확보한 기반도 같이 봐야 한다.

### 3.1 확보된 deterministic 기반

- Signal backbone과 feature snapshot 저장 경로가 있다.
- Market regime / strategy selection / portfolio allocation이 pure helper 형태로 추가됐다.
- sizing / guardrail / broker submit 경계는 여전히 deterministic path가 우선이다.
- unknown state / reconciliation-first / hard guardrail 원칙은 유지되고 있다.

### 3.2 이 기반이 중요한 이유

이제 필요한 것은 새 agent를 무작정 늘리는 것이 아니라,
이미 계산 가능한 deterministic 결과를 `후보 생성 계층`으로 승격하는 일이다.

즉, 지금의 구조는 버려야 할 것이 아니라,
**판단 입력 계층에서 후보 생성 계층으로 한 단계 더 올려야 하는 상태**다.

---

## 4. 리팩토링이 필요한 핵심 영역

### 4.0 초저유동성 BUY 실행 구멍과 기대수익률 정렬

최근 운영 사례에서
초저유동성 `core` 종목이

- universe에 남고
- deterministic candidate는 `NO_ACTION`
- AI override로 `APPROVE` 승격
- sizing은 `현금 / 현재가` 기반으로 대량 산출
- execution은 전면 `MARKET` 제출

경로를 통해 실제 KIS 주문까지 전달되는 사례가 확인됐다.

이 사례는 단순 보수성 부족이 아니다.
`실행 비용과 체결 불확실성이 alpha를 압도하는 거래`
를 시스템이 허용했다는 뜻이므로,
핵심 목표인 `위험조정 기대수익률 최대화`와 직접 충돌한다.

따라서 아래 방향은 기대수익률 목표에 부합한다.

1. `core` BUY 경로에도 deterministic liquidity gate 추가
   - 저유동성 종목을 candidate 생성 이전에 제거
   - 이는 alpha 억제가 아니라 negative EV 차단이다.

2. `NO_ACTION -> AI APPROVE`의 blanket 허용 축소
   - 단, 전면 금지는 아님
   - `eligibility 실패`, 특히 `execution feasibility 실패` 상태에서는
     AI 승격을 허용하지 않는 조건부 제한이 맞다.

3. 전면 `MARKET` 정책 제거
   - 모든 종목 LIMIT 고정이 아니라
     저유동성 구간에서 `LIMIT 강제` 또는 `submit 금지`
     로 바꾸는 방식이 기대값 보존에 맞다.

4. sizing에 participation cap 추가
   - `주문수량 / 당일 누적거래량`
   - `주문대금 / 당일 누적거래대금`
   상한을 hard cap으로 둬야 한다.

반대로 아래 형태는 그대로는 부합하지 않는다.

- `NO_ACTION이면 AI override 전면 금지`
  - deterministic calibration 미성숙 구간에서
    실제 alpha 후보까지 차단할 수 있다.
  - 따라서 `execution infeasible 상태에서만 override 금지`
    형태로 좁혀야 한다.

## 4.1 Trigger / Candidate 계층 부재

### 현재 상태

- `signal_feature_snapshot`
- `market_regime`
- `strategy_selection`
- `portfolio_allocation`

위 결과가 존재하지만, 최종적으로는 AI Risk / FDC prompt 입력으로만 주로 사용된다.

### 문제

이 구조에서는 다음 질문에 답하기 어렵다.

- 이번 주 SELL 판단이 왜 줄었는가
- WATCH가 왜 안 나오는가
- 특정 feature threshold를 바꾸면 BUY candidate가 얼마나 늘어나는가
- AI가 어떤 candidate를 얼마나 기각했는가

### 필요한 리팩토링

`Deterministic Trigger Engine` 또는 `Candidate Generation Layer`를 추가해야 한다.

예시 출력 계약:

- `watch_candidate`
- `buy_candidate`
- `sell_candidate`
- `reduce_candidate`
- `candidate_confidence`
- `trigger_reason_codes`
- `trigger_version`

권장 역할 분리:

- Signal/Regime/Strategy/Portfolio → deterministic candidate 생성
- AI Risk / FDC → candidate 승인, 보류, 승격, 기각
- Guardrail / Sizing / Execution → authoritative enforcement

### 기대효과

- feature 기반 threshold 실험 가능
- WATCH/BUY/SELL 분포 변화 추적 가능
- AI override 효과 측정 가능
- backtest/replay/live 간 정렬성 향상

### 우선순위

가장 높은 우선순위의 구조 리팩토링이다.

---

## 4.2 Decision Orchestrator 비대화

### 현재 상태

다음 파일들이 이미 상당히 크다.

- `decision_orchestrator.py`
- `execution_service.py`
- `ai_risk.py`
- `final_decision_composer.py`
- `run_agent_subprocess.py`

특히 `DecisionOrchestratorService`는 아래 책임을 동시에 가진다.

- context assembly
- snapshot lookup
- feature 기반 파생 계산
- AI 실행 orchestration
- held-position override
- persistence 연결
- execution pipeline 진입

### 문제

이 구조에서는 다음이 어렵다.

- feature trigger 정책만 독립 실험
- 후보 생성 단계만 별도 replay
- AI layer 교체 실험
- source_type 정책 분리

즉, `판단 개선 속도`보다 `조정 비용`이 빠르게 커진다.

### 필요한 리팩토링

`Decision Orchestrator`를 최소 아래 단계로 명시 분리해야 한다.

1. `Context Assembly Stage`
2. `Deterministic Derivation Stage`
   - regime / strategy / portfolio / trigger
3. `AI Policy Stage`
   - EI / AR / FDC
4. `Decision Materialization Stage`
   - candidate/final decision persistence
5. `Execution Preparation Stage`
   - sizing / order construction input

### 기대효과

- 단계별 replay 가능
- 어느 단계가 실제로 수익률에 기여하는지 분해 가능
- 테스트 범위 축소
- prompt 수정이 execution 경계에 미치는 영향 축소

### 우선순위

Trigger 계층 추가와 함께 묶어서 진행할 가치가 높다.

---

## 4.3 Prompt Context Projection 중복

### 현재 상태

AI Risk와 FDC prompt에는 다음 정보가 중복으로 들어간다.

- signal feature snapshot
- market regime
- strategy selection
- portfolio allocation
- position / cash / risk 상태

현재는 prompt builder가 각 파일에 직접 서술형으로 퍼져 있다.

### 문제

- 같은 fact를 서로 다른 표현으로 중복 투입
- AR/FDC prompt 간 의미 차이 발생 가능
- 필드 추가/삭제 시 두 군데 이상 동시 수정 필요
- prompt audit 시 “무슨 context가 실제로 주입되었는지” 추적이 어렵다

### 필요한 리팩토링

`Prompt Context Projector` 또는 `Decision Prompt Input Schema`를 공통 모듈로 분리해야 한다.

권장 형태:

- `DecisionPromptContext`
- `render_signal_section()`
- `render_regime_section()`
- `render_portfolio_section()`
- `render_risk_snapshot_section()`

또는 텍스트 렌더 이전에
`LLMInputView`라는 구조화 객체를 먼저 만들고, 각 agent는 이를 자신만의 prompt로 렌더하게 한다.

### 기대효과

- prompt drift 감소
- context versioning 가능
- agent 간 입력 일관성 향상
- replay 시 “실제 입력” 저장/비교 가능

### 우선순위

중상.
Trigger 계층 다음으로 바로 정리할 가치가 있다.

---

## 4.4 판단 결과 스키마의 비정형 확장

### 현재 상태

`trade_decisions.decision_json`에 점점 더 많은 구조가 들어가고 있다.

예:

- strategy selection
- portfolio allocation
- event/risk reason codes
- execution preferences

### 문제

현재 구조는 저장은 되지만, 아래 분석에는 약하다.

- candidate와 final decision 분리 분석
- AI override 분리 분석
- trigger별 승률 비교
- regime별 BUY/SELL 품질 측정
- source_type별 actionability 비교

### 필요한 리팩토링

결정 레코드를 최소 아래 개념으로 분리할 필요가 있다.

1. `deterministic_candidate`
2. `ai_policy_opinion`
3. `final_trade_decision`
4. `execution_outcome_summary`
5. `performance_attribution`

반드시 즉시 테이블을 쪼개라는 뜻은 아니다.
하지만 적어도 스키마 레벨에서는 위 구분이 명확해야 한다.

### 기대효과

- 기대수익률 기여 분해 가능
- AI와 deterministic 계층의 성과 분리 가능
- drift/회귀 탐지 정확도 향상

### 우선순위

중.
Trigger 계층이 생기면 곧바로 따라와야 한다.

---

## 4.5 Order Construction 책임 미분리

### 현재 상태

설계 문서에는 `Order Construction Agent`가 있으나,
실코드에서는 이 책임이 아직 FDC 출력, translation helper, sizing, execution service에 나뉘어 있다.

### 문제

- `결정`과 `집행 형태`가 분석상 분리되지 않는다.
- 예를 들어 BUY가 맞았는지와 LIMIT/MARKET 정책이 맞았는지가 섞인다.
- execution style 실험을 feature/strategy 실험과 독립적으로 하기 어렵다.

### 필요한 리팩토링

`Order Construction Service`를 deterministic 계층으로 분리해야 한다.

권장 입력:

- final decision
- strategy selection
- portfolio allocation
- liquidity/quote policy
- source_type

권장 출력:

- order side
- order type
- price policy
- time horizon to execution policy mapping

### 기대효과

- alpha 판단과 execution policy를 분리 평가 가능
- 체결률/슬리피지 개선 실험 가능
- BUY/SELL 빈도 변화와 주문 스타일 변화의 효과를 구분 가능

### 우선순위

중.
수익률 개선의 실질 효과가 크다.

---

## 4.6 성과 귀속(attribution) 계층 부재

### 현재 상태

현재도 audit와 decision 기록은 많지만,
`무엇이 성과를 만들었는가`를 정식으로 분해하는 구조는 아직 약하다.

### 문제

아래 질문에 구조적으로 답하기 어렵다.

- feature trigger가 맞았나, AI override가 맞았나
- regime classifier 품질이 실제 수익률에 도움이 되었나
- source_type별 어떤 lane이 기대값이 높았나
- WATCH가 실제로 기회비용을 줄였나

### 필요한 리팩토링

최소 아래 지표를 저장할 attribution path가 필요하다.

- candidate type
- trigger reason codes
- AI override 여부
- final action
- submit 여부
- fill 여부
- holding horizon
- realized PnL / MFE / MAE
- regime at decision time
- feature snapshot version

### 기대효과

- 수익률 개선이 “감”이 아니라 데이터 기반으로 가능
- 기대수익률 최대화라는 핵심 목표와 직접 연결

### 우선순위

중상.
Trigger 계층과 함께 설계해두는 것이 바람직하다.

---

## 4.7 Subprocess 직렬화/복원 수동 중복

### 현재 상태

`run_agent_subprocess.py`는 context reconstruction을 수동으로 많이 수행한다.

### 문제

- deterministic 파생 객체가 늘어날수록 복원 코드가 계속 비대해진다.
- field 추가 누락 시 runtime drift가 생긴다.
- replay/subprocess/직접호출 간 입력 차이 위험이 커진다.

### 필요한 리팩토링

공통 직렬화 계층을 두어야 한다.

예:

- `serialize_decision_context()`
- `deserialize_decision_context()`
- dataclass registry 기반 generic serializer

### 기대효과

- agent subprocess와 본 프로세스의 입력 일치성 향상
- 새 deterministic 계층 추가 비용 감소

### 우선순위

중하.
직접 alpha를 만들지는 않지만, 구조 확장 비용을 줄인다.

---

## 5. 무엇은 아직 리팩토링하지 않아도 되는가

아래는 지금 당장 대형 리팩토링 우선순위가 아니다.

1. 브로커 submit / reconciliation 안전 경계 자체
   - 여기는 계속 안정화가 필요하지만, 방향은 이미 맞다.
2. inspection API / Admin UI
   - 운영 가치가 있으나 기대수익률 자체를 직접 만들지는 않는다.
3. feature 종류를 무한히 늘리는 일
   - 지금 더 필요한 것은 feature 추가보다 `trigger 구조화`다.

즉, 현재 병목은 `feature 부족`보다
`feature를 수익률 실험 가능한 구조로 승격하지 못한 것`에 가깝다.

---

## 6. 권장 우선순위

### P1

1. deterministic trigger / candidate 계층 추가
2. Decision Orchestrator 단계 분리
3. prompt context projection 공통화

### P2

4. decision schema를 candidate / AI opinion / final decision으로 재정리
5. deterministic Order Construction 계층 분리
6. attribution / performance linkage 강화

### P3

7. subprocess serialization 공통화
8. prompt/view schema versioning 고도화

---

## 7. 제안하는 다음 문서/구현 단위

이 분석을 실제 작업으로 옮길 때는 아래 순서가 적절하다.

1. `deterministic_trigger_engine_v1` 설계 문서
2. `decision_pipeline_stage_split` 설계 문서
3. `candidate_vs_final_decision_schema` 설계 문서
4. `performance_attribution_for_trigger_and_override` 설계 문서

---

## 8. 최종 결론

현재 시스템은 `안전한 AI 판단 시스템` 쪽으로는 분명 진전이 있다.
하지만 `기대수익률 최대화`를 위한 다음 성장 단계에서는
아래 변화가 꼭 필요하다.

- feature를 더 넣는 것
- AI prompt를 더 길게 만드는 것

보다 중요한 것은:

- **deterministic trigger를 만든다**
- **AI는 그 trigger를 해석/승인/보류한다**
- **성과는 trigger와 override 단위로 측정한다**

즉, 앞으로 필요한 리팩토링의 본질은
`AI 중심 판단 파이프라인을 버리는 것`이 아니라,
**deterministic alpha candidate 생성 계층을 명시적으로 세우고,
AI를 그 위의 policy layer로 더 얇게 재배치하는 것**이다.
