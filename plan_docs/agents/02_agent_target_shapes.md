# Agent Target Shapes

이 문서는 14개 필수 Agent를 "최종적으로 어떤 개발 모양으로 가져가는 것이 맞는가"를 설명한다.

핵심 원칙:

1. live-safe 시스템에서 주문 제출, 하드 제한, authoritative reconciliation은 AI가 직접 소유하지 않는다.
2. `Agent`는 책임 단위이지, 모두가 provider LLM 호출 단위는 아니다.
3. 계산 가능하고 검증 가능한 영역은 deterministic backend가 우선한다.
4. AI는 해석, 요약, 정책 판단, 다중 신호 통합처럼 불확실성이 큰 영역에 우선 배치한다.

## 1. Data Collector Agent

### 최종 모양

- Deterministic worker / adapter 집합
- KIS REST / WebSocket / external source adapter / polling worker로 구성

### 왜 이렇게 가야 하는가

- 데이터 수집은 반복 가능성과 안정성이 중요하다.
- 재시도, rate limit, subscription budget, gap fill은 AI보다 worker 설계가 우선이다.

### 현재와의 연결

- KIS REST/WebSocket client
- PollingWorker
- SourceAdapter / OpenDartSourceAdapter

## 2. Data Quality Agent

### 최종 모양

- Deterministic validator / health-check service
- 필요 시 quality incident emitter와 결합

### 담당 범위

- 결측/지연 데이터 탐지
- 중복 이벤트 탐지
- stale market data 탐지
- API 오류율/응답 이상 탐지

### 비고

- "Agent"라는 이름이 붙어 있지만, LLM으로 만들 이유가 가장 약한 축 중 하나다.

## 3. Market Regime Agent

### 최종 모양

- Hybrid
- deterministic feature engine이 1차 국면 분류
- 필요 시 AI가 보조 해석

### 담당 범위

- 상승/하락/횡보
- 변동성 체제 구분
- 리스크 온/오프 분위기 판정

### 권장 구현 순서

1. deterministic regime feature set 구축
2. rule-based classifier
3. 이후 AI가 설명/보정만 담당

## 4. Universe Selection Agent

### 최종 모양

- Deterministic candidate filter and ranking service
- optional AI commentary

### 담당 범위

- 거래 가능 종목 풀 생성
- 유동성/슬리피지/이벤트/규칙 필터링
- exploration budget 제어

### 비고

- 비용과 병목 제어를 위한 gatekeeper이므로 deterministic 성격이 강해야 한다.

## 5. Strategy Selection Agent

### 최종 모양

- Hybrid policy service
- deterministic strategy registry + optional AI selector

### 담당 범위

- 현재 국면에서 허용할 전략 선택
- execution style preference 제안
- 특정 전략 비활성화/감쇠

## 6. Signal Agent

### 최종 모양

- Deterministic scoring engine

### 담당 범위

- 기술적 지표 점수
- 수급/모멘텀/변동성 score
- event/news derived factor score

### 비고

- 이 축은 LLM보다 수치 재현성과 backtest 일관성이 중요하다.

## 7. News/RAG Agent

### 최종 모양

- Provider AI Agent + retrieval/event ingestion hybrid

### 담당 범위

- 뉴스/공시/리포트 요약
- 리스크 태깅
- 이벤트 relevance 판단

### 현재 구현과의 연결

- v1의 Event Interpretation Agent가 이 역할 일부를 선점하고 있다.
- **v1 External Event Source = OpenDART only** (T1_REGULATORY). 뉴스 source adapter는 P2 Backlog으로 보류.
- external event pipeline + OpenDART adapter는 v1에서 정상 운영 중.
- 뉴스 source 통합은 P0-1~P1-B (OpenDART symbol 매핑 → EI prompt 개선) 안정화 후 재검토.

### News Source 평가 이력 (2026-05-12)

| 평가 | 접근법 | 결과 |
|------|--------|------|
| 1차 | Naver Finance Scraping | ❌ Legal Gate No-Go |
| 2차 | Naver News Search API | ❌ 3-way 검증 No-Go |
| 3차 | 대체 후보 6개 비교 | ❌ 모두 v1 기준 No-Go |

**핵심**: Company name 기반 검색은 검색 접근법 자체의 한계 (precision 24~26%), Symbol 직접 매핑 source는 한국 coverage 부족 또는 Legal 문제. Legal + 한국 Coverage + Symbol 직접 매핑을 모두 만족하는 source는 현재 없음.

**향후 재검토 조건**: Licensed vendor · Legal-approved source · Stronger symbol mapping path (LLM re-ranking)

## 8. Portfolio Agent

### 최종 모양

- Deterministic portfolio construction service
- optional AI explanation

### 담당 범위

- 목표 비중
- 종목 간 자본 배분
- concentration / exposure budget 반영

### 비고

- sizing은 deterministic backend가 우선이며 AI는 설명/추천에 머무는 것이 안전하다.

## 9. Order Construction Agent

### 최종 모양

- Deterministic order construction service
- AI output은 참고 입력으로만 사용

### 담당 범위

- 매수/매도 방향
- limit/market/stop 등 주문 타입 결정
- 시간 조건
- 청산 규칙 초안

### 경계

- broker submit 직접 호출 금지
- hard guardrail 우회 금지

## 10. AI Risk Manager Agent

### 최종 모양

- Provider AI Agent
- 단, 후단에 deterministic hard limits / guardrail이 반드시 존재

### 담당 범위

- 리스크 의견
- size adjustment factor
- volatility / liquidity / concentration 해석

### 실전 latency 관점

- AR은 event 해석을 처음부터 다시 하는 Agent가 아니라,
  EI summary + position/cash/risk snapshot fact를 빠르게 읽는 Agent에 가깝다.
- 따라서 실전에서는 EI보다 더 짧은 prompt와 timeout budget을 가져야 한다.
- raw recent_events를 다시 보더라도 provenance-rich short line만 허용하고,
  장황한 narrative 중복은 피하는 것이 맞다.

### 현재 구현과의 연결

- 현재 v1 real agent로 이미 연결되어 있다.

## 11. AI Compliance Agent

### 최종 모양

- Hybrid
- AI policy/compliance opinion + deterministic hard validator 분리

### 담당 범위

- 정책 위반 가능성 해석
- 전략 충돌
- 특수 이벤트 리스크
- rule ambiguity 해석

### 경계

- 브로커 절대 거부 조건
- 필수 필드 누락
- 금지 종목/권한 불일치

위 항목은 AI가 아니라 hard validator가 반드시 차단해야 한다.

## 12. Execution Agent

### 최종 모양

- Deterministic execution pipeline
- 사실상 `OrderManager + BrokerAdapter + ReconciliationService`

### 담당 범위

- 주문 제출
- 분할 실행
- 체결 추적
- 상태 전이
- unknown state reconciliation

### 비고

- 이름은 Agent지만, 이 축을 provider AI agent로 만들면 현재 설계 원칙과 충돌한다.

## 13. Performance Agent

### 최종 모양

- Deterministic analytics batch / reporting service
- optional AI narrative layer

### 담당 범위

- PnL attribution
- 전략별 기여도
- 거래 실패 원인 집계
- execution quality 분석

## 14. Model Monitor Agent

### 최종 모양

- Deterministic monitoring service + offline evaluation pipeline

### 담당 범위

- drift 탐지
- 과최적화 징후
- 실전/백테스트 괴리
- provider output quality degradation

## v1에서 실제로 우선 구현한 Agent 세트

현재 코드 기준 v1 우선순위는 아래 3개다.

1. Event Interpretation Agent
2. AI Risk Agent
3. Final Decision Composer

이 선택은 다음 이유로 타당하다.

### v1 실전 latency budget 해석

현재 v1 3-Agent 체인은 모두 Provider AI Agent이지만, 실전 운영에서는 동일 budget으로 취급하면 안 된다.

- EI: 가장 느릴 수 있으나, event provenance를 구조화하는 slowest analysis layer
- AR: EI보다 짧아야 하는 intermediate risk opinion layer
- FDC: 가장 짧아야 하는 final intent synthesis layer

원칙:

- event 수집은 background ingestion이 담당한다
- 주문 직전 판단 경로는 이미 정리된 context만 읽는다
- prompt quality를 높이기 위해 provenance를 넣더라도, event count cap / default omission / structured summary 우선 원칙을 유지해야 한다

- external event 해석은 AI 효용이 높다.
- 리스크 의견 계층은 AI 해석 가치가 크다.
- 아직 Market/Universe/Strategy/Signal/Portfolio/Order Construction이 전부 세분화되지 않았기 때문에,
  v1에서는 Final Decision Composer가 임시 통합 계층 역할을 수행할 수 있다.

## 장기적으로 세분화될 가능성이 높은 축

향후 `Final Decision Composer`가 더 얇아지고 아래 축이 독립할 가능성이 높다.

- Market Regime Agent
- Universe Selection Agent
- Strategy Selection Agent
- Signal Agent
- Portfolio Agent
- Order Construction Agent
- AI Compliance Agent

## 최종 원칙 정리

- 모든 책임을 결국 커버하되, 모두를 "같은 종류의 에이전트"로 만들 필요는 없다.
- live trading에서는 deterministic execution / reconciliation / guardrail이 AI보다 우선한다.
- AI는 해석과 정책 판단의 상위 계층을 담당하고, 계산과 제출은 backend service가 맡는다.
