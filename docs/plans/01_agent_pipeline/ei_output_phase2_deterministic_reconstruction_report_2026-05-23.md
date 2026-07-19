# EI Output Contract Phase 2 — Deterministic Minimal Reconstruction 보고서

**날짜**: 2026-05-23
**작업자**: Orchestrator → Ask → Architect → Code 위임

## 1. 작업 개요

- **목적**: `detected_only` 경로에서 input recent events를 최소 구조의 `InterpretedEvent`로 deterministic하게 복원
- **범위**: `aggregate_view.event_count` alias 전환은 제외 (Phase 3으로 deferred)
- **설계 문서**: [`plans/ei_output_phase2_deterministic_reconstruction.md`](plans/ei_output_phase2_deterministic_reconstruction.md)

## 2. 수정 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| [`schemas.py`](src/agent_trading/services/ai_agents/schemas.py:194) | `InterpretedEvent`에 `is_reconstructed: bool = False` 필드 추가 |
| [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py) | `_reconstruct_events()` 신규 함수, `_finalize_ei_output()` 수정, `_build_summary_text()` Case 7 추가, `run()` 3개 경로에 `recent_events` 전달 |
| [`utils.ts`](admin_ui/src/lib/utils.ts:371) | `formatEiOutput()`에 `isReconstructed` 필드 추가 |
| [`AgentRunDetailPanel.tsx`](admin_ui/src/components/AgentRunDetailPanel.tsx:95) | Reconstructed event 회색/italics + `(재구성됨)` 배지 표시 |
| [`test_event_interpretation.py`](tests/services/ai_agents/test_event_interpretation.py:458) | `TestReconstruction` 클래스 (14개 신규 테스트) |
| [`utils.test.ts`](admin_ui/src/__tests__/utils.test.ts:507) | `formatEiOutput.isReconstructed` 3개 신규 테스트 |

## 3. Reconstruction 규칙

| 규칙 | 내용 |
|------|------|
| **R1** | LLM 해석을 날조하지 않음 — `impact_direction`, `impact_horizon`, `confidence`, `novelty`, `supports_entry`, `supports_exit`, `risk_flags`, `reason_codes`는 기본값 유지 |
| **R2** | 복원은 최소 수준 — `headline`, `published_at`, `source_name`, `severity`, `direction` 등 `ExternalEventEntity`에서 deterministic하게 추출 가능한 필드만 채움 |
| **R3** | `is_reconstructed = True`로 구분 가능하게 설정 |
| **R4** | `summary_basis`는 `"detected_only"` 유지 |
| **R5** | summary 문구는 detected_only 컨텍스트에 맞게 작성 — `"AI 분석이 완료되지 않았으나, N건의 관련 이벤트가 감지되었습니다"` |

### 필드 매핑

| `InterpretedEvent` 필드 | `ExternalEventEntity` 매핑 | 비고 |
|---|---|---|
| `source_event_id` | `source_event_id or str(event_id)` | source_event_id가 None이면 UUID 문자열 사용 |
| `event_type` | `event_type` | 직접 매핑 |
| `source_name` | `source_name` | 직접 매핑 |
| `source_reliability_tier` | `source_reliability_tier` | 직접 매핑 |
| `stale` | `False` | 고정 |
| `impact_direction` | `direction` | 직접 매핑 |
| `impact_horizon` | `"swing"` (기본값) | 날조 금지 |
| `confidence` | `0.0` (기본값) | 날조 금지 |
| `novelty` | `"medium"` (기본값) | 날조 금지 |
| `supports_entry` | `False` (기본값) | 날조 금지 |
| `supports_exit` | `False` (기본값) | 날조 금지 |
| `risk_flags` | `()` (기본값) | 날조 금지 |
| `reason_codes` | `()` (기본값) | 날조 금지 |
| `summary` | `headline or body_summary or ""` | 최소 preview |
| **`is_reconstructed`** (신규) | **`True`** | 항상 True |

## 4. 테스트 결과

- **Backend**: 33/33 통과 (기존 19 + 신규 14)
  - `TestBuildEiSummary`: 8개 (기존)
  - `TestFinalizeEiOutput`: 11개 (기존)
  - `TestReconstruction`: 14개 (신규)
- **Frontend (vitest)**: 266/266 통과 (기존 263 + 신규 3)
  - `formatEiOutput` `isReconstructed=true` (all events reconstructed)
  - `formatEiOutput` `isReconstructed=false` (some events lack `is_reconstructed`)
  - `formatEiOutput` `isReconstructed=false` (events array is empty)
- **Docker Health Check**: 200 OK
- **Schema Import**: 정상 (`is_reconstructed=False` 기본값 확인)

## 5. 변경 불필요 파일

| 파일 | 이유 |
|------|------|
| [`run_agent_subprocess.py`](scripts/run_agent_subprocess.py) | FDC skip은 events가 이미 있는 경로, reconstruction 대상 아님 |
| [`entities.py`](src/agent_trading/domain/entities.py) | `ExternalEventEntity` 변경 불필요 (reconstruction은 읽기만 수행) |
| [`api.ts`](admin_ui/src/types/api.ts) | `isReconstructed`는 TypeScript 타입 선언만으로 충분 (utils.ts에서 처리) |

## 6. 남은 후속 과제

- `aggregate_view.event_count` → `interpreted_event_count` alias 전환 (Phase 3)
