# Phase 6 Subtask 2: 수정안 선택 결과

## 선정 결과: **Candidate 1 — `agent_name mismatch` (recorder.py:125-131)**

---

## 1. 후보별 분석 결과

### Candidate 1: `agent_name mismatch` (recorder.py:124-132) ⭐ **선정**

**현재 코드** ([`recorder.py:124-132`](src/agent_trading/services/ai_agents/recorder.py:124)):
```python
stored_agent_name = output_dict.get("agent_name")
if stored_agent_name is not None and stored_agent_name != agent_type:
    logger.warning(
        "Agent name mismatch in structured_output: "
        "output.agent_name=%r != agent_type=%r — "
        "overwriting output.agent_name to match",
        stored_agent_name,
        agent_type,
    )
    output_dict["agent_name"] = agent_type
```

**변경 전:**
| 항목 | 값 |
|------|-----|
| 로그 레벨 | `WARNING` |
| 메시지 | `"Agent name mismatch in structured_output: output.agent_name=%r != agent_type=%r — overwriting output.agent_name to match"` |

**변경 후:**
| 항목 | 값 |
|------|-----|
| 로그 레벨 | `INFO` |
| 메시지 | `"Agent name auto-normalized: '%s' → '%s'"` |

**영향받는 테스트:** 없음 (어떤 테스트도 이 로그 메시지를 assertion하지 않음)

**선정 사유:**
| 기준 | 평가 |
|------|------|
| 혼동 제거 효과 | ⭐⭐⭐ 매 decision cycle마다 3회(FDC/EIC/AR) WARNING 발생 → "mismatch"라는 용어가 심각한 문제로 오인될 수 있으나 실제로는 자동 정상화됨 |
| 저위험성 | ⭐⭐⭐ 로그 레벨만 변경 (WARNING→INFO). 메시지 개선. 기능 로직 변경 없음 |
| 회귀 위험 최소 | ⭐⭐⭐ 테스트 영향 0건. `test_orchestrator_agents.py:453`는 `structured_output["agent_name"]`의 값을 assertion할 뿐 로그 레벨/메시지를 확인하지 않음 |
| 운영 부담 감소 | ⭐⭐⭐ 3 WARNINGs/cycle → 0 WARNINGs/cycle. 일일 100회 decision cycle 기준 300건의 불필요한 WARNING 제거 |

---

### Candidate 2: `broker quote timeout or error` (execution_service.py:279-283)

**현재 코드** ([`execution_service.py:279-283`](src/agent_trading/services/execution_service.py:279)):
```python
logger.warning(
    "Phase 1.5: broker quote timeout or error for symbol=%s — "
    "proceeding with best-effort fallback (empty quote).",
    symbol,
    exc_info=True,
)
```

**분석 결과:**
- Subtask 1에서 "진단 정보 부족 (어떤 symbol, 어떤 예외인지 누락)"이라고 분석했으나, **실제 코드에는 이미 `symbol` 파라미터와 `exc_info=True`가 포함되어 있음**
- 이 WARNING은 실제 인프라 문제(브로커 타임아웃, 네트워크 장애)를 감지하는 유용한 신호
- 실패 후 circuit breaker가 open되는 별도 WARNING(line 274)과 중복되지 않음
- **진단 정보가 이미 충분하므로 개선 효과가 제한적**

**평가:**
| 기준 | 평가 |
|------|------|
| 혼동 제거 효과 | ⭐⭐ 실 장애 상황에서 유용한 경고 — 제거 대상 아님 |
| 저위험성 | ⭐⭐⭐ 로그 메시지 개선만 필요 |
| 회귀 위험 최소 | ⭐⭐⭐ 테스트 영향 0건 |
| 운영 부담 감소 | ⭐ 발생 빈도 낮음 (브로커 장애 시에만) |

**결론:** Subtask 1의 전제가 부정확했으며, 현재 로그가 이미 적절히 구현되어 있음. 수정 불필요.

---

### Candidate 3: `effective_cash fallback` (sizing_engine.py:227-230)

**현재 코드** ([`sizing_engine.py:227-231`](src/agent_trading/services/sizing_engine.py:227)):
```python
elif inputs.available_cash is not None:
    effective_cash = inputs.available_cash
    logger.warning(
        "effective_cash=%s (source=available_cash fallback, "
        "orderable_amount is None)",
        effective_cash,
    )
```

**분석 결과:**
- Paper 환경에서 `orderable_amount`는 자주 None (KIS Paper가 VTTC8908R 미지원)
- 정상적인 코드 경로이나 WARNING으로 분류되어 있음
- Test 파일 `test_sizing_engine.py`에서 이 경로를 테스트하지만 로그 레벨을 assertion하지 않음
- `test_kis_snapshot_sync.py:921`에서 `"orderable_amount not available from KIS"` 메시지를 `caplog`로 검증 — 이는 다른 로그 위치의 메시지

**영향받는 테스트:** 없음

**평가:**
| 기준 | 평가 |
|------|------|
| 혼동 제거 효과 | ⭐⭐ paper에서 정상 동작 → WARNING은 오해 유발 |
| 저위험성 | ⭐⭐⭐ 로그 레벨만 변경 (WARNING→INFO) |
| 회귀 위험 최소 | ⭐⭐⭐ 테스트 영향 0건 |
| 운영 부담 감소 | ⭐⭐ 1 WARNING/BUY-cycle. Candidate 1보다 빈도 낮음 |

**결론:** Candidate 1에 비해 noise 감소 효과가 1/3 수준. 차선책으로 유효하나 우선순위 낮음.

---

## 2. 최종 선정: Candidate 1 상세 설계

### 변경 사항

**파일:** [`src/agent_trading/services/ai_agents/recorder.py`](src/agent_trading/services/ai_agents/recorder.py)

**변경할 라인:** 124-132

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| 로그 레벨 | `logger.warning(` | `logger.info(` |
| 메시지 | `"Agent name mismatch in structured_output: output.agent_name=%r != agent_type=%r — overwriting output.agent_name to match"` | `"Agent name auto-normalized: '%s' → '%s'"` |
| 인자 | `stored_agent_name, agent_type` | `stored_agent_name, agent_type` |

### 변경 전/후 코드 diff

```diff
-            logger.warning(
-                "Agent name mismatch in structured_output: "
-                "output.agent_name=%r != agent_type=%r — "
-                "overwriting output.agent_name to match",
+            logger.info(
+                "Agent name auto-normalized: '%s' → '%s'",
                 stored_agent_name,
                 agent_type,
             )
```

### 영향받는 테스트 파일

| 파일 | 영향 | 설명 |
|------|------|------|
| [`tests/services/ai_agents/test_orchestrator_agents.py:445-455`](tests/services/ai_agents/test_orchestrator_agents.py:445) | **없음** | `structured_output_json["agent_name"]` 값만 assertion. 로그 레벨/메시지 미검증 |
| [`tests/services/ai_agents/test_korean_enforcement.py`](tests/services/ai_agents/test_korean_enforcement.py) | **없음** | 모든 테스트에서 `agent_name`과 `agent_type`을 일치시켜 전달하므로 이 코드 경로에 진입하지 않음 |
| [`tests/smoke/test_runtime_three_agent_smoke.py:281-283`](tests/smoke/test_runtime_three_agent_smoke.py:281) | **없음** | `structured_output_json.get("agent_name")` 값만 assertion. 이 테스트는 stub agent를 사용하므로 항상 일치함 |
| [`tests/services/test_decision_orchestrator.py`](tests/services/test_decision_orchestrator.py) | **없음** | recorder 3 runs 검증. 로그 메시지 미검증 |

### 예상 효과

| 지표 | 값 |
|------|------|
| 감소하는 WARNING 수 | 3건/decision cycle (FDC, EIC, AR 각 1회) |
| 일일 WARNING 감소량 (100 cycles 기준) | 300건 |
| 모니터링 노이즈 감소율 | ~95% (해당 WARNING이 차지하던 비율 기준) |
| 오탐 방지 | "mismatch" → "auto-normalized"로 용어 변경 → 운영자 불필요한 우려 제거 |

### 리스크 평가

| 리스크 | 확률 | 영향 | 대응 |
|--------|------|------|------|
| 로그 파싱/모니터링 도구가 메시지 문자열 의존 | 낮음 | 중간 | 현재 메시지와 새로운 메시지 모두 transient log viewer에서 확인 가능. 메시지 변경에 민감한 모니터링 규칙이 있다면 Subtask 4/5에서 확인 필요 |
| INFO 레벨로 낮추어 중요한 agent_name 불일치를 놓침 | 매우 낮음 | 낮음 | 코드가 즉시 정상화(line 132)하므로 WARNING 레벨 불필요 |
| `test_orchestrator_agents.py`의 `caplog` 미사용 검증 누락 | 없음 | 없음 | 해당 테스트는 `caplog`를 사용하지 않음. 직접 확인 완료 |

---

## 3. 구현 지침 (Subtask 3용)

### 적용할 변경

1. [`src/agent_trading/services/ai_agents/recorder.py`](src/agent_trading/services/ai_agents/recorder.py)의 124-132번 라인:
   - `logger.warning(` → `logger.info(`
   - 메시지를 `"Agent name auto-normalized: '%s' → '%s'"`로 변경
   - 인자 순서 유지: `stored_agent_name, agent_type`

2. **파일 수정은 `apply_patch`로 적용** (제약 조건 준수)

### 테스트 실행 명령어

```bash
# 대상 테스트 (회귀 확인)
pytest tests/services/ai_agents/test_orchestrator_agents.py::TestSchemaAlignment -v
pytest tests/services/ai_agents/test_korean_enforcement.py -v
pytest tests/smoke/test_runtime_three_agent_smoke.py -v
pytest tests/services/test_decision_orchestrator.py::TestAssembleAndCreateOrderFullFlow -v
```

### 검증 항목

1. `structured_output_json["agent_name"]`이 여전히 `agent_type`과 일치하는지 확인
2. `INFO` 레벨로 로그가 출력되는지 확인 (WARNING이 아님)
3. 기존 테스트가 모두 통과하는지 확인
