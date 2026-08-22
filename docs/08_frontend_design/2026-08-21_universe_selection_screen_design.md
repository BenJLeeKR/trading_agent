# 유니버스 선정 현황 화면 분리 — 설계 문서

> **상태**: 📝 설계 전용(이번 문서 작성 시점 기준 구현 미착수)
> **목적**: `운영 대시보드`(`OperationsDashboardView.tsx`) 하단의 `Universe Selection / Market Overlay`
> 섹션을 제거하고, `core`/`market_overlay`/`event_overlay` 선정 종목을 날짜별로 볼 수 있는
> 별도 화면 `유니버스 선정 현황`(`/operations/universe-selection`)으로 분리하기 위한 구조 설계.
> 이번 문서는 레이아웃/API 계약/상태 표현 설계까지만 다루며, 실제 컴포넌트 구현은 후속 작업이다.

## 0. 오타/용어 확인

요구사항의 "event overlay"는 백엔드에 **정확히 동일한 이름 `event_overlay`**로 실존한다
(`SourceType.EVENT_OVERLAY = "event_overlay"`, [`universe_selection_types.py:31`](../../src/agent_trading/services/universe_selection_types.py)).
다른 이름(catalyst, news overlay 등)으로 대체되어 있지 않으므로, 화면/문서 어디에서도
`event_overlay`를 그대로 쓴다.

`SourceType`(`universe_selection_types.py:29-34`) 전체 값:

```
CORE                    = "core"
MARKET_OVERLAY          = "market_overlay"
EVENT_OVERLAY           = "event_overlay"
RECONCILIATION_OVERLAY  = "reconciliation_overlay"
HELD_POSITION           = "held_position"
MANUAL                  = "manual"
```

요구사항의 4개 카드(core/market_overlay/event_overlay/전체 수량)는 이 중 앞 3개만 다루고,
나머지 3개(`reconciliation_overlay`/`held_position`/`manual`)는 "기타"로 뭉쳐 별도 처리한다(§4.5).

## 1. 현재 구조 요약

| 항목 | 내용 |
|---|---|
| 위치 | [`OperationsDashboardView.tsx:1322-1366`](../../admin_ui/src/components/OperationsDashboardView.tsx) — "Section D", `Panel` 안에 통계 카드 4개(그리드)만, 목록 테이블 없음 |
| 호출 API | `getActiveIntradayFreezeSummary()`([`client.ts:463-469`](../../admin_ui/src/api/client.ts)) → `GET /instruments/trading-universe/freeze-summary` 단 하나. **날짜 파라미터 없음** |
| 서버 동작 | 항상 `datetime.now(timezone.utc).astimezone(_KST).date()`로 "오늘"만 조회([`instruments.py:76`](../../src/agent_trading/api/routes/instruments.py)) |
| 응답 타입 | `TradingUniverseFreezeView`([`types/api.ts:404-414`](../../admin_ui/src/types/api.ts)): `business_date`, `frozen_at`, `target_count`, `source_type_counts: Record<string, number>`, `inclusion_reason_counts`, `items: TradingUniversePreviewItem[]` |
| item 타입 | `TradingUniversePreviewItem`([`types/api.ts:396-402`](../../admin_ui/src/types/api.ts)): `symbol`, `market`, `source_type: string`, `inclusion_reason: string`, `priority: number` — **enum이 아니라 plain string**, 프론트가 값을 임의로 재해석하지 않고 백엔드 문자열을 그대로 사용해야 함 |
| 현재 표시 | 오늘 freeze 편입 수(`target_count`), `market_overlay`/`event_overlay` 카운트, 그리고 이 요구사항과 무관한 "오늘 매수 주문 전환" 카드(별개 지표) |
| 제거 영향 | `deriveAlerts`(`lib/alerts.ts`)는 freeze/universe 필드를 참조하지 않아 알림 로직 영향 없음. `dashboard.test.tsx`의 "renders universe selection / market overlay panel" 테스트 1건만 제거 대상 |
| Auth/RBAC | `ProtectedRoute.tsx`는 `isAuthenticated` 단일 게이트만 있고 역할별 권한 분리가 없음 — 새 화면도 기존 `operations/*` 라우트와 동일하게 이 게이트 하나만 통과하면 됨. **RBAC 충돌 없음** |
| 라우팅 패턴 | `App.tsx:53-68`에 `operations/alerts`, `operations/orders`, `operations/realtime-quotes`처럼 `operations/*` 하위 라우트 관례가 이미 있음 |
| 네비게이션 | `Layout.tsx:49-61` "운영 모니터링" 그룹에 "운영 경고"/"주문 추적"/"정합성 점검"이 나열되어 있음 |

## 2. 새 화면 정보 구조

```
유니버스 선정 현황 (/operations/universe-selection)
├── 날짜 선택 (기본값: 오늘 KST)
├── freshness 표시 (frozen_at)
├── 요약 카드 4개: 전체 수량 / core / market_overlay / event_overlay
├── bucket별 종목 리스트 (Panel + DataTable, 3개 섹션: core / market_overlay / event_overlay)
└── 기타(reconciliation_overlay / held_position / manual) — 접이식 Panel 1개
```

## 3. API 계약 변경 필요 여부

### 3.1 라우트: 파라미터만 확장, 하위 호환 유지

```
GET /instruments/trading-universe/freeze-summary?business_date=YYYY-MM-DD
```

- `business_date` 쿼리 파라미터를 **옵션**으로 추가. 생략 시 기존과 동일하게 KST 오늘로 동작(하위 호환 — 대시보드에 이 API를 계속 쓰는 다른 곳이 있다면 영향 없음, 실제로는 없음, §1).
- 잘못된 날짜 형식(`YYYY-MM-DD`가 아님)은 `400 Bad Request`.
- 응답 스키마(`TradingUniverseFreezeView`)는 변경 없음. `business_date`가 미래 날짜거나 freeze가 없는 날이면 기존과 동일하게 `null` 반환(§5.3).

### 3.2 repository 변경 필요 없음

`UniverseFreezeRunRepository.get_latest(business_date: date, freeze_purpose: str)`
([`contracts.py:1553-1557`](../../src/agent_trading/repositories/contracts.py))가 **이미 날짜 파라미터를 받는다**.
`_build_active_intraday_freeze_view(repos)`([`instruments.py:72-110`](../../src/agent_trading/api/routes/instruments.py))만
`business_date: date | None = None` 인자를 추가로 받아 `business_date or datetime.now(...).astimezone(_KST).date()`로
바꾸면 된다. Postgres/InMemory 구현 양쪽 모두 이미 날짜로 필터링하므로 리포지토리 계층은 손대지 않는다.

### 3.3 client.ts 변경

```ts
getActiveIntradayFreezeSummary(businessDate?: string): Promise<TradingUniverseFreezeView | null>
```

옵션 인자 추가만으로 충분. 미지정 시 기존 대시보드 호출부(제거 예정이지만 과도기에 남아있을 수 있음)는 그대로 동작.

## 4. 화면 레이아웃 설계

### 4.1 데스크톱 와이어프레임

```
┌──────────────────────────────────────────────────────────────────────┐
│ 유니버스 선정 현황                                                     │
├──────────────────────────────────────────────────────────────────────┤
│ [FilterBar rightSlot]  조회일: [2026-08-21 ▾]   frozen 09:02:14 KST   │ ← §4.2, §4.3
├──────────────────────────────────────────────────────────────────────┤
│ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐              │
│ │ 전체 수량  │ │  core     │ │market_    │ │event_     │  ← StatusCard × 4
│ │  128건    │ │  84건     │ │overlay 30건│ │overlay 10건│              │
│ │ *합계 아님│ │           │ │           │ │           │              │
│ └───────────┘ └───────────┘ └───────────┘ └───────────┘              │
├──────────────────────────────────────────────────────────────────────┤
│ Panel: core (84건)                                                    │
│  ┌ DataTable: symbol | market | inclusion_reason | priority ┐        │
│  └──────────────────────────────────────────────────────────┘        │
├──────────────────────────────────────────────────────────────────────┤
│ Panel: market_overlay (30건)                                          │
│  ┌ DataTable: symbol | market | inclusion_reason | priority ┐        │
│  └──────────────────────────────────────────────────────────┘        │
├──────────────────────────────────────────────────────────────────────┤
│ Panel: event_overlay (10건)                                           │
│  ┌ DataTable: symbol | market | inclusion_reason | priority ┐        │
│  └──────────────────────────────────────────────────────────┘        │
├──────────────────────────────────────────────────────────────────────┤
│ ▸ 기타(reconciliation_overlay / held_position / manual) — 4건 [펼치기] │ ← 접이식, §4.5
└──────────────────────────────────────────────────────────────────────┘
```

### 4.2 상단 날짜 선택 영역

`FilterBar`의 `rightSlot`에 `DecisionsView.tsx:510-517` / `RealizedPnlView.tsx:551-558`와
동일한 패턴(`<label>조회일</label>` + `<input type="date">`)을 그대로 재사용한다.
새 날짜 입력 컴포넌트를 만들지 않는다. 기본값은 오늘(KST), URL query param(`?date=YYYY-MM-DD`)과
동기화해 새로고침/링크 공유 시에도 같은 날짜가 유지되게 한다.

### 4.3 freshness 표시 위치

날짜 선택 영역 바로 옆(같은 줄, `rightSlot` 안)에 `frozen {formatKstDateTime(frozen_at)}` 텍스트를
작게 배치 — 기존 Section D의 위치(카드 subtitle)보다 상단으로 끌어올려, "이 화면이 지금 보여주는
데이터가 언제 얼려진(freeze) 것인지"를 카드를 안 봐도 바로 알 수 있게 한다. freeze가 없는 날은
이 자리에 "—" 대신 **"해당 날짜 freeze 없음"**을 명시(§5.3, 0건과 구분).

### 4.4 요약 카드 4개 배치

`StatusCard` 4개를 grid로 배치(`grid grid-cols-2 xl:grid-cols-4 gap-3`, 기존 Section D 그리드 그대로 재사용).
"전체 수량" 카드에는 subtitle로 **"core+market+event 합계와 다를 수 있음(기타 포함)"** 각주를 고정 표시한다
(요구사항 §7 대응, §4.5·§5.6 참고). 나머지 3개 카드는 각 bucket의 `source_type_counts[...]` 값을 그대로 표시.

### 4.5 bucket별 리스트 배치 — Tabs 대신 Panel 스택

Admin UI `common/`에는 Tabs 프리미티브가 없다(`Panel`/`DataTable`/`StatusCard`/`StatusBadge`/`FilterBar`/
`LoadingSpinner`/`ErrorBanner`만 존재). 새 탭 컴포넌트를 만들기보다, `Dashboard`의 Section A~D처럼
**Panel을 bucket별로 세로로 3개 나열**하는 기존 관례를 그대로 따른다. 각 Panel 제목에 bucket 이름과
건수를 함께 표시(`title="core (84건)"`)해서, 스크롤 중에도 어느 섹션인지 헷갈리지 않게 한다.
종목 행에는 `source_type` 값을 그대로 보여주는 `StatusBadge`를 추가로 붙여, "이 Panel 안에 있으니
당연히 이 bucket"이라는 암묵적 가정에만 의존하지 않고 행 단위로도 재확인 가능하게 한다(요구사항 §8
"오해하지 않게" 대응).

기타(`reconciliation_overlay`/`held_position`/`manual`) 항목은 운영자가 일상적으로 볼 필요가 적으므로
**접이식(collapsed) Panel** 1개로 뒤에 배치(기본 접힘, 클릭 시 펼침) — `OperationsAlertsView.tsx`의
`notesCollapsed` 패턴과 동일한 방식.

### 4.6 mobile 대응

- 요약 카드 그리드: `grid-cols-2`(mobile) → `xl:grid-cols-4`(desktop), Section D의 기존 그리드 클래스 그대로.
- `DataTable`은 기존 컴포넌트가 이미 responsive 스크롤을 지원(다른 화면에서 검증됨) — 별도 처리 불필요.
- 날짜 선택 영역은 `FilterBar`가 이미 `flex-wrap`으로 좁은 화면에서 줄바꿈 처리.

## 5. 상태별 표시 설계

| 상태 | 판정 근거 | 표현 |
|---|---|---|
| loading | fetch 중 | `LoadingSpinner`, 카드/리스트 영역 전체를 스켈레톤 없이 스피너로 대체(날짜 변경 시에도 동일하게 **즉시 리셋**, §5.5) |
| API 실패 | `GET .../freeze-summary` reject | `ErrorBanner`("다시 시도") — 화면 전체를 에러로 표시. **카드/리스트를 0이나 빈 리스트로 렌더링하지 않는다** |
| 해당 날짜 freeze 없음 | 응답 `null`(freeze_run 없음 또는 items 없음, [`instruments.py:88,92`](../../src/agent_trading/api/routes/instruments.py)) | 카드 값 "—" + `StatusCard` `neutral` variant, `badgeLabel="미수집"`(기존 대시보드 관례, `StatusCard.tsx:10`) + 리스트 영역에 "해당 날짜 freeze 없음" 안내 문구. **"0건"과 시각적으로 다르게 표기** |
| 조회 성공 + 특정 bucket 0건 | 응답 성공, `source_type_counts`에 해당 키 없음/0 | 카드에 "0건" 그대로(정상 variant), 해당 Panel 본문에 "이 날짜에는 core 선정 종목이 없습니다"처럼 **명확한 0건 문구**(빈 테이블만 덜렁 두지 않음) — "미수집"과 절대 혼용하지 않음 |
| stale/freshness | `frozen_at` | §4.3. 추가로 조회 날짜가 오늘이 아닐 때(과거 날짜 조회 중)는 "freshness" 개념 자체가 무의미하므로, `frozen_at`을 "이 날짜의 freeze 시각"으로만 표시하고 "얼마나 오래됐는지(stale 경고)"는 **오늘 날짜 조회일 때만** 판단한다 — 과거 날짜를 "오래된 데이터"로 오판하지 않게 |
| 날짜 변경 중 이전 데이터 오인 | 날짜 input `onChange` 시점 | 새 요청 시작과 동시에 카드/리스트를 **즉시 loading 상태로 리셋**(이전 날짜 값을 그대로 둔 채 로딩 스피너만 겹치지 않게) — 그렇지 않으면 "8/20 데이터가 8/21 데이터인 것처럼" 보일 수 있음 |
| auth/RBAC | ProtectedRoute 단일 게이트 | 이 화면 전용 권한 분기는 없음. 인증 실패 시 기존 라우팅 로직(`/login` redirect)이 동일하게 적용되므로 화면 자체에서 추가 처리 불필요 — 다만 **API 401/403을 "freeze 없음"으로 오인하지 않도록**, `getActiveIntradayFreezeSummary`가 인증 오류를 던지면 반드시 "API 실패" 경로로 분류(HTTP status로 구분, 응답이 `null`인 정상 케이스와 섞지 않음) |
| enum 임의 해석 위험 | `source_type: string`(enum 아님, [`types/api.ts:397`](../../admin_ui/src/types/api.ts)) | 프론트는 `source_type` 값을 6개 알려진 값(§0)으로 화이트리스트 매핑만 하고, **모르는 값이 오면 "기타"로 그냥 떨어뜨리되 원본 문자열을 함께 노출**(예: 배지에 원본 값 표시) — 새로운 `SourceType`이 백엔드에 추가돼도 화면이 조용히 그 종목을 숨기지 않게 함 |

## 6. 테스트 설계

1. 대시보드에서 Section D("Universe Selection / Market Overlay") 관련 텍스트/Panel이 더 이상 렌더링되지 않는지(`dashboard.test.tsx` 기존 테스트 제거 + `queryByText` 부재 회귀 테스트)
2. 새 화면: `source_type_counts`로부터 전체/core/market/event 4개 카드 값이 정확히 산출되는지
3. 날짜 변경 시 `business_date` 파라미터로 API가 다시 호출되는지(spy call args 확인), 그리고 새 요청 중 이전 데이터가 즉시 사라지고 loading으로 전환되는지
4. core/market/event 종목이 각각 올바른 Panel에만 나타나는지(잘못된 bucket에 섞이지 않는지)
5. `source_type`이 알려진 6개 값이 아닌 임의 문자열일 때 "기타"로 떨어지되 원본 값이 화면에서 사라지지 않는지
6. 상태 3종 개별 렌더 테스트: (a) freeze 없음("미수집" 표기, "0건" 아님) (b) API 실패(`ErrorBanner`, 카드 0 아님) (c) 정상 응답이지만 특정 bucket 0건("0건" 명시 문구)

## 7. 구현 단위 (3~5개)

1. **백엔드**: `GET /instruments/trading-universe/freeze-summary`에 옵션 `business_date` 쿼리 파라미터 추가(리포지토리 변경 없음, 라우트 함수 1개만 수정 + 최소 테스트)
2. **프론트 API client/타입**: `getActiveIntradayFreezeSummary(businessDate?)` 시그니처 확장
3. **새 화면 뼈대**: `UniverseSelectionView.tsx` 라우트(`/operations/universe-selection`)/nav 추가, 날짜 선택 + freshness + 4개 카드까지만(리스트 없이), loading/error/미수집 상태 포함
4. **리스트 렌더링**: core/market_overlay/event_overlay 3개 Panel+DataTable 추가 + bucket 배지 + 기타 접이식 Panel
5. **대시보드 정리**: Section D 및 관련 fetch/state/기존 테스트 제거("오늘 매수 주문 전환" 카드 유지 여부는 별도 확인 필요, §9)

## 8. 1순위 구현 추천

**단위 1(백엔드 `business_date` 파라미터 추가)**을 최우선 추천한다. 나머지 프론트 작업 전부가 이
파라미터의 존재를 전제로 하며, 백엔드 변경은 리포지토리 수정 없이 라우트 함수 하나만 건드리는 가장
작고 리스크가 낮은 단위이고, 옵션 파라미터라 기존 대시보드 호출부에도 영향이 없어 독립적으로
병합 가능하다.

## 9. 미확인 사항

- `freeze_purpose`는 현재 코드에서 `"decision_loop_intraday"` 하나만 하드코딩되어 있음 — 운영 데이터에
  다른 purpose 값이 실제로 존재하는지는 확인하지 않음(이번 화면 범위에서는 이 값 하나만 다룬다고 가정).
- Section D의 4번째 카드였던 "오늘 매수 주문 전환"(freeze 종목 기준 매수 주문 전환 건수)을 새 화면에
  포함할지, 완전히 버릴지는 요구사항에 명시되어 있지 않음 — 사용자 확인 필요.
- 실제 인증 토큰 만료/401 응답이 이 API에서 다른 API와 동일한 형태로 오는지는 코드 레벨로만 확인했고,
  실제 API 호출로 재현 테스트하지는 않았음(이번 턴은 문서 설계만 진행, API 대량 호출 금지 지침 준수).
- Admin UI 디자인 시스템에 명시적 "기타" 접이식 패턴의 재사용 가능한 공용 컴포넌트가 없어, 이번엔
  `OperationsAlertsView.tsx`의 `notesCollapsed` state 패턴을 참고로 제시했다 — 실제 구현 시 공용
  `Collapsible` 컴포넌트로 뽑아낼지는 후속 판단 필요.
