# Admin UI 정보 구조

## 개요

이 문서는 AI 멀티 에이전트 트레이딩 시스템의 Admin UI에 대한 장기 정보 구조(IA)를 정의합니다.

목표는 현재 화면과 앞으로 추가될 운영자 화면을 모두 포괄하면서도, 시스템이 커질 때 자연스럽게 확장 가능한 구조를 만드는 것입니다.

## 제품 요약

Admin UI는 아래 정보를 다루는 읽기 전용 운영 콘솔입니다.

- 주문(Orders)
- Reconciliation run 및 blocking lock
- 계정, 포지션, 현금 잔고
- AI trade decision 및 decision context
- 브로커 / 시스템 진단 정보

이 UI는 일반 사용자용이 아니라 내부 운영자용 도구입니다.

## 1단계 네비게이션

- Overview
- Orders
- Reconciliation
- Accounts
- Decisions
- Broker
- System
- Admin

## 현재 활성 화면

현재 구현되었거나 가까운 시일 내 집중 대상으로 보는 화면은 아래와 같습니다.

- Overview
- Orders
- Reconciliation
- Accounts
- Decisions

## 예약 화면

아직 구현하지 않았지만 향후 확장을 위해 영역만 확보해 두는 화면은 아래와 같습니다.

- Broker
- System
- Admin

## 공통 섹션 패턴

가능한 한 각 섹션은 아래 구조를 따릅니다.

- Summary
- List
- Detail
- Related Links / Drill-down
- Empty State
- Error State
- Warning State

## 섹션 정의

### Overview

목적:

- 시스템 전반의 상태와 위험 신호를 가장 빠르게 파악

대표 내용:

- API health
- Database health
- Active lock count
- Incomplete reconciliation count
- Recent orders
- Orders / Reconciliation으로의 이동 링크

### Orders

목적:

- 주문, 주문 상태 전이, 브로커 매핑 정보 확인

대표 내용:

- Orders list
- Order detail
- Order state events
- Broker order mapping

### Reconciliation

목적:

- 불명확 상태, reconciliation run, active lock 상태 확인

대표 내용:

- Reconciliation runs
- Blocking locks
- Reflection failure signals
- Unknown-state cases

### Accounts

목적:

- 계정 단위 상태, 포지션, 현금 잔고 스냅샷 확인

대표 내용:

- Accounts list
- Account detail
- Positions
- Cash balances
- Risk snapshots

### Decisions

목적:

- AI가 생성한 trade decision과 연결된 decision context 확인

대표 내용:

- Trade decisions list
- Decision detail
- Decision context detail
- Agent run trace links

### Broker

목적:

- 브로커 연결 상태 및 진단 정보 확인

대표 내용:

- Connectivity status
- Broker status
- Rate limit / capacity
- Submit / inquiry diagnostics

### System

목적:

- 플랫폼 수준 운영 상태 확인

대표 내용:

- API health
- Database health
- Background workers
- Event loop / gap fill status
- Audit / replay status

### Admin

목적:

- 운영/관리성 메타데이터 화면 수용

대표 내용:

- Auth / sessions
- Config versions
- Strategies
- Clients / users / roles
- Feature flags

## IA 관리 원칙

- 새 화면은 독립 페이지처럼 추가하지 말고, 1단계 도메인 영역 아래에 배치합니다.
- 각 화면은 최소 아래 항목을 문서화합니다.
  - Route
  - Purpose
  - Core panels
  - Related drill-down paths
- Active screen은 전체 IA의 제한된 부분집합으로 유지합니다.
- Reserved screen은 구현 전이라도 먼저 구조를 잡아둘 수 있습니다.
