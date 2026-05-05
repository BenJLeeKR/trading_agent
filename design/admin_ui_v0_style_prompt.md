# Admin UI v0.dev Style Prompt

## 목적

이 문서는 v0.dev에 전달할 스타일/구조 지시 프롬프트다.

역할:

- 현재 Admin UI의 정보 구조를 유지한 채
- visual direction을 더 정제된 운영 콘솔 스타일로 끌어올릴 수 있도록
- v0.dev가 UI template을 생성할 수 있게 한다

## 사용 순서

1. 먼저 `admin_ui_information_architecture.md`와 `admin_ui_screen_spec.md`를 읽고 현재 구조를 이해한다
2. `admin_ui_dalle_prompt.md`로 콘셉트 시안을 만든 뒤, 원하는 시각 방향을 선택한다
3. 아래 프롬프트를 v0.dev에 입력한다
4. 필요하면 선택한 DALL-E 시안을 함께 참고 이미지로 준다

## v0.dev 기본 프롬프트

아래 영어 프롬프트를 그대로 사용:

```text
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

Visual style:
- premium dark admin dashboard
- elegant rounded panels
- subtle glass-like surfaces
- restrained shadows
- compact spacing
- table-first layout
- detail side panels
- status-driven design

Avoid:
- consumer SaaS aesthetic
- giant hero headers
- oversized cards
- excessive whitespace
- loud gradients
- playful visuals
- purple-heavy branding
- chart-first dashboard design

Required screens:
- Overview
- Orders
- Reconciliation
- Accounts
- Decisions

Important constraints:
- read-only only
- no submit/cancel/amend UI
- all interactions are inspect / navigate / filter / select
- selected rows should visually connect to detail panels
- warning banners should be highly visible
```

## 보조 입력 자료

v0.dev에 아래 정보를 함께 주면 결과 품질이 좋아진다.

### 필수 화면 요구사항

#### Overview

- health status
- database status
- active locks count
- incomplete reconciliation count
- recent orders
- links into Orders and Reconciliation

#### Orders

- filter bar: symbol, side, status
- orders table
- selected order detail
- state events section
- broker orders section

#### Reconciliation

- runs table
- locks table
- active lock warning banner
- status filter

#### Accounts

- account filter/search
- accounts table
- selected account detail
- positions table
- cash balance section

#### Decisions

- decision filters
- decisions table
- selected decision detail
- decision context detail

### 데이터 우선순위

강조해야 할 데이터:

- order status
- reconciliation state
- active locks
- cash balance state
- position snapshots
- AI decision confidence
- decision context cross-reference

### 상태 종류

#### Order Status

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

#### Reconciliation Status

- running
- resolved
- reflection_failed

#### Lock State

- active
- expired

#### Warning Signals

- active locks
- reflection failed
- degraded health
- missing cash snapshot
- no positions
- unknown order state / reconcile required

## 전달 시 주의

- “현재 Admin UI의 정보 구조를 유지한 상태에서 스타일/템플릿만 리파인한다”는 점을 분명히 전달한다
- 새 기능을 추가하라고 요청하지 않는다
- write action을 넣지 말라고 분명히 적는다
- 차트 중심 대시보드보다 table + detail 중심 운영 화면을 요구한다

