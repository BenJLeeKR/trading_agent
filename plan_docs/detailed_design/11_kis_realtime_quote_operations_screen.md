# KIS 실시간 현재가 조회 운영 화면 설계 v1

## 0. 문서 성격

이 문서는 Admin UI에 신규로 추가하는 "실시간 현재가 조회" 화면의 상세 설계다.
[`ENTERPRISE_TRADING_SYSTEM_DESIGN.md`](../ENTERPRISE_TRADING_SYSTEM_DESIGN.md) /
[`ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md`](../ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md)
어디에도 이 화면은 계획되어 있지 않았다 — **완전 신규 범위**이며, 사전 조사 결과
`[PRIORITY_MAP] remaining_work_priority_map.md` 섹션 16의 "Admin UI 추가 고도화는
보류" 원칙과 별개로 진행하기로 결정된 항목이다.

이 문서는 `05_koreainvestment_adapter_spec.md`, `10_broker_rate_limit_and_capacity_policy.md`와
같은 기존 KIS 관련 설계 문서를 대체하지 않는다. 기존 트레이딩 계좌/세션 정책은 그대로 두고,
이 화면 전용의 **완전히 분리된 계좌/앱키**를 사용하는 것을 전제로 한다.

## 1. 목적

- Admin UI의 "기본 운영" 메뉴 아래 별도 화면으로 "실시간 현재가 조회"를 추가한다.
- 기존 주문 제출, 체결 처리, 정합성(reconciliation) 기능은 전혀 건드리지 않는다.
- 1차 목표: 운영자가 선택한 종목의 **현재가, 등락, 체결 시각, 수신 상태, 연결 상태**를
  빠르게 확인할 수 있게 한다.
- 이 화면은 운영 편의 도구이며, 트레이딩 판단에 직접 사용되는 데이터 경로가 아니다.

## 2. 범위

### 2.1 Phase 1 범위 (이 문서가 다루는 범위)

- 조회 전용(read-only) 화면.
- 운영자가 종목을 선택해 실시간 체결가/호가를 구독하고 화면에서 확인.

### 2.2 명시적 비범위

다음은 이 화면의 범위에 포함하지 않는다.

- 주문 제출/취소/정정.
- 자동매매 판단(AI decision, signal 계산, regime 판단).
- Universe 편입/제외 로직.
- 이 화면에서 수신한 시세를 트레이딩 의사결정 파이프라인에 자동으로 공급하는 것.

이 화면이 다루는 유일한 "정책 설계"는 **수신 실패 시 REST fallback 또는 마지막 수신값
표시 정책**이다 (5.7 참고).

## 3. 사전 조사 요약 및 확정된 전제

구현 착수 전 여러 차례의 조사/검토를 거쳐 다음 전제가 확정되었다.

| 항목 | 결정 | 근거 |
|---|---|---|
| 실행 환경 | **Live 전용** (모의투자 미지원) | `169`/`172`/`178`/`179` KIS 문서의 "모의 TR_ID: 모의투자 미지원" 또는 KRX 전용 채널의 모의 지원 여부 확인 |
| 사용 계좌/앱키 | **기존 트레이딩 계좌/앱키(`KIS_APP_KEY`)와도, `KIS_LIVE_INFO_*`(공시/163 전용)와도 별개인 신규 Live 계좌 + 신규 appkey** | 세션(앱키당 1개)·REST RPS/WS 구독(계좌당 18RPS/41건) 스코프 분석 결과, 별도 계좌만이 기존 트레이딩/공시 세션과의 충돌·budget 공유 문제를 모두 해소함 |
| 데이터 전달 방식 | **실시간 스트리밍** (REST polling 배제) | 사용자 요구사항 명시 |
| TR 채널 | **KRX 전용으로 통일**: 체결가 `H0STCNT0`(172번 문서), 호가 `H0STASP0`(178번 문서) | 통합채널(`H0UNCNT0`/`H0UNASP0`, KRX+NXT)은 모의투자 미지원이며 신규 파서가 필요한 반면, KRX 전용 채널은 기존 `ws_parser.py`/`websocket_client.py`에 이미 파서가 구현되어 있어 재사용 가능 |

### 3.1 문서 간 상충 여부 확인

이 설계를 작성하면서 기존 문서/코드와 대조해 다음 상충 사항을 확인했다.

1. **`10_broker_rate_limit_and_capacity_policy.md` §12의 표가 현재 코드 상태와 불일치한다.**
   해당 표(228행)는 `WebSocket registrations | 합산 41건 | ❌ SubscriptionBudget 기본 100 (base.py)`로
   "41건 한도가 강제되지 않는다"고 명시하지만, 실제 코드(`adapter.py:85`)는 이미
   `SubscriptionBudget(max_subscriptions=41)`로 **명시적으로 41을 전달**하고 있다.
   `base.py:70`의 클래스 기본값 100은 `SubscriptionBudget` 자체의 안전 상한(safety ceiling)일
   뿐이며, `base.py:29-39` 클래스 docstring에도 "`KoreaInvestmentAdapter`가 41로 override한다"고
   명시되어 있다. **`10_...md` §12 표는 갱신이 필요한 stale 정보이며, 이 신규 화면 설계는
   "41건이 이미 코드로 강제된다"는 현재 상태를 기준으로 진행한다.** (`10_...md` 문서 자체의
   수정은 이 작업의 범위 밖이나, 별도로 갱신을 권고한다.)
2. **`KIS_LIVE_INFO_*` 자격증명은 이 화면에 사용하지 않는다.** 사전 조사 중 한때
   "LIVE_INFO_* 키 활용" 전제가 있었으나, 이후 검토(세션 preemption 위험, 계좌 단위
   budget 공유 위험)를 거쳐 **별도 계좌·앱키 사용으로 최종 결정**되었다. 이 문서의 모든
   설계는 후자 기준이다. 과거 대화/문서에 `LIVE_INFO_*` 활용을 전제한 문구가 남아 있다면
   이 문서가 최신 결정을 우선한다.
3. **`websocket_client.py`의 기존 채널 구성과 충돌하지 않는다.** `_OPTIONAL_CHANNELS =
   frozenset({"H0STCNT0", "H0STASP0", "H0STCNS0"})`(websocket_client.py:65)는 이미 이번에
   채택한 KRX 전용 채널과 동일하므로, 클라이언트/파서 재사용에 구조적 문제가 없다. 다만
   기존 인스턴스는 트레이딩 계좌 전용으로 생성되므로, 이 화면은 **같은 클래스의 별도
   인스턴스**(신규 계좌 자격증명으로 생성)를 사용해야 한다. 기존 인스턴스를 공유하거나
   재사용하지 않는다.

## 4. Backend 설계

### 4.1 Approval Key 재사용/발급 정책

- 이 화면 전용 신규 계좌의 appkey/appsecret으로 `/oauth2/Approval`을 호출해 approval_key를
  발급한다 (KIS 문서 `002_실시간_(웹소켓)_접속키_발급.md`).
- 발급된 approval_key는 `KisTokenCache`(`token_cache.py`)를 통해 파일 캐시한다.
  `build_live_approval_key_cache_config()`를 재사용하되, `fingerprint_input`이
  `app_key`/`api_secret` 기반이므로 신규 계좌의 자격증명을 넣으면 기존 캐시 파일
  (`kis_live_oauth_token.json` 등)과 자동으로 분리된 fingerprint를 갖는다 — **신규
  `CachePurpose`를 추가할 필요는 없다.**
- 유효기간 24시간, 만료 5분 전 조기 갱신 정책은 기존 `KisMarketStateClient`와 동일하게
  따른다 (`_APPROVAL_KEY_EXPIRY=86400`, `_APPROVAL_KEY_REFRESH_MARGIN=300` 패턴 재사용).
- approval_key는 세션 연결 시 1회만 사용되므로, 재연결 시에도 **캐시에서 유효한 키를
  우선 재사용**하고, 캐시 미스(만료/파일 없음)일 때만 재발급 REST 호출을 수행한다.
  재연결 폭주 시 매번 재발급을 시도하지 않도록 해야 한다 (approval key 발급도 1RPS
  제한 대상).

### 4.2 WebSocket Session 1개 원칙

- 이 화면 전용 계좌의 appkey는 **오직 이 화면의 단일 `KISWebSocketClient` 인스턴스만
  소유**한다. 같은 appkey로 두 번째 연결을 여는 코드 경로를 만들지 않는다.
- FastAPI 프로세스(`api` 컨테이너)의 `lifespan` startup에서 1회 생성하고, 프로세스
  생명주기 동안 유지한다.
- **uvicorn은 `--workers 1`을 유지**해야 한다. 워커가 여러 개면 각 워커가 독립적으로
  이 화면 전용 세션을 열려고 시도해 "앱키당 1세션" 제약을 위반한다.

### 4.3 구독 종목 수 제한

> **2026-07-08 KIS 공식 문서/웹페이지 재확인 결과 반영**: 41건 한도는 appkey/계좌
> 기준 **국내/해외/파생 전체 실시간 채널 합산**이며, **체결가+호가를 같은 종목에
> 모두 구독하면 2건으로 계산된다.** 이 화면은 종목당 체결가(`H0STCNT0`)와
> 호가(`H0STASP0`)를 **둘 다** 구독하므로, KIS 공식 한도(41건) 기준으로는
> 최대 약 20종목(41 ÷ 2, 소수점 버림)까지 동시 조회가 가능하다.

> **2026-07-09 운영 안정성 조정**: 위 KIS 공식 한도(41건)는 그대로이지만, 이 화면
> 전용 구독 예산은 **자체적으로 30건(≈ 15종목)으로 낮춰 운영**한다. 다른 실시간
> 채널이 향후 같은 appkey pool을 공유하게 될 가능성, approval_key 재발급/재연결
> 구간의 순간적 중복 등록 등을 감안한 안전 마진(11건)을 미리 확보하기 위함이다.
> 이하 "41건" 서술은 **KIS 서버 측 공식 상한**을 가리키고, 이 화면이 실제로 강제하는
> `SubscriptionBudget`/API 응답값은 모두 **30건(15종목)** 기준이다.

- `SubscriptionBudget(max_subscriptions=30)`을 명시적으로 생성한다 — KIS 공식 상한
  (41, 기존 `KoreaInvestmentAdapter`가 쓰는 값과 동일 `adapter.py:85` 패턴)보다 낮은
  자체 안전 한도다. 이 budget은 **"등록 건수" 단위**로 소비되므로, 종목 1개를 구독
  추가할 때마다 체결가+호가 2건을 함께 등록/해제해 budget에서 2를 소비한다(§5.2
  구독 API도 이 2건 단위 원자적 등록/해제를 전제로 설계한다).
- 이 화면은 critical/optional 구분이 필요 없다 — 모든 구독이 "화면에 표시 중인 종목"이므로
  전량 optional로 취급하고, 화면에서 사라진 종목은 즉시 구독 해제(`tr_type=2`, 체결가+호가
  2건 모두 해제)한다.
- 여러 admin_ui 브라우저 세션이 같은 종목을 동시에 볼 수 있으므로, 종목별로 **참조
  카운트(reference count)**를 두어 마지막 뷰어가 사라질 때만 실제 KIS 구독(2건)을 해제한다.
  이를 통해 30건 한도를 종목 단위(2건씩)로만 소모하고 뷰어 수와 무관하게 유지한다.
- **국내/해외/파생 전체 합산이라는 점도 유의**: 이 화면은 국내주식(KRX)만 다루지만,
  같은 앱키로 향후 해외/파생 실시간 채널을 추가로 구독하는 기능이 생기면 그 등록
  건수도 같은 KIS 공식 41건 pool을 공유한다(우리 자체 30건 한도는 그 41건 pool 안에서
  더 보수적으로 예약해 쓰는 것). 현재는 이 화면이 이 앱키의 유일한 구독 주체이므로
  즉시 문제되지 않으나, 향후 확장 시 반드시 재확인해야 한다.

### 4.4 Subscription Budget과 Broker Capacity 관측값 연결

- 기존 `GET /broker-capacity`(`routes/broker_capacity.py`)는 **트레이딩 계좌의** budget만
  노출한다. 이 화면 전용 계좌는 별개이므로, 기존 엔드포인트에 억지로 합치지 않고
  **별도 필드 또는 별도 read-only 엔드포인트**로 노출한다 (5.3 참고).
- 노출 항목: 활성 구독 종목 수, 30건 대비 사용률, 세션 연결 상태, 마지막 approval_key
  발급/갱신 시각.

### 4.5 실시간 Quote Snapshot 저장 여부

- **원칙: 메모리 전용(in-memory only), DB persistence 없음.**
- 근거:
  - 이 화면은 트레이딩 판단에 쓰이지 않는 운영 편의 도구이므로 감사(audit)/재현성
    요구사항이 없다 (`03_data_model_erd.md`의 "감사 및 재현성 저장" 대상이 아님).
  - 초 단위로 갱신되는 tick성 데이터를 DB에 영속화하면 쓰기 부하만 늘고 실익이 없다.
  - 이미 존재하는 `KISRestClient`의 quote TTL 캐시(`_get_quote_from_cache`/
    `_set_quote_cache`, `rest_client.py:2070-2084`)와 같은 철학 — quote는 "최신값만
    중요한" 데이터로 취급한다.
- 저장 위치: 프로세스 메모리 내 `dict[symbol -> LatestQuoteSnapshot]` (API 프로세스
  `app.state`에 보관). 프로세스 재시작 시 초기화되는 것을 허용한다.
- **DB persistence로 전환할 기준** (Phase 1 이후 재검토 트리거):
  - 운영자가 "특정 시점 시세를 나중에 다시 봐야 한다"는 요구를 제기하는 경우.
  - 수신 데이터를 이후 다른 분석 파이프라인에 공식적으로 편입하기로 결정하는 경우
    (이 경우 §2.2 비범위 항목을 재정의해야 함).

### 4.6 Disconnect / Reconnect / Gap Fill 정책

- 재연결 backoff는 기존 `KISWebSocketClient._handle_disconnect()`(1s → 최대 60s,
  무한 재시도) 로직을 그대로 재사용한다.
- **Gap fill은 이 화면에서 수행하지 않는다.** 기존 `detect_gap()`/`get_last_continuum()`은
  주문 이벤트(`H0STCNI0`)처럼 "놓치면 안 되는" critical 채널을 위한 장치이며, 시세
  tick은 놓쳐도 다음 tick으로 자연 복구되는 데이터이므로 gap fill의 실익이 없다.
  연결이 끊겼던 구간의 시세는 유실된 것으로 간주하고, 재연결 후 최신 tick부터 다시
  받는다.
- 재연결 중에는 화면에 "연결 끊김 / 재연결 시도 중" 상태를 노출하고, 마지막으로
  수신한 값은 "최종 수신값(stale)"으로 표시를 유지한다 (5.7, 6번 참고).

### 4.7 REST Quote Fallback 정책

- **REST fallback은 "장애 시 임시 대체" 용도로만 사용하고, 정상 시나리오의 주 경로로
  쓰지 않는다** (사용자가 REST polling을 주 경로에서 배제하기로 결정했으므로).
- Fallback 조건: WebSocket 세션이 끊긴 상태가 N초(예: 10초) 이상 지속되고, 화면에
  현재 표시 중인 종목이 있는 경우에 한해, 기존 `KISRestClient.get_quote()`
  (이 화면 전용 계좌가 아닌 **REST는 기존 트레이딩 계좌 client를 재사용해도 무방** —
  REST 현재가 조회는 계좌 격리가 필요한 이유가 없는 단순 조회이므로, 신규 계좌용
  REST client를 별도로 만들지 판단은 구현 단계에서 확정)를 호출해 1회성으로 보정한다.
- Fallback으로 얻은 값은 화면에 "REST 보정값" 배지와 함께 표시해, WebSocket 실시간
  값과 혼동되지 않게 한다.

## 5. API 설계

이 화면 전용 API는 기존 `api/routes/` 패턴(예: `broker_capacity.py`의 "adapter
미설정 시 503" 패턴)을 따른다. 라우트 파일 후보: `src/agent_trading/api/routes/realtime_quotes.py`.

### 5.1 화면 초기 로딩용 endpoint

```
GET /realtime-quotes/bootstrap
```

- 응답: 이 화면 전용 세션의 연결 상태, 현재 구독 목록(다른 admin_ui 세션이 이미
  보고 있는 종목 포함), 30건 대비 사용률, 환경 라벨(`live`/`paper` — 항상 `live`
  고정이지만 화면에 재확인용으로 노출).

### 5.2 구독 요청/해제 endpoint

```
POST   /realtime-quotes/subscriptions     { "symbols": ["005930", "000660"] }
DELETE /realtime-quotes/subscriptions     { "symbols": ["005930"] }
```

- 참조 카운트 증감만 수행하고, 실제 KIS 구독 등록/해제는 참조 카운트가 0에서 1로
  또는 1에서 0으로 바뀔 때만 트리거한다. 이때 **체결가+호가 2건을 원자적으로 함께
  등록/해제**한다 — 한 채널만 구독하고 다른 채널은 실패하는 부분 상태를 만들지 않는다.
- 30건 초과 요청은 422/409 등으로 명시적으로 거부하고, 어떤 종목이 원인인지 응답에
  포함한다 (자동 evict 없음 — 이 화면은 critical/optional 구분이 없으므로 임의로
  다른 사용자의 구독을 evict하면 안 된다). **종목 1개당 2건을 소비**하므로, 잔여
  budget이 1건만 남은 상태에서는 신규 종목 추가가 거부되어야 한다(잔여 30건 기준이
  아니라 잔여 2건 이상 확보 가능 여부로 판단).

### 5.3 현재 구독 상태 조회 endpoint

```
GET /realtime-quotes/subscriptions
```

- 현재 활성 구독 목록, 종목별 참조 카운트, 30건 대비 사용량, 세션 연결 상태,
  마지막 approval_key 갱신 시각을 반환한다 (4.4의 관측값).

### 5.4 최신 quote snapshot 조회 endpoint

```
GET /realtime-quotes/snapshot?symbols=005930,000660
```

- 4.5의 메모리 내 최신 snapshot을 반환한다. WebSocket/SSE relay 도입 전까지는
  이 endpoint가 화면의 유일한 데이터 획득 경로가 된다 (5.5의 Phase 1 polling안).

### 5.5 Admin UI ↔ 백엔드 실시간 전달 방식

세 가지 후보를 검토했다.

| 후보 | 설명 | 장점 | 단점 |
|---|---|---|---|
| a. UI polling | admin_ui가 `GET /realtime-quotes/snapshot`을 1~3초 간격으로 호출 | 구현 단순, 기존 패턴(`Layout.tsx` 헬스체크 polling)과 동일, 인증/에러 처리가 기존 REST 패턴 그대로 재사용 | 진짜 실시간(sub-second)은 아님, 종목 수가 많으면 응답 payload 증가 |
| b. FastAPI WebSocket/SSE relay | 백엔드가 KIS WS를 구독해 브라우저로 실시간 중계 | tick 단위 실시간성 확보 | `@app.websocket` 선례 없음(신규 구현), fan-out/backpressure 설계 필요, 인증 처리 신규 |
| c. 초기 polling → 이후 relay | a로 시작해 b로 전환 | 리스크를 단계적으로 분산, Phase 1 착수 속도 확보 | 두 번 구현하는 비용 발생 |

**Phase 1 권장안: (c) — 우선 (a) UI polling으로 시작하고, Phase 4에서 (b) relay로
전환한다.**

> **✅ 2026-07-09 Phase 4 완료 — transport는 SSE(Server-Sent Events)로 최종 결정**.
> WebSocket이 아니라 SSE를 선택한 이유:
> 1. 구독/해제/종목검색 등 client→server 방향 명령은 이미 기존 REST endpoint
>    (5.2~5.4)가 전부 처리한다. Phase 4가 새로 필요로 하는 건 **server→client
>    단방향 push뿐**이라, 양방향 프로토콜(WS)을 새로 얹을 이유가 없다.
> 2. 이 화면은 "선택된 종목 1개"만 본다(§2.2, 화면 UX 원칙). 종목 전환은
>    "기존 스트림을 닫고 새 스트림을 연다"로 충분히 표현되며, WS의 멀티플렉싱
>    (한 연결에서 여러 채널 구독)이 주는 이점이 크지 않다.
> 3. 브라우저 `EventSource`는 재연결을 자동으로 처리해주지만 커스텀
>    `Authorization` 헤더를 못 보내는 제약이 있어, `fetch` + `ReadableStream`으로
>    직접 파싱하는 방식을 택했다(재연결 로직은 클라이언트에서 자체 구현,
>    `admin_ui/src/api/client.ts`의 `subscribeRealtimeQuoteStream()`). 이 방식이면
>    기존 Bearer 토큰 인증을 그대로 재사용할 수 있어, WS 핸드셰이크용 별도
>    인증 방식을 새로 설계할 필요가 없다.
> 4. FastAPI `StreamingResponse`(SSE)는 이 코드베이스에 이미 존재하는 REST
>    라우팅 스택 위에 자연스럽게 얹히고, `@app.websocket`처럼 완전히 별도인
>    연결 관리 레이어가 필요 없다.
>
> **구현 구조** (`realtime_quote_broadcaster.py`, `routes/realtime_quotes.py::stream_quote`):
> - `QuoteBroadcaster`가 `app.state`에 1개 존재하는 app-process 내부 fan-out
>   계층이다. `RealtimeQuoteSource`(`KisRealtimeQuoteSource`/`InMemoryMockQuoteSource`)
>   는 여전히 pull 기반 truth로 남고(`get_snapshots()` 변경 없음, 기존
>   REST bootstrap/subscribe/snapshot endpoint도 그대로 동작) — Phase 1-3
>   contract는 깨지 않았다.
> - **true push**: `KisRealtimeQuoteSource`에 `add_listener()`를 추가해, WS
>   tick으로 상태가 갱신될 때마다(`_apply_realtime_frame`) 콜백으로 즉시
>   broadcaster에 알린다. Polling 없이 tick 단위로 그대로 전달된다.
> - **fallback poll**: `InMemoryMockQuoteSource`는 pull 전용(읽을 때마다 생성)이라
>   push 이벤트가 없다 — broadcaster가 `add_listener` 미지원을 duck-typing으로
>   감지하면 짧은 주기(기본 1초)로 대신 폴링해 같은 이벤트 스트림으로
>   흘려보낸다. 구독자(SSE route)는 실제 push인지 poll-fallback인지 알 필요가
>   없다 — 이게 "완전 연결 실패 시에도 최소한의 degraded fallback을 남긴다"는
>   제약을 만족하는 지점이다.
> - **heartbeat**: 종목별로 별도 주기(기본 5초)의 상태-only 이벤트를 추가로
>   보내, 데이터가 없어도 연결이 죽지 않은 것처럼 보이지 않게 하고 클라이언트가
>   staleness를 tick 주기와 무관하게 판단할 수 있게 한다.
> - **상태 모델**: `connected`/`reconnecting`/`disconnected`/`stale`/`no_data_yet`
>   5가지는 `QuoteBroadcaster._status_for()`가 계산해 매 이벤트에 실어 보낸다.
>   나머지 `degraded`는 프론트가 이 값 + 스트림 자체의 전송 오류(재연결 시도 중)를
>   종합해 표시하는 UI 레벨 상태로 유지했다(기존 배너 로직과 동일 원칙).
> - **reconnect**: `QuoteBroadcaster.stream()`은 새 구독이 열릴 때마다 캐시된
>   최신 snapshot을 즉시 1건 내려준다 — 재접속(새 SSE 연결) 시 다음 tick까지
>   기다리지 않고 바로 최신 상태로 따라잡는다. 클라이언트 쪽도 전송 실패 시
>   지수 백오프(1s→최대 10s)로 자체 재연결한다.
> - **degraded 시 REST polling fallback**: 클라이언트의 SSE 연결 자체가
>   실패/재시도 중이면(`onTransportError`) 기존 `GET /realtime-quotes/snapshot`
>   3초 polling 경로가 그대로 다시 켜진다 — Phase 1-3 폴링 코드를 제거하지 않고
>   "완전 연결 실패 시 fallback"으로 남겨뒀다.
> - **single-process 가정 유지**: `QuoteBroadcaster`는 `app.state`의 in-memory
>   `asyncio.Queue`로만 fan-out한다. multi-worker/여러 `api` 프로세스로
>   확장하려면 Redis 등 외부 pub/sub이 필요하며, 이번 범위에는 포함하지 않았다
>   (아래 "남아있는 제한/후속 과제" 참고).
>
> **파일**: `services/realtime_quote_broadcaster.py`(신규), `services/kis_realtime_quote_source.py`
> (`add_listener`/`remove_listener`/`_notify_listeners` 추가), `api/routes/realtime_quotes.py`
> (`GET /realtime-quotes/stream` 신규), `api/deps.py`/`api/app.py`(broadcaster DI/lifespan
> 등록), `admin_ui/src/api/client.ts`(`subscribeRealtimeQuoteStream`), `RealtimeQuoteView.tsx`
> (push 우선 + polling fallback으로 전환).
>
> **남아있는 제한**:
> - single-process 가정 그대로 — `uvicorn --workers 1` 필요(기존 "1 appkey = 1
>   WS 세션" 제약과 동일 이유로 이미 강제되고 있었음).
> - `KIS_REALTIME_QUOTE_*`/`KIS_LIVE_INFO_*` credential 분리는 이번에도 그대로
>   유지했다 — 통합 여부는 여전히 후속 검토 대상(아래 "Credential 분리/통합
>   판단 메모" 참고, 이제는 "Phase 4 완료 이후" 시점에서 재평가).
>
> **후속 과제**:
> 1. Credential/appkey 통합 재검토 — 이제 push relay/WS ownership 구조가
>    안정화됐으니, "Credential 분리/통합 판단 메모"의 재평가 트리거 조건을 실제로
>    다시 점검.
> 2. Multi-worker/cross-process fan-out 필요성 판단 — 지금은 단일 뷰어(운영자
>    1인) 가정이 유지되는 한 문제없음. 여러 운영자가 동시에 다른 종목을 보게
>    되면 Redis pub/sub 등 외부 broadcaster로의 이전이 필요한지 재검토.
> 3. Session ownership 정리 — 지금은 `api` 프로세스가 WS 연결과 broadcaster를
>    함께 소유한다. 만약 향후 WS 연결 자체를 별도 프로세스/서비스로 분리하게
>    되면(예: 여러 `api` 워커가 하나의 WS 세션을 공유해야 하는 시점), 그 경계를
>    다시 설계해야 한다.
>
> **✅ 2026-07-09 장마감 후 리소스 비효율 리뷰 → 변경 감지(dedup) 적용**.
> 실측 결과 장 마감(15:30) 후에도 KIS가 호가(`H0STASP0`)/체결(`H0STCNT0`) 프레임을
> 마지막 값 그대로 반복 전송하는 것이 확인됐다 — `updated_at`은 계속 갱신되지만
> 실제 값(가격/호가/잔량)은 완전히 동일했다. 기존에는 프레임을 받을 때마다
> 내용이 바뀌었는지 확인 없이 매번 `_notify_listeners()`를 호출해 SSE 직렬화·
> 전송·브라우저 리렌더가 불필요하게 반복됐다.
>
> - **`KisRealtimeQuoteSource`에 종목별 "마지막으로 notify한 내용의 signature"
>   캐시(`_last_notified_signature`)를 추가**. 매 프레임마다 `updated_at`을 제외한
>   의미 있는 필드들(가격/변동률/누적거래량/호가 10단계/최근 체결 tick 등)로
>   signature를 만들어 직전 signature와 다를 때만 `_notify_listeners()`를 호출한다.
>   구독 직후 첫 프레임은 비교 대상이 없어 항상 다르게 판정되므로, "장중엔
>   미구독 → 장 종료 후 구독" 시나리오에서도 최소 1회는 반드시 화면에 값이
>   표시된다. `unsubscribe()` 시 해당 종목의 캐시도 함께 제거해, 재구독 시 다시
>   최소 1회 notify가 보장된다.
> - **`_SymbolState.apply_trade()`도 함께 수정**: 기존에는 체결 프레임을 받을
>   때마다 내용이 동일하더라도 `recent_trades` 이력에 무조건 새 tick을
>   append해, "체결 히스토리"가 재전송된 동일 프레임으로 계속 부풀려지는
>   문제가 있었다. 이제는 직전 tick과 `trade_time`/가격/체결량이 완전히 같으면
>   재전송으로 간주해 이력에 추가하지 않는다 — 이 수정이 없으면 히스토리 길이가
>   매 프레임마다 바뀌어 signature 비교 자체가 무력화된다.
> - REST polling 경로(5.3, 5.4)와 초기 스냅샷 로딩은 이 변경의 영향을 받지
>   않는다 — `to_snapshot()`이 반환하는 값 자체는 그대로이며, 바뀐 건 push
>   listener에게 "언제 다시 알릴지"뿐이다.
>
> **파일**: `services/kis_realtime_quote_source.py`(`_last_notified_signature`,
> `_content_signature()`, `_apply_realtime_frame()`/`unsubscribe()` 수정,
> `_SymbolState.apply_trade()` 수정), `tests/services/test_kis_realtime_quote_source.py`
> (`TestPushListenerDedup` 4개 테스트 추가).

권장 근거:

- 이 화면은 "운영자가 몇 초 간격으로 확인하는" 운영 도구이지, 밀리초 단위 트레이딩
  판단에 쓰이는 경로가 아니다 (§1, §2.2). polling만으로 1차 목표를 충분히 달성한다.
- `@app.websocket` 엔드포인트가 이 코드베이스에 선례가 없어, relay 구현에는 fan-out
  broadcaster·backpressure·연결 인증 등 신규 설계 요소가 많다 (4.2, 4.3 참고). 이를
  Phase 1 스코프에 넣으면 "조회 전용 화면"이라는 단순한 목표 대비 구현 리스크가
  커진다.
- polling 경로(5.3, 5.4 endpoint)는 어차피 relay 방식에서도 "초기 상태 로딩/재연결
  후 스냅샷 동기화" 용도로 그대로 재사용되므로 버려지는 작업이 아니다.
- backend의 KIS WebSocket 연결 자체(4.1~4.6)는 polling 단계에서도 이미 필요하다 —
  즉 "실시간 스트리밍 수신"과 "브라우저로의 전달 방식"은 분리된 문제이며, 이번
  Phase 1은 전자만 실시간으로 하고 후자는 polling으로 근사한다.

## 6. Admin UI 설계

### 6.1 메뉴/라우트

- 메뉴명(제안): **"실시간 현재가"**
- 위치: "기본 운영" 섹션 (`Layout.tsx`의 `navSections` 배열, 기존 "기본 운영" 그룹에 추가)
- 라우트: `/operations/realtime-quotes`
- 아이콘(제안): `lucide-react`의 `LineChart` 또는 `Activity`

### 6.2 화면 구성

- **종목 입력/선택**: 종목코드 직접 입력 또는 기존 instrument master 검색 컴포넌트 재사용.
- **구독 목록**: 현재 화면에서 구독 중인 종목 리스트, 종목별 해제 버튼.
- **현재가 카드/테이블**: 종목코드, 현재가, 전일 대비/등락률, 누적 거래량, 체결 시각.
- **연결 상태**: 이 화면 전용 KIS WS 세션의 연결/재연결/끊김 상태 배지.
- **마지막 수신 시각**: 종목별로 마지막 tick을 받은 시각 — polling 방식이므로
  "화면이 최신 데이터를 받았는가"와 "그 데이터가 실제로 언제 체결된 것인가"를
  구분해 표시한다.
- **오류/재연결 상태**: 재연결 backoff 진행 중 여부, REST fallback 사용 중 여부(4.7)를
  명확히 배지로 표시.
- **구독 한도 표시**: 30건 대비 현재 사용량(예: "12 / 30 구독 중") — 5.3 endpoint 값을
  그대로 노출.

### 6.3 환경 혼동 방지

- 이 화면은 **항상 Live 전용**이지만, 트레이딩 계좌 화면들과 나란히 있을 때 운영자가
  "이 시세가 paper 환경 값인가 live 값인가" 혼동할 수 있다. 화면 상단에 고정
  배지로 `LIVE` 환경임을 항상 표시한다 (다른 화면의 paper/live 표시 컨벤션이 있다면
  그것을 재사용).
- 이 화면 전용 계좌가 트레이딩 계좌와 다르다는 점도 툴팁/안내 문구로 노출해,
  운영자가 "이 화면에서 보는 계좌가 실제 매매 계좌와 다르다"는 것을 인지하게 한다.

## 7. 안전장치

- **read-only 명시**: API 응답 스키마와 UI 화면 모두에 이 화면이 조회 전용임을
  명시한다(예: API 응답에 `"readonly": true` 메타 필드, UI 화면 헤더에 "조회 전용"
  라벨).
- **주문 제출과 연결 금지**: 이 화면 전용 계좌/appkey는 주문 제출 API 경로
  (`BrokerAdapter.submit_order` 등)와 **어떤 코드 경로로도 연결하지 않는다**. 이
  계좌를 위한 어댑터 인스턴스는 quote/orderbook 구독 메서드만 노출하도록 제한한다
  (주문 관련 메서드가 존재하는 `KoreaInvestmentAdapter` 전체를 재사용하지 말고,
  필요한 최소 기능만 노출하는 wrapper를 구현 단계에서 검토).
- **Rate limit / 구독 한도 준수**: 4.3의 30건 자체 상한(KIS 공식 상한 41건보다 낮음)을
  코드로 강제(§10.4.3 언급된 `SubscriptionBudget(max_subscriptions=30)`)하고, 초과
  요청은 API 레벨에서 거부한다
  (5.2).
- **민감정보 비노출**: approval_key, appkey/appsecret은 API 응답/로그/UI 어디에도
  노출하지 않는다. `KisTokenCache`의 기존 로깅 패턴(`_log_hit`/`_log_miss`,
  `token_cache.py:714-731`)이 토큰 값 자체를 로그에 남기지 않는 것을 그대로 따른다.

## 8. 단계별 구현 계획

- **Phase 1**: 이 설계 문서, API contract 확정, UI mock data 기반 화면 뼈대. ✅ 완료
- **Phase 2**: Backend quote subscription manager — 이 화면 전용 `KISWebSocketClient`
  인스턴스, 참조 카운트 기반 구독 관리, 메모리 snapshot 저장(4.1~4.6, 5.1~5.4). ✅ 완료
  (단, Step 4 REST Fallback 세부 항목은 미구현 — `[PRIORITY_MAP]` #19 참고)
- **Phase 3**: Admin UI polling 화면 — 6.1~6.3 화면을 5.5(a) polling 방식으로 연결. ✅ 완료
- **Phase 4**: WebSocket/SSE relay 검토 및 전환 — 5.5(b) 도입, fan-out broadcaster 설계.
  ✅ **완료 (2026-07-09)** — SSE 채택, `QuoteBroadcaster` fan-out 계층 추가, push 우선+
  REST polling degraded fallback. 상세는 §5.5 상단 블록 참고.
- **Phase 5**: 운영 관측/alert 연동 — 세션 끊김 장기화, 30건 근접, approval_key
  갱신 실패 등에 대한 알림을 기존 운영 alert 채널에 연동. 🔲 미착수(다음 후보)

각 Phase는 이전 Phase 완료 후 별도 승인을 거쳐 착수한다. Phase 4는 Phase 3 운영
경험을 바탕으로 실시간성이 실제로 부족한지 재검토를 거쳐 착수·완료했다.

## 9. 테스트 계획

- **Unit test**: 참조 카운트 기반 구독/해제 로직, 30건 초과 시 거부 로직, snapshot
  갱신/staleness 판정 로직.
- **API contract test**: 5.1~5.4 endpoint의 요청/응답 스키마, adapter 미설정 시
  503 처리(`broker_capacity.py` 패턴과 동일 검증).
- **Admin UI rendering test**: 연결 상태 배지, 구독 한도 표시, REST fallback 배지
  등 상태 전이별 렌더링 테스트 (mock data 기반, 기존 admin_ui 테스트 패턴 준용).
- **KIS mock WebSocket test**: 기존 `ws_parser.py`/`websocket_client.py` 테스트
  스위트와 동일한 방식으로, mock WS 서버를 통해 구독 성공/실패, 재연결, 30건
  초과 시나리오를 검증.
- **Live read-only smoke test**: 신규 계좌 자격증명으로 실제 KIS Live WS에 연결해
  1개 종목을 짧게 구독/해제하는 최소 smoke test. 기존
  `logs/trigger_proxy_attribution_smoke_2026-07-02.log`류의 운영 smoke test와
  동일한 성격으로, CI 상시 실행이 아닌 수동/저빈도 실행 대상으로 분류한다.

## Credential 분리/통합 판단 메모

### 현재 판단
- 현재는 KIS_REALTIME_QUOTE_*와 KIS_LIVE_INFO_*를 분리 유지한다.
- **2026-07-09 Phase 4(push relay) 완료 시점에도 이 결정은 그대로 유지했다** —
  Phase 4 작업 범위에서 credential 통합은 명시적으로 제외됐다(사용자 지시).
  아래 재평가는 이제부터 후속 검토 대상이다.

### 지금 분리 유지가 합리적인 이유
- 핵심 쟁점은 ops-scheduler와의 단순 충돌보다 WebSocket session ownership이다.
- KIS_LIVE_INFO_*는 단순 REST 조회용 credential이 아니라 이미 장운영정보(163) WebSocket을 소유한다.
- 따라서 지금 합치면 단순 appkey 재사용이 아니라 아래 책임을 다시 설계해야 한다.
  - approval key 발급/재발급
  - reconnect 정책
  - registration budget 관리
  - 장애 격리와 원인 분리
- 현재 구현은 pi 내부 전용 quote source 기준으로 안정화되어 있어,
  문제 발생 시 현재가 경로만 독립적으로 degraded/fallback 처리하기 쉽다.

### 그럼에도 통합을 후속 검토해야 하는 이유
- 현재 현재가 화면은 단일 종목 중심이므로, 초기 설계 당시 예상했던 다종목 fan-out 압력은 아직 작다.
- 별도 계좌/appkey 유지에는 실제 운영·행정 비용이 든다.
- 거래 없는 별도 계좌/appkey의 장기 유지 보장을 시스템이 줄 수 없으므로,
  이는 기술 외부 이슈가 아니라 실제 아키텍처 입력값으로 취급해야 한다.
- **Phase 4에서 push relay/WS ownership 구조(`QuoteBroadcaster`) 정리가 이제
  완료됐으므로**, KIS_REALTIME_QUOTE_*와 KIS_LIVE_INFO_*를 단일 market-data
  credential로 통합할 수 있는지는 지금부터가 실제 재검토 시점이다. 다만 이번
  Phase 4 작업에서는 통합 자체를 진행하지 않았다(범위 제외, 사용자 지시) — 후속
  과제로 남긴다.
