# EI Output Contract Phase 2 — Deterministic Minimal Reconstruction

**날짜**: 2026-05-22  
**작성자**: Roo (Architect)  
**상태**: 초안 (리뷰 필요)  

---

## 1. 목적

`detected_only` 경로에서 input [`ExternalEventEntity`](../../src/agent_trading/domain/entities.py:521)들을 최소 구조의 [`InterpretedEvent`](../../src/agent_trading/services/ai_agents/schemas.py:138)로 deterministic하게 복원한다. 이로써:

- `events[]`가 비어 있어 downstream (UI, FDC 등)에서 가독성이 떨어지는 문제 해결
- Exception fallback / self-contradiction guard 경로에서도 최소한의 이벤트 프리뷰 제공
- `is_reconstructed: bool = True`로 LLM 해석과의 구분 명확화

---

## 2. Reconstruction 규칙 (보수적 접근)

| 규칙 | 내용 |
|------|------|
| **R1** | LLM 해석을 날조하지 않는다 — `impact_direction`, `impact_horizon`, `confidence`, `novelty`, `supports_entry`, `supports_exit`, `risk_flags`, `reason_codes`는 기본값 유지 |
| **R2** | 복원은 최소 수준 — headline, published_at, source_name, severity, direction 등 `ExternalEventEntity`에서 deterministic하게 추출 가능한 필드만 채움 |
| **R3** | `is_reconstructed = True`로 구분 가능하게 설정 — LLM이 생성한 event와 반드시 구별 |
| **R4** | `summary_basis`는 `"detected_only"` 유지 — reconstructed event가 있어도 LLM이 해석한 것이 아님 |
| **R5** | summary 문구는 detected_only 컨텍스트에 맞게 작성 — "AI 분석이 완료되지 않았으나, N건의 이벤트가 감지되었습니다" |

---

## 3. ExternalEventEntity → InterpretedEvent 매핑

### 3.1 필드 매핑 테이블

| `InterpretedEvent` 필드 | `ExternalEventEntity` 매핑 | 비고 |
|---|---|---|
| `source_event_id` | `source_event_id or str(event_id)` | source_event_id가 None이면 UUID 문자열 사용 |
| `event_type` | `event_type` | 직접 매핑 |
| `source_name` | `source_name` | 직접 매핑 |
| `source_reliability_tier` | `source_reliability_tier` | 직접 매핑 (기본값 "T3") |
| `stale` | `False` | 고정 (freshness budget 없이 판단 불가) |
| `impact_direction` | `direction` | `ExternalEventEntity.direction` 매핑 |
| `impact_horizon` | `"swing"` (기본값) | **날조 금지** |
| `confidence` | `0.0` (기본값) | **날조 금지** |
| `novelty` | `"medium"` (기본값) | **날조 금지** |
| `supports_entry` | `False` (기본값) | **날조 금지** |
| `supports_exit` | `False` (기본값) | **날조 금지** |
| `risk_flags` | `()` (기본값) | **날조 금지** |
| `reason_codes` | `()` (기본값) | **날조 금지** |
| `summary` | `headline or body_summary or ""` | 최소 preview (LLM 판단 아님) |
| **`is_reconstructed`** (신규) | **`True`** | **신규 필드 — 항상 True** |

### 3.2 `_reconstruct_events()` 함수 설계

```python
def _reconstruct_events(
    recent_events: tuple[ExternalEventEntity, ...],
) -> tuple[InterpretedEvent, ...]:
    """ExternalEventEntity → InterpretedEvent 최소 복원.

    Parameters
    ----------
    recent_events
        원본 입력 이벤트 리스트 (AssembledContext.recent_events).

    Returns
    -------
    tuple[InterpretedEvent, ...]
        is_reconstructed=True로 설정된 InterpretedEvent 튜플.
    """
    reconstructed: list[InterpretedEvent] = []
    for ev in recent_events:
        reconstructed.append(
            InterpretedEvent(
                source_event_id=ev.source_event_id or str(ev.event_id),
                event_type=ev.event_type,
                source_name=ev.source_name,
                source_reliability_tier=ev.source_reliability_tier,
                stale=False,
                impact_direction=ev.direction,
                impact_horizon="swing",       # 기본값 — 날조 금지
                confidence=0.0,               # 기본값 — 날조 금지
                novelty="medium",             # 기본값 — 날조 금지
                supports_entry=False,         # 기본값 — 날조 금지
                supports_exit=False,          # 기본값 — 날조 금지
                risk_flags=(),
                reason_codes=(),
                summary=ev.headline or ev.body_summary or "",
                is_reconstructed=True,        # ★ 신규 필드
            )
        )
    return tuple(reconstructed)
```

### 3.3 매핑 비고

- `published_at`은 `InterpretedEvent`에 필드가 없으므로 매핑하지 않음 (별도 필드 추가 없음)
- `severity` → `InterpretedEvent`에 대응 필드 없음 (기존 스키마 유지)
- `InterpretedEvent.summary`는 LLM interpretation summary가 아닌 단순 headline preview로 사용 → 혼동을 방지하기 위해 `summary`보다는 headline을 그대로 사용
- source_event_id 우선순위: `ExternalEventEntity.source_event_id` (OpenDART receipt number 등) → `str(event_id)` (UUID fallback)

---

## 4. `_finalize_ei_output()` 수정方案

### 4.1 시그니처 변경

```python
def _finalize_ei_output(
    output: EventInterpretationOutput,
    input_event_count: int = 0,
    recent_events: tuple[ExternalEventEntity, ...] = (),    # ★ 신규 파라미터
) -> EventInterpretationOutput:
```

### 4.2 Reconstruction 실행 위치

`_finalize_ei_output()` 내부, `interpreted_count` 계산 직전에 reconstruction 수행:

```python
def _finalize_ei_output(
    output: EventInterpretationOutput,
    input_event_count: int = 0,
    recent_events: tuple[ExternalEventEntity, ...] = (),
) -> EventInterpretationOutput:
    av = output.aggregate_view
    has_events = bool(output.events)
    degraded = av.interpretation_incomplete
    detected = output.detected_event_count
    no_material = av.no_material_events
    reason = av.degraded_reason

    # ── Phase 2: Deterministic minimal reconstruction ──
    # 조건: input_event_count > 0 AND events == () AND (degraded OR exception fallback)
    if input_event_count > 0 and not has_events and recent_events:
        reconstructed = _reconstruct_events(recent_events)
        output = replace(output, events=reconstructed)
        has_events = True   # ← 이후 truth table에서 사용

    # interpreted_event_count는 항상 len(events)와 일치
    interpreted_count = len(output.events)

    # summary_basis 결정 (reconstructed 고려)
    ...
```

### 4.3 호출부 변경

`EventInterpretationAgent.run()` 내 3개 호출부:

1. **정상 경로** (L411):
   ```python
   result = _finalize_ei_output(
       result,
       input_event_count=input_event_count,
       recent_events=request.context.recent_events or (),
   )
   ```

2. **Exception fallback (input > 0)** (L485):
   ```python
   fallback = _finalize_ei_output(
       fallback,
       input_event_count=input_event_count,
       recent_events=request.context.recent_events or (),
   )
   ```

3. **Exception fallback (input == 0)** (L499):
   ```python
   fallback = _finalize_ei_output(
       fallback,
       recent_events=(),   # input 없음 → recent_events도 없음
   )
   ```

---

## 5. Truth Table 영향 분석

### 5.1 현재 Truth Table

| `has_events` | `degraded` | `detected > 0 or input > 0` | `summary_basis` |
|---|---|---|---|
| T | F | — | `"interpreted"` |
| T | T | — | `"interpreted_degraded"` |
| F | — | T | `"detected_only"` |
| F | — | F | `"none"` |

### 5.2 Reconstructed events 고려한 Truth Table

`all_reconstructed` 플래그 도입: `events`가 모두 `is_reconstructed=True`인 경우.

```python
# events가 모두 reconstructed인지 확인
all_reconstructed = (
    has_events
    and all(getattr(e, "is_reconstructed", False) for e in output.events)
)
```

| `has_events` | `all_reconstructed` | `degraded` | `detected > 0 or input > 0` | `summary_basis` |
|---|---|---|---|---|
| T | F | F | — | `"interpreted"` |
| T | F | T | — | `"interpreted_degraded"` |
| T | T | — | — | **`"detected_only"`** (← 변경) |
| F | — | — | T | `"detected_only"` |
| F | — | — | F | `"none"` |

**핵심 변경**: `has_events=True`이지만 `all_reconstructed=True`이면 `"detected_only"`를 반환한다. 이는 LLM이 해석한 event가 하나도 없기 때문.

### 5.3 구현

```python
# summary_basis 결정
all_reconstructed = (
    has_events
    and all(getattr(e, "is_reconstructed", False) for e in output.events)
)

if has_events and not all_reconstructed and not degraded:
    summary_basis = "interpreted"
elif has_events and not all_reconstructed and degraded:
    summary_basis = "interpreted_degraded"
elif has_events and all_reconstructed:
    summary_basis = "detected_only"    # ★ reconstructed만 있으면 detected_only
elif not has_events and (detected > 0 or input_event_count > 0):
    summary_basis = "detected_only"
else:
    summary_basis = "none"
```

---

## 6. Summary 문구 — Detected Only + Reconstructed Events

### 6.1 `_build_summary_text()`에 새로운 Case 추가

현재 [`_build_summary_text()`](../../src/agent_trading/services/ai_agents/event_interpretation.py:47)는 6개 Case를 가짐.  
새로운 **Case 7 — Reconstructed events only** 추가:

```python
# ── Case 7: Reconstructed events only (detected_only + reconstructed) ──
if has_events and not is_degraded and summary_basis == "detected_only":
    event_count_display = len(output.events)
    parts: list[str] = []
    # 이벤트별 preview (headline/summary)
    previews = []
    for ev in output.events[:3]:  # 최대 3건
        if ev.summary:
            preview = ev.summary.split(".")[0] if "." in ev.summary else ev.summary
            if len(preview) > 60:
                preview = preview[:57] + "..."
            previews.append(preview)
    if previews:
        parts.append(", ".join(previews))
    parts.append(f"AI 분석이 완료되지 않았으나, {event_count_display}건의 관련 이벤트가 감지되었습니다")
    return "(" + str(event_count_display) + "건) " + " | ".join(parts)
```

**주의**: `summary_basis` 값을 `_build_summary_text()` 내부에서 알 수 있도록 파라미터 추가 또는 `output.summary_basis` 직접 사용.  
→ 현재 `_build_summary_text()`는 `output` 객체를 받으므로 `output.summary_basis`로 접근 가능 (단, `_finalize_ei_output()`에서 `replace()`로 summary_basis 설정 후 `_build_summary_text()` 호출 순서에 유의).

### 6.2 호출 순서 변경

`_finalize_ei_output()` 내부에서 `summary_basis` 결정을 `_build_summary_text()` 호출 **전**으로 이동:

```python
# 1. reconstruction 수행
# 2. interpreted_event_count 설정
# 3. summary_basis 결정 (reconstructed 고려)
# 4. output = replace(output, interpreted_event_count=..., summary_basis=...)  # summary_basis 먼저 설정
# 5. summary = _build_summary_text(output, ...)  # output.summary_basis 사용 가능
# 6. output = replace(output, summary=summary)  # 최종 summary 설정
```

### 6.3 FDC skip 경로 (변경 불필요)

[`run_agent_subprocess.py:630-647`](../../scripts/run_agent_subprocess.py:630)에서:
- `summary_basis="none"`으로 강제
- `events`는 EI 원본 유지
- FDC skip은 events가 이미 있는 경로이므로 reconstruction 대상이 아님

---

## 7. `InterpretedEvent`에 `is_reconstructed` 필드 추가

### 7.1 스키마 변경

[`InterpretedEvent`](../../src/agent_trading/services/ai_agents/schemas.py:138)에 필드 추가:

```python
@dataclass(slots=True, frozen=True)
class InterpretedEvent:
    # ... 기존 14개 필드 ...
    summary: str = ""

    # ★ Phase 2: Deterministic minimal reconstruction 플래그
    is_reconstructed: bool = False
    """``True`` when this event was deterministically reconstructed
    from raw input (``ExternalEventEntity``) rather than interpreted
    by the LLM.  LLM-interpreted events always have ``False``."""
```

`frozen=True` dataclass이므로 기본값이 `False`인 필드만 추가하면 기존 코드와 100% 호환된다.

### 7.2 `__post_init__` 처리

`InterpretedEvent`는 `frozen=True`이므로 `__post_init__`이 필요하지 않음. 단순 필드 추가로 충분.

---

## 8. 변경 파일 목록 및 상세 변경 사항

### 8.1 [`src/agent_trading/services/ai_agents/schemas.py`](../../src/agent_trading/services/ai_agents/schemas.py)

| 라인 | 변경 내용 |
|------|---------|
| 193-194 | `InterpretedEvent`에 `is_reconstructed: bool = False` 필드 추가 |

### 8.2 [`src/agent_trading/services/ai_agents/event_interpretation.py`](../../src/agent_trading/services/ai_agents/event_interpretation.py)

| 라인 | 변경 내용 |
|------|---------|
| Import | `ExternalEventEntity` import 추가 (`from agent_trading.domain.entities import ExternalEventEntity`) |
| 신규 함수 | `_reconstruct_events(recent_events) → tuple[InterpretedEvent, ...]` |
| 144-196 | `_finalize_ei_output()` 시그니처에 `recent_events` 파라미터 추가 |
| 144-196 | reconstruction 조건 검사 로직 추가 (`input_event_count > 0` AND `not has_events` AND `recent_events`) |
| 144-196 | `all_reconstructed` 플래그 도입 및 truth table 수정 |
| 144-196 | `summary_basis` 결정 → `replace()` 순서 조정 (summary_basis를 먼저 설정) |
| 47-141 | `_build_summary_text()`에 Case 7 (reconstructed only) 추가 |
| 411 | `_finalize_ei_output(result, input_event_count=..., recent_events=...)` |
| 485 | `_finalize_ei_output(fallback, input_event_count=..., recent_events=...)` |
| 499 | `_finalize_ei_output(fallback, recent_events=())` |

### 8.3 [`admin_ui/src/lib/utils.ts`](../../admin_ui/src/lib/utils.ts)

| 라인 | 변경 내용 |
|------|---------|
| 355-370 | `EiInterpretationView`에 `isReconstructed: boolean` 필드 추가 |
| 372-426 | `formatEiOutput()`에서 `events` 배열의 `is_reconstructed` 플래그 읽어 `isReconstructed` 설정 |
| - | `allReconstructed` 헬퍼 로직 추가 (선택적) |

### 8.4 [`admin_ui/src/components/AgentRunDetailPanel.tsx`](../../admin_ui/src/components/AgentRunDetailPanel.tsx)

| 라인 | 변경 내용 |
|------|---------|
| 95-124 | reconstructed event 표시 영역 추가 — 회색 배경, italics, "재구성된 이벤트" 라벨 |
| - | 각 event item에 `(재구성)` 배지 표시 |

### 8.5 변경 불필요 파일

| 파일 | 이유 |
|------|------|
| [`scripts/run_agent_subprocess.py`](../../scripts/run_agent_subprocess.py) | FDC skip은 events가 이미 있는 경로, reconstruction 대상 아님 |
| [`src/agent_trading/domain/entities.py`](../../src/agent_trading/domain/entities.py) | `ExternalEventEntity` 변경 불필요 |
| [`admin_ui/src/types/api.ts`](../../admin_ui/src/types/api.ts) | `isReconstructed`는 TypeScript 타입 선언만으로 충분 (utils.ts에서 처리) |

---

## 9. 데이터 흐름 다이어그램

```mermaid
flowchart TD
    A[EventInterpretationAgent.run] --> B{Exception?}
    B -->|Yes| C[Exception fallback output]
    B -->|No| D[LLM response parsed]
    D --> E{input_event_count > 0<br>AND events == ()?}
    E -->|Yes: self-contradiction| F[degraded=True<br>events=() 유지]
    E -->|No| G[정상 output<br>events=LLM events]
    C --> H{input_event_count > 0?}
    H -->|Yes| I[fallback_av: event_count=input count]
    H -->|No| J[fallback_av: event_count=0]
    I --> K{input_event_count > 0<br>AND events == ()<br>AND degraded?}
    F --> K
    G --> L[_finalize_ei_output: reconstruction bypass]

    K -->|Yes: reconstruction 대상| M[_reconstruct_events]
    M --> N[events = reconstructed<br>is_reconstructed=True]
    K -->|No| O[events 유지]

    N --> P[summary_basis 결정]
    O --> P
    P --> Q{all_reconstructed?}
    Q -->|Yes| R[summary_basis = detected_only]
    Q -->|No| S[기존 truth table]
    R --> T[_build_summary_text: Case 7]
    S --> U[_build_summary_text: 기존 Case 1-6]
    T --> V[return finalized output]
    U --> V
```

---

## 10. 테스트 전략

### 10.1 추가할 테스트 케이스

#### 단위 테스트: `_reconstruct_events()`

| TC | 설명 | 검증 |
|----|------|------|
| TC-1 | 단일 ExternalEventEntity → InterpretedEvent 변환 | 모든 매핑 필드 정확성 확인 |
| TC-2 | 복수 ExternalEventEntity 변환 | 튜플 길이 일치 확인 |
| TC-3 | headline=None, body_summary=None인 경우 | summary = "" 확인 |
| TC-4 | source_event_id=None인 경우 | source_event_id = str(event_id) 확인 |
| TC-5 | 모든 reconstructed event의 is_reconstructed=True | 필드값 확인 |
| TC-6 | impact_direction, impact_horizon 등 기본값 필드 확인 | confidence=0.0, impact_horizon="swing" 등 |

#### 단위 테스트: `_finalize_ei_output()` — Reconstruction 조건

| TC | 설명 | 검증 |
|----|------|------|
| TC-7 | input_event_count>0, events=(), degraded=True → reconstruction 실행 | events 길이 == input_event_count |
| TC-8 | input_event_count=0, events=() → reconstruction 미실행 | events 유지 (()) |
| TC-9 | events!=() (정상) → reconstruction 미실행 | events 유지 |
| TC-10 | input_event_count>0, events!=() (self-contradiction guard에서 events 보존) → reconstruction 미실행 | events 유지 |
| TC-11 | FDC skip 경로 모의 → reconstruction 미실행 | events 유지 |

#### 단위 테스트: Truth Table — Reconstructed events

| TC | 설명 | 검증 |
|----|------|------|
| TC-12 | has_events=True, all_reconstructed=True, degraded=False | summary_basis = "detected_only" |
| TC-13 | has_events=True, all_reconstructed=True, degraded=True | summary_basis = "detected_only" |
| TC-14 | has_events=True, all_reconstructed=False, degraded=False | summary_basis = "interpreted" (기존) |
| TC-15 | has_events=True, all_reconstructed=False, degraded=True | summary_basis = "interpreted_degraded" (기존) |

#### 단위 테스트: Summary — Reconstructed events

| TC | 설명 | 검증 |
|----|------|------|
| TC-16 | reconstructed events 1건 | "AI 분석이 완료되지 않았으나, 1건의 관련 이벤트가 감지되었습니다" 포함 |
| TC-17 | reconstructed events 3건 이상 | preview에 headline truncated 적용 확인 (80자 제한) |
| TC-18 | summary="" (headline도 body_summary도 없음) | preview 생략, event count만 표시 |

#### 통합 테스트: `EventInterpretationAgent.run()` — 전체 경로

| TC | 설명 | 검증 |
|----|------|------|
| TC-19 | Exception fallback + input_event_count>0 | events에 reconstructed event 포함, is_reconstructed=True |
| TC-20 | Self-contradiction guard + input_event_count>0 | events에 reconstructed event 포함 |
| TC-21 | 정상 LLM 응답 (events 있음) | events에 is_reconstructed=False, summary_basis="interpreted" |

#### 프론트엔드 테스트

| TC | 설명 | 검증 |
|----|------|------|
| TC-22 | `formatEiOutput()`에서 `is_reconstructed` 필드 처리 | EiInterpretationView에 isReconstructed 포함 |
| TC-23 | reconstructed event UI 표시 | 회색/italics 스타일 적용 확인 |
| TC-24 | 혼합 (LLM events + reconstructed 없음) | 정상 스타일 유지 |

### 10.2 테스트 파일 위치

- 백엔드 단위 테스트: [`tests/services/ai_agents/test_event_interpretation.py`](../../tests/services/ai_agents/test_event_interpretation.py) (신규 또는 기존 파일)
- 프론트엔드 테스트: [`admin_ui/src/__tests__/utils.test.ts`](../../admin_ui/src/__tests__/utils.test.ts) (기존)

---

## 11. 구현 순서

| 단계 | 파일 | 작업 | 의존성 |
|------|------|------|--------|
| 1 | `schemas.py` | `InterpretedEvent.is_reconstructed` 필드 추가 | 없음 |
| 2 | `event_interpretation.py` | `_reconstruct_events()` 함수 구현 | 1 |
| 3 | `event_interpretation.py` | `_finalize_ei_output()` 수정 (recent_events, reconstruction, truth table) | 2 |
| 4 | `event_interpretation.py` | `_build_summary_text()` Case 7 추가 | 3 |
| 5 | `event_interpretation.py` | `run()` 내 3개 호출부에 recent_events 전달 | 3 |
| 6 | `utils.ts` | `EiInterpretationView` + `formatEiOutput()` 수정 | 1 |
| 7 | `AgentRunDetailPanel.tsx` | reconstructed event UI 표시 | 6 |
| 8 | 테스트 | 모든 테스트 케이스 구현 | 1-7 |

---

## 12. 변경 요약

```diff
--- a/src/agent_trading/services/ai_agents/schemas.py
+++ b/src/agent_trading/services/ai_agents/schemas.py
@@ -190,6 +190,7 @@ class InterpretedEvent:
     reason_codes: tuple[str, ...] = ()
     summary: str = ""
+    is_reconstructed: bool = False

--- a/src/agent_trading/services/ai_agents/event_interpretation.py
+++ b/src/agent_trading/services/ai_agents/event_interpretation.py
@@ -32,6 +33,8 @@ from agent_trading.services.ai_agents.schemas import (
     generate_json_schema,
 )
+from agent_trading.domain.entities import ExternalEventEntity

+# 신규 함수
+def _reconstruct_events(...) -> tuple[InterpretedEvent, ...]:

 def _finalize_ei_output(
     output: EventInterpretationOutput,
     input_event_count: int = 0,
+    recent_events: tuple[ExternalEventEntity, ...] = (),
 ) -> EventInterpretationOutput:
+    # Reconstruction 로직
+    # Truth table 수정 (all_reconstructed 고려)
+    # summary_basis → replace 순서 조정

 def _build_summary_text(...):
+    # Case 7: reconstructed events only
```

---

## 13. 리스크 및 고려사항

| 리스크 | 영향 | 완화 |
|--------|------|------|
| `is_reconstructed` 필드가 LLM JSON 스키마에 노출됨 | LLM이 실수로 True 설정 가능 | 기본값 False, LLM은 이 필드를 알 필요 없음 (JSON schema에서 제외하거나 무시) |
| `_finalize_ei_output()`이 `events`를 변경 | 기존에는 read-only였으나 Phase 2에서 변경 | 조건이 매우 제한적이므로 영향 최소화 (오직 `events==()` AND `input>0` AND `recent_events` 있을 때만) |
| `ExternalEventEntity` import로 인한 순환 참조 | 없음 (domain entities는 low-level, services imports it already) | 확인 완료: `event_interpretation.py`에서 `ExternalEventEntity` import 가능 |
| `summary` 필드가 LLM interpretation summary와 혼동 | `(재구성)` 라벨로 구분 | UI에서 명확히 표시, is_reconstructed로 기계적 구분 가능 |
