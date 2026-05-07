# Agent Inventory And Status

기준 문서:

- `plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md` 6.1
- `plan_docs/detailed_design/01_system_architecture.md`
- `plan_docs/detailed_design/07_mvp_scope_and_delivery_plan.md`
- `plan_docs/detailed_design/08_ai_decision_policy.md`

기준 코드:

- `src/agent_trading/runtime/bootstrap.py`
- `src/agent_trading/services/ai_agents/`
- `src/agent_trading/services/decision_orchestrator.py`
- `src/agent_trading/services/order_manager.py`
- `src/agent_trading/services/reconciliation_service.py`
- `src/agent_trading/brokers/`

## 상태 정의

- `Implemented`
  - 현재 코드에 독립 구현체가 있고, 런타임 경로에 실제 연결되어 있다.
- `Partially Implemented`
  - 책임의 일부는 구현되었지만, 설계에서 기대한 전용 Agent 형태나 전체 범위는 아직 아니다.
- `Planned`
  - 설계 문서에는 있으나, 현재 전용 구현체나 실연결이 없다.

## 14개 Agent 매핑 표

| Agent | 설계상 역할 | 권장 최종 구현 형태 | 현재 상태 | 현재 앵커 |
|---|---|---|---|---|
| Data Collector Agent | 시세, WebSocket, 계좌, 주문, 외부 데이터 수집 | Deterministic worker + adapter layer | Partially Implemented | `brokers/koreainvestment/*`, `brokers/polling_worker.py`, `brokers/source_adapter.py`, `runtime/bootstrap.py` |
| Data Quality Agent | 결측, 이상치, 지연 데이터, API 오류 탐지 | Deterministic validator/service | Partially Implemented | freshness budget, dedup, gap fill, runtime fallback 관련 구현과 정책 문서 |
| Market Regime Agent | 시장 국면 판단 | Hybrid: deterministic feature engine + optional AI interpretation | Planned | `08_ai_decision_policy.md`에 개념 정의만 존재 |
| Universe Selection Agent | 거래 후보 종목군 생성 | Deterministic ranking/filter engine 중심, 필요 시 AI 보조 | Planned | `08_ai_decision_policy.md`에 설계만 존재 |
| Strategy Selection Agent | 사용할 전략/실행 스타일 선택 | Hybrid policy service + optional AI recommendation | Planned | `08_ai_decision_policy.md`에 설계만 존재 |
| Signal Agent | 기술/수급/모멘텀/변동성 점수화 | Deterministic scoring engine | Planned | `08_ai_decision_policy.md`에 설계만 존재 |
| News/RAG Agent | 뉴스/공시/리포트/이벤트 요약과 리스크 태깅 | Provider AI Agent + retrieval/event adapter hybrid | Partially Implemented | `EventInterpretationAgent`, `OpenDartSourceAdapter`, external event pipeline |
| Portfolio Agent | 목표 비중, 진입/청산 후보 계산 | Deterministic portfolio construction service | Planned | 설계 문서상 개념만 존재 |
| Order Construction Agent | 가격/수량/주문 타입/시간조건/청산 규칙 결정 | Deterministic order-construction service with AI inputs | Planned | `08_ai_decision_policy.md`에 설계만 존재 |
| AI Risk Manager Agent | 한도, 손실, 유동성, 집중도, 헤지, 사이징 조정 판단 | Provider AI Agent + deterministic hard limits 후단 연동 | Implemented | `services/ai_agents/ai_risk.py`, `decision_orchestrator.py`, `runtime/bootstrap.py` |
| AI Compliance Agent | 금지 조건, 브로커 제약, 정책 위반 가능성 판단 | Hybrid: AI policy agent + deterministic hard validator 분리 | Planned | `01_system_architecture.md`, `08_ai_decision_policy.md`에 정의만 존재 |
| Execution Agent | AI 최종 결정 실행, 주문 분할, 체결 추적 | Deterministic execution pipeline, not provider AI | Partially Implemented | `order_manager.py`, `reconciliation_service.py`, `brokers/koreainvestment/adapter.py` |
| Performance Agent | 성과 분석, 원인 분석, 전략별 기여도 계산 | Deterministic analytics job + optional AI commentary | Planned | 설계 문서상 개념만 존재 |
| Model Monitor Agent | drift, 과최적화, 실전/백테스트 괴리 감시 | Deterministic monitoring service + offline analysis | Planned | 설계 문서상 개념만 존재 |

## 현재 구현 관점의 핵심 해석

### 1. 현재 "실제 AI Agent"는 3개만 런타임에 연결되어 있다

- Event Interpretation Agent
- AI Risk Agent
- Final Decision Composer

이 3개는 `DecisionOrchestrator` 경로에서 request chain으로 연결된다.

### 2. Final Decision Composer는 14개 목록의 직접 1:1 항목이 아니다

설계상의 14개 목록에는 `Final Decision Composer`라는 이름이 없지만,
현재 구현에서는 v1 의사결정 통합기의 역할을 담당한다.

실무적으로는 아래 임시 통합 계층으로 해석하는 것이 맞다.

- Market/Universe/Strategy/Signal/Portfolio/Order Construction 중
  아직 세분 구현되지 않은 판단 일부를 통합하는 v1 composer
- 단, broker submit이나 hard guardrail을 직접 소유하지는 않음

### 3. Execution Agent는 AI가 아니라 deterministic path로 유지해야 한다

현재 시스템 원칙상:

- AI는 판단 계층
- broker submit은 deterministic execution path
- authoritative state reflection은 reconciliation / order manager path

따라서 `Execution Agent`는 이름과 달리 최종 구현도 provider LLM agent가 아니라
`OrderManager + BrokerAdapter + ReconciliationService` 중심의 실행 서비스 묶음으로
정리하는 것이 맞다.

