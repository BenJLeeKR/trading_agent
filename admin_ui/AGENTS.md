# admin_ui/AGENTS.md

## 적용 범위

이 지침은 `admin_ui/` 이하 프론트엔드 코드에 적용한다. 루트 `AGENTS.md`를 우선 따르고, 이 문서는 운영 대시보드 UI 변경 규칙을 보강한다.

## 프론트엔드 원칙

- Admin UI는 운영자가 백엔드 상태를 오해하지 않게 만드는 read/inspect 중심 화면이다.
- 상태, freshness, auth, API 오류, 빈 데이터는 명확하게 표시한다.
- 실제 동작하지 않은 작업을 성공처럼 보이게 하지 않는다.
- 백엔드 enum, API schema, RBAC 정책과 UI 표시 문구를 맞춘다.
- 코드를 제외한 화면 문구, 주석, 설명, 보고는 한국어를 사용한다.

## 주요 경로

- `src/`: React/TypeScript 애플리케이션 코드.
- `src/components/`: 공통 UI 컴포넌트.
- `src/views/`: Dashboard, Orders, Reconciliation, Accounts, Decisions 등 주요 화면.
- `src/lib/` 또는 API client 경로: Inspection API 호출 계층과 공통 유틸리티.
- `*.test.*`: Vitest와 React Testing Library 기반 테스트.

## 검증

- 가능한 경우 프론트엔드 검증은 `bash scripts/harness/run.sh <command>` 또는 대응하는 `make` target으로 실행한다.
- Admin UI의 정답 판정은 `bash scripts/harness/run.sh accept frontend` 또는 `make accept-admin-ui`를 사용한다.
- 변경 전 `package.json`의 scripts를 확인한다.
- 가능한 가장 좁은 테스트를 먼저 실행한다.
- UI 동작 변경 시 관련 컴포넌트나 view 테스트를 우선 실행한다.
- API contract 변경과 함께 작업했다면 백엔드 schema와 프론트 타입·표시 로직을 함께 확인한다.

## 검증 부하 제한

- 이 Ubuntu 서버에서는 프론트엔드 전체 테스트와 전체 빌드 실행을 기본 금지한다.
- 사용자 명시 승인 없이 `npm test`, `npm run test`, `npm run test:run`, `npm run build`를 실행하지 않는다.
- watch mode, 장시간 실행 테스트, 대량 DOM 렌더링 테스트, 백엔드 API를 실제 호출하는 검증은 사용자 명시 승인 없이 실행하지 않는다.
- 전체 테스트나 전체 빌드가 필요하다고 판단되면 직접 실행하지 말고 예상 부하, 필요한 이유, 대체 검증안을 먼저 보고한다.

## UI 표시 규칙

- loading, empty, error, stale 상태를 구분한다.
- timestamp와 freshness 정보는 운영자가 판단할 수 있게 노출한다.
- 주문, 정합성, agent run, decision 상태는 원본 상태값과 한국어 설명이 어긋나지 않게 한다.
- 위험하거나 불확실한 상태는 정상 상태처럼 색상이나 문구를 표시하지 않는다.

## 금지 사항

- API 오류를 빈 목록으로만 숨기지 않는다.
- 인증 실패와 권한 부족을 같은 메시지로 뭉개지 않는다.
- 운영 지표를 계산 없이 임의로 표시하지 않는다.
- 백엔드 contract 변경 없이 프론트에서만 상태 의미를 재정의하지 않는다.
