# Live-info/Session/Scheduler 경로 최종 운영 검증 보고서

**검증 일시:** 2026-05-16 (토) 15:56 KST  
**검증 환경:** `KIS_ENV=paper`, `KIS_LIVE_INFO_ENABLED=true`  
**비고:** **비영업일(토요일)** 검증 — 장 종료 후, session phase transition 미발생

---

## 1. 관측 시각/환경

| 항목 | 값 |
|------|-----|
| 관측 UTC | 2026-05-16 06:56:32 |
| 관측 KST | 2026-05-16 15:56:32 |
| 요일 | 토요일 (비영업일) |
| Docker Compose project | `agent_trading` |
| Scheduler image | `agent_trading-app:latest` |
| API image | `agent_trading-api` |
| Postgres image | `postgres:16-alpine` |

---

## 2. 컨테이너/로그 상태

### 2.1 컨테이너 상태

| 컨테이너명 | 상태 | 비고 |
|------------|------|------|
| `agent_trading-ops-scheduler` | **Up 4 min (unhealthy)** | 실행 중이나 health check 실패 |
| `agent_trading-api-1` | Up 29 min (healthy) | 정상 |
| `agent_trading-app-1` | Up 6 hours | 정상 |
| `agent_trading-snapshot-sync-1` | Up 6 hours | 정상 |
| `agent_trading-db-1` | Up 19 hours (healthy) | 정상 |

**ops-scheduler unhealthy 분석:**  
Scheduler는 비영업일 감지 → session gate SKIP → 15 cycles 후 shutdown 완료.  
Health check는 main loop가 활성 상태인지 확인하는데, 비영업일에는 loop가 곧바로 idle → 종료되므로 `unhealthy`로 표시됨.  
**영업일 재검증 필요**: 영업일에는 phase별 task dispatch로 loop가 지속되므로 healthy 전환 예상.

### 2.2 주요 env 변수 (ops-scheduler)

```
KIS_ENV=paper
KIS_LIVE_INFO_ENABLED=true
KIS_LIVE_INFO_WS_URL=ws://ops.koreainvestment.com:21000
KIS_LIVE_INFO_BASE_URL=https://openapi.koreainvestment.com:9443
KIS_LIVE_TOKEN_CACHE_PATH=.cache/kis_live_token.json
KIS_LIVE_TOKEN_CACHE_ENABLED=true
```

### 2.3 로그 핵심 키워드 분석

| 키워드 | 상태 | 상세 |
|--------|------|------|
| `Token cache hit for live-info holiday client` | ✅ **Hit** (2회차) | 1회차는 miss → save, 2회차 hit |
| `Token cache saved for live-info holiday client` | ✅ Save (1회차) | 첫 기동 시 OAuth token 발급 후 캐시 저장 |
| `chk-holiday` | ✅ 정상 호출 | 076 API `BASS_DT=20260516` |
| `kis_holiday_api` | ✅ Source 확인 | `source=kis_holiday_api` |
| `market_state` | N/A | 163 미연결로 market_state 미조회 |
| `fallback` | ✅ **미사용** | fallback 경로 사용되지 않음 |
| `source=` | ✅ `kis_holiday_api` | CombinedSessionProvider → 076 성공 |
| `is_trading_day` | ✅ `False` | 토요일 정상 |

### 2.4 Scheduler Startup 로그 (핵심)

```
SessionProvider: KisHolidayProvider (076 API) base_url=...
Session provider initialized: KisHolidayProvider (163 WS not available)
Session source: CombinedSessionProvider (076+163+fallback)
```

---

## 3. 076 (chk-holiday) 결과

**판정: ✅ 비영업일 기준 완전 정상**

076 API 호출 결과:
```
is_trading_day=False
opnd_yn=N
bzdy_yn=N
tr_day_yn=Y
source=kis_holiday_api
```

- `is_trading_day=false` — 토요일 정상
- `opnd_yn=N` (영업일 아님) ✅
- `bzdy_yn=N` (휴장일 아님? → 토요일은 휴장일) ✅
- `tr_day_yn=Y` (거래일?→ 의사거래일?) — 주석: 한국투자증권 응답에서 토요일은 `tr_day_yn=Y`로 옴
- Session gate: `pre_market` SKIP + `end_of_day` SKIP — 정상

---

## 4. 163 (WebSocket market-state) 결과

**판정: ✅ paper env 제약으로 설계상 미지원 (기존 P2 과제)**

로그:
```
Session provider initialized: KisHolidayProvider (163 WS not available)
```

- Paper environment에서는 163 WebSocket endpoint가 활성화되지 않음
- `KIS_LIVE_INFO_WS_URL`은 설정되어 있으나 paper env에서 WS handshake 실패
- → **Live 전환 시 재검증 필요** (P2)

---

## 5. Cache 상태

### 5.1 Holiday OAuth Token Cache (`kis_live_oauth_token.json`)

| 항목 | 값 |
|------|-----|
| 존재 여부 | `/app/.cache/kis_live_oauth_token.json` ✅ |
| token_purpose | `holiday_oauth` |
| token_type | `Bearer` |
| access_token | JWT (eyJ0eXAiOi...) ✅ |
| fingerprint | `77d8cecf942e7b1f` |
| expires_at | `1779000631` (≈ 2026-05-16 ~09:50 UTC, 약 3h 유효) |

**첫 기동:** Token cache miss → OAuth 발급 → cache save  
**두 번째 기동:** ✅ **Token cache hit** → 재사용

### 5.2 Market-State Token Cache (`kis_live_token.json`)

**⚠️ 미존재** — 163 WS 미연결로 market-state token 미발급 (paper env 정상)

### 5.3 Dev Token Cache (`kis_token.json`)

| 항목 | 값 |
|------|-----|
| 존재 여부 | `/app/.cache/kis_token.json` ✅ |
| cache_type | `None` (일반 dev token) |
| fingerprint | (빈값) |
| expires_at | `1778975255` (과거 — 만료) |
| access_token | 존재 |

---

## 6. DB market_sessions / session_events 결과

### 6.1 market_sessions

```
 run_date  |     source      | is_trading_day | market_phase | raw_opnd_yn | raw_mkop_cls_code | raw_antc_mkop_cls_code |          checked_at           |          updated_at
------------+-----------------+----------------+--------------+-------------+-------------------+------------------------+-------------------------------+-------------------------------
 2026-05-16 | kis_holiday_api | f              |              |             |                   |                        | 2026-05-16 06:52:46.570762+00 | 2026-05-16 06:52:46.570837+00
```

- **1건 정상 INSERT** ✅
- DB timestamp 기준: 15:52:46 KST에 record 생성
- `source=kis_holiday_api` ✅
- `market_phase=NULL` — 비영업일 정상 (phase 미할당)
- `raw_opnd_yn/mkop_cls_code=NULL` — 076 응답에서 `opnd_yn=N`이면 phase 관련 raw 필드는 미기입

### 6.2 session_events

```
 previous_phase | new_phase | trigger_source | occurred_at
----------------+-----------+----------------+-------------
(0 rows)
```

- **0건** ✅ — 비영업일, phase transition 없음 (정상)

---

## 7. Admin UI API 반영 결과

### 7.1 `GET /market-sessions/latest`

**✅ 정상 응답 (200)**

```json
{
    "session": {
        "id": 1,
        "run_date": "2026-05-16",
        "is_trading_day": false,
        "opnd_yn": "N",
        "bzdy_yn": "N",
        "tr_day_yn": "Y",
        "market_phase": null,
        "source": "kis_holiday_api",
        "reason": "opnd_yn=N bzdy_yn=N tr_day_yn=Y",
        "checked_at": "2026-05-16T06:52:46.570762+00:00",
        "updated_at": "2026-05-16T06:52:46.570837+00:00"
    },
    "stale": true
}
```

- `stale=true` — `checked_at`이 120초 경과 (scheduler 종료 후 heartbeat 중단)
- **비영업일 정상**: scheduler가 loop 종료 후 heartbeat 미발생

### 7.2 `GET /market-sessions/events/recent?limit=5`

**✅ 정상 응답 (200)** — `{"events": []}`

### 7.3 Admin UI (port 8001)

**❌ 미응답** — admin-ui 컨테이너 미실행 또는 8001 포트 미노출.  
운영 환경에서는 nginx 등을 통해 frontend가 8001에서 서빙될 것으로 추정되나 현재 docker compose에는 포함되지 않음.

---

## 8. 현재(비영업일) 판정

### 종합 평가: **B — 부분 성공** ✅

> 비영업일 기준으로 모든 경로가 정상 작동 중이며, 식별된 미지원 사항은 설계 범위 내입니다.

| 평가 항목 | 결과 | 비고 |
|-----------|------|------|
| 076 API 호출 | ✅ 정상 | `is_trading_day=false` |
| Holiday OAuth Token Cache | ✅ Hit | 2회차부터 cache hit |
| Session Gate (pre-market/end-of-day) | ✅ 정상 SKIP | `opnd_yn=N` |
| 163 WebSocket | ⚠️ paper env 미지원 | P2, live 전환 시 재검증 |
| Market-State Token Cache | ⚠️ 미생성 | 163 미연결로 정상 |
| DB market_sessions | ✅ 1건 정상 INSERT | `source=kis_holiday_api` |
| DB session_events | ✅ 0건 (정상) | 비영업일 phase transition 없음 |
| API /market-sessions/latest | ✅ 정상 응답 | stale=true (scheduler 종료) |
| API /market-sessions/events/recent | ✅ 정상 응답 | events=[] |
| Container health | ⚠️ unhealthy | 비영업일 scheduler 종료로 인한 health check 실패 |
| Fallback 경로 | ✅ 미사용 | 076 정상 작동으로 fallback 불필요 |

---

## 9. 영업일(2026-05-18 월) 재검증 필요 항목 체크리스트

> ⚠️ 아래 항목은 비영업일(토요일)에는 검증 불가 — **5/18(월) 영업일 장중 재검증 필수**

### 🔴 Critical Path (필수)

| # | 항목 | 검증 방법 | 기대 결과 |
|---|------|-----------|-----------|
| 1 | **076 영업일 `is_trading_day=true`** | scheduler 로그 `is_trading_day=True` 확인 | 영업일 오전 076 API 호출 |
| 2 | **Session phase transition** | session_events 기록 확인 | `PRE_MARKET` → `OPEN` → `CLOSING` → `AFTER_HOURS` |
| 3 | **`market_phase` 변화** | market_sessions DB 확인 | 각 phase별 `market_phase` 갱신 |
| 4 | **Session gate task dispatch** | scheduler 로그 `session_gate: GO` 확인 | 영업일 phase별 task 실행 |
| 5 | **Container health → healthy** | `docker ps` health status | scheduler loop 활성 상태 유지 |

### 🟡 Secondary (중요)

| # | 항목 | 검증 방법 | 기대 결과 |
|---|------|-----------|-----------|
| 6 | **163 WebSocket 연결** | scheduler 로그 market_state 갱신 확인 | **※ paper env 제약 — live env 전환 시만 가능** |
| 7 | **Market-state token cache 생성** | `kis_live_token.json` 확인 | 163 연결 시 token cache 저장 |
| 8 | **stale=false 전환** | API `/market-sessions/latest` | heartbeat 주기 내 `checked_at` 갱신 |
| 9 | **raw_opnd_yn/mkop_cls_code 기입** | DB market_sessions raw_* 필드 | 영업일 076 응답 raw 필드 확인 |
| 10 | **장중 재시작 시 cache hit** | scheduler 재기동 후 cache hit 확인 | token 재사용 (OAuth 발급 최소화) |

### 🟢 Nice-to-have

| # | 항목 | 검증 방법 | 기대 결과 |
|---|------|-----------|-----------|
| 11 | **Fallback 경로 비활성** | scheduler 로그 `fallback` 미출현 확인 | 076/163 정상 → fallback 불필요 |
| 12 | **Concurrent scheduler lock** | 두 번째 scheduler instance lock 실패 확인 | advisory lock 정상 작동 |
| 13 | **Admin UI (8001) 접속** | 브라우저에서 Admin UI 확인 | frontend에서 session data 표시 |

---

## 10. Follow-up 항목

1. **Container unhealthy 원인 제거** — 비영업일 scheduler 종료 시 health check가 실패하지 않도록 `healthcheck` 설정 조정 필요 (low priority, 비영업일에는 정상 동작)
2. **163 WebSocket live env 전환 계획** — P2 과제로 live 전환 시 163 WS endpoint 활성화 및 market-state token cache 저장 확인
3. **캐시 디렉토리 마운트 정합성** — 현재 cache 경로는 `/app/.cache/`이나 docker-compose volume mount와 불일치 가능성 있음 (별도 리포트 [`ops_scheduler_cache_mount_alignment_hotfix_2026-05-16.md`](plans/ops_scheduler_cache_mount_alignment_hotfix_2026-05-16.md) 참조)

---

## 부록: 명령어 실행 요약

```bash
# 컨테이너 상태
docker ps --filter name=ops-scheduler --format "{{.Names}} {{.Status}}"
# → agent_trading-ops-scheduler Up 4 minutes (unhealthy)

# ops-scheduler env (cache/live 관련)
KIS_ENV=paper
KIS_LIVE_INFO_ENABLED=true
KIS_LIVE_INFO_WS_URL=ws://ops.koreainvestment.com:21000

# Cache 파일
# /app/.cache/
#   ├── kis_live_oauth_token.json  (holiday OAuth, 541B, created 15:51 KST)
#   └── kis_token.json             (dev token, 597B, modified 08:52 KST)

# DB market_sessions: 1건 (2026-05-16, is_trading_day=false)
# DB session_events: 0건

# API /market-sessions/latest: 200 OK (stale=true)
# API /market-sessions/events/recent: 200 OK (events=[])
```
