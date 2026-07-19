# Roo Code 인계 문서

## 1. 목적

이 문서는 현재 저장소의 핵심 설계와 초기 코드 골격 상태를 Roo Code의 DeepSeek-Reasoner가 이어받아 실무 설계 및 구현을 진행할 수 있도록 정리한 인계 문서다.

Codex는 이 시점까지 다음 범위를 담당했다.

- 상위 설계 방향 정리
- 상세 설계 문서 세트 작성
- `src/` 패키지 골격 생성
- 공통 `BrokerAdapter` 계약 정의
- PostgreSQL DDL 초안 작성
- `dataclass + repository interface` 기반 저장 계층 계약 정의

이후 구현의 중심은 Roo Code가 맡는 것을 전제로 한다.

## 2. 현재 산출물

### 2.1 상위 설계 문서

- [ENTERPRISE_TRADING_SYSTEM_DESIGN.md](/workspace/agent_trading/plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md:1)

### 2.2 상세 설계 문서 세트

- [README.md](/workspace/agent_trading/plan_docs/detailed_design/README.md:1)
- [01_system_architecture.md](/workspace/agent_trading/plan_docs/detailed_design/01_system_architecture.md:1)
- [02_order_execution_sequence.md](/workspace/agent_trading/plan_docs/detailed_design/02_order_execution_sequence.md:1)
- [03_data_model_erd.md](/workspace/agent_trading/plan_docs/detailed_design/03_data_model_erd.md:1)
- [04_broker_adapter_interface.md](/workspace/agent_trading/plan_docs/detailed_design/04_broker_adapter_interface.md:1)
- [05_koreainvestment_adapter_spec.md](/workspace/agent_trading/plan_docs/detailed_design/05_koreainvestment_adapter_spec.md:1)
- [06_config_schema.md](/workspace/agent_trading/plan_docs/detailed_design/06_config_schema.md:1)
- [07_mvp_scope_and_delivery_plan.md](/workspace/agent_trading/plan_docs/detailed_design/07_mvp_scope_and_delivery_plan.md:1)

### 2.3 DB 초안

- [db/README.md](/workspace/agent_trading/db/README.md:1)
- [0001_initial_schema.sql](/workspace/agent_trading/db/migrations/0001_initial_schema.sql:1)

### 2.4 코드 골격

- [domain/enums.py](/workspace/agent_trading/src/agent_trading/domain/enums.py:1)
- [domain/models.py](/workspace/agent_trading/src/agent_trading/domain/models.py:1)
- [domain/entities.py](/workspace/agent_trading/src/agent_trading/domain/entities.py:1)
- [brokers/base.py](/workspace/agent_trading/src/agent_trading/brokers/base.py:1)
- [brokers/koreainvestment/adapter.py](/workspace/agent_trading/src/agent_trading/brokers/koreainvestment/adapter.py:1)
- [repositories/contracts.py](/workspace/agent_trading/src/agent_trading/repositories/contracts.py:1)
- [repositories/memory.py](/workspace/agent_trading/src/agent_trading/repositories/memory.py:1)
- [repositories/container.py](/workspace/agent_trading/src/agent_trading/repositories/container.py:1)
- [repositories/bootstrap.py](/workspace/agent_trading/src/agent_trading/repositories/bootstrap.py:1)
- [runtime/bootstrap.py](/workspace/agent_trading/src/agent_trading/runtime/bootstrap.py:1)

## 3. 현재 구조 요약

### 3.1 패키지 구조

```text
src/agent_trading/
  domain/
    enums.py
    models.py
    entities.py
  brokers/
    base.py
    errors.py
    koreainvestment/adapter.py
  repositories/
    base.py
    filters.py
    contracts.py
    memory.py
    container.py
    bootstrap.py
  config/
    settings.py
  services/
    order_manager.py
  runtime/
    bootstrap.py
```

### 3.2 계층 역할

- `domain/enums.py`
  - 시스템 공통 enum

- `domain/models.py`
  - 브로커/실행 계층 공통 모델

- `domain/entities.py`
  - DB DDL에 대응하는 저장 엔티티

- `brokers/base.py`
  - 브로커 추상화 계약

- `repositories/contracts.py`
  - 저장소 인터페이스

- `repositories/memory.py`
  - 임시 in-memory 구현

## 4. 설계 결정 사항

### 4.1 브로커 계층

- 코어는 특정 브로커 API 형식을 직접 알지 않는다.
- 브로커 연동은 모두 `BrokerAdapter` 뒤에 숨긴다.
- 기본 브로커는 한국투자증권이다.
- `KoreaInvestmentAdapter`는 현재 스텁 수준이다.

### 4.2 저장 계층

- ORM은 아직 도입하지 않았다.
- 현재 방향은 `dataclass entity + repository protocol + explicit SQL`이다.
- 실제 DB 구현은 아직 없다.
- 메모리 구현은 애플리케이션 서비스 테스트용 임시 대체재다.

### 4.3 DB 설계

- PostgreSQL 기준이다.
- 별도 스키마 `trading` 아래에 생성되도록 설계했다.
- 상태 테이블과 이벤트 테이블을 같이 유지한다.
- replay와 raw payload는 DB blob 저장이 아니라 URI 참조 방식이다.

### 4.4 우선순위

- AI보다 주문 경로와 정합성이 먼저다.
- live보다 paper trading 경로가 먼저다.
- 재주문보다 reconcile 우선 정책을 유지한다.

## 5. 아직 구현되지 않은 것

아래는 아직 설계만 있고 구현은 없는 항목이다.

- PostgreSQL repository 구현
- DB connection / transaction 관리
- migration framework
- config loader / validator
- order manager 상태 전이 로직
- decision orchestrator
- risk/compliance agent 로직
- reconciliation worker
- KIS auth manager
- KIS REST client
- KIS WebSocket client
- observability / audit persistence 실제 구현
- 테스트 코드

## 6. Roo Code가 바로 시작할 작업 순서

### Step 1. PostgreSQL 저장 계층

다음 파일들을 새로 만드는 것을 권장한다.

- `src/agent_trading/db/connection.py`
- `src/agent_trading/db/transaction.py`
- `src/agent_trading/repositories/postgres/`
- `src/agent_trading/repositories/postgres/accounts.py`
- `src/agent_trading/repositories/postgres/orders.py`
- `src/agent_trading/repositories/postgres/decision_contexts.py`

목표:

- `repositories/contracts.py`를 만족하는 실제 PostgreSQL 구현 작성
- SQL은 현재 DDL의 `trading.*` 스키마를 기준으로 작성

### Step 2. OrderManager 실전화

현재 [order_manager.py](/workspace/agent_trading/src/agent_trading/services/order_manager.py:1)는 placeholder다.

여기서 필요한 것:

- 주문 생성
- 기초 검증
- idempotency 검사
- 상태 전이
- repository 저장
- audit log 남기기

### Step 3. KIS adapter 실제 구현 분해

현재 [adapter.py](/workspace/agent_trading/src/agent_trading/brokers/koreainvestment/adapter.py:1)는 스텁이다.

권장 분리:

- `auth_manager.py`
- `rest_client.py`
- `websocket_client.py`
- `normalizer.py`

주의:

- endpoint, TR ID, hashkey, approval key 절차는 구현 직전에 최신 공식 문서로 재확인 필요

### Step 4. 테스트 기초

최소 권장:

- repository contract test
- order status transition test
- duplicate order prevention test
- KIS adapter mock transport test

## 7. 구현 시 주의사항

### 7.1 계약을 먼저 바꾸지 말 것

아래 파일은 현재 시스템 경계 역할을 하므로, 구현 편의를 위해 먼저 흔들지 않는 것이 좋다.

- [brokers/base.py](/workspace/agent_trading/src/agent_trading/brokers/base.py:1)
- [repositories/contracts.py](/workspace/agent_trading/src/agent_trading/repositories/contracts.py:1)
- [domain/entities.py](/workspace/agent_trading/src/agent_trading/domain/entities.py:1)

필요하면 구현을 진행하면서 변경하되, 변경 이유를 명시적으로 남기는 것이 좋다.

### 7.2 DDL 기준으로 구현할 것

- 저장소 구현은 [0001_initial_schema.sql](/workspace/agent_trading/db/migrations/0001_initial_schema.sql:1)을 기준으로 맞춘다.
- 테이블명은 모두 `trading.<table>` 형태다.
- SQL에서 `search_path`에 의존하지 말고 스키마를 명시하는 편이 안전하다.

### 7.3 실전 API 값 하드코딩 금지

특히 한국투자증권 관련:

- base URL
- TR ID
- rate limit
- approval key 절차
- hashkey 필요 범위

위 항목은 코드에 박지 말고 설정 또는 어댑터 내부 상수 계층으로 관리하는 것이 좋다.

## 8. 미해결 설계 쟁점

아직 일부는 의도적으로 열어뒀다.

- PostgreSQL 드라이버 선택
  - `psycopg` async 여부
  - `asyncpg` 여부

- migration tool 선택
  - Alembic 도입 여부
  - 초기에는 plain SQL migration만 유지할지 여부

- JSONB 사용 범위
  - replay bundle manifest
  - decision structured output
  - audit metadata

- 서비스 계층 비동기 정책
  - repository를 전부 async로 유지할지
  - 초기 구현만 sync로 단순화할지

현재 코드는 `BrokerAdapter`와 repository contract가 async 기준으로 작성돼 있다. 가능하면 그 방향을 유지하는 것이 좋다.

## 9. 추가 설계 보강 필요 항목

아래 항목들은 지금 당장 아키텍처를 뒤집을 수준의 공백은 아니지만, Roo Code가 구현을 시작하기 전에 적어도 문서 또는 코드 주석 수준으로 명확히 보강하는 것이 좋다.

### 9.1 주문 상태 전이 명세 강화

현재 상태:

- 주문 상태 enum과 큰 흐름은 정의돼 있다.
- 하지만 어떤 이벤트가 어떤 상태 전이를 허용하는지는 코드 수준에서 아직 닫히지 않았다.

보강 필요 내용:

- 상태별 허용 전이표
- 전이 트리거
  - submit 성공
  - submit timeout
  - broker reject
  - partial fill
  - cancel request
  - reconcile 결과
- 금지 전이 규칙
  - 예: `FILLED -> CANCELLED` 금지
- 상태 전이 시 audit log 필수 필드

이유:

- 이 부분이 느슨하면 `OrderManager`, repository update, reconciliation이 각각 다른 규칙으로 구현될 위험이 있다.

권장 산출물:

- `plan_docs/detailed_design/order_state_machine.md`
- 또는 `services/order_manager.py` 상단에 상태 전이표 주석 추가

### 9.2 DDL과 entity 간 매핑 규칙 명문화

현재 상태:

- `domain/entities.py`와 DDL은 대체로 대응하지만, 컬럼명/nullable/JSON 구조에 대한 공식 매핑 규칙은 없다.

보강 필요 내용:

- snake_case DB 컬럼과 Python 필드의 1:1 대응 표
- enum 저장 방식
  - DB는 text/check
  - Python은 enum
- Decimal, datetime, JSONB 직렬화 규칙
- nullable 컬럼의 Python 표현 방식

이유:

- PostgreSQL repository를 구현할 때 매퍼마다 관행이 달라지면 코드 일관성이 깨진다.

권장 산출물:

- `plan_docs/detailed_design/persistence_mapping.md`
- 또는 repository 구현 패키지에 공통 row mapper 규칙 문서 추가

### 9.3 OrderManager와 Guardrail 책임 경계 명확화

현재 상태:

- 설계 문서상 `OrderManager`, `Hard Guardrail`, `Portfolio Engine` 책임은 구분돼 있다.
- 하지만 실제 구현 관점에서 어떤 검증이 어느 계층 책임인지는 아직 애매하다.

보강 필요 내용:

- `OrderManager` 책임
  - 주문 엔티티 생성
  - 상태 전이
  - 멱등성 체크 호출
  - broker submit orchestration
- `Hard Guardrail` 책임
  - 수량/금액/손실 한도 차단
  - kill switch
  - broker capability 차단
- `Portfolio Engine` 책임
  - target position 계산

이유:

- 이 경계가 흐려지면 `OrderManager`가 비대해지거나, 반대로 주문 생성 전에 필요한 검증이 여러 곳에 중복된다.

권장 원칙:

- `OrderManager`는 판단자가 아니라 “검증된 주문 의도를 실행 흐름에 태우는 서비스”로 제한한다.

### 9.4 Reconciliation 정책 세분화

현재 상태:

- “재주문보다 reconcile 우선” 원칙은 명확하다.
- 하지만 어떤 불확실 상태에서 어떤 조회 순서와 중단 정책을 적용할지는 아직 세부화되지 않았다.

보강 필요 내용:

- submit timeout 시 처리 순서
- WebSocket 단절 시 주문 상태 추적 방식
- 부분 체결 후 장시간 무응답 처리
- broker/internal position mismatch 시 신규 주문 중단 조건
- EOD 정산 시 강제 reconcile 범위

이유:

- 이 부분은 운영 안정성의 핵심이다.
- 구현자가 임의 정책을 넣기 시작하면 시스템 동작이 예측 불가능해진다.

권장 산출물:

- `plan_docs/detailed_design/reconciliation_policy.md`

### 9.5 KIS Adapter 내부 경계 구체화

현재 상태:

- `auth_manager`, `rest_client`, `websocket_client`, `normalizer` 분리는 제안돼 있다.
- 그러나 각 모듈의 입출력 계약은 아직 없다.

보강 필요 내용:

- auth manager가 반환하는 세션 객체
- rest client가 받는 공통 요청 모델
- websocket client의 event callback 또는 queue 계약
- normalizer 입력 raw payload와 출력 normalized model 정의

이유:

- 실제 API 연동 구현에 들어가면 이 경계가 먼저 고정돼야 병렬 작업이 가능하다.

권장 원칙:

- KIS 고유값은 adapter 내부에서만 소비
- 코어는 normalized model만 사용

### 9.6 감사 로그와 민감정보 처리 규칙 보강

현재 상태:

- 감사 로그 테이블과 필수 항목은 정의돼 있다.
- 하지만 어떤 필드를 항상 남기고 어떤 값은 마스킹해야 하는지는 충분히 닫히지 않았다.

보강 필요 내용:

- 주문/체결/설정 변경/운영자 개입별 필수 로그 필드
- 계좌번호, 토큰, appkey/appsecret, raw payload 마스킹 규칙
- correlation id 전파 규칙
- replay 목적 로그와 운영 감사 로그의 차이

이유:

- 이 부분을 구현 후반에 맞추면 로그 포맷이 다시 흔들린다.

권장 산출물:

- `plan_docs/detailed_design/audit_and_masking_policy.md`

### 9.7 Replay Bundle 구조 보강

현재 상태:

- replay bundle을 URI 참조 방식으로 둔 것은 맞다.
- 그러나 bundle 내부 manifest 구조와 최소 포함 항목은 미정이다.

보강 필요 내용:

- manifest JSON 구조
- 포함해야 하는 데이터
  - market data reference
  - feature snapshot reference
  - config version
  - model/prompt version
  - raw agent output
  - final structured trade decision
- 보관 주기
- 재실행 시 deterministic 조건

이유:

- replay는 나중에 덧붙이기 어렵고, 처음부터 로그와 저장 구조가 맞아야 한다.

### 9.8 테스트 우선순위 재정의

현재 상태:

- 테스트 종류는 적어뒀지만, 어떤 순서로 고정할지까지는 안 정해졌다.

보강 필요 내용:

- 1순위
  - repository contract test
  - order status transition test
  - idempotency test
- 2순위
  - reconciliation scenario test
  - audit log emission test
- 3순위
  - KIS adapter mock integration test

이유:

- 테스트 우선순위가 없으면 구현이 브로커 연동 쪽으로 먼저 새어버릴 수 있다.

권장 원칙:

- “저장 계층과 주문 상태 전이”를 먼저 고정하고 그 다음 브로커 연동으로 간다.

### 9.9 Config 활성화 및 변경 반영 정책

현재 상태:

- config schema는 있다.
- 하지만 세션 중 설정 변경이 언제 반영되는지에 대한 운영 정책은 약하다.

보강 필요 내용:

- 설정 활성화 시점
- 세션 중 hot reload 허용 범위
- live 환경 승인 절차
- config rollback 절차

이유:

- 설정 변경 정책이 약하면 운영자가 의도치 않게 live 동작을 바꿀 수 있다.

### 9.10 우선 보강해야 할 순서

Roo Code는 아래 순서로 설계 보강을 병행하는 것이 좋다.

1. 주문 상태 전이 명세
2. DDL-entity 매핑 규칙
3. OrderManager/Guardrail 책임 경계
4. Reconciliation 정책
5. 감사 로그/마스킹 규칙
6. KIS adapter 내부 계약
7. Replay bundle 구조
8. Config 활성화 정책

이 중 `1~4`는 구현 전에 최소 초안을 문서화하는 것이 좋고, `5~8`은 구현과 병행 가능하다.

## 10. 권장 종료 기준

Roo Code의 첫 번째 마일스톤은 아래 정도가 적당하다.

1. PostgreSQL repository 구현 완료
2. `OrderManager`가 repository를 사용해 주문 엔티티를 생성/저장 가능
3. in-memory가 아니라 실제 DB를 사용하는 bootstrap 추가
4. paper 환경 기준으로 account/instrument/order insert 및 query 확인

이 단계가 끝나면 그 다음부터 KIS 실연동으로 넘어가면 된다.

## 11. Codex에서 마지막으로 남기는 판단

지금은 설계적으로 더 넓히는 것보다 구현으로 내려가는 게 맞다.

특히 다음 원칙은 유지하는 것이 좋다.

- 브로커 의존성은 어댑터 뒤에 격리
- 주문 상태 전이는 명시적
- 중복 주문 방지는 저장 계층까지 포함해 보장
- live 전에 paper/replay/reconcile 먼저 확보

이 문서 기준으로 이후 작업의 주도권은 Roo Code에 넘긴다.
