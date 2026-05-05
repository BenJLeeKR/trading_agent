# Admin UI 화면 스펙

## 목적

이 문서는 현재 범위의 운영자용 Admin UI 화면 스펙을 정의합니다.

특히 아래 작업의 기준 문서로 사용합니다.

- DALL-E 콘셉트 시안 생성
- v0.dev 템플릿 생성
- 이후 UI 구현 정교화

## 디자인 원칙

- 엔터프라이즈 운영 콘솔
- Read-only
- Desktop-first
- 높은 정보 밀도
- 명확한 경고 상태
- 장식 최소화
- 소비자 SaaS 스타일 금지

## 공통 레이아웃 규칙

- 좌측 고정 네비게이션 사이드바
- 상단 status strip 또는 page header
- 메인 영역은 list + detail 또는 table + detail 패턴 사용
- 필터 밀도는 높아도 됨
- warning banner는 눈에 띄어야 함
- empty state와 error state는 명시적으로 표시

## 공통 컴포넌트

- Summary Card
- Filter Bar
- Data Table
- Detail Panel
- Status Badge
- Warning Banner
- Empty State
- Error Banner
- Loading Spinner

## 화면 목록

### 1. Overview

목적:

- 시스템 전체 상태를 가장 빠르게 파악

핵심 정보:

- API health
- Database health
- Recent orders count
- Active locks count
- Incomplete reconciliation runs count

핵심 패널:

- Status summary cards
- Recent orders table
- Recent reconciliation / lock signal area

drill-down 대상:

- Orders
- Reconciliation

### 2. Orders

목적:

- 주문 lifecycle, broker mapping, 관련 decision lineage 확인

핵심 정보:

- Symbol
- Side
- Quantity
- Status
- Created time
- Correlation ID

핵심 패널:

- Filter bar
- Orders table
- Selected order detail
- State events table
- Broker orders table

필터:

- Symbol search
- Status
- Side

drill-down 대상:

- Decision Context
- Trade Decision
- Reconciliation

### 3. Reconciliation

목적:

- uncertain state, reconciliation run, active lock 상태 확인

핵심 정보:

- Reconciliation run status
- Trigger type
- Active locks
- Reflection failures

핵심 패널:

- Filter bar
- Runs table
- Locks table
- Active warning banner

필터:

- Run status
- Trigger type

drill-down 대상:

- Related order
- Related account

### 4. Accounts

목적:

- 계정 단위 상태, 포지션, 현금 잔고 확인

핵심 정보:

- Account code
- Client code
- Account type
- Positions
- Cash balance

핵심 패널:

- Account filter/search
- Accounts table
- Selected account detail
- Positions table
- Cash balance panel

필터:

- Account code / alias search
- Account type

drill-down 대상:

- Related orders
- Related reconciliation runs

### 5. Decisions

목적:

- AI decision 출력과 관련 context를 운영자가 읽을 수 있게 함

핵심 정보:

- Ticker / symbol
- Side
- Decision type
- Confidence
- Agent label
- Decision context ID
- Trade decision ID

핵심 패널:

- Filter bar
- Decisions table
- Selected decision detail
- Decision context detail

필터:

- Symbol / ticker
- Side
- Decision type
- Confidence range

drill-down 대상:

- Related order
- Decision context detail

## 상태 표현 규칙

### 상태 색상

- 정상: muted green
- 경고: amber / yellow
- 오류 / lock / failure: red
- 중립 / 정보: slate / gray / blue

### Read-only 규칙

- destructive button 없음
- submit / cancel / amend control 없음
- view / inspect / navigate 성격의 action만 허용

## 현재 범위 경계

이 문서는 아래 Active screen 범위만 다룹니다.

- Overview
- Orders
- Reconciliation
- Accounts
- Decisions

Broker, System, Admin 같은 미래 영역은 별도 IA 문서 범위이며, 현재 디자인 패키지에는 포함하지 않습니다.
