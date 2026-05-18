# REDUCE/EXIT sell submit runtime validation report — 2026-05-18

## 1. 검증 목적
FDC의 REDUCE/EXIT 결정이 실제 `order_requests(side='SELL')`로 생성되고 broker까지 submit되는지 실운영 환경에서 검증

## 2. 검증 대상 사례

### 2.1 DB 조회 결과 (최종 — 2026-05-18 15:34 KST 기준)

| 항목 | 결과 |
|------|------|
| 최근 9시간 REDUCE/EXIT + sell trade_decisions | **11건** ✅ — 정상 생성, side='sell' |
| 대응 order_requests (side='SELL') | **0건** ❌ — 단 1건 연결됨 (005830, side='buy') |
| broker_orders (SELL) | **0건** ❌ |
| 000150 reduce (sell) → order_request | **2건 모두 미생성** ❌ |
| 000810 reduce (sell) → order_request | **3건 모두 미생성** ❌ |
| 000880 reduce/exit | 해당 없음 (HOLD/WATCH만 존재) |

### 2.2 차단 지점 상세

#### 차단 A (해결 ✅): SELL override 대소문자 불일치
- **파일**: [`src/agent_trading/services/decision_orchestrator.py:659`](src/agent_trading/services/decision_orchestrator.py:659)
- **원인**: FDC 출력 `side="SELL"` (대문자) vs `OrderSide.SELL.value="sell"` (소문자) 직접 비교 → 항상 False
- **수정**: `fdc_side.lower() == OrderSide.SELL.value`로 정규화
- **관련 테스트**: [`tests/services/test_submit_order_from_decision.py`](tests/services/test_submit_order_from_decision.py) — 대문자 SELL 테스트 2개 추가 (총 8개)
- **실운영 검증**: trade_decisions에 side='sell'이 11건 저장됨 — `_ensure_trade_decision()`의 `_resolve_order_side()` 정규화는 정상 작동 확인

#### 차단 B (해결 중 ⚠️): decision_submit_gate timeout
- **파일**: [`scripts/run_near_real_ops_scheduler.py:761`](scripts/run_near_real_ops_scheduler.py:761)
- **원인 1**: `_DECISION_TIMEOUT = 85` < `PER_AGENT_HARD_TIMEOUT = 90` → scheduler가 subprocess를 항상 먼저 kill
- **수정 1**: 85→95로 증가 (95 > 90 확보)
- **결과 1**: 여전히 timeout (실제 소요 99.05s → 95s 초과)
- **수정 2**: 95→180으로 추가 증가
- **결과 2**: **여전히 timeout** — 184.05s 소요 (180s + 4s asyncio overhead)
- **수정 3**: 180→300으로 증설 (2026-05-18 15:37 KST 적용 + scheduler 재시작 완료)
- **근본 원인**: NAVER API 429 rate limit → seeded news 검색에서 최대 4회 재시도 → 전체 pipeline 지연
  - dry-run 모드에서도 7분 이상 실행 중 (NAVER API 429로 인한 재시도)
  - `PER_AGENT_HARD_TIMEOUT=90`은 `assemble_and_submit()`에만 적용, seeded news 처리는 별도 timeout 없음

#### 차단 C (선행 조건 ❌): KIS mock trading 상/하한가 오류
- 97건 `rejected` 중 다수가 `msg_cd=40270000` (모의투자 상/하한가 오류)
- SELL/BUY 무관한 가격 검증 오류 — side fix과 독립적

### 2.3 추가 발견: subprocess stdout/stderr 로깅 누락
- **파일**: [`scripts/run_near_real_ops_scheduler.py:407-446`](scripts/run_near_real_ops_scheduler.py:407)
- **문제**: timeout 발생 시 `stdout_b, stderr_b = (b"", b"")`로 초기화 → subprocess의 partial 출력이 모두 손실
- **수정**: partial stdout/stderr를 보존하도록 개선 (timeout 후에도 최대 4KB까지 로깅)
- **적용**: 2026-05-18 15:37 KST, scheduler 재시작과 함께 반영

## 3. 코드 수정 요약

| 파일 | 변경 | 영향 |
|------|------|------|
| [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:659) | `fdc_side.lower()` 정규화 (1行) | SELL override 정상화 |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:761) | `_DECISION_TIMEOUT 85→95→180→300` (1行, 3회 수정) | subprocess kill 방지 |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:407-446) | timeout 후 partial stdout/stderr 보존 | 디버깅 가능성 개선 |
| [`tests/services/test_submit_order_from_decision.py`](tests/services/test_submit_order_from_decision.py) | 대문자 SELL 테스트 2개 추가 | 검증 범위 확장 |

## 4. 테스트 검증 결과

```
tests/services/test_submit_order_from_decision.py   8 passed  ✅
tests/services/test_decision_orchestrator.py        37 passed  ✅
tests/api/test_health.py                            13 passed  ✅
```

## 5. 최종 판정: 🔴 미동작 (Not Working)

| 구분 | 상태 |
|------|------|
| FDC REDUCE/EXIT + side=sell 결정 생성 | ✅ 정상 (11건, 최근 9시간) |
| `_ensure_trade_decision()` → DB 저장 | ✅ 정상 (trade_decisions.side='sell') |
| `AIDecisionInputs.side` 전파 | ✅ 정상 (코드 수정 완료) |
| `assemble()` SELL override | ✅ 정상 (코드 수정 완료, 단위 테스트 통과) |
| `build_submit_order_request_from_decision()` | ✅ 정상 (단위 테스트 통과) |
| scheduler `decision_submit_gate` 완료 | ❌ **timeout (선행 차단벽)** — 85→95→180→300으로 증설 중 |
| `order_requests(side='SELL')` 생성 | ❌ **0건** — timeout으로 subprocess 미완료 |
| `broker_orders` SELL submit | ❌ **0건** |

### 판정 근거
1. **SELL override 코드 자체는 정상** — 단위 테스트 8/8 통과, trade_decisions에 side='sell' 저장 확인
2. **실운영 경로 차단** — `decision_submit_gate` timeout이 전체 pipeline을 블로킹
3. **timeout 근본 원인** — NAVER API 429 rate limit으로 인한 seeded news 처리 지연
4. **`_DECISION_TIMEOUT=300` 적용 완료** — scheduler 재시작 완료, 다음 submit gate 사이클에서 재검증 필요
5. **장 마감 후** — 현재 EOD 모드이므로 `decision_submit_gate`는 다음 영업일 장중에만 실행됨

## 6. 남은 Follow-up

### 즉시 조치 필요
1. ✅ **`_DECISION_TIMEOUT 300초` 적용 + scheduler 재시작** — 완료 (15:37 KST)
2. ⏳ **다음 영업일 장중 `decision_submit_gate` 완료 확인** — 300초면 충분할 것으로 예상
3. ⏳ **완료 시**: DB에서 order_requests(side='SELL') 생성 확인 + broker_orders 연결 확인

### 중기 개선 (권장)
4. ❌ **NAVER API rate limit 대책**: 429 응답 시 exponential backoff + fallback 전략 개선
   - 현재 최대 4회 재시도, 각각 1-8초 sleep → 최대 30초 이상 지연 가능
   - seeded news 처리가 `assemble_and_submit()`보다 먼저 실행되므로 전체 pipeline blocking
5. ❌ **seeded news 처리 timeout 도입**: `process_seeds()`에 별도 timeout 적용 필요
   - 현재 `PER_AGENT_HARD_TIMEOUT=90`은 `assemble_and_submit()`에만 적용
   - seeded news 처리는 무제한 대기 → NAVER 429 발생 시 전체 pipeline 지연
6. ❌ **KIS mock trading 가격 오류**: `40270000` 오류는 side와 무관 — 별도 분석 필요
