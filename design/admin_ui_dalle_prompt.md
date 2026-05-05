# Admin UI DALL-E Prompt Package

## 목적

이 문서는 DALL-E로 Admin UI 콘셉트 시안을 만들기 위한 프롬프트 모음이다.

주의:

- 이 프롬프트는 시안 생성용이다
- 바로 구현 명세로 쓰지 않는다
- 생성된 시안을 선택한 뒤, 현재 시스템 정보 구조에 맞게 v0.dev 입력과 UI 스펙으로 다시 정리해야 한다

## 사용 원칙

1. 먼저 전체 콘셉트 프롬프트로 2~4장의 방향성 시안을 만든다
2. 마음에 드는 톤을 하나 선택한다
3. 이후 Orders / Reconciliation / Accounts / Decisions 화면 프롬프트로 세부 시안을 만든다
4. 결과물을 현재 `design/*.md` 문서의 정보 구조와 비교한다
5. “예쁜가”보다 “운영 도구로 쓸 수 있는가”를 기준으로 고른다

## 프롬프트 A — 전체 콘셉트

아래 영어 프롬프트를 그대로 사용:

```text
Design a desktop-first enterprise operations dashboard for an AI multi-agent trading system.

Use this visual direction:
- clean, premium admin dashboard
- muted dark neutral palette
- soft glassy panels with subtle blur
- refined rounded cards
- compact but elegant layout
- left navigation sidebar
- top status strip
- large central data table
- right-side detail panel
- restrained gradients only for atmosphere, not decoration
- high information density suitable for operators
- strong status badges and warning banners
- polished fintech / enterprise control center feel

Required sections:
- Overview
- Orders
- Reconciliation
- Accounts
- Decisions

The UI must remain read-only and operations-focused.
Do not design a marketing page.
Do not use oversized whitespace or consumer SaaS hero sections.
No playful illustrations.
No crypto-gambling aesthetic.
No bright purple-heavy gradients.

Visual emphasis:
- tables
- filters
- detail drawers or side panels
- health status
- active locks
- reconciliation warning states
- AI decision confidence indicators

Make it look premium and modern, but still practical for real operators.
```

## 프롬프트 B — Orders 화면

```text
Create a premium enterprise trading operations screen for Orders.

Visual style:
- muted dark neutral background
- elegant rounded panels
- subtle glass effect
- compact, high-density data layout
- refined but practical fintech admin UI

Layout:
- left sidebar
- top status/header row
- top filter bar with symbol search, side, status
- central orders table
- right-side order detail panel
- lower section for state transition history and broker order mapping

Show:
- order statuses as strong badges
- IDs and timestamps in a clean monospace style
- warning states clearly
- read-only inspection workflow only

No charts as the main focus.
No marketing visuals.
```

## 프롬프트 C — Reconciliation 화면

```text
Create an enterprise reconciliation monitoring screen for a trading system.

Visual style:
- premium dark admin console
- subtle glass surfaces
- compact layout
- strong operational warning visibility

Layout:
- left sidebar
- top header
- central table of reconciliation runs
- adjacent or tabbed section for blocking locks
- strong warning banner for active locks
- status filters at the top

Emphasize:
- running, resolved, reflection_failed, reconcile_required
- active lock severity
- operational clarity over decoration

This is a read-only operator console.
```

## 프롬프트 D — Accounts 화면

```text
Create an enterprise accounts monitoring screen for a trading operations console.

Visual style:
- refined dark neutral palette
- elegant but compact admin dashboard
- subtle blur / glass panels
- premium fintech back-office look

Layout:
- account filters on top
- accounts list/table
- selected account detail panel
- positions table
- cash balance section

Need clear visual handling for:
- no positions
- no cash balance snapshot
- selected account state
- related operational context

Read-only only.
```

## 프롬프트 E — Decisions 화면

```text
Create an enterprise AI decision inspection screen for a trading operations dashboard.

Visual style:
- premium dark admin UI
- subtle glassmorphism
- dense but readable layout
- elegant confidence/status indicators

Layout:
- decision filters on top
- decisions table
- selected decision detail panel
- decision context section

Show:
- ticker
- side
- decision type
- confidence
- agent label
- decision context links

Read-only internal operator tool, not consumer product UI.
```

## 선택 기준

시안을 고를 때 아래 기준으로 평가한다.

- Orders / Reconciliation / Accounts / Decisions를 모두 자연스럽게 담을 수 있는가
- list + detail 구조가 살아 있는가
- 운영 경고(active lock, failure, degraded health)가 눈에 띄는가
- 과도하게 consumer SaaS스럽지 않은가
- 데이터 밀도가 너무 낮지 않은가

