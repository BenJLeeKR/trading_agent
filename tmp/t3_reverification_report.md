# T3 재검증 — 하위 Task 2: Recent 로그/DB 재집계 결과 보고서

> 작성 시각: 2026-05-28 14:29 KST (UTC 05:29)

---

## 1. 로그 파일 분석

### 1.1 `t3_429_fastfail_verify_20260527.log`

- **실행 시각**: 2026-05-27 14:39:40 KST (05:39:40 UTC)
- **모드**: `paper-decision-loop` dry run (submit=False)
- **핵심 발견**:
  - **모든 T3 symbol에서 NAVER 429 발생**: `NAVER 429 fast-fail: query='...' — daily quota likely exhausted`
  - T3 pipeline 20s timeout → `RuntimeError: Transaction not started` during `persist_seeded_events()`
  - `SeededNewsCandidateService` metrics: `seeds=13 queries=26 raw=0 gate+0/gate-0 deduped=0 low_conf=0 cross_sym=0 seed_q_drop=0 retry=0 kept=0`
  - 모든 T3 symbol이 `no candidates after processing`로 skip
  - held_position symbol들은 DB의 `recent_events`로 대체 (T3 pipeline 미실행)

### 1.2 `budget_protection_submit_20260527.log`

- **실행 시각**: 2026-05-27 17:29:14 KST (08:29:14 UTC)
- **모드**: `paper-decision-loop` with submit=True
- **핵심 발견**:
  - 동일한 NAVER 429 패턴
  - **Phase 4c STALE_SNAPSHOT_ACCOUNT**: 모든 주문이 stale snapshot guard에 의해 BLOCKED
  - **Partial persist on timeout**: 5개 symbol (000210, 000670, 000720, 000880, 001040)에서 각 40건씩 partial persist 성공
  - `EventInterpretationAgent` JSONDecodeError (symbol 000210, input_events=283)
  - `Sell guard BLOCKED`: symbol 000670, REDUCE decision but position=0

### 1.3 `test_freshness_20260528.log`

- pytest 실행 결과: **58 passed** in 24.16s
- `test_freshness.py`: 7 tests passed
- `test_kis_snapshot_sync.py`: 51 tests passed

---

## 2. Plan 문서 분석

### 2.1 `t3_async_restoration_2026-05-27.md`

- **목적**: T3 pipeline을 동기 `await` → `asyncio.create_task()` (fire-and-forget)로 전환
- **2-Cycle 검증 결과** (2026-05-27 12:59 UTC):
  - T3 live pipeline timeout (20s): 78/78 (100%) ❌
  - Fresh skip: 0/78 (0%) ❌
  - Wall clock: 830.8s ❌ (300s cadence 초과)
  - NAVER 429: 236회 ⚠️
- **제안 변경**:
  - A. `_run_one_cycle()`: `await` → `create_task()` (fire-and-forget)
  - B. `_run_loop()`: Cycle 종료 시 T3 Task Drain
  - C. held_position T3 Skip 복원
  - D. Freshness 기준: `published_at` → `COALESCE(created_at, ingested_at)` 복원
- **기대 효과**: Wall clock 830.8s → ~400-500s (~50% 감소)

### 2.2 `t3_execution_policy_redesign_2026-05-27.md`

- **목적**: Freshness 기준 변경 (Alternative A) + Partial persist (Alternative B)
- **선정**: Alternative A + Alternative B (C, D rejected)
- **`_T3_FRESHNESS_SECONDS = 7200`** (2h) 복원
- **3단계 Partial persist**: Timeout 시 수집된 candidates를 DB에 저장
- **리스크**: NULL published_at, partial persist 품질 저하, 2h news gap

---

## 3. DB 재집계 결과

### 3.1 external_events 일별 분포 (최근 7일)

| KST 날짜 | T1 | T2 | T3 |
|----------|----|----|----|
| 2026-05-28 | 560 | 40,120 | **0** |
| 2026-05-27 | 443 | 10,840 | **180** |

- **T3 이벤트는 5/27이 마지막**이며, 5/28에는 단 1건도 없음
- T1/T2는 정상적으로 계속 적재 중

### 3.2 T3 freshness 상태

- **총 T3 이벤트**: 180건 (39개 symbol)
- **마지막 T3 이벤트**: 2026-05-27 02:58:37 UTC (= 11:58 KST)
- **5/28 T3 이벤트**: **0건** ❌
- **5/26 T3 이벤트**: 1건 (symbol 000030, 2026-05-26 23:50 UTC)
- **published_at NULL 비율**: 0% (모든 T3 이벤트에 published_at 존재)

### 3.3 T3 symbol별 이벤트 수 (5/27)

| Symbol | 건수 | 비고 |
|--------|------|------|
| 005935 | 19 | 삼성전자우 |
| 005930 | 15 | 삼성전자 |
| 005385, 005380 | 각 8 | |
| 006260, 006360, 000660, 000670 | 각 7 | |
| 004020 | 6 | |
| 000150, 005830, 004800 | 각 5 | |
| ... | 3-4 | 대부분의 symbol |
| 003670, 000100 | 각 2 | |

### 3.4 T3 이벤트가 없는 symbol

- **T3 이벤트가 없는 symbol**: 300+개 (external_events 테이블에 존재하는 대부분의 symbol)
- T3 이벤트가 있는 symbol은 **39개**에 불과

### 3.5 trade_decisions source_type별 분포

| KST 날짜 | core | held_position | market_overlay |
|----------|------|---------------|----------------|
| 2026-05-28 | 1,249 | 474 | 0 |
| 2026-05-27 | 1,931 | 596 | 3 |
| 2026-05-26 | 1,082 | 226 | 225 |

- Decision loop는 정상적으로 실행 중 (core + held_position)
- market_overlay는 5/27부터 거의 중단

---

## 4. "T3 이벤트 적재 중단" 근본 원인 진단

### 4.1 직접 원인: NAVER API 일일 할당량 소진

- NAVER News Search API는 **일일 25,000 쿼리** 제한
- T3 pipeline이 각 symbol마다 2회씩 NAVER API 호출 (query + dedup check)
- 78개 symbol × 2회 = 156회/cycle, 여러 cycle 반복으로 할당량 조기 소진
- 5/27 이후 모든 NAVER API 호출이 **429 (Too Many Requests)** 반환

### 4.2 2차 원인: T3 pipeline timeout 시 persist 실패

- `_T3_TIMEOUT = 20s`로 설정
- NAVER 429 상황에서도 20s 동안 대기 후 timeout
- Timeout 발생 시 `persist_seeded_events()`가 **transaction context 없이** 호출됨
- `RuntimeError: Transaction not started. Use 'async with'.` → DB에 이벤트 저장 실패
- budget_protection_submit 로그에서는 일부 symbol에서 partial persist 성공 (40건씩)

### 4.3 3차 원인: 동기 T3 pipeline이 Decision Path Blocking

- T3 pipeline이 동기(`await`)로 실행되어 decision path를 20s씩 blocking
- Wall clock 830.8s로 300s cadence 초과
- `asyncio.create_task()` (fire-and-forget)로 전환하면 wall clock ~50% 감소 예상

### 4.4 4차 원인: Freshness 기준이 `created_at`으로 설정

- 현재 freshness 기준: `created_at` (DB INSERT 시각)
- `_T3_FRESHNESS_SECONDS = 600s` (10분)
- NAVER 429로 T3 이벤트가 전혀 없으면 `has_fresh_t3_events()`가 항상 `False`
- `published_at` 기준으로 변경하면 Cycle 2에서 freshness skip 가능

### 4.5 종합 타임라인

| 시각 (KST) | 이벤트 |
|------------|--------|
| 5/26 ~23:50 | 마지막 T3 이벤트 persist (symbol 000030, 1건) |
| 5/27 01:33-02:58 | 5/27 T3 이벤트 179건 persist (39개 symbol) |
| 5/27 02:58 | **마지막 T3 이벤트** (symbol 000660, 02:58:37 UTC) |
| 5/27 14:39 | t3_429_fastfail_verify dry run: 모든 T3 429, timeout, persist 실패 |
| 5/27 17:29 | budget_protection_submit: 모든 T3 429, 일부 partial persist 성공 |
| 5/28 00:00~ | **T3 이벤트 0건** — 적재 완전 중단 |

### 4.6 현재 상태 요약

| 지표 | 값 | 상태 |
|------|-----|------|
| 마지막 T3 이벤트 | 5/27 11:58 KST | ❌ 26시간 이상 경과 |
| 5/28 T3 이벤트 | 0건 | ❌ |
| T1/T2 적재 | 정상 | ✅ |
| Decision loop 실행 | 정상 | ✅ |
| NAVER API 상태 | 429 (할당량 소진) | ❌ |
| Freshness skip 가능 | 불가 (DB에 T3 이벤트 없음) | ❌ |
| Partial persist | 일부 성공 (timeout 시) | ⚠️ |
| Transaction error | persist_seeded_events()에서 발생 | ❌ |

### 4.7 권장 조치

1. **즉시**: `_T3_FRESHNESS_SECONDS`를 7200s(2h)로 증가 (plan 문서 참조)
2. **단기**: T3 pipeline을 `asyncio.create_task()` fire-and-forget으로 전환
3. **단기**: Timeout 시 partial persist 로직 구현 (transaction context 보장)
4. **중기**: NAVER API 할당량 모니터링 및 쿼리 최적화
5. **중기**: Freshness 기준을 `published_at`으로 변경하여 Cycle 2 skip 가능하게 함
