# 시스템 아키텍처 상세 설계 v1

## 1. 목적

이 문서는 엔터프라이즈급 AI 멀티 에이전트 매매 시스템의 구현 단위를 정의한다.  
초기 구현의 우선순위는 다음과 같다.

1. 브로커 추상화와 한국투자증권 기본 연동
2. 데이터 정합성과 상태 동기화
3. 주문 안전장치와 감사 가능성
4. 백테스트/페이퍼트레이딩 기반
5. 그 위에 AI 의사결정 계층

## 2. 시스템 경계

### 2.1 외부 시스템

- 한국투자증권 KIS REST API
- 한국투자증권 KIS WebSocket
- 선택 브로커 REST/WebSocket
- 시세/뉴스/거시 데이터 공급자
- 알림 채널 Slack, Email, PagerDuty
- 운영자 UI 및 관리 API

### 2.2 내부 시스템

- Control Plane
- Trading Plane
- Data Plane
- Observability Plane

## 3. 논리 아키텍처

```text
Admin UI / Client API
  -> Config Service
  -> Strategy Registry
  -> Model Registry
  -> Prompt Registry

Scheduler / Session Controller
  -> Market Data Ingestion
  -> Data Quality Service
  -> Feature Pipeline
  -> Decision Orchestrator
  -> AI Risk Agent
  -> AI Compliance Agent
  -> Hard Guardrail Engine
  -> Portfolio Engine
  -> Order Manager
  -> Broker Router
  -> Broker Adapter
  -> Reconciliation Service

Event Bus / Workflow Log
  -> Audit Log
  -> Monitoring
  -> Replay Engine
  -> Backtest / Paper Engine
```

## 4. 핵심 컴포넌트와 책임

### 4.1 Config Service

- 클라이언트별 설정 버전 관리
- 실전/모의 환경 분리
- 전략/리스크/브로커 파라미터 조회
- 롤백 가능한 설정 배포
- 공용 정책 계층과 개인 credential 계층 분리

### 4.1.1 공용 Plane / 개인 Plane 분리 원칙

향후 P3 멀티 사용자 리팩토링에서는 아래 경계를 유지한다.

- 공용 Plane
  - instrument master
  - market session / 휴장일 / 장상태 수집
  - universe selection 정책
  - feature 계산식
  - deterministic trigger / eligibility / ranking 엔진
  - broker adapter 구현체
  - audit / replay / reconciliation 프레임워크
- 개인 Plane
  - KIS 계좌 credential
  - AI provider credential
  - NAVER 등 외부 API credential
  - 주문 가능 계좌 매핑
  - 사용자별 리스크 / execution override

원칙:

- 공용 Plane은 코드와 정책을 공유하되, 결과 데이터 소유권은 `client_id`, `account_id`로 분리한다.
- 개인 Plane에서 관리되는 비밀값은 Control Plane의 secret resolver를 통해서만 Trading Plane으로 주입한다.
- Trading Plane은 전역 `.env` 기반 단일 runtime 설정을 authoritative source로 사용하지 않는다.

### 4.2 Session Controller

- 장 상태 판단
- 거래 세션 시작/종료 이벤트 발행
- 전략별 스케줄 관리
- 장중 신규 주문 가능 여부 전역 제어

### 4.3 Market Data Ingestion

- REST 초기 스냅샷 수집
- WebSocket 실시간 시세 구독
- 종목 마스터 및 휴장/거래정지 정보 동기화
- 외부 데이터 소스 정규화

### 4.4 Data Quality Service

- 필수 필드 누락 검사
- timestamp 역전/지연 감지
- 가격 상하한/이상치 검사
- 데이터 소스 간 불일치 알림
- 품질 등급 산출 후 downstream 전달

### 4.5 Feature Pipeline

- 시계열 feature 생성
- 종목별/전략별 feature snapshot 저장
- 결정 시점 기준 point-in-time 정합성 보장
- 장후 batch는 외부 market data fetch 실패와 DB persist 실패를
  분리 관측/재실행 가능해야 한다.
- feature snapshot batch는
  `universe freeze -> fetch stage -> persist stage -> failed-symbol retry`
  구조를 권장한다.
- 동일 snapshot 시점 재실행은 idempotent 해야 하며,
  일부 종목 실패가 전체 batch를 오염시키지 않도록
  종목 단위 isolation(savepoint 또는 동등 구조)을 둔다.

### 4.6 Decision Orchestrator

- 입력 컨텍스트 조립
- Agent 실행 순서 관리
- Agent 간 충돌 조정
- 최종 주문 의사결정 구조화

### 4.7 AI Risk Agent

- 전략 의도와 현재 포지션, 변동성, 손실 노출을 평가
- 허용 가능 리스크 범위와 축소/거절 의견 반환

### 4.8 AI Compliance Agent

- 주문 가능 시간, 금지 종목, 과도한 회전율, 계좌 정책 위반 여부 판단
- 위반 가능성에 대한 structured decision 반환

### 4.9 Hard Guardrail Engine

- 계좌/종목/일별 손실 한도
- 주문 중복 차단
- 최대 주문 수량/금액
- 브로커 capability 위반 차단
- kill switch 강제 적용

### 4.10 Portfolio Engine

- 전략별 target position 계산
- 현 포지션 대비 rebalance order 생성
- 현금, 증거금, 통화 노출 계산

### 4.11 Order Manager

- client order id 생성
- 주문 상태 전이 관리
- 재시도와 보류 처리
- 주문/체결 이벤트 영속화

### 4.12 Broker Router

- 계좌-브로커 매핑
- capability 확인
- 어댑터 호출 위임

### 4.13 Reconciliation Service

- 내부 주문/포지션 상태와 브로커 상태 비교
- 체결 누락, 부분 체결, 취소 불일치 복구
- 일마감 기준 상태 스냅샷 확정

### 4.14 Replay Engine

- 특정 decision context 재생성
- 동일 feature, config, model, prompt 버전으로 판단 재현
- backtest/paper/live 결과 비교

## 5. 런타임 상호작용 원칙

- 모든 동기 호출에는 `correlation_id`를 부여한다.
- 주문 이벤트는 append-only event log에도 기록한다.
- 브로커 호출 결과가 불확실할 때는 재주문보다 상태 조회를 우선한다.
- 신규 주문보다 상태 정합성 복구가 우선이다.
- AI 출력은 자유 텍스트가 아니라 구조화 JSON으로 정규화한다.

## 5.1 Runtime Safety Boundary

- `Decision Orchestrator`는 주문 의도를 생성할 수 있지만 직접 broker submit을 호출할 수 없다.
- `Order Manager`만 주문 상태 전이의 source of truth가 될 수 있다.
- `Hard Guardrail Engine`은 `AI Risk Agent`, `AI Compliance Agent`보다 후단에 위치하지만 최종 주문 생성 여부에 대해 더 높은 우선순위를 가진다.
- `Broker Adapter`는 주문 가능 여부를 스스로 판단하지 않는다. adapter는 capability 확인과 broker 응답 정규화만 수행한다.
- `Reconciliation Service`가 불일치를 감지한 `account/symbol/strategy` 조합은 신규 주문 차단 상태가 될 수 있어야 한다.
- `Trading Plane`은 Control Plane 설정 변경을 즉시 무조건 반영하지 않는다. runtime에 고정된 config version을 사용하고, reload 이벤트는 검증 후 적용한다.

## 5.2 Plane Failure Isolation

- Data Plane 장애 시 신규 진입을 중단하되, 포지션 축소 또는 청산 판단은 정책에 따라 제한적으로 허용한다.
- Observability Plane 장애는 trading halt 사유가 될 수 있다. 특히 audit log 저장 실패 시 live 주문은 중단한다.
- Control Plane 장애 중에는 기존 runtime config로 읽기 전용 운용만 허용한다.
- Broker Gateway 장애 시 신규 주문은 중단하고, 상태 조회와 reconciliation을 우선한다.
- AI Decision Layer 장애 시 deterministic fallback 정책을 사용할 수 있는지 명시한다. fallback이 없으면 신규 진입 금지다.

## 5.3 Service Ownership Matrix

| 기능 | Source of Truth | Write 권한 | Read 권한 | 비고 |
|---|---|---|---|---|
| 주문 상태 | Order Manager | Order Manager | Reconciliation, Monitoring | Adapter 직접 수정 금지 |
| 포지션 상태 | Reconciliation Service | Reconciliation Service | Portfolio, Risk | broker 기준과 내부 기준 동시 보존 |
| 설정 버전 | Config Service | Config Service | Runtime Services | 세션 중 변경은 reload 이벤트 필요 |
| feature snapshot | Feature Pipeline | Feature Pipeline | Decision, Replay | point-in-time 보장 |
| audit event | Audit Log Service | 모든 서비스 append | Monitoring, Replay | 수정 불가 |

## 5.4 Replay Consistency Contract

- `Replay Engine`은 단순 로그 조회기가 아니라 decision context를 재구성할 수 있어야 한다.
- replay 대상에는 `config version`, `strategy version`, `model version`, `prompt version`, `feature snapshot`, `market data reference`, `agent raw output`, `backend calculation version`이 포함되어야 한다.
- live와 paper의 replay 결과를 비교할 때 broker fill과 simulated fill의 차이를 별도 layer로 분리한다.
- replay 결과가 원래 trade decision과 다르면 version mismatch 또는 nondeterministic output으로 표시한다.

## 5.5 Provider AI Agent Boundary

v1 Provider AI Agent 3개(Event Interpretation Agent, AI Risk Agent, Final Decision Composer)는 **Decision Layer** 내에 위치하며, 아래 실행 경로를 따른다.

```text
Provider AI Agents
  -> Decision Orchestrator
  -> Deterministic Score / Threshold Engine
  -> Hard Guardrail Engine
  -> Order Manager
  -> Broker Adapter
```

**경계 규칙**:

- Provider AI Agent는 **판단 계층**이며 직접 주문을 제출하지 않는다.
- Agent 출력은 자유 텍스트가 아니라 JSON schema를 준수하며, raw output과 structured output을 모두 저장한다.
- 최종 수치 계산(expected value, final trade score, position size), threshold 판정, hard guardrail은 **deterministic backend**가 수행한다.
- `Decision Orchestrator`는 Agent 실행 순서를 관리하고, Agent 출력을 `AssembledContext`로 조립하여 백엔드 계산 계층에 전달한다.
- Fast / Slow Layer 분리 원칙을 유지한다. v1의 Provider AI Agent는 기본적으로 Slow Layer 중심으로 운용하며, intraday execution path에서는 직접적인 LLM 호출보다 사전 계산된 구조화 출력과 deterministic backend를 우선 사용한다.
- `Order Manager`만 주문 상태 전이의 source of truth가 될 수 있으며, 어떤 AI Agent도 이 경로를 우회할 수 없다.

## 6. 배포 단위 v1

### 6.1 단일 서비스로 묶어도 되는 영역

- Config API
- Strategy Registry
- Backtest API
- Admin API

### 6.2 분리 권장 영역

- `trading-runtime`
- `broker-gateway`
- `market-data-worker`
- `reconciliation-worker`
- `monitoring-alert-worker`

### 6.3 저장소

- PostgreSQL: 거래/설정/감사 메타데이터
- Redis: 캐시, 세션 상태, idempotency lock
- Object Storage: raw market data, raw agent output, replay bundle
- Time-series store optional: 고빈도 시세 및 메트릭

## 7. 비기능 설계

### 7.1 가용성

- 브로커 장애 시 신규 주문 자동 중단
- 읽기 전용 모드 지원
- 실시간 데이터 단절 시 degraded mode 전환

### 7.2 일관성

- 주문 상태는 event-sourced log와 current-state table을 함께 유지
- 포지션은 브로커 기준과 내부 기준을 모두 저장

### 7.3 보안

- 브로커 자격증명은 secret manager에 보관
- 운영자 행위도 감사 로그에 남김

## 8. v1 구현 제외 범위

- 멀티 브로커 동시 라우팅
- 파생상품 주문
- 다중 국가/다중 통화 자동 헤지
- 완전 자동 모델 재학습 파이프라인
