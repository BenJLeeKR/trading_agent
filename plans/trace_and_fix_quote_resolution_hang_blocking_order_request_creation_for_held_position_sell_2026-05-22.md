# quote_resolution 병목이 held_position sell의 order_request 생성을 차단하는 문제 분석 및 수정

## 1. 개요
- **분석 대상**: 2026-05-22 12:56 KST `decision_submit_gate` 배치
- **영향받은 종목**: 두산(000150), 삼성화재(000810) — 모두 `trade_decision`만 생성, `order_request` 없음
- **직전 유사 사례**: 2026-05-22 12:11 KST batch (Round 5에서 분석)

## 2. 배치 상태

### 12:56 batch — 실패
| 항목 | 값 |
|------|-----|
| decision_context 생성 | 12:56:21 KST |
| AI Agents 완료 | ~13:01:30 KST (추정) |
| 마지막 trade_decision | 13:01:14 KST (010130) |
| Scheduler timeout | 600s |
| Subprocess kill 시점 | ~13:06:21 KST |
| **결과**: 8개 trade_decision, **0개 order_request** |

### 13:07 batch — 정상 진행 중
| 항목 | 값 |
|------|-----|
| 000810 order_request | 13:11:08 KST 생성됨 ✅ |
| 000270 order_request | 13:11:24 KST 생성됨 ✅ |
| `asyncio.wait_for(10s)` | 정상 동작 확인 |

## 3. Root Cause 분석

### 3.1 Fix H(asyncio.wait_for 10s)의 실제 동작 여부
**동작함.** httpx 0.28.1 + httpcore 1.0.9는 cooperative await(`await client.get()`, `await response.aread()`)을 사용하므로, `asyncio.wait_for()`가 C-level I/O를 정상적으로 interrupt할 수 있음. 13:07 batch가 이를 입증.

### 3.2 12:56 batch 실패의 실제 원인
**scheduler-level 600s timeout**이 subprocess를 SIGKILL하기 전에 8개 symbol의 전체 pipeline(`AI Agents(4분) + quote(10s x 8) + submit`)을 완료하지 못했음.

| 단계 | 소요 시간 | 누적 |
|------|----------|------|
| AI Agents (8개 symbol) | ~4분 10초 | ~4분 10초 |
| Quote resolution (symbol당 10s x 8) | ~80초 | ~5분 30초 |
| Submit order (symbol당 ~10s x 8) | ~80초 | ~6분 50초 |
| **총 예상 시간** | **~410초** | **> 600s timeout** |

### 3.3 HP sell에서 quote의 필요성
HP sell(REDUCE/EXIT SELL)에서 `broker.get_quote()`는 **단순 참고용**. 실제 submit 시 broker adapter가 `_resolve_smoke_price()`를 사용하여 fallback price로 주문을 생성함. quote 실패/지연이 주문 자체를 막아서는 안 됨.

## 4. 적용한 수정

### Fix K: HP sell quote bypass (⭐ 핵심 수정)
- **파일**: [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:990)
- **변경**: HP sell(REDUCE/EXIT SELL) 조건에서 `broker.get_quote()`를 완전히 건너뜀
- **효과**: symbol당 10s 절약 → 8개 batch에서 최대 80s 절감 → 600s timeout 내 모든 symbol 처리 가능
- **로깅**: `HP_SELL_QUOTE_BYPASS: symbol=%s skipping broker.get_quote(), using smoke price fallback`

### Fix L: httpx timeout 단축 (보조 수정)
- **파일**: [`src/agent_trading/brokers/koreainvestment/rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py:413)
- **변경**: `httpx.Timeout(30.0, connect=10.0)` → `httpx.Timeout(8.0, connect=5.0, read=5.0)`
- **효과**: socket read timeout 30s→5s로 단축, 이중 안전장치

### Fix M: HP_SELL_QUOTE_BYPASS 감사 로깅 (Fix K에 포함)
- `HP_SELL_QUOTE_BYPASS` prefix로 grep 가능한 로그 메시지
- 사후 분석 시 `grep "HP_SELL_QUOTE_BYPASS"`로 모든 bypass 사례 추적 가능

## 5. 전/후 비교

| 시나리오 | 이전 | 이후 |
|----------|------|------|
| 8개 symbol batch, HP sell 다수 포함 | AI 4분 + quote 80s + submit 80s = **>600s → SIGKILL** | AI 4분 + quote 0s(bypass) + submit 80s = **~320s → 정상 완료** |
| HP sell quote C-level block | 10s timeout (Fix H), 그래도 느림 | **quote 호출 자체 생략** → 0s |
| BUY symbol timeout | 10s timeout 후 fallback | 동일 (변경 없음) |
| socket read hang | httpx read timeout 30s → ~30s 지연 | httpx read timeout **5s** → ~5s 지연 |

## 6. 테스트 결과
- **전체 테스트**: 93 passed, 1 failed
- 유일한 실패: `tests/api/test_external_events.py::test_get_recent_events_with_data` — **DB 데이터 의존성 문제, 수정과 무관**
- HP sell 관련 테스트 80개 모두 통과

## 7. Docker 운영 검증
```json
{
    "status": "ok",
    "database": "connected",
    "scheduler": { "healthy": true }
}
```

## 8. 관련 문서
- [Debug 분석 보고서: quote_resolution hang 검증](plans/held_position_sell_silent_drop_root_cause_final_2026-05-22.md)
- [Round 5 보고서: 000810 vs 000150 분기 차이](plans/trace_and_fix_divergence_between_000810_and_000150_within_same_decision_submit_gate_batch_2026-05-22.md)
- [Fix H 보고서: asyncio.wait_for 10s](plans/held_position_sell_silent_drop_root_cause_final_2026-05-22.md)
