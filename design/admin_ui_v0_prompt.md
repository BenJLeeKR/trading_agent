# v0.dev 입력 패키지

## 사용 안내

이 문서는 v0.dev에 넣을 입력 자료 패키지입니다.

아래 영어 프롬프트는 v0.dev에 직접 전달하기 좋도록 유지하고, 설명 문장은 한글로 정리합니다.

## v0.dev 기본 프롬프트

아래 영어 프롬프트를 그대로 사용:

Create a desktop-first read-only admin console for an AI multi-agent trading system.

This is not a marketing page.
It is an internal operations dashboard for monitoring:

- orders
- reconciliation runs and locks
- accounts, positions, cash balances
- AI trade decisions and decision contexts

Design principles:

- enterprise operations console
- dense but readable tables
- strong status visibility
- left navigation sidebar
- top status summary row
- list + detail panel workflow
- read-only only
- no write actions
- no consumer SaaS feel
- no giant hero sections
- no playful visuals

Use a professional, restrained design system with:

- muted dark or muted light enterprise palette
- compact spacing
- clear warning/error states
- high information density
- strong visual hierarchy

## 필수 화면

1. Overview dashboard
2. Orders screen
3. Reconciliation screen
4. Accounts screen
5. Decisions screen

## 화면 요구사항

### Overview

- health status
- database status
- active locks count
- incomplete reconciliation count
- recent orders
- links into Orders and Reconciliation

### Orders

- filter bar: symbol, side, status
- orders table
- selected order detail
- state events section
- broker orders section

### Reconciliation

- runs table
- locks table
- active lock warning banner
- status filter

### Accounts

- account filter/search
- accounts table
- selected account detail
- positions table
- cash balance section

### Decisions

- decision filters
- decisions table
- selected decision detail
- decision context detail

## 상호작용 규칙

- read-only only
- 모든 액션은 조회 / 점검 / 이동 성격만 허용
- table은 selected-row 패턴을 지원해야 함
- detail panel은 시각적으로 명확히 구분돼야 함
- warning banner는 눈에 띄어야 함

## 피해야 할 것

- marketing landing page styling
- oversized whitespace
- decorative charts
- purple-heavy gradient aesthetic
- consumer product visuals

## 도메인 데이터 참고

### Order Status

- draft
- validated
- pending_submit
- submitted
- acknowledged
- partially_filled
- filled
- cancelled
- rejected
- expired
- reconcile_required

### Reconciliation Status

- running
- resolved
- reflection_failed

### Lock State

- active
- expired

### Warning Signals

- active locks
- reflection failed
- degraded health
- missing cash snapshot
- no positions
- unknown order state / reconcile required

## 예시 데이터 필드

### Orders

- order_request_id
- symbol
- side
- quantity
- status
- created_at
- correlation_id

### Reconciliation

- reconciliation_run_id
- account_id
- trigger_type
- status
- started_at
- summary_json

### Locks

- lock_id
- account_id
- symbol
- side
- reason
- locked_at
- expires_at
- is_active

### Accounts

- account_id
- account_code
- client_code
- account_type

### Positions

- symbol
- quantity
- average_price
- market_price
- unrealized_pnl
- source_of_truth

### Decisions

- trade_decision_id
- decision_context_id
- ticker
- side
- decision_type
- confidence
- agent_label
- created_at

## 전달 메모

- 장식적인 대시보드보다 데이터 중심 레이아웃을 우선
- table과 detail panel을 적극 활용
- 일반 사용자 UI가 아니라 운영자 도구라는 점 유지
- write action button 추가 금지
- 초기 템플릿에 chart-heavy analytics 추가 금지
