# P1 구현: KIS 장운영정보 기반 Scheduler Session Gate

**작성일**: 2026-05-16  
**담당**: Roo  
**상태**: ✅ Complete (P1)

---

## 1. 개요

`scripts/run_near_real_ops_scheduler.py`가 **한국투자증권 실제 장운영정보**를 기반으로 phase 전이를 제어하도록 개선.  
휴장일(토/일/공휴일)에는 scheduler가 phase를 SKIP하여 불필요한 snapshot/decision loop 실행을 방지.

### 목표

1. **076 API** (국내휴장일조회)를 통한 실전 장운영정보 확인
2. **KISRestClient와 완전 분리**된 live-info 전용 클라이언트
3. **Session gate** 패턴으로 scheduler가 비거래일 SKIP
4. **Fallback** (weekday heuristic)으로 KIS API 미설정시에도 동작 보장
5. **163 API** (장운영정보 통합 WebSocket) stub 준비 (P2에서 실구현)

---

## 2. 아키텍처

### 계층 구조

```
run_near_real_ops_scheduler.py
  │
  ├── _session_gate() ───────────────────── session gate decision
  │
  └── MarketSessionProvider (ABC)
        ├── KisHolidayProvider        ← 076 API 사용 (KISHolidayClient)
        └── FallbackSessionProvider   ← weekday heuristic (Mon-Fri = trading day)
```

### Live-info Client 분리 원칙

```
KISRestClient            KISHolidayClient
 (paper/live 주문)         (076 휴장일 전용)
──────────────────        ─────────────────
submit_order()            get_holiday_status()
cancel_order()            _ensure_token()
get_positions()           
get_cash_balance()        
  ... (40+ methods)       ... (1 public method only)
  
상속/공유 없음            상속/공유 없음
자체 token 관리           자체 token 관리 (in-memory only)
file cache O              file cache X
```

---

## 3. 파일 변경 사항

### 신규 파일

| 파일 | 설명 | 라인 수 |
|------|------|---------|
| [`src/agent_trading/brokers/koreainvestment/holiday_client.py`](../src/agent_trading/brokers/koreainvestment/holiday_client.py) | 076 API 전용 REST 클라이언트 (KISRestClient와 완전 분리) | 291 |
| [`src/agent_trading/services/market_session.py`](../src/agent_trading/services/market_session.py) | MarketSessionProvider ABC + KisHolidayProvider + FallbackSessionProvider | ~150 |
| [`src/agent_trading/brokers/koreainvestment/market_state_client.py`](../src/agent_trading/brokers/koreainvestment/market_state_client.py) | 163 WebSocket adapter shell (P1: stub only) | ~120 |
| [`tests/brokers/koreainvestment/test_holiday_client.py`](../tests/brokers/koreainvestment/test_holiday_client.py) | KISHolidayClient 테스트 (14 tests) | 389 |
| [`tests/services/test_market_session.py`](../tests/services/test_market_session.py) | MarketSessionProvider 테스트 (14 tests) | ~200 |

### 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| [`scripts/run_near_real_ops_scheduler.py`](../scripts/run_near_real_ops_scheduler.py) | `_session_gate()`, `_init_session_provider()`, `_close_session_provider()` 추가 + SchedulerState에 session_info 필드 |
| [`docker-compose.yml`](../docker-compose.yml) | app/api/snapshot-sync 3개 서비스에 `KIS_LIVE_INFO_*` env vars 추가 |
| [`tests/scripts/test_run_near_real_ops_scheduler.py`](../tests/scripts/test_run_near_real_ops_scheduler.py) | Session gate 테스트 21개 추가 (총 35 → 56 tests) |

---

## 4. 핵심 구현 상세

### 4.1 KISHolidayClient (`holiday_client.py`)

- **076 API**: `GET /uapi/domestic-stock/v1/quotations/chk-holiday`, TR_ID=`CTCA0903R`
- **모의투자 미지원** → 항상 실전 endpoint 사용 (`https://openapi.koreainvestment.com:9443`)
- **Token 관리**: `asyncio.Lock` single-flight pattern, in-memory only (file cache X)
- **KIS 권장사항**: 1일 1회만 호출 → `KisHolidayProvider`에서 date-based cache 적용

```python
@dataclass(frozen=True, slots=True)
class HolidayStatus:
    bass_dt: str       # 기준일자
    wday_dvsn_cd: str  # 요일구분코드 (01=일...07=토)
    bzdy_yn: str       # 영업일여부
    tr_day_yn: str     # 거래일여부
    opnd_yn: str       # 개장일여부 ← is_trading_day
    sttl_day_yn: str   # 결제일여부
    
    @property
    def is_trading_day(self) -> bool:  # opnd_yn == "Y"
    @property
    def is_business_day(self) -> bool:  # bzdy_yn == "Y"
```

### 4.2 MarketSessionProvider (`market_session.py`)

```python
@dataclass(frozen=True, slots=True)
class SessionInfo:
    is_trading_day: bool
    opnd_yn: str
    bzdy_yn: str
    tr_day_yn: str
    source: str          # "kis_holiday_api" | "fallback" | "gate_error_fallback"
    reason: str

class MarketSessionProvider(ABC):
    @abstractmethod
    async def is_trading_day(self, target_date: date) -> bool: ...
    @abstractmethod
    async def get_session_info(self, target_date: date) -> SessionInfo: ...
```

**KisHolidayProvider**:
- `KISHolidayClient` 사용, 실전 credentials 필요
- **date 기반 캐시**: 이미 조회한 날짜는 재조회 X (1일 1회 정책 준수)
- API 실패 시 `KISHolidayError` 전파 → `_session_gate()`에서 conservative allow

**FallbackSessionProvider**:
- weekday heuristic: Mon-Fri → trading day, Sat-Sun → non-trading day
- 한국 공휴일(설날/추석 등)은 076 API로만 확인 가능하므로 fallback임

**`create_session_provider()` factory**:
1. `KIS_LIVE_INFO_ENABLED=true` + credentials 존재 → `KisHolidayProvider`
2. 미설정 → `FallbackSessionProvider`

### 4.3 Session Gate (`_session_gate()` in scheduler)

```
_session_gate(provider, run_date, state, phase_name) → bool
  │
  ├── state.session_info 이미 있음 → 재사용 (캐시)
  │
  ├── provider.get_session_info() 실패 → conservative allow (True)
  │     → state.session_info.source = "gate_error_fallback"
  │
  ├── is_trading_day == False → logger.warning("SKIP phase=...") → return False
  │
  └── is_trading_day == True → logger.info("ALLOW phase=...") → return True
```

**Phase 전이 위치**:
- `pre_market` 진입 전
- `intraday` 진입 전
- `end_of_day` 진입 전
- `--once` 모드에서도 동일하게 적용

**비거래일 동작**:
- phase SKIP → `state.done = True`로 표시 → 재시도 없이 종료
- `_log_summary()`에 session_source 표시

### 4.4 MarketStateClient (`market_state_client.py`)

P1에서는 **stub only**. P2에서 실제 WebSocket 구현 예정.

```python
class MarketPhaseCode(str, Enum):
    PRE_OPEN = "00"       # 장개시전 
    REGULAR = "01"        # 정규장
    AFTER_HOURS = "02"    # 시간외
    BATCH_AUCTION = "03"  # 단일가매매
    PRE_MARKET = "04"     # 프리마켓
    UNKNOWN = "99"        # 알수없음

class KisMarketStateClient(MarketStateProvider):
    # P1 stub: 항상 UNKNOWN 반환
    async def get_current_state(self) -> MarketState: ...
```

---

## 5. 설정

### Docker Compose env vars (모든 서비스)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `KIS_LIVE_INFO_ENABLED` | `false` | live-info client 활성화 |
| `KIS_LIVE_INFO_APP_KEY` | `""` | KIS 실전 앱키 (076 전용) |
| `KIS_LIVE_INFO_APP_SECRET` | `""` | KIS 실전 앱시크릿 |
| `KIS_LIVE_INFO_BASE_URL` | `""` (기본: `https://openapi.koreainvestment.com:9443`) | KIS 실전 base URL |
| `KIS_LIVE_INFO_WS_URL` | `""` (P2: 163 WebSocket) | KIS 실전 WebSocket URL |

---

## 6. 테스트 결과

**63/63 통과** (2026-05-16)

| 테스트 파일 | 통과 | 설명 |
|------------|------|------|
| `tests/brokers/koreainvestment/test_holiday_client.py` | 14 | HolidayStatus, 성공/실패 파싱, token caching, lifecycle |
| `tests/services/test_market_session.py` | 14 | KisHolidayProvider, FallbackSessionProvider, factory, cache |
| `tests/scripts/test_run_near_real_ops_scheduler.py` | 35 | 기존 14 + 신규 21 (session gate, state, provider init/close) |

### 주요 테스트 커버리지

**Holiday Client**:
- ✅ `HolidayStatus.is_trading_day` True/False
- ✅ 076 API 응답 파싱 (array output, dict output)
- ✅ 기본 base_date 자동 설정
- ✅ Token caching (single-flight, 재사용)
- ✅ HTTP 401 → `KISHolidayError("HTTP 401 ...")`
- ✅ KIS business error → `KISHolidayError("KIS error (rt_cd=...) ...")`
- ✅ Empty output → `KISHolidayError("Empty output ...")`
- ✅ Token 발급 실패 → `KISHolidayError`
- ✅ Network error → `KISHolidayError("Request failed ...")`
- ✅ `close()` idempotent, async context manager

**Session Gate**:
- ✅ 평일 → gate 통과 (`allowed=True`)
- ✅ 주말 → gate 차단 (`allowed=False`, reason="주말")
- ✅ SessionInfo caching (두 번째 호출은 재사용)
- ✅ Provider exception → conservative allow
- ✅ ALLOW 로그에 `session_source=%s` 포함
- ✅ SKIP 로그에 `phase=%s`, `reason=%s` 포함
- ✅ `SchedulerState.session_info` 필드 (기본 None, 설정 가능)
- ✅ `_init_session_provider()` → FallbackSessionProvider (기본)
- ✅ `_close_session_provider()` None/Fallback 모두 안전

---

## 7. Docker 검증

- ✅ `docker compose build` → 3 images 빌드 성공
- ✅ `docker compose up -d` → 4 containers 정상 기동 (db, app, api, snapshot-sync)
- ✅ `GET /health/readyz` → `{"status":"ok"}`
- ✅ 컨테이너 내 import 검증: `KISHolidayClient`, `MarketSessionProvider`, `MarketStateProvider` 등

---

## 8. P2 예정 작업

1. **163 API WebSocket 실구현**: `KisMarketStateClient`에 실제 WebSocket 연결, `MKOP_CLS_CODE` 파싱, 장운영 상태 모니터링
2. **장운영 상태 기반 phase 전이 세분화**: 
   - 정규장 시작 전에는 pre_market만 허용
   - 정규장 중에는 intraday + submit 허용
   - 장종료 후에는 after-hours snapshot + EOD만 허용
3. **WebSocket 재연결 로직**: 지수형 backoff, circuit breaker
4. **운영 메트릭**: session gate hit/miss, API latency, cache 효율

---

## 9. 참고 API 문서

- [076 국내휴장일조회](../reference_docs/kis_openapi_full_20260503_markdown/076_국내휴장일조회.md)
- [163 국내주식 장운영정보 (통합)](../reference_docs/kis_openapi_full_20260503_markdown/163_국내주식_장운영정보_(통합).md)
