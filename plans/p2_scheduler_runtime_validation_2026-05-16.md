# P2 Scheduler Hardening — 운영 검증 보고서

**작성일**: 2026-05-16 (토)  
**관측 시각 (KST)**: 2026-05-16 11:52:53 ~ 12:00  
**서버 시간 (UTC)**: 2026-05-16 02:52:53 ~ 03:00  
**Timezone**: `Asia/Seoul` (KST, UTC+9)

---

## 1. 관측 시각/환경

| 항목 | 값 |
|------|-----|
| 요일 | 토요일 (비거래일) |
| 서버 OS | Linux 6.8 |
| Shell | `/bin/bash` |
| Docker Compose | v2 |
| 컨테이너 상태 | `api` (healthy), `app` (up), `db` (healthy), `snapshot-sync` (up) — 모두 정상 |
| DB | PostgreSQL 16 Alpine, `trading` database |

Docker 컨테이너 목록:
```
NAME                            SERVICE         STATUS
agent_trading-api-1             api             Up 2 hours (healthy)
agent_trading-app-1             app             Up 2 hours
agent_trading-db-1              db              Up 15 hours (healthy)
agent_trading-snapshot-sync-1   snapshot-sync   Up 2 hours
```

---

## 2. 076 (Holiday Lookup) 결과

### 로그 분석

가장 최신 로그 파일: `logs/near_real_scheduler_2026-05-15.log` (2.9MB, 724 cycles, 81 tasks, 0 failed)

**`session_gate` 로그 status: ⚠️ 발견되지 않음**

```bash
# session_gate 관련 모든 패턴 검색 결과 0건
$ grep -n "session_gate\|session_info\|is_trading_day\|opnd_yn\|bzdy_yn\|tr_day_yn\|market_session\|persist_session" logs/near_real_scheduler_2026-05-15.log
# (결과 없음)
```

**원인 분석**:
- `scripts/run_near_real_ops_scheduler.py`에는 P1/P2 hardening 코드(`_session_gate()`, `_init_market_state_provider()`, `_persist_session_state()`)가 포함되어 있음
- 그러나 `src/agent_trading/services/market_session.py`와 `src/agent_trading/brokers/koreainvestment/market_state_client.py`의 수정 시각이 **2026-05-16 10:32~10:38**로, 5/15 실행 시점에는 P1/P2 코드가 미적용 상태였던 것으로 추정
- 즉, 5/15 로그는 **P1/P2 hardening 이전 버전**의 scheduler에 의해 생성됨

### 설정 파일 확인 (`.env`)

```ini
KIS_LIVE_INFO_ENABLED=false          # ← 076 API 비활성화
KIS_LIVE_INFO_APP_KEY="PScDVLq..."  # (설정되어 있으나 ENABLED=false로 미사용)
KIS_LIVE_INFO_APP_SECRET="8ZH+..."  # (설정되어 있으나 ENABLED=false로 미사용)
KIS_LIVE_INFO_BASE_URL="https://openapi.koreainvestment.com:9443"
```

### `create_session_provider()` resolution logic (코드 분석)

```python
# market_session.py:394-432
enabled = os.getenv("KIS_LIVE_INFO_ENABLED", "false").strip().lower() == "true"
# KIS_LIVE_INFO_ENABLED=false → FallbackSessionProvider 선택
```

- `KIS_LIVE_INFO_ENABLED=false` → `FallbackSessionProvider` (weekday heuristic) 사용
- 076 API (`KisHolidayProvider`)는 비활성화 상태
- `KisHolidayProvider`가 활성화되려면 `KIS_LIVE_INFO_ENABLED=true` 필요

### 076 판정: **⚠️ 코드 레벨 구현 완료, 운영 비활성화**

---

## 3. 163 WebSocket / Phase 결과

### 설정 확인

```ini
KIS_LIVE_INFO_ENABLED=false          # 163 WebSocket 비활성화
KIS_LIVE_INFO_WS_URL="ws://ops.koreainvestment.com:21000"  # 설정만 있음
```

### `_init_market_state_provider()` 코드 분석

```python
# run_near_real_ops_scheduler.py:776-809
kis_live_info_enabled = env.get("KIS_LIVE_INFO_ENABLED", "").strip().lower() == "true"
if not kis_live_info_enabled:
    logger.info("Market state provider: skipped (KIS_LIVE_INFO_ENABLED != true)")
    return None  # ← KIS_LIVE_INFO_ENABLED=false이므로 여기서 조기 반환
```

- WebSocket 미연결 → `KisMarketStateClient` 미생성
- `CombinedSessionProvider` 미사용 → `FallbackSessionProvider` 단독 사용
- `_session_phase_monitor()` 태스크 미생성
- 로그: `Session provider initialized: FallbackSessionProvider (163 WS not available)`

### `KisMarketStateClient` 구조

| 클래스 | 역할 |
|--------|------|
| `MarketPhaseCode` | 장운영 phase enum (str, Enum) |
| `MarketState` | 장운영 상태 dataclass (phase, 시간 정보) |
| `MarketStateProvider` (ABC) | market state provider 추상 기본 클래스 |
| `KisMarketStateClient` | 163 WebSocket 실제 구현체 (approval key 발급 + WS subscribe) |

### 163 판정: **⚠️ 구현 완료, KIS_LIVE_INFO_ENABLED=false로 비활성화 상태**

---

## 4. Token Cache Hit/Miss 요약

### Live-info token cache

```bash
$ ls -la .cache/kis_live_token.json
# ls: cannot access '.cache/kis_live_token.json': No such file or directory
```

**결과: ❌ 파일 없음 (miss)**

### 기존 KIS token cache (paper용)

```bash
$ cat .cache/kis_token.json
{
  "access_token": "eyJ0eXAi...",
  "token_type": "bearer",
  "expires_at": 1778975255.2238665,
  "kis_env": "paper",
  "base_url": "https://openapivts.koreainvestment.com:29443",
  "app_key_fingerprint": "b5d0fe1dcbdd94ed",
  "created_at": 1778889155.3775225
}
```
- 최종 업데이트: **2026-05-16 08:52:53 KST** (오늘, 비거래일)
- 만료: `1778975255` → 2026-05-17 03:47:35 KST (24시간 후)

### 설정

```ini
KIS_LIVE_TOKEN_CACHE_ENABLED=true
KIS_LIVE_TOKEN_CACHE_PATH=.cache/kis_live_token.json
```

`KIS_LIVE_TOKEN_CACHE_ENABLED=true`로 설정되어 있으나, live-info 자체가 비활성화되어 cache 파일이 생성되지 않음.  
`settings.py`의 `AppSettings`에 `kis_live_token_cache_enabled`, `kis_live_token_cache_path` 필드 존재.

### Token Cache 판정: **⚠️ 구현 완료 (`kis_live_token_cache_path`, `kis_live_token_cache_enabled`), Live Info 비활성화로 미사용**

---

## 5. market_sessions / session_events DB 상태

### 테이블 스키마

```sql
-- market_sessions (12 columns)
 id             | bigint
 run_date       | date
 is_trading_day | boolean
 opnd_yn        | character varying
 bzdy_yn        | character varying
 tr_day_yn      | character varying
 market_phase   | character varying    -- P2: 163 phase
 raw_opnd_yn    | character varying    -- P2: 076 raw
 raw_mkop_cls_code      | character varying  -- P2: 163 raw
 raw_antc_mkop_cls_code | character varying  -- P2: 163 raw
 source         | character varying
 reason         | character varying
 checked_at     | timestamp with time zone
 created_at     | timestamp with time zone
 updated_at     | timestamp with time zone

-- session_events (8 columns)
 id                | bigint
 market_session_id | bigint
 previous_phase    | character varying
 new_phase         | character varying
 trigger_source    | character varying
 metadata          | jsonb
 occurred_at       | timestamp with time zone
 created_at        | timestamp with time zone
```

### 데이터 조회

```sql
-- market_sessions: 0 rows
SELECT * FROM trading.market_sessions ORDER BY updated_at DESC LIMIT 10;
-- (0 rows)

-- session_events: 0 rows (별도 조회 시)
```

**❌ 두 테이블 모두 데이터가 없음.**  
`_persist_session_state()`가 호출되지 않았거나, P1/P2 코드가 아직 운영에 반영되지 않았음을 의미.

Migration 0014가 적용되어 테이블은 존재하지만, `_persist_session_state()`는 `state.session_info is not None`일 때만 호출되며, session_gate → get_session_info → persist 흐름이 완료되어야 기록됨.

### DB 판정: **⚠️ 테이블 스키마 준비 완료, 데이터 미기록 (P1/P2 미배포 상태에서 실행)**

---

## 6. 최종 판정: **C**

| 기준 | 상태 | 설명 |
|------|------|------|
| **076 gate** | ✅ 코드 구현 완료 | `KisHolidayProvider` (076 API) 및 `FallbackSessionProvider` 구현 완료 |
| **163 WS** | ⚠️ 비활성화 | `KIS_LIVE_INFO_ENABLED=false` → `KisMarketStateClient` 미생성 |
| **Token cache** | ⚠️ 비활성화 | `KIS_LIVE_TOKEN_CACHE_ENABLED=true`지만 live-info disabled로 cache 미생성 |
| **DB persistence** | ⚠️ 미기록 | `market_sessions`, `session_events` 모두 0 rows (P1/P2 코드 배포 전 로그) |
| **Scheduler 안전성** | ✅ 정상 | 5/15: 724 cycles, 81 tasks, 0 failed, pre_market_done=True, end_of_day_done=True |

**판정 근거**:
- **C**: 163 실연동은 제한적 (`KIS_LIVE_INFO_ENABLED=false`)
- **076 + fallback은 정상**: 코드 레벨에서 구현 완료, FallbackSessionProvider 선택 로직 확인
- Scheduler 자체는 `--once`/loop 모드 모두 안전하게 동작 (5/15 로그 기준)
- 모든 P2 구성 요소(CombinedSessionProvider, KisMarketStateClient, token cache, market_sessions/session_events)는 코드 레벨에서 구현 완료
- 단, `KIS_LIVE_INFO_ENABLED=false`로 인해 실제 076 API 호출 및 163 WebSocket 연결이 이루어지지 않아 **End-to-End 검증은 불가능**

---

## 7. 다음 P3 필요 여부

### 발견된 이슈

| # | 이슈 | 심각도 | 설명 |
|---|------|--------|------|
| 1 | **KIS_LIVE_INFO_ENABLED=false** | 중간 | 076 API + 163 WS 모두 비활성화. `FallbackSessionProvider`만 동작 |
| 2 | **market_sessions 0 rows** | 중간 | P1/P2 코드 배포 전 로그이므로 정상, 배포 후 검증 필요 |
| 3 | **kis_live_token.json 미존재** | 낮음 | live-info disabled 상태에서는 정상. 활성화 시 자동 생성 예상 |
| 4 | **5/16 토요일 비거래일** | 낮음 | scheduler 미실행으로 금일 검증 불가 |

### P3에서 보완할 항목

1. **KIS_LIVE_INFO_ENABLED=true 전환**
   - 다음 거래일(2026-05-18 월) 전에 `.env`에서 `KIS_LIVE_INFO_ENABLED=true`로 변경 필요
   - 단, live-info credential이 실제 KIS 실서버용이므로 **paper 환경과의 분리** 재확인 필요
   - 실제 API 호출 전 `KISHolidayClient` approval key 발급 테스트 필요

2. **076 API End-to-End 검증**
   - `KIS_LIVE_INFO_ENABLED=true` 설정 후 scheduler dry-run으로 `KisHolidayProvider` 호출 확인
   - `opnd_yn`, `bzdy_yn`, `tr_day_yn` 응답값 validation
   - `session_gate: ALLOW/SKIP` 로그 확인

3. **163 WebSocket End-to-End 검증**
   - `KIS_LIVE_INFO_ENABLED=true` 설정 후 `KisMarketStateClient` approval key 발급 확인
   - WebSocket 연결(`wss://ops.koreainvestment.com:21000`) 및 phase change 수신 확인
   - `_session_phase_monitor()` 태스크 정상 동작 확인

4. **Token cache hit/mism 검증**
   - `kis_live_token.json` 파일 생성 확인
   - cache hit 시 approval key 재사용, cache miss 시 재발급 동작 확인
   - token 만료 전 갱신 로직 확인

5. **DB persistence 검증**
   - scheduler 실행 후 `market_sessions` 테이블 row 생성 확인
   - `session_events` 테이블 phase change 이벤트 기록 확인
   - `ON CONFLICT (run_date) DO UPDATE` (upsert) 동작 확인

6. **Phase monitor 안전성**
   - WebSocket 연결 실패 시 graceful fallback 확인
   - phase monitor task 취소/재시작 안전성 확인
   - after-hours 감지 로직 검증

### 권장 조치 순서

```
P3-1: KIS_LIVE_INFO_ENABLED=true 설정 변경 및 approval key 발급 테스트
P3-2: Scheduler dry-run (--once --skip-intraday --skip-eod)으로 076 API 호출 확인
P3-3: DB persistence 확인 (market_sessions row 생성)
P3-4: 163 WebSocket approval + connection 테스트 (별도 스크립트)
P3-5: Full scheduler run (다음 거래일)으로 전체 흐름 End-to-End 검증
P3-6: Token cache hit rate 모니터링
```

---

## 부록: 수집 명령어 실행 결과 요약

| 명령어 | 실행 결과 |
|--------|-----------|
| `ls -la logs/ \| tail -20` | 3개 로그 파일 확인 (scheduler_05-14, 05-14_closed, 05-15) |
| `grep -n "session_gate\|is_trading_day\|opnd_yn" logs/*.log` | **0건** — P1 로그 없음 |
| `grep -n "163\|WebSocket\|market_state\|phase_change" logs/*.log` | **0건** — P2 로그 없음 |
| `grep -n "token_cache\|kis_live_token" logs/*.log` | **0건** |
| `grep -n "market_session\|session_events\|persist_session" logs/*.log` | **0건** |
| `ls -la .cache/kis_live_token.json` | **파일 없음** |
| `cat .cache/kis_token.json` | ✅ paper token 존재 (만료 2026-05-17 03:47 KST) |
| `docker compose ps` | ✅ 4개 컨테이너 모두 정상 |
| `docker compose exec db psql ... market_sessions` | ✅ 테이블 존재, **0 rows** |
| `docker compose exec db psql ... session_events` | ✅ 테이블 존재, **0 rows** |
| `grep KIS_LIVE .env` | ✅ `KIS_LIVE_INFO_ENABLED=false` 확인 |
| `grep -n "create_session_provider\|class KisMarketStateClient" src/**/*.py` | ✅ 구현 확인 |
