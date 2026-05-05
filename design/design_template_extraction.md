# Design Template Extraction Guide

## 목적

이 문서는 `/workspace/agent_trading/design/design_template/`에 있는 v0.dev 산출물을
현재 `admin_ui/`에 **그대로 교체하지 않고**, 필요한 디자인 시스템과 레이아웃 패턴만
점진적으로 이식하기 위한 추출 가이드입니다.

핵심 원칙:

- 현재 동작하는 `admin_ui/`는 유지
- API 연동 / Auth / 테스트 / `/admin` static serving 구조는 유지
- `design_template/`는 **디자인 시스템과 레이아웃 레퍼런스**로 사용
- Vite 기반 현재 앱에 필요한 부분만 흡수

## 현재 상태 요약

### 현재 운영 UI

- 경로: `admin_ui/`
- 스택: Vite + React + TypeScript
- 특징:
  - FastAPI `/admin` 정적 서빙
  - sessionStorage 기반 token auth
  - inspection API 연동 완료
  - Vitest/RTL 테스트 존재

### v0.dev 템플릿

- 경로: `design/design_template/`
- 형태:
  - Vite + React 구조 포함
  - `src/App.tsx`, `src/main.tsx`, `vite.config.ts` 존재
  - `react-router-dom` 기반 라우팅 포함
- 잔재:
  - `app/` 디렉토리 존재
  - `next` / `next-themes` 의존성 존재
  - `use client` 문구 존재

결론:

- 템플릿은 **시각 방향 참고용 + 부분 이식용**
- 그대로 merge하는 대상은 아님

## 추출 대상 분류

### 1. Keep — 거의 그대로 가져올 가치가 있는 것

아래는 현재 `admin_ui/`에 직접 이식할 가능성이 높은 대상입니다.

- 레이아웃 구조
  - 사이드바 폭/위계
  - 상단 상태 영역 구조
  - 메인 패널 배치
- 색상/표면 스타일
  - dark neutral palette
  - panel surface layering
  - border/shadow/radius 방향
- 카드 스타일
  - summary card 구조
  - 상태 카드 hierarchy
- 테이블 스타일
  - header hierarchy
  - row hover / selected row 표현
  - dense enterprise table spacing
- detail panel 구조
  - section grouping
  - meta 정보 위계
- 아이콘 방향
  - lucide 계열 outline icon 사용 방식

### 2. Adapt — 개념은 가져오되 현재 구조에 맞게 재작성할 것

아래는 그대로 복사하지 말고 현재 `admin_ui/`에 맞게 재작성해야 합니다.

- `AdminShell`
  - 현재 `Layout`과 역할 비교 후 구조만 반영
- `OverviewDashboard`
  - 현재 `Dashboard` 정보 구조 유지하면서 스타일만 반영
- `OrdersView`
  - 현재 filter/search/detail 흐름 유지
- `ReconciliationView`
  - 현재 runs/locks/active warning 흐름 유지
- `AccountsView`
  - 현재 positions/cash detail 구조 유지
- `DecisionsView`
  - 현재 decision detail/context lazy load 흐름 유지
- `src/index.css`
  - 토큰/스타일 규칙은 참고하되 현재 앱에 맞게 정리

### 3. Ignore — 현재 범위에서 가져오지 않을 것

아래는 현재 `admin_ui/`에 직접 가져오지 않습니다.

- `app/` 디렉토리 전체
  - Next App Router 잔재
- `next` 관련 의존성
- `next-themes`
- Vercel/Next 전용 설정
- mock data 전체를 데이터 소스로 사용하는 구조
- 실제 운영 흐름과 무관한 placeholder 화면

## 파일별 추천 처리

| 템플릿 파일 | 권장 처리 |
|---|---|
| `src/App.tsx` | 라우팅 구조 참고만, 직접 복사 금지 |
| `src/main.tsx` | 진입 구조 참고만 |
| `src/index.css` | 색상/spacing/radius/shadow 토큰 추출 |
| `components/admin/*` | 공통 레이아웃/카드/패널 구조 참고 후 재구성 |
| `components/theme-provider.tsx` | 현재 범위에서는 무시 |
| `lib/utils.ts` | 유틸이 단순하면 선택적 흡수 |
| `lib/mock-data.ts` | 운영 코드에는 사용 금지, fixture 참고만 |
| `app/layout.tsx`, `app/page.tsx` | 무시 |
| `components.json` | 스타일 시스템 참고만 |

## 현재 `admin_ui`와의 매핑

| 현재 `admin_ui` | 템플릿에서 참고할 것 |
|---|---|
| `Layout` | `AdminShell`의 sidebar/header/panel 구조 |
| `Dashboard` | overview panel composition |
| `OrdersView` | table + detail layout tone |
| `OrderDetail` | detail panel grouping |
| `ReconciliationView` | warning block / tab styling |
| `AccountsView` | account detail card hierarchy |
| `DecisionsView` | decision list/detail visual hierarchy |
| `DataTable` | row/column styling, hover/selected states |
| `StatusBadge` | 색/shape/weight refinement |

## 권장 이식 순서

### Phase A — 공통 시각 시스템

1. 색상 토큰
2. spacing / radius / shadow
3. Layout shell
4. Summary card
5. DataTable
6. StatusBadge
7. Warning / Error banner
8. Detail panel

### Phase B — 화면 적용

1. Dashboard
2. Orders / OrderDetail
3. Reconciliation
4. Accounts
5. Decisions

## 체크리스트

이식 전에 확인:

- 현재 `admin_ui`의 기능 구조를 유지하는가
- route/auth/API 연동을 깨지 않는가
- 테스트가 계속 가능한가
- `/admin` 정적 서빙 구조를 바꾸지 않는가

이식 후 확인:

- `npm run test:run`
- `npm run build`
- `/admin#/` 수동 확인
- Orders / Reconciliation / Accounts / Decisions 화면 가독성 확인

## 최종 원칙

- 템플릿을 “채택”하는 것이 아니라 “추출”한다
- 스타일 시스템은 가져오되, 앱 구조는 현재 `admin_ui`를 기준으로 유지한다
- 기능보다 시각 리파인을 우선한다
