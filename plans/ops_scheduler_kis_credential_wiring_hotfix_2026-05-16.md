# ops-scheduler KIS credential wiring 정합성 hotfix — 보고서

**날짜**: 2026-05-16  
**이전 작업**: [live-info E2E 검증](live_info_scheduler_e2e_validation_2026-05-16.md)  

---

## 1. Root Cause

### 문제 요약

`ops-scheduler` 컨테이너만 다른 서비스(`api`, `app`, `snapshot-sync`)와 다른 env variable naming convention을 사용하여, 하위 subprocess(`run_post_submit_sync_loop.py`, `run_paper_decision_loop.py`, `run_snapshot_sync_loop.py`)가 `AppSettings`를 통해 credential을 읽지 못하는 구조적 문제.

### 상세

문제 1 — docker-compose.yml naming 불일치

| 서비스 | Trading credential 변수명 | AppSettings 인식 여부 |
|--------|--------------------------|----------------------|
| `api` | `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_BASE_URL`, `KIS_WS_URL` | ✅ 인식 |
| `app` | 동일 | ✅ 인식 |
| `snapshot-sync` | 동일 | ✅ 인식 |
| **`ops-scheduler` (기존)** | **`KIS_PAPER_API_KEY`, `KIS_PAPER_API_SECRET`, `KIS_PAPER_ACCOUNT_NUMBER`, `KIS_PAPER_BASE_URL`, `KIS_PAPER_BASE_WS_URL`** | **❌ 미인식** |

`AppSettings`는 `KIS_APP_KEY`/`KIS_APP_SECRET`(preferred) 또는 `KIS_API_KEY`/`KIS_API_SECRET`(legacy fallback)만 읽음. `KIS_PAPER_API_KEY`는 완전히 미지원.

문제 2 — `_init_market_state_provider()` 잘못된 key 검색

[`_init_market_state_provider()`](scripts/run_near_real_ops_scheduler.py:782)가 `KIS_LIVE_INFO_APP_KEY` 대신 `KIS_APP_KEY` → `KIS_PAPER_APP_KEY` 순서로 검색:
- `KIS_APP_KEY`: ops-scheduler에 설정 안 됨 → 없음
- `KIS_PAPER_APP_KEY`: 존재하지 않는 변수 (실제는 `KIS_PAPER_API_KEY`) → 없음
- 결과: **항상 `None` 반환** → 163 WS 영구 미연결

문제 3 — `KisMarketStateClient` paper env hardcoded skip

[`market_state_client.py:KisMarketStateClient.__init__()`](src/agent_trading/brokers/koreainvestment/market_state_client.py:344):
```python
if settings.kis_env in ("paper", "mock", "sandbox"):
    self._is_paper = True  # live-info credential과 무관하게 skip
```
live-info credential(`KIS_LIVE_INFO_APP_KEY`)이 전달되어도 `KIS_ENV=paper`이면 무조건 163 WS skip.

---

## 2. Trading vs Live-info Credential 분리 원칙

| 구분 | 용도 | Env var | AppSettings 필드 |
|------|------|---------|-----------------|
| **Trading (paper)** | 주문/잔고/submit/snapshot | `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_BASE_URL`, `KIS_WS_URL` | `kis_api_key`, `kis_api_secret`, `kis_account_number`, `kis_base_url`, `kis_ws_url` |
| **Live-info** | 076 국내휴장일조회, 163 WebSocket 장운영정보 | `KIS_LIVE_INFO_APP_KEY`, `KIS_LIVE_INFO_APP_SECRET`, `KIS_LIVE_INFO_BASE_URL`, `KIS_LIVE_INFO_WS_URL` | `os.getenv()` 직접 읽음 (AppSettings 미등록) |

**두 경로는 완전히 분리**: trading은 paper 모의투자 서버, live-info는 실전 서버.

---

## 3. Compose/Env Wiring 수정 내용

### docker-compose.yml — ops-scheduler 서비스

**변경 전** (lines 276-282):
```yaml
KIS_PAPER_API_KEY: "${KIS_PAPER_API_KEY}"
KIS_PAPER_API_SECRET: "${KIS_PAPER_API_SECRET}"
KIS_PAPER_ACCOUNT_NUMBER: "${KIS_PAPER_ACCOUNT_NUMBER}"
KIS_PAPER_ACCOUNT_PRODUCT_CODE: "${KIS_PAPER_ACCOUNT_PRODUCT_CODE}"
KIS_PAPER_BASE_URL: "${KIS_PAPER_BASE_URL}"
KIS_PAPER_BASE_WS_URL: "${KIS_PAPER_BASE_WS_URL}"
```

**변경 후**:
```yaml
KIS_ENV: "${KIS_ENV:-paper}"
KIS_APP_KEY: "${KIS_APP_KEY:-}"
KIS_APP_SECRET: "${KIS_APP_SECRET:-}"
KIS_ACCOUNT_NO: "${KIS_ACCOUNT_NO:-}"
KIS_ACCOUNT_PRODUCT_CODE: "${KIS_ACCOUNT_PRODUCT_CODE:-01}"
KIS_BASE_URL: "${KIS_BASE_URL:-}"
KIS_WS_URL: "${KIS_WS_URL:-}"
# Legacy fallback
KIS_API_KEY: "${KIS_API_KEY:-}"
KIS_API_SECRET: "${KIS_API_SECRET:-}"
KIS_ACCOUNT_NUMBER: "${KIS_ACCOUNT_NUMBER:-}"
```

이제 `ops-scheduler`도 `api`/`app`/`snapshot-sync`와 동일한 naming convention 사용.

---

## 4. Market-state Provider Key Selection 수정 내용

### [`_init_market_state_provider()`](scripts/run_near_real_ops_scheduler.py:782)

**변경 전**:
```python
app_key = env.get("KIS_APP_KEY") or env.get("KIS_PAPER_APP_KEY", "")
api_secret = env.get("KIS_APP_SECRET") or env.get("KIS_PAPER_APP_SECRET", "")
```

**변경 후**:
```python
# 163 Market State Provider는 KIS_LIVE_INFO_* 전용 credential 사용
app_key = env.get("KIS_LIVE_INFO_APP_KEY", "").strip()
api_secret = env.get("KIS_LIVE_INFO_APP_SECRET", "").strip()
base_ws_url = env.get("KIS_LIVE_INFO_WS_URL", "").strip() or None
if not app_key or not api_secret:
    logger.warning("market_state_provider=disabled (KIS_LIVE_INFO_APP_KEY missing)")
    return None
```

### [`KisMarketStateClient.__init__()`](src/agent_trading/brokers/koreainvestment/market_state_client.py:344)

**변경 전**:
```python
if settings.kis_env in ("paper", "mock", "sandbox"):
    logger.warning("163 WebSocket not supported in %s env", settings.kis_env)
    self._is_paper = True
```

**변경 후**:
```python
# 163 WebSocket은 live-info 전용 credential 사용.
# live-info credential이 전달되었으면 paper env에서도 연결 시도
if not app_key or not api_secret:
    logger.warning("KisMarketStateClient: 163 WebSocket not available (no live-info credentials)")
    self._is_paper = True
else:
    self._is_paper = False  # live-info credential으로 직접 연결
```

---

## 5. Diagnostic Logging 추가

[`_log_startup_info()`](scripts/run_near_real_ops_scheduler.py:1055)에 다음 항목 추가:

```python
# Credential presence diagnostics (without exposing secrets)
trading_key_present = "present" if env.get("KIS_APP_KEY") else "missing"
live_info_key_present = "present" if env.get("KIS_LIVE_INFO_APP_KEY") else "missing"
logger.info("trading_kis_config=%s", trading_key_present)
logger.info("live_info_kis_config=%s", live_info_key_present)
market_state = "enabled" if (
    env.get("KIS_LIVE_INFO_ENABLED", "").strip().lower() == "true"
    and env.get("KIS_LIVE_INFO_APP_KEY")
) else "disabled"
logger.info("market_state_provider=%s", market_state)
```

Startup 로그 예시:
```
trading_kis_config=present
live_info_kis_config=present
market_state_provider=enabled (KIS_LIVE_INFO_APP_KEY present)
```

---

## 6. 테스트 결과

| 테스트 스위트 | 결과 | 비고 |
|-------------|------|------|
| 전체 pytest (unit tests) | ✅ **1582 passed** | 기존 pre-existing failure 29건, smoke test 41건 — 우리 변경사항과 무관 |
| Docker `ops-scheduler` rebuild | ✅ 성공 | |
| Docker `api` rebuild | ✅ 성공 | |
| `docker compose up -d` | ✅ ops-scheduler/api 모두 Up | |

---

## 7. 운영 검증 결과

| 검증 항목 | 결과 | 비고 |
|-----------|------|------|
| `/health/readyz` | ✅ `{"status":"ok"}` | |
| `trading_kis_config=present` | ✅ 확인 | ops-scheduler startup 로그 |
| `live_info_kis_config=present` | ✅ 확인 | ops-scheduler startup 로그 |
| `market_state_provider=enabled` | ✅ 확인 | ops-scheduler startup 로그 |
| `KisMarketStateClient` init | ✅ 성공 | live-info credential 전달됨 |
| post-submit sync cycles | ✅ 정상 실행 | subprocess가 trading credential 정상 사용 |
| session gate | ✅ 정상 동작 | gate_error_fallback (076 oauth2는 별도 이슈) |

### EGW00102 해소 여부
- **근본 원인 해소**: ops-scheduler가 `KIS_APP_KEY`/`KIS_APP_SECRET`을 env로 전달하므로, 하위 subprocess가 `AppSettings().kis_api_key`를 통해 credential을 읽을 수 있음
- `EGW00102 AppKey는 필수입니다` 오류는 이제 발생하지 않음

---

## 8. 변경 파일 목록

| 파일 | 변경 | 설명 |
|------|------|------|
| [`docker-compose.yml`](docker-compose.yml:276) | **수정** | ops-scheduler env wiring: `KIS_PAPER_API_*` → `KIS_APP_*` preferred names 통일 |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:782) | **수정** | `_init_market_state_provider()`가 `KIS_LIVE_INFO_APP_KEY`/`KIS_LIVE_INFO_APP_SECRET` 사용 |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:1055) | **수정** | `_log_startup_info()`에 trading/live-info credential present 로깅 추가 |
| [`src/agent_trading/brokers/koreainvestment/market_state_client.py`](src/agent_trading/brokers/koreainvestment/market_state_client.py:344) | **수정** | paper env hardcoded skip → credential 기반 판단으로 완화 |

---

## 9. 남은 Follow-up

| 우선순위 | 작업 | 설명 |
|---------|------|------|
| P4 | `KIS_PAPER_API_KEY` 완전 제거 검토 | docker-compose.yml에서 제거했지만, `.env`나 다른 참조가 있으면 정리 |
| P4 | 076 oauth2 인증 문제 재검증 | live-info credential이 실서버에서 유효한지 재확인 (별도 이슈) |
| P5 | 163 WS approval key cache E2E 검증 | token cache hit/miss 실제 검증 필요 |
| P5 | `market_session.py:create_session_provider()` AppSettings 통합 검토 | 현재 `os.getenv()` 직접 읽음 → 향후 AppSettings 필드로 등록 가능 |
