# 엔터프라이즈급 AI 멀티 에이전트 매매 시스템 설계 지시서 V2

이 문서는 [`ENTERPRISE_TRADING_SYSTEM_DESIGN.md`](./ENTERPRISE_TRADING_SYSTEM_DESIGN.md)를 기반으로,  
**2026-05-10 현재까지 실제 구현된 구조와 남은 Gap**을 반영해 갱신한 실행 지향 버전이다.

원본 문서는 이상적인 최종 상태를 넓게 정의한다.  
이 V2 문서는 그 설계를 부정하지 않고, 다음을 명확히 한다.

1. 현재 실제로 구현된 범위
2. 이미 확정된 설계 원칙
3. 아직 남은 핵심 Gap
4. 다음 우선순위

이 문서의 핵심 관점은 다음과 같다.

- **paper와 live는 별도 시스템이 아니라 동일 시스템의 설정 기반 실행 모드**
- **AI는 판단 주체, backend는 deterministic execution / safety / traceability 주체**
- **live 이전에 paper 운영/성과/안정성 검증을 충분히 마친다**

---

## 1. 현재 시점의 최상위 상태

### 1.1 현재 구현 철학

현재 시스템은 원본 설계 문서의 전체 범위 중, 특히 아래 축을 우선 완성하는 방향으로 발전했다.

- KIS 중심 브로커 실행 코어
- 주문 안전성 및 정합성
- paper 운영 루프
- paper 성과 측정
- paper 합격 기준과 live readiness 평가

즉, 지금 시스템은 아직 “전체 enterprise platform 완성” 단계는 아니지만,  
**paper 기준의 폐쇄 루프 검증 가능한 자동매매 실행 코어**로는 상당히 진척된 상태다.

### 1.2 현재 구현 상태 한 줄 요약

```text
Decision → Sizing → Guardrail → Submit → Post-Submit Sync → Snapshot Refresh
→ Paper Performance Summary / History / Metrics / Benchmark
→ Paper Go/No-Go / Exit Criteria / Live Readiness
```

---

## 2. V2에서 고정하는 핵심 설계 원칙

### 2.1 Paper/Live 관계

- paper와 live는 서로 다른 시스템이 아니다.
- 동일한 decision pipeline, sizing, guardrail, reconciliation, observability, performance framework를 사용한다.
- 차이는 기본적으로 다음 설정에만 존재해야 한다.
  - `broker_env=paper|live`
  - broker credential
  - base URL / WebSocket URL
  - broker capability / rate limit profile
  - validation / approval / exit criteria의 강도

### 2.2 실행 경계

- AI는 판단을 담당한다.
- backend는 다음을 deterministic하게 담당한다.
  - order request translation
  - sizing
  - hard guardrail
  - broker submit
  - state transition
  - reconciliation / post-submit sync
  - snapshot freshness gating

### 2.3 운영 원칙

- 신규 주문보다 계좌 보호와 상태 정합성이 우선이다.
- 모호한 broker 상태에서는 재주문보다 reconciliation이 우선이다.
- live 전환보다 paper 검증이 우선이다.
- 성과 측정은 절대값뿐 아니라 benchmark 대비 상대값까지 확인한다.

---

## 3. 현재 실제 구현된 핵심 범위

### 3.1 브로커 / 실행 코어

현재 구현상 가장 강한 축이다.

구현 완료 또는 실질 구현 상태:

- `BrokerAdapter` 기반 공통 계약
- `KoreaInvestmentAdapter` 중심 실행 경로
- KIS REST / WebSocket 연동
- KIS rate limit / capacity / strict global cap
- broker-agnostic snapshot runner
- broker-aware snapshot factory
- submit pipeline
- safe order path E2E
- reconciliation / blocking lock / stale snapshot guard

현재 판단:

- **KIS 중심 코어는 강함**
- **멀티 브로커 구조는 준비되었지만 실구현은 KIS 위주**

### 3.2 결정 파이프라인

현재 AI 판단 경로는 완전한 multi-agent full mesh는 아니지만, 실전적 최소 경로는 구현됐다.

현재 중심 구성:

- EI
- AR
- FDC
- `assemble_and_submit()`
- deterministic sizing phase
- `TradeDecisionEntity` 저장
- `OrderManager` submit 연계

현재 판단:

- **AI Decision → Submit 실행 경로는 연결 완료**
- **원본 문서의 전체 Agent 집합에는 아직 못 미침**

### 3.3 주문 후 상태 수렴

이 축은 현재 매우 잘 구현된 편이다.

현재 구현:

- `OrderSyncService.sync_order_post_submit()`
- scheduler 기반 post-submit polling loop
- KIS WS fill notification 기반 fast-path sync trigger
- Phase 5.5 submit 직후 first sync
- fill terminal 감지 시 snapshot refresh
- snapshot refresh direct integration

현재 판단:

- **submit 이후 상태 반영/수렴 경로는 paper 기준으로 상당히 완성도 높음**

### 3.4 Snapshot / Freshness / Health

현재 구현:

- snapshot sync batch/all accounts
- run history 저장
- inspection API
- freshness summary
- readiness degraded 정책
- startup grace
- submit 직전 stale snapshot guard
- account-level freshness 정밀화

현재 판단:

- **snapshot freshness는 주문 안전성에 실제로 연결된 상태**
- **run-level summary와 account-level freshness가 분리되어 있음**

### 3.5 Paper 운영 루프

현재 구현:

- `run_snapshot_sync_loop.py`
- `run_post_submit_sync_loop.py`
- `run_paper_decision_loop.py`
- `run_event_ingestion_loop.py`
- `verify_paper_loop.py`

현재 판단:

- **paper 운영용 데몬/루프 구조는 거의 한 세트로 갖춰짐**
- **이제는 “운영 가능”을 넘어서 “운영 평가 가능” 단계까지 도달**

### 3.6 성과 평가 계층

현재 구현:

- `GET /performance-summary`
- `GET /performance-history`
- `GET /performance-metrics`
- `GET /performance-benchmark`

주요 지원 지표:

- realized / unrealized / total pnl
- daily history
- cumulative return
- drawdown
- win rate
- avg win / avg loss
- profit factor
- benchmark excess return

현재 판단:

- **paper 수익성 평가의 최소 백엔드 기준은 확보**
- **Sharpe/Sortino/Calmar/turnover 등은 아직 후속**

### 3.7 Paper/Llive 검증 게이트

현재 구현:

- `PaperGateService`
- `GET /performance/paper-go-no-go`
- `evaluate_paper_exit.py`
- `evaluate_live_gate.py`
- `mode_boundary_paper_live.md`

현재 판단:

- **paper 합격 기준**
- **live 검토 readiness**
가 분리되어 정리되어 있음

단, 이것은 아직 **실제 live 주문 허용 정책**이 아니라  
**live 검토 자격의 read-only 평가 레이어**다.

---

## 4. 원본 설계 문서 대비 현재 구현 분류

### 4.1 이미 잘 반영된 항목

| 영역 | 상태 | 비고 |
|---|---|---|
| KIS primary broker 구조 | 강하게 반영 | 실제 구현 중심축 |
| BrokerAdapter 경계 | 반영 | KIS 전용 구현 격리 |
| AI Final Trade Decision ↔ 실제 주문 분리 | 반영 | deterministic backend 경계 확립 |
| Hard Guardrail Layer | 반영 | stale/account freshness, duplicate, lock, safe path |
| Reconciliation / state sync | 반영 | post-submit sync, WS fast path, polling fallback |
| paper trading 검증 우선 | 강하게 반영 | 현재 개발 주축 |
| 감사/추적성 | 부분 강함 | traceability와 audit 성격은 강화됨 |
| 성과 분석 기본 계층 | 반영 | summary/history/metrics/benchmark |

### 4.2 부분 반영된 항목

| 영역 | 상태 | 설명 |
|---|---|---|
| Multi-Agent 구조 | 부분 반영 | EI/AR/FDC 중심, 나머지 Agent는 미약 |
| 운영/관측성 | 부분 반영 | health/readiness/gate/API는 있음, full monitoring stack은 아님 |
| Compliance / Risk | 부분 반영 | AI risk/compliance + hard guardrail은 있음, portfolio-level 정교화 부족 |
| Event ingestion | 부분 반영 | loop/worker는 있음, source 다양성/운영성은 제한적 |
| Paper/Live boundary | 반영 | mode boundary 원칙 정리 완료, naming은 일부 paper 중심 |

### 4.3 큰 Gap으로 남은 항목

| 영역 | 상태 | 설명 |
|---|---|---|
| Full event-driven backtest engine | 큰 Gap | replay 검증은 강하나 full backtest는 아님 |
| Control Plane / Config / Approval workflow | 큰 Gap | versioned config/approval rollout은 제한적 |
| Full multi-agent stack | 큰 Gap | design spec의 agent 폭에 아직 미달 |
| Multi-broker real implementation | 큰 Gap | KIS 외 실질 구현 없음 |
| Enterprise data/infra stack | 큰 Gap | Redis/Timeseries/S3/VectorDB/Kafka 미구현 또는 축소 |
| Live canary actual execution policy | 큰 Gap | readiness는 있으나 live submit policy 없음 |

---

## 5. 현재 구조를 반영한 아키텍처 요약

### 5.1 현재 실질 운영 흐름

```text
Event Ingestion Loop
  -> External Events / Normalized Events

Snapshot Sync Loop
  -> Cash / Positions Snapshot
  -> Freshness / Health

Paper Decision Loop
  -> EI / AR / FDC
  -> TradeDecisionEntity
  -> Deterministic Sizing
  -> Hard Guardrail
  -> Order Submit
  -> Phase 5.5 Immediate Post-Submit Sync

WS Fill Notification / Post-Submit Sync Loop
  -> Order State / Fills / Snapshot Refresh

Performance Layer
  -> Summary
  -> History
  -> Metrics
  -> Benchmark Comparison

Evaluation Layer
  -> Paper Go/No-Go
  -> Paper Exit Criteria
  -> Live Gate / Canary Readiness
```

### 5.2 현재 Control / Trading / Observability Plane 재해석

#### Control Plane

현재 일부만 구현:

- auth / RBAC 일부
- paper exit criteria
- live readiness evaluation
- mode boundary 문서화

아직 부족:

- strategy registry
- prompt registry 정식화
- model registry 정식화
- live approval workflow
- config rollout / approval

#### Trading Plane

현재 강하게 구현:

- KIS adapter
- order manager
- decision orchestrator
- sizing
- stale/account guard
- post-submit sync
- WS-triggered sync

#### Observability Plane

현재 부분 구현:

- health / readyz
- snapshot freshness
- performance summary/history/metrics/benchmark
- paper gate
- paper exit
- live gate readiness

아직 부족:

- alert routing
- metrics stack
- tracing
- operator intervention tools

---

## 6. Multi-Agent 구조 V2 해석

원본 문서는 매우 넓은 Agent 집합을 정의한다.  
현재 구현은 아래처럼 **축소된 실전형 최소 경로**를 중심으로 되어 있다.

### 6.1 현재 실질 Agent 계층

| Agent | 현재 상태 |
|---|---|
| Event Interpretation | 구현 |
| AI Risk | 구현 |
| Final Decision Composer | 구현 |
| Performance 평가 계층 | 부분 구현 |
| Model Monitor | 미구현 |
| Market Regime | 미구현/축소 |
| Universe Selection | 미구현/축소 |
| Strategy Selection | 미구현/축소 |
| News/RAG | 미구현/축소 |
| Portfolio Agent | 미구현/축소 |

### 6.2 V2 원칙

- 현재는 `EI → AR → FDC`를 **v1 실행 코어**로 간주한다.
- 나머지 Agent는 향후 확장 영역으로 남긴다.
- 즉, “multi-agent”의 완전한 폭보다 **주문 실행과 안전성**을 우선한 구현 상태다.

---

## 7. Risk / Compliance / Guardrail V2

### 7.1 현재 강한 부분

- AI 판단과 hard guardrail 분리
- duplicate / stale / account freshness / blocking lock 차단
- safe order path E2E 검증
- reconcile_required / unknown-state 보호

### 7.2 아직 약한 부분

- correlation risk
- beta exposure
- sector exposure
- hedge / de-risk 전략
- overnight risk
- leverage / cross-account risk

### 7.3 V2 판단

현재는 **order safety 중심 리스크 구조**는 충분히 강하지만,  
**portfolio-level risk management**는 아직 원본 설계 수준에 못 미친다.

---

## 8. Backtest / Paper / Live 전환 V2

### 8.1 현재 현실적 상태

| 단계 | 상태 |
|---|---|
| Replay-style deterministic validation | 강함 |
| Paper trading 운영 루프 | 강함 |
| Paper 성과 평가 | 강함 |
| Paper exit / live readiness | 강함 |
| Full event-driven backtest engine | 약함 |
| Live canary execution policy | 미구현 |

### 8.2 V2 원칙

- live 이전 검증의 실제 주력 수단은 현재 **paper + replay**다.
- full backtest engine은 아직 후속 우선순위다.
- live 진입 전에는 다음이 반드시 전제되어야 한다.
  - paper exit PASS
  - live readiness READY
  - 운영자 수동 검토 완료

---

## 9. 성과 분석 V2

### 9.1 현재 제공되는 성과 계층

| 계층 | 상태 |
|---|---|
| summary | 구현 |
| daily history | 구현 |
| performance metrics | 구현 |
| benchmark comparison | 구현 |

### 9.2 아직 남은 KPI Gap

원본 문서 KPI 대비 아직 부족한 것:

- Sharpe ratio
- Sortino ratio
- Calmar ratio
- turnover
- 평균 보유 기간
- Agent별 기여도
- 전략별 기여도 정교화
- backtest vs paper/live 괴리 지표
- 주문 실패율 / 체결 지연 / API 오류율의 성과 지표화

### 9.3 V2 판단

현재는 **paper 수익성 판단**에는 충분하지만,  
**enterprise-grade performance analytics**로는 아직 후속이 남아 있다.

---

## 10. 데이터 아키텍처 V2

원본 문서의 데이터 아키텍처는 미래 확장형이다.  
현재 구현은 훨씬 단순화되어 있다.

### 10.1 현재 실질 저장 축

- PostgreSQL 중심 저장
- in-memory test repositories
- snapshot/fill/order/decision/event 저장

### 10.2 아직 미구현 또는 축소 상태

- Redis 실시간 cache/lock/rate limit 계층
- TimescaleDB / ClickHouse 시계열 분리
- S3 / MinIO artifact 저장
- Vector DB 기반 RAG
- Kafka / Redpanda event bus

### 10.3 V2 원칙

- 현재는 **실행 코어와 paper 검증 루프**를 우선한다.
- infra-grade 분리 저장소는 scale 단계에서 도입한다.

---

## 11. 보안 및 운영성 V2

### 11.1 현재 확보된 것

- auth / RBAC 일부
- 감사/추적성 강화
- health/readyz
- paper/live mode boundary 정리

### 11.2 아직 부족한 것

- secret manager 기반 완전 전환
- strong admin auth / MFA
- immutable audit storage
- network security hardening
- live activation privilege 분리

### 11.3 V2 판단

현재는 **개발/검증 단계 운영 보안** 수준이고,  
실전 production-grade security hardening은 아직 후속이다.

---

## 12. 현재 기준 우선순위 재정렬

### 12.1 P1

가장 먼저 해결해야 할 남은 큰 Gap:

1. full event-driven backtest engine
2. control plane / config / approval workflow
3. 운영/관측성 핵심 보강
4. live canary actual execution policy

### 12.2 P2

다음 확장 우선순위:

1. multi-agent 확장
2. multi-broker 실구현
3. portfolio-level risk/compliance 고도화
4. performance analytics 확장

### 12.3 P3

장기 확장 우선순위:

1. infra/data architecture 확장
2. security hardening
3. full observability stack
4. replay UX / operator tooling

---

## 13. 개발 단계 V2 재정의

원본 19장의 phase는 유효하지만, 현재 상태를 반영하면 다음처럼 재해석하는 것이 맞다.

### 완료 또는 실질 완료

- Phase 1 Foundation: 상당 부분 완료
- Phase 2 KoreaInvestment Adapter: 핵심 완료
- Phase 5 AI Risk / AI Compliance / Guardrail: 실전형 최소 범위 완료
- Phase 7 Execution Engine: 핵심 완료
- Phase 8 Dashboard / Operations: 기본 운영 계층 부분 완료

### 부분 완료

- Phase 3 Data Pipeline
- Phase 4 Backtest / Paper Trading
- Phase 6 Multi-Agent Decision Engine

### 아직 미완성

- Phase 9 Live Canary

---

## 14. 현재 기준의 권장 Repository/Runtime 해석

현재 실제 코드베이스는 원본 문서의 이상적인 repository 구조보다 단순하다.  
그러나 구조적 방향은 다음으로 유지한다.

### 공통 코어

- brokers
- services
- repositories
- runtime
- config
- domain

### paper 검증 레이어

- paper decision loop
- paper gate
- paper exit criteria
- paper performance evaluation

### future live layer

- live gate
- live canary execution policy
- operator approval / intervention

즉, **코어는 공통**, **paper/live는 운영 모드 및 검증/전환 레이어**로 분리한다.

---

## 15. V2에서 명시적으로 남기는 남은 Gap

### 15.1 반드시 남겨둘 Gap

- full backtest engine
- config approval / control plane
- live canary execution policy
- operator intervention workflow
- portfolio-level risk
- benchmark history / relative trend 심화

### 15.2 의도적으로 후순위로 둔 Gap

- KiwoomAdapter 실구현
- infra stack full separation
- vector DB / RAG 본격화
- metrics/tracing stack
- advanced performance analytics

---

## 16. 최종 V2 요약

현재 시스템은 다음처럼 이해해야 한다.

```text
동일 코어 시스템
  + KIS 중심 broker execution
  + deterministic backend execution/safety
  + paper 운영 루프
  + paper 성과 평가
  + paper 합격 기준
  + live readiness 평가

아직 남은 것
  + full backtest
  + control plane / approval
  + live canary actual policy
  + full multi-agent / multi-broker / observability 확장
```

즉, 이 시스템은 현재

- “아이디어 수준 설계 문서”
가 아니라
- **paper 단계까지는 실운영 가능한 자동매매 코어**

에 가깝다.

다만 원본 설계 문서가 지향한 **enterprise-grade full platform**까지는 아직 거리가 있으며,  
다음 확장 우선순위는 **backtest / control plane / live canary policy**다.

