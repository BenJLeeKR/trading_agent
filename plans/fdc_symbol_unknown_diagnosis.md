# FDC symbol = UNKNOWN 원인 진단

> **해결 완료 ✅** — [`final_decision_composer.py:_build_user_prompt()`](../src/agent_trading/services/ai_agents/final_decision_composer.py:258)에
> Symbol line 추가 완료 (AR과 동일한 events 기반 추출 패턴).
> Phase 2 재실행 결과 `fdc-new-1`의 `raw_symbol`이 `UNKNOWN` → `030200`로 개선됨 (88/88 테스트 통과).

## 1. 전체 경로 추적

### 1.1 데이터 흐름 개요

```
measurement script                    AgentExecutionRequest          _build_user_prompt()          Provider Output        metadata override
                    ─────────────▶                       ───────────▶                   ────────────────▶                       ──────────────▶
                                                                                                                              
  AR: symbol="030200"                 request.context                Symbol: 030200 (events 기반)   symbol:"030200"         symbol=result.symbol
                                       .recent_events                                                                    → "030200" ✅
                                       .events[0].symbol
                                       = "030200"

  FDC: symbol="030200"                request.context                ❌ Symbol line 없음!           symbol:"UNKNOWN"        symbol=result.symbol
                                       .recent_events                                                                    → "UNKNOWN" ❌
                                       .events[0].symbol
                                       = "030200"                     Account ID만 있음
```

### 1.2 경로별 상세 분석

#### 구간 A: Request Assembly (measurement script → AgentExecutionRequest)

[`scripts/ar_fdc_output_measurement.py`](scripts/ar_fdc_output_measurement.py:809-821):

```python
request_with_ei = AgentExecutionRequest(
    decision_context_id=UUID("..."),
    correlation_id=correlation_id,
    context=context,                          # ← AssembledContext(recent_events=events)
    event_interpretation_output=ei_output,
)
request_full = AgentExecutionRequest(
    ...
    context=context,                          # ← 동일
    event_interpretation_output=ei_output,
    ai_risk_output=ar_output,
)
```

- `context`는 [`AssembledContext`](src/agent_trading/services/decision_orchestrator.py:198)로, `recent_events=tuple(events_list)` 포함
- event entity의 `symbol` 필드는 DB 조회 결과 `"030200"`로 정상
- `AgentExecutionRequest` 자체에는 `symbol` 필드가 없음 ([`base.py`](src/agent_trading/services/ai_agents/base.py:56-62))
- **이 구간은 정상** — symbol 정보는 `context.recent_events`를 통해 전달됨

#### 구간 B: FDC _build_user_prompt() — **🔴 누락 지점 확정**

[`final_decision_composer.py:258-265`](src/agent_trading/services/ai_agents/final_decision_composer.py:258-265):

```python
lines: list[str] = [
    f"Correlation ID: {request.correlation_id}",
]

# Symbol / decision context
dc = context.decision_context
if dc:
    lines.append(f"Account ID: {dc.account_id}")
```

**문제**: `# Symbol / decision context`라는 주석이 있지만 **Symbol line이 구현되지 않음**. Account ID만 추가됨.

#### 구간 C: AR _build_user_prompt() — **✅ 정상 (비교 기준)**

[`ai_risk.py:291-302`](src/agent_trading/services/ai_agents/ai_risk.py:291-302):

```python
# Symbol source priority:
#   1. context.recent_events first non-None e.symbol
#   2. Fallback "(not available)"
symbol: str = "(not available)"
if events:
    for e in events:
        if e.symbol:
            symbol = e.symbol
            break
lines.append(f"Symbol: {symbol}")
```

AR은 events의 `symbol` 필드에서 Symbol을 읽어 prompt에 포함시킴 → Provider가 `symbol: "030200"` 반환.

#### 구간 D: Provider Output Parsing

- Provider가 prompt에 Symbol line이 없으면 output의 `symbol` 필드를 채울 방법이 없음
- Deepseek은 `symbol` field가 schema에 `"type": "string"`으로 정의되어 있으므로 기본값 `"UNKNOWN"` 사용

#### 구간 E: Metadata Override (run() → output)

[`final_decision_composer.py:166-174`](src/agent_trading/services/ai_agents/final_decision_composer.py:166-174):

```python
result = FinalDecisionComposerOutput(
    ...
    symbol=result.symbol,     # ← Provider가 반환한 값을 그대로 사용
    ...
)
```

- Provider가 `"UNKNOWN"`을 반환 → override에서도 `"UNKNOWN"` 유지
- `request`나 `context`에서 symbol을 가져와 덮어쓰지 않음

#### 구간 F: AR의 metadata override — 비교

[`ai_risk.py:170-178`](src/agent_trading/services/ai_agents/ai_risk.py:170-178):

```python
result = AIRiskOutput(
    ...
    symbol=result.symbol,     # ← AR도 동일하게 result.symbol 사용
    ...
)
```

AR도 동일한 패턴(`symbol=result.symbol`)이지만, **prompt에 Symbol line이 있었으므로** provider가 정확한 값을 반환함.

---

## 2. 원인 확정

### 2.1 누락 지점: FDC `_build_user_prompt()`에 Symbol line 부재

| 구분 | AR | FDC |
|------|-----|-----|
| Prompt에 Symbol line | ✅ `Symbol: 030200` | ❌ 없음 |
| Provider output symbol | `"030200"` | `"UNKNOWN"` |
| Metadata override 방식 | `symbol=result.symbol` | `symbol=result.symbol` |
| **결과** | **정상** | **UNKNOWN** |

**근거**:
1. FDC prompt 아티팩트 ([`data/ar_fdc_prompts_030200.json`](data/ar_fdc_prompts_030200.json))의 `fdc_*_prompt` 필드에서 `Symbol:` 문자열이 **존재하지 않음**
2. AR prompt에는 `Symbol: 030200`이 존재
3. FDC `_build_user_prompt()` 코드에 Symbol line 생성 로직이 없음
4. `DecisionContextEntity`에는 `symbol` 필드 자체가 없음 ([`entities.py:144-153`](src/agent_trading/domain/entities.py:144))
5. `AgentExecutionRequest`에는 `symbol` 필드가 없음 ([`base.py:56-62`](src/agent_trading/services/ai_agents/base.py:56))
6. events의 `symbol`은 AR과 동일하게 사용 가능하지만, FDC가 이를 활용하지 않음

### 2.2 UNKNOWN이 생기는 정확한 기전

```
FDC _build_user_prompt()
  → Symbol line 없이 prompt 생성
  → Provider가 prompt만 보고 symbol을 알 수 없음
  → JSON schema의 symbol field 기본값 "UNKNOWN" 사용
  → FinalDecisionComposerAgent.run()에서 symbol=result.symbol로 보존
  → Phase 2 _call_fdc()에서 parsed_output.decision_type 추출
  → 최종 output: symbol = "UNKNOWN"
```

---

## 3. 수정 필요 여부 및 제안

### 3.1 수정 판정: **필요**

- FDC prompt에 Symbol이 없다는 것은 downstream agent가 **어떤 symbol에 대해 결정을 내리는지 모른다는 의미**
- 이는 FDC prompt의 정보 불완전성 문제로, 버그에 해당
- AR은 동일한 문제를 해결한 이력이 있음 (provenance propagation 작업에서 Symbol line 추가됨)
- FDC는 당시 작업 범위에서 제외되었거나 누락됨

### 3.2 제안하는 최소 수정

**Option A (권장, 3~5 lines)**: FDC `_build_user_prompt()`에 AR과 동일한 패턴으로 Symbol line 추가

```python
# In FinalDecisionComposerAgent._build_user_prompt(), after Correlation ID line:
# Symbol source priority (same as AIRiskAgent):
#   1. context.recent_events first non-None e.symbol
#   2. Fallback "(not available)"
symbol: str = "(not available)"
if events:
    for e in events:
        if e.symbol:
            symbol = e.symbol
            break
lines.append(f"Symbol: {symbol}")
```

**변경 파일**: [`src/agent_trading/services/ai_agents/final_decision_composer.py`](src/agent_trading/services/ai_agents/final_decision_composer.py) — 1개 파일, ~5 lines 추가

**영향**:
- FDC prompt에 `Symbol: 030200` 라인이 추가됨
- Provider가 올바른 symbol을 output에 포함시킬 수 있음
- 기존 테스트에 영향 없음 (symbol 필드는 string type으로 이미 존재)
- broker submit semantics, admin UI, DB schema 변경 없음
- 기존 FDC output의 `decision_type`, `confidence` 등 핵심 필드와 무관
- **단, prompt 변화로 인해 FDC output의 다른 필드(decision_type 등)가 미세하게 달라질 가능성은 있음** — 이는 의도된 개선(정보 보강)의 자연스러운 결과

**Option B (보류)**: `AgentExecutionRequest`에 `symbol` 필드를 추가하고, orchestrator에서 설정 후, `FinalDecisionComposerAgent.run()`의 metadata override에서 `request.symbol`을 사용

- 더 구조적인 해결책이지만 변경 범위가 큼 (base.py + orchestrator.py + fdc.py)
- `AgentExecutionRequest`는 frozen dataclass로, 변경 시 모든 caller 영향
- Option A로 충분히 해결 가능

---

## 4. production 영향 분석

| 항목 | 영향 |
|------|------|
| FDC output의 `symbol` 필드 | `"UNKNOWN"` → `"030200"`로 개선 |
| FDC output의 다른 필드 (`decision_type`, `confidence` 등) | 미세 변화 가능성 있음 (prompt에 추가 정보) |
| broker submit | 영향 없음 — `symbol` 필드는 submit에 사용되지 않음 |
| `run_orchestrator_once.py` | 영향 없음 |
| logging | `symbol=%s` 로그가 정확해짐 |
| 기존 테스트 | `test_agents.py`의 FDC prompt 테스트에 Symbol line 추가 필요할 수 있음 |

---

## 5. 남은 리스크 1개

**Prompt 변화로 인한 FDC output drift**: Symbol line 추가로 FDC prompt가 변경되면, provider의 output(`decision_type`, `confidence` 등)이 미세하게 달라질 수 있습니다. 이는 현재 exploratory validation에서 관찰된 `fdc-old-1`(`APPROVE`) vs `fdc-new-1`(`HOLD`) 차이와 유사한 효과입니다. 수정 전후의 FDC output 비교를 위해 Phase 2 재실행이 필요할 수 있습니다.

---

## 6. 후속 조치 완료

**FDC `_build_user_prompt()`에 Symbol line 추가 완료** ✅

| 항목 | 상태 |
|------|------|
| Symbol line 추가 ([`final_decision_composer.py:258`](../src/agent_trading/services/ai_agents/final_decision_composer.py:258)) | ✅ 완료 — AR과 동일한 events 기반 패턴 |
| 코드 주석: Symbol source 우선순위 설명 (`AgentExecutionRequest`에 `symbol` 필드 없음) | ✅ 완료 |
| 테스트 3개: symbol 정상 / symbol=None / events=[] | ✅ 통과 (88/88) |
| Phase 2 재실행: FDC NEW `raw_symbol=030200` 확인 | ✅ 확인 |
| OLD-style prompt는 근사 재현 유지 (수정 대상 아님) | ✅ 유지 |

**변경 파일**: [`src/agent_trading/services/ai_agents/final_decision_composer.py`](../src/agent_trading/services/ai_agents/final_decision_composer.py) — 1개 파일
**테스트 파일**: [`tests/services/ai_agents/test_agents.py`](../tests/services/ai_agents/test_agents.py) — 3개 테스트 추가
