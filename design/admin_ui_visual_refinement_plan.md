# Plan 53 — Admin UI Visual Refinement

## 목적

현재 Admin UI의 기능 구조와 정보 구조는 유지한 채,
선택한 visual reference 방향에 맞춰
UI의 밀도, 위계, 패널 구조, 색상, 상태 표현을 정제한다.

이번 작업은 기능 추가가 아니라 **시각적 리파인**이다.

## 목표

- 기존 Admin UI를 더 프리미엄한 엔터프라이즈 운영 콘솔 스타일로 개선
- Orders / Reconciliation / Accounts / Decisions / Overview 화면의 시각적 일관성 강화
- 공통 컴포넌트 기준으로 리파인
- 정보 밀도는 유지하되, 가독성과 상태 인지가 좋아지게 개선

## 변경 원칙

- backend 변경 없음
- API 변경 없음
- Auth/RBAC 변경 없음
- 라우팅 구조 유지
- read-only 원칙 유지
- 기존 테스트 가능한 한 유지, 필요 시 UI 테스트 selector 업데이트

## 우선 리파인 대상

### P0

- Layout
- Summary cards
- DataTable
- StatusBadge
- ErrorBanner
- Warning banner
- Detail panel
- Filter bar

### P1

- Dashboard
- OrdersView
- OrderDetail
- ReconciliationView
- AccountsView
- DecisionsView

## 시각적 방향

- muted dark neutral palette
- elegant rounded surfaces
- subtle glass-like panels
- compact spacing
- premium but practical admin console
- strong warning emphasis
- selected row clarity
- reduced visual clutter

## 세부 작업

### 1. 디자인 토큰 정리

- background
- surface
- panel
- border
- text primary/secondary
- success/warning/error/info
- radius
- shadow
- spacing

### 2. Layout 개선

- sidebar hierarchy 정리
- top header/status strip 정리
- content width / panel spacing 정리

### 3. DataTable 개선

- row hover
- selected row state
- header hierarchy
- compact cell spacing
- numeric alignment

### 4. Status/Warning 개선

- lock / failure / degraded health 강조
- badge 색 정제
- warning banner 일관성 통일

### 5. Detail Panel 개선

- section grouping
- meta field hierarchy
- ID / timestamp / summary 배치 정리

### 6. Screen-level polish

- Dashboard cards 정리
- Orders list/detail balance
- Reconciliation warning visibility
- Accounts detail readability
- Decisions confidence presentation

## 테스트/검증

- 기존 UI 테스트 회귀 없음 확인
- 시각적 변경으로 selector가 깨지면 테스트 업데이트
- build 성공
- 수동 확인:
  - `/admin`
  - login
  - overview
  - orders
  - reconciliation
  - accounts
  - decisions

## 완료 기준

- 주요 5개 화면의 visual language 일관화
- 공통 컴포넌트 리파인 완료
- 운영 상태 강조 표현 개선
- 기존 기능/구조 회귀 없음

## 비범위

- 기능 추가
- 새 API
- write action
- 브랜딩 전면 교체
- chart-heavy redesign
- Admin IA 변경
