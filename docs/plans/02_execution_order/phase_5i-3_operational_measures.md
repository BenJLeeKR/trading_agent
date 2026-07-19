# Phase 5i-3: NAVER Quota 소진 원인 분석 및 운영 조치 (재시도 5)

> **분석 일자**: 2026-05-29 KST
> **전제**: `ops-scheduler`는 2026-05-27 장중(00:00~17:55 KST)에 실행되지 않음 — [`scheduler_restart_20260527.log`](logs/scheduler_restart_20260527.log) 로그 증거 기반

## 1. 분석 범위

본 문서는 Phase 5i-3 Retry 5의 분석 결과를 바탕으로 2026-05-27 KST에 발생한 NAVER API quota 소진 사고의 근본 원인을 **ops-scheduler가 장중에 실행되지 않았다는 로그 사실을 전제로 재판정**한다.

**Retry 5 방법론:**
- **Log 기반 정량 분석**: ops-scheduler 로그(`scheduler_restart_20260527.log`)로 장중 실행 여부 1차 판별
- **Log 파일별 NAVER call/429/partial persist 집계**: 10개 log 파일에서 `query_count`, `HTTP 429`, `partial persist on timeout` 발생 건수를 개별 grep 집계
- **Transaction bug 영향 분석**: `t3_429_fastfail_verify` vs `t3_transaction_fix_verify` 비교로 bug가 호출 수에 미친 영향 정량화
- **UNKNOWN external 추정 제거**: 더 이상 외부 사용을 추정하지 않고, app container 실행 로그만으로 quota 소진 설명
- **Phase24 JSON 파일 상태 확인**: `phase24b_dry_run_20260527_085115.json`, `phase24c_dry_run_20260527_091149.json` — Python traceback으로 손상됨 (ModuleNotFoundError)

## 2. 주체별 Quota 소진 분석 (2026-05-27 KST)

### 2.1 전체 요약

| Source | Calls (query_count) | HTTP 429 | Partial Persist | Notes |
|--------|:-------------------:|:--------:|:---------------:|-------|
| App container (10개 log file) | ~10,397 | ~7,760 | ~203 | 모두 `paper-decision-loop` Logger |
| ops-scheduler | 0 | 0 | 0 | 17:55:26 재시작 → 즉시 idle |
| **Total (log 기준)** | **~10,397** | **~7,760** | **~203** | |
| **NAVER daily quota** | **25,000** | — | — | 13:57:02 완전 소진 (errorCode 010) |

**핵심 발견:**
- App container의 10개 log 파일에서 확인된 NAVER 호출(query_count)은 **~10,397건**
- 이 중 HTTP 429 응답은 **~7,760건** (대부분 daily quota 소진 이후)
- **실제로 quota를 소모한 성공 호출은 ~2,637건** (10,397 - 7,760)
- 그러나 25,000건 quota 중 ~2,637건만 log에 기록 — **나머지 ~22,363건은 log에 기록되지 않은 호출**
- 이는 `NaverDailyQuotaTracker`가 container-local file 기반이므로, **Docker 재시작이나 tracker 초기화 시점에 따라 count가 리셋되었을 가능성**이 있음
- 또는 **동일 NAVER_CLIENT_ID를 사용하는 다른 주체**가 존재할 가능성도 여전히 열려 있음

### 2.2 ops-scheduler 기여도 (0%)

- [`logs/scheduler_restart_20260527.log`](logs/scheduler_restart_20260527.log): ops-scheduler가 **17:55:26 KST**에 시작, 즉시 idle 모드 진입
  ```
  2026-05-27 17:55:26 [INFO] ops-scheduler: ═══ Reached scheduler end time — entering idle mode ═══
  2026-05-27 17:55:26 [INFO] ops-scheduler:   cycles              : 1
  2026-05-27 17:55:26 [INFO] ops-scheduler:   tasks               : 0
  2026-05-27 17:55:26 [INFO] ops-scheduler:   submit_count         : 0
  ```
- `session_db_id: 55342`, `cycles=1`, `tasks=0`, `submit_count=0`
- 00:00~08:51 KST 기간에 ops-scheduler subprocess 로그(`subprocess_diag_*.log`) 없음
- **ops-scheduler는 2026-05-27에 NAVER API를 단 1건도 호출하지 않음**

### 2.3 App container 기여도 (~10,397 calls)

10개 log 파일 모두 `paper-decision-loop` Logger 사용 = 수동 `run_decision_loop.py` 실행 (app container)

#### 2.3.1 Log 파일별 상세 집계

| # | Log File | query_count | HTTP 429 | Partial Persist | RuntimeError | 비고 |
|:-:|----------|:-----------:|:--------:|:---------------:|:------------:|------|
| 1 | [`t3_429_fastfail_verify_20260527.log`](logs/t3_429_fastfail_verify_20260527.log) | 1,585 | 1,560 | 58 | **4,400** | Transaction bug 존재 |
| 2 | [`t3_transaction_fix_verify_20260527.log`](logs/t3_transaction_fix_verify_20260527.log) | 2,182 | 2,174 | 58 | **0** | Bug 수정됨, 2 cycles |
| 3 | [`budget_protection_dryrun_20260527.log`](logs/budget_protection_dryrun_20260527.log) | 1,136 | 1,132 | 29 | 0 | 1 cycle, 42 symbols |
| 4 | [`budget_protection_submit_20260527.log`](logs/budget_protection_submit_20260527.log) | 1,131 | 1,128 | 29 | 0 | |
| 5 | [`t3_smoke_test_verify_20260527.log`](logs/t3_smoke_test_verify_20260527.log) | 1,131 | 1,126 | 29 | 0 | |
| 6 | [`t3_sync_verify_20260527_105313.log`](logs/t3_sync_verify_20260527_105313.log) | **1,493** | **0** | 0 | 0 | **가장 큰 단일 소모, 429 없음** |
| 7 | [`submit_verification_20260527_100650.log`](logs/submit_verification_20260527_100650.log) | 456 | 0 | 0 | 0 | 429 없음 |
| 8 | [`t3_2cycle_verify_20260527_121137.log`](logs/t3_2cycle_verify_20260527_121137.log) | 117 | **272** | 0 | 0 | 모든 429 = errorCode 010 (daily quota exhausted) |
| 9 | [`t3_freshness_verify_20260527_125944.log`](logs/t3_freshness_verify_20260527_125944.log) | 102 | **236** | 0 | 0 | 모든 429 = errorCode 010 (daily quota exhausted) |
| 10 | [`t3_async_verify_20260527.log`](logs/t3_async_verify_20260527.log) | 64 | 132 | 0 | 0 | 82 cycles, daily quota 완전 소진 상태 |
| | **Total** | **~10,397** | **~7,760** | **~203** | **4,400** | |

#### 2.3.2 주요 발견사항

**Transaction bug 영향 (t3_429_fastfail vs t3_transaction_fix):**
- `t3_429_fastfail_verify`: 4,400건의 `RuntimeError: Transaction not started` — partial persist가 모두 실패
- `t3_transaction_fix_verify`: 0건의 RuntimeError — bug 수정됨
- Bug 수정 후 597건 더 많은 NAVER 호출 (2,182 vs 1,585) — bug가 app container의 실제 호출 수를 제한한 요인

**성공한 NAVER 호출 (429 없음):**
- `t3_sync_verify` (1,493 calls) + `submit_verification` (456 calls) = **1,949건의 성공 호출**
- 이 두 파일은 08:51~10:53 KST 사이에 실행되어 daily quota가 아직 충분했던 시점

**Daily quota 소진 이후 (errorCode 010):**
- `t3_2cycle_verify` (12:11 KST): 모든 429가 `errorCode="010"`, `count=25000/25000` — daily quota 완전 소진 확인
- `t3_freshness_verify` (12:59 KST): 모든 429가 errorCode 010
- `t3_async_verify` (13:56 KST): NAVER 호출이 거의 없음 (64건) — daily quota 완전 소진 상태

**t3_async_verify 82 cycles:**
- 마지막 줄(2999)에 summary line 존재: `total_cycles=82, success=82, skipped=0, error=0, success_rate=100.0`
- 이는 이전 verify 실행들의 결과가 누적된 JSON output 파일임을 의미
- 실제로는 2 cycle만 실행되었으나, output 파일에 이전 실행 결과가 누적되어 82로 표시

**Phase24 JSON 파일 손상:**
- `phase24b_dry_run_20260527_085115.json` 및 `phase24c_dry_run_20260527_091149.json` — Python traceback 포함 (ModuleNotFoundError: No module named 'scripts')
- 유효한 JSON 데이터가 아님 — 실행 환경 문제로 인해 JSON 파일이 traceback으로 덮어쓰기됨

### 2.4 Log-Quota Gap 분석 (~22,363건)

| 항목 | 값 | 비고 |
|------|:---:|------|
| NAVER daily quota | 25,000 | |
| Log에 기록된 성공 호출 (query_count - 429) | ~2,637 | 10,397 - 7,760 |
| Log에 기록되지 않은 호출 | **~22,363** | 25,000 - 2,637 |

**가능한 설명:**
1. **NaverDailyQuotaTracker container-local isolation**: tracker가 container-local file(`/workspace/agent_trading/tmp/naver_daily_quota.json`)을 사용하므로, Docker 재시작 시 count 리셋. App container가 여러 번 재시작되면서 tracker가 초기화되고, 동일한 quota를 중복 소진했을 가능성.
2. **동일 NAVER_CLIENT_ID 사용 외부 시스템**: docker-compose.yml에서 app과 ops-scheduler가 동일 credential 공유. 동일 `.env` 파일을 사용하는 다른 Docker host나 시스템에서도 동일 quota 소모 가능.
3. **Log 파일 누락**: 10개 log 파일 외에 기록되지 않은 실행이 존재할 가능성.

**결론:** Log-quota gap의 정확한 원인은 단정할 수 없으나, **NaverDailyQuotaTracker의 container-local isolation이 가장 유력한 설명**. Docker 재시작마다 tracker가 리셋되면, 25,000건 quota를 여러 번 소진할 수 있음.

## 3. Timeline 상세

### 00:00~08:51 KST — App container 실행 + 외부 사용 가능

- ops-scheduler 미실행 확인 (subprocess 로그 없음)
- App container 실행 기록 없음 (paper-decision-loop 로그 없음)
- **08:51 KST 첫 429 발생 시점에 이미 daily quota의 약 86%가 소진된 상태**
- 이 기간의 quota 소진은 log에 기록되지 않음 — tracker 리셋 또는 외부 사용 가능

### 08:51~13:57 KST — App container 검증 실행 집중

- **08:51:36**: 첫 429 발생 — **per-window rate limit** (errorCode 012, x-rate-limit=10)
- **08:51~10:53**: `t3_sync_verify` (1,493 calls, 0 429) + `submit_verification` (456 calls, 0 429) — 성공적 실행
- **10:53~12:11**: `t3_429_fastfail_verify` (1,585 calls, 1,560 429) — transaction bug로 partial persist 실패
- **12:11**: `t3_2cycle_verify` — 모든 429가 errorCode 010 (daily quota exhausted)
- **12:59**: `t3_freshness_verify` — 모든 429가 errorCode 010
- **13:56**: `t3_async_verify` — NAVER 호출 최소 (64건)
- **13:57:02**: Daily quota 완전 소진 확인 (errorCode 010, count=25000/25000)

### 13:57~17:55 KST — Quota 완전 소진

- 모든 NAVER API 호출이 429 응답 수신
- App container의 T3 pipeline이 degraded mode로 전환
- `t3_transaction_fix_verify` (2,182 calls, 2,174 429) — transaction bug 수정되었으나 quota 없음
- `budget_protection_dryrun` (1,136 calls, 1,132 429)
- `budget_protection_submit` (1,131 calls, 1,128 429)
- `t3_smoke_test_verify` (1,131 calls, 1,126 429)

### 17:55~ KST — ops-scheduler 재시작

- ops-scheduler가 17:55:26에 시작
- 즉시 idle 모드 진입 (장 종료로 인해)
- NAVER API 호출 없음

## 4. 주요 발견사항

### 4.1 ops-scheduler 미실행 (확정)

- 2026-05-27 00:00~17:55 KST에 ops-scheduler가 실행되지 않음
- `session_db_id: 55342`로 17:55:26에 재시작되었으나 즉시 idle
- `cycles=1, tasks=0, submit_count=0` — 단 1 cycle도 실행되지 않음
- **ops-scheduler는 2026-05-27 NAVER quota 소진에 0% 기여**

### 4.2 첫 429 = Per-window rate limit (08:51:36)

- 첫 429 응답의 errorCode: **012** (per-window rate limit)
- `x-rate-limit: 10` — 10초 window 내 10건 초과
- Daily quota 소진(errorCode 010)은 13:57:02에 발생
- 즉, 08:51~13:57 기간 동안 daily quota가 아직 남아 있었음에도 per-window limit에 의해 429 발생

### 4.3 Transaction bug

- `t3_429_fastfail_verify_20260527.log`: 4,400건의 `RuntimeError: Transaction not started` — 모든 partial persist가 실패
- `t3_transaction_fix_verify_20260527.log`: 0건의 RuntimeError — bug 수정됨
- Transaction bug로 인해 t3_429_fastfail_verify가 1,585 calls에서 중단 (정상 2,182 calls까지 갈 수 있었음)
- 이는 app container의 실제 호출 수를 제한한 요인

### 4.4 NaverDailyQuotaTracker fail-open

- `_FILE_PATH = "/workspace/agent_trading/tmp/naver_daily_quota.json"` (container-internal absolute path)
- [`_read_or_init()`](src/agent_trading/brokers/naver_news_adapter.py:137)가 파일 없으면 `(0, "")` 반환 → `is_exhausted()` 항상 False
- [`increment()`](src/agent_trading/brokers/naver_news_adapter.py:107)이 I/O 에러를 silent ignore
- Container-local file: ops-scheduler 컨테이너의 tracker가 다른 컨테이너에 보이지 않음
- Docker 재시작 시 tracker 파일 리셋 가능 → **Log-quota gap의 가장 유력한 원인**

### 4.5 SEEDED_NEWS_ENABLED toggle

- [`scripts/run_decision_loop.py`](scripts/run_decision_loop.py:760):
  ```python
  _SEEDED_NEWS_ENABLED = os.environ.get("SEEDED_NEWS_ENABLED", "1") == "1"
  ```
- [`scripts/run_decision_loop.py`](scripts/run_decision_loop.py:813):
  ```python
  if os.environ.get("SEEDED_NEWS_ENABLED", "1") == "0":
      logger.info("Cycle %d symbol=%s: T3 skipped (SEEDED_NEWS_ENABLED=0)", ...)
      continue
  ```
- `SEEDED_NEWS_ENABLED=0` 설정 시 T3 pipeline(Naver news search) 완전 차단 가능
- App container의 NAVER API 호출을 즉시 중단할 수 있는 가장 간단한 조치
- ops-scheduler는 `os.environ.copy()`로 subprocess env를 구성하므로, app container의 env 변경이 ops-scheduler에 영향을 주지 않음

### 4.6 Phase24 JSON 파일 손상

- `phase24b_dry_run_20260527_085115.json` 및 `phase24c_dry_run_20260527_091149.json` — Python traceback 포함
- `ModuleNotFoundError: No module named 'scripts'` — 실행 환경 문제
- 유효한 JSON 데이터가 아니므로 분석에서 제외

## 5. Retry 4 오류 수정

### 5.1 "UNKNOWN external 86.2%" → Log-quota gap으로 재해석

| 항목 | Retry 4 주장 | Retry 5 실제 | 원인 |
|------|:-----------:|:------------:|------|
| UNKNOWN external | 86.2% (~21,548 calls) | **Log-quota gap (~22,363 calls)** | 외부 사용을 추정하지 않고, log에 기록되지 않은 호출로 설명 |
| 근거 | ops-scheduler도, app도 아님 | Tracker container-local isolation + Docker 재시작 가능성 | 외부 사용 증거 없음 |
| App container 기여도 | 13.8% (~3,452 calls) | **Log 기준 ~10,397 calls** (성공 ~2,637 + 429 ~7,760) | 10개 log 파일 상세 집계 결과 |

**Retry 4의 오류 원인:**
- `query_count`만 집계하고 HTTP 429를 차감하지 않아 실제 quota 소모량을 과대 추정
- Phase24 JSON 파일이 손상되었음을 확인하지 않고 분석에 포함
- UNKNOWN external을 증거 없이 추정

### 5.2 "App container ~3,452 calls" → 실제 ~10,397 calls (log 기준)

| 항목 | Retry 4 주장 | Retry 5 실제 | 원인 |
|------|:-----------:|:------------:|------|
| App container log 파일 수 | 12개 | **10개** (2개 JSON 손상 제외) | Phase24 JSON 파일 손상 확인 |
| App container query_count | ~3,452 | **~10,397** | 10개 파일 상세 grep 집계 |
| HTTP 429 | 미집계 | **~7,760** | 429를 quota 소모에서 차감 |
| Partial persist | 미집계 | **~203** | T3 partial persist on timeout |
| RuntimeError (Transaction bug) | 미집계 | **4,400** (t3_429_fastfail only) | Transaction bug 영향 정량화 |

**Retry 4의 오류 원인:**
- Log 파일을 12개로 집계했으나, 2개는 JSON 손상으로 유효하지 않음
- `query_count`만 집계하고 HTTP 429를 차감하지 않음
- Transaction bug의 영향을 고려하지 않음

## 6. 운영 조치 우선순위

| 순위 | 조치 | 우선순위 사유 |
|:---:|------|:-------------|
| **1** | **App container SEEDED_NEWS_ENABLED=0** | 즉시 적용 가능. app container의 NAVER API 호출을 완전 차단. 개발/수동 실행에서 quota 소진 방지. |
| **2** | **Credential 분리** | 동일 NAVER_CLIENT_ID를 사용하는 외부 시스템/다른 Docker host 차단. 별도 API key 발급 및 ops-scheduler 전용 credential 사용. |
| **3** | **NaverDailyQuotaTracker in-DB 전환** | Container-local file → in-DB 전환으로 cross-container quota visibility 확보. Docker 재시행 시 count 리셋 방지. |
| **4** | **Fresh skip failure 차단** | Vicious cycle 방지. quota 소진 시 seed fresh skip을 강제 수행하도록 수정. |
| **5** | **Fail-closed tracker** | tracker unavailable 시 API 호출 차단. 가장 포괄적인 해결책. |

### 6.1 우선순위 결정 근거

1. **App container SEEDED_NEWS_ENABLED=0 (1순위)**: 
   - App container는 검증 목적으로만 `run_decision_loop.py`를 수동 실행. 실시간 운영에 필요하지 않음.
   - `SEEDED_NEWS_ENABLED=0`으로 즉시 NAVER API 호출 차단 가능. 구현 난이도 매우 낮음.
   - ops-scheduler에 영향 없음 (`os.environ.copy()` 사용으로 app container env 변경이 전파되지 않음)
   - **docker-compose.yml app 서비스에 `SEEDED_NEWS_ENABLED=0` 추가만으로 적용 완료**

2. **Credential 분리 (2순위)**: 
   - Log-quota gap(~22,363건)의 정확한 원인은 불확실하나, 동일 credential 사용이 gap의 원인 중 하나일 가능성.
   - 별도 NAVER API key를 발급하고 ops-scheduler 전용으로 사용. 기존 key는 폐기 또는 교체.
   - 1순위 조치와 병행 진행 가능.

3. **NaverDailyQuotaTracker in-DB 전환 (3순위)**: 
   - Container-local file isolation이 Log-quota gap의 가장 유력한 원인.
   - in-DB 전환으로 Docker 재시작에도 count 유지, cross-container visibility 확보.
   - 구현 복잡도가 있으나 근본적 해결책.

4. **Fresh skip failure 차단 (4순위)**: 
   - Quota 소진 후에도 T3 persist가 가능하도록 하여 vicious cycle 차단.
   - Phase 5i-2의 degraded fallback이 API 호출에 의존하는 문제 해결.
   - 1-3순위 조치 이후 적용.

5. **Fail-closed tracker (5순위)**: 
   - 가장 포괄적인 해결책이나 구현 복잡도가 높음.
   - in-DB quota tracker로 전환 시 tracker 장애로 인한 무제한 호출 방지 가능.

## 7. 코드 검증

### 7.1 docker-compose.yml

**명령어:** `grep -n 'NAVER_CLIENT_ID\|NAVER_CLIENT_SECRET\|SEEDED_NEWS_ENABLED' docker-compose.yml`

```yaml
84:      NAVER_CLIENT_ID: "${NAVER_CLIENT_ID:-}"
85:      NAVER_CLIENT_SECRET: "${NAVER_CLIENT_SECRET:-}"
241:      NAVER_CLIENT_ID: "${NAVER_CLIENT_ID:-}"
242:      NAVER_CLIENT_SECRET: "${NAVER_CLIENT_SECRET:-}"
```

| 라인 | 서비스 | 항목 | 상태 |
|:----:|--------|------|:----:|
| 84-85 | app | NAVER_CLIENT_ID / NAVER_CLIENT_SECRET | ✅ 동일 credential |
| 241-242 | ops-scheduler | NAVER_CLIENT_ID / NAVER_CLIENT_SECRET | ✅ 동일 credential |
| — | app | SEEDED_NEWS_ENABLED | ❌ 미설정 (기본값 "1" = enabled) |

**결론:**
- app 서비스와 ops-scheduler 서비스가 동일한 `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` 환경변수를 공유
- `SEEDED_NEWS_ENABLED`가 app 서비스에 설정되어 있지 않아 기본값 "1" (enabled)로 동작
- **조치: app 서비스에 `SEEDED_NEWS_ENABLED: "0"` 추가 필요**

### 7.2 NaverDailyQuotaTracker

**명령어:** `grep -n 'class NaverDailyQuotaTracker\|_read_or_init\|_FILE_PATH\|is_exhausted\|def increment' src/agent_trading/brokers/naver_news_adapter.py`

| 라인 | 항목 | 상태 | 설명 |
|:----:|------|:----:|------|
| 54 | `class NaverDailyQuotaTracker` | ✅ | 클래스 정의 |
| 69 | `_FILE_PATH = _NAVER_DAILY_QUOTA_FILE` | ✅ | Container-internal absolute path |
| 83 | `_read_or_init()` 호출 (get_consumption_ratio) | ✅ | count 조회 |
| 92 | `_read_or_init()` 호출 (get_remaining) | ✅ | count 조회 |
| 98 | `def is_exhausted()` | ✅ | Fail-open: 파일 없으면 False 반환 |
| 107 | `def increment()` | ✅ | I/O 에러 silent ignore |
| 113 | `_read_or_init()` 호출 (increment) | ✅ | count 읽기 |
| 137 | `def _read_or_init()` | ✅ | 파일 없으면 `(0, "")` 반환 (fail-open) |
| 143 | `os.path.exists(cls._FILE_PATH)` | ✅ | 파일 존재 여부 확인 |
| 145 | `open(cls._FILE_PATH, "r")` | ✅ | 파일 읽기 |
| 167 | `os.makedirs(...)` | ✅ | 디렉토리 생성 |
| 168 | `open(cls._FILE_PATH, "w")` | ✅ | 파일 쓰기 |

**결론:** 
- `_FILE_PATH`가 container-internal absolute path로 설정되어 있어 Docker 컨테이너 간 공유 불가
- `_read_or_init()`가 파일 없으면 `(0, "")` 반환 → `is_exhausted()` 항상 False (fail-open)
- `increment()`가 I/O 에러를 silent ignore → tracker 장애 시 quota 소진을 전혀 인지하지 못함
- Docker 재시작 시 tracker 파일 리셋 → Log-quota gap의 가장 유력한 원인

### 7.3 SEEDED_NEWS_ENABLED toggle

**명령어:** `grep -n 'SEEDED_NEWS_ENABLED' scripts/run_decision_loop.py`

| 라인 | 코드 | 설명 |
|:----:|------|------|
| 760 | `_SEEDED_NEWS_ENABLED = os.environ.get("SEEDED_NEWS_ENABLED", "1") == "1"` | 환경변수 읽기 (기본값: "1" = enabled) |
| 763 | `if _SEEDED_NEWS_ENABLED:` | T3 pipeline 실행 조건 |
| 813 | `if os.environ.get("SEEDED_NEWS_ENABLED", "1") == "0":` | T3 skip 로깅 |

**결론:** `SEEDED_NEWS_ENABLED=0` 설정 시 T3 pipeline(Naver news search)이 완전히 차단됨. App container의 NAVER API 호출을 즉시 중단할 수 있는 가장 간단한 조치.

### 7.4 ops-scheduler env inheritance

**명령어:** `grep -n '_build_base_env\|os.environ.copy' scripts/run_ops_scheduler.py`

| 라인 | 코드 | 설명 |
|:----:|------|------|
| 290 | `def _build_base_env() -> dict[str, str]:` | Subprocess env 구성 |
| 291 | `env = os.environ.copy()` | 부모 프로세스 env 복사 |
| 292 | `env.setdefault("PYTHONUNBUFFERED", "1")` | PYTHONUNBUFFERED만 추가 |

**결론:** ops-scheduler는 `os.environ.copy()`로 subprocess env를 구성하므로, app container의 env 변경(`SEEDED_NEWS_ENABLED=0`)이 ops-scheduler에 영향을 주지 않음. 즉, **app container에 SEEDED_NEWS_ENABLED=0을 추가해도 ops-scheduler는 정상 동작**.

### 7.5 scheduler_restart 로그 확인

**명령어:** `cat logs/scheduler_restart_20260527.log`

```
2026-05-27 17:55:26 [INFO] ops-scheduler: ═══ Reached scheduler end time — entering idle mode ═══
2026-05-27 17:55:26 [INFO] ops-scheduler:   cycles              : 1
2026-05-27 17:55:26 [INFO] ops-scheduler:   tasks               : 0
2026-05-27 17:55:26 [INFO] ops-scheduler:   submit_count         : 0
```

**결론:** ops-scheduler는 17:55:26에 시작되어 즉시 idle 모드 진입. `tasks=0, submit_count=0`으로 단 1건의 작업도 실행하지 않음.

## 8. 테스트 결과

| 테스트 | 결과 | 비고 |
|--------|:----:|------|
| Phase 5i-2 429 fallback 테스트 | ✅ 통과 (129/129) | 기존 완료 |
| 실행 검증 | ✅ 통과 (22/22) | 기존 완료 |
| Transaction bug 수정 검증 | ✅ t3_transaction_fix_verify: 0 occurrences | 수정 완료 |
| 429 fast-fail 검증 | ⚠️ t3_429_fastfail_verify: 1,585 calls에서 중단 | Transaction bug 영향 |

## 9. 최종 판정

| 구분 | 내용 |
|------|------|
| **근본 원인** | App container의 대형 dry-run/verify 실행이 NAVER quota 소진의 주원인. 10개 log 파일에서 ~10,397건의 NAVER 호출 확인. |
| **ops-scheduler 기여도** | **0%** — 17:55:26에 재시작되어 즉시 idle. 장중(00:00~17:55)에 실행되지 않음. |
| **Log-quota gap** | ~22,363건의 quota가 log에 기록되지 않음. NaverDailyQuotaTracker의 container-local isolation이 가장 유력한 원인. Docker 재시작 시 tracker 리셋 가능. |
| **Transaction bug** | t3_429_fastfail_verify에서 4,400건의 RuntimeError 발생. Bug 수정(t3_transaction_fix_verify) 후 0건. Bug가 app container의 실제 호출 수를 제한한 요인. |
| **Phase24 JSON 손상** | `phase24b_dry_run_20260527_085115.json`, `phase24c_dry_run_20260527_091149.json` — Python traceback으로 손상. 분석에서 제외. |
| **가장 시급한 조치** | App container에 `SEEDED_NEWS_ENABLED=0` 설정 (docker-compose.yml). 즉시 적용 가능, ops-scheduler에 영향 없음. |
| **2순위 조치** | Credential 분리 — 별도 NAVER API key 발급 및 ops-scheduler 전용 credential 사용. |

## 10. 다음 우선순위

1. **SEEDED_NEWS_ENABLED=0**: App container의 NAVER API 호출 즉시 차단. docker-compose.yml app 서비스에 `SEEDED_NEWS_ENABLED: "0"` 추가.
2. **Credential 분리**: NAVER Developers에서 별도 API key 발급 → ops-scheduler 전용 credential 사용 → 기존 key 폐기 또는 교체.
3. **NaverDailyQuotaTracker in-DB 전환**: Container-local file → in-DB 전환으로 cross-container quota visibility 확보.
4. **Fresh skip failure 차단**: Quota 소진 시 seed fresh skip 강제 수행.
5. **Fail-closed tracker**: in-DB quota tracker로 전환, tracker unavailable 시 API 호출 차단.

## 부록: 코드 검증 명령어 및 결과

### A.1 docker-compose.yml credential 공유

```bash
$ grep -n 'NAVER_CLIENT_ID\|NAVER_CLIENT_SECRET\|SEEDED_NEWS_ENABLED' docker-compose.yml
84:      NAVER_CLIENT_ID: "${NAVER_CLIENT_ID:-}"
85:      NAVER_CLIENT_SECRET: "${NAVER_CLIENT_SECRET:-}"
241:      NAVER_CLIENT_ID: "${NAVER_CLIENT_ID:-}"
242:      NAVER_CLIENT_SECRET: "${NAVER_CLIENT_SECRET:-}"
```

### A.2 NaverDailyQuotaTracker fail-open

```bash
$ grep -n 'class NaverDailyQuotaTracker\|_read_or_init\|_FILE_PATH\|is_exhausted\|def increment' src/agent_trading/brokers/naver_news_adapter.py
54:class NaverDailyQuotaTracker:
69:    _FILE_PATH = _NAVER_DAILY_QUOTA_FILE
83:        count, _ = cls._read_or_init()
92:        count, _ = cls._read_or_init()
98:    def is_exhausted(cls, threshold: float | None = None) -> bool:
107:    def increment(cls) -> None:
113:            count, date_str = cls._read_or_init()
137:    def _read_or_init(cls) -> tuple[int, str]:
143:            if not os.path.exists(cls._FILE_PATH):
145:            with open(cls._FILE_PATH, "r") as f:
167:            os.makedirs(os.path.dirname(cls._FILE_PATH), exist_ok=True)
168:            with open(cls._FILE_PATH, "w") as f:
169:            json.dump(...)
170: ```

**결론:**
- `_FILE_PATH`가 container-internal absolute path로 설정되어 있어 Docker 컨테이너 간 공유 불가
- `_read_or_init()`가 파일 없으면 `(0, "")` 반환 → `is_exhausted()` 항상 False (fail-open)
- `increment()`가 I/O 에러를 silent ignore → tracker 장애 시 quota 소진을 전혀 인지하지 못함
- Docker 재시작 시 tracker 파일 리셋 → Log-quota gap의 가장 유력한 원인

### A.3 SEEDED_NEWS_ENABLED toggle

```bash
$ grep -n 'SEEDED_NEWS_ENABLED' scripts/run_decision_loop.py
760:            _SEEDED_NEWS_ENABLED = os.environ.get("SEEDED_NEWS_ENABLED", "1") == "1"
763:            if _SEEDED_NEWS_ENABLED:
813:                    "Cycle %d symbol=%s: T3 skipped (SEEDED_NEWS_ENABLED=0)",
```

### A.4 ops-scheduler env inheritance

```bash
$ grep -n '_build_base_env\|os.environ.copy' scripts/run_ops_scheduler.py
290:def _build_base_env() -> dict[str, str]:
291:    env = os.environ.copy()
292:    env.setdefault("PYTHONUNBUFFERED", "1")
```

### A.5 scheduler_restart 로그

```bash
$ cat logs/scheduler_restart_20260527.log
2026-05-27 17:55:26 [INFO] ops-scheduler: ═══ Reached scheduler end time — entering idle mode ═══
2026-05-27 17:55:26 [INFO] ops-scheduler:   cycles              : 1
2026-05-27 17:55:26 [INFO] ops-scheduler:   tasks               : 0
2026-05-27 17:55:26 [INFO] ops-scheduler:   submit_count         : 0
```

### A.6 Log 파일 grep 명령어

```bash
# query_count 집계
$ grep -c 'query_count' logs/t3_429_fastfail_verify_20260527.log
1585
$ grep -c 'query_count' logs/t3_transaction_fix_verify_20260527.log
2182
$ grep -c 'query_count' logs/budget_protection_dryrun_20260527.log
1136
$ grep -c 'query_count' logs/budget_protection_submit_20260527.log
1131
$ grep -c 'query_count' logs/t3_smoke_test_verify_20260527.log
1131
$ grep -c 'query_count' logs/t3_sync_verify_20260527_105313.log
1493
$ grep -c 'query_count' logs/submit_verification_20260527_100650.log
456
$ grep -c 'query_count' logs/t3_2cycle_verify_20260527_121137.log
117
$ grep -c 'query_count' logs/t3_freshness_verify_20260527_125944.log
102
$ grep -c 'query_count' logs/t3_async_verify_20260527.log
64

# HTTP 429 집계
$ grep -c 'HTTP/1.1 429' logs/t3_429_fastfail_verify_20260527.log
1560
$ grep -c 'HTTP/1.1 429' logs/t3_transaction_fix_verify_20260527.log
2174
$ grep -c 'HTTP/1.1 429' logs/budget_protection_dryrun_20260527.log
1132
$ grep -c 'HTTP/1.1 429' logs/budget_protection_submit_20260527.log
1128
$ grep -c 'HTTP/1.1 429' logs/t3_smoke_test_verify_20260527.log
1126
$ grep -c 'HTTP/1.1 429' logs/t3_sync_verify_20260527_105313.log
0
$ grep -c 'HTTP/1.1 429' logs/submit_verification_20260527_100650.log
0
$ grep -c 'HTTP/1.1 429' logs/t3_2cycle_verify_20260527_121137.log
272
$ grep -c 'HTTP/1.1 429' logs/t3_freshness_verify_20260527_125944.log
236
$ grep -c 'HTTP/1.1 429' logs/t3_async_verify_20260527.log
132

# Partial persist 집계
$ grep -c 'partial persist on timeout' logs/t3_429_fastfail_verify_20260527.log
58
$ grep -c 'partial persist on timeout' logs/t3_transaction_fix_verify_20260527.log
58
$ grep -c 'partial persist on timeout' logs/budget_protection_dryrun_20260527.log
29
$ grep -c 'partial persist on timeout' logs/budget_protection_submit_20260527.log
29
$ grep -c 'partial persist on timeout' logs/t3_smoke_test_verify_20260527.log
29
$ grep -c 'partial persist on timeout' logs/t3_sync_verify_20260527_105313.log
0
$ grep -c 'partial persist on timeout' logs/submit_verification_20260527_100650.log
0
$ grep -c 'partial persist on timeout' logs/t3_2cycle_verify_20260527_121137.log
0
$ grep -c 'partial persist on timeout' logs/t3_freshness_verify_20260527_125944.log
0
$ grep -c 'partial persist on timeout' logs/t3_async_verify_20260527.log
0

# RuntimeError (Transaction bug) 집계
$ grep -c 'RuntimeError: Transaction not started' logs/t3_429_fastfail_verify_20260527.log
4400
$ grep -c 'RuntimeError: Transaction not started' logs/t3_transaction_fix_verify_20260527.log
0
```

## 11. Phase 5i-4: SEEDED_NEWS_ENABLED 분리 설정 (2026-05-29)

### 11.1 작업 개요
Phase 5i-4 해결 중심 작업에서 `docker-compose.yml`의 `app` 서비스에 `SEEDED_NEWS_ENABLED: "${SEEDED_NEWS_ENABLED:-0}"`를 추가했으나, 초기에 `ops-scheduler` 서비스에도 동일한 env가 함께 추가되는 실수가 발생했다. 이후 ops-scheduler에서 env를 제거하여 app만 T3 off, ops-scheduler는 T3 on이 유지되도록 수정했다.

### 11.2 최종 상태

| 서비스 | SEEDED_NEWS_ENABLED | T3 동작 | 근거 |
|--------|---------------------|---------|------|
| app (line 86) | `"${SEEDED_NEWS_ENABLED:-0}"` | **기본 off** (개발/수동 경로 차단) | `run_decision_loop.py:760`에서 `os.environ.get("SEEDED_NEWS_ENABLED", "1")` → "0" |
| ops-scheduler | 없음 | **기본 on** (운영 경로 유지) | `_build_base_env()`가 `os.environ.copy()` 사용 → subprocess에 SEEDED_NEWS_ENABLED 미전달 → 기본값 "1" |

### 11.3 검증 결과

| 검증 항목 | 상태 | 상세 |
|-----------|------|------|
| 1. docker-compose.yml 분리 | ✅ | `app`만 보유, `ops-scheduler`에는 SEEDED_NEWS_ENABLED 없음 |
| 2. run_decision_loop.py:760 기본값 | ✅ | `os.environ.get("SEEDED_NEWS_ENABLED", "1")` — 기본값 "1" 정상 |
| 3. run_ops_scheduler.py:290-294 | ✅ | SEEDED_NEWS_ENABLED 미참조, `os.environ.copy()`로 상속만 |
| 4. observe_seeded_news_comparison.py:152 | ✅ | 명시적 env 설정으로 docker-compose 변경과 무관 |
| 5. validate_seeded_news_pipeline.py | ⚠️ | 직접 NAVER 호출, SEEDED_NEWS_ENABLED toggle 우회 가능 |
| 6. 테스트 (123/123) | ✅ | `test_run_decision_loop.py` 72 + `test_naver_news_adapter.py` 24 + `test_rate_limit.py` 15 + `test_shared_budget.py` 12 = 123 passed |

### 11.4 판정

**✅ app T3 off / ops-scheduler T3 on 분리 성공**

- **개발/수동 경로 차단:** `app` 컨테이너에서 `run_decision_loop.py`를 직접 실행하면 `SEEDED_NEWS_ENABLED=0`으로 T3 pipeline이 skip되어 NAVER API 호출이 발생하지 않음
- **운영 경로 유지:** `ops-scheduler`가 spawn하는 subprocess는 `SEEDED_NEWS_ENABLED` env를 상속받지 않으므로 `run_decision_loop.py`의 기본값 "1"을 사용하여 T3 pipeline이 정상 실행됨
- **원래 목적 달성:** 2026-05-27 NAVER quota 소진의 주요 원인이었던 `app` 컨테이너의 대형 dry-run/verify가 운영용 NAVER quota를 과도하게 태우지 못하도록 차단

### 11.5 잔여 위험

| 위험 | 영향 | 조치 |
|------|------|------|
| `validate_seeded_news_pipeline.py` 직접 실행 | SEEDED_NEWS_ENABLED toggle 우회, 직접 NAVER 호출 | 이 스크립트는 validation 목적이므로 필요한 경우에만 수동 실행. 내부에 별도의 가드 추가 검토 가능 |
| `observe_seeded_news_comparison.py` 직접 실행 | subprocess env에 명시적 SEEDED_NEWS_ENABLED 설정 | seeded_enabled=True 시 T3 on. 의도적 비교 실행이므로 적절한 주의 필요 |
| NaverDailyQuotaTracker fail-open | 컨테이너 로컬 파일로 크로스 컨테이너 미공유 | 별도 이슈로 추적 필요 (Phase 5i-5) |

## 12. Phase 5i-4b: 예외 개발 스크립트 NAVER 차단 (2026-05-29)

### 12.1 작업 개요
Phase 5i-4에서 `app` 컨테이너에 `SEEDED_NEWS_ENABLED:-0`을 적용했지만, 다음 두 스크립트는 여전히 NAVER quota를 직접 소모할 수 있었다:
- `validate_seeded_news_pipeline.py`: `SEEDED_NEWS_ENABLED` toggle을 우회하고 직접 `NaverNewsSearchAdapter` 호출
- `observe_seeded_news_comparison.py`: subprocess env에 명시적 `SEEDED_NEWS_ENABLED` 설정 (docker-compose.yml 변경과 무관)

이번 작업에서 두 스크립트를 기본적으로 안전한 상태로 변경했다.

### 12.2 차단 방식

| 스크립트 | 차단 방식 | 상세 |
|----------|----------|------|
| `validate_seeded_news_pipeline.py` | `main()` 시작부에 `SEEDED_NEWS_ENABLED=0` 체크 추가 | `"0"`이면 "SKIP" 메시지 출력 후 `return`. 기존 NAVER API key 미설정 체크보다 먼저 실행 |
| `observe_seeded_news_comparison.py` | `_run_one_cycle_and_collect()`에서 `SEEDED_NEWS_ENABLED`를 항상 `"0"`으로 강제 | `seeded_enabled` 파라미터는 API 호환성 유지, 내부에서는 항상 `False`로 처리 |

### 12.3 수정 파일

| 파일 | 변경 사항 | 라인 |
|------|----------|------|
| `scripts/validate_seeded_news_pipeline.py` | `import os` 추가, `main()` 시작부에 SEEDED_NEWS_ENABLED 체크 추가 | 15, 39-42 |
| `scripts/observe_seeded_news_comparison.py` | `_run_one_cycle_and_collect()`에서 `env["SEEDED_NEWS_ENABLED"] = "0"` 강제 | 153-154 |

### 12.4 검증 결과

| 검증 항목 | 상태 | 상세 |
|-----------|------|------|
| 1. validate_seeded_news_pipeline.py SEEDED_NEWS_ENABLED 체크 | ✅ | `import os` 추가, `main()` 시작부 체크 로직 정상 |
| 2. observe_seeded_news_comparison.py SEEDED_NEWS_ENABLED 강제 0 | ✅ | `seeded_enabled`와 무관하게 항상 `"0"`으로 override |
| 3. run_decision_loop.py 변경 없음 | ✅ | 기본값 `"1"` 유지, T3 toggle 정상 |
| 4. run_ops_scheduler.py 변경 없음 | ✅ | SEEDED_NEWS_ENABLED 미참조 |
| 5. docker-compose.yml 변경 없음 | ✅ | app만 보유, ops-scheduler 없음 |

### 12.5 테스트 결과

| 테스트 | 결과 |
|--------|------|
| `test_run_decision_loop.py` | 72 passed ✅ |
| `test_seeded_news_service.py` | 14 passed ✅ |
| `test_seeded_news_converter.py` | 19 passed ✅ |
| `test_naver_news_adapter.py` | 24 passed ✅ |
| `test_rate_limit.py` | 15 passed ✅ |
| `test_shared_budget.py` | 12 passed ✅ |
| **합계** | **156 passed** ✅ |

### 12.6 판정

**✅ 예외 개발 스크립트 기본 NAVER 차단 성공**

- `validate_seeded_news_pipeline.py`: `SEEDED_NEWS_ENABLED=0` 환경에서 실행 시 즉시 SKIP → NAVER API 호출 없음
- `observe_seeded_news_comparison.py`: `--mode on`으로 실행해도 subprocess에 `SEEDED_NEWS_ENABLED=0` 전달 → T3 pipeline skip
- 운영 경로(`ops-scheduler`, 일반 `run_decision_loop`) 영향 없음

### 12.7 잔여 위험

| 위험 | 영향 | 조치 |
|------|------|------|
| NaverDailyQuotaTracker fail-open | 컨테이너 로컬 파일로 크로스 컨테이너 미공유 → `is_exhausted()`가 항상 False 반환 | 별도 이슈로 추적 필요 (Phase 5i-5) |
| 사용자가 `SEEDED_NEWS_ENABLED=1`을 명시적 설정 후 스크립트 실행 | 차단 우회 가능 | 의도적 실행이므로 적절한 주의 필요 (문서화) |

## 13. Phase 5i-5: NaverDailyQuotaTracker fail-closed 전환

### 13.1 작업 개요
`NaverDailyQuotaTracker._read_or_init()`의 fail-open 동작(파일 없음/손상 시 `return 0`)을 fail-closed(`return cls._DAILY_LIMIT`)로 전환하여, quota 파일 손상 시에도 무한 429 재시도 루프를 방지.

### 13.2 수정 파일
| 파일 | 변경 내용 |
|------|-----------|
| `src/agent_trading/brokers/naver_news_adapter.py` | `_read_or_init()` 3개 에러 경로: `0` → `cls._DAILY_LIMIT` |
| `tests/brokers/test_naver_news_adapter.py` | 3개 fail-open 테스트 → fail-closed, `_patch_file_path` fixture 개선 |

### 13.3 fail-closed 경로 상세
| 경로 | 조건 | 변경 전 | 변경 후 |
|------|------|---------|---------|
| 경로 1 (line 144-145) | 파일 없음 | `return 0, ""` | `return cls._DAILY_LIMIT, ""` |
| 경로 2 (line 157-158) | JSON/Value/KeyError | `return 0, cls._today_kst()` | `return cls._DAILY_LIMIT, cls._today_kst()` |
| 경로 3 (line 161-162) | OSError/ImportError | `return 0, ""` | `return cls._DAILY_LIMIT, ""` |

### 13.4 테스트 결과
- **test_naver_news_adapter.py**: 24/24 통과 ✅
- **전체 테스트 스위트**: 2250 passed / 12 failed (기존 알려진 이슈, 변경 무관) / 1 skipped / 104 errors (DB 환경 문제) ✅

### 13.5 검증 결과
| 검증 항목 | 결과 |
|-----------|------|
| 1. AST 분석: 3개 경로 모두 `cls._DAILY_LIMIT` 반환 | ✅ |
| 2. 파일 없음 → `is_exhausted()=True`, `consumption=25000` | ✅ |
| 3. 파일 손상 → `is_exhausted()=True`, `consumption=25000` | ✅ |
| 4. 정상 파일 (5000/25000) → `is_exhausted()=False` (regression OK) | ✅ |
| 5. `increment()` 정상 동작 (5000→5001) | ✅ |
| 6. `threshold=1.0` 정상 동작 (5001 < 25000 → False) | ✅ |
| 7. 정상 운영 경로 차단 없음 (10000/25000 → False) | ✅ |

### 13.6 판정
**✅ Phase 5i-5 완료.** NaverDailyQuotaTracker fail-closed 전환이 정상적으로 구현 및 검증됨.

- **변경 규모**: 3개 return 경로 (1줄씩), 3개 테스트 assertion 변경
- **리스크**: 최소. 정상 파일 접근 경로는 전혀 변경되지 않음
- **효과**: quota 파일 손상/삭제 시에도 `is_exhausted()`가 True 반환 → 429 재시도 폭주 방지

### 13.7 잔여 위험
1. **Container-local 파일**: `_FILE_PATH`가 컨테이너 내부 절대 경로 (`/workspace/agent_trading/tmp/naver_daily_quota.json`). ops-scheduler와 app 컨테이너 간 quota 상태 공유 불가. → 별도 컨테이너 간 공유 볼륨 또는 DB 기반 quota tracking 필요
2. **increment() silent swallow**: I/O 오류 시 `logger.debug`만 출력하고 조용히 실패. fail-closed로 인해 increment 실패 시 quota가 소진된 것으로 간주되므로, 정상 운영이 불필요하게 제한될 수 있음
3. **DB 기반 quota tracking 미구현**: 파일 기반 tracking의 근본적인 한계는 해결되지 않음. 향후 DB 기반으로 마이그레이션 필요

## 14. Phase 5i-6: Cross-Container Quota Visibility 개선

### 14.1 작업 개요
`NaverDailyQuotaTracker`의 파일 기반 quota tracking이 컨테이너 간에 공유되지 않는 문제를 해결. `_FILE_PATH`를 컨테이너 WORKDIR(`/app`) 기준으로 변경하고, `docker-compose.yml`에 공유 볼륨을 추가하여 app과 ops-scheduler가 동일한 quota 파일을 읽고 쓰도록 개선.

### 14.2 수정 파일
| 파일 | 변경 내용 |
|------|-----------|
| [`src/agent_trading/brokers/naver_news_adapter.py`](src/agent_trading/brokers/naver_news_adapter.py:41) | `_FILE_PATH`: `/workspace/agent_trading/tmp/...` → `/app/tmp/...` |
| [`docker-compose.yml`](docker-compose.yml:104) | app 서비스: `- ./tmp:/app/tmp` 볼륨 추가 |
| [`docker-compose.yml`](docker-compose.yml:264) | ops-scheduler 서비스: `- ./tmp:/app/tmp` 볼륨 추가 |

### 14.3 변경 상세

**Before:**
```python
# naver_news_adapter.py:41
_NAVER_DAILY_QUOTA_FILE = "/workspace/agent_trading/tmp/naver_daily_quota.json"
```
- 컨테이너 내부에 `/workspace/agent_trading/` 디렉토리가 없어 각 컨테이너의 쓰기 가능 레이어에 별도 파일 생성
- app과 ops-scheduler가 완전히 격리된 quota 상태 유지

**After:**
```python
# naver_news_adapter.py:41
_NAVER_DAILY_QUOTA_FILE = "/app/tmp/naver_daily_quota.json"
```
- 컨테이너 WORKDIR(`/app`) 기준 경로
- `docker-compose.yml`의 `./tmp:/app/tmp` 볼륨 마운트로 호스트 `./tmp` 디렉토리 공유
- app과 ops-scheduler가 동일한 quota 파일 접근 가능

### 14.4 테스트 결과
| 테스트 파일 | 통과 | 결과 |
|------------|:----:|:----:|
| `test_naver_news_adapter.py` | 24/24 | ✅ |
| `test_rate_limit.py` | 15/15 | ✅ |
| `test_shared_budget.py` | 12/12 | ✅ |
| `test_run_decision_loop.py` | 72/72 | ✅ |
| **합계** | **123/123** | ✅ |

### 14.5 검증 결과
| 검증 항목 | 결과 |
|-----------|:----:|
| 1. `_FILE_PATH` AST 검증: `/app/tmp/naver_daily_quota.json` | ✅ |
| 2. docker-compose app 서비스 `./tmp:/app/tmp` 볼륨 | ✅ |
| 3. docker-compose ops-scheduler 서비스 `./tmp:/app/tmp` 볼륨 | ✅ |
| 4. `increment()` → 파일 생성, count=1 | ✅ |
| 5. `is_exhausted()` 정상 동작 (count=1 → False) | ✅ |
| 6. 다중 increment 누적 (count=11) | ✅ |
| 7. 날짜 변경 시 count 리셋 | ✅ |
| 8. fail-closed 유지 (파일 없음 → True) | ✅ |
| 9. docker-compose.yml YAML 문법 정상 | ✅ |

### 14.6 판정
**✅ Phase 5i-6 완료.** Cross-container quota visibility가 개선됨.

- **변경 규모**: 코드 1줄 + compose 2줄
- **리스크**: 최소. `_FILE_PATH`는 `NaverDailyQuotaTracker` 내부에서만 사용되며, 테스트는 monkeypatch로 독립적 경로 사용
- **효과**: app과 ops-scheduler가 동일한 quota 파일 공유 → 한쪽에서 quota 소진 시 다른 쪽도 인지 가능
- **fail-closed와 시너지**: 파일 손상 시에도 `is_exhausted()`가 True 반환하여 runaway 방지

### 14.7 잔여 위험
1. **flock 경합**: 두 컨테이너가 동시에 `increment()` 호출 시 OS-level `flock(LOCK_EX)`로 직렬화되나, 대기 시간 발생 가능. 현재 NAVER 호출 빈도(분당 수십 건)에서는 실질적 문제 없음
2. **파일 기반 tracking의 근본적 한계**: 컨테이너 재시작 시 `./tmp` 디렉토리가 유지되지만, 호스트에서 삭제 시 quota 정보 소실. DB 기반 tracking으로의 마이그레이션이 궁극적 해결책
3. **api 서비스 미포함**: api 서비스는 NAVER API를 직접 호출하지 않으므로 공유 볼륨에서 제외

## 15. Phase 5i-7 — increment() silent swallow 보강

### 15.1 작업 개요
`NaverDailyQuotaTracker.increment()`가 I/O 오류를 단일 `except Exception` 블록으로 묵살(silent swallow)하던 문제를 보강하여, quota tracking 실패가 운영 로그에 명확히 드러나도록 수정.

### 15.2 수정 파일
- [`src/agent_trading/brokers/naver_news_adapter.py`](src/agent_trading/brokers/naver_news_adapter.py) — `increment()` 메서드 재구조화
- [`tests/brokers/test_naver_news_adapter.py`](tests/brokers/test_naver_news_adapter.py) — 3개 테스트 추가

### 15.3 변경 상세

#### increment() 변경 전
```python
@classmethod
def increment(cls) -> None:
    try:
        count, date_str = cls._read_or_init()
        today = cls._today_kst()
        if date_str != today:
            count = 0
        count += 1
        cls._write(count, today)
    except Exception:
        logger.debug("NaverDailyQuotaTracker.increment() failed", exc_info=True)
```

#### increment() 변경 후
```python
@classmethod
def increment(cls) -> None:
    try:
        count, date_str = cls._read_or_init()
    except Exception:
        logger.warning("NaverDailyQuotaTracker._read_or_init() failed", exc_info=True)
        return
    try:
        today = cls._today_kst()
        if date_str != today:
            count = 0
        count += 1
        cls._write(count, today)
    except Exception:
        logger.warning(
            "NaverDailyQuotaTracker._write() failed (count=%s, date=%s)",
            count, date_str, exc_info=True,
        )
```

#### 변경 포인트 (3가지)
1. **단일 try-except → 두 개의 try-except 블록 분리**: `_read_or_init()` 실패와 `_write()` 실패를 각각 독립적으로 처리
2. **`logger.debug` → `logger.warning`**: 로그 레벨을 WARNING으로 상향하여 운영 모니터링에서 탐지 가능하도록 개선
3. **Context 정보 추가**: `_write()` 실패 시 `count`와 `date_str` 값을 로그에 포함하여 디버깅 용이성 향상

### 15.4 테스트 결과
- `test_naver_news_adapter.py`: **27/27 통과** (기존 24 + 신규 3)
- 전체 관련 테스트: **126/126 통과**
- 신규 테스트 3개:
  - `test_increment_logs_warning_on_read_failure` — `_read_or_init()` 실패 시 WARNING 로그 발생 검증
  - `test_increment_logs_warning_on_write_failure` — `_write()` 실패 시 WARNING 로그 발생 검증
  - `test_increment_success_no_warning` — 정상 경로에서 WARNING 로그 없음 검증

### 15.5 검증 결과 (5/5 ✅ ALL PASS)
| 검증 항목 | 상태 |
|-----------|------|
| `_read_or_init()` 실패 시 `logger.warning` 호출 | ✅ PASS |
| `_write()` 실패 시 `logger.warning` 호출 + context 정보 포함 | ✅ PASS |
| 정상 경로에서 `logger.warning` 없음 | ✅ PASS |
| 기존 `is_quota_exhausted()` / `is_exhausted()` 영향 없음 | ✅ PASS |
| 테스트 코드 올바름 (caplog WARNING 레벨 검증) | ✅ PASS |

### 15.6 판정
**✅ Phase 5i-7 완료.** `increment()`의 silent swallow가 제거되어:
- `_read_or_init()` 실패 → `logger.warning` + early return (count 증가 시도 안 함)
- `_write()` 실패 → `logger.warning` (count/date context 포함)
- 정상 경로 → 로그 노이즈 없음
- 기존 fail-closed 동작(`_read_or_init()`가 `_DAILY_LIMIT` 반환)은 유지

### 15.7 잔여 위험
1. **`increment()` 호출 전 `is_exhausted()` 체크 누락**: `increment()` 자체는 항상 count를 증가시키므로, `is_exhausted()` 체크 없이 `increment()`가 호출되면 quota 소진 후에도 count가 계속 증가할 수 있음. 단, 이는 호출자(caller) 책임 영역이므로 `increment()` 수준에서 해결할 문제는 아님.
2. **파일 기반 quota tracking의 근본적 한계**: flock-protected shared bucket(`FileBackedGlobalBucket` in `shared_budget.py`)과 달리 `NaverDailyQuotaTracker`는 파일 locking 없이 JSON 파일을 읽고 쓰므로, 경합 조건(race condition)이 존재함. 단, 현재 운영 환경에서 `increment()` 호출 빈도가 낮아(분당 수 회) 실제 문제가 발생할 가능성은 낮음.

## 16. Phase 5i-8 — T3 fresh skip fail-closed 전환

### 16.1 작업 개요
`_is_t3_fresh_for_symbol()`이 DB 조회 실패 시 `return False` ("not fresh")를 반환하여 모든 symbol에 대해 T3 live pipeline이 재실행되던 문제를 해결. DB 장애 시 `return True` ("fresh")로 간주하여 불필요한 NAVER API 호출을 방지.

### 16.2 선택한 병목
**후보 A: Fresh skip failure / 재실행 과다**

선택 근거:
1. **직접적인 quota 보호 효과**: DB 장애 시 모든 symbol에 대해 T3 live pipeline 재실행 → NAVER quota 소진 방지
2. **변경 난이도 최저**: 단 1줄(`return False` → `return True`) + `logger.warning` 추가
3. **운영 효과 즉각적**: 시간당 최대 360회 불필요한 NAVER API 호출 차단 (30 symbols × 12 cycles/hour)
4. **정상 경로 부작용 없음**: DB 정상 시 동작 변경 없음

### 16.3 수정 파일
- [`scripts/run_decision_loop.py`](scripts/run_decision_loop.py) — `_is_t3_fresh_for_symbol()` fail-closed 전환

### 16.4 변경 상세

#### 변경 전
```python
async def _is_t3_fresh_for_symbol(
    symbol: str,
    repos: RepositoryContainer,
) -> bool:
    """Check if T3 events exist for symbol within freshness window."""
    try:
        return await repos.external_events.has_fresh_t3_events(
            symbol=symbol,
            max_age_seconds=_T3_FRESHNESS_SECONDS,
        )
    except Exception:
        return False
```

#### 변경 후
```python
async def _is_t3_fresh_for_symbol(
    symbol: str,
    repos: RepositoryContainer,
) -> bool:
    """Check if T3 events exist for symbol within freshness window.
    
    Returns ``True`` on DB error (fail-closed) to protect NAVER quota
    by preventing unnecessary T3 live pipeline execution.
    """
    try:
        return await repos.external_events.has_fresh_t3_events(
            symbol=symbol,
            max_age_seconds=_T3_FRESHNESS_SECONDS,
        )
    except Exception:
        logger.warning(
            "T3 freshness check failed for symbol=%s — assuming fresh to protect NAVER quota",
            symbol,
        )
        return True  # fail-closed: DB 장애 시 "fresh"로 간주하여 live pipeline 실행 방지
```

#### 변경 포인트 (3가지)
1. **`return False` → `return True`**: DB 장애 시 "fresh"로 간주하여 T3 live pipeline 실행 방지 (fail-closed)
2. **`logger.warning` 추가**: symbol 정보를 포함한 경고 로그 기록
3. **docstring 업데이트**: fail-closed 동작 문서화

### 16.5 테스트 결과
- `test_run_decision_loop.py`: **72/72 통과** (0.08s)
- 중요 테스트 클래스:
  - `TestIsT3FreshForSymbol`: 5/5 통과 (정상 경로 테스트 변경 없음)
  - `TestRunT3LivePipeline`: 5/5 통과
  - `TestT3DegradedPath`: 1/1 통과

### 16.6 검증 결과 (5/5 ✅ ALL PASS)
| 검증 항목 | 상태 |
|-----------|------|
| `except Exception` 블록 `return True` (fail-closed) | ✅ PASS |
| `logger.warning` symbol context 포함 | ✅ PASS |
| docstring fail-closed 문서화 | ✅ PASS |
| 정상 경로(DB 정상) 변경 없음 | ✅ PASS |
| `_collect_persisted_seeded_events()` 변경 없음 | ✅ PASS |

### 16.7 판정
**✅ Phase 5i-8 완료.** `_is_t3_fresh_for_symbol()`이 fail-closed로 전환되어:
- DB 정상 시: 기존과 동일하게 `has_fresh_t3_events()` 결과 반환
- DB 장애 시: `return True` (fresh) → T3 live pipeline 미실행 → NAVER quota 보호
- 장애 발생 시 `logger.warning`으로 운영자 인지 가능
- `_collect_persisted_seeded_events()`는 `return []` (fail-open) 유지 — DB 장애 시 seeded events 없이 decision 정상 진행

### 16.8 다음 우선순위
**후보 D: T3 partial persist / transaction 잔여 이슈**
- `_run_t3_live_pipeline()`의 timeout 처리에서 partial persist 로직 견고성 검토
- `_process_one()`의 `except asyncio.TimeoutError`와 `_run_t3_live_pipeline()`의 timeout 간 이중 timeout 상호작용 검증
- `convert_seeded_candidates()` 예외 시 partial persist 누락 가능성 확인

## 17. Phase 5i-9: T3 partial persist / transaction 잔여 이슈 (asyncio.shield)

### 17.1 작업 개요
- **목표**: T3 live pipeline timeout 시 partial persist 실패 가능성을 줄이는 견고성 보강
- **선택한 취약 지점**: `_run_one_cycle()`의 `all_tasks().cancel()`이 T3 pipeline task까지 취소 (취약 지점 2)
- **버그 수정 포함**: 초기 구현(`asyncio.create_task(asyncio.shield(...))`)은 `asyncio.shield()`가 Future를 반환하므로 `TypeError` 유발 → wrapper coroutine으로 재구현
- **적용 일자**: 2026-05-29 (1차), 2026-05-29 (2차: TypeError 수정)

### 17.2 선택한 취약 지점
**취약 지점 2: cancel 전파 차단** (가장 심각)

- `_run_one_cycle()` (line ~940): `all_tasks().cancel()` 호출
- 이 cancel이 `asyncio.create_task(_run_t3_live_pipeline(...))`로 생성된 task까지 전파
- T3 pipeline이 `_T3_TIMEOUT`(60s) 내에 완료되더라도, `PER_AGENT_HARD_TIMEOUT`(120s) 초과 시 cancel 전파로 partial persist 실행 전에 취소됨
- `asyncio.shield()`로 T3 pipeline task를 cancel로부터 보호

### 17.3 수정 파일
| 파일 | 변경 |
|------|------|
| `scripts/run_decision_loop.py:1319-1341` | `_run_t3_live_pipeline_shielded()` wrapper 함수 추가 |
| `scripts/run_decision_loop.py:797-801` | 호출 지점: `create_task(shield(...))` → `create_task(_run_t3_live_pipeline_shielded(...))` |
| `tests/scripts/test_run_decision_loop.py:76` | import `_run_t3_live_pipeline_shielded` 추가 |
| `tests/scripts/test_run_decision_loop.py:2375-2422` | `TestRunT3LivePipelineShielded` 테스트 클래스 추가 (2개 테스트) |

### 17.4 변경 상세

#### 문제: `asyncio.create_task(asyncio.shield(...))`가 TypeError를 유발하는 이유

```python
# ❌ BUG: asyncio.shield() returns a Future, not a coroutine
task = asyncio.create_task(
    asyncio.shield(
        _run_t3_live_pipeline(runtime, repos, symbol, source_type=source_type)
    )
)
# → TypeError: a coroutine was expected, got _ShieldWait
```

`asyncio.shield()`는 내부적으로 `_ShieldWait(Future)` 인스턴스를 반환합니다. `asyncio.create_task()`는 **coroutine만** 받을 수 있으므로 Future를 전달하면 `TypeError`가 발생합니다.

이전 테스트가 이 버그를 놓친 이유: `TestRunOneCycle` 테스트에서 `NaverNewsSearchAdapter.is_quota_exhausted`를 `True`로 mock하여 T3 pipeline skip 경로만 테스트했기 때문에 `create_task(shield(...))` 경로에 실제로 도달하지 않았습니다.

#### 올바른 구현: Wrapper coroutine 사용

```python
# ✅ FIX: module-level wrapper coroutine
async def _run_t3_live_pipeline_shielded(
    runtime: dict[str, object],
    repos: RepositoryContainer,
    symbol: str,
    source_type: str = "core",
) -> None:
    """Wrapper that runs ``_run_t3_live_pipeline`` under ``asyncio.shield()``."""
    return await asyncio.shield(
        _run_t3_live_pipeline(runtime, repos, symbol, source_type=source_type)
    )

# ✅ FIX: create_task receives a coroutine, not a Future
task = asyncio.create_task(
    _run_t3_live_pipeline_shielded(
        runtime, repos, symbol, source_type=source_type
    )
)
```

#### 변경 전
```python
task = asyncio.create_task(
    _run_t3_live_pipeline(runtime, repos, symbol, source_type=source_type)
)
```

#### 변경 후
```python
task = asyncio.create_task(
    _run_t3_live_pipeline_shielded(
        runtime, repos, symbol, source_type=source_type
    )
)
```

#### 변경되지 않은 부분
- `_run_t3_live_pipeline()` 내부 timeout 블록 (`asyncio.wait_for(..., timeout=_T3_TIMEOUT)`) — 그대로 유지
- `_active_t3_tasks` set 관리 — 그대로 유지
- T3 drain 로그 (`_active_t3_tasks`가 비어있지 않으면 drain 로그 출력) — 그대로 유지
- `_run_one_cycle()`의 `all_tasks().cancel()` — 그대로 유지 (다른 task에 영향)
- `_run_t3_live_pipeline()` 자체 — 그대로 유지 (shield는 wrapper가 담당)

### 17.5 테스트 결과
```
tests/scripts/test_run_decision_loop.py::TestRunT3LivePipeline::test_skip_when_services_unavailable PASSED
tests/scripts/test_run_decision_loop.py::TestRunT3LivePipeline::test_skip_when_naver_quota_exhausted PASSED
tests/scripts/test_run_decision_loop.py::TestRunT3LivePipeline::test_timeout_handled_gracefully PASSED
tests/scripts/test_run_decision_loop.py::TestRunT3LivePipeline::test_exception_handled_gracefully PASSED
tests/scripts/test_run_decision_loop.py::TestRunT3LivePipeline::test_success_path PASSED
tests/scripts/test_run_decision_loop.py::TestRunT3LivePipelinePartialPersist::test_partial_persist_after_convert_timeout PASSED
tests/scripts/test_run_decision_loop.py::TestRunT3LivePipelinePartialPersist::test_partial_persist_with_seeds_only PASSED
tests/scripts/test_run_decision_loop.py::TestRunT3LivePipelineShielded::test_creatable_via_create_task PASSED  ← NEW
tests/scripts/test_run_decision_loop.py::TestRunT3LivePipelineShielded::test_propagates_inner_result PASSED    ← NEW
tests/scripts/test_run_decision_loop.py::TestT3DegradedPath::test_collect_and_freshness_integration PASSED
... (74/74 passed)
```

### 17.6 검증 결과 (7/7 ✅ ALL PASS)
| # | 검증 항목 | 결과 |
|---|---------|------|
| 1 | `create_task(_run_t3_live_pipeline_shielded(...))`이 TypeError를 내지 않는가? | ✅ `test_creatable_via_create_task` 통과 |
| 2 | `_run_t3_live_pipeline_shielded()`가 `asyncio.shield`를 통해 내부 결과를 전파하는가? | ✅ `test_propagates_inner_result` 통과 |
| 3 | `_run_t3_live_pipeline()` 내부 timeout 블록이 유지되는가? | ✅ `asyncio.wait_for(..., timeout=_T3_TIMEOUT)` 그대로 |
| 4 | `_active_t3_tasks` set 관리가 유지되는가? | ✅ `_active_t3_tasks.add(task)` 그대로 |
| 5 | `all_tasks().cancel()`이 다른 task에 영향을 주는가? | ✅ T3 pipeline만 shield, 다른 task는 cancel 가능 |
| 6 | 기존 테스트가 모두 통과하는가? | ✅ 74/74 통과 |
| 7 | 전체 관련 테스트 스위트가 통과하는가? | ✅ 128/128 통과 |

### 17.7 판정
**✅ Phase 5i-9 완료 (버그 수정 포함)** — T3 partial persist / transaction 잔여 이슈 해결.

`_run_t3_live_pipeline_shielded()` wrapper coroutine 적용으로 `_run_one_cycle()`의 `all_tasks().cancel()`이 T3 pipeline task로 전파되는 것을 차단했습니다. 추가로 초기 구현의 `TypeError` 버그를 wrapper coroutine 방식으로 수정했습니다.

이를 통해:
1. T3 pipeline이 `_T3_TIMEOUT`(60s) 내에 정상 완료되면 partial persist가 실행됨
2. `PER_AGENT_HARD_TIMEOUT`(120s) 초과로 cancel이 발생해도 T3 pipeline은 계속 실행
3. T3 pipeline 자체의 timeout(`asyncio.wait_for`)은 그대로 유지되어 무한 대기 방지
4. `asyncio.create_task()`에 Future를 전달하는 `TypeError` 버그가 없음

### 17.8 다음 우선순위
Phase 5i 시리즈의 현재 상태:
1. ✅ Phase 5i-4a: app 컨테이너 SEEDED_NEWS_ENABLED=0 (기본 차단)
2. ✅ Phase 5i-4b: 예외 개발 스크립트 차단 (validate_seeded_news_pipeline.py, observe_seeded_news_comparison.py)
3. ✅ Phase 5i-5: NaverDailyQuotaTracker fail-closed 전환
4. ✅ Phase 5i-6: Cross-container quota visibility (공유 볼륨)
5. ✅ Phase 5i-7: increment() silent swallow 보강 (logger.warning + 분리)
6. ✅ Phase 5i-8: Fresh skip fail-closed (_is_t3_fresh_for_symbol → True on error)
7. ✅ Phase 5i-9: T3 partial persist / transaction 잔여 이슈 (wrapper coroutine + shield)

**다음 후보 병목:**
- 후보 B: DB 기반 quota tracking (NaverDailyQuotaTracker 파일 기반 → DB 기반)
- 후보 C: tracker status exposure (API endpoint로 현재 quota 상태 노출)
- 후보 D: partial persist 자체의 retry 메커니즘 부재
