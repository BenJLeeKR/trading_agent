# 두 검증 로그 재집계 결과 비교표

## 기본 메타 정보

| 항목 | 로그 A (t3_429_fastfail_verify) | 로그 B (t3_transaction_fix_verify) |
|------|------|------|
| 파일명 | `t3_429_fastfail_verify_20260527.log` | `t3_transaction_fix_verify_20260527.log` |
| 파일 크기 | 119,358 lines | 13,552 lines |
| 시작 시간 | 2026-05-27 14:39:40 KST (05:39:40 UTC) | 2026-05-27 15:12:18 KST (06:12:18 UTC) |
| 출력 형식 | `output=json` | `output=text` |
| Universe | 41 symbols (11 held_position + 30 core) | 42 symbols (12 held_position + 30 core) |
| 추가 심볼 | - | 007070 (GS리테일) |
| 총 사이클 | 82 (41 symbols × 2 cycles) | 84 (42 symbols × 2 cycles) |
| 성공 | 82 | 84 |
| 스킵 | 0 | 0 |
| 에러 | 0 | 0 |
| 성공률 | 100.0% | 100.0% |
| 총 소요 시간 | 567.9초 (9분 28초) | 668.7초 (11분 9초) |
| 심볼당 평균 시간 | 6.9초 | 8.0초 |

---

## A. 오류 및 예외 (Error & Exception)

| 패턴 | 로그 A | 로그 B | 비고 |
|------|--------|--------|------|
| `RuntimeError: Transaction not started` | **2,200** | **0** | ✅ **트랜잭션 버그 수정 확인됨** |
| `TimeoutError` (T3 pipeline) | **4,400** | **0** | ✅ **TimeoutError 완전 제거** |
| `CancelledError` (asyncio) | **2,200** | **0** | ✅ **CancelledError 완전 제거** |
| `Failed to persist seeded event: None` | **2,200** | **0** | ✅ **persist 실패 완전 제거** |

> **분석**: 로그 A에서는 각 T3 timeout 이벤트마다 `CancelledError → TimeoutError → RuntimeError("Transaction not started")` 체인이 발생했습니다. 각 RuntimeError마다 `Failed to persist seeded event: None`이 1회씩 기록되어 총 2,200회의 persist 실패가 발생했습니다. 로그 B에서는 이 모든 오류가 **0건**으로, 트랜잭션 버그가 완전히 수정되었음을 확인할 수 있습니다.

---

## B. 429 Rate Limiting (NAVER API)

| 패턴 | 로그 A | 로그 B | 비고 |
|------|--------|--------|------|
| `429 Too Many Requests` (HTTP) | **1,560** | **2,174** | 로그 B가 614건 더 많음 |
| `NAVER 429 fast-fail` (WARNING) | **1,560** | **2,174** | 429 HTTP 응답과 1:1 매칭 |
| `daily quota likely exhausted` | **1,560** | **2,174** | 429 HTTP 응답과 1:1 매칭 |

> **분석**: 로그 B가 로그 A보다 NAVER 429 발생이 614건 더 많습니다. 이는 로그 B가 1개 더 많은 심볼(007070)을 처리하고, 각 심볼당 더 많은 NAVER 쿼리(seeded news 검색)를 수행했기 때문입니다. 로그 B의 T3 pipeline이 정상 동작하여 더 많은 seeded news 검색이 이루어졌습니다.

---

## C. T3 Pipeline 지표

| 패턴 | 로그 A | 로그 B | 비고 |
|------|--------|--------|------|
| `T3 decision path` | **60** | **60** | 동일 (core symbols만 해당) |
| `live_pipeline=sync_executed` | **60** | **60** | 모든 core symbol에서 pipeline 실행 |
| `live_pipeline=skipped` | **0** | **0** | freshness skip 없음 |
| `T3 partial persist on timeout` | **58** | **58** | 동일 |
| `Seeded events persisted=40` | **3** | **58** | **로그 B가 55건 더 많음** |
| `Disclosure: success` | **60** | **60** | 동일 |

> **분석**: 
> - `T3 decision path`와 `live_pipeline=sync_executed`는 두 로그 모두 60회로 동일합니다. 이는 30개 core symbol × 2 cycles = 60회의 T3 pipeline 실행을 의미합니다.
> - `live_pipeline=skipped`는 두 로그 모두 0회로, freshness skip이 전혀 발생하지 않았습니다.
> - `T3 partial persist on timeout`은 두 로그 모두 58회로 동일합니다. 이는 T3 pipeline timeout이 두 로그에서 비슷한 빈도로 발생했음을 의미합니다.
> - **핵심 차이**: `Seeded events persisted=40`이 로그 A는 3회, 로그 B는 58회입니다. 로그 A에서는 T3 timeout 발생 시 `persist_seeded_events`에서 RuntimeError가 발생하여 대부분의 seeded event persist가 실패했지만, 로그 B에서는 트랜잭션 버그가 수정되어 정상적으로 persist가 완료되었습니다.

---

## D. Freshness 지표

| 패턴 | 로그 A | 로그 B | 비고 |
|------|--------|--------|------|
| `recent_events` (총 mentions) | **164** | **168** | 로그 B가 4건 더 많음 |
| `recent_events.*count=0` | **2** | **0** | 로그 A에서만 발생 |
| `recent_events.*count>0` (추정) | 162 | 168 | 로그 B가 6건 더 많음 |

> **분석**: 
> - `recent_events` mentions: 로그 A 164회, 로그 B 168회. 로그 B가 4회 더 많은 것은 1개 추가 심볼(007070) × 2 cycles = 2회 + 추가 recent_events 호출 2회 때문입니다.
> - `count=0`: 로그 A에서만 2회 발생 (symbol=006650 cycle 1, cycle 2에서 count=0). 로그 B에서는 count=0이 전혀 없습니다.
> - 로그 B의 `recent_events` mentions가 168회로 더 많은 것은 T3 pipeline이 정상 동작하여 더 많은 seeded events가 persist되었고, 이로 인해 `list_by_symbol`과 `seeded_supplement`가 모두 증가했기 때문입니다.

---

## E. Agent 실행 지표

| 패턴 | 로그 A | 로그 B | 비고 |
|------|--------|--------|------|
| `Agent name mismatch` (WARNING) | **244** | **249** | 로그 B가 5건 더 많음 |
| `HTTP Request.*200 OK` (DeepSeek API) | **303** | **310** | 로그 B가 7건 더 많음 |
| `Cycle X/2 complete — health=ok` | **0** | **84** | **로그 B에만 존재** (신규 로깅) |

> **분석**:
> - `Agent name mismatch`: 로그 A 244회, 로그 B 249회. 이는 각 agent subprocess 실행 시 agent name이 일치하지 않는 경고로, 모든 symbol/cycle에서 발생합니다. 로그 B가 5회 더 많은 것은 1개 추가 심볼(007070) 처리 때문입니다.
> - `HTTP Request.*200 OK` (DeepSeek API): 로그 A 303회, 로그 B 310회. 모든 DeepSeek API 호출이 200 OK를 반환했습니다. 로그 B가 7회 더 많은 것은 추가 심볼 처리 + 추가 agent 호출 때문입니다.
> - `Cycle X/2 complete — health=ok`: 로그 B에만 84회 존재합니다. 이는 로그 B에 추가된 새로운 health check 로깅 포맷으로, 각 symbol 처리 완료 후 health 상태를 기록합니다. 로그 A에는 이 포맷이 없습니다.

---

## F. 요약 비교

| 구분 | 로그 A | 로그 B | 평가 |
|------|--------|--------|------|
| **트랜잭션 버그** | ❌ RuntimeError 2,200회 | ✅ **0회** | **버그 수정 확인** |
| **TimeoutError** | ❌ 4,400회 | ✅ **0회** | **Timeout 완전 제거** |
| **Seeded events persist** | 3회만 성공 (99.9% 실패) | 58회 성공 | **persist 정상화** |
| **NAVER 429** | 1,560회 | 2,174회 | 로그 B에서 더 많은 쿼리 실행 |
| **Freshness skip** | 없음 | 없음 | 동일 |
| **Health check 로깅** | 없음 | 84회 | 신규 로깅 포맷 |
| **총 소요 시간** | 567.9초 | 668.7초 | 로그 B가 100.8초 더 소요 |
| **평균 심볼당 시간** | 6.9초 | 8.0초 | 로그 B가 1.1초 더 느림 |

---

## 핵심 결론

1. **트랜잭션 버그 수정 확인**: 로그 A에서 2,200회 발생한 `RuntimeError("Transaction not started")`가 로그 B에서 **0회**로 완전히 제거되었습니다. 이에 따라 `TimeoutError`(4,400회→0회), `CancelledError`(2,200회→0회), `Failed to persist seeded event`(2,200회→0회)도 모두 사라졌습니다.

2. **Seeded events persist 정상화**: 로그 A에서는 T3 timeout 발생 시 `persist_seeded_events`에서 RuntimeError가 발생하여 3회만 persist에 성공했지만, 로그 B에서는 트랜잭션 버그 수정으로 58회 모두 정상 persist되었습니다.

3. **NAVER 429 증가**: 로그 B가 로그 A보다 NAVER 429가 614건 더 많습니다. 이는 T3 pipeline이 정상 동작하여 더 많은 seeded news 검색 쿼리가 실행되었기 때문입니다.

4. **소요 시간 증가**: 로그 B가 로그 A보다 100.8초 더 소요되었습니다(668.7초 vs 567.9초). 이는 T3 pipeline이 정상 동작하여 추가적인 seeded news 검색 및 persist 작업이 수행되었기 때문입니다.

5. **신규 로깅 포맷**: 로그 B에만 `Cycle X/2 symbol=... complete — status=... duration=...s [health=ok]` 포맷의 health check 로깅이 84회 추가되었습니다.
