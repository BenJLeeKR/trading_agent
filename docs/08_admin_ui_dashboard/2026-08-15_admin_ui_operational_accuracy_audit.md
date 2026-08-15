# Admin UI 운영 정확성 1차 점검

작성일: 2026-08-15  
범위: `admin_ui/src/components/`, `admin_ui/src/api/client.ts`, `admin_ui/src/hooks/useEnumMetadata.ts`, `src/agent_trading/api/schemas.py`, `src/agent_trading/api/enum_metadata.py` read-only 확인

## 목적

이번 점검은 Admin UI를 크게 개편하기 전, 운영자가 백엔드 상태를 오해할 가능성이 높은 지점을 구조적으로 분류하고 다음 구현 단위를 작게 좁히기 위한 것이다. 화면을 보기 좋게 바꾸는 작업이 아니라, `loading`, `empty`, `error`, `stale`, `partial failure`, `auth`, API 실패를 서로 구분해 read/inspect 화면의 신뢰도를 높이는 작업을 우선한다.

## 현재 구조

- 라우팅은 `admin_ui/src/App.tsx`에서 `OperationsDashboardView`, `OrdersView`, `ReconciliationView`, `AccountsView`, `DecisionsView`, `AgentRunsView` 등 컴포넌트 직접 연결 방식이다. `admin_ui/src/views/` 디렉터리는 현재 없다.
- API 호출은 대부분 `admin_ui/src/api/client.ts`의 `request()` 래퍼를 통한다. `401`은 토큰 삭제와 전역 unauthorized 핸들러로 처리하지만, `403` 권한 부족은 일반 `ApiResponseError`로만 전달된다.
- enum 라벨은 `GET /metadata/enums` 기반 `useEnumMetadata()`가 있으나, 여러 화면이 여전히 자체 수동 매핑을 함께 사용한다.
- 공통 테이블 `DataTable`은 `loading`과 `empty`만 표현한다. `error`, `stale`, `partial failure`, `permission denied`, `last fetched at` 같은 운영 상태 슬롯은 없다.

## 화면별 확인 결과

| 화면 | 주요 API | 현재 표시 상태 | 운영 오해 가능성 |
|---|---|---|---|
| 운영 대시보드 | `GET /health`, `/health/readyz`, `/orders?date=today`, `/orders/daily-summary`, `/orders/buy-block-summary`, `/clients`, `/accounts`, `/account-snapshots/latest`, `/reconciliation/summary`, `/snapshot-sync-runs`, `/market-sessions/latest`, `/market-sessions/operations-day/latest`, `/instruments/trading-universe/freeze-summary`, `/instruments/index-membership/staleness` | 개별 API 실패를 `apiErrors`에 누적하고 일부 카드/알림에 반영한다. 여러 호출은 실패 시 `null` 또는 `[]`로 fallback한다. | 일부 계좌·스냅샷 fan-out 실패가 집계 숫자 축소처럼 보일 수 있다. 카드 값의 기준 시각이 API별로 일관되게 노출되지 않는다. 상태 라벨 일부가 화면 내부 수동 매핑이다. |
| 주문 | `GET /orders?date=YYYY-MM-DD`, `GET /metadata/enums` | 목록 API 실패는 전체 오류로 표시한다. empty와 error는 구분된다. | 조회 성공 시점 또는 데이터 freshness가 없다. enum 메타데이터 실패 시 라벨이 원문으로 fallback되지만, 화면에는 "라벨 메타데이터 미확인" 상태가 없다. |
| 정합성 점검 | `GET /reconciliation/runs`, `/reconciliation/locks`, `/orders?status=reconcile_required`, `/positions?account_id=...`, `/orders/{id}/broker-orders` | runs/locks는 섹션 오류를 나누지만, 과거 실패 조회와 브로커 보조 조회 실패는 빈 목록으로 변환된다. | API 실패가 "과거 실패 이력 없음" 또는 "브로커 정보 없음"처럼 보일 수 있다. `started` 상태를 필터 옵션에는 `running`으로 두는 등 원본 상태값과 화면 용어가 섞인다. |
| 계좌 | `GET /snapshot-sync-runs?limit=1`, `/clients/default`, `/clients`, `/accounts?client_id=...`, `/account-snapshots/latest?account_id=...` | 계좌 목록 오류는 전체 오류다. 상세 오류도 전체 `error`로 올라간다. 최신 스냅샷 run 오류는 boolean만 세팅되고 화면에는 표시되지 않을 수 있다. | 스냅샷 동기화 API 실패가 헤더에서 사라져 "문제 없음"처럼 보일 수 있다. 현금/포지션이 없을 때 API 실패, 미수집, 실제 0 보유를 구분하기 어렵다. |
| 의사결정 | `GET /trade-decisions`, `/decision-contexts/{id}`, `/external-events/recent`, `/metadata/enums` | 목록 실패는 오류 표시. 상세 컨텍스트/외부 이벤트는 별도 오류 상태를 가진다. | `execution_status`, stop reason, source type 일부가 화면 내부 수동 매핑이다. 목록은 조회일 기본값이 있으나 기준 시각/freshness는 없다. 검색은 현재 서버 페이지 내부 필터라 전체 결과 검색처럼 오해할 수 있다. |
| 에이전트 실행 | `GET /agent-runs` | 목록 실패는 오류 표시. empty는 별도 표시. | 상태 라벨과 에이전트 유형이 대부분 화면 내부 수동 해석이다. 조회 기준 시각과 데이터 freshness가 없다. |

## 우선순위가 높은 구조적 약점

1. **API 실패를 빈 데이터로 바꾸는 보조 경로**
   - `ReconciliationView`의 historical failed run 조회 실패는 `setHistoricalFailedRuns([])`로 처리된다.
   - `ReconciliationView`의 broker order lazy load 실패는 해당 주문의 broker orders를 빈 배열로 저장한다.
   - `OperationsDashboardView`도 여러 API를 `[]` 또는 `null`로 fallback하고 `apiErrors`에 누적하지만, 모든 카드가 그 partial failure를 직접 드러내지는 않는다.

2. **freshness 기준이 화면마다 다르거나 없다**
   - 대시보드와 계좌 화면 일부는 `snapshot_at`, `started_at`, `formatKstElapsed()`를 사용한다.
   - 주문, 의사결정, 에이전트 실행 목록에는 "이 목록을 언제 성공적으로 받았는지"가 없다.
   - 백엔드는 `SnapshotSyncRunHealthSummary.is_stale`, `stale_threshold_seconds`, `ReconciliationSummary.generated_at` 같은 필드를 제공하지만 모든 화면이 일관되게 소비하지 않는다.

3. **auth/permission/empty/error 구분이 공통화되어 있지 않다**
   - `request()`는 `401`만 특별 취급하고 `403`은 일반 오류 문자열로 넘어간다.
   - 공통 `DataTable`은 permission denied나 API 실패를 표현할 수 없어 각 화면이 직접 처리해야 한다.
   - 결과적으로 권한 부족, 필터 결과 0건, API 실패, 데이터 미수집이 화면별로 다른 방식으로 드러난다.

4. **백엔드 enum metadata와 화면 내부 수동 매핑이 병존한다**
   - `order_status`, `side`, `decision_type`, `entry_style`는 백엔드 `ENUM_METADATA`에 등록되어 있다.
   - `OrdersView`는 일부 메타데이터를 쓰지만, `OperationsDashboardView`, `ReconciliationView`, `AgentRunsView`, `AgentRunDetailPanel`, `DecisionsView`에는 수동 상태/라벨 매핑이 남아 있다.
   - 새 상태값이 추가되면 프론트가 임의 색상 또는 원문 fallback으로 표시할 가능성이 있다.

5. **부분 실패 집계의 운영 의미가 부족하다**
   - `OperationsDashboardView`는 fan-out 중 일부 계좌 또는 스냅샷 조회 실패를 감지하지만, 최종 집계 카드의 숫자가 "전체 성공 기준"인지 "일부 성공 기준"인지 카드 옆에서 바로 확인하기 어렵다.
   - 운영자는 낮아진 숫자를 실제 보유/주문 감소로 오해할 수 있다.

## 다음 구현 단위

### 1순위: 보조 API 실패를 빈 데이터와 분리

대상: `ReconciliationView`

- historical failed run 조회 실패를 `historicalFailedError` 상태로 분리한다.
- broker order lazy load 실패를 주문별 `brokerErrorMap`으로 분리한다.
- 실패 시 "이력이 없습니다" 또는 "브로커 정보 없음" 대신 "조회 실패, 원본 상태 미확인"을 표시한다.
- 검증: `bash scripts/harness/run.sh admin-test-one src/__tests__/reconciliation.test.tsx`, 필요 시 `bash scripts/harness/run.sh accept frontend`

### 2순위: 화면 공통 데이터 상태 모델 도입

대상: `DataTable` 또는 작은 `DataStateBanner` 컴포넌트

- `empty`, `error`, `permissionDenied`, `partial`, `stale`, `lastFetchedAt`를 표현할 수 있는 공통 표시 단위를 만든다.
- 처음에는 `OrdersView`, `DecisionsView`, `AgentRunsView`처럼 단일 목록 화면 1~2개에만 적용한다.
- 검증: 해당 view 단일 테스트 selector와 `accept frontend`

### 3순위: 조회 성공 시각과 freshness 표시 추가

대상: `OrdersView`, `DecisionsView`, `AgentRunsView`

- 목록 API 성공 시 `lastFetchedAt`을 저장하고 헤더 또는 필터 줄에 KST 기준으로 표시한다.
- 자동 새로고침이 없다는 사실을 "성공한 마지막 조회 시각"으로 명확히 한다.
- stale 판정은 임의 정책을 만들지 말고, 먼저 timestamp 표시만 추가한다.

### 4순위: enum/status 라벨 소스 정리

대상: `OperationsDashboardView`, `ReconciliationView`, `DecisionsView`, `AgentRunsView`

- 백엔드 `ENUM_METADATA`가 있는 필드는 `getEnumLabel()`을 우선 사용한다.
- metadata에 없는 필드는 문서화된 로컬 매핑으로 격리하고, fallback은 원문 값과 "미등록 상태"를 같이 드러낸다.
- `execution_status`처럼 백엔드에서 derived 되는 값은 화면에서 의미를 재정의하지 않는다.

### 5순위: 운영 대시보드 partial failure 표시 강화

대상: `OperationsDashboardView`

- `apiErrors`를 카드별 source coverage와 연결한다.
- 계좌 fan-out, 스냅샷 fan-out 실패가 있으면 집계 카드에 "일부 계좌 미반영"을 직접 표시한다.
- `[]` fallback으로 계산된 0과 실제 0을 구분한다.

## 1순위 추천 작업

가장 먼저 `ReconciliationView`의 "API 실패가 빈 데이터처럼 보이는 경로"를 고친다. 이 화면은 정합성 잠금, unresolved run, broker order 확인처럼 주문 안전성과 직접 연결된 read/inspect 화면이고, 현재 실패를 빈 배열로 바꾸는 코드 경로가 명확하다. 변경 범위도 한 화면과 단일 테스트 파일로 좁힐 수 있다.

## 후속 구현용 프롬프트 초안

```text
작업 루트는 /workspace/agent_trading_dev/ 기준.
CLAUDE.md, AGENTS.md, admin_ui/AGENTS.md를 따른다.

목표:
Admin UI ReconciliationView에서 API 실패가 빈 데이터처럼 보이는 경로를 수정한다.

필수 범위:
- historical failed run 조회 실패를 "과거 실패 이력 없음"과 구분해 표시한다.
- broker order lazy load 실패를 "브로커 정보 없음"과 구분해 표시한다.
- 백엔드 상태값 의미를 프론트에서 재정의하지 않는다.
- 화면 문구는 한국어로 작성한다.

검증:
- bash scripts/harness/run.sh admin-test-one src/__tests__/reconciliation.test.tsx
- bash scripts/harness/run.sh accept frontend

완료 보고:
- 변경 파일
- 실패/empty/loading 구분 방식
- 실행 검증과 미검증 범위
```

## 미확인 사항

- 실제 운영 API/DB 호출은 하지 않았다. 이 문서는 현재 소스와 schema 기준의 구조 분석이다.
- RBAC 정책의 세부 권한 matrix는 이번 범위에서 별도 문서/서버 설정까지 추적하지 않았다.
- 화면별 실제 브라우저 렌더링과 스크린샷 검증은 하지 않았다.
- `admin_ui/src/views/`는 없고 현재 구조는 `components/*View.tsx` 중심임을 확인했다.
