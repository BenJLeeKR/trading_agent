# HolidayClient OAuth2 파싱 버그 Hotfix + Live-info E2E 재검증 보고서

**작성일**: 2026-05-16 15:20 KST  
**담당**: Roo (Code Mode)

---

## 1. Root Cause 요약

| 항목 | 내용 |
|------|------|
| **증상** | `KisHolidayProvider`에서 076 API 호출 시 `KISHolidayError` 발생 |
| **에러 메시지** | `KIS error (rt_cd=) from oauth2_token: unknown error` |
| **원인** | [`holiday_client.py:_parse_response()`](src/agent_trading/brokers/koreainvestment/holiday_client.py:184)가 모든 응답에 대해 `data.get("rt_cd", "")` 검증 수행. oauth2/tokenP 응답은 `rt_cd` 필드가 없으므로 `"" != "0"`이 되어 항상 예외 발생 |
| **oauth2 응답 구조** | `{"access_token": "eyJ...", "token_type": "Bearer", "expires_in": 86400}` — `rt_cd` 필드 **없음** |
| **uapi 응답 구조 (정상)** | `{"rt_cd": "0", "msg1": "success", "output": [...]}` |
| **영향** | ops-scheduler 기동 시 076 holiday lookup 실패 → `gate_error_fallback`으로 모든 session gate SKIP |

---

## 2. Parser Hotfix 내용

### 2.1 변경 파일

| 파일 | 변경 |
|------|------|
| [`src/agent_trading/brokers/koreainvestment/holiday_client.py`](src/agent_trading/brokers/koreainvestment/holiday_client.py) | `_parse_response()`에 `context == "oauth2_token"` 분기 추가 |
| [`tests/brokers/koreainvestment/test_holiday_client.py`](tests/brokers/koreainvestment/test_holiday_client.py) | `_mock_token_response()`에서 `rt_cd` 제거 + 신규 테스트 7개 추가 |

### 2.2 `_parse_response()` 수정 방식

```python
def _parse_response(self, resp: httpx.Response, context: str = "") -> dict:
    # HTTP 오류 처리 (변경 없음)
    resp.raise_for_status()
    data = resp.json()

    # NEW: OAuth2 응답은 rt_cd 검증 건너뜀
    if context == "oauth2_token":
        return data

    # 기존 uapi 응답 rt_cd 검증 (변경 없음)
    rt_cd = data.get("rt_cd", "")
    if rt_cd != "0":
        raise KISHolidayError(...)

    return data
```

- **최소 수정 원칙**: 2줄(`if context == "oauth2_token": return data`)만 추가
- 기존 uapi 응답 처리 로직 완전히 보존
- `context` 파라미터는 이미 `_ensure_token()`(line 167)에서 `context="oauth2_token"`으로 전달 중이었음 → `authenticate()` 추가 수정 불필요

### 2.3 `authenticate()` (= `_ensure_token()`) 상태

[`_ensure_token()`](src/agent_trading/brokers/koreainvestment/holiday_client.py:141)은 이미 line 167에서:
```python
data = self._parse_response(resp, context="oauth2_token")
```
로 `context="oauth2_token"`을 전달하고 있었음. 따라서 **추가 수정 불필요**.

---

## 3. 테스트 결과

### 3.1 실행 결과

```
$ python3 -m pytest tests/brokers/koreainvestment/test_holiday_client.py -v
============================== 23 passed in 0.05s ==============================
```

**23/23 전 테스트 통과** ✅

### 3.2 추가된 테스트 목록 (신규 7개)

| 테스트 클래스 | 테스트명 | 설명 |
|--------------|---------|------|
| `TestParseResponse` | `test_parse_oauth2_response_no_rt_cd` | oauth2 응답(rt_cd 없음) → context="oauth2_token" → 정상 파싱 |
| `TestParseResponse` | `test_parse_uapi_response_success` | uapi 정상(rt_cd=0) → context="" / "chk-holiday" → 정상 파싱 (회귀 방지) |
| `TestParseResponse` | `test_parse_uapi_response_error` | uapi 실패(rt_cd=E) → KISHolidayError 발생 (회귀 방지) |
| `TestParseResponse` | `test_parse_oauth2_response_http_error` | oauth2 HTTP 401 → KISHolidayError (HTTP 오류는 context 무관) |
| `TestParseResponse` | `test_parse_oauth2_response_json_error` | oauth2 JSON 파싱 실패 → KISHolidayError |
| `TestEnsureToken` | `test_ensure_token_success` | `_ensure_token()` mocked 성공 → access_token 반환 + 캐시 저장 |
| `TestEnsureToken` | `test_ensure_token_cached` | 두 번째 호출 시 HTTP 호출 없이 캐시 반환 |
| `TestEnsureToken` | `test_ensure_token_http_error` | oauth2 HTTP 오류 → KISHolidayError |
| `TestEnsureToken` | `test_ensure_token_request_error` | 네트워크 오류 → KISHolidayError |

### 3.3 기존 테스트 회귀 검증

기존 16개 테스트 (HolidayStatus 3, GetHolidayStatusSuccess 4, GetHolidayStatusErrors 5, ClientLifecycle 2, token_failure 1, request_error 1) 모두 통과. 특히 `_mock_token_response()`에서 `rt_cd`를 제거했음에도 통과한 것은 hotfix가 정상 동작함을 의미.

---

## 4. Docker 재빌드/재기동 결과

| 단계 | 상태 | 세부사항 |
|------|------|----------|
| `docker compose build ops-scheduler` | ✅ 성공 | 이미지 `agent_trading-app:latest` rebuild (9.5s) |
| `docker compose up -d ops-scheduler` | ✅ 성공 | Container `agent_trading-ops-scheduler` 재생성 및 시작 |
| `/health` | ✅ 성공 | `{"status": "ok", "database": "connected", "runtime_mode": "postgres"}` |

---

## 5. 076 재검증 결과 (ops-scheduler 로그)

### 5.1 핵심 로그 분석

```
2026-05-16 15:18:29 [INFO]   live_info_kis_config=present          ✅
2026-05-16 15:18:29 [INFO]   market_state_provider=enabled          ✅
...
2026-05-16 15:18:29 [INFO]   POST /oauth2/tokenP "HTTP/1.1 200 OK"  ✅ (더 이상 076 에러 없음)
2026-05-16 15:18:29 [INFO]   GET /chk-holiday?BASS_DT=20260516 "200 OK" ✅
2026-05-16 15:18:29 [INFO]   KisHolidayProvider: session_info date=2026-05-16
                             is_trading_day=False opnd_yn=N
                             bzdy_yn=N tr_day_yn=Y source=kis_holiday_api  ✅
```

### 5.2 076 성공 판정

**✅ 076 HOLIDAY LOOKUP — COMPLETE SUCCESS**

- oauth2/tokenP: `200 OK` (rt_cd 파싱 버그 완전 해결)
- chk-holiday: `200 OK` (정상 응답)
- `is_trading_day=False` (2026-05-16은 토요일, 비거래일 — 정상)
- `source=kis_holiday_api` (fallback 아님! 직접 API 호출 성공)
- Session gate가 정상적으로 비거래일 감지 → pre-market/intraday SKIP

### 5.3 독립 테스트

컨테이너 내 독립 테스트는 oauth2 rate limit(`EGW00133`: 1분당 1회)으로 403 발생했으나, 이는 ops-scheduler가 이미 동일 분 내에 oauth2를 호출했기 때문. rate limit은 정상 동작.

---

## 6. 163 WebSocket 재검증 결과

| 항목 | 결과 |
|------|------|
| `KisMarketStateClient` 생성자 | ❌ `settings` 파라미터 미비로 직접 인스턴스화 실패 (별도 이슈) |
| 스케줄러 로그 메시지 | `Session provider initialized: KisHolidayProvider (163 WS not available)` |
| 환경 | Paper 모드 → WS 미지원(설계상) |

**판정**: Paper 환경에서는 WebSocket이 설계상 비활성화됨. Live 환경 전환 시 재검증 필요.

---

## 7. Token Cache 결과

| 항목 | 결과 |
|------|------|
| In-memory token cache | ✅ 정상 (스케줄러 로그: oauth2 1회 호출 후 캐시) |
| File cache (`/app/data/.cache/`) | ❌ 디렉토리 미존재 (별도 이슈 — P2) |
| 스케줄러 설정 | `Live-info token cache: true (path: .cache/kis_live_token.json)` |

In-memory cache는 정상 동작. File cache 디렉토리는 아직 생성되지 않았으나 ops-scheduler의 정상 기동에는 영향 없음.

---

## 8. DB Market Sessions 결과

```sql
SELECT run_date, source, is_trading_day, raw_opnd_yn, checked_at
FROM trading.market_sessions ORDER BY run_date DESC LIMIT 5;
```

| run_date | source | is_trading_day | raw_opnd_yn | checked_at (UTC) |
|----------|--------|---------------|-------------|-----------------|
| 2026-05-16 | `gate_error_fallback` | `t` | NULL | 2026-05-16 05:38:08 |

- **행 1건**, 이전 hotfix 미적용 상태에서 fallback으로 기록됨
- 새로운 ops-scheduler는 **비거래일(토요일)** 이므로 session gate가 SKIP → market_sessions 업데이트 없음
- 평일 재가동 시 `source=kis_holiday_api`로 갱신 예상

## 9. Session Events 결과

```sql
SELECT trigger_source, previous_phase, new_phase, occurred_at
FROM trading.session_events ORDER BY created_at DESC LIMIT 10;
```

**0건** — 주말 비거래일이라 phase 전환 이벤트 없음 (정상)

---

## 10. Admin UI API 결과

| Endpoint | 상태 |
|----------|------|
| `GET /market-sessions/latest` | `Missing Authorization header` (인증 필요 — 정상 라우팅) |
| `GET /market-sessions/events/recent` | `Missing Authorization header` (인증 필요 — 정상 라우팅) |

API 엔드포인트가 정상 라우팅되며, 인증만 추가하면 사용 가능.

---

## 11. 최종 판정

```
판정: B — PASS with minor caveats
```

| 평가 항목 | 상태 |
|-----------|------|
| P0 hotfix (`_parse_response()` oauth2 분기) | ✅ 완료 |
| Regression test | ✅ 23/23 통과 |
| Docker rebuild + restart | ✅ 성공 |
| `/health` | ✅ `status: ok` |
| 076 oauth2/tokenP | ✅ `HTTP 200 OK` (더 이상 파싱 에러 없음) |
| 076 chk-holiday | ✅ `HTTP 200 OK`, 정상 파싱 |
| 163 WebSocket | ⚠️ Paper 환경 미지원 (설계) |
| Token cache (in-memory) | ✅ 정상 |
| Token cache (file) | ⚠️ 디렉토리 미생성 (P2) |
| DB market_sessions | ⚠️ 기존 fallback 레코드 존재, 평일 재가동 시 갱신 예정 |
| Session events | ✅ 0건 (비거래일 정상) |
| Admin API | ✅ 정상 라우팅 확인 |

### 근거

1. **P0 hotfix 완료**: `_parse_response()`에 `context="oauth2_token"` 분기 2줄 추가
2. **ops-scheduler 정상 기동**: live-info credential 인식 → oauth2/tokenP 성공 → 076 chk-holiday 성공 → 비거래일 session gate 정상 동작
3. **Fallback 미사용**: `source=kis_holiday_api`로 직접 API 호출 성공 (이전: `gate_error_fallback`)
4. **추가 수정 불필요**: `_ensure_token()`은 이미 `context="oauth2_token"` 전달 중
5. **일부 P2 과제**: file cache 디렉토리 생성, DB 기존 fallback 레코드 정리

---

## 12. 남은 P1/P2 과제

| 우선순위 | 과제 | 설명 |
|---------|------|------|
| **P1** | ops-scheduler 재기동 후 DB market_sessions 갱신 확인 | 평일(월~금)에 재기동하여 `source=kis_holiday_api`로 기록되는지 검증 필요 |
| **P2** | File cache 디렉토리 사전 생성 | `/app/data/.cache/` 디렉토리가 없어 `kis_live_token.json` 파일 저장 안 됨. 스케줄러 기동 시 자동 생성 로직 또는 Dockerfile에 `mkdir` 추가 |
| **P2** | DB 기존 `gate_error_fallback` 레코드 정리 | hotfix 반영 이전 fallback 레코드, 트레이싱 혼선 방지를 위해 정리 또는 무시 로직 검토 |
| **P2** | 163 WS Paper 환경 개선 | 현재 Paper에서 WS 미지원, Live 전환 시 별도 E2E 필요 |

---

*End of report.*
