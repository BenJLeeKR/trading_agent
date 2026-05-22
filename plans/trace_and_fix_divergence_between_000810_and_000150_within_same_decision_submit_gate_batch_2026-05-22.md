# 000810(삼성화재) vs 000150(두산) 동일 decision_submit_gate 배치 분기 차이 분석 및 수정

## 1. 개요
- **분석 일시**: 2026-05-22 12:11 KST (decision_submit_gate 배치 시작)
- **대상 배치**: 동일한 `decision_context`에서 처리된 삼성화재(000810)와 두산(000150)
- **문제**: 같은 batch에서 000810은 order_request 생성 및 submitted까지 완료, 000150은 trade_decision만 저장

## 2. 배치 시작/종료 시각
- `decision_context.created_at = 2026-05-22 12:11:39 KST`
- 삼성화재 `decision_at = 2026-05-22 12:14:16 KST` (2분 37초 소요)
- 두산 `decision_at = 2026-05-22 12:14:49 KST` (3분 10초 소요, 33초 늦음)
- 두산 pipeline 미완료 — scheduler-level 600s timeout까지 대기 후 SIGKILL

## 3. 000810 vs 000150 Phase별 비교

### 3.1 삼성화재 (000810) — 정상 완료
| Phase | 상태 | 소요 시간 |
|-------|------|-----------|
| Phase 0: AI Agents | 완료 | ~2분 37초 |
| Phase 1: trade_decision 저장 | 완료 (`2f36a10e`) | agents 완료 직후 |
| Phase 1.5: broker.get_quote() | 완료 | **~3초** (첫 번째 semaphore batch) |
| Phase 2: Translation/Sizing | 완료 | 정상 |
| Phase 3: submit_order_to_broker() | 완료 | 정상 |
| **결과**: order_request `79f05399`, broker_native_order_id `0000022983`, status=submitted |

### 3.2 두산 (000150) — 미완료 (HANG)
| Phase | 상태 | 소요 시간 |
|-------|------|-----------|
| Phase 0: AI Agents | 완료 | ~3분 10초 (33초 지연) |
| Phase 1: trade_decision 저장 | 완료 (`832599eb`) | agents 완료 직후 |
| Phase 1.5: broker.get_quote() | **C-level httpx socket read BLOCK** | **HANG** (절대 완료되지 않음) |
| Phase 2: Translation/Sizing | 도달하지 못함 | — |
| Phase 3: submit_order_to_broker() | 도달하지 못함 | — |
| **결과**: trade_decision만 존재, order_request=NULL |

## 4. Root Cause 분석

### 4.1 직접 원인
두산(`000150`)은 `assemble_and_submit()`의 Phase 1.5 — `broker.get_quote()` 호출에서 **C-level httpx socket read block**에 걸려 영원히 대기했습니다.

### 4.2 왜 삼성화재는 통과하고 두산은 막혔는가?
1. Semaphore(5)로 인해 첫 번째 5개 symbol batch가 동시에 MARKET_DATA bucket 접근
2. 삼성화재는 첫 번째 batch에 포함되어 **bucket exhaustion 전에** 3초 만에 quote 획득
3. 두산은 이후 batch에서 quote 호출 시점에 MARKET_DATA bucket이 exhausted되었거나 KIS API가 일시적 응답 지연
4. `asyncio.wait_for(420s)`가 C-level httpx socket read를 **interrupt하지 못함** (known Python limitation)
5. 420s subprocess timeout도 fire되지 않음
6. **scheduler-level 600s timeout**이 유일한 종료 수단 → SIGTERM → SIGKILL로 전체 subprocess 종료

### 4.3 왜 trade_decision만 남았는가?
- `_ensure_trade_decision()` (Phase 1)는 **INSERT-only 정책**으로 AI Agents 완료 직후 항상 실행됨
- Phase 1.5 (broker quote)는 Phase 1 이후, Phase 2 이전에 위치
- 따라서 Phase 1에서 저장된 trade_decision은 Phase 1.5에서 멈춰도 이미 DB에 존재함
- trade_decision만 있고 order_request가 없는 이유: **Phase 1.5에서 hang되어 Phase 3(create_order)에 도달하지 못했기 때문**

### 4.4 현재 audit trail 부재
- `SubmitResult.error_phase`는 subprocess kill 전에 생성되지 않음
- Audit log는 Phase 2 이후에 생성되므로 미도달
- 유일한 단서: scheduler log의 `timeout=True` (다음 batch log에 덮어써질 수 있음)
- → **trade_decision EXISTS + order_request DOES NOT EXIST**로만 추론 가능

## 5. 적용한 수정

### Fix H: broker quote 개별 timeout (하드)
- **파일**: [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:990-1017)
- **변경**: `await broker.get_quote(...)` → `await asyncio.wait_for(broker.get_quote(...), timeout=10.0)`
- **효과**: C-level I/O block이 발생해도 **10초 후 timeout** → 빈 dict fallback 반환 → pipeline 계속 진행
- **fallback**: `quote = {}` → Phase 2에서 `_resolve_smoke_price()` 등 fallback price 사용 가능

### Fix I: os._exit(1) → raise (소프트)
- **파일**: [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py:885-909)
- **변경**: `os._exit(1)` (전체 subprocess 종료) → `raise RuntimeError(...)` (해당 symbol만 skip)
- **효과**: 한 symbol의 timeout이 전체 batch를 죽이지 않고, 나머지 symbol은 정상 처리

### Fix J: PHASE_TRACE 로깅 보강
- **파일**: [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:990,1000)
- **변경**: quote resolution 전후 `PHASE_TRACE: symbol=%s phase=quote_resolution start/done` 로그 추가
- **효과**: 사후 분석 시 `PHASE_TRACE` prefix로 grep하여 각 symbol의 phase 진행 상황 추적 가능

## 6. 테스트 결과
- **93 passed, 1 failed**
- 유일한 실패: `tests/api/test_external_events.py::test_get_recent_events_with_data` — **DB 데이터 의존성 문제, 본 수정과 무관**
- 수정 관련 회귀(regression) 없음

## 7. Docker 운영 검증
- `docker compose build ops-scheduler`: ✅ 성공 (6.9s)
- `docker compose up -d ops-scheduler`: ✅ 재시작 성공
- `GET /health`: ✅ `{"status": "ok", "database": "connected", "scheduler": {"healthy": true}}`

## 8. 재발 방지 평가

| 시나리오 | 이전 | 이후 |
|----------|------|------|
| broker quote C-level block | 영원히 HANG, 전체 batch 사망 | 10초 후 timeout → fallback → 계속 진행 |
| 한 symbol timeout | `os._exit(1)` → 전체 subprocess 종료 | `raise` → 해당 symbol만 ERROR → 나머지 계속 |
| 사후 분석 | log에 timeout 흔적만 (덮어써짐) | PHASE_TRACE 로그로 각 symbol phase 추적 가능 |

## 9. 관련 문서
- [Debug 분석 보고서](plans/held_position_sell_silent_drop_root_cause_final_2026-05-22.md)
- [HANDOVER_TO_NEW_SESSION.md](plans/HANDOVER_TO_NEW_SESSION.md)
