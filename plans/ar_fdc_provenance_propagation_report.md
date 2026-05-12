# AR/FDC Prompt Provenance 전파 + AR Symbol Line BUG 수정 — 구현 보고

## 1. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| [`src/agent_trading/services/ai_agents/ai_risk.py`](../src/agent_trading/services/ai_agents/ai_risk.py) | 수정 | events section → provenance-rich format, Symbol line bug fix, `datetime` import 추가 |
| [`src/agent_trading/services/ai_agents/final_decision_composer.py`](../src/agent_trading/services/ai_agents/final_decision_composer.py) | 수정 | events section → provenance-rich format, `datetime` import 추가 |
| [`tests/services/ai_agents/test_agents.py`](../tests/services/ai_agents/test_agents.py) | 수정 | `TestAIRiskAgentPrompt` (10 tests) + `TestFinalDecisionComposerAgentPrompt` (6 tests) 추가 |

## 2. 변경 상세

### 2.1 AR events section — provenance-rich format 적용

**변경 위치**: [`ai_risk.py:_build_user_prompt()`](../src/agent_trading/services/ai_agents/ai_risk.py:391)

**BEFORE** (OLD format):
```python
lines.append(f"  - [{e.event_type}] {headline}")
```

**AFTER** (NEW format — EI와 동일한 규칙):
```python
# Provenance tags — same rules as EI
parts: list[str] = []
if e.source_name:
    parts.append(f"[src:{e.source_name}]")
if e.source_reliability_tier:
    parts.append(f"[tier:{e.source_reliability_tier}]")
if e.event_type:
    parts.append(f"[{e.event_type}]")
if e.published_at:
    parts.append(f"[{e.published_at.strftime('%Y-%m-%d')}]")
if e.issuer_code:
    parts.append(f"[issuer:{e.issuer_code}]")
if e.severity and e.severity != "medium":
    parts.append(f"[severity:{e.severity}]")
if e.direction and e.direction not in ("neutral", ""):
    parts.append(f"[{e.direction}]")

# Stale check
stale_mark = ""
if e.ingested_at and (now - e.ingested_at).total_seconds() > 86400:
    stale_mark = " ⚠️STALE"

tagged = " ".join(parts)
body = f" — {summary[:200]}" if summary else ""
lines.append(f"  {tagged}{stale_mark} {headline}{body}")
```

### 2.2 FDC events section — provenance-rich format 적용

**변경 위치**: [`final_decision_composer.py:_build_user_prompt()`](../src/agent_trading/services/ai_agents/final_decision_composer.py:324)

AR과 **완전히 동일한 provenance tag 규칙** 적용 (코드 중복 승인).

### 2.3 AR Symbol line bug fix

**변경 위치**: [`ai_risk.py:_build_user_prompt()`](../src/agent_trading/services/ai_agents/ai_risk.py:291)

**BEFORE** (BUG):
```python
lines.append(f"Symbol: {request.context.decision_context or '(not available)'}")
```
→ `DecisionContextEntity.__repr__()` 노출 또는 `"(not available)"` fallback

**AFTER** (FIX):
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

### 2.4 Import 추가

두 파일 모두 `from datetime import datetime, timezone` 추가 (기존 코드에 `datetime.now(timezone.utc)` 사용).

## 3. Default tag omission 규칙 (EI와 동일)

| 태그 | 생략 조건 |
|------|-----------|
| `[severity:...]` | `severity`가 `None`이거나 `"medium"`일 때 |
| `[positive]` / `[negative]` | `direction`이 `None`이거나 `"neutral"` 또는 `""`일 때 |
| `[issuer:...]` | `issuer_code`가 `None`일 때 |
| `⚠️STALE` | `ingested_at`이 `None`이거나 24h 이내일 때 |
| `[src:...]` | `source_name`이 `None`/empty일 때 |
| `[tier:...]` | `source_reliability_tier`가 `None`/empty일 때 |
| `[date]` | `published_at`이 `None`일 때 |

## 4. Symbol line source 우선순위

1. `request.context.recent_events` 첫 번째 non-None `e.symbol`
2. `"(not available)"` fallback

`AgentExecutionRequest`에 직접 `symbol` 필드가 없으므로 events 기반 추출 사용.

## 5. 테스트 결과

### 5.1 실행 명령

```bash
python3 -m pytest tests/services/ai_agents/test_agents.py -v --tb=short
```

### 5.2 결과: **85 passed** ✅

| 테스트 클래스 | 테스트 수 | 설명 |
|---------------|-----------|------|
| `TestStubEventInterpretationAgent` | 7 | 기존 — 변경 없음 |
| `TestStubAIRiskAgent` | 6 | 기존 — 변경 없음 |
| `TestAIRiskAgent` | 18 | 기존 — 회귀 없음 |
| `TestStubFinalDecisionComposerAgent` | 7 | 기존 — 변경 없음 |
| `TestFinalDecisionComposerAgent` | 9 | 기존 — 회귀 없음 |
| `TestEventInterpretationAgent` | 7 | 기존 — 변경 없음 |
| `TestEventInterpretationAgentPrompt` | 6 | 기존 — 변경 없음 |
| **`TestAIRiskAgentPrompt`** | **10** | **신규** — AR provenance + Symbol line |
| **`TestFinalDecisionComposerAgentPrompt`** | **6** | **신규** — FDC provenance |

### 5.3 신규 테스트 상세

**`TestAIRiskAgentPrompt`** (10 tests):
1. `test_ar_events_all_tags_present` — 모든 provenance tag 포함 확인
2. `test_ar_events_severity_medium_omitted` — severity=medium 생략
3. `test_ar_events_direction_neutral_omitted` — direction=neutral 생략
4. `test_ar_events_fresh_no_stale` — fresh event → ⚠️STALE 미포함
5. `test_ar_events_no_issuer_tag_when_none` — issuer_code=None → [issuer:] 생략
6. `test_ar_events_stale_mark_when_old` — stale event → ⚠️STALE 포함
7. `test_ar_symbol_line_no_repr_leak` — Symbol line에 `DecisionContextEntity` repr 없음
8. `test_ar_symbol_line_fallback_when_no_events` — 빈 events → `"(not available)"`
9. `test_ar_symbol_line_fallback_when_symbol_none` — symbol=None → `"(not available)"`
10. `test_ar_combined_provenance_and_symbol` — provenance tags + Symbol line 공존

**`TestFinalDecisionComposerAgentPrompt`** (6 tests):
1. `test_fdc_events_all_tags_present`
2. `test_fdc_events_severity_medium_omitted`
3. `test_fdc_events_direction_neutral_omitted`
4. `test_fdc_events_fresh_no_stale`
5. `test_fdc_events_no_issuer_tag_when_none`
6. `test_fdc_events_stale_mark_when_old`

## 6. 측정 스크립트 재실행 결과

```bash
python3 scripts/ei_improvement_measurement.py
```

**Exit code: 0** ✅

| 항목 | 030200 | 327260 | 090150 |
|------|--------|--------|--------|
| AR raw provenance gap | ✅ | ✅ | ✅ |
| FDC raw provenance gap | ✅ | ✅ | ✅ |
| AR Symbol line BUG | ❌ not reproduced | ❌ not reproduced | ❌ not reproduced |
| AR Symbol line | `Symbol: 030200` | `Symbol: 327260` | `Symbol: 090150` |
| AR provenance tags (src/tier/issuer) | 4/4/4 | 4/4/4 | 4/4/4 |
| FDC provenance tags (src/tier/issuer) | 4/4/4 | 4/4/4 | 4/4/4 |

## 7. 변경 제약 준수 확인

| 제약 조건 | 상태 |
|-----------|------|
| Query contract 변경 금지 | ✅ — 변경 없음 |
| Migration 금지 | ✅ — 변경 없음 |
| Source adapter 변경 금지 | ✅ — 변경 없음 |
| Output schema 변경 금지 | ✅ — 변경 없음 |
| Provider 호출 경로 변경 금지 | ✅ — 변경 없음 |
| Broker submit semantics 변경 금지 | ✅ — 변경 없음 |
| Admin UI 변경 금지 | ✅ — 변경 없음 |
| DB schema 변경 금지 | ✅ — 변경 없음 |
| Production semantics 변경 금지 | ✅ — prompt format만 변경, output schema 동일 |
| Source adapter 추가 금지 | ✅ — 변경 없음 |

## 8. 남은 리스크

| 리스크 | 심각도 | 설명 |
|--------|--------|------|
| 측정 스크립트 하드코딩된 "남은 리스크" 텍스트 | 낮음 | `scripts/ei_improvement_measurement.py`의 "남은 리스크" 섹션이 이전 상태를 가리킴. 기능적 영향 없음 |
| EI ↔ AR/FDC events format 코드 중복 | 중간 | 3개 파일에 동일한 provenance formatting 로직이 중복. 향후 module-level helper 추출 가능 |
| `AgentExecutionRequest`에 `symbol` 필드 부재 | 낮음 | events 기반 추출로 우회했으나, 명시적 필드가 있으면 더 안전함 |
