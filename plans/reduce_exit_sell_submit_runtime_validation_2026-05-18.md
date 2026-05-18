# REDUCE/EXIT sell submit runtime validation report — 2026-05-18

## 1. 검증 목적
FDC의 REDUCE/EXIT 결정이 실제 `order_requests(side='SELL')`로 생성되고 broker까지 submit되는지 실운영 환경에서 검증

## 2. 검증 대상 사례

### 2.1 DB 조회 결과 (사전 분석)
| 항목 | 결과 |
|------|------|
| 최근 7일 trade_decisions (reduce/sell) | **80건** ✅ — 정상 생성, side='sell' |
| 대응 order_requests (side='SELL') | **0건** ❌ — 모두 side='buy'로 잘못 생성 |
| broker_orders (SELL) | **0건** ❌ |
| 000150 reduce (sell) → order_request | ❌ 미생성 |
| 000810 reduce (sell) → order_request | ❌ 미생성 |
| 000880 reduce/exit | 해당 없음 (reduce/exit 없음) |

### 2.2 차단 지점 상세

#### 차단 A (해결 ✅): SELL override 대소문자 불일치
- **파일**: [`src/agent_trading/services/decision_orchestrator.py:659`](src/agent_trading/services/decision_orchestrator.py:659)
- **원인**: FDC 출력 `side="SELL"` (대문자) vs `OrderSide.SELL.value="sell"` (소문자) 직접 비교 → 항상 False
- **수정**: `fdc_side.lower() == OrderSide.SELL.value`로 정규화
- **관련 PR**: [`tests/services/test_submit_order_from_decision.py`](tests/services/test_submit_order_from_decision.py) — 대문자 SELL 테스트 2개 추가 (총 8개)

#### 차단 B (해결 중 ⚠️): decision_submit_gate timeout
- **파일**: [`scripts/run_near_real_ops_scheduler.py:761`](scripts/run_near_real_ops_scheduler.py:761)
- **원인 1**: `_DECISION_TIMEOUT = 85` < `PER_AGENT_HARD_TIMEOUT = 90` → scheduler가 subprocess를 항상 먼저 kill
- **수정 1**: 85→95로 증가 (95 > 90 확보)
- **결과**: 여전히 timeout (실제 소요 99s → 95s 초과)
- **수정 2**: 95→180으로 추가 증가 (subprocess의 90s hard timeout + NAVER API retry 시간 확보)
- **추가 원인**: NAVER API 429 rate limit → retry로 인한 시간 초과

#### 차단 C (선행 조건 ❌): KIS mock trading 상/하한가 오류
- 97건 `rejected` 중 다수가 `msg_cd=40270000` (모의투자 상/하한가 오류)
- SELL/BUY 무관한 가격 검증 오류 — side fix과 독립적

## 3. 코드 수정 요약

| 파일 | 변경 | 영향 |
|------|------|------|
| [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `fdc_side.lower()` 정규화 (1行) | SELL override 정상화 |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py) | `_DECISION_TIMEOUT 85→180` (1行) | subprocess kill 방지 |
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
| FDC REDUCE/EXIT + side=sell 결정 생성 | ✅ 정상 (80건) |
| `_ensure_trade_decision()` → DB 저장 | ✅ 정상 (trade_decisions.side='sell') |
| `AIDecisionInputs.side` 전파 | ✅ 정상 (코드 수정 완료) |
| `assemble()` SELL override | ✅ 정상 (코드 수정 완료, 단위 테스트 통과) |
| `build_submit_order_request_from_decision()` | ✅ 정상 (단위 테스트 통과) |
| scheduler `decision_submit_gate` 완료 | ❌ **timeout (선행 차단벽)** |
| `order_requests(side='SELL')` 생성 | ❌ **0건** |
| `broker_orders` SELL submit | ❌ **0건** |

## 6. 남은 Follow-up

### 즉시 조치 필요
1. **_DECISION_TIMEOUT 180초 적용 후 scheduler 재시작** → decision_submit_gate가 완료되는지 재확인
2. **완료 시**: DB에서 order_requests(side='SELL') 생성 확인 + broker_orders 연결 확인

### 중기 개선 (권장)
3. **NAVER API rate limit 대책**: 429 응답 시 exponential backoff + fallback 전략 개선
4. **paper_decision_loop timeout 구조 개선**: PER_AGENT_HARD_TIMEOUT(90s)과 scheduler timeout(180s) 간 관계 명확화
5. **subprocess stdout/stderr 로깅**: scheduler 로그에 subprocess 상세 출력 포함되어야 디버깅 용이
6. **KIS mock trading 가격 오류**: `40270000` 오류는 side와 무관 — 별도 분석 필요
