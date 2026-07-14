# KIS 실시간 현재가 조회 운영 화면 설계 v1

## 0. 문서 성격

이 문서는 Admin UI에 신규로 추가하는 "실시간 현재가 조회" 화면의 상세 설계다.
[`ENTERPRISE_TRADING_SYSTEM_DESIGN.md`](../ENTERPRISE_TRADING_SYSTEM_DESIGN.md) /
[`ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md`](../ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md)
어디에도 이 화면은 계획되어 있지 않았다 — **완전 신규 범위**이며, 사전 조사 결과
`[PRIORITY_MAP] remaining_work_priority_map.md` 섹션 16의 "Admin UI 추가 고도화는
보류" 원칙과 별개로 진행하기로 결정된 항목이다.

이 문서는 `05_koreainvestment_adapter_spec.md`, `10_broker_rate_limit_and_capacity_policy.md`와
같은 기존 KIS 관련 설계 문서를 대체하지 않는다. 기존 트레이딩 계좌/세션 정책은 그대로 둔다.

> **⚠️ 2026-07-10 갱신**: 이 문서(§4~§9)는 애초에 "트레이딩 계좌와도 공시/076 계좌와도
> 완전히 분리된 신규 전용 계좌/앱키(`KIS_REALTIME_QUOTE_*`)"를 전제로 작성됐다. 이는
> 2026-07-08 초기 설계 당시의 결정이며, **2026-07-10에 credential 통합 구현으로
> 대체되었다** — `ops-scheduler`의 163 WS 의존 제거로 별도 계좌를 유지할 근거(WS
> 세션 소유권 충돌)가 사라져, 현재는 공시/076 계좌와 동일한 `KIS_LIVE_INFO_*`가
> 이 화면의 authoritative credential이다(신규 전용 계좌는 더 이상 쓰지 않음).
> 트레이딩 계좌(`KIS_APP_KEY`)와 분리되어 있다는 원칙만 그대로 유지된다. 상세는
> "Credential 분리/통합 판단 메모"의 "✅ 2026-07-10 통합 구현 상세" 참고.

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

> **⚠️ 아래 "사용 계좌/앱키" 행은 2026-07-08 초기 설계 당시 결정이며, 2026-07-10에
> credential 통합 구현으로 대체되었다.** 163 WS 의존이 `ops-scheduler`에서
> 제거되면서 이 화면이 해당 appkey의 유일한 WebSocket 소비자가 됐고, 그 결과
> **현재 authoritative credential은 `KIS_LIVE_INFO_*`**다(`KIS_REALTIME_QUOTE_*`는
> deprecated fallback으로만 코드에 남아 있음). 상세는 아래 "Credential 분리/통합
> 판단 메모"의 "✅ 2026-07-10 통합 구현 상세" 참고 — 이 표의 다른 행(실행 환경/
> 데이터 전달 방식/TR 채널)은 지금도 유효하다.

| 항목 | 결정 | 근거 |
|---|---|---|
| 실행 환경 | **Live 전용** (모의투자 미지원) | `169`/`172`/`178`/`179` KIS 문서의 "모의 TR_ID: 모의투자 미지원" 또는 KRX 전용 채널의 모의 지원 여부 확인 |
| 사용 계좌/앱키 | ~~기존 트레이딩 계좌/앱키(`KIS_APP_KEY`)와도, `KIS_LIVE_INFO_*`(공시/163 전용)와도 별개인 신규 Live 계좌 + 신규 appkey~~ **[2026-07-08 초기 결정 — 2026-07-10 통합 구현으로 대체됨] 현재는 `KIS_LIVE_INFO_*`(공시/076 계좌와 동일 credential)를 그대로 사용한다.** | *(당시 근거, 현재는 무효)* 세션(앱키당 1개)·REST RPS/WS 구독(계좌당 18RPS/41건) 스코프 분석 결과, 별도 계좌만이 기존 트레이딩/공시 세션과의 충돌·budget 공유 문제를 모두 해소함 → *(현재 근거)* `ops-scheduler`의 163 WS 제거로 해당 appkey의 WS 세션 소유 프로세스가 `api` 하나만 남아, 별도 계좌 없이도 세션 충돌 문제가 해소됨 |
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
2. **[2026-07-08 초기 설계 당시 판단 — 2026-07-10 통합 구현으로 폐기됨]** ~~`KIS_LIVE_INFO_*`
   자격증명은 이 화면에 사용하지 않는다.~~ 사전 조사 중 한때 "LIVE_INFO_* 키 활용" 전제가
   있었으나, 당시에는 이후 검토(세션 preemption 위험, 계좌 단위 budget 공유 위험)를 거쳐
   **별도 계좌·앱키 사용으로 결정**되었었다. 이 문서 본문의 §4~§9(Backend/API/UI/테스트
   설계)는 그 당시 결정을 전제로 작성되어, `KIS_REALTIME_QUOTE_*`라는 신규 전용 계좌를
   구축하는 것으로 서술되어 있다.
   **✅ 2026-07-10 갱신: 이 판단은 폐기되었다.** `ops-scheduler`의 163 WS 의존 제거로
   "세션 preemption 위험"의 전제(이 appkey로 WS를 여는 프로세스가 둘 이상 존재)가
   사라졌고, 그 결과 **`KIS_LIVE_INFO_*`가 이 화면의 authoritative credential로
   통합 구현되었다**(`KIS_REALTIME_QUOTE_*`는 deprecated fallback). 따라서 이 문서를
   읽을 때, §4~§9 본문에 등장하는 "`KIS_REALTIME_QUOTE_*`"/"신규 전용 계좌" 서술은
   **당시 설계 기록**으로 이해해야 하며, **현재 실제 코드가 쓰는 credential은
   `KIS_LIVE_INFO_*`**다. 상세는 "Credential 분리/통합 판단 메모"의 "✅ 2026-07-10
   통합 구현 상세" 참고.
3. **`websocket_client.py`의 기존 채널 구성과 충돌하지 않는다.** `_OPTIONAL_CHANNELS =
   frozenset({"H0STCNT0", "H0STASP0", "H0STCNS0"})`(websocket_client.py:65)는 이미 이번에
   채택한 KRX 전용 채널과 동일하므로, 클라이언트/파서 재사용에 구조적 문제가 없다. 다만
   기존 인스턴스는 트레이딩 계좌 전용으로 생성되므로, 이 화면은 **같은 클래스의 별도
   인스턴스**(신규 계좌 자격증명으로 생성)를 사용해야 한다. 기존 인스턴스를 공유하거나
   재사용하지 않는다.

## 4. Backend 설계

> **⚠️ 2026-07-10 갱신 — 아래 §4~§9는 2026-07-08 초기 설계 당시 문서다.**
> "신규 전용 계좌", "`KIS_REALTIME_QUOTE_*`" 등으로 서술된 부분은 **당시 결정을
> 기록한 것**이며, 구조(approval key 캐시 정책, WebSocket Session 1개 원칙,
> 구독 종목 수 제한, API/UI 설계, 테스트 계획)는 지금도 그대로 유효하다 —
> 달라진 건 **오직 이 credential이 가리키는 실제 env var 이름뿐**이다.
> `KIS_REALTIME_QUOTE_APP_KEY`/`_APP_SECRET`/`_BASE_URL`/`_WS_URL`이라고 쓰인
> 곳은 전부 현재 `KIS_LIVE_INFO_APP_KEY`/`_APP_SECRET`/`_BASE_URL`/`_WS_URL`로
> 읽으면 된다(`KIS_REALTIME_QUOTE_*`는 deprecated fallback으로만 코드에 남음).
> "완전히 분리된 신규 계좌"라는 표현도 "트레이딩 계좌와는 분리되어 있으나,
> 076 홀리데이 조회/disclosure 계좌(`KIS_LIVE_INFO_*`)와는 같은 credential을
> 공유한다"로 갱신해서 읽어야 한다. 상세 배경은 아래 "Credential 분리/통합
> 판단 메모"의 "✅ 2026-07-10 통합 구현 상세" 참고.

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

> **✅ 2026-07-10 구현 완료 — Step 4(REST Fallback 연동)**. 아래는 실제 구현
> 기준으로 갱신한 내용이다(구현 전 초안은 하단 "구현 전 초안(참고)" 참고).
>
> **이 절이 다루는 건 "API↔KIS 간 quote source fallback"이다** — Phase 4(§5.5)의
> SSE push relay가 다루는 "브라우저↔API 간 transport fallback"(SSE 전송 실패 시
> REST polling)과는 완전히 다른 계층이다. 전자는 KIS WebSocket 연결 자체가
> 끊겼을 때 **값 자체**를 REST로 보정하는 것이고, 후자는 KIS WS는 멀쩡한데
> **admin_ui로의 전달 경로**(SSE)만 끊겼을 때 REST polling으로 우회 전달하는
> 것이다. 두 fallback은 독립적으로 동시에 발생할 수 있다.
>
> - **트리거 조건**: `KisRealtimeQuoteSource.connection_state()`가
>   `CONNECTED`가 아닌 상태(`DISCONNECTED`/`RECONNECTING`)로 10초
>   (`_FALLBACK_TRIGGER_AFTER_SECONDS`) 이상 지속되면, 그 시점부터 구독 중인
>   모든 종목에 대해 REST 현재가 조회(`KISRestClient.get_quote()`,
>   `FHKST01010100`)를 호출해 snapshot을 보정한다. REST client는 이 화면 전용으로
>   이미 격리된 client(2026-07-10부터 `KIS_LIVE_INFO_APP_KEY` 기준 — 이전에는
>   `KIS_REALTIME_QUOTE_APP_KEY`, 아래 "Credential 분리/통합 판단 메모" 참고)를
>   그대로 재사용한다 — 트레이딩 계좌 client를 새로 끌어올 필요가 없어(계좌 통합
>   불필요) 초안보다 더 단순하게 확정했다.
> - **과호출 방지**: 종목별 쿨다운(10초, `_FALLBACK_COOLDOWN_SECONDS`) — 연결이
>   끊긴 채로 오래 지속돼도 종목당 최소 10초 간격으로만 REST를 호출한다.
>   헬스체크 주기는 3초(`_HEALTH_CHECK_INTERVAL_SECONDS`). 쿨다운은 **fetch가
>   성공했을 때만** 시작된다 — 실패하면 다음 헬스체크에서 곧바로 재시도한다
>   (아래 "2026-07-10 마감 전 보정" 참고).
> - **캐시 우회**: `KISRestClient.get_quote()`는 3분 TTL 캐시를 갖고 있고,
>   `subscribe()`의 정적 참조값 보강(§4.1)/자정 롤오버 재조회가 같은 캐시를
>   공유한다. Step 4 fallback은 `get_quote(symbol, bypass_cache=True)`로 호출해
>   이 캐시를 우회하고 항상 최신값을 가져온다(아래 "2026-07-10 마감 전 보정" 참고).
> - **필드 정책**: REST 응답(`FHKST01010100`)에서 확보 가능한 실시간성 필드만
>   갱신한다 — `last_price`/`change`/`change_rate`/`change_sign`,
>   `open_price`/`high_price`/`low_price`, `accumulated_volume`/`accumulated_value`,
>   `trading_halted`(`temp_stop_yn`). 호가 10단계(`ask_levels`/`bid_levels`),
>   체결 이력(`recent_trades`), 체결 시각(`trade_time`), 시간구분(`hour_class`)은
>   REST 응답에 없으므로 **마지막으로 알려진 값을 그대로 유지**한다(값을 비우거나
>   null로 만들지 않는다 — "프레임 유지" 원칙과 동일). `prev_close`/상한가/하한가/
>   PER/PBR/EPS/BPS는 이미 별도의 정적 참조값 갱신 로직(자정 롤오버 포함)이 있으므로
>   이 fallback에서는 건드리지 않는다.
> - **`data_source: "rest_fallback"` 노출**: fallback이 적용된 snapshot은
>   `QuoteSnapshot.data_source`(및 API/SSE 응답의 동일 필드)가 `"rest_fallback"`으로
>   실제로 내려간다 — 이전까지는 타입 힌트 주석으로만 존재하고 실제 산출 경로가
>   없었다. KIS WS가 회복되고 실제 tick이 다시 도착하면(`apply_trade`/
>   `apply_orderbook`) 별도 처리 없이 자동으로 `"websocket"`으로 복귀한다.
> - **기존 SSE push relay(§5.5)와의 연동**: fallback으로 갱신된 snapshot도 기존
>   `_notify_listeners()`/dedup 경로를 그대로 타므로, `QuoteBroadcaster` 구독자
>   (SSE stream)도 REST 보정값을 push로 받는다 — SSE 이벤트 구조/API contract는
>   변경 없음.
> - **UI 배지는 이번 범위에서 추가하지 않았다** — `RealtimeQuoteSnapshotView.data_source`
>   필드가 이미 화면에 그대로 노출되므로(§6, 상세정보 패널 등), 최소 변경 원칙에
>   따라 프론트엔드는 건드리지 않았다. 별도의 "REST 보정값" 전용 배지 UI가
>   필요하면 후속 과제로 남긴다.
>
> **파일**: `services/kis_realtime_quote_source.py`(`_SymbolState.data_source`,
> `apply_rest_fallback()`, `_health_monitor_loop()`, `_maybe_apply_rest_fallback()`,
> `connect()`/`aclose()`/`unsubscribe()` 수정), `tests/services/test_kis_realtime_quote_source.py`
> (`TestRestFallback` 6개 테스트 추가).
>
> **✅ 2026-07-10 마감 전 검수로 확인된 결함 3건 보정**:
> 1. **캐시 우회**: `_maybe_apply_rest_fallback()`이 기존에는 `get_quote(symbol)`을
>    그대로 호출해, `subscribe()`(§4.1 정적 참조값 보강)/자정 롤오버 재조회와
>    같은 3분 TTL 캐시를 공유했다 — WS가 구독 직후 3분 이내에 끊기면 "장애
>    시점의 실제 최신 현재가"가 아니라 "구독 시점 캐시값"을 그대로 반환할 수
>    있었다. `KISRestClient.get_quote()`에 `bypass_cache: bool = False` 파라미터를
>    추가하고, fallback 경로에서만 `bypass_cache=True`로 호출하도록 수정했다
>    (캐시를 아예 없애지 않고, 이 경로만 우회 — 다른 호출자는 영향 없음).
> 2. **실패 시 쿨다운 오기록**: `_last_fallback_at[symbol]`를 REST 호출 **전**에
>    기록해, 호출이 실패해도 쿨다운이 걸려 다음 헬스체크에서도 재시도가 막혔다.
>    쿨다운 기록 시점을 fetch **성공 이후**로 옮겨, 실패한 시도는 다음 헬스체크
>    주기에서 곧바로 재시도되게 했다.
> 3. **`data_source` 전환 미전파**: `_content_signature()`가 `data_source`를
>    의도적으로 제외하고 있어서, 가격/거래량 등 숫자 값이 완전히 동일한 채
>    `websocket` → `rest_fallback`으로 출처만 바뀌는 경우 signature가 그대로라
>    listener(SSE 구독자 포함) notify가 생략될 수 있었다. signature 튜플에
>    `data_source`를 포함시켜, 출처 전환도 반드시 구독자에게 전달되도록 했다.
>
> 테스트: `TestRestFallback`에 3건 추가 — 실제 `KISRestClient`(진짜 TTL 캐시
> 포함, HTTP 전송 계층만 stub)로 캐시 우회를 재현하는 테스트, fetch 실패 후
> 다음 헬스체크에서 재시도되고 성공 시에만 쿨다운이 걸리는 테스트, 값이
> 동일한데 출처만 바뀌어도 listener가 재통보받는 테스트.
>
> **파일**: `brokers/koreainvestment/rest_client.py`(`get_quote(..., bypass_cache)`),
> `services/kis_realtime_quote_source.py`(`_maybe_apply_rest_fallback()`,
> `_content_signature()` 수정), `tests/services/test_kis_realtime_quote_source.py`
> (`TestRestFallback`에 3개 테스트 추가, 실제 `KISRestClient` stub 헬퍼 추가).
>
> **구현 전 초안(참고, 더 이상 유효하지 않음)**: REST fallback은 "장애 시 임시
> 대체" 용도로만 사용하고 정상 시나리오의 주 경로로 쓰지 않는다는 원칙은 그대로
> 유지했다. 다만 "REST 보정값 배지"는 이번에 UI에 추가하지 않았고, REST client도
> 트레이딩 계좌 재사용 대신 이미 격리된 전용 client를 그대로 썼다.

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
> - `KIS_REALTIME_QUOTE_*`/`KIS_LIVE_INFO_*` credential 분리는 **✅ 2026-07-10에
>   통합으로 전환됐다**(아래 "Credential 분리/통합 판단 메모" 참고): 재평가
>   당시("당분간 분리 유지")에는 두 credential이 서로 다른 컨테이너(`api` vs
>   `ops-scheduler`)에서 각각 운영되고 있다는 점이 통합의 핵심 장벽이었으나,
>   같은 날 `ops-scheduler`의 163 WS 의존이 제거되면서 그 장벽이 사라져 곧바로
>   `KIS_LIVE_INFO_*`를 authoritative credential로 하는 통합을 구현했다.
>
> **후속 과제**:
> 1. ~~Credential/appkey 통합 재검토~~ — **✅ 2026-07-10 완료 → 같은 날 통합
>    구현 완료.** 최종적으로 `KIS_LIVE_INFO_*`로 통합했다. 상세 근거와 구현
>    내역은 아래 "Credential
>    분리/통합 판단 메모" 참고.
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
>
> **✅ 2026-07-10 자정 경과 구독의 `prev_close` stale 버그 수정**. `000660`에서
> "호가" 프레임의 대비율(클라이언트가 `prev_close`로 직접 계산)과 "실시간 체결가"의
> 대비율(KIS가 매 틱마다 직접 계산해 보내주는 `change_rate`)이 서로 다르게
> 표시되는 문제가 보고돼 실측했다 — `last_price - change`(체결 tick 기준 실제
> 전일종가)가 저장된 `prev_close`와 완전히 달랐다(예: 2,186,000 vs 2,076,000).
>
> - **원인**: `prev_close`/상한가/하한가/PER/PBR/EPS/BPS는 `subscribe()` 시점에
>   REST(`FHKST01010100`)로 **딱 1회만** 가져와 저장하고 이후 절대 갱신하지
>   않는다(`_SymbolState.apply_static_reference()`). 그런데 앞서 §5.5의 리소스
>   비효율 리뷰에서 이미 확인했듯 구독은 브라우저 연결이 끊겨도 자동
>   해제되지 않아, 자정을 넘겨 며칠씩 유지되는 경우가 실제로 있다(`000660`이
>   바로 그 사례). 자정이 지나면 오늘의 진짜 전일종가가 바뀌는데, 캐시된
>   `prev_close`는 구독을 시작한 날짜의 값에 멈춰 있어 어긋난다. 반면 체결
>   tick의 `change_rate`(`PRDY_CTRT`)는 KIS 서버가 매번 그 시점 기준으로
>   새로 계산해 보내주므로 항상 정확하다.
> - **수정**: `_SymbolState`에 `reference_date`(KST "YYYYMMDD") 필드를 추가해
>   정적 참조값을 가져온 날짜를 기록한다. `_apply_realtime_frame()`에서 매
>   프레임마다 오늘 날짜와 비교해 다르면(자정 경과) `_refresh_static_reference()`를
>   백그라운드 태스크로 스케줄링해 REST 재조회 후 `prev_close` 등을 갱신한다.
>   종목별 `_reference_refresh_in_progress` 집합으로 중복 재조회를 막는다.
>   REST 실패 시에도 다음 프레임에서 다시 시도된다(best-effort, 조회 실패가
>   메시지 처리 자체를 막지 않음).
> - 라이브로 재구독해 확인한 결과 `last_price - change == prev_close`가 정확히
>   일치함을 확인했다(수정 전엔 약 110,000원 차이가 있었다). 자정 경과
>   시나리오 자체는 실시간으로 재현하기 어려워 단위 테스트로 검증했다
>   (`TestStaticReferenceRefresh`).
>
> **파일**: `services/kis_realtime_quote_source.py`(`_SymbolState.reference_date`,
> `_reference_refresh_in_progress`, `_refresh_static_reference()`,
> `_apply_realtime_frame()`/`unsubscribe()` 수정), `tests/services/test_kis_realtime_quote_source.py`
> (`TestStaticReferenceRefresh` 2개 테스트 추가).
>
> **✅ 2026-07-10 Phase 4 마감 전 보정 2건 (프론트엔드)**. 새 기능이 아니라 직전
> Phase 4 구현의 마감 전 수정이다 — credential/appkey 통합, transport 변경
> (SSE→WS), multi-worker 확장, REST fallback 신규 구현은 이번 범위에 포함하지
> 않았다.
>
> 1. **`RealtimeQuoteView.tsx` 상태 소스 일원화**: 헤더 연결 아이콘/라벨,
>    degraded 판정, warning banner, stale 표시가 각자 `connection.connection_state`
>    (bootstrap 시점 1회성 값)와 `streamStatus`(SSE 스트림의 실시간 값)를 서로
>    다르게 참조해, 배너는 끊김인데 헤더는 "연결됨"으로 남거나 그 반대인 모순이
>    발생할 수 있었다. **실시간 연결 상태의 authoritative source를 `streamStatus`
>    (+ SSE transport 자체가 끊긴 상태를 나타내는 `pushDegraded`) 하나로 통일**했다
>    (`resolveConnectionState()`). `connection.connection_state`는 선택된 종목의
>    스트림이 아직 첫 이벤트를 받기 전(종목 선택 직후/미선택)의 fallback으로만
>    쓰인다 — 스트림이 한 번이라도 이벤트를 받으면 그 이후로는 bootstrap 값을
>    보지 않는다.
> 2. **SSE stream 401 인증 만료 처리 보강**: `subscribeRealtimeQuoteStream()`이
>    공통 `request()` 래퍼를 거치지 않고 직접 `fetch()`를 호출해, `/realtime-quotes/
>    stream`의 401이 일반 transport error로 취급되어 backoff 재시도만 반복될 수
>    있었다. 이제 401을 감지하면 `clearStoredToken()` + 공용 `_onUnauthorized()`
>    콜백(AuthContext의 로그아웃)을 호출하고 재시도 루프를 완전히 멈춘다 — 다른
>    REST API가 401을 받았을 때와 동일한 "로그인 세션 종료" 사용자 경험이 되도록
>    맞췄다.
>
> **파일**: `admin_ui/src/components/RealtimeQuoteView.tsx`(`resolveConnectionState()`
> 추가, 헤더/배너/degraded 판정을 이 값 하나로 통일), `admin_ui/src/api/client.ts`
> (`subscribeRealtimeQuoteStream()`의 401 처리), `admin_ui/src/__tests__/realtimeQuoteView.test.tsx`
> (streamStatus 전이·stale·bootstrap fallback 시나리오 추가), `admin_ui/src/__tests__/realtimeQuoteStream.test.ts`
> (신규 — 401 처리 전용 테스트), `admin_ui/src/__tests__/test-utils/mockFetch.ts`
> (`mockFetchStreamUnauthorized()` 추가).

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
  (Step 4 REST Fallback 세부 항목도 **2026-07-10 구현 완료** — §4.7 상단 블록 참고)
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

## Credential 분리/통합 판단 메모 — ✅ 통합 구현 완료(2026-07-10, 같은 날 재검토 이후)

> **✅ 2026-07-10 재검토 완료(결론: 당분간 분리 유지) → 같은 날 163 WS 제거 →
> 같은 날 credential 통합 구현 완료.** 아래 재검토는 "당분간 분리 유지"로 결론
> 났었지만, 그 결론의 핵심 근거는 "`KisMarketStateClient`(`KIS_LIVE_INFO_*`)가
> `ops-scheduler`라는 별도 프로세스에서 살아있어, 통합하면 §4.2 WebSocket Session
> 1개 원칙을 **프로세스 경계 너머로** 지켜야 한다"는 것이었다. 같은 날 뒤이어
> 163 WS 자체가 `ops-scheduler`에서 완전히 제거되면서 이 근거가 사라졌다 —
> 이제 `KIS_LIVE_INFO_*` appkey의 WS 세션 소비자는 `api` 프로세스
> (`KisRealtimeQuoteSource`) **하나뿐**이라, "프로세스 경계를 넘는 세션 소유권
> 재설계" 없이도 통합이 가능해졌다. 그래서 재검토 직후 곧바로 통합을 구현했다.
> 실제 변경: `runtime/bootstrap.py::build_realtime_quote_source()`가
> `KIS_REALTIME_QUOTE_*` 대신 `KIS_LIVE_INFO_APP_KEY`/`_APP_SECRET`/`_BASE_URL`/
> `_WS_URL`(+ 신규 `KIS_LIVE_INFO_APPROVAL_CACHE_PATH`)을 authoritative credential로
> 쓰도록 변경했고, `docker-compose.yml`/`.env.example`에서 `KIS_REALTIME_QUOTE_*`를
> 표준 설정에서 제거했다(코드에는 짧은 하위 호환 fallback만 남김). 상세는 이
> 섹션 맨 아래 "✅ 2026-07-10 통합 구현 상세" 참고. 아래는 재검토 당시의
> 원본 근거와 결론이며, 역사적 기록으로 그대로 남겨둔다.

> **[원본 재검토 완료 메모, 2026-07-10]** Phase 4(push relay)/
> Step 4(REST fallback) 완료로 착수 트리거가 충족돼 실제 코드 기준으로 재검토했다.
> 이번 작업은 **판단 문서화**이며, credential 통합 구현 자체는 진행하지 않았다.
> 아래는 그 재검토 근거와 결론이다.

### 확인한 코드 범위
- `services/kis_realtime_quote_source.py` — `KisRealtimeQuoteSource`(현재가), `api` 프로세스 전용.
- `services/realtime_quote_broadcaster.py` — `QuoteBroadcaster`(SSE fan-out), `api` 프로세스 전용.
- `brokers/koreainvestment/websocket_client.py` — `KISWebSocketClient`(현재가가 재사용하는 공용 WS client).
- `brokers/koreainvestment/market_state_client.py` — `KisMarketStateClient`(장운영정보 163, `KIS_LIVE_INFO_*` 전용).
- `scripts/run_ops_scheduler.py` — `KisMarketStateClient`를 실제로 인스턴스화하는 유일한 지점(`_init_market_state_provider()`).
- `api/app.py` — `KisRealtimeQuoteSource`/`QuoteBroadcaster`의 lifespan wiring. `KisMarketStateClient`는 **여기 전혀 등장하지 않는다**.
- `docker-compose.yml` — `KIS_REALTIME_QUOTE_*`는 `api` 서비스에만 배선, `KIS_LIVE_INFO_*`는 `app`/`api`/`ops-scheduler`/`reconciliation-worker` 4개 서비스 모두에 배선(단, 실제 사용은 `ops-scheduler`뿐).
- `reference_docs/.../002_실시간_(웹소켓)_접속키_발급.md` — approval key 발급/세션 정책 원문.

### 이번 재검토로 새로 확인된 핵심 사실 — "같은 프로세스 안"이 아니다
이전까지의 판단 메모는 분리 이유를 "WebSocket session ownership / reconnect blast
radius / approval key / registration budget 분리"로 서술했지만, 이는 암묵적으로
"같은 `api` 프로세스 안에서 두 WS 클라이언트를 어떻게 공존시킬지"의 문제처럼
읽힐 여지가 있었다. 실제 코드를 추적한 결과, 이는 **프로세스 내부 설계 문제가
아니라 컨테이너 경계를 넘는 문제**임이 확인됐다:

- `KisRealtimeQuoteSource`(`KIS_REALTIME_QUOTE_*`)는 **`api` 컨테이너 프로세스**
  안에서만 살아있다(모듈 docstring에 이미 명시된 불변식: "this connection lives
  and dies with the `api` process only").
- `KisMarketStateClient`(`KIS_LIVE_INFO_*`)는 **`ops-scheduler` 컨테이너 프로세스**
  안에서만 인스턴스화된다(`run_ops_scheduler.py::_init_market_state_provider()`).
  `api` 프로세스의 `lifespan`에는 이 클라이언트가 전혀 등장하지 않는다.
- 두 클라이언트는 코드 레벨에서도 서로 다른 클래스다 — 현재가는 공용
  `KISWebSocketClient`(approval key를 생성자 인자로 받아 고정 사용, 발급/캐시는
  외부 `KISRestClient`가 담당)를 재사용하고, 장운영정보는 독립 구현체
  `KisMarketStateClient`(자체 approval key 캐시/재연결 로직 내장)를 쓴다.
- registration budget(41건 상한)은 `SubscriptionBudget`이라는 **프로세스 내
  인메모리 객체**로 관리된다(`KisRealtimeQuoteSource.__init__`에서 매 인스턴스마다
  새로 생성) — 프로세스 간에 공유되는 상태가 아니다.
- `§4.2 WebSocket Session 1개 원칙`("같은 appkey로 두 번째 연결을 여는 코드
  경로를 만들지 않는다")이라는 명시적 설계 불변식이 이미 존재한다. credential을
  통합하면 이 불변식을 **프로세스 경계 너머로** 지켜야 한다 — `api`와
  `ops-scheduler`가 완전히 독립적으로 기동/재시작되는 두 프로세스이기 때문에,
  "동일 appkey를 쓰는 두 프로세스 중 하나가 재시작될 때 다른 프로세스의 세션이
  끊기지 않는다"는 보장을 코드만으로 주기 어렵다.

이 발견은 재검토의 결론에 결정적이다 — 통합은 "같은 프로세스 안에서 session
manager를 공유하는 설계 변경"이 아니라, **두 개의 독립 배포 단위(컨테이너) 중
하나가 이 credential의 유일한 소유자가 되도록 서비스 토폴로지 자체를 바꾸는
작업**이다.

### 분리 유지 vs 통합 비교

| 관점 | 분리 유지 | 통합 |
|---|---|---|
| 장애 원인 분리 | 현재가 화면 장애가 장운영정보(트레이딩 스케줄링의 핵심 입력)에 영향을 주지 않음 | 같은 appkey/세션을 공유하면 한쪽의 재연결 폭주·approval key 재발급이 다른 쪽 세션에 영향을 줄 위험 |
| 프로세스 경계 | `api`/`ops-scheduler`가 완전히 독립적으로 배포·재기동 가능 | 두 프로세스 중 하나가 credential을 소유하고 다른 프로세스는 위임받는 구조로 재설계 필요 |
| registration budget(41건) | 각자 별도 41건 한도 — 여유 있음(현재가 최대 30건 + 163 채널 1건 = 31건이라 합쳐도 이론상 여유는 있으나, 프로세스 간 budget 조정 메커니즘이 없다는 게 더 큰 문제) | 프로세스 간 budget 공유를 위해 외부 상태 저장소(Redis 등, 명시적 비범위) 필요 |
| approval key 재발급 경쟁 | 각자 독립 appkey라 경쟁 자체가 발생하지 않음 | 동일 appkey에 대해 두 프로세스가 각자 재발급을 시도하면 "세션 1개 원칙" 위반 소지 |
| rollback 용이성 | 한쪽만 롤백/재배포해도 다른 쪽에 영향 없음 | 통합 후에는 credential 관련 변경이 두 서비스 모두에 영향 |
| 운영·행정 비용 | 별도 계좌/appkey를 계속 유지·재발급·점검해야 함(기술 외부 비용) | 계좌/appkey 관리 단순화 |
| dormant credential 리스크 | 거래 없는 별도 계좌의 장기 존속을 시스템이 보장할 수 없음(외부 정책 리스크) | 리스크 해소 |
| 현재 화면 규모 대비 필요성 | 단일 종목 중심이라 fan-out 압력 자체는 작음(순수 register 건수 관점에서는 통합 필요성이 낮음) | 압력이 작다는 것은 통합의 "여유"이지 "필요"는 아님 |

### 통합 시 필요한 구조 변경 범위(최소 설계 수준)
실제로 통합을 추진한다면 최소한 아래가 필요하다 — "env 정리" 수준이 아니라
**서비스 토폴로지 재설계**다:

1. **소유권 결정**: `api`와 `ops-scheduler` 중 어느 프로세스가 통합된 credential의
   WS 세션을 소유할지 결정. 예를 들어 (a) `ops-scheduler`가 소유하고 `api`는 그
   결과를 IPC/메시지큐로 전달받아 현재가 화면에 릴레이하거나, (b) `api`가 소유하고
   `ops-scheduler`는 장운영정보를 API 호출/큐 구독으로 받아오는 구조.
2. **approval key 발급/캐시 소유권 이전**: 현재 `KISRestClient`(현재가)와
   `KisMarketStateClient`(장운영정보)가 각자 독립적으로 관리하는 approval key
   캐시(`KisTokenCache`, 파일 기반)를 단일 소유자로 좁히고, 다른 프로세스는
   그 캐시를 읽기 전용으로만 참조하거나 아예 접근하지 않도록 재설계.
3. **channel registration 소유권**: 체결가/호가(`H0STCNT0`/`H0STASP0`)와
   장운영정보(`H0UNMKO0`)를 동일 WS 세션 아래 등록할지, 아니면 여전히 두 개의
   물리적 WS 연결을 유지하되 credential만 공유할지 결정. 후자를 택해도 "세션 1개
   원칙"과 정면 충돌하므로, 결국 전자(단일 세션에 두 채널 모두 등록)로 귀결될
   가능성이 높다 — 이는 `KisRealtimeQuoteSource`와 `KisMarketStateClient`를
   하나의 client로 합치거나 최소한 하나의 session manager 아래 두는 재작성을
   의미한다.
4. **reconnect policy 단일화**: 현재 두 클라이언트는 서로 다른 backoff 정책을
   갖는다(`KISWebSocketClient`의 exponential backoff vs `KisMarketStateClient`의
   자체 backoff). 통합 세션은 재연결 정책도 하나로 통일해야 한다.
5. **registration budget 프로세스 간 공유**: 두 프로세스가 여전히 분리된
   채로 credential만 공유하는 절충안을 택한다면, 41건 budget을 프로세스 간에
   조율할 외부 상태 저장소(Redis 등)가 필요하다 — 이는 기존 문서에서 이미
   "multi-worker/cross-process fan-out은 범위 외"로 명시한 것과 동일한 클래스의
   비용이다.
6. **failure isolation 전략**: 통합 세션이 끊기면 트레이딩 스케줄링(장운영정보)과
   현재가 화면이 동시에 영향을 받는다 — 어느 쪽이 critical path인지 우선순위를
   정하고, 한쪽 장애가 다른 쪽을 fail-safe하게 만들지 않도록 하는 회로 차단
   전략이 필요하다.

### 현재 권고안 — 당분간 분리 유지
**결론: 지금 통합 구현에 착수하지 않는다. 당분간 분리 구조를 유지한다.**

- 통합의 실익(별도 계좌/appkey 운영·행정 비용 절감)은 실재하지만, 이는 순수
  운영·행정 비용이지 기술적 필요는 아니다 — 현재 registration budget 관점에서는
  통합하지 않아도 아무 문제가 없다(각자 여유 있는 41건 한도를 따로 쓰고 있다).
- 반면 통합 비용은 처음 판단했던 것보다 크다 — "같은 프로세스 안의 session
  manager 설계"가 아니라 **서로 다른 두 컨테이너 프로세스의 소유권을 재설계**해야
  하는 작업이며, 트레이딩 스케줄링의 핵심 입력(장운영정보)과 운영 편의 기능
  (현재가 화면)을 하나의 장애 반경으로 묶는 대가를 치러야 한다.
- 별도 계좌/appkey의 dormant 리스크(장기 존속을 시스템이 보장 못 함)는 여전히
  유효한 우려이지만, 이는 **기술 통합으로 해결할 문제가 아니라 계좌/앱키 관리를
  담당하는 운영 조직의 행정적 결정 사항**으로 분리해서 다뤄야 한다 — "코드를
  합친다"고 "계좌가 사라질 위험"이 없어지는 것은 아니다(오히려 계좌를 유지하는
  한 문제가 없고, 계좌 회수 결정이 내려지는 시점에 대응하면 된다).

### 후속 액션(선행 조사 체크리스트 — 지금 착수하는 항목 아님)
장기적으로 정말 통합이 필요해지는 시점(예: 별도 계좌 회수가 확정되는 경우)에
대비해, 아래를 먼저 조사해야 실제 설계에 들어갈 수 있다:
- [ ] KIS에 appkey당 동시 WS 세션 허용 여부(2개 이상의 프로세스가 같은 approval
      key/appkey로 동시에 연결을 여는 것이 실제로 거부되는지, 아니면 뒤에 연결한
      쪽이 앞선 세션을 끊는지)를 공식 문의/실측으로 확인.
- [ ] "credential은 공유하되 프로세스는 그대로 분리 유지"하는 절충안이 실제로
      가능한지(예: 하나의 프로세스가 항상 세션을 열고, 다른 프로세스는 그 결과만
      구독하는 구조) 검토.
- [ ] 별도 계좌/appkey의 실제 회수·재발급 정책을 운영 조직에 확인해, "얼마나
      급한 문제인지" 시한을 구체화.
- [ ] 위 조사 결과에 따라 "당분간 분리 유지" 결론을 재확인하거나, 통합 설계
      착수 여부를 다시 판단.

> **📌 2026-07-13 관련 실측 확인**: 위 체크리스트는 **WS approval-key/세션
> 1개 원칙**(WebSocket 계층) 범위였는데, 별개로 **REST `oauth2/tokenP`
> 토큰 캐시** 계층에서도 유사한 문제가 실제로 존재함을 코드 분석으로
> 확인했다 — 같은 `KIS_LIVE_INFO_*` appkey를 쓰는 076 holiday client와
> 공시/시세 quote client가 서로 다른 캐시 파일(`kis_live_oauth_token.json`
> vs `kis_disclosure_token.json`)을 써서, cold start 시 같은 appkey로
> `oauth2/tokenP`가 중복 발급될 위험(`EGW00133` 1분당 1회 제한)이 있다.
> 이건 WS 세션 통합 여부와 무관하게 **지금 바로 고칠 수 있는 별도
> 이슈**라, `plans/kis_dev_token_cache.md` 상단 banner + `plans/[BACKLOG]
> backlog.md`의 "KIS 토큰 캐시 통합(appkey당 1개)" 항목으로 분리해서
> 진행한다.

## 163 WS(장운영정보, `ops-scheduler`) 제거 가능성 검토 메모 — ✅ 구현 완료(2026-07-10)

> **✅ 2026-07-10 검토 완료 → 같은 날 구현 완료.** 결론: "제거 가능성 높음,
> 장기 shadow 검증 없이 진행 가능" → 실제로 `scripts/run_ops_scheduler.py`에서
> `KisMarketStateClient`/`CombinedSessionProvider` 의존을 제거했다.
> `_init_market_state_provider()`/`_session_phase_monitor()`/
> `_handle_phase_change()`/`_insert_session_event()`를 삭제하고,
> `_init_session_provider()`는 이제 항상 076 REST(`KisHolidayProvider`) +
> `FallbackSessionProvider`만 반환한다. `SchedulerState.market_phase`/
> `last_phase_change`와 대응 DB 컬럼(`trading.market_sessions`/
> `trading.operations_day_runs`)은 스키마 변경 없이 남겨두되, 이 두 필드의
> 유일한 writer가 사라졌으므로 앞으로는 항상 `NULL`이다(로깅은 이미 "N/A"
> 폴백을 갖추고 있고, `docker-compose.yml`의 ops-scheduler healthcheck가 참조하는
> `market_phase IN ('after_hours','idle')` 단축 경로는 더 이상 히트하지 않지만
> heartbeat 최신성 검사로 정상 폴백된다). `core_risk_off` 장후 검증 배치
> (`signal_feature_batch`/`trigger_proxy_attribution`)는 아래에서 이미 확인했듯
> `state.market_phase`가 아니라 고정 시계 트리거(`_run_end_of_day`의
> `after_hours_mode` 진입, `DEFAULT_SIGNAL_FEATURE_BATCH_TIME`)로만 게이팅되므로
> 영향이 없음을 코드 확인 + 회귀 테스트(`tests/scripts/test_run_ops_scheduler.py`
> 148 passed, `tests/services/test_market_session.py` 30 passed,
> `tests/services/test_signal_feature_batch_runtime.py` +
> `tests/services/test_trigger_proxy_attribution.py` 포함 202 passed)로 검증했다.
> `CombinedSessionProvider` 클래스 자체는 `services/market_session.py`에 그대로
> 남겨두었다(재사용 가능한 추상화이며, 다른 잠재적 소비자를 위해 삭제하지 않음) —
> `ops-scheduler`만 더 이상 이를 생성/사용하지 않는다. credential(`KIS_LIVE_INFO_*`/
> `KIS_REALTIME_QUOTE_*`) 통합 자체는 이번 작업 범위 밖으로 그대로 유지했다.
>
> 이번 검토는 credential 통합(위 메모)의 **선행 조건 검증**이다 — 통합의 최대
> 장벽이 "163 WS가 `ops-scheduler`라는 별도 프로세스에서 살아있다"는 사실이었으므로,
> 163 자체를 없앨 수 있다면 통합 문제가 "두 프로세스 중 하나의 소유권을 재설계"에서
> "남은 유일한 WS 소유자(`api`)의 credential을 그대로 두거나 `KIS_LIVE_INFO_*`를
> 아예 폐기"하는 훨씬 단순한 문제로 축소된다. 이번 작업은 **판단 문서화**이며,
> `KisMarketStateClient` 제거 구현이나 env 배선 변경은 진행하지 않았다.

### 확인한 코드 범위
- `scripts/run_ops_scheduler.py` — 모듈 docstring("Session Gate P1"), `_session_gate()`,
  `_session_phase_monitor()`, `_init_market_state_provider()`, phase 전이 시각 상수.
- `services/market_session.py` — `KisHolidayProvider`(076), `FallbackSessionProvider`
  (주말 휴리스틱), `CombinedSessionProvider`(076+163 결합 로직), `create_session_provider()`.
- `brokers/koreainvestment/market_state_client.py` — `KisMarketStateClient.connect()`의
  paper-환경 skip 로직(`_is_paper`).
- `.env`(현재 실제 배포 설정) — `KIS_ENV=paper`, `KIS_LIVE_INFO_ENABLED=true`.

### 163 WS가 스케줄러에서 실제로 하는 일
1. **`CombinedSessionProvider`의 안전장치(safe mode) — 유일하게 실질적 게이팅 효과**:
   076(`opnd_yn`)이 거래일이라고 해도, 163의 `market_phase`가 `HALT`/`UNKNOWN`이면
   그날 전체를 비거래일로 처리(안전 모드)한다. 076은 "오늘이 휴장일인지"(하루 단위
   정적 정보)만 알려주므로, 장중 거래정지 같은 예외 상황은 163 없이는 감지할 수 없다.
   - **다만 이 효과는 하루 중 단 한 순간으로 제한된다.** `_session_gate()`는
     `state.session_info`를 **그날 최초 호출 시점에 한 번만** 계산해 하루 종일
     캐시한다(`if state.session_info is None:`). 즉 163의 실시간성이 실제
     게이팅에 반영되는 시점은 "그날 첫 세션 게이트 호출 순간"뿐이고, 그 이후
     장중에 163이 새로 `HALT`를 보고해도 이미 캐시된 `session_info`는 갱신되지
     않아 게이팅에 반영되지 않는다.
2. **`_session_phase_monitor()`의 관측성(observability)** — 5초 간격으로 163을
   폴링해 phase 변화를 감지하고 `trading.market_sessions`/`trading.session_events`
   테이블에 기록한다. `state.market_phase` 값 자체는 로그 문자열과 DB 저장에만
   쓰이고, **스케줄러의 실행 여부/타이밍/주문 게이팅 조건문에는 전혀 쓰이지
   않는다**(코드 전체에서 `state.market_phase`가 `if`/`return` 조건으로 등장하는
   곳이 없다).
3. **phase 전이(pre-market/intraday/EOD 시작 시각) 자체는 163과 완전히 무관하다**
   — `PRE_MARKET_START = dtime(8, 0)`, `INTRADAY_START = dtime(8, 50)`,
   `MARKET_CLOSE = dtime(15, 30, 30)`, `END_OF_DAY_END = dtime(16, 30)` 같은
   고정 시계 상수로 이미 결정되어 있다(모듈 docstring에도 "P1 Session Gate"가
   076+fallback만으로 설계됐다고 명시 — 163은 나중에 추가된 P2 보강 계층이다).

### 076/휴리스틱/시계 기반으로 이미 대체되고 있는 부분
- phase 전이 트리거: 163 유무와 무관하게 이미 100% 시계 기반.
- 거래일 여부의 1차 판정: 076(`KisHolidayProvider`)/주말 휴리스틱
  (`FallbackSessionProvider`)이 이미 담당 — 163은 그 위에 얹는 부가 안전장치일 뿐.
- **결정적 사실**: 현재 실제 배포 설정(`.env`)은 `KIS_ENV=paper`다.
  `KisMarketStateClient.connect()`는 `_is_paper`(= credential 없음 **또는**
  `kis_env in (paper, mock, sandbox)`) 조건에서 실제 WS 연결 자체를 건너뛰고
  즉시 반환한다(`"connect() skipped — 163 WebSocket not available in paper
  environment"`). 즉 `KIS_LIVE_INFO_ENABLED=true`로 credential이 설정돼 있고
  `KisMarketStateClient` 인스턴스가 생성됨에도 불구하고, **현재 이 시스템은
  이미 매일 163 없이(076-only `CombinedSessionProvider` 분기) 운영되고 있다.**
  이는 가정이 아니라 코드 로직으로 확정되는 사실이다.

### 163 WS를 없애면 가장 먼저 잃는 것
- 장중 실시간 `HALT`/`UNKNOWN`(거래정지 등 이례 상황)을 "그날 최초 게이트 호출
  시점"에 반영할 수 있는 유일한 안전장치 — 076/휴리스틱은 이 정보를 원천적으로
  제공하지 않는다. 다만 위에서 확인했듯 이 효과 자체가 하루 중 한 순간으로
  이미 제한적이다.
- 운영 대시보드의 실시간 phase 관측성(`market_phase` 컬럼, `session_events`
  이력) — 시계 기반 근사로 대체 가능하나, VI 발동/동시호가 변동 등으로 인한
  실제 KIS 서버 phase와의 미세한 시차는 더 이상 실측할 수 없게 된다.

> **✅ 2026-07-10 추가 판단(사용자 확인) — 배치 주문 주기 관점에서 이 손실은
> 크리티컬하지 않다.** 실제 주문 판단/제출은 `DEFAULT_DECISION_INTERVAL_SECONDS
> = 300`(5분) 간격의 배치 스크립트(`run_decision_loop.py`)로만 이뤄진다 —
> 즉시 반응이 필요한 실시간 주문 경로가 시스템에 애초에 없다. 이 사실이
> 위 손실의 실제 영향을 무디게 만드는 이유는 두 가지다:
> 1. `session_gate`의 163 `HALT`/`UNKNOWN` 안전모드는 애초부터 "장중 특정
>    순간에 즉각 반응"하는 장치가 아니라 "그날 최초 호출 시점에 이례적이면
>    그날 스케줄 전체를 스킵"하는 하루 단위 조대한 필터였다(위에서 이미 확인).
>    5분 배치처럼 저빈도로 실행되는 시스템에서는 이런 "사전 대략적 필터"가
>    갖는 실효성이 더욱 작다.
> 2. 163 없이 배치가 계속 돌다가 실제 거래정지/VI 구간에 주문을 제출하더라도,
>    그건 KIS 서버가 주문 단계에서 거부/에러로 응답할 사안이다 — 개별 주문의
>    실제 안전성은 163의 phase 신호가 아니라 브로커 응답 처리/주문 파이프라인의
>    다른 검증 레이어가 담당한다. 즉 163을 없앤다고 시스템이 위험한 주문을
>    걸러내지 못하게 되는 게 아니라, "5분 배치가 도는 걸 하루 단위로 좀 더
>    보수적으로 사전에 걸러주는 부가 필터"를 잃을 뿐이다.

### 검증 체크리스트(163 제거 전 반드시 확인)
- [ ] **거래일 판단 정확도**: 076-only 판정과 163 결합 판정이 실제로 갈린 날이
      있었는지 로그/DB(`session_events`) 이력에서 확인.
- [ ] **장개시/장마감 경계 오판 가능성**: 고정 시계 상수(`PRE_MARKET_START` 등)와
      실제 163이 보고한 phase 전이 시각의 차이를 실측.
- [ ] **`HALT`/`UNKNOWN` safe-mode 제거 영향**: 163이 실제로 `HALT`/`UNKNOWN`을
      보고한 사례가 과거에 있었는지, 있었다면 그게 실제 시장 이상 상황이었는지
      사후 확인.
- [ ] **시간외/동시호가 구간 영향**: `AFTER_HOURS`/`CLOSING` phase 판정이 스케줄러의
      after-hours 스냅샷 로직(`allow_after_hours_positions` 등)에 실질적으로
      영향을 주는지 재확인(현재는 `state.market_phase`가 조건문에 쓰이지 않는다는
      점에서 이미 영향이 없어 보이지만, 명시적으로 재확인 필요).
- [ ] **주문 타이밍/게이팅 정확도 저하 여부**: 실제 주문 제출 여부(`session_gate`
      리턴값)가 163 유무에 따라 달라진 날이 있었는지 확인.
- [ ] **운영 관찰성 손실 허용 여부**: `market_phase`/`session_events`를 참조하는
      운영 대시보드/알림이 있다면, 그 소비자들이 관측성 손실을 감내할 수 있는지 확인.

### 권장 검증 방법론 — shadow 비교(참고용, 필수 선행 조건 아님)
> **✅ 2026-07-10 갱신**: 아래 shadow 비교 절차는 애초에 "VI/거래정지 같은
> tail 이벤트가 크리티컬한 문제를 일으킬 수 있다"는 전제 위에서 설계했다.
> 그런데 이 시스템은 주문 판단/제출이 5분 배치로만 이뤄져 즉시 반응이 필요한
> 실시간 경로가 없다는 게 확인되면서, 그 전제 자체가 이 시스템에는 해당하지
> 않는 것으로 결론 났다(아래 "현재 시점 권고안" 참고). 따라서 이 방법론은
> **제거 진행의 필수 선행 조건이 아니라, 더 보수적으로 접근하고 싶을 때
> 선택적으로 쓸 수 있는 참고 절차**로 남겨둔다.

"한번 꺼보고 본다" 방식이 아니라, **163을 그대로 켜 둔 채** 아래를 재현 가능한
절차로 수행한다:
1. `CombinedSessionProvider.get_session_info()`가 이미 내부적으로 `holiday_info`
   (076-only 결과)와 최종 `result`(163 결합 결과)를 모두 계산한다 — 이 둘을 함께
   로깅/DB에 남기도록 계측을 추가한다(이번 작업 범위 밖, 후속 구현 시 필요).
2. **관찰 기간은 2단계로 나눈다** — "정상 경로 검증"과 "tail 이벤트 검증"이
   요구하는 기간이 서로 다르기 때문이다(✅ 2026-07-10 사용자 피드백 반영):
   - **1단계(1~2 거래일, 1차 통과 기준)**: phase 전이(pre-market→intraday→
     closing→after-hours)는 매일 반복되는 정상 경로이므로, 실전 거래일
     1~2일만 관찰해도 고정 시계 상수와 실측 163 phase 전이 시각의 정합성은
     충분히 확인된다. 이 단계에서 divergence가 없으면 "정상 경로"는 통과로
     간주한다.
   - **2단계(배경 상시 관찰, 기간 제한 없음)**: `HALT`/`UNKNOWN` safe-mode는
     VI 발동/거래정지 같은 **저빈도 tail 이벤트**이므로, 짧은 기간에 발생하지
     않았다고 "안전하다"고 결론 내릴 수 없다(관측 기간이 짧아서 못 본 것과
     애초에 없어서 못 본 것을 구분할 수 없음). shadow 로깅은 순수 관측이라
     비용이 거의 없으므로, 1단계 통과 후에도 로깅 자체는 계속 켜둔 채
     운영하다가 실제로 `HALT`/`UNKNOWN` 이벤트가 발생하면(시점 무관) 그 사례가
     제대로 잡히는지 사후 확인하는 방식으로 전환한다 — "N주 동안 무작정
     대기"가 아니라 "짧게 1차 검증 후 그린라이트, 이후 이벤트 발생 시 소급
     확인"이다.
   - 가능하다면 1단계 관찰일을 변동성이 큰 날(실적 발표일, 지수 리밸런싱일,
     옵션 만기일, 공휴일 전후 등)로 의도적으로 골라 짧은 기간에도 이례 상황을
     관찰할 확률을 높인다.
3. **비교 지표**: (a) 076-only 판정과 163 결합 판정의 `is_trading_day` 불일치
   일수, (b) `HALT`/`UNKNOWN` safe-mode가 실제로 발동한 횟수와 그 발동이
   사후적으로 정당했는지(실제 장애/이상 상황이었는지), (c) `session_events`의
   실측 phase 전이 시각과 고정 시계 상수 간의 최대/평균 편차.
4. 이 shadow 관찰은 **`KIS_ENV=live`(실전) 환경에서** 수행해야 의미가 있다 —
   지금까지의 "163 없이 매일 운영됨" 실측은 paper 환경의 결과이므로, live
   환경에서의 실제 시장 이상상황(VI, 거래정지 등) 빈도는 아직 검증되지 않았다.

### 현재 시점 권고안
**제거 가능성 높음 — 별도의 장기 shadow 검증 없이 진행 가능.**
(✅ 2026-07-10 최종 갱신, 사용자 판단 확인 및 반영)

근거: ① 163의 실질적 게이팅 효과가 이미 "하루 중 한 순간"으로 제한적임이
코드로 확인됨, ② phase 전이 자체가 애초부터 163과 무관한 시계 기반임,
③ 076-only 경로가 이미 paper 환경에서 매일 실질 운영되며 검증되고 있음,
④ **실제 주문 판단/제출이 5분 간격 배치(`DEFAULT_DECISION_INTERVAL_SECONDS=300`)
로만 이뤄져 즉시 반응이 필요한 실시간 경로가 없으므로**, 163이 제공하던
"장중 즉각적 이상 감지"라는 가치 자체가 이 시스템의 요구사항과 애초에 맞지
않는다 — 개별 주문의 실제 안전성은 브로커(KIS) 응답 처리/주문 파이프라인의
다른 검증 레이어가 담당하고, 163은 그 위에 얹힌 하루 단위 부가 필터였을
뿐이다.

VI/거래정지 같은 tail 이벤트에 대한 리스크 완화가 이 shadow 검증의 원래
목적이었는데, 그 이벤트가 실제로 크리티컬한 영향을 주는 경로(즉시 반응이
필요한 주문 실행) 자체가 이 시스템에 없다고 판단되므로, 장기 관찰 없이도
"제거해도 안전하다"는 결론에 도달할 수 있다. 다만 아래 최소 확인은 실제
제거 구현 시점에 한 번은 짚어야 한다(이번 작업 범위 밖).

### 다음 액션(장기 shadow 검증 대신 최소 확인만 남김) — ✅ 2026-07-10 구현 시 재확인 완료
- [x] 실제 제거 구현 착수 시, `session_gate`/`state.market_phase`가 정말
      주문 게이팅·타이밍 조건문 어디에도 쓰이지 않는지 최종 재확인 — 구현
      직전 grep으로 재검증했고(`if`/`return` 조건에 `state.market_phase`가
      등장하지 않음을 확인), 실제로 `_run_end_of_day`(고정 시계)만이
      `after_hours_mode`를 설정함을 코드로 확정한 뒤 제거를 진행했다.
- [x] 제거 후 `market_sessions`/`session_events`의 관측성 손실을 참조하는
      운영 대시보드/알림이 있는지 확인 — Admin UI
      `OperationsDashboardView.tsx`가 `market_phase`를 배지 색상/부제목에
      표시하지만 이미 `?? "-"` null-safe 폴백을 갖추고 있어 코드 수정 없이도
      깨지지 않는다(항상 "neutral" 배지로 표시됨). 이번 작업은 프론트엔드
      수정을 범위에서 제외했으므로 대체 표시(시계 기반 추정 phase)로의 전환은
      **후속 과제로 남긴다**.
- [x] 검증이 완료되어 credential 통합 여부를 재판단할 조건이 성립했다 — **같은
      날 실제로 통합을 구현했다.** 상세는 아래 "✅ 2026-07-10 통합 구현 상세" 참고.

## ✅ 2026-07-10 통합 구현 상세

163 WS 제거로 credential 통합의 핵심 장벽(프로세스 경계를 넘는 WS 세션 소유권
문제)이 해소된 직후, 같은 날 실제 통합을 구현했다. 요구사항: **최종 authoritative
key는 `KIS_LIVE_INFO_*`** (`KIS_REALTIME_QUOTE_*`가 아니라).

### 변경된 초기화 경로
- `src/agent_trading/runtime/bootstrap.py::build_realtime_quote_source()`:
  - 기존: `settings.kis_realtime_quote_app_key`/`_app_secret`/`_base_url`/`_ws_url`/
    `_approval_cache_path`만 읽음.
  - 변경: **우선** `settings.kis_live_app_key`/`kis_live_app_secret`/
    `kis_live_info_base_url`/`kis_live_info_ws_url`/`kis_live_info_approval_cache_path`를
    읽는다. 이 중 앞의 두 필드(`kis_live_app_key`/`_app_secret`)는
    `_build_kis_live_quote_client()`(disclosure/live 계좌 REST 클라이언트,
    `run_decision_loop.py` 등 여러 스크립트가 이미 사용 중)와 **동일한 필드**다
    — 즉 이 appkey는 이제 (a) 076 REST 휴장일 조회, (b) disclosure/live REST
    quote 조회, (c) 실시간 현재가 화면의 WS+REST fallback 세 가지 용도로 함께
    쓰이지만, 전부 REST 아니면 유일한 WS 소비자(`api` 프로세스)이므로 §4.2
    WebSocket Session 1개 원칙과 충돌하지 않는다.
  - 짧은 하위 호환: `kis_live_app_key`/`_app_secret`가 비어 있으면
    legacy `kis_realtime_quote_app_key`/`_app_secret`(+`_base_url`/`_ws_url`/
    `_approval_cache_path`)로 fallback하고 `logger.warning()`을 남긴다 —
    신규 배포는 이 fallback을 탈 필요가 없다.
- `src/agent_trading/config/settings.py`: 신규 필드
  `kis_live_info_approval_cache_path`(env `KIS_LIVE_INFO_APPROVAL_CACHE_PATH`,
  기본값 `.cache/kis_live_info_approval_key.json`) 추가. 기존
  `kis_realtime_quote_*` 5개 필드/리졸버는 삭제하지 않고 "[Deprecated] legacy
  fallback"으로 docstring만 갱신해 그대로 남겼다(코드에서 fallback 경로가 여전히
  참조하므로).
- `KISRestClient`(`brokers/koreainvestment/rest_client.py`)는 전과 동일하게
  범용 dataclass다 — credential 인자만 바뀌었을 뿐 클라이언트 코드 자체는
  수정하지 않았다.

### 설정 파일 정리
- `docker-compose.yml`(`api` 서비스): `KIS_REALTIME_QUOTE_*` 5개 env 라인을
  제거하고 `KIS_LIVE_INFO_APPROVAL_CACHE_PATH`를 추가했다. `ops-scheduler`
  서비스는 변경 없음(원래도 `KIS_REALTIME_QUOTE_*`를 쓰지 않았다 — 163 제거와
  무관하게 애초에 배선되어 있지 않았음을 재확인).
- `.env.example`: `KIS_LIVE_INFO_*` 섹션 설명에 "이제 실시간 현재가 화면의
  authoritative credential이기도 하다"를 명시하고 `KIS_LIVE_INFO_APPROVAL_CACHE_PATH`를
  추가. `KIS_REALTIME_QUOTE_*` 섹션은 "[Deprecated]"로 표시하고 값 라인을
  주석 처리했다(코드 레벨 fallback은 남아 있으므로 완전 삭제하지 않음).

### 실시간 현재가 기능 자체는 변경 없음
`KisRealtimeQuoteSource`, `QuoteBroadcaster`(SSE fan-out), REST fallback 로직
(`RestFallbackAugmentedQuoteSource` 등)은 **한 줄도 수정하지 않았다** — 이번
통합은 순수하게 "어느 credential으로 REST/WS 클라이언트를 만드는가"의 문제이며,
현재가 조회/구독/SSE push/REST fallback 동작 자체는 그대로다.

### 검증
- `tests/services/test_kis_realtime_quote_source.py::TestBuildRealtimeQuoteSource` —
  기존 2개 테스트를 `KIS_LIVE_INFO_*` 기준으로 갱신하고, legacy fallback
  경로를 검증하는 신규 테스트(`test_builds_source_with_legacy_realtime_quote_fallback`)를
  추가해 총 3개 모두 통과 확인.
- 실시간 현재가/SSE/scheduler/session 관련 회귀 테스트 전체(283개) DB 없이 통과.
- `docker compose config`로 compose 정합성 확인.
