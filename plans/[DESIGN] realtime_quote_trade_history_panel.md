# 실시간 현재가 화면 — 실시간 체결가(시별/일별) 프레임 추가 설계

> **상태**: ✅ 설계+구현 완료 (2026-07-09)
> **범위**: `현재가` 화면에 `호가`와 `종목 상세정보` 사이에 새 프레임 추가.
> 기존 `호가`/`종목 상세정보` 프레임, 구독 관리, WS 연결 로직은 변경하지 않음.

## 1. 배경

`현재가` 화면에서 체결가 tick 히스토리(시별)와 일자별 시세(일별)를 볼 수 없었다.
사용자가 제시한 참고 이미지 기준으로 `호가` ↔ `종목 상세정보` 사이에 탭 전환형
프레임을 추가한다.

## 2. 디자인 결정 (사용자 확정)

| 항목 | 결정 |
|---|---|
| 새 프레임 폭 | 최소 400px (`minmax(400px, 1fr)`) |
| 표시 행 수 | 20행 고정 |
| 보관 상한(메모리/응답) | 30개 (표시 20행보다 여유를 둠) |

## 3. 데이터 출처

| 탭 | TR / API | 특성 |
|---|---|---|
| 시별 | `H0STCNT0`(체결가, 이미 구독 중인 WS 채널) | 매 tick 누적. 새 REST 호출 없음 |
| 일별 | `FHKST01010400`(주식현재가 일자별, REST, 신규 연동) | 탭 진입 시 1회 조회, 최근 30거래일 |

`H0STCNT0`는 이미 파싱 중이었지만 **per-tick 체결량(`CNTG_VOL`, 1-indexed field 13)**은
그동안 추출하지 않고 있었다 — 이번에 추가했다(`ACML_VOL`은 누적치라 다른 값).

`FHKST01010400`은 비슷한 역할의 기존 `inquire_daily_itemchartprice`(`FHKST03010100`,
signal 배치가 쓰는 기간별시세)와는 다른 TR이다 — 이 TR은 응답에 `prdy_vrss`/`prdy_ctrt`
(전일대비/전일대비율)을 이미 포함해서 별도 계산 없이 그대로 쓸 수 있다.

## 4. 백엔드 변경

- `realtime_quote_source.py`
  - `TradeTick`(시간/체결가/전일대비/전일대비율/체결량), `DailyPriceBar`(날짜/종가/전일대비/
    전일대비율/거래량) 신규 dataclass, `MAX_TRADE_HISTORY`/`MAX_DAILY_PRICE_HISTORY = 30`
  - `QuoteSnapshot.recent_trades: list[TradeTick]` 필드 추가(기본값 빈 리스트)
  - `RealtimeQuoteSource` 프로토콜에 `get_daily_price(symbol, count) -> list[DailyPriceBar]` 추가
  - `InMemoryMockQuoteSource`: 결정론적 mock tick 히스토리 + mock 일별 시세 생성기 추가
- `kis_realtime_quote_source.py`
  - `_parse_trade_fields`에 `tick_volume`(field 13, `CNTG_VOL`) 추가
  - `_SymbolState.recent_trades: deque(maxlen=30)`, `apply_trade()`에서 `appendleft`로 누적
    (newest-first, 별도 reverse 불필요)
  - `get_daily_price()` 신규 — `self._rest_client.get_daily_price()` 위임, WS 구독 상태와
    무관하게 동작(순수 REST, budget 소비 없음)
- `rest_client.py`
  - `KIS_ENDPOINTS`/`KIS_TR_IDS`에 `inquire_daily_price` 엔트리 추가(`FHKST01010400`)
  - `get_daily_price()` 신규 메서드 — 별도 캐시 없음(저빈도 호출)
- `api/schemas.py` / `api/routes/realtime_quotes.py`
  - `RealtimeQuoteTradeTickView` 추가, `RealtimeQuoteSnapshotView.recent_trades` 필드 추가
  - `RealtimeQuoteDailyPriceItem`/`RealtimeQuoteDailyPriceResponse` 추가
  - `GET /realtime-quotes/daily-price?symbol=...` 신규 라우트(구독 여부 무관, 422 on invalid symbol)

## 5. 프론트엔드 변경

- `common/TradeHistoryPanel.tsx` 신규 — 시별/일별 탭, 20행 고정(부족하면 `—` placeholder로
  패딩 — 다른 프레임과 동일한 "프레임 유지" 원칙), 일별 탭은 종목/탭 진입 시 1회만 REST
  조회하고 같은 종목이면 재조회하지 않음(캐시)
- `RealtimeQuoteView.tsx` — 그리드를 2단(`526px_1fr`)에서 3단
  (`526px_minmax(400px,1fr)_1fr`)으로 변경, 가운데에 `실시간 체결가` Panel 추가
- `types/api.ts`/`api/client.ts` — 위 신규 타입/엔드포인트 반영

## 6. 테스트

- 백엔드: `test_realtime_quote_source.py`(mock 히스토리/일별시세), `test_kis_realtime_quote_source.py`
  (tick 필드 매핑, newest-first 누적, `get_daily_price` KIS 필드 매핑/구독 무관/상한 30 캡),
  `test_realtime_quotes.py`(snapshot에 recent_trades 포함, `/daily-price` 200/422)
- 프론트: `realtimeQuoteView.test.tsx`에 시별 탭 기본 표시, 일별 탭 클릭 시 fetch+표시 테스트 추가
