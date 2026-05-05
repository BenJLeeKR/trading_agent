# Plan 53 — Admin UI Visual Refinement (Roo Code Prompt)

현재 상태:
- `admin_ui/`는 이미 동작하는 Vite + React + TypeScript 기반 read-only 운영 UI다
- 인증, API 연동, 테스트, `/admin` 정적 서빙 구조가 이미 존재한다
- `/workspace/agent_trading/design/design_template/`에는 v0.dev가 생성한 Vite 기반 디자인 템플릿이 있다
- 하지만 이 템플릿은 그대로 교체 대상이 아니라, **디자인 시스템 / 레이아웃 / 스타일 패턴 추출용 소스**로 사용해야 한다

이번 작업 목표:
- `design_template/`의 시각 언어를 현재 `admin_ui/`에 **점진적으로 이식**하라
- 현재 기능, API 연동, 인증, 테스트는 유지하고
- 공통 컴포넌트와 핵심 화면의 visual language만 정제하라

왜 지금 이 작업을 하나:
- 현재 Admin UI는 기능적으로 충분히 성숙했지만, 시각적 완성도와 일관성은 아직 기본형에 가깝다
- v0.dev 템플릿은 현재 구조에 맞는 premium enterprise admin dashboard 방향을 제공한다
- 전체 프레임워크를 갈아엎지 않고, 현재 운영 도구를 더 정제된 콘솔로 끌어올릴 수 있다

반드시 먼저 읽을 파일:
1. `design/design_template_extraction.md`
2. `design/admin_ui_visual_direction.md`
3. `design/admin_ui_visual_refinement_plan.md`
4. `design/admin_ui_screen_spec.md`
5. `design/design_template/src/App.tsx`
6. `design/design_template/src/index.css`
7. `design/design_template/components/` 하위 공통 shell / panel / card / table 관련 파일
8. `admin_ui/src/components/Layout.tsx`
9. `admin_ui/src/components/common/DataTable.tsx`
10. `admin_ui/src/components/common/StatusBadge.tsx`
11. `admin_ui/src/components/common/ErrorBanner.tsx`
12. `admin_ui/src/components/Dashboard.tsx`
13. `admin_ui/src/components/OrdersView.tsx`
14. `admin_ui/src/components/OrderDetail.tsx`
15. `admin_ui/src/components/ReconciliationView.tsx`
16. `admin_ui/src/components/AccountsView.tsx`
17. `admin_ui/src/components/DecisionsView.tsx`
18. `admin_ui/src/__tests__/` 전체

핵심 원칙:
1. `admin_ui/`를 유지하라. `design_template/`를 그대로 복사해 덮어쓰지 마라.
2. backend / auth / routing / API contract는 건드리지 마라.
3. read-only 운영 UI라는 현재 경계를 유지하라.
4. 스타일 토큰과 공통 컴포넌트부터 리파인하고, 그 다음 화면에 적용하라.
5. 기존 테스트가 깨지지 않게 하고, selector 변경이 필요하면 테스트를 같이 업데이트하라.

권장 구현 범위:

### P0 — 공통 시각 시스템
- `Layout`
- summary card 스타일
- `DataTable`
- `StatusBadge`
- `ErrorBanner`
- warning banner 패턴
- detail panel 표준 구조
- filter bar 스타일

### P1 — 화면 적용
- `Dashboard`
- `OrdersView`
- `OrderDetail`
- `ReconciliationView`
- `AccountsView`
- `DecisionsView`

추출 / 이식 원칙:

### Keep
- 사이드바 위계
- top status/header 구조
- dark neutral palette 방향
- surface layering
- rounded panel style
- table density / hover / selected state 방향
- detail panel grouping

### Adapt
- `AdminShell` → 현재 `Layout`에 맞게 재구성
- overview dashboard composition → 현재 `Dashboard`에 맞게 재구성
- template table/card/panel styling → 현재 `DataTable`/detail panel에 맞게 재구성

### Ignore
- `app/` 디렉토리
- `next` / `next-themes`
- Next 전용 구조
- mock data를 실제 화면 데이터 소스로 사용하는 방식

구체 작업 순서:

1. `design_template`에서 필요한 visual tokens를 추출하라
- background
- surface
- border
- text
- success / warning / error
- radius
- shadow
- spacing

2. 현재 `admin_ui`에 스타일 토큰/공통 스타일 계층을 도입하라
- 가능하면 현재 스택을 유지하면서 CSS로 정리
- 불필요하게 프레임워크/스타일 시스템을 갈아타지 마라

3. `Layout`부터 리파인하라
- sidebar
- page header
- content shell

4. 공통 컴포넌트를 리파인하라
- `DataTable`
- `StatusBadge`
- `ErrorBanner`
- loading / warning / detail surface

5. 각 화면에 순서대로 적용하라
- `Dashboard`
- `OrdersView`
- `OrderDetail`
- `ReconciliationView`
- `AccountsView`
- `DecisionsView`

테스트/검증 요구사항:
1. `admin_ui` 테스트 전부 통과
2. `npm run build` 성공
3. `/admin#/` 수동 확인 가능
4. 로그인 후 아래 화면 수동 확인
- Overview
- Orders
- Reconciliation
- Accounts
- Decisions

이번 작업에서 하지 말 것:
- backend API 변경
- auth 정책 변경
- write action 추가
- Next.js로 마이그레이션
- chart-heavy redesign
- Admin IA 재설계

완료 후 보고 형식:
1. `design_template`에서 실제로 가져온 visual 요소 목록
2. 공통 컴포넌트에서 바뀐 점
3. 화면별 적용 범위
4. 테스트 결과
5. 아직 남은 시각 리파인 공백 2~3개

중요:
- 템플릿을 “도입”하는 것이 아니라 “추출 후 현재 앱에 이식”하는 작업이다
- 현재 `admin_ui`의 운영 로직과 테스트 기반이 더 중요하다
- visual refinement는 기능 리팩터링이 아니라, 운영 콘솔의 일관성과 가독성을 높이는 작업이어야 한다
