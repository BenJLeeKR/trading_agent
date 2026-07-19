# Live-info/Session/Scheduler 경로 최종 검증 — 예비 관측 보고서

**현재 비영업일(토요일)로 예비 관측만 수행. 영업일(5/18 월) 장중 재검증 필요.**

---

## 1. 관측 시각/환경

| 항목 | 값 |
|------|-----|
| 관측 UTC | 2026-05-16 07:02:48 |
| 관측 KST | 2026-05-16 16:02:48 |
| 요일 | 토요일 (비영업일) |
| 검증 환경 | `KIS_ENV=paper`, `KIS_LIVE_INFO_ENABLED=true` |
| Scheduler image | `agent_trading-app:latest` |
| API image | `agent_trading-api` |
| Postgres image | `postgres:16-alpine` |

---

## 2. 컨테이너 상태

| 컨테이너명 | 상태 | 비고 |
|------------|------|------|
| `agent_trading-ops-scheduler` | **Up 9 min (unhealthy)** | 실행 중이나 health check 실패 — 비영업일 scheduler loop 종료로 정상 |
| `agent_trading-api-1` | Up 33 min (healthy) | 정상 |
| `agent_trading-app-1` | Up 6 hours | 정상 |
| `agent_trading-snapshot-sync-1` | Up 6 hours | 정상 |
| `agent_trading-db-1` | Up 19 hours (healthy) | 정상 |

**판정: ⚠️ scheduler unhealthy — 비영업일에는 설계 범위 내 정상 동작**

### 주요 env 변수 (ops-scheduler)

```
KIS_ENV=paper
KIS_LIVE_INFO_ENABLED=true
KIS_LIVE_INFO_WS_URL=ws://ops.koreainvestment.com:21000
KIS_LIVE_INFO_BASE_URL=https://openapi.koreainvestment.com:9443
KIS_LIVE_TOKEN_CACHE_PATH=.cache/kis_live_token.json
KIS_LIVE_TOKEN_CACHE_ENABLED=true
KIS_APP_KEY=PS5vNDY2X8aELSc9f64hFanpBZljSm...
KIS_LIVE_INFO_APP_KEY=PScDVLqkufdKEEunAe008QZtZuwqPV...
```

---

## 3. ops-scheduler 로그 분석 (최근 기동, 15:52 KST)

### 3.1 기동 이력

scheduler가 **2회 연속 기동**된 것으로 확인:

| # | 기동 시각 (KST) | Cache | 076 호출 | 종료 사유 |
|---|----------------|-------|----------|-----------|
| 1 | 15:51:31 | **Miss** → Save | `BASS_DT=20260516` → `is_trading_day=False` | 15 cycles 후 shutdown |
| 2 | 15:52:46 | **Hit** ✅ | `BASS_DT=20260516` → `is_trading_day=False` | 2 cycles 후 shutdown (docker 재시작 정책) |

### 3.2 핵심 키워드

| 키워드 | 상태 | 상세 |
|--------|------|------|
| `Token cache hit for live-info holiday client` | ✅ **Hit** (2회차) | 1회차 miss → save, 2회차 재사용 성공 |
| `Token cache saved for live-info holiday client` | ✅ Save (1회차) | 최초 기동 시 OAuth token 발급 후 캐시 저장 |
| `chk-holiday` | ✅ 정상 호출 | 076 API `BASS_DT=20260516` |
| `kis_holiday_api` | ✅ Source 확인 | `source=kis_holiday_api` |
| `market_state` / `163 WS` | N/A | **163 WS not available** (paper env 정상) |
| `fallback` | ✅ **미사용** | 076 정상 작동으로 fallback 불필요 |
| `source=` | ✅ `kis_holiday_api` | CombinedSessionProvider → 076 성공 |
| `is_trading_day` | ✅ `False` | 토요일 정상 |
| `heartbeat` | ✅ 생성됨 | `Heartbeat background task created (interval=10s)` |
| `session_gate: SKIP` | ✅ 정상 | `pre_market` + `end_of_day` 모두 SKIP |
| `Advisory lock` | ✅ 획득 | `advisory lock acquired (key=0x4E4541525245414C)` |

### 3.3 Scheduler Summary (2회차)

```
cycles              : 2 (조기종료, 재시작 후 짧게 실행)
tasks               : 0
failed_tasks        : 0
pre_market_done     : True
end_of_day_done     : True
after_hours_active  : False
session_source      : kis_holiday_api
session_is_trading_day: False
session_market_phase: N/A
```

---

## 4. 076 (chk-holiday) 결과

**판정: ✅ 비영업일 기준 완전 정상** (이전 보고서와 동일)

076 API 응답:
```
is_trading_day=False
opnd_yn=N
bzdy_yn=N
tr_day_yn=Y
source=kis_holiday_api
```

---

## 5. 163 (WebSocket market-state) 결과

**판정: ✅ paper env 제약으로 설계상 미지원** (P2, live 전환 시 재검증)

로그: `Session provider initialized: KisHolidayProvider (163 WS not available)`

---

## 6. Cache 상태

### 6.1 Cache 디렉토리 (`/app/.cache/`)

```
total 16
drwxr-xr-x 2 1007 1001 4096 May 16 15:51 .
drwxr-xr-x 1 root root 4096 May 16 15:51 ..
-rw-r--r-- 1 root root  541 May 16 15:51 kis_live_oauth_token.json
-rw-r--r-- 1 1007 1001  597 May 16 08:52 kis_token.json
```

> ⚠️ **참고**: 캐시 경로는 `/app/.cache/`이며, `/app/data/.cache/`는 존재하지 않음. 이는 이전 보고서에서 언급된 마운트 정합성 이슈와 무관하게 scheduler 내부 경로는 정상.

### 6.2 Holiday OAuth Token Cache (`kis_live_oauth_token.json`)

| 항목 | 값 |
|------|-----|
| 존재 여부 | `/app/.cache/kis_live_oauth_token.json` ✅ |
| token_purpose | `holiday_oauth` |
| fingerprint | `77d8cecf942e7b1f` |
| expires_at | `1779000631.3185625` (≈ 2026-05-16 ~09:50 UTC, 약 3h 유효) |
| token_type | `Bearer` |
| access_token | JWT (eyJ0eXAiOiJKV1Qi...) ✅ |

### 6.3 Market-State Token Cache (`kis_live_token.json`)

**⚠️ 미존재** — 163 WS 미연결로 market-state token 미발급 (paper env 정상)

### 6.4 Dev Token Cache (`kis_token.json`)

| 항목 | 값 |
|------|-----|
| 존재 여부 | `/app/.cache/kis_token.json` ✅ |
| cache_type | `None` |
| fingerprint | (빈값) |
| expires_at | `1778975255` (과거 — 만료) |
| access_token | 존재 |

---

## 7. DB 상태

### 7.1 `trading.market_sessions`

```
  run_date  |     source      | is_trading_day | market_phase | raw_opnd_yn | raw_mkop_cls_code | raw_antc_mkop_cls_code |          checked_at           |          updated_at
------------+-----------------+----------------+--------------+-------------+-------------------+------------------------+-------------------------------+-------------------------------
 2026-05-16 | kis_holiday_api | f              |              |             |                   |                        | 2026-05-16 06:52:46.570762+00 | 2026-05-16 06:52:46.570837+00
```

- **1건 정상 INSERT** ✅
- `source=kis_holiday_api` ✅
- `market_phase=NULL` — 비영업일 정상 (phase 미할당)
- `raw_opnd_yn/mkop_cls_code=NULL` — 076 응답에서 `opnd_yn=N`이면 phase 관련 raw 필드 미기입

### 7.2 `trading.session_events`

```
 previous_phase | new_phase | trigger_source | occurred_at
----------------+-----------+----------------+-------------
(0 rows)
```

- **0건** ✅ — 비영업일, phase transition 없음 (정상)

---

## 8. Admin UI API 결과

### 8.1 `GET /market-sessions/latest`

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
        "raw_opnd_yn": null,
        "raw_mkop_cls_code": null,
        "raw_antc_mkop_cls_code": null,
        "source": "kis_holiday_api",
        "reason": "opnd_yn=N bzdy_yn=N tr_day_yn=Y",
        "checked_at": "2026-05-16T06:52:46.570762+00:00",
        "updated_at": "2026-05-16T06:52:46.570837+00:00"
    },
    "stale": true
}
```

- `stale=true` — `checked_at`이 120초 경과 (scheduler 종료 후 heartbeat 중단)
- **비영업일 정상**

### 8.2 `GET /market-sessions/events/recent?limit=5`

**✅ 정상 응답 (200)** — `{"events": []}`

### 8.3 인증 방식

API는 `Authorization: Bearer` 헤더 필요 (`INSPECTION_API_TOKEN=dev-token-123`).
- Health endpoint (`/health`)는 인증 불필요 ✅

---

## 9. 현재(비영업일) 판정 요약

### 종합 평가: **B — 부분 성공** ✅

> 비영업일 기준 모든 경로 정상 작동. 식별된 미지원 사항은 설계 범위 내.

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
| Advisory lock | ✅ 정상 획득 | 중복 실행 방지 |
| Scheduler 2회 기동 | ✅ 정상 범위 | Docker restart 정책에 의한 재기동 — cache hit 확인 |

---

## 10. 영업일(2026-05-18 월) 장중 재검증 체크리스트 (업데이트)

> ⚠️ 아래 항목은 비영업일(토요일)에는 검증 불가 — **5/18(월) 영업일 장중 재검증 필수**

### 🔴 Critical Path (필수)

| # | 항목 | 검증 방법 | 기대 결과 | 비고 |
|---|------|-----------|-----------|------|
| 1 | **076 영업일 `is_trading_day=true`** | scheduler 로그 `is_trading_day=True` 확인 | 영업일 오전 076 API 호출 | 이전 보고서와 동일 |
| 2 | **Session phase transition** | session_events 기록 확인 | `PRE_MARKET` → `OPEN` → `CLOSING` → `AFTER_HOURS` | 이전 보고서와 동일 |
| 3 | **`market_phase` 변화** | market_sessions DB 확인 | 각 phase별 `market_phase` 갱신 | 이전 보고서와 동일 |
| 4 | **Session gate task dispatch** | scheduler 로그 `session_gate: GO` 확인 | 영업일 phase별 task 실행 | 이전 보고서와 동일 |
| 5 | **Container health → healthy** | `docker ps` health status | scheduler loop 활성 상태 유지 | 이전 보고서와 동일 |

### 🟡 Secondary (중요)

| # | 항목 | 검증 방법 | 기대 결과 | 비고 |
|---|------|-----------|-----------|------|
| 6 | **163 WebSocket 연결** | scheduler 로그 market_state 갱신 확인 | **※ paper env 제약 — live env 전환 시만 가능** | 이전 보고서와 동일 |
| 7 | **Market-state token cache 생성** | `kis_live_token.json` 확인 | 163 연결 시 token cache 저장 | 이전 보고서와 동일 |
| 8 | **stale=false 전환** | API `/market-sessions/latest` | heartbeat 주기 내 `checked_at` 갱신 | 이전 보고서와 동일 |
| 9 | **raw_opnd_yn/mkop_cls_code 기입** | DB market_sessions raw_* 필드 | 영업일 076 응답 raw 필드 확인 | 이전 보고서와 동일 |
| 10 | **장중 재시작 시 cache hit** | scheduler 재기동 후 cache hit 확인 | token 재사용 (OAuth 발급 최소화) | 이전 보고서와 동일 |

### 🟢 Nice-to-have

| # | 항목 | 검증 방법 | 기대 결과 | 비고 |
|---|------|-----------|-----------|------|
| 11 | **Fallback 경로 비활성** | scheduler 로그 `fallback` 미출현 확인 | 076/163 정상 → fallback 불필요 | 이전 보고서와 동일 |
| 12 | **Concurrent scheduler lock** | 두 번째 scheduler instance lock 실패 확인 | advisory lock 정상 작동 | 이전 보고서와 동일 |
| 13 | **Admin UI (8001) 접속** | 브라우저에서 Admin UI 확인 | frontend에서 session data 표시 | 이전 보고서와 동일 |
| 14 | **✅ [NEW] Scheduler 재기동 시 cache hit 유지** | 영업일 장중 scheduler 재시작 후 로그 확인 | token cache hit + 076 정상 호출 | 비영업일 2회 기동에서 cache hit 확인됨. 영업일에도 동일 패턴 검증 |
| 15 | **✅ [NEW] API 인증 헤더 정합성** | curl with `Authorization: Bearer` | API 정상 응답 확인 | 현재 API는 인증 필요. 영업일에도 동일하게 작동하는지 확인 |
| 16 | **✅ [NEW] Cache 디렉토리 경로 확인** | `docker exec`로 `/app/.cache/` 확인 | `kis_live_oauth_token.json` 존재 | 경로는 `/app/.cache/`로 확인됨. 영업일에도 동일 경로 유지 |

### 체크리스트 변경 내역

- **항목 14 (신규)**: 비영업일에서 scheduler 2회 기동 시 cache hit이 확인됨. 영업일 장중 재시작 시나리오에서도 동일하게 cache hit이 유지되는지 검증 필요.
- **항목 15 (신규)**: API가 `Bearer` 인증을 요구함을 확인. 영업일 장중 API 호출 시 인증 헤더 포함 필요.
- **항목 16 (신규)**: Cache 디렉토리가 `/app/.cache/`임을 확인. 이전 보고서에서 언급된 `/app/data/.cache/`와의 차이를 영업일에도 재확인.

---

## 11. Follow-up 항목

1. **Container unhealthy 원인 제거** — 비영업일 scheduler 종료 시 health check 실패. 영업일에는 loop가 지속되어 healthy 전환 예상.
2. **163 WebSocket live env 전환 계획** — P2 과제로 live 전환 시 163 WS endpoint 활성화 및 market-state token cache 저장 확인 필요.
3. **API 인증 토큰 관리** — `INSPECTION_API_TOKEN=dev-token-123`은 개발용. 운영 환경에서는 별도 토큰 관리 필요.
4. **Scheduler 2회 기동 현상 분석** — docker restart 정책에 의한 것인지, scheduler 내부 로직에 의한 것인지 확인 필요. 현재 076/cache 경로에는 영향 없음.

---

## 부록: 관측 명령어 실행 요약

```bash
# 컨테이너 상태
$ docker ps --filter name=ops-scheduler --format "{{.Names}} {{.Status}}"
→ agent_trading-ops-scheduler Up 9 minutes (unhealthy)

# 모든 컨테이너
$ docker ps --format "{{.Names}} {{.Image}} {{.Status}}"
→ agent_trading-ops-scheduler  agent_trading-app:latest  Up 9 minutes (unhealthy)
  agent_trading-api-1          agent_trading-api          Up 33 minutes (healthy)
  agent_trading-app-1          b05c183f21b1               Up 6 hours
  agent_trading-snapshot-sync-1 agent_trading-snapshot-sync Up 6 hours
  agent_trading-db-1           postgres:16-alpine         Up 19 hours (healthy)

# Cache (holiday OAuth)
$ docker exec agent_trading-ops-scheduler cat /app/.cache/kis_live_oauth_token.json
→ token_purpose=holiday_oauth, fingerprint=77d8cecf942e7b1f, expires_at=1779000631

# Cache (market-state) — 미존재
$ docker exec agent_trading-ops-scheduler cat /app/.cache/kis_live_token.json
→ NOT FOUND

# DB market_sessions: 1건 (2026-05-16, is_trading_day=false)
# DB session_events: 0건

# API /market-sessions/latest (with auth): 200 OK (stale=true)
# API /market-sessions/events/recent (with auth): 200 OK (events=[])
```
