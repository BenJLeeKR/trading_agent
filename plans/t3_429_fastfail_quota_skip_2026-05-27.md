# T3 Pipeline 429 Fast-Fail + NAVER Quota Preemptive Skip

**Date:** 2026-05-27
**Status:** Draft (설계)

---

## 1. Problem Analysis

### 현재 상황

T3 Pipeline(`_run_t3_live_pipeline()`)이 [`asyncio.create_task()`](scripts/run_decision_loop.py:783)로 fire-and-forget 실행될 때, NAVER API 일일 쿼터(25,000건)가 완전 소진되어 **모든 NAVER query가 429를 반환**하고 있습니다.

**현재 429 처리 흐름 (문제점):**

```
429 응답 수신
  → `_NAVER_RETRYABLE_STATUS_CODES` 에 포함됨
  → exponential backoff: 1s + 2s + 4s + jitter (약 7~8s 소모)
  → max retries 초과 후 `NaverSearchResponse(items=[])` 반환
  → Step 2(process_seeds) 내부에서 각 query별로 위 과정 반복
  → 20s timeout 발생
  → `candidates is None`이므로 partial persist 불가
  → T3 event DB에 0건 persist
  → 다음 cycle `has_fresh_t3_events()` = False
  → 매 cycle 동일한 T3 pipeline 재실행 → NAVER quota 완전 소진
```

### 영향

| 영향 | 설명 |
|------|------|
| Timeout | 20s timeout이 fire-and-forget task에서 발생하여 CPU/메모리 낭비 |
| DB persist 실패 | T3 event가 한 건도 persist되지 않음 |
| Freshness deadlock | 매 cycle이 T3 stale 상태로 인식되어 동일 pipeline 반복 실행 |
| Quota wasting | 429에 대한 retry backoff로 불필요한 API 호출 발생 |

---

## 2. 설계 목표

| Priority | 목표 | 설명 |
|----------|------|------|
| **P0** | NAVER Quota Preemptive Skip | T3 pipeline 시작 전에 NAVER 일일 quota 소진 상태 확인 후 SKIP |
| **P1** | 429 Fast-Fail | 429 응답 시 retry 없이 즉시 중단 (fast-fail) |
| **P2** | Partial Persist 기준 완화 | Step 1(disclosure) 완료 시점의 `seeds`만 있어도 partial persist 허용 |

---

## 3. 상세 설계

### 3.1 NAVER Daily Quota Tracker

#### 필요성

현재 NAVER API 호출에 대한 일일 quota tracking 메커니즘이 **전혀 존재하지 않음**. KIS API는 [`RateLimitBudgetManager`](src/agent_trading/brokers/rate_limit.py:121)에서 관리되지만, NAVER API에 대한 유사한 메커니즘이 없음.

#### 설계: `NaverDailyQuotaTracker`

[`src/agent_trading/brokers/shared_budget.py`](src/agent_trading/brokers/shared_budget.py)의 [`FileBackedGlobalBucket`](src/agent_trading/brokers/shared_budget.py:18) 패턴을 차용하여 flock-protected file 기반 일일 quota tracker 구현.

> **⚠️ Best-Effort Tracker:** 이 tracker는 **best-effort** 방식으로 동작합니다. 파일 손상, flock 획득 실패, 디스크 I/O 오류 등이 발생하면 "tracker unavailable" 상태로 판단하고 **호출을 차단하지 않고 진행**합니다 (fail-open). quota 초과 추정은 보수적으로 동작하여, tracker unavailable 시에는 quota가 정상이라고 가정하고 API 호출을 허용합니다.

```python
# src/agent_trading/brokers/naver_news_adapter.py 에 추가

_NAVER_DAILY_QUOTA_FILE = "/workspace/agent_trading/tmp/naver_daily_quota.json"
_NAVER_DAILY_LIMIT = 25000       # NAVER API 일일 quota
_NAVER_QUOTA_THRESHOLD = 0.9     # 90% = 22,500건
```

**`NaverDailyQuotaTracker` 클래스:**

```python
class NaverDailyQuotaTracker:
    """File-backed daily quota tracker for NAVER Search API.

    Tracks NAVER API calls made today using a flock-protected file.
    Resets at midnight KST (UTC+9).

    Design follows FileBackedGlobalBucket pattern from shared_budget.py.
    """

    _FILE_PATH = "/workspace/agent_trading/tmp/naver_daily_quota.json"
    _DAILY_LIMIT = 25000
    _THRESHOLD = 0.9  # 90%

    @classmethod
    def get_current_consumption(cls) -> int:
        """Read current day's call count from file."""
        ...

    @classmethod
    def get_consumption_ratio(cls) -> float:
        """Return consumption ratio (0.0 ~ 1.0)."""
        ...

    @classmethod
    def is_exhausted(cls, threshold: float = _THRESHOLD) -> bool:
        """Check if daily quota exceeds threshold."""
        ...

    @classmethod
    def increment(cls) -> None:
        """Increment daily call count by 1."""
        ...

    @classmethod
    def _read_or_init(cls) -> tuple[int, str]:
        """Read (count, date_str) from file; reset if date changed."""
        ...

    # ── Error handling: all file operations are best-effort ──
    # If the file cannot be read/opened/written (OSError, ValueError),
    # the method returns (0, "") to signal "tracker unavailable".
    # Callers MUST interpret this as "quota OK, continue" rather than
    # blocking the API call.
```

**파일 포맷:** JSON (`{"count": 12345, "date": "20260527", "updated_at": "2026-05-27T14:30:00+09:00"}`)

**파일 조작 로직:**

```
1. 파일 읽기: fcntl.LOCK_SH → JSON 파싱
2. date != 오늘 날짜(YYYYMMDD KST) → count = 0으로 리셋
3. 파일 쓰기: fcntl.LOCK_EX → JSON 직렬화 후 쓰기
4. 읽기/쓰기는 asyncio.to_thread()로 실행 (event loop blocking 방지)
5. 모든 I/O 오류 → 조용히 무시 (tracker unavailable = quota OK 간주)
```

**클래스 메서드로 `NaverNewsSearchAdapter`에 노출:**

```python
class NaverNewsSearchAdapter:
    ...

    @classmethod
    def get_daily_usage_ratio(cls) -> float:
        """Return NAVER API daily quota usage ratio (0.0 ~ 1.0)."""
        return NaverDailyQuotaTracker.get_consumption_ratio()

    @classmethod
    def is_quota_exhausted(cls, threshold: float = 0.9) -> bool:
        """Check if daily quota exceeds threshold."""
        return NaverDailyQuotaTracker.is_exhausted(threshold)
```

### 3.2 429 Fast-Fail (P1)

#### 현재 코드 분석

[`_call_api()`](src/agent_trading/brokers/naver_news_adapter.py:237)의 현재 429 처리:

```python
# Line 297-339: 현재 코드
if response.status_code in _NAVER_RETRYABLE_STATUS_CODES:
    if response.status_code == 429:
        # 로깅 (WARNING)
        ...
    if attempt < self._max_retries:
        delay = self._backoff_base * (2**attempt) + jitter  # 7~8s 소모
        await asyncio.sleep(delay)
        continue
    else:
        return NaverSearchResponse(items=[])
```

#### 변경: 429를 retryable set에서 분리

```python
# 변경 후: 429는 retry 없이 즉시 fast-fail

# Retryable: 500, 502, 503, 504만 (429 제외)
_NAVER_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({500, 502, 503, 504})

# _call_api() 내 429 처리:
if response.status_code == 429:
    logger.warning(
        "NAVER 429 fast-fail: query=%r — daily quota likely exhausted",
        query,
    )
    # 여전히 increment는 하지 않음 (호출은 했지만 실패)
    return NaverSearchResponse(items=[])

# Retryable 5xx 처리: 기존 backoff 유지
elif response.status_code in _NAVER_RETRYABLE_STATUS_CODES:
    ...기존 retry 로직 동일...
```

**핵심 변경사항:**
1. `_NAVER_RETRYABLE_STATUS_CODES`에서 429 **제거**
2. 429 수신 시 즉시 `NaverSearchResponse(items=[])` 반환 (WARNING 로그)
3. 429는 `_call_api()` 수준에서 추가 호출 없이 종료
4. 단, `NaverDailyQuotaTracker.increment()`는 실제 API 호출 성공/실패와 무관하게 `_call_api()` 진입 시점에 호출 (consumption tracking 용도)

#### 429 Fast-Fail 흐름도

```mermaid
flowchart TD
    A[API 호출 시작] --> B[NaverDailyQuotaTracker.increment]
    B --> C[HTTP GET 요청]
    C --> D{응답 코드}
    D -->|200 OK| E[정상 응답 처리]
    D -->|429| F[WARNING 로그]
    F --> G[NaverSearchResponse items=[] 반환]
    D -->|5xx| H[기존 retry backoff]
    H -->|재시도| C
    H -->|max retries| G
    D -->|400/401/403/404| I[기존 non-retryable 처리]
    I --> G
```

### 3.3 T3 Pipeline Preemptive Skip (P0)

#### 현재 호출 흐름

```
decision loop (line 774-787):
  if not t3_fresh:
    task = asyncio.create_task(_run_t3_live_pipeline(...))
```

#### 변경: NAVER quota 확인 후 create_task SKIP

**Decision loop 수준 skip** ([`scripts/run_decision_loop.py`](scripts/run_decision_loop.py) line 778-787):

```python
# ── T3 live path: run synchronously (await) before assemble ──
t3_fresh = await _is_t3_fresh_for_symbol(repos, symbol)
if not t3_fresh:
    # ── NAVER quota preemptive check ──
    if NaverNewsSearchAdapter.is_quota_exhausted():
        logger.warning(
            "T3 live pipeline skipped for symbol=%s: "
            "NAVER quota exhausted (%.1f%%)",
            symbol,
            NaverNewsSearchAdapter.get_daily_usage_ratio() * 100,
        )
    else:
        task = asyncio.create_task(
            _run_t3_live_pipeline(runtime, repos, symbol, source_type=source_type)
        )
        _active_t3_tasks.add(task)
        task.add_done_callback(_active_t3_tasks.discard)
```

**`_run_t3_live_pipeline()` 내부에도 이중 확인** (line 1061-1066):

```python
async def _run_t3_live_pipeline(...):
    seeds = None
    candidates = None
    seeded_events = None

    try:
        # ── Preemptive NAVER quota check (이중 방어) ──
        if NaverNewsSearchAdapter.is_quota_exhausted():
            logger.warning(
                "symbol=%s T3 skipped: NAVER quota exhausted (%.1f%%) "
                "before KIS disclosure fetch",
                symbol,
                NaverNewsSearchAdapter.get_daily_usage_ratio() * 100,
            )
            return

        disclosure_seed_service = runtime.get("disclosure_seed_service")
        ...
```

#### T3 Pipeline Skip 조건 요약

`_run_t3_live_pipeline()` 시작 시 SKIP 조건:

| 조건 | 위치 | 로그 |
|------|------|------|
| `source_type in ("held_position", "market_overlay")` | caller (line 767) | 기존 유지 |
| NAVER quota >= 90% | caller + `_run_t3_live_pipeline()` 내부 | `"NAVER quota exhausted (X/25000)"` |
| services not available | `_run_t3_live_pipeline()` line 1064 | `"services not available"` |
| no disclosure seeds | `_run_t3_live_pipeline()` line 1073 | `"no disclosure seeds"` |
| 429 발생 (fast-fail) | `_call_api()` → candidates=None | `"no candidates after processing"` |

### 3.4 Partial Persist 기준 완화 (P2)

#### 현재 코드 분석

[`_run_t3_live_pipeline()`](scripts/run_decision_loop.py:1112-1137)의 except 블록:

```python
except asyncio.TimeoutError:
    if seeded_events is not None:       # Step 3 완료
        await persist_seeded_events(seeded_events, repos.external_events)
    elif candidates is not None:         # Step 2 완료
        partial_events = convert_seeded_candidates(candidates)
        await persist_seeded_events(partial_events, repos.external_events)
    else:                                # Step 1도 미완료
        logger.warning("no partial data to persist")
```

#### 변경: seeds만 있어도 partial persist

```python
except asyncio.TimeoutError:
    if seeded_events is not None:       # Step 3 완료
        await persist_seeded_events(seeded_events, repos.external_events)
    elif candidates is not None:         # Step 2 완료
        partial_events = convert_seeded_candidates(candidates)
        await persist_seeded_events(partial_events, repos.external_events)
    elif seeds is not None and len(seeds) > 0:  # ← 신규: Step 1 완료
        # KIS disclosure title만이라도 KIS disclosure event(T2)로 persist
        #
        # ⚠️ 중요: 이 변경은 has_fresh_t3_events()에 영향이 없습니다.
        # T2 tier event이므로 _is_t3_fresh_for_symbol()의 T3 필터에 의해 제외됨.
        # 즉, freshness deadlock 문제의 해결책이 아닙니다.
        #
        # 기대 효과: _collect_persisted_seeded_events()의 T3 tier 필터로
        # 수집되지는 않지만, decision input의 컨텍스트 보강에 일부 기여 가능.
        from agent_trading.services.seeded_news_service import (
            DisclosureTitleDTO,
        )
        # seeds → ExternalEventEntity 변환 (disclosure event)
        partial_events = _convert_disclosure_seeds_to_events(seeds)
        await persist_seeded_events(partial_events, repos.external_events)
        logger.info(
            "symbol=%s T3 partial persist on timeout: "
            "%d disclosure seeds -> %d events (step 1 only)",
            symbol, len(seeds), len(partial_events),
        )
    else:
        logger.warning(
            "symbol=%s T3 skipped: live pipeline timed out after %ds "
            "(no partial data to persist)",
            symbol, _T3_TIMEOUT,
        )
```

**`_convert_disclosure_seeds_to_events()` 함수:**

```python
def _convert_disclosure_seeds_to_events(
    seeds: list[DisclosureTitleDTO],
) -> list[ExternalEventEntity]:
    """Convert KIS disclosure seed DTOs to ExternalEventEntity list.

    These are KIS disclosure events (not seeded_news), so they have:
    - event_type = "Y|{headline}" (KIS disclosure prefix)
    - source_reliability_tier = "T2" (KIS disclosure tier)

    This does NOT affect has_fresh_t3_events() since the tier is T2.
    But _collect_persisted_seeded_events() filters by T3 only.
    """
    events: list[ExternalEventEntity] = []
    for seed in seeds:
        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type=f"Y|{seed.headline}",
            source_name="kis_disclosure",
            source_reliability_tier="T2",
            symbol=seed.symbol,
            market=seed.market if hasattr(seed, 'market') else "KR",
            published_at=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            severity="medium",
            direction="neutral",
            headline=seed.headline,
        )
        events.append(event)
    return events
```

> **참고:** 이 변경으로 persist된 event는 KIS disclosure event(T2)이므로 [`has_fresh_t3_events()`](scripts/run_decision_loop.py:1010)에 영향이 없습니다. 하지만 [`_collect_persisted_seeded_events()`](scripts/run_decision_loop.py:975)에서 `source_reliability_tier == "T3"` 필터로 제외되므로, 기존 로직에 영향을 주지 않습니다. 단, `_collect_persisted_seeded_events()`에 전달되어 event 해석 컨텍스트를 제공할 수 있습니다.

---

## 4. 변경 대상 파일 및 변경 사항 요약

### 4.1 [`src/agent_trading/brokers/naver_news_adapter.py`](src/agent_trading/brokers/naver_news_adapter.py)

| 변경 | 상세 |
|------|------|
| `_NAVER_RETRYABLE_STATUS_CODES` | 429 제거 (`{500, 502, 503, 504}`) |
| `NaverDailyQuotaTracker` 클래스 추가 | File-backed daily quota counter |
| `NaverNewsSearchAdapter.get_daily_usage_ratio()` | 클래스 메서드로 quota ratio 노출 |
| `NaverNewsSearchAdapter.is_quota_exhausted()` | 클래스 메서드로 quota check 노출 |
| `_call_api()` 429 처리 변경 | retry 제거 → WARNING 로그 + `NaverSearchResponse(items=[])` 즉시 반환 |
| `_call_api()` 진입 시 increment | `NaverDailyQuotaTracker.increment()` 호출 |

### 4.2 [`scripts/run_decision_loop.py`](scripts/run_decision_loop.py)

| 변경 | 라인 | 상세 |
|------|------|------|
| `_convert_disclosure_seeds_to_events()` 함수 추가 | - | KIS disclosure seed → ExternalEventEntity 변환 |
| `_run_t3_live_pipeline()` 시작 시 NAVER quota check | line 1061~ | 서비스 check 직후 quota 확인 → SKIP |
| `_run_t3_live_pipeline()` except TimeoutError | line 1132~ | `seeds` 기반 partial persist 분기 추가 |
| decision loop T3 fire 시 NAVER quota check | line 779~ | `create_task()` 전 quota 확인 → SKIP |

### 4.3 [`tests/brokers/test_naver_news_adapter.py`](tests/brokers/test_naver_news_adapter.py)

| 테스트 | 설명 |
|--------|------|
| `test_429_fast_fail_no_retry` | 429 응답 시 retry 없이 즉시 `[]` 반환 검증 |
| `test_429_does_not_retry` | 429 이후 추가 API 호출 없음을 `assert_called_once()`로 검증 |
| `test_quota_tracker_increment` | `NaverDailyQuotaTracker.increment()` 호출 시 count 증가 검증 |
| `test_quota_tracker_reset_on_new_day` | 일자 변경 시 count 리셋 검증 |
| `test_quota_exhausted_check` | threshold 초과 시 `is_quota_exhausted()=True` 검증 |

### 4.4 [`tests/scripts/test_run_decision_loop.py`](tests/scripts/test_run_decision_loop.py)

| 테스트 | 설명 |
|--------|------|
| `test_skip_when_naver_quota_exhausted` | NAVER quota 소진 시 T3 pipeline skip 검증 |
| `test_partial_persist_with_seeds_only` | Step 1 완료 후 timeout → seeds 기반 partial persist 검증 |
| 기존 테스트 유지 | 모든 기존 테스트가 변경 후에도 통과 |

---

## 5. 변경 영향 분석

### 5.1 기존 동작과의 차이

| 시나리오 | 현재 | 변경 후 |
|----------|------|---------|
| NAVER quota < 90%, 정상 응답 | T3 pipeline 정상 실행 | **동일** |
| NAVER quota >= 90%, 모든 요청 429 | 7~8s retry backoff → timeout (20s) → persist 실패 | **0s delay** → SKIP 로그 + T3 실행 안 함 |
| NAVER quota < 90%이지만 특정 query만 429 | retry backoff (7~8s) → empty → 다음 query 계속 | **즉시 empty 반환** → 다음 query 계속 (0s delay) |
| Step 1 완료, Step 2 timeout | `seeds=None` persist 불가 | seeds 기반 KIS disclosure event persist |
| held_position/market_overlay | T3 skip (기존) | **동일** |
| 5xx server error | retry backoff (기존) | **동일** (429만 변경) |

### 5.2 성능 영향

| 항목 | 영향 |
|------|------|
| Quota 파일 I/O | 호출당 1회 flock-protected file read/write (asyncio.to_thread) → 미미함 |
| 429 fast-fail | 7~8s → 0s (불필요한 backoff 제거) |
| Preemptive skip | file read 1회 (asyncio.to_thread) → 무시 가능 |

### 5.3 주의사항

1. **파일 경로:** `/workspace/agent_trading/tmp/naver_daily_quota.json` 사용. 다중 인스턴스 환경에서는 공유 볼륨 또는 DB 기반 tracking 필요
2. **asyncio.to_thread:** file I/O는 asyncio event loop를 block하지 않도록 `asyncio.to_thread()`로 실행
3. **KST 기준 리셋:** NAVER quota는 KST 기준 midnight 리셋. `NaverDailyQuotaTracker`는 KST 날짜 기준으로 리셋 판단
4. **Best-Effort:** 모든 파일 I/O 오류는 조용히 무시하고 "tracker unavailable → quota OK"로 간주 (fail-open). tracker 장애가 API 호출을 차단하지 않도록 함

---

## 6. 구현 순서

```
Step 1: NaverDailyQuotaTracker 구현 (naver_news_adapter.py)
  → 파일 기반 daily counter
  → flock-protected read/write
  → KST 기준 자정 리셋

Step 2: 429 Fast-Fail 변경 (naver_news_adapter.py)
  → _NAVER_RETRYABLE_STATUS_CODES에서 429 제거
  → _call_api() 429 처리 로직 변경
  → _call_api() 진입 시 increment 호출

Step 3: T3 Pipeline Preemptive Skip (run_decision_loop.py)
  → decision loop 수준 quota check
  → _run_t3_live_pipeline() 내부 이중 check

Step 4: Partial Persist 기준 완화 (run_decision_loop.py)
  → _convert_disclosure_seeds_to_events() 구현
  → except TimeoutError에 seeds 분기 추가

Step 5: 테스트 추가
  → test_naver_news_adapter.py: 429 fast-fail + quota tracker
  → test_run_decision_loop.py: quota skip + seeds partial persist

Step 6: 기존 테스트 통과 확인
```

---

## 7. Mermaid: 전체 흐름도

```mermaid
flowchart TD
    START[Decision Loop: symbol cycle 시작] --> A{source_type in\nheld_position/\nmarket_overlay?}
    A -->|Yes| B[SKIP: T3 live pipeline\nlog debug + read persisted]
    A -->|No| C{t3_fresh?}
    C -->|Yes| D[SKIP: use persisted T3 events\nno live pipeline needed]
    C -->|No| E{NAVER quota\n>= 90%?}
    E -->|Yes| F[SKIP: log WARNING\nNAVER quota exhausted\nread persisted events only]
    E -->|No| G[create_task: _run_t3_live_pipeline]

    G --> H{NAVER quota\n>= 90%? 2nd check}
    H -->|Yes| I[SKIP: log + return immediately]
    H -->|No| J[Step 1: fetch KIS disclosure titles]
    J --> K{seeds found?}
    K -->|No| L[SKIP: log + return]
    K -->|Yes| M[Step 2: NAVER news search per seed]

    M --> N{429 received?}
    N -->|Yes| O[429 Fast-Fail: WARNING log\nreturn [] immediately\ncontinue to next query]
    N -->|No| P[Process candidates normally]

    M --> Q{Timeout during Step 2?}
    Q -->|Yes| R[Partial persist: seeds ->\nKIS disclosure events (T2)]
    Q -->|No| S[Step 3: convert candidates]
    S --> T{Step 4: persist to DB}
    T --> U[END: T3 events available\nfor next cycle]

    R --> U
```

---

## 8. 리스크 및 고려사항

### 8.1 파일 기반 quota tracker의 한계
- 프로세스 크래시 시 파일 상태 불일치 가능성 (flock으로 최소화)
- 다중 인스턴스 환경에서 파일 공유 필요
- `/workspace/agent_trading/tmp/` 디렉토리는 존재해야 함 → 구현 시 `os.makedirs(exist_ok=True)`로 생성
- Best-Effort 설계로 인해 tracker가 정상 동작하지 않아도 API 호출은 계속됨 (quota 초과 호출 가능성 존재)

### 8.2 429 Fast-Fail의 conservative한 접근
- NAVER 429는 항상 "일일 quota 소진"을 의미한다고 가정
- 만약 429가 transient rate limit(초당 호출 제한)인 경우에도 fast-fail
  - 현재 `_NaverTokenBucket`(8 req/s) + `_NAVER_SEMAPHORE(2)`로 초당 호출 제한은 이미 관리 중
  - 따라서 429는 거의 항상 일일 quota 소진
- 초당 rate limit 429를 구분해야 한다면 Retry-After 헤더 분석 가능 (현재 불필요)

### 8.3 기존 테스트 호환성
- `test_429_triggers_retry_and_eventually_succeeds`: 429 retry 테스트 → **삭제 또는 5xx로 변경**
- `test_429_retry_exhaustion_returns_empty`: 429 retry exhaustion 테스트 → **삭제 또는 5xx로 변경**
- `test_transient_error_retry`: 5xx retry 테스트 → **변경 없음 (5xx는 retry 유지)**

---

## 9. Code 모드 전환 시 전달사항

1. `apply_diff` 도구를 사용하여 파일 수정 (`.env` 수정 금지)
2. [`naver_news_adapter.py`](src/agent_trading/brokers/naver_news_adapter.py)에 `NaverDailyQuotaTracker` 추가 후,
   `_NAVER_RETRYABLE_STATUS_CODES`에서 429 제거
3. [`run_decision_loop.py`](scripts/run_decision_loop.py)에 quota check 로직 추가
4. 테스트 파일에서 429 retry 테스트는 5xx retry 테스트로 변경
5. `python3 -m pytest tests/brokers/test_naver_news_adapter.py tests/scripts/test_run_decision_loop.py -v` 로 전체 테스트 통과 확인
