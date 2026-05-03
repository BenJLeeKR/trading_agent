# MVP 범위 및 전달 계획 v1

## 1. v1 목표

실전 투입 전 검증 가능한 최소 폐쇄 루프를 만든다.

```text
시장 데이터 수집
-> 데이터 품질 점검
-> 단일 전략 판단
-> 리스크/컴플라이언스 평가
-> hard guardrail
-> 한국투자증권 모의투자 주문
-> 체결 반영
-> 정합성 점검
-> 성과/감사 기록
```

## 2. v1 포함 범위

- 자산군: 국내주식
- 브로커: 한국투자증권
- 환경: 모의투자 우선, 실전은 canary만
- 계좌 수: 계좌 1개
- 전략 수: 전략 1개
- 의사결정: 단일 orchestrator + v1 Provider AI Agent 3개 (Event Interpretation, AI Risk, Final Decision Composer) + deterministic backend engine
- UI: 운영자용 최소 대시보드 또는 API

## 3. v1 제외 범위

- 키움 어댑터 구현
- 파생상품
- 다중 계좌 라우팅
- 멀티 전략 자본 배분 최적화
- 자동 모델 재학습
- 자동 scale-up
- live 중 자동 모델 재학습 반영
- LLM debate 기반 주문 승인
- 고빈도 매매
- 시장가 주문 기본 허용
- 다중 브로커 smart order routing
- 완전 자동 장애 복구 후 재개
- 운영자 승인 없는 kill-switch 해제

## 4. 단계별 구현 순서

### Step 0. Simulation Harness

- mock broker transport
- simulated quote/orderbook generator
- deterministic fill simulator
- partial fill scenario
- rejected order scenario
- submit timeout scenario
- websocket disconnect scenario
- duplicate event scenario
- reconciliation mismatch scenario

### Step 1. Foundation

- 저장소 구조 생성
- config schema 및 secret reference 구현
- 공통 로깅, correlation id, audit logging
- 핵심 DB 스키마 생성

### Step 2. Broker Core

- `BrokerAdapter` 인터페이스
- `KoreaInvestmentAdapter` 뼈대
- auth manager
- quote/order/position 조회

### Step 3. Safe Order Path

- order manager
- idempotency
- hard guardrail
- reconciliation worker

### Step 4. Data and Replay

- market data ingestion
- feature snapshot 저장
- decision context 저장
- replay bundle 생성

### Step 5. Paper Trading Loop

- paper submit
- fill sync
- paper PnL 계산
- 운영 알림

### Step 6. AI Decision Layer

- v1 Provider AI Agent 3개 순차 도입
  - Event Interpretation Agent (external event 구조화 우선)
  - AI Risk Agent (리스크 의견 + size adjustment factor)
  - Final Decision Composer (최종 매매 의도 통합)
- orchestrator (Agent 실행 순서 관리, AssembledContext 조립)
- deterministic backend engine (score/threshold/sizing 계산)
- structured decision output (JSON schema, raw output 저장)
- audit / replay 기반 확보 (agent 실행마다 schema_version, model_id, prompt_id 저장)

### Step 7. Live Canary

- 소액/소종목/제한 시간대 실전 전환
- reject/error/delay 모니터링 강화
- 운영자 수동 승인 옵션 유지

## 5. 완료 기준

### 5.1 Step 2 완료 기준

- 모의투자 환경에서 인증 성공
- 시세 조회 가능
- 잔고 조회 가능
- 주문 전송 및 주문 상태 조회 가능

### 5.2 Step 3 완료 기준

- 중복 주문 차단 동작
- kill switch 강제 중단 동작
- timeout 후 reconcile 경로 동작
- unknown order state 발생 시 신규 주문 차단
- partial fill 후 exposure 반영
- cancel timeout 후 reconcile 경로 동작
- idempotency key 중복 주문 방지
- order_state_event append-only 기록
- guardrail_evaluation 저장
- audit log 저장 실패 시 live 주문 차단

### 5.0 Step 0 완료 기준

- 실제 KIS API 없이 safe order path를 end-to-end로 테스트 가능
- 같은 seed와 같은 scenario에서 같은 결과 재현
- duplicate order prevention 테스트 통과
- unknown state에서 신규 주문 차단 테스트 통과

### 5.3 Step 4 완료 기준

- decision_context 재생성 가능
- feature snapshot point-in-time 정합성 검증
- config/model/prompt/calculation version 저장
- replay 결과가 원 판단과 다를 경우 mismatch reason 기록
- market data stale event 저장

### 5.4 Step 5 완료 기준

- 하루 장중 paper trade를 무인 실행
- 체결/잔고/포지션 불일치 탐지
- 감사 로그와 PnL 리포트 생성
- 최소 20 거래일 paper run 권장
- 주문 오류율, reconciliation mismatch, fill latency 측정
- 예상 체결가와 simulated/actual fill price 괴리 리포트
- 일별 PnL, MDD, turnover, reject count 리포트
- paper 환경에서 kill switch 발동 테스트
- paper/live divergence 측정을 위한 필드 저장

### 5.5 Step 6 완료 기준

- AI output JSON schema validation
- net_expected_value_bps가 threshold 이하일 때 주문 거부
- risk/compliance/execution check 중 하나라도 실패하면 `order_request` 미생성
- opposing_evidence가 비어 있지 않도록 강제 또는 warning
- LLM raw output과 structured output 저장
- backend calculation version 저장
- 동일 입력 replay 시 동일 decision 재현 또는 nondeterminism 표시

### 5.6 Step 7 완료 기준

- canary live 주문 수 제한
- 실패 시 자동 신규 주문 중단
- 운영자 알림 및 수동 개입 가능
- canary 자본 상한 적용
- 일간 주문 횟수 상한 적용
- 수동 승인 옵션 활성화
- audit log unavailable 시 live halt
- broker API error rate threshold 초과 시 신규 주문 중단
- quote delay threshold 초과 시 신규 주문 중단
- 주문 상태 불명확 시 `account/symbol/strategy` lock
- canary 종료 후 운영 리뷰 문서 생성

## 5.7 Go / No-Go Criteria

| 단계 | Go 조건 | No-Go 조건 |
|---|---|---|
| Paper -> Canary | 최소 N 거래일 정상 운용, mismatch 기준 이하, kill switch 테스트 통과 | 주문 중복, reconciliation 실패, audit 누락 |
| Canary -> Limited Live | 소액 실전에서 오류율 기준 이하, 체결 괴리 허용범위 이내 | unknown state 반복, API 오류율 초과, 손실한도 경보 |
| Limited Live -> Full Live | 운영 리뷰 승인, 리스크 지표 안정, replay 재현성 확보 | 성과보다 운영 안정성 미달 |

## 6. 바로 다음 실무 작업

아래 순서로 바로 이어가면 된다.

1. `src/` 기준 패키지 구조 생성
2. DB 스키마 초안 작성
3. `BrokerAdapter`와 공통 domain model 코드화
4. `KoreaInvestmentAdapter` mock transport 기반 contract test 작성
5. paper 환경 end-to-end 시나리오 테스트 작성
