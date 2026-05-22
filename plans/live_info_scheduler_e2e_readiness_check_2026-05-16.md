# live-info 운영정보 경로 활성화 — 사전 점검 및 E2E 실행 체크리스트

> **작성일**: 2026-05-16  
> **목적**: `KIS_LIVE_INFO_ENABLED=true` 전환 전, 코드/설정/compose wiring이 준비되었는지 정적 분석  
> **제약**: Ask 모드 — 코드 수정/실행 없이 문서 분석만 수행

---

## 1. 현재 wiring 준비 상태 판정

### 1.1 `.env` — live-info 관련 키 설정 현황

| 키 | 값 | 상태 |
|---|---|---|
| `KIS_LIVE_INFO_ENABLED` | `false` | ✅ 정의됨 (전환 필요: `true`) |
| `KIS_LIVE_INFO_APP_KEY` | `"PScDVLqkufdKEEunAe008QZtZuwqPVA7aK2S"` | ✅ 정의됨 |
| `KIS_LIVE_INFO_APP_SECRET` | `"8ZH+IMoerQikAL5Ejg47VmpTaT3/..."` | ✅ 정의됨 |
| `KIS_LIVE_INFO_BASE_URL` | `"https://openapi.koreainvestment.com:9443"` | ✅ 정의됨 |
| `KIS_LIVE_INFO_WS_URL` | `"ws://ops.koreainvestment.com:21000"` | ✅ 정의됨 |
| `KIS_LIVE_TOKEN_CACHE_ENABLED` | `true` | ✅ 정의됨 |
| `KIS_LIVE_TOKEN_CACHE_PATH` | `.cache/kis_live_token.json` | ✅ 정의됨 |
| `KIS_ENV` | `paper` | ✅ 정의됨 (paper 유지) |

**판정**: ✅ 모든 live-info env var가 `.env`에 정의되어 있음.  
**필요 조치**: `KIS_LIVE_INFO_ENABLED=false` → `true` 로 변경만 하면 됨.

### 1.2 `docker-compose.yml` — env wiring 현황

| 서비스 | live-info env 전달 | 상태 |
|---|---|---|
| `ops-scheduler` | `KIS_LIVE_INFO_ENABLED`, `_APP_KEY`, `_APP_SECRET`, `_BASE_URL`, `_WS_URL`, `_TOKEN_CACHE_ENABLED`, `_TOKEN_CACHE_PATH` 모두 `${...}`로 전달 | ✅ 완전 wiring |
| `api` | 동일하게 7개 live-info env var 전달 | ✅ 완전 wiring |
| `app` | 동일하게 7개 live-info env var 전달 | ✅ 완전 wiring |
| `snapshot-sync` | 동일하게 7개 live-info env var 전달 | ✅ 완전 wiring |

**주요 발견**:
- `KIS_LIVE_TOKEN_CACHE_ENABLED` 기본값: `${KIS_LIVE_TOKEN_CACHE_ENABLED:-true}` — `.env`에 `true`로 설정되어 있으므로 Docker 내부에서도 `true`로 전달됨
- `snapshot-sync`의 `restart` 정책: `"no"` (line 245) — 의도대로 설정됨
- `ops-scheduler`의 `healthcheck`: 60초 간격, 120초 heartbeat threshold 기반 검증 (line 301-305)

### 1.3 `settings.py` — AppSettings 필드 기본값

| 필드 | env var 이름 | 기본값 | 비고 |
|---|---|---|---|
| `kis_live_token_cache_enabled` | `KIS_LIVE_TOKEN_CACHE_ENABLED` | `false` | `_resolve_kis_live_token_cache_enabled()`에서 `"false"`가 기본 |
| `kis_live_token_cache_path` | `KIS_LIVE_TOKEN_CACHE_PATH` | `.cache/kis_live_token.json` | |
| `kis_live_info_ws_url` | `KIS_LIVE_INFO_WS_URL` | `""` (빈 문자열) | |

**⚠️ 중요 발견**:  
`settings.py`에는 `kis_live_info_enabled`, `kis_live_info_app_key`, `kis_live_info_app_secret`, `kis_live_info_base_url` 필드가 **정의되어 있지 않음**.  
이 값들은 `settings.py`의 `AppSettings` dataclass를 통하지 않고, `market_session.py`의 `create_session_provider()`에서 직접 `os.getenv()`로 읽음.

### 1.4 `market_session.py` — 076 API (국내휴장일조회) 연결

```python
# create_session_provider() at market_session.py:439-477
enabled = os.getenv("KIS_LIVE_INFO_ENABLED", "false").strip().lower() == "true"
app_key = os.getenv("KIS_LIVE_INFO_APP_KEY", "").strip()
app_secret = os.getenv("KIS_LIVE_INFO_APP_SECRET", "").strip()
base_url = os.getenv("KIS_LIVE_INFO_BASE_URL", "").strip()

if enabled and app_key and app_secret:
    base = base_url or "https://openapi.koreainvestment.com:9443"
    client = KISHolidayClient(app_key=app_key, app_secret=app_secret, base_url=base)
    return KisHolidayProvider(holiday_client=client)
else:
    return FallbackSessionProvider()
```

**판정**: ✅ `KIS_LIVE_INFO_ENABLED=true` + credential 3종이 모두 있으면 `KisHolidayProvider` (076 API) 사용.  
Fallback은 `FallbackSessionProvider` (weekday heuristic).

### 1.5 `market_state_client.py` — 163 WebSocket (장운영정보) 연결

**핵심 로직 흐름**:

1. **`_init_market_state_provider()`** (`run_near_real_ops_scheduler.py:782-815`):
   - `KIS_LIVE_INFO_ENABLED=true` 확인
   - `KIS_APP_KEY` / `KIS_APP_SECRET` (paper credential) 사용
   - `AppSettings()` 생성 → `KisMarketStateClient(settings, app_key, api_secret)`
   - `KisMarketStateClient.__init__()`에서 `settings.kis_env`가 `paper`면 **connect() skipped** + `is_connected=False`

2. **`KisMarketStateClient`** (`market_state_client.py:290`):
   - Paper env에서는 `connect()` 호출 시 `"163 WebSocket not supported in paper env"` 로그 + early return
   - `is_connected`는 `False` 유지
   - Live env에서만 실제 WebSocket 연결 시도

3. **Approval key cache** (`market_state_client.py:200-256`):
   - `_load_live_info_approval_key_cache()`: `settings.kis_live_token_cache_enabled` 확인 → 파일 로드
   - `_save_live_info_approval_key_cache()`: approval key를 `.cache/kis_live_token.json`에 저장
   - Fingerprint: `live_info_{app_key}_{api_secret}`의 SHA-256

4. **WebSocket URL resolution** (`market_state_client.py:727-754`):
   - 우선순위: ① `_base_ws_url` (명시적) ② `KIS_LIVE_INFO_WS_URL` ③ `KIS_BASE_WS_URL` ④ HTTP base URL fallback
   - `.env`에 `KIS_LIVE_INFO_WS_URL=ws://ops.koreainvestment.com:21000` → `ws://ops.koreainvestment.com:21000/websocket`

**⚠️ 중요 발견 — 163 WebSocket은 paper env에서 skip됨**:
- `KisMarketStateClient.__init__()`에서 `settings.kis_env`가 `paper`면 `_is_paper=True` 설정
- `connect()` 호출 시 `"163 WebSocket not supported in paper env"` 로그 + early return
- 따라서 `KIS_ENV=paper` 상태에서는 163 WebSocket이 **절대 연결되지 않음**
- 076 API (국내휴장일)는 `KIS_LIVE_INFO_ENABLED=true`만으로 동작 (paper env에서도 가능)

### 1.6 Admin UI — session 상태 표시

- `OperationsDashboardView.tsx`에서 `GET /api/market-sessions/latest`와 `GET /api/market-sessions/events/recent` 호출
- API 라우트: `src/agent_trading/api/routes/sessions.py` — `market_sessions` 테이블에서 최신 행 조회
- `healthy` 판정: `checked_at`이 120초 이내면 healthy
- **판정**: ✅ Admin UI는 이미 session 상태를 볼 수 있는 구조. 별도 수정 불필요.

---

## 2. wiring 준비 상태 요약

| 구성 요소 | 준비 상태 | 비고 |
|---|---|---|
| `.env` live-info 키 | ✅ 완료 | `KIS_LIVE_INFO_ENABLED=true`로 변경만 필요 |
| `docker-compose.yml` env wiring | ✅ 완료 | 모든 서비스에 live-info env var 전달됨 |
| `settings.py` AppSettings | ⚠️ 부분 | `kis_live_info_enabled` 등 일부 필드는 미정의 (os.getenv 직접 사용) |
| 076 API (국내휴장일) | ✅ 준비 완료 | `create_session_provider()`에서 직접 os.getenv 사용 |
| 163 WebSocket (장운영정보) | ⚠️ paper env skip | `KIS_ENV=paper`면 connect() skipped. Live 전환 필요 |
| Live-info token cache | ✅ 준비 완료 | `settings.py`에 `kis_live_token_cache_enabled`/`_path` 정의됨 |
| Admin UI session 표시 | ✅ 준비 완료 | API 라우트 + UI 컴포넌트 모두 구현됨 |
| ops-scheduler entrypoint | ✅ 준비 완료 | `scripts/run_ops_scheduler.py` → `run_near_real_ops_scheduler.py` canonical 경로 |

---

## 3. 사용자 실행 체크리스트

### 3.1 사전 준비 (수동)

```bash
# 1. .env 파일에서 KIS_LIVE_INFO_ENABLED=true 로 변경
#    (파일 편집기로 직접 수정)

# 2. Docker 컨테이너 상태 확인
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 3. 기존 ops-scheduler 로그 확인 (50줄)
docker logs agent_trading-ops-scheduler 2>&1 | tail -50
```

### 3.2 Docker 재기동 (Code 모드 필요)

```bash
# 4. ops-scheduler 재시작 (env var 변경 반영)
docker compose up -d ops-scheduler

# 5. (선택) api 서비스도 재시작
docker compose up -d api
```

### 3.3 로그 확인 포인트

```bash
# 6. ops-scheduler 로그 실시간 확인
docker logs -f agent_trading-ops-scheduler 2>&1

# 확인해야 할 로그 메시지:
# ✅ "SessionProvider: KisHolidayProvider (076 API)" — 076 성공
# ✅ "Live-info enabled: true" — startup info
# ✅ "Market state provider: skipped (KIS_LIVE_INFO_ENABLED != true)" — paper env에서 정상
#    (또는 live env라면 "KisMarketStateClient: connected")
# ✅ "Live-info token cache: hit" 또는 "miss" — token cache 동작 확인
```

### 3.4 DB 확인 쿼리

```sql
-- 7. market_sessions 테이블 확인 (076 API 결과)
SELECT run_date, is_trading_day, opnd_yn, bzdy_yn, tr_day_yn, source, checked_at
FROM trading.market_sessions
ORDER BY checked_at DESC
LIMIT 5;

-- 8. session_events 테이블 확인 (phase transition)
SELECT se.id, se.previous_phase, se.new_phase, se.trigger_source, se.occurred_at
FROM trading.session_events se
ORDER BY se.occurred_at DESC
LIMIT 10;
```

### 3.5 Health check

```bash
# 9. API health check
curl -s http://localhost:8000/health/readyz | jq .

# 10. market-sessions API
curl -s http://localhost:8000/api/market-sessions/latest | jq .
curl -s http://localhost:8000/api/market-sessions/events/recent | jq .
```

### 3.6 Admin UI 확인

- 브라우저에서 `http://localhost:8000` 접속
- Operations Dashboard에서 Session Status 섹션 확인
  - `source`: `kis_holiday_provider` (076 성공) 또는 `fallback`
  - `is_trading_day`: `true`/`false`
  - `market_phase`: phase 값
  - `healthy`: heartbeat 120초 이내면 `true`

---

## 4. 성공 판정 기준

| # | 항목 | 성공 조건 | 확인 방법 |
|---|---|---|---|
| 1 | 076 API 성공 | 로그에 `"SessionProvider: KisHolidayProvider (076 API)"` 출력 | `docker logs` |
| 2 | 076 API 응답 | `market_sessions` 테이블에 `source='kis_holiday_provider'` 행 생성 | DB 쿼리 |
| 3 | 163 WebSocket (live env) | 로그에 `"KisMarketStateClient: connected"` 출력 | `docker logs` |
| 4 | 163 WebSocket (paper env) | 로그에 `"163 WebSocket not supported in paper env"` 출력 (정상) | `docker logs` |
| 5 | Live token cache hit | 로그에 `"Live-info token cache: hit"` 출력 | `docker logs` |
| 6 | market_sessions 갱신 | `checked_at`이 최근 120초 이내 | DB 쿼리 or API |
| 7 | Admin UI 반영 | Operations Dashboard에 session 정보 표시 | 브라우저 확인 |
| 8 | session_events 기록 | phase transition 이벤트가 `session_events` 테이블에 기록 | DB 쿼리 or API |

---

## 5. 실패 시 확인할 로그 포인트

| 증상 | 확인할 로그 | 원인 |
|---|---|---|
| 076 API 미호출 | `"SessionProvider: FallbackSessionProvider"` | `KIS_LIVE_INFO_ENABLED`가 `true`가 아님, 또는 APP_KEY/SECRET 누락 |
| 076 API 401 | `"KISHolidayClient: 401"` | live-info APP_KEY/SECRET이 유효하지 않음 |
| 076 API timeout | `"KISHolidayClient: timeout"` | BASE_URL 오류 또는 네트워크 문제 |
| 163 WS 미연결 | `"163 WebSocket not supported in paper env"` | `KIS_ENV=paper` — 정상 동작 |
| 163 WS 연결 실패 | `"KisMarketStateClient: connection error"` | WS_URL 오류, approval key 발급 실패 |
| Token cache miss | `"Live-info token cache: miss reason=..."` | 파일 없음, fingerprint 불일치, 만료 |
| Admin UI 미표시 | `"GET /market-sessions/latest"` error | API 서비스 미실행 또는 DB 연결 문제 |
| Scheduler 미기동 | `"Scheduler advisory lock NOT acquired"` | 다른 인스턴스가 실행 중 |

---

## 6. Code 모드가 필요한 작업 범위

| 작업 | 설명 | 우선순위 |
|---|---|---|
| `.env` 수정 | `KIS_LIVE_INFO_ENABLED=false` → `true` | P0 (필수) |
| `docker compose up -d ops-scheduler` | env var 변경 반영을 위한 재시작 | P0 (필수) |
| `docker logs` 확인 | 로그 분석 | P0 (필수) |
| DB 쿼리 실행 | `market_sessions`, `session_events` 확인 | P1 |
| API health check | `curl` 명령 실행 | P1 |
| Admin UI 확인 | 브라우저에서 session 상태 확인 | P1 |
| (선택) `KIS_ENV=live` 전환 | 163 WebSocket 활성화 (실제 운영 전환 시) | P2 |

---

## 7. Mermaid: live-info 활성화 시 데이터 흐름

```mermaid
flowchart TD
    subgraph .env["📄 .env"]
        A[KIS_LIVE_INFO_ENABLED=true]
        B[KIS_LIVE_INFO_APP_KEY]
        C[KIS_LIVE_INFO_APP_SECRET]
        D[KIS_LIVE_INFO_BASE_URL<br/>https://openapi.koreainvestment.com:9443]
        E[KIS_LIVE_INFO_WS_URL<br/>ws://ops.koreainvestment.com:21000]
        F[KIS_LIVE_TOKEN_CACHE_ENABLED=true]
        G[KIS_LIVE_TOKEN_CACHE_PATH<br/>.cache/kis_live_token.json]
    end

    subgraph docker-compose["🐳 docker-compose.yml"]
        H[ops-scheduler<br/>env: 모든 live-info var 전달]
        I[api<br/>env: 모든 live-info var 전달]
    end

    subgraph scheduler["⚙️ ops-scheduler (run_ops_scheduler.py)"]
        J[_init_market_state_provider]
        K[_init_session_provider → create_session_provider]
    end

    subgraph market_session["📦 market_session.py"]
        L[os.getenv KIS_LIVE_INFO_ENABLED]
        M{enabled && app_key && app_secret?}
        N[KisHolidayProvider<br/>076 API: 국내휴장일조회]
        O[FallbackSessionProvider<br/>weekday heuristic]
    end

    subgraph market_state["📦 market_state_client.py"]
        P[KisMarketStateClient]
        Q{settings.kis_env == paper?}
        R[connect() skipped<br/>163 WS not supported]
        S[connect() → approval key →<br/>WebSocket 연결]
        T[_load_live_info_approval_key_cache]
        U[_save_live_info_approval_key_cache]
    end

    subgraph db["🗄️ PostgreSQL"]
        V[market_sessions 테이블]
        W[session_events 테이블]
    end

    subgraph admin_ui["🖥️ Admin UI"]
        X[OperationsDashboardView<br/>GET /market-sessions/latest<br/>GET /market-sessions/events/recent]
    end

    .env --> docker-compose
    docker-compose --> H
    docker-compose --> I
    H --> J
    H --> K
    K --> L
    L --> M
    M -->|Yes| N
    M -->|No| O
    N --> V
    O --> V
    J --> P
    P --> Q
    Q -->|paper| R
    Q -->|live| S
    S --> T
    S --> U
    T -->|cache hit| S
    U -->|cache save| S
    P --> W
    I --> X
    V --> X
    W --> X
```

---

## 8. 결론

**현재 wiring 준비 상태: ✅ 대부분 준비 완료**

- `.env`에 모든 live-info credential이 이미 정의되어 있음 (`KIS_LIVE_INFO_ENABLED=false`만 변경 필요)
- `docker-compose.yml`의 모든 서비스(`ops-scheduler`, `api`, `app`, `snapshot-sync`)에 live-info env var가 완전히 wiring됨
- 076 API (국내휴장일)는 `KIS_LIVE_INFO_ENABLED=true`만으로 paper env에서도 즉시 활성화 가능
- 163 WebSocket (장운영정보)는 `KIS_ENV=paper`에서는 skip되며, live 전환 시에만 활성화됨
- Admin UI는 이미 session 상태를 표시할 수 있는 구조
- `ops-scheduler` entrypoint는 canonical 경로(`scripts/run_ops_scheduler.py`) 사용 중

**실행 전 필요 조치 단 1가지**: `.env`에서 `KIS_LIVE_INFO_ENABLED=false` → `true` 변경
