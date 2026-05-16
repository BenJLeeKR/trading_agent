# Phase 4: Live-info 076/163 E2E 운영 검증 보고서

**검증 일시**: 2026-05-16 15:08 ~ 15:11 KST (UTC+9)
**검증자**: Roo (ops-scheduler 컨테이너 기반)
**보고서 버전**: 1.0

---

## 1. 검증 환경

| 항목 | 값 |
|------|-----|
| Container | `agent_trading-ops-scheduler` (이미지: `agent_trading-app:latest`) |
| Container 상태 | **running but unhealthy** (32분 전 시작) |
| TZ | `Asia/Seoul` |
| KIS env | `paper` |
| Live-info enabled | `true` |
| Live-info BASE_URL | `https://openapi.koreainvestment.com:9443` |
| Live-info WS URL | `ws://ops.koreainvestment.com:21000` |
| Token cache enabled | `true` (path: `.cache/kis_live_token.json`) |
| Session source | `CombinedSessionProvider (076+163+fallback)` |
| API 서버 | `agent_trading-api-1` (port 8000, token: `dev-token-123`) |
| DB | PostgreSQL 16, schema: `trading`, user: `trading` |

---

## 2. ops-scheduler 로그 핵심

### 2.1 Startup 로그 (14:38:09 KST)

```
market_state_provider=enabled (KIS_LIVE_INFO_APP_KEY present)
SessionProvider: KisHolidayProvider (076 API) base_url=https://openapi.koreainvestment.com:9443
Session provider initialized: KisHolidayProvider (163 WS not available)
  Live-info enabled:   true
  Live-info token cache: true (path: .cache/kis_live_token.json)
  Session source:      CombinedSessionProvider (076+163+fallback)
  trading_kis_config=present       ✅
  live_info_kis_config=present     ✅
  market_state_provider=enabled    ✅
```

### 2.2 076 실패 로그 (14:38:09 KST) — **크리티컬**

```
HTTP Request: POST https://openapi.koreainvestment.com:9443/oauth2/tokenP "HTTP/1.1 200 OK"
KisHolidayProvider: 076 API failed for 20260516 — KIS error (rt_cd=) from oauth2_token: unknown error
Traceback:
  File ".../holiday_client.py", line 167, in _ensure_token
    data = self._parse_response(resp, context="oauth2_token")
  File ".../holiday_client.py", line 209, in _parse_response
    raise KISHolidayError(
```

### 2.3 Fallback 전환 (지속)

```
session_gate: ALLOW phase=intraday run_date=2026-05-16 session_source=gate_error_fallback opnd_yn=N bzdy_yn=N tr_day_yn=N market_phase=N/A
```

**gate_error_fallback이 전체 운영 기간 동안 유지됨** (14:38:10 ~ 15:11:08 KST, 5초 간격)

### 2.4 163 WebSocket

```
Session provider initialized: KisHolidayProvider (163 WS not available)
```

WebSocket 163 endpoint는 코드 레벨에서 **연결 시도조차 하지 않음** (not available 처리).

---

## 3. 076 결과 (국내휴장일조회)

### 3.1 oauth2/tokenP (access_token 발급)

**독립 테스트 성공** — KIS 실서버 직접 호출:

| 항목 | 결과 |
|------|------|
| HTTP Status | **200 OK** |
| access_token | `eyJ0eXAiOiJKV1QiLCJh...` (유효) |
| expires_in | 86400 (24시간) |
| token_type | Bearer |

**credential은 완전 유효함** (`KIS_LIVE_INFO_APP_KEY`/`KIS_LIVE_INFO_APP_SECRET` 정상)

### 3.2 `_parse_response` 코드 버그 (근본 원인)

[`holiday_client.py`](src/agent_trading/brokers/koreainvestment/holiday_client.py:197)의 `_parse_response()`는 **uapi 응답 포맷 기준**으로 작성됨:

```python
rt_cd = data.get("rt_cd", "")       # ← uapi 응답에만 존재
if rt_cd != "0":
    raise KISHolidayError(...)
```

그러나 **oauth2/tokenP 응답**에는 `rt_cd` 필드가 **존재하지 않음**:

```json
{
  "access_token": "eyJ0eXAi...",
  "access_token_token_expired": "2026-05-17 14:20:59",
  "token_type": "Bearer",
  "expires_in": 86400
}
```

→ `data.get("rt_cd", "")`가 빈 문자열 `""` 반환 → `"" != "0"` → `KISHolidayError` 발생

**즉, credential은 정상이지만 파싱 코드가 oauth2 응답 구조와 맞지 않아 실패**

### 3.3 076 CTCA0903R (chk-holiday)

oauth2/tokenP가 실패하여 CTCA0903R 자체는 한 번도 호출되지 않음.
1분 rate limit(1회/분)으로 인해 독립 재시도는 제한됨.

---

## 4. 163 결과 (장운영정보 WebSocket approval)

### 4.1 oauth2/Approval (approval_key 발급)

**독립 테스트 성공** — KIS 실서버 직접 호출:

| 항목 | 결과 |
|------|------|
| HTTP Status | **200 OK** |
| approval_key | `8b5f7547-7ac1-4cc0-bcd7-d686e82b9cfe` (유효) |

### 4.2 WebSocket 연결

코드 레벨에서 163 WS 연결이 **"not available"로 초기화**되어 연결 시도 자체가 없음.
approval_key는 유효하나 WebSocket 구독 경로가 활성화되지 않음.

---

## 5. Token Cache hit/miss 결과

### 5.1 Live-info token cache 파일

```
/app/.cache/ 디렉토리 내용:
  kis_token.json         597 bytes  (paper trading 전용)
  kis_live_token.json    ← 존재하지 않음 ❌
```

| 항목 | 상태 |
|------|------|
| `KIS_LIVE_TOKEN_CACHE_ENABLED` | `true` |
| `KIS_LIVE_TOKEN_CACHE_PATH` | `.cache/kis_live_token.json` |
| Cache 파일 존재 | **없음** |
| Cache hit 로그 | **없음** (076 실패로 캐싱 기회 없음) |
| Cache miss 로그 | **없음** (076 실패로 캐시 조회 기회 없음) |

### 5.2 Paper trading token cache (비교)

Paper token cache(`kis_token.json`)는 정상 작동 중:
- `Token cache: hit fingerprint=b5d0fe1dcbdd94ed` — 반복 확인됨
- `Token cache: miss reason=file_missing` — 최초 시작 시 1회

---

## 6. DB 상태

### 6.1 `trading.market_sessions`

| id | run_date | source | is_trading_day | market_phase | opnd_yn | bzdy_yn | tr_day_yn | raw_opnd_yn |
|----|----------|--------|---------------|-------------|---------|---------|-----------|-------------|
| 1 | 2026-05-16 | `gate_error_fallback` | true | (null) | N | N | N | (null) |

- `raw_opnd_yn`, `raw_mkop_cls_code`, `raw_antc_mkop_cls_code` — **모두 NULL**
- `source = gate_error_fallback` — 076 결과가 아닌 fallback 사용
- 단 1건의 row만 존재

### 6.2 `trading.session_events`

**0건** — 이벤트가 전혀 기록되지 않음 (076 실패로 market_phase 변화 없음)

### 6.3 API market-sessions/latest

`GET /market-sessions/latest` → **500 Internal Server Error** (별도 API 버그)
- `'Connection' object has no attribute 'acquire'` — `get_db` 의존성 주입 버그

---

## 7. Admin UI 반영 결과

API 엔드포인트 자체가 500 에러를 반환하여 Admin UI에서 market session 데이터를 정상적으로 표시할 수 없는 상태.
(별도의 API deps 버그로 인해 session API가 동작하지 않음)

---

## 8. 최종 판정

### 판정: **C — credential 자체 문제 아님 + 코드 버그**

| 기준 | 결과 |
|------|------|
| 076 oauth2/tokenP 성공? | **✅ 성공** (HTTP 200, valid access_token) |
| 076 CTCA0903R 성공? | **❌ 실패** (파싱 버그로 tokenP 단계에서 중단) |
| 163 oauth2/Approval 성공? | **✅ 성공** (HTTP 200, valid approval_key) |
| 163 WebSocket 연결? | **❌ 미연결** (코드에서 "not available" 처리) |
| Live-info token cache hit? | **❌ 없음** (076 실패로 캐싱 기회 없음) |
| market_sessions 갱신? | **❌ gate_error_fallback만 기록** |
| session_events 기록? | **❌ 0건** |
| Admin UI 반영? | **❌ API 500 에러** |
| Fallback 미사용? | **❌ gate_error_fallback 계속 사용 중** |

### 진단: **Credential은 정상, wiring도 정상, 문제는 순수 코드 버그**

```
[KIS 실서버]                    [ops-scheduler]
                                    │
oauth2/tokenP ◄───────────────── HTTP POST
   │  HTTP 200 + access_token        │
   │  (정상 응답)                    │
   │                                 │
   ──────────────────────────────► _parse_response()
                                      │
                                      ├─ data.get("rt_cd", "") → ""
                                      ├─ rt_cd != "0" → True
                                      └─ raise KISHolidayError ❌
```

---

## 9. 다음 액션

### 즉시 필요 (Priority 1) — `_parse_response` 버그 수정

[`holiday_client.py`](src/agent_trading/brokers/koreainvestment/holiday_client.py:197)의 `_parse_response()`에서 **oauth2/tokenP 응답에 대한 분기 처리** 필요:

```python
# oauth2/tokenP 응답 (rt_cd 없음)
# → access_token 필드 존재 여부로 oauth 응답 감지
if context == "oauth2_token" and "access_token" in data:
    return data  # rt_cd 검증 스킵

# uapi 응답 (rt_cd 있음)
rt_cd = data.get("rt_cd", "")
if rt_cd != "0":
    raise KISHolidayError(...)
```

또는 더 간단한 접근: oauth2/tokenP 전용 별도 메서드 사용

### Priority 2 — 163 WebSocket 활성화

163 WS 경로가 "not available"로 설정된 원인 확인 및 활성화.
approval_key는 정상 발급되므로 WebSocket 핸드셰이크/구독 코드만 활성화하면 됨.

### Priority 3 — API market-sessions 버그 수정

`get_db` 의존성에서 Pool 대신 Connection을 반환하는 문제 (별도 이슈).

### Priority 4 — 수정 후 재검증

버그 수정 후 아래 항목 재확인:
1. 076 CTCA0903R 정상 호출 → `opnd_yn`, `bzdy_yn`, `tr_day_yn` 응답 확인
2. Live-info token cache hit/miss 로그 확인
3. market_sessions `source = kis_holiday_api` 전환 확인
4. session_events phase transition 기록 확인
5. 163 WS connect/subscribe 성공 확인

---

## Appendix: 독립 테스트 증거

### A. oauth2/tokenP (076용 access_token) — 2026-05-16 15:11 KST

```json
HTTP 200 OK
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJh...",
  "access_token_token_expired": "2026-05-17 14:20:59",
  "token_type": "Bearer",
  "expires_in": 86400
}
```

### B. oauth2/Approval (163용 approval_key) — 2026-05-16 15:11 KST

```json
HTTP 200 OK
{
  "approval_key": "8b5f7547-7ac1-4cc0-bcd7-d686e82b9cfe"
}
```

### C. DB market_sessions row

```
id=1, run_date=2026-05-16, source=gate_error_fallback,
is_trading_day=t, opnd_yn=N, bzdy_yn=N, tr_day_yn=N,
raw_opnd_yn=NULL, raw_mkop_cls_code=NULL, raw_antc_mkop_cls_code=NULL
```

### D. Container env (live-info 관련)

```
KIS_LIVE_INFO_ENABLED=true
KIS_LIVE_INFO_APP_KEY=PScDVLqkufdKEEunAe008QZtZuwqPVA7aK2S
KIS_LIVE_INFO_APP_SECRET=8ZH+IMoerQikAL5Ejg47VmpTaT3/...
KIS_LIVE_INFO_BASE_URL=https://openapi.koreainvestment.com:9443
KIS_LIVE_INFO_WS_URL=ws://ops.koreainvestment.com:21000
KIS_LIVE_TOKEN_CACHE_ENABLED=true
KIS_LIVE_TOKEN_CACHE_PATH=.cache/kis_live_token.json
TZ=Asia/Seoul
```
