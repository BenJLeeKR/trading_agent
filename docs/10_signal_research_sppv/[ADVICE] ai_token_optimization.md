# 의사결정 프로세스 토큰 최적화 리팩터링 제안서

작성일: 2026-06-18

## 1. 현행 구조의 문제점 (토큰 낭비 원인)
현재 `decision_orchestrator.py`의 구조를 분석해 보면, **시스템적 결격 사유나 정량적 매력도가 전혀 없는 종목조차도 무조건 3개의 AI 에이전트(Event Interpretation, AI Risk, Final Decision Composer)를 일괄 호출**하고 있습니다. 

AI 호출이 끝난 뒤에야 `_check_buy_eligibility_upgrade_guard` 등의 가드레일을 통해 "이 종목은 유동성이 없어서 매수 불가" 혹은 "정량 시그널이 없어 WATCH로 강등"과 같이 AI의 결정을 기각(Override)합니다. 
즉, **어차피 시스템 규칙에 의해 거절될 종목에 대해 비싼 LLM 토큰을 낭비**하고 있으며, 때로는 AI가 무리하게 매수 사유를 만들어내어 불필요한 거래(승률 저하)를 유발하기도 합니다.

## 2. 토큰 절약과 최고 기대수익률을 위한 3단계 Short-Circuit 구조

기대수익률을 훼손하지 않으면서 토큰을 획기적으로 아끼기 위해서는 **"AI의 판단이 무의미해지는 조건"을 AI 호출 전단(Front)으로 전진 배치**해야 합니다. 이를 위한 3단계 조기 차단(Early Reject) 아키텍처를 제안합니다.

### Phase 1: Hard Constraint Early Reject (실행 불가 조건의 사전 차단)
**개념:** AI가 "매수"라고 외쳐도 물리적으로 불가능한 상황이라면 AI 호출을 원천 생략합니다.
**적용 방안:**
`_derive_deterministic_context_components()` 직후에 다음 이유가 하나라도 포함되어 있다면, 에이전트를 아예 호출하지 않고 즉시 `NO_ACTION` 또는 `HOLD`로 프로세스를 종료합니다.
*   **유동성/체결 불가:** `eligibility_low_average_volume`, `eligibility_low_turnover` (호가창이 얇아 슬리피지가 막대하게 발생하여 기대수익률을 심각하게 훼손하는 종목)
*   **자금 부족:** `eligibility_allocation_blocked` (해당 종목을 살 예산 한도가 0인 경우)
*   **시스템 제어:** `eligibility_risk_off_block` (하락장 폭락 등 매수 금지 구간)

### Phase 2: Lazy & Conditional Agent Invocation (조건부 지연 호출)
**개념:** 3개의 AI를 무조건 한 번에(`_run_agents_in_subprocess`) 묶어서 부르지 않고, 앞선 에이전트/데이터의 결과에 따라 필요할 때만 호출합니다.
**적용 방안:**
*   **Event Interpretation 생략:** 해당 종목에 `recent_events`(최근 72시간 내 공시/뉴스)가 0건이라면, Event Agent 호출을 생략하고 Empty 결과를 다음으로 넘깁니다.
*   **"재료와 수급"의 교집합 부재 시 컷오프:** `deterministic_trigger.primary_candidate == "NO_ACTION"` 이고 동시에 `recent_events` 도 없다면? → **"차트/수급 모멘텀도 없고 뉴스도 없는 종목"**입니다. 이 경우 AI가 임의로 억지 매수 논리(환각)를 만들어낼 확률이 높으므로, Risk/FDC AI를 부르지 않고 곧바로 `NO_ACTION`으로 컷아웃(Cut-out) 합니다.

### Phase 3: Cascading AI Risk Filter (AI 리스크 사전 검열)
**개념:** 비싸고 무거운 FDC(최종 의사결정) AI를 부르기 전에, 가벼운 Risk AI로 치명적 결함을 먼저 필터링합니다.
**적용 방안:**
*   현재처럼 AI Risk와 FDC를 동시에 부르지 않고 **순차적으로(Sequential)** 파이프라인을 재구성합니다.
*   신규 매수(Buy) 검토 시, AI Risk Agent의 결과가 `risk_opinion == "reject"`이거나 `risk_score`가 매우 높게(예: 0.85 이상) 나왔다면, 가장 많은 프롬프트 토큰을 소모하는 FDC Agent 호출을 과감히 생략하고 프로세스를 거절(Reject) 처리합니다.

## 3. 리팩터링을 통한 비즈니스 기대 효과
1.  **압도적인 토큰 비용 절감:** 전체 유니버스의 60~80% 이상이 Phase 1과 Phase 2에서 걸러지게 되어 낭비되는 토큰을 극적으로 줄일 수 있습니다.
2.  **수익률(승률) 보전 및 슬리피지 방어:** 유동성 미달, 예산 초과 상태, 팩트 없는(이벤트+모멘텀 부재) 종목에서의 무리한 진입을 사전에 차단하여 가짜 신호(False Positive)로 인한 손실을 방어합니다.
3.  **루프 대기시간(Latency) 혁신:** AI 호출을 생략함으로써 1회 전체 종목 순회(Decision Loop) 속도가 비약적으로 단축됩니다. 이는 곧 타점 포착 지연을 방지하여 체결 단가를 유리하게 만들어 줍니다.
