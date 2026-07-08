# KIS 실시간 현재가 조회 화면 — 구현 실행 계획

> **목적**: `plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md`(Backend/API 설계)와
> `plans/[DESIGN]_kis_realtime_quote_screen_ui_layout.md`(Admin UI 레이아웃 설계)를
> 실제 구현 가능한 단위(작은 PR)로 분해한다.
> **상태**: ❌ 미구현 — 이 문서는 실행 계획 문서이며, 이 작업 자체로는 코드를 변경하지 않는다.
> **참조**: [`11_kis_realtime_quote_operations_screen.md`](../plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md),
> [`[DESIGN]_kis_realtime_quote_screen_ui_layout.md`](%5BDESIGN%5D_kis_realtime_quote_screen_ui_layout.md),
> [`[BACKLOG] backlog.md` #37](%5BBACKLOG%5D%20backlog.md),
> [`[PRIORITY_MAP] remaining_work_priority_map.md` #19](%5BPRIORITY_MAP%5D%20remaining_work_priority_map.md)

---

## 목차

1. [목표](#1-목표)
2. [비목표](#2-비목표)
3. [선행 조건](#3-선행-조건)
4. [현재 재사용 가능한 코드/문서](#4-현재-재사용-가능한-코드문서)
5. [구현 단계](#5-구현-단계)
6. [파일별 예상 변경 범위](#6-파일별-예상-변경-범위)
7. [DB Migration 필요 여부 판단](#7-db-migration-필요-여부-판단)
8. [운영 안전장치](#8-운영-안전장치)
9. [테스트 명령 후보](#9-테스트-명령-후보)
10. [Rollback 전략](#10-rollback-전략)
11. [Phase 1에서 의도적으로 제외할 항목](#11-phase-1에서-의도적으로-제외할-항목)

---

## 1. 목표

- Admin UI "기본 운영" 메뉴 아래 "실시간 현재가" 화면을 추가해, 운영자가 선택한 종목의
  실시간 체결가(`H0STCNT0`)/호가(`H0STASP0`, 둘 다 KRX 전용)를 조회할 수 있게 한다.
- 이 화면 전용의 **완전히 분리된 Live 계좌·앱키**(이미 발급·행정 처리 완료)로 KIS
  WebSocket에 연결하고, 기존 트레이딩 계좌/공시 계좌(`KIS_APP_KEY`, `KIS_LIVE_INFO_*`)의
  세션·rate-limit budget과 **전혀 공유하지 않는다**.
- 구현자가 리뷰 가능한 크기의 PR 단위로 나눠 진행할 수 있도록, 각 구현 단계(§5)를
  독립적으로 머지 가능한 순서로 배열한다.

## 2. 비목표

- 주문 제출, 자동매매 판단, universe 편입, signal 계산과의 연결 — 이 화면은 시작부터
  끝까지 read-only다.
- 기존 트레이딩 계좌·공시 계좌(`KIS_LIVE_INFO_*`)의 세션/코드 경로 변경 — 이 작업은
  신규 계좌 전용 클라이언트 인스턴스만 추가하며, 기존 `KoreaInvestmentAdapter`,
  `KisMarketStateClient`, `OrderManager`, `ReconciliationService` 등 주문/체결/정합성
  경로는 **일절 수정하지 않는다.**
- **`ops-scheduler` 서비스/코드 수정** — 이 신규 계좌 전용 WebSocket 연결은 전적으로
  `api` 서비스 프로세스(FastAPI `lifespan`) 안에서만 생성·유지된다.
  `scripts/run_ops_scheduler.py`를 비롯한 `ops-scheduler` 컨테이너의 어떤 코드도
  이번 작업 범위에서 수정하지 않으며, 재배포·재시작도 필요하지 않다. §6, §8 참고.
- KIS 통합 채널(`H0UNCNT0`/`H0UNASP0`, KRX+NXT)이나 REST polling 방식 채택 —
  이미 KRX 전용 + 실시간 스트리밍으로 결정됨(`11_...md` §3).
- 이번 계획에는 §11에 명시한 항목(차트, 워치리스트 영속화, 알림, 다중 종목 비교 뷰 등)을
  포함하지 않는다.

## 3. 선행 조건

| # | 항목 | 상태 |
|---|---|---|
| 1 | 신규 계좌·앱키 발급 및 행정 처리 | ✅ 완료 (사용자 확인) |
| 2 | Backend 설계 문서 확정 | ✅ 완료 — `11_kis_realtime_quote_operations_screen.md` |
| 3 | UI 레이아웃 설계 확정 | ✅ 완료 — `[DESIGN]_kis_realtime_quote_screen_ui_layout.md` |
| 4 | `.env` 변수명 확정 | ✅ 완료 — `KIS_REALTIME_QUOTE_APP_KEY`/`APP_SECRET`/`BASE_URL`/`WS_URL` |
| 5 | 신규 계좌의 상한가/하한가/기준가/PER/PBR/EPS/BPS 보강 경로 확정 | ✅ **완료** — REST 현재가 조회(`029_주식현재가_시세.md`, TR `FHKST01010100`)로 확정. 기존 `KISRestClient.get_quote()`가 이미 이 필드들을 raw output으로 반환하므로 **신규 백엔드 코드 불필요**(Step 0 참고) |
| 6 | `OrdersView`/`FillHistoryView` 종목 클릭 딥링크 연동 범위 확정 | ✅ 완료 — UI 레이아웃 설계 §3.1에서 Phase 3 범위로 명시 |
| 7 | KIS 공식 문서 재확인(TR ID, message format, 구독 제한) | 🔄 **부분 완료** — 2026-07-08 사용자가 KIS 공식 웹페이지/문서로 재확인: `H0STCNT0`/`H0STASP0` 필드 스펙 일치, 41건 구독 한도 세부 규칙(계좌 합산, 체결가+호가 2건 계산), REST 현재가 조회(`FHKST01010100`) 응답 필드 일치 — 모두 확인 완료. **남은 항목은 approval key 발급(`/oauth2/Approval`) 요청/응답 필드뿐**이며, 이는 Step 3 구현 직전 최종 재확인으로 남긴다 |

## 4. 현재 재사용 가능한 코드/문서

| 대상 | 위치 | 재사용 내용 |
|---|---|---|
| WS 채널 파서 | [`ws_parser.py`](../src/agent_trading/brokers/koreainvestment/ws_parser.py) | `H0STCNT0`/`H0STASP0` 파서가 이미 구현됨 — **신규 파서 작성 불필요** |
| WS 클라이언트 | [`websocket_client.py`](../src/agent_trading/brokers/koreainvestment/websocket_client.py) | `KISWebSocketClient` 클래스 — 신규 계좌 자격증명으로 **별도 인스턴스** 생성해 재사용 |
| 구독 budget | [`base.py`](../src/agent_trading/brokers/base.py) | `SubscriptionBudget(max_subscriptions=41)` — `adapter.py:85` 패턴 재사용 |
| Approval key 캐시 | [`token_cache.py`](../src/agent_trading/brokers/koreainvestment/token_cache.py) | `KisTokenCache` + `build_live_approval_key_cache_config()` — fingerprint가 appkey/secret 기반이라 신규 계좌 자격증명을 넣으면 자동으로 캐시 파일 분리됨. 신규 `CachePurpose` 불필요 |
| REST quote 조회 | [`rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py) | `KISRestClient.get_quote()`(2086-2118행, TTL 캐시 포함, endpoint `inquire_price` → TR `FHKST01010100`) — REST fallback(§5.4)과 정적 참조값 보강(상한가/하한가/기준가/PER/PBR/EPS/BPS)에 그대로 재사용. raw `output` 딕셔너리를 그대로 반환하므로 **신규 파싱 코드 불필요** |
| API 라우트 패턴 | [`routes/broker_capacity.py`](../src/agent_trading/api/routes/broker_capacity.py) | "adapter 미설정 시 503" 패턴 — 신규 라우트 파일에 그대로 적용 |
| DI 패턴 | [`api/deps.py`](../src/agent_trading/api/deps.py) | `get_kis_client(request)` 스타일 — 신규 계좌 전용 adapter DI 함수 신설 시 참고 |
| Admin UI 공용 컴포넌트 | `admin_ui/src/components/common/*.tsx` | `StatusBadge`/`StatusCard`/`Panel`/`DataTable`/`DetailField`/`ErrorBanner`/`WarningBanner`/`LoadingSpinner`/`FilterBar` — UI 레이아웃 설계 §9에서 상세 매핑 확정 |
| 구독 한도 progress bar 패턴 | [`BrokerCapacityPanel.tsx`](../admin_ui/src/components/BrokerCapacityPanel.tsx) | 내부 `ProgressBar`/`utilisationColor()` — 41건 한도 표시에 재사용 |
| 종목 딥링크 패턴 | [`AccountsView.tsx:340`](../admin_ui/src/components/AccountsView.tsx), [`OrdersView.tsx:60-66`](../admin_ui/src/components/OrdersView.tsx) | `navigate(\`...?symbol=X\`)` + 마운트 시 쿼리 파라미터 읽기 패턴 |
| 메뉴/라우트 패턴 | [`Layout.tsx`](../admin_ui/src/components/Layout.tsx), [`App.tsx`](../admin_ui/src/App.tsx) | `navSections` 배열 + `<Route>` 추가 패턴 |

## 5. 구현 단계

각 단계는 **독립적으로 리뷰·머지 가능한 PR 단위**로 설계했다. 단계 간 의존성은
화살표(→)로 표시하며, 병렬 진행 가능한 단계는 명시한다.

### Step 0 — 정적 참조값 보강 경로 확정 (선행, 코드 변경 없음) — ✅ 확정 완료

- §3 항목 5는 이미 해소되었다: 상한가/하한가/기준가/PER/PBR/EPS/BPS는
  REST 현재가 조회(`029_주식현재가_시세.md`, TR `FHKST01010100`)로 확정.
  `KISRestClient.get_quote()`(`rest_client.py:2086-2118`)가 이 필드들을 raw
  `output` 딕셔너리로 이미 반환하므로 **신규 백엔드 코드가 필요 없다.**
- **적용 방식(확정)**: 종목이 신규 구독될 때(또는 종목 전환 시) `get_quote()`를
  1회 호출해 응답을 캐싱하고, 이후 장중에는 재조회하지 않는다(당일 상/하한가·
  기준가·PER/PBR/EPS/BPS는 장중 사실상 불변).
- Step 0의 남은 작업은 "결정"이 아니라 **"Step 3에서 이 값을 어느 컴포넌트가
  캐싱할지"를 정하는 구현 세부사항**으로 축소되었다 — `QuoteSubscriptionManager`
  내부에 종목별 정적 참조값 캐시(dict)를 두는 것을 권장(Step 3에서 구현).
- 참고: `[DESIGN]_kis_realtime_quote_screen_ui_layout.md` §6-E, v3 변경 사항.

### Step 1 — Backend Schema / API Contract (→ Step 2, 3의 전제)

- **작업**: `api/schemas.py`에 신규 Pydantic 모델 정의만 추가
  (`RealtimeQuoteBootstrapResponse`, `QuoteSubscriptionRequest`, `QuoteSubscriptionView`,
  `QuoteSnapshotView` 등 — 필드는 `11_...md` §5.1~5.4와 UI 설계 §6의 필드 매핑 기준).
- **범위**: 스키마 정의 + `routes/realtime_quotes.py`에 **stub 라우트**(빈 응답 또는
  501)만 등록해 API contract를 고정한다. 실제 KIS 연동 로직은 Step 3에서 채운다.
- **의존성**: 없음(첫 PR로 시작 가능).
- **구현 직전 재확인**: 없음(이 단계는 KIS 통신을 포함하지 않음).

### Step 2 — Admin UI Route / Menu 추가 (Step 1과 병렬 가능)

- **작업**: `Layout.tsx`에 "기본 운영" 섹션 메뉴 항목 추가, `App.tsx`에
  `/operations/realtime-quotes` 라우트 추가, mock 데이터 기반의 빈 화면 컴포넌트
  (`RealtimeQuoteView.tsx`) 최소 골격만 생성.
- **범위**: 메뉴 클릭 시 화면이 뜨는 것까지만 확인. 실제 데이터 연동은 Step 6에서.
- **의존성**: 없음(Step 1과 병렬로 진행 가능).

### Step 3 — Quote Subscription Manager + KIS WebSocket Adapter 연동

- **작업**:
  1. 신규 계좌 전용 자격증명(`KIS_REALTIME_QUOTE_APP_KEY` 등)을 읽는 설정 추가
     (`config/settings.py`).
  2. 신규 계좌 전용 `KISWebSocketClient` 인스턴스를 생성하는 factory 함수 추가
     (기존 `adapter.py`/`bootstrap.py`의 `KoreaInvestmentAdapter` 생성 경로와는
     **별도의 새 함수**로 분리 — 기존 함수 시그니처/동작 변경 금지).
  3. 종목별 참조 카운트 기반 구독/해제 관리자(가칭 `QuoteSubscriptionManager`) 구현
     — `SubscriptionBudget(max_subscriptions=41)` 사용. **종목 1개를 구독할 때마다
     체결가(`H0STCNT0`)+호가(`H0STASP0`) 2건을 원자적으로 등록/해제**하도록 구현
     (아래 "2026-07-08 재확인 결과" 참고 — 잔여 budget이 2건 미만이면 신규 종목
     추가를 거부).
  4. FastAPI `lifespan`에 이 매니저를 `app.state`로 등록.
- **범위**: 이 단계에서 실제로 KIS Live WS에 연결이 시작된다 — **여기서부터 실제
  네트워크/자격증명 검증이 필요**. 이 연결은 **`api` 서비스 프로세스 안에서만**
  생성·유지되며, `ops-scheduler` 컨테이너는 이 연결의 존재를 알 필요도, 어떤
  형태로도 관여할 필요도 없다. `ops-scheduler` 쪽 코드 변경·재배포는 이번 작업
  전체에 걸쳐 발생하지 않는다.
- **의존성**: Step 1(스키마) 완료 후 진행. Step 0(정적 참조값 결정) 완료 필요.
- **✅ 2026-07-08 KIS 공식 웹페이지/문서 재확인 완료**:
  - `H0STCNT0`/`H0STASP0`의 필드 스펙이 `172`/`178`번 문서와 **일치 확인됨**.
  - WebSocket 41건 한도 세부 사항 확인됨:
    - appkey/계좌 기준 세션 1개, 등록 건수 총합 41건 — 국내/해외/파생 **전체 실시간
      채널 합산**(이 화면이 이 앱키의 유일한 구독 주체인 동안은 문제 없음).
    - **체결가+호가를 같은 종목에 모두 구독하면 2건으로 계산됨** — 이 화면은 두
      채널을 모두 쓰므로, **41건 = 최대 약 20종목**으로 재계산해야 한다(41건이
      아니라 20종목이 실질 상한). §8 운영 안전장치, UI 레이아웃 설계 §1/§6-A에도
      이 수치를 반영함.
  - approval key 발급(`/oauth2/Approval`) 요청/응답 필드는 여전히 **구현 직전
    최종 재확인 대상**으로 남긴다(이번 확인 범위는 TR 필드/구독 한도로 한정).

### Step 4 — REST Fallback 연동

- **작업**: WS 연결 끊김이 N초 이상 지속될 때 `KISRestClient.get_quote()`를 1회
  호출해 값을 보정하는 로직을 `QuoteSubscriptionManager`에 추가(`11_...md` §4.7).
  REST client는 기존 트레이딩 계좌 client 재사용 여부를 이 단계에서 최종 확정.
- **의존성**: Step 3 완료 후.
- **✅ 2026-07-08 KIS 공식 웹페이지/문서 재확인 완료**: REST 현재가 조회(`FHKST01010100`,
  `029_주식현재가_시세.md`) 응답 필드가 최신 공지와 **일치 확인됨**
  (`stck_mxpr`/`stck_llam`/`stck_sdpr`/`per`/`pbr`/`eps`/`bps` 포함). 추가 재확인 불필요.

### Step 5 — Backend API 실제 연동 (Step 1 stub → 실 구현)

- **작업**: Step 1에서 만든 stub 라우트를 Step 3/4의 `QuoteSubscriptionManager`와
  연결해 실제 동작하는 API로 완성 (`GET /realtime-quotes/bootstrap`,
  `POST/DELETE /realtime-quotes/subscriptions`, `GET /realtime-quotes/subscriptions`,
  `GET /realtime-quotes/snapshot`).
- **의존성**: Step 1, 3, 4 완료 후.

### Step 6 — Realtime Quote Screen Component (Admin UI 데이터 연동)

- **작업**: Step 2의 화면 골격에 실제 API 연동(polling 방식, `11_...md` §5.5(a))을
  붙인다. UI 레이아웃 설계의 §4~§6(단일 종목 상세 뷰, 10단계 호가창, 종목 상세정보
  패널, 종목 전환 바)을 구현.
- **의존성**: Step 5 완료 후. Step 2 완료 후.

### Step 7 — 상태/오류/연결 표시

- **작업**: UI 레이아웃 설계 §7(Loading/Empty/Error/Degraded)의 4개 상태와 §5의
  연결 상태(A)/오류·재연결(F)/수신 상태(G) 영역을 구현. "연결이 불안정해도 화면
  전체를 비우지 않는다" 원칙을 컴포넌트 레벨에서 검증.
- **의존성**: Step 6과 함께 진행하거나 직후.

### Step 8 — 종목 딥링크 연동 (Optional, 별도 PR)

- **작업**: `OrdersView.tsx`/`FillHistoryView.tsx`의 종목 컬럼을 클릭 가능하게 변경해
  `/operations/realtime-quotes?symbol=X`로 이동하는 링크 추가(UI 레이아웃 설계 §3.1).
- **범위**: 기존 두 화면에 대한 **소규모 변경** — 주문/체결 데이터 표시 로직 자체는
  건드리지 않고, 컬럼 렌더링만 변경.
- **의존성**: Step 6(대상 화면이 존재해야 함) 완료 후. 독립적으로 별도 PR 권장(기존
  화면을 건드리는 유일한 단계이므로 리뷰를 분리하는 것이 안전).

### Step 9 — 테스트

- 각 Step에 해당하는 단위/통합 테스트는 그 Step의 PR에 포함한다(§9 참고).
- 전체 스위트 회귀 확인은 마지막 PR(Step 8 또는 그 이전 마지막 기능 PR)에서 1회 수행.

### 단계 요약 (실행 순서)

```
Step 0 (정적 참조값 출처 확정 — ✅ 완료, 코드 없음)
  └─▶ Step 1 (Backend contract) ──┐        Step 2 (UI route/menu 골격)
                                    ├─▶ Step 3 (WS adapter + subscription manager)
                                    │      └─▶ Step 4 (REST fallback)
                                    │             └─▶ Step 5 (API 실연동)
                                    │                    └─▶ Step 6 (UI 데이터 연동) ◀── Step 2
                                    │                           └─▶ Step 7 (상태/오류 표시)
                                    │                                  └─▶ Step 8 (딥링크, optional 별도 PR)
```

## 6. 파일별 예상 변경 범위

| 파일 | 변경 성격 | 해당 Step |
|---|---|---|
| `src/agent_trading/config/settings.py` | 추가 — `KIS_REALTIME_QUOTE_*` 4개 env 필드 | 3 |
| `src/agent_trading/api/schemas.py` | 추가 — 신규 Pydantic 모델 4~5개 | 1 |
| `src/agent_trading/api/routes/realtime_quotes.py` | **신규 파일** | 1, 5 |
| `src/agent_trading/api/app.py` | 추가 — 신규 라우터 등록, `lifespan`에 `QuoteSubscriptionManager` 초기화 코드 추가 | 3, 5 |
| `src/agent_trading/api/deps.py` | 추가 — 신규 계좌 전용 DI 함수 | 3 |
| `src/agent_trading/brokers/koreainvestment/quote_subscription_manager.py` | **신규 파일**(가칭) | 3, 4 |
| `src/agent_trading/runtime/bootstrap.py` | 추가 — 신규 계좌 전용 client factory 함수(기존 함수는 수정하지 않고 새 함수 추가) | 3 |
| `admin_ui/src/components/Layout.tsx` | 추가 — `navSections`에 메뉴 항목 1개 | 2 |
| `admin_ui/src/App.tsx` | 추가 — `<Route>` 1개 | 2 |
| `admin_ui/src/components/RealtimeQuoteView.tsx` | **신규 파일** | 2, 6, 7 |
| `admin_ui/src/components/common/QuoteLadder.tsx`(가칭, 10단계 호가 전용 렌더러) | **신규 파일** | 6 |
| `admin_ui/src/api/client.ts` | 추가 — `getRealtimeQuoteBootstrap()`/`subscribeQuote()`/`unsubscribeQuote()`/`getQuoteSnapshot()` | 6 |
| `admin_ui/src/types/api.ts` | 추가 — Step 1 스키마에 대응하는 TS 인터페이스 | 6 |
| `admin_ui/src/components/OrdersView.tsx` | 수정 — 종목 컬럼 `render`를 클릭 가능하게 변경 | 8 |
| `admin_ui/src/components/FillHistoryView.tsx` | 수정 — 종목 컬럼 `render`를 클릭 가능하게 변경 | 8 |
| `.env.example` | 추가 — `KIS_REALTIME_QUOTE_*` 4개 항목 | 3 |
| `docker-compose.yml` | 추가 — `api` 서비스 환경변수 전달 목록에 4개 항목 추가 | 3 |
| `tests/api/test_realtime_quotes.py` | **신규 파일** | 1, 5, 9 |
| `tests/brokers/koreainvestment/test_quote_subscription_manager.py` | **신규 파일** | 3, 4, 9 |
| `admin_ui/src/components/__tests__/RealtimeQuoteView.test.tsx` | **신규 파일** | 6, 7, 9 |

**변경하지 않는 파일(명시적 확인)**: `websocket_client.py`, `ws_parser.py`, `adapter.py`,
`market_state_client.py`, `order_manager.py`, `reconciliation_service.py`, 기존
`OrdersView.tsx`/`FillHistoryView.tsx`의 데이터 조회·필터 로직(컬럼 렌더링 외 부분).

**`ops-scheduler` 서비스 전체(명시적 확인)**: `scripts/run_ops_scheduler.py`를 포함해
`ops-scheduler` 컨테이너가 실행하는 어떤 파일도 이번 작업에서 변경하지 않는다.
`docker-compose.yml`에 추가하는 `KIS_REALTIME_QUOTE_*` 환경변수도 **`api` 서비스에만**
전달하며, `ops-scheduler` 서비스 정의에는 추가하지 않는다.

## 7. DB Migration 필요 여부 판단

**결론: 필요 없음.**

- `11_kis_realtime_quote_operations_screen.md` §4.5에서 이미 "메모리 전용
  (in-memory only), DB persistence 없음"으로 확정했다 — 이 화면의 quote snapshot은
  프로세스 메모리(`app.state`)에만 존재하며, 재시작 시 초기화되는 것을 허용한다.
- 구독 목록도 세션 동안만 유지되는 휘발성 상태이며(UI 레이아웃 설계 §11 "종목
  즐겨찾기 영속화" 제외), 별도 테이블이 필요 없다.
- 신규 계좌·앱키 자격증명은 `.env`(및 기존 `KisTokenCache` 파일 캐시 메커니즘)로
  관리되며, DB 스키마 변경이 필요 없다.
- 따라서 이번 작업 전체에 걸쳐 `src/agent_trading/db/migrations/`에 신규 마이그레이션
  파일을 추가하지 않는다. 만약 이후(Phase 2+) DB persistence 요구가 생기면(설계 문서
  §4.5의 "DB persistence로 전환할 기준" 참고) 그 시점에 별도 계획으로 다룬다.

## 8. 운영 안전장치

- **read-only 강제**: 신규 계좌 전용 adapter/client에는 주문 제출 관련 메서드를
  노출하지 않는다 — `KoreaInvestmentAdapter` 전체를 재사용하지 말고, quote/orderbook
  구독에 필요한 최소 인터페이스만 갖는 wrapper를 Step 3에서 구현한다.
- **세션 격리**: 신규 계좌의 `KISWebSocketClient` 인스턴스는 이 화면 전용 코드
  경로에서만 생성한다. 기존 `bootstrap.py`의 트레이딩 계좌 생성 함수를 수정하거나
  같은 함수를 신규 계좌에도 쓰는 방식은 금지(세션 preemption 위험).
- **uvicorn 단일 워커 유지**: `--workers 1` 설정을 변경하지 않는다(앱키당 1세션 제약).
- **구독 한도 하드 캡**: `SubscriptionBudget(max_subscriptions=41)`을 명시적으로
  설정하고, 초과 요청은 API 레벨에서 422/409로 거부(자동 evict 없음). **종목당
  체결가+호가 2건을 소비하므로 실질 상한은 약 20종목**이다 — UI/API 모두 "종목
  기준"이 아니라 "등록 건수 기준"으로 잔여 capacity를 계산해야 한다(잔여 2건 미만이면
  신규 종목 추가 거부).
- **Rate limit 격리 확인**: 신규 계좌는 별도 계좌이므로 기존 18RPS/41건 budget과
  공유되지 않음을 Step 3 구현 시 재확인(별도 `RateLimitBudgetManager` 인스턴스 사용).
- **민감정보 비노출**: approval_key, appkey/appsecret을 API 응답/로그/UI 어디에도
  노출하지 않는다. 기존 `KisTokenCache`의 `_log_hit`/`_log_miss` 로깅 패턴(토큰 값
  미포함)을 그대로 따른다.
- **기존 경로 무변경 원칙**: 이 작업 전체에서 `OrderManager`, `BrokerAdapter`
  (트레이딩 계좌), `ReconciliationService`, 기존 KIS WS/REST client 클래스의
  **공개 인터페이스는 절대 변경하지 않는다.** 필요한 모든 신규 기능은 별도
  클래스/함수로 추가한다.
- **`ops-scheduler` 무변경/무재배포**: 이 화면의 KIS Live WS 연결은 전적으로 `api`
  서비스 프로세스 안에서 생성·유지된다. `ops-scheduler` 컨테이너의 코드, 설정,
  환경변수, 배포 절차 중 어떤 것도 이번 작업으로 변경되지 않으며, `ops-scheduler`의
  재시작/재배포도 필요하지 않다. `ops-scheduler`가 담당하는 트레이딩 계좌(`KIS_APP_KEY`)
  및 공시 계좌(`KIS_LIVE_INFO_*`)의 기존 세션/스케줄 루프는 이번 작업과 완전히
  분리되어 영향을 받지 않는다.
- **장중 배포 주의**: Step 3(실제 KIS Live WS 연결이 시작되는 단계) 이후의 `api`
  서비스 배포는 기존 운영 원칙(`[BACKLOG] backlog.md`의 여러 항목에 반복되는 "장중
  작업 금지" 원칙)을 따라 **장 종료 후 배포, 다음 장중 검증**을 권장한다. Step 1, 2(stub/골격
  단계)는 실제 KIS 통신이 없으므로 이 제약에서 자유롭다.

## 9. 테스트 명령 후보

### Backend (pytest)

```bash
# Step 1 — schema/contract 단위 테스트
python -m pytest tests/api/test_realtime_quotes.py -v

# Step 3/4 — subscription manager 단위 테스트 (mock WS 서버 기반)
python -m pytest tests/brokers/koreainvestment/test_quote_subscription_manager.py -v

# 기존 KIS broker 테스트 회귀 확인 (변경하지 않은 기존 파일들)
python -m pytest tests/brokers/koreainvestment/ -v

# 전체 회귀 확인 (마지막 PR에서 1회)
python -m pytest tests/ -v --ignore=tests/smoke -W ignore::DeprecationWarning
```

### Admin UI (vitest)

```bash
# Step 6/7 — 신규 컴포넌트 테스트
npm run test:run -- RealtimeQuoteView

# 전체 회귀 확인 (Step 8 포함, 기존 테스트 영향 확인)
npm run test:run
```

### Live Read-only Smoke (Step 3 이후, 장 종료 후 1회 수동 실행 권장)

```bash
# 신규 계좌 자격증명으로 실제 KIS Live WS에 연결해 1개 종목 구독/해제만 확인
python -m pytest tests/smoke/test_realtime_quote_live_smoke.py -v -m smoke --timeout=30
```

> 위 smoke test 파일명은 가칭이며, `tests/smoke/test_kis_paper_smoke.py` 등 기존
> smoke test 컨벤션(`-m smoke` 마커, timeout 지정)을 따른다.

## 10. Rollback 전략

- **Step 1, 2**: 신규 파일/추가 코드만 존재하므로, 문제가 생기면 해당 파일을 삭제하고
  `Layout.tsx`/`App.tsx`의 추가된 라인만 되돌리면 된다. 기존 화면/API에 영향 없음.
- **Step 3, 4, 5**: `lifespan`에 추가한 `QuoteSubscriptionManager` 초기화 코드를
  feature flag(env, 예: `KIS_REALTIME_QUOTE_ENABLED=false`)로 감싸, 문제 발생 시
  **코드 롤백 없이 즉시 비활성화** 가능하게 한다. 비활성화 시 `GET
  /realtime-quotes/bootstrap`은 503(adapter 미설정과 동일한 패턴)을 반환하고, 신규
  계좌 WS 연결 자체가 시작되지 않는다.
- **Step 6, 7**: Admin UI 메뉴 항목을 숨기거나 라우트를 비활성화하는 것만으로 화면
  진입을 막을 수 있다(백엔드 API가 살아있어도 무해함 — read-only이므로).
- **Step 8**: `OrdersView.tsx`/`FillHistoryView.tsx`의 종목 컬럼 렌더링 변경만
  되돌리면 되는 단일 파일 단위 롤백.
- **공통 원칙**: 어떤 Step도 기존 주문/체결/정합성 코드 경로를 수정하지 않으므로,
  이 작업 전체를 롤백하더라도 **기존 트레이딩 기능에는 영향이 없다.** 이것이 이
  작업을 여러 개의 독립 PR로 쪼갠 핵심 이유이기도 하다 — 특정 Step에서 문제가
  발견되어도 이전 Step까지는 안전하게 유지된 채로 운영을 계속할 수 있다.
- DB migration이 없으므로(§7) migration rollback 절차는 해당 없음.

## 11. Phase 1에서 의도적으로 제외할 항목

`[DESIGN]_kis_realtime_quote_screen_ui_layout.md` §10과 `11_kis_realtime_quote_operations_screen.md`의
비범위를 실행 계획 관점에서 다시 정리한다.

- 차트(캔들/라인) 시각화
- 다중 종목 동시 화면 비교(2개 이상 종목을 나란히 배치하는 뷰)
- 종목 즐겨찾기/워치리스트의 서버 영속화(DB 저장) — 세션 동안만 메모리 유지
- 가격 도달 알림/급등락 알림 등 alert 인프라 연동
- 예상체결가/예상체결량(동시호가 전용 필드) 표시
- WebSocket/SSE relay 방식으로의 전환 — Phase 1은 **UI polling**만 구현
  (`11_...md` §5.5(c) 단계적 전환 계획에 따라 relay는 Phase 4 이후 별도 계획)
- 통합 채널(`H0UNCNT0`/`H0UNASP0`, KRX+NXT) 도입 — KRX 전용으로 확정됨
- 주문 화면으로의 단축 진입 동선(호가 클릭 시 주문창 연결 등)
- 모바일 전용 네이티브 제스처(스와이프 등)
- 이 화면을 위한 신규 alert/모니터링 대시보드 구축(`11_...md` §8 Phase 5 범위이며
  이번 계획은 Phase 1~3 상당 범위만 다룸)
