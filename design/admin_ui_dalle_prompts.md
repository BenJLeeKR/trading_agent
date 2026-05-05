# Admin UI DALL-E 프롬프트

## 사용 방법

이 문서는 구현 스펙이 아니라 **콘셉트 시안 생성용**입니다.

다음 요소를 탐색하는 데 사용합니다.

- 레이아웃 방향
- 정보 밀도
- 화면 분위기
- 네비게이션 구조
- detail panel 패턴

주의:

- 아래 프롬프트는 시안 생성용입니다.
- 구현 명세로 바로 사용하지 말고, 시안 선택 후 별도 UI 스펙으로 정리해야 합니다.

## 공통 디자인 제약

- 엔터프라이즈 운영 대시보드
- 읽기 전용 내부 운영 콘솔
- 데스크톱 우선
- 읽기 쉬운 고밀도 정보 배치
- 장식 최소화
- 마케팅 랜딩 페이지 스타일 금지
- consumer SaaS 느낌 금지
- 과도한 공백 카드 레이아웃 금지

## 프롬프트 A — 전체 콘셉트

아래 영어 프롬프트를 그대로 사용:

Design an enterprise operations dashboard for an AI multi-agent trading system.
Read-only admin console.
Desktop-first layout with a left navigation sidebar, top health/status strip, dense data tables, and a right-side detail panel.
Professional, minimal, information-dense, suitable for operations staff.
Show sections for Orders, Reconciliation, Accounts, and Decisions.
Use a calm dark neutral palette or muted light enterprise palette.
Avoid marketing website aesthetics.
No hero section, no oversized cards, no consumer SaaS look.
High signal, low decoration, finance/operations console feel.

## 프롬프트 B — Orders 화면

아래 영어 프롬프트를 그대로 사용:

Enterprise trading operations screen for Orders.
Large orders table in the center with filters on top: symbol search, side, status.
Selected order detail panel on the right.
Below detail panel include state transition history and broker order mapping.
Show status badges, timestamps, IDs, and warning states clearly.
Professional admin console style, dense but readable, desktop-first.

## 프롬프트 C — Reconciliation 화면

아래 영어 프롬프트를 그대로 사용:

Enterprise reconciliation monitoring screen for a trading platform.
Main table of reconciliation runs, tab or section for blocking locks, strong warning banner for active locks.
Need statuses like running, resolved, reflection_failed, reconcile_required.
Operations-focused, high information density, minimal styling, no marketing feel.

## 프롬프트 D — Accounts 화면

아래 영어 프롬프트를 그대로 사용:

Enterprise account monitoring screen for a trading system.
Accounts list on the left or center, selected account detail on the right, positions table and cash balance section below.
Need clear empty states for no positions and no cash snapshot.
Professional, muted enterprise visual style, compact tables and summary info.

## 프롬프트 E — Decisions 화면

아래 영어 프롬프트를 그대로 사용:

Enterprise AI decision inspection screen for a trading system.
Decision list with filters, confidence indicators, side, decision type, and a detail panel showing decision context.
Need cross-reference feel with order and context IDs.
Operations UI, not consumer UI, information-dense, minimal decoration.
