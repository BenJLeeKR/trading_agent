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

- `SubscriptionBudget(max_subscriptions=41)`을 명시적으로 생성한다 (기존
  `KoreaInvestmentAdapter`와 동일한 값을 이 화면 전용 계좌에도 적용 — `adapter.py:85` 패턴 참고).
- 이 화면은 critical/optional 구분이 필요 없다 — 모든 구독이 "화면에 표시 중인 종목"이므로
  전량 optional로 취급하고, 화면에서 사라진 종목은 즉시 구독 해제(`tr_type=2`)한다.
- 여러 admin_ui 브라우저 세션이 같은 종목을 동시에 볼 수 있으므로, 종목별로 **참조
  카운트(reference count)**를 두어 마지막 뷰어가 사라질 때만 실제 KIS 구독을 해제한다.
  이를 통해 41건 한도를 종목 단위로만 소모하고 뷰어 수와 무관하게 유지한다.

### 4.4 Subscription Budget과 Broker Capacity 관측값 연결

- 기존 `GET /broker-capacity`(`routes/broker_capacity.py`)는 **트레이딩 계좌의** budget만
  노출한다. 이 화면 전용 계좌는 별개이므로, 기존 엔드포인트에 억지로 합치지 않고
  **별도 필드 또는 별도 read-only 엔드포인트**로 노출한다 (5.3 참고).
- 노출 항목: 활성 구독 종목 수, 41건 대비 사용률, 세션 연결 상태, 마지막 approval_key
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
  보고 있는 종목 포함), 41건 대비 사용률, 환경 라벨(`live`/`paper` — 항상 `live`
  고정이지만 화면에 재확인용으로 노출).

### 5.2 구독 요청/해제 endpoint

```
POST   /realtime-quotes/subscriptions     { "symbols": ["005930", "000660"] }
DELETE /realtime-quotes/subscriptions     { "symbols": ["005930"] }
```

- 참조 카운트 증감만 수행하고, 실제 KIS 구독 등록/해제는 참조 카운트가 0에서 1로
  또는 1에서 0으로 바뀔 때만 트리거한다.
- 41건 초과 요청은 422/409 등으로 명시적으로 거부하고, 어떤 종목이 원인인지 응답에
  포함한다 (자동 evict 없음 — 이 화면은 critical/optional 구분이 없으므로 임의로
  다른 사용자의 구독을 evict하면 안 된다).

### 5.3 현재 구독 상태 조회 endpoint

```
GET /realtime-quotes/subscriptions
```

- 현재 활성 구독 목록, 종목별 참조 카운트, 41건 대비 사용량, 세션 연결 상태,
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
- **구독 한도 표시**: 41건 대비 현재 사용량(예: "12 / 41 구독 중") — 5.3 endpoint 값을
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
- **Rate limit / 구독 한도 준수**: 4.3의 41건 상한을 코드로 강제(§10.4.3 언급된
  `SubscriptionBudget(max_subscriptions=41)`)하고, 초과 요청은 API 레벨에서 거부한다
  (5.2).
- **민감정보 비노출**: approval_key, appkey/appsecret은 API 응답/로그/UI 어디에도
  노출하지 않는다. `KisTokenCache`의 기존 로깅 패턴(`_log_hit`/`_log_miss`,
  `token_cache.py:714-731`)이 토큰 값 자체를 로그에 남기지 않는 것을 그대로 따른다.

## 8. 단계별 구현 계획

- **Phase 1**: 이 설계 문서, API contract 확정, UI mock data 기반 화면 뼈대.
- **Phase 2**: Backend quote subscription manager — 이 화면 전용 `KISWebSocketClient`
  인스턴스, 참조 카운트 기반 구독 관리, 메모리 snapshot 저장(4.1~4.6, 5.1~5.4).
- **Phase 3**: Admin UI polling 화면 — 6.1~6.3 화면을 5.5(a) polling 방식으로 연결.
- **Phase 4**: WebSocket/SSE relay 검토 및 전환 — 5.5(b) 도입, fan-out broadcaster 설계.
- **Phase 5**: 운영 관측/alert 연동 — 세션 끊김 장기화, 41건 근접, approval_key
  갱신 실패 등에 대한 알림을 기존 운영 alert 채널에 연동.

각 Phase는 이전 Phase 완료 후 별도 승인을 거쳐 착수한다 (특히 Phase 4는 Phase 3
운영 경험을 바탕으로 실시간성이 실제로 부족한지 재검토한 뒤 착수 여부를 결정).

## 9. 테스트 계획

- **Unit test**: 참조 카운트 기반 구독/해제 로직, 41건 초과 시 거부 로직, snapshot
  갱신/staleness 판정 로직.
- **API contract test**: 5.1~5.4 endpoint의 요청/응답 스키마, adapter 미설정 시
  503 처리(`broker_capacity.py` 패턴과 동일 검증).
- **Admin UI rendering test**: 연결 상태 배지, 구독 한도 표시, REST fallback 배지
  등 상태 전이별 렌더링 테스트 (mock data 기반, 기존 admin_ui 테스트 패턴 준용).
- **KIS mock WebSocket test**: 기존 `ws_parser.py`/`websocket_client.py` 테스트
  스위트와 동일한 방식으로, mock WS 서버를 통해 구독 성공/실패, 재연결, 41건
  초과 시나리오를 검증.
- **Live read-only smoke test**: 신규 계좌 자격증명으로 실제 KIS Live WS에 연결해
  1개 종목을 짧게 구독/해제하는 최소 smoke test. 기존
  `logs/trigger_proxy_attribution_smoke_2026-07-02.log`류의 운영 smoke test와
  동일한 성격으로, CI 상시 실행이 아닌 수동/저빈도 실행 대상으로 분류한다.
