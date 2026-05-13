# Near-Real 운영 모니터링 UI 스펙

## 목적

이 문서는 현재 운영 환경(`KIS_ENV=paper`, 운영상 live 취급)의 **near-real 운영 모니터링 화면** 요구사항을 정의한다.

기존 [`admin_ui_screen_spec.md`](./admin_ui_screen_spec.md)가 Orders / Reconciliation / Accounts / Decisions 중심의 기본 운영 콘솔 범위를 다뤘다면, 이 문서는 아래 운영 목적에 집중한다.

- 장중 운영 상태를 한눈에 파악
- snapshot freshness / sync health / `reconcile_required` 누적 상태 추적
- AI 판단과 실제 주문 제출 경로를 운영자 시점에서 점검
- 포지션 / 현금 / 성과 / gate 상태를 한 화면에서 연결
- Pre-Market / Intraday / End-of-Day 루틴의 운영 점검 보조

## 전제

- 현재 `KIS_ENV=paper`는 운영상 live 환경으로 간주한다.
- 다만 KIS paper API의 알려진 응답 차이(`inquire-daily-ccld`, `reconcile_required`, no fills)는 별도 제약으로 인식한다.
- 이 UI는 **운영자용 내부 콘솔**이다.
- 메뉴명, 라벨, 경고 문구는 가능한 한 **한글 우선**으로 구성한다.
- Desktop-first, 고밀도 정보, read-mostly 운영 화면을 전제로 한다.

## 화면 범위

### P0

1. 운영 대시보드
2. 운영 경고 / 상태 패널
3. 실행 상태 / 주문 추적 패널

### P1

4. 포지션 / 현금 / 성과 패널
5. AI 판단 / 에이전트 실행 패널
6. 운영 루틴 체크 패널

### P2

7. CTO 시연 모드 요약 화면
8. 주간 운영 리포트 화면

## 정보 구조 제안

기존 1단계 네비게이션을 유지하되, 운영용 관점에서 아래 2차 화면 또는 탭을 추가한다.

- `개요`
  - `운영 대시보드`
  - `운영 경고`
- `주문`
  - `주문 추적`
  - `상태 전이`
- `정합성 점검`
  - `sync / freshness`
  - `reconcile_required`
- `계좌`
  - `포지션 / 현금`
  - `성과`
- `판단`
  - `AI 결정`
  - `에이전트 실행`
- `운영`
  - `일일 체크`
  - `주간 점검`

## 화면 1 — 운영 대시보드

### 목적

- 운영자가 로그인 직후 **오늘 운영 가능한 상태인지**를 10초 안에 판단

### 핵심 위젯

1. 상단 상태 바
   - `API 상태`
   - `DB 상태`
   - `Ready 상태`
   - `브로커 용량`
2. 운영 신호 카드
   - `마지막 스냅샷 동기화`
   - `미해결 정합성 상태`
   - `오늘 AI 결정 수`
   - `오늘 주문 제출 수`
3. 운영 경고 배너
   - stale snapshot
   - `reconcile_required` 급증
   - sync 실패 누적
4. 최근 실행 타임라인
   - 최근 dry-run / submit / sync / audit event
5. 오늘 운영 요약
   - `현재 포지션`
   - `현금`
   - `미실현 손익`
   - `당일 성과`

### 데이터 소스

- `GET /health`
- `GET /health/readyz`
- `GET /broker-capacity`
- `GET /reconciliation/summary`
- `GET /orders`
- `GET /trade-decisions`
- `GET /agent-runs`
- `GET /performance-summary`

### 상태 규칙

- 정상
  - snapshot fresh
  - sync 실패 없음
  - `reconcile_required` 증가 없음
- 주의
  - snapshot stale
  - `reconcile_required > 5`
  - AI 판단이 계속 `HOLD`
- 위험
  - readyz degraded/not_ready
  - sync 실패 연속
  - broker capacity unavailable

## 화면 2 — 운영 경고 / 상태 패널

### 목적

- 운영 중 수동 개입이 필요한 신호를 가장 먼저 보여준다.

### 핵심 위젯

1. `즉시 확인 필요`
   - stale snapshot
   - active blocking lock
   - sync failure
   - token / auth 문제
2. `주의 상태`
   - `reconcile_required` 누적
   - `pending_submit` 재발생
   - submit 없음 장기 지속
3. `운영 메모`
   - 오늘 수동 조치 내역
   - 내일 pre-market 확인 사항

### 데이터 소스

- `GET /reconciliation/locks`
- `GET /reconciliation/summary`
- `GET /orders`
- `GET /health/readyz`
- `GET /broker-capacity`

### 추가 API 필요 여부

- P0는 기존 API로 가능
- 운영 메모 persistence가 필요하면 별도 API 또는 수기 문서 연결 필요

## 화면 3 — 실행 상태 / 주문 추적 패널

### 목적

- AI 판단이 실제 주문 제출 경로로 이어졌는지 추적

### 핵심 위젯

1. 최근 주문 테이블
   - `주문 ID`
   - `종목`
   - `매수/매도`
   - `수량`
   - `상태`
   - `생성 시각`
2. 주문 상세 패널
   - `order_state_events`
   - `broker_orders`
   - `ODNO`
   - `last_synced_at`
3. 제출 경로 요약
   - `Decision Context`
   - `Trade Decision`
   - `Agent Runs`

### 데이터 소스

- `GET /orders`
- `GET /orders/{id}`
- `GET /orders/{id}/events`
- `GET /orders/{id}/broker-orders`
- `GET /trade-decisions`
- `GET /decision-contexts/{id}`
- `GET /agent-runs`

### 운영 규칙

- `HOLD`는 실패가 아니라 non-actionable 상태
- `reconcile_required`는 현재 환경에서 허용 상태이지만 증가 추세는 경고

## 화면 4 — 포지션 / 현금 / 성과 패널

### 목적

- 운영 결과를 계좌 단위로 빠르게 파악

### 핵심 위젯

1. 계좌 요약 카드
   - `총 평가금액`
   - `현금`
   - `보유 종목 수`
   - `미실현 손익`
2. 포지션 테이블
   - `종목`
   - `수량`
   - `평균단가`
   - `현재가`
   - `미실현 손익`
3. 성과 카드
   - `누적 수익률`
   - `최대 낙폭`
   - `승률`
   - `체결 건수`
4. 성과 추이
   - 일별 equity history
   - benchmark 비교는 P1

### 데이터 소스

- `GET /accounts`
- `GET /positions`
- `GET /cash-balances`
- `GET /performance-summary`
- `GET /performance-history`
- `GET /performance-metrics`
- `GET /performance-benchmark`
- `GET /performance-benchmark-history`

## 화면 5 — AI 판단 / 에이전트 실행 패널

### 목적

- `APPROVE / HOLD / REJECT` 분포와 최근 AI 실행 품질을 운영자가 읽을 수 있게 한다.

### 핵심 위젯

1. 판단 분포 카드
   - `APPROVE`
   - `HOLD`
   - `REJECT`
2. 최근 판단 테이블
   - `종목`
   - `decision_type`
   - `confidence`
   - `created_at`
3. 선택 판단 상세
   - 요약 근거
   - agent linkage
4. 에이전트 실행 타임라인
   - `EI`
   - `Risk`
   - `FDC`
   - 실행 시간 / 성공 여부

### 데이터 소스

- `GET /trade-decisions`
- `GET /decision-contexts/{id}`
- `GET /agent-runs`

## 화면 6 — 운영 루틴 체크 패널

### 목적

- 운영 체크리스트를 화면에서 보조한다.

### 핵심 위젯

1. Pre-Market 체크
   - `KIS_ENV`
   - token cache
   - snapshot freshness
   - `KIS_SMOKE_PRICE`
2. Intraday 체크
   - dry-run 결과
   - submit 여부
   - sync freshness
   - `reconcile_required`
3. End-of-Day 체크
   - 최종 sync
   - stale `pending_submit`
   - 일일 성과 기록
4. 주간 체크
   - gate 상태
   - 성과 지표
   - 운영 이슈 누적

### 데이터 소스

- 기존 API + 운영 문서 기반 계산

### 추가 API 필요 여부

- 체크 상태를 서버가 계산해 주지 않아도 v1은 프런트 계산 가능
- 장기적으로는 `/paper-go-no-go`와 운영 상태 집계를 조합하는 보조 API가 있으면 좋음

## 메뉴명 / 텍스트 원칙

- 메뉴명은 한글 우선
  - `개요`
  - `주문`
  - `정합성 점검`
  - `계좌`
  - `판단`
  - `에이전트 실행`
  - `운영`
- 상태 라벨도 한글 우선
  - `정상`
  - `주의`
  - `위험`
  - `제출 대기`
  - `정합성 필요`
  - `실행 가능`
  - `실행 보류`
- 차트 제목, 카드 제목, 빈 상태 문구도 한글 우선

## API 매핑 요약

### 기존 API로 바로 가능한 항목

- health / readyz
- broker capacity
- orders / order events / broker orders
- reconciliation summary / runs / locks
- accounts / positions / cash balances
- trade decisions / decision contexts / agent runs
- audit logs
- performance summary / history / metrics / benchmark
- paper go/no-go

### 추가 연결이 필요한 항목

- 운영 메모 저장
- 체크리스트 체크 상태 persistence
- 당일 운영 이슈 수기 입력

## P0 / P1 / P2 우선순위

### P0

- 운영 대시보드
- 운영 경고 패널
- 주문 추적 패널

### P1

- 포지션 / 성과 패널
- AI 판단 / 에이전트 실행 패널
- 운영 루틴 체크 패널

### P2

- 주간 리뷰 요약
- CTO 시연 모드
- 운영 메모 / 이슈 히스토리

## 구현 원칙

- 기존 Admin UI 정보 구조를 깨지 않는다.
- 새 화면이 필요하면 기존 메뉴 하위 탭 또는 보조 페이지로 넣는다.
- **예쁜 대시보드보다 운영 판단 속도**를 우선한다.
- 지나치게 chart-heavy한 분석 화면은 피한다.
- `reconcile_required`, snapshot freshness, sync health, 최근 판단/주문 상태를 최상단에 둔다.

