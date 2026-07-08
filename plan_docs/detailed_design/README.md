# 상세 설계 문서 세트 v1

이 디렉터리는 `ENTERPRISE_TRADING_SYSTEM_DESIGN.md`를 구현 가능한 수준으로 분해한 상세 설계 초안 모음이다.

## 문서 목록

1. `01_system_architecture.md`
   - 시스템 경계
   - 컴포넌트 책임
   - 런타임 상호작용
   - 배포 단위

2. `02_order_execution_sequence.md`
   - 주문 생성부터 체결 정산까지의 시퀀스
   - 멱등성
   - 실패/재시도/정합성 복구

3. `03_data_model_erd.md`
   - 핵심 엔티티
   - 관계
   - 감사 및 재현성 저장 규칙

4. `04_broker_adapter_interface.md`
   - 공통 브로커 추상화
   - capability 모델
   - 공통 오류 계약

5. `05_koreainvestment_adapter_spec.md`
   - 한국투자증권 어댑터 책임
   - 인증/토큰/실시간 접속키 생명주기
   - 주문 및 시세 처리 규칙

6. `06_config_schema.md`
   - 클라이언트별 설정 구조
   - 환경 분리
   - 버전 관리 원칙

7. `07_mvp_scope_and_delivery_plan.md`
   - v1 범위
   - 단계별 구현 순서
   - 완료 기준

8. `08_ai_decision_policy.md`
   - 기대수익률 지향 AI 판단 구조
   - 시장 비효율 가설
   - regime/strategy/signal 통합 방식
   - sizing/exit/feedback 구조

9. `09_market_and_event_data_policy.md`
   - 공시/뉴스/리포트/거시 데이터 소스 정책
   - source reliability, polling, dedup, freshness
   - event classification과 RAG 저장 정책

10. `10_broker_rate_limit_and_capacity_policy.md`
   - 브로커 호출 제한의 주문 안전성 정책
   - order/inquiry/reconciliation 예산 분리
   - websocket capacity, cache TTL, throttling/backoff/circuit

11. `11_kis_realtime_quote_operations_screen.md`
   - Admin UI "기본 운영" 실시간 현재가 조회 화면 설계
   - 전용 계좌/appkey 분리, approval key/세션/구독 한도 정책
   - API contract, UI 구성, polling → relay 단계 전환 계획

## 설계 원칙

- 실전/모의 환경은 논리적으로만이 아니라 설정, 자격증명, 계좌, 라우팅 수준에서 분리한다.
- AI 의사결정은 주문 판단 주체지만 계좌 보호는 deterministic hard guardrail이 수행한다.
- 브로커 의존성은 `BrokerAdapter` 뒤에 격리한다.
- 같은 입력으로 같은 결과를 재현할 수 있도록 모든 의사결정 입력과 출력을 저장한다.
- 라이브 주문보다 먼저 백테스트와 페이퍼트레이딩 경로를 확정한다.
