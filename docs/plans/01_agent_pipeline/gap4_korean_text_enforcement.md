# AI Agent Comment/Rationale 저장 한국어 강제

## 목표
AI Agent(Event Interpretation / AI Risk / Final Decision Composer)의 서술형 텍스트 필드가 PostgreSQL에 저장될 때 반드시 한국어가 되도록 이중 방어(Dual Defense)를 적용한다.

## 서술형 텍스트 필드 인벤토리

### 1. AI Agent 출력 스키마 (`src/agent_trading/services/ai_agents/schemas.py`)

| # | 스키마 | 필드 | 타입 | 설명 | 저장 경로 |
|---|--------|------|------|------|-----------|
| 1 | `EventInterpretationOutput` → `InterpretedEvent.summary` | `str` | 이벤트 해석 요약 (Human-readable) | → `structured_output_json` → `agent_runs` |
| 2 | `EventInterpretationOutput` → `AggregateEventView.opposing_evidence` | `tuple[str]` | 전체 bias에 반대되는 증거 리스트 | → `structured_output_json` → `agent_runs` |
| 3 | `AIRiskOutput.risk_opinion` | `str` | 리스크 의견 ("allow"/"reduce"/"reject"/"review") | → `structured_output_json` → `agent_runs` |
| 4 | `AIRiskOutput.summary` | `str` | 리스크 평가 요약 (Human-readable) | → `structured_output_json` → `agent_runs` |
| 5 | `AIRiskOutput.opposing_evidence` | `tuple[str]` | 리스크 의견에 반대되는 증거 리스트 | → `structured_output_json` → `agent_runs` |
| 6 | `FinalDecisionComposerOutput.summary` | `str` | 최종 결정 요약 (Human-readable) | → `structured_output_json` → `agent_runs` + `rationale_summary` → `trade_decisions` |
| 7 | `FinalDecisionComposerOutput.opposing_evidence` | `tuple[str]` | 최종 결정에 반대되는 증거 리스트 | → `structured_output_json` → `agent_runs` + `opposing_evidence` → `trade_decisions` |

### 2. DB 엔티티 (`src/agent_trading/domain/entities.py`)

| # | 엔티티 | 필드 | 타입 | 설명 | 비고 |
|---|--------|------|------|------|------|
| 1 | `AgentRunEntity` | `structured_output_json` | `dict[str, object]` | 전체 에이전트 출력 (위 7개 필드 포함) | JSONB 컨테이너 |
| 2 | `TradeDecisionEntity` | `rationale_summary` | `str \| None` | FDC summary의 사본 | line 1200 |
| 3 | `TradeDecisionEntity` | `opposing_evidence` | `dict[str, object]` | FDC opposing_evidence → `{"items": [...]}` | lines 1192-1196 |
| 4 | `TradeDecisionEntity` | `decision_json` | `dict[str, object]` | 결정 컨텍스트 JSON (risk_opinion 포함) | lines 1201-1214 |

### 3. 한국어 강제 대상 vs 면제

**한국어로 저장되어야 하는 필드:**
- `InterpretedEvent.summary`
- `AggregateEventView.opposing_evidence` (각 문자열)
- `AIRiskOutput.summary`
- `AIRiskOutput.opposing_evidence` (각 문자열)
- `AIRiskOutput.risk_opinion` (가능한 한국어; "allow"/"reduce"/"reject"/"review"는 backend에서 enum 처리)
- `FinalDecisionComposerOutput.summary`
- `FinalDecisionComposerOutput.opposing_evidence` (각 문자열)
- `TradeDecisionEntity.rationale_summary`
- `TradeDecisionEntity.opposing_evidence["items"]` (각 문자열)

**면제 (그대로 유지):**
- `reason_codes` — machine-readable 코드
- `risk_flags` — categorical flags
- `decision_type` — enum ("APPROVE"/"REJECT"/"HOLD"/etc.)
- `side`, `entry_style`, `time_horizon` — categorical enums
- `agent_name`, `schema_version` — metadata
- `decision_context_id`, `symbol`, `issuer_code` — identifiers

## 설계: Dual Defense

### Layer 1: Prompt 수준 (Agent Prompt에 한국어 지시 추가)

**변경 대상:** 세 Agent의 `_build_system_prompt()` 메서드
- `EventInterpretationAgent._build_system_prompt()` (event_interpretation.py:200)
- `AIRiskAgent._build_system_prompt()` (ai_risk.py:212)
- `FinalDecisionComposerAgent._build_system_prompt()` (final_decision_composer.py:216)

**변경 내용:** 각 system prompt에 아래 문장 추가
```
"All human-readable narrative fields (summary, opposing_evidence, risk_opinion) MUST be written in Korean. "
"Machine-readable fields (reason_codes, decision_type, side, etc.) MUST remain in English."
```

### Layer 2: Backend Validation/Normalization

**2a. Korean 텍스트 검증/정규화 유틸리티 추가**
- 위치: 새 파일 `src/agent_trading/services/ai_agents/korean_normalizer.py`
- 함수: `validate_or_normalize_korean(text: str) -> str`
  - 한글이 포함되어 있으면 → 그대로 반환 (이미 한국어)
  - 한글이 전혀 없으면 → `"[ko: {text}]` 또는 `"${text}"` (강제 한국어 마킹)
  - 실제로는 간단한 유니코드 범위 체크: `\uAC00-\uD7AF` (한글 음절), `\u1100-\u11FF` (자모), `\u3130-\u318F` (호환 자모)

**2b. Recorder 정규화 (`recorder.py`의 `record()` 메서드)**
- `structured_output_json`이 기록되기 전, 서술형 필드를 순회하며 `validate_or_normalize_korean()` 적용
- 타겟 키 경로:
  - `["summary"]` — EI/AR/FDC 모두
  - `["opposing_evidence"]` — 배열 각 요소
  - `["risk_opinion"]` — AR 전용

**2c. TradeDecisionEntity 저장 전 정규화 (`_ensure_trade_decision()`)**
- `rationale_summary` 할당 전에 `validate_or_normalize_korean()` 적용
- `opposing_evidence["items"]` 각 요소에 `validate_or_normalize_korean()` 적용
- `decision_json` 내 서술형 값들에 적용

### 3. 변경 제한 사항
- Admin UI 변경 금지 (기존 API 응답 스키마 유지)
- Broker submit semantics 변경 금지
- Hard guardrail / reconciliation 경계 변경 금지
- 기존 주문 실행 의미 변경 금지

## 변경 파일 목록

### 수정 파일

| # | 파일 | 변경 내용 |
|---|------|-----------|
| 1 | `src/agent_trading/services/ai_agents/event_interpretation.py` | `_build_system_prompt()`에 한국어 지시 추가 |
| 2 | `src/agent_trading/services/ai_agents/ai_risk.py` | `_build_system_prompt()`에 한국어 지시 추가 |
| 3 | `src/agent_trading/services/ai_agents/final_decision_composer.py` | `_build_system_prompt()`에 한국어 지시 추가 |
| 4 | `src/agent_trading/services/ai_agents/recorder.py` | `record()`에서 `structured_output_json` 서술형 필드 한국어 정규화 |
| 5 | `src/agent_trading/services/decision_orchestrator.py` | `_ensure_trade_decision()`에서 `rationale_summary`, `opposing_evidence` 한국어 정규화 |

### 신규 파일

| # | 파일 | 내용 |
|---|------|------|
| 1 | `src/agent_trading/services/ai_agents/korean_normalizer.py` | `validate_or_normalize_korean()` 유틸리티 함수 |

### 테스트 파일

| # | 파일 | 내용 |
|---|------|------|
| 1 | `tests/services/ai_agents/test_korean_normalizer.py` | `validate_or_normalize_korean()` 단위 테스트 |
| 2 | `tests/services/ai_agents/test_korean_enforcement.py` | Recorder/Orchestrator 통합 테스트 |

## 테스트 시나리오

1. **한국어 텍스트는 그대로 통과** — `summary="시장 모멘텀 둔화로 진입 보류"` → 정규화 후 동일
2. **영어 텍스트는 한국어로 마킹** — `summary="Market momentum slowing"` → `"[ko: Market momentum slowing]"` 또는 유사 처리
3. **혼합 텍스트도 통과** — `summary="매수 신호 strong buy signal detected"` → 한글이 포함되어 있으므로 통과
4. **빈 문자열/None은 그대로** — `summary=""` 또는 `summary=None` → 변경 없음
5. **opposing_evidence 배열의 각 요소** — 각 문자열 개별 검증
6. **Recorder 정규화** — `record()` 호출 후 저장된 `structured_output_json`의 서술형 필드가 한국어인지 검증
7. **TradeDecisionEntity 정규화** — `_ensure_trade_decision()` 호출 후 저장된 `rationale_summary`가 한국어인지 검증

## 실행 순서 (TODO)

1. [`korean_normalizer.py`](src/agent_trading/services/ai_agents/korean_normalizer.py) 신규 생성 — `validate_or_normalize_korean()` 함수
2. 세 Agent의 `_build_system_prompt()`에 한국어 지시 추가
3. [`recorder.py`](src/agent_trading/services/ai_agents/recorder.py)의 `record()`에 한국어 정규화 적용
4. [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py)의 `_ensure_trade_decision()`에 한국어 정규화 적용
5. 단위 테스트 생성 (`test_korean_normalizer.py`)
6. 통합 테스트 생성 (`test_korean_enforcement.py`)
7. [`[BACKLOG] backlog.md`](plans/[BACKLOG]%20backlog.md) 업데이트
