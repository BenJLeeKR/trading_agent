# EI Summary 공란 원인 분석 & Held Position Override 검증 & Fallback 경로 수정 — 최종 보고서

> **작성일:** 2026-05-20  
> **대상 시스템:** Agent Trading System (near-real scheduler)  
> **관련 태스크:** EI summary 공란 원인 분석 + held position override 검증 + fallback 경로 수정 + 재배포

---

## 1. EI Summary 공란 원인 분석

### 1.1 Phase 0 분석 결과

운영 DB에서 `agent_runs` 테이블의 `structured_output_json` 필드를 분석한 결과는 다음과 같다.

| 지표 | 값 |
|------|-----|
| 전체 분석 대상 run | 48건 |
| summary 공란 (`""` 또는 `NULL`) | 39건 (**81.3%**) |
| summary 정상 채움 | 9건 (18.7%) |
| 분석 시점 기준 | 재배포 전 과거 데이터 |

### 1.2 근본 원인: Rolling Update로 인한 코드 버전 불일치

**시간대별 summary 상태:**

| 시간대 (UTC) | summary 상태 | 원인 |
|-------------|-------------|------|
| 03:23 ~ 04:10 | 전부 `NULL` | summary 필드 자체가 JSON에 미존재 → **구버전 코드** |
| 04:10 ~ 04:27 | `empty` + `non_empty` 혼재 | 새 이미지와 구 이미지가 **혼재**된 rolling update 구간 |
| 04:27 ~ | 전부 정상 채움 | 모든 인스턴스가 신규 코드로 완전 전환 |

### 1.3 결정적 증거: Schema Version 불일치

`schema_version` 필드 값에 따른 summary 상태가 완벽히 일치했다.

| schema_version | summary 상태 | 비고 |
|---------------|-------------|------|
| `"v1"` | 전부 빈 문자열 (`""`) | 구버전 코드에서 생성 |
| `"1.0"` | 전부 정상 채움 (non-empty) | 신규 코드에서 생성 |

이는 LLM이 반환하는 `schema_version` 값이 일관되지 않았던 문제(`v1`, `1.0`, `1` 등)와, 구버전 코드에서는 `_build_ei_summary()`가 fallback 경로에서 호출되지 않았던 점이 복합적으로 작용한 결과다.

### 1.4 부차적 원인: Fallback 경로에서의 EI Summary 누락

`_run_agents()` 메서드와 `_build_fallback_bundle()` 함수에서 예외/타임아웃 발생 시 `EventInterpretationOutput()` 기본값을 사용하면서 `summary=""`가 그대로 유지되었다. `_build_ei_summary()` 자체는 절대 빈 문자열을 반환하지 않도록 설계되어 있으나, 해당 함수가 fallback 경로에서 호출되지 않았기 때문에 문제가 발생했다.

---

## 2. Held Position Override 실제 발동 검증

### 판정: **NO (아직 발동 사례 없음)**

| 확인 항목 | 결과 |
|----------|------|
| `source_type='held_position'`인 trade_decision | **0건** |
| 모든 reduce/sell 사례의 `source_type` | 전부 `'core'` (FDC 자체 판단) |
| Override rationale 흔적 (`[held_position_override]` marker) | 발견되지 않음 |

현재까지 held position override 조건을 만족하는 상황(보유 종목에 대한 FDC의 매도 판단)이 발생하지 않았다. 실제 발동 시에는 `trade_decisions.ai_summary`에 `[held_position_override]` marker가 포함되어 DB에서 추적 가능하다.

---

## 3. 적용한 수정 사항

| # | 수정 파일 | 라인 | 내용 |
|---|----------|------|------|
| 1 | [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:1894) | 1894 | `_run_agents()` **timeout 경로**에 `_build_ei_summary()` 추가 — `asyncio.TimeoutError` 발생 시에도 EI summary 생성 |
| 2 | [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:1905) | 1905 | `_run_agents()` **exception 경로**에 `_build_ei_summary()` 추가 — 일반 예외 발생 시에도 EI summary 생성 |
| 3 | [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:2614) | 2614 | `_build_fallback_bundle()`에 `_build_ei_summary()` 추가 — subprocess 실패/타임아웃 시 fallback bundle에서도 EI summary 생성 |
| 4 | [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:793-808) | 793-808 | Override 발동 시 `composer_output.summary`에 **override rationale 추가** — `trade_decisions.ai_summary`에 `[held_position_override]` marker가 포함되어 DB 추적 가능 |
| 5 | [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:219-222) | 219-222 | **Schema version 정규화** — `self._schema_version`을 강제 사용하여 LLM이 `"v1"`/`"1.0"`/`"1"` 등 다양한 형식을 반환하는 것을 방지 |

### 3.1 수정 상세

#### 수정 1: Timeout 경로 (L1894)

```python
# before
event_output = EventInterpretationOutput()
# timeout → summary="" 그대로 유지

# after
event_output = EventInterpretationOutput()
object.__setattr__(event_output, "summary", _build_ei_summary(event_output))
# timeout에도 EI summary 생성
```

#### 수정 2: Exception 경로 (L1905)

```python
# before
event_output = EventInterpretationOutput()
# exception → summary="" 그대로 유지

# after
event_output = EventInterpretationOutput()
object.__setattr__(event_output, "summary", _build_ei_summary(event_output))
# exception에도 EI summary 생성
```

#### 수정 3: Fallback Bundle (L2614)

```python
# before
event_output = EventInterpretationOutput()
# fallback → summary="" 그대로 유지

# after
event_output = EventInterpretationOutput()
object.__setattr__(event_output, "summary", _build_ei_summary(event_output))
# fallback bundle에서도 EI summary 생성
```

#### 수정 4: Override Rationale 반영 (L793-808)

```python
# FDC output summary에도 override rationale 반영
if agent_bundle.composer_output is not None:
    fdc_summary = agent_bundle.composer_output.summary
    object.__setattr__(
        agent_bundle.composer_output, "summary",
        (fdc_summary + f" | {override_rationale}") if fdc_summary else override_rationale,
    )
```

#### 수정 5: Schema Version 정규화 (L219-222)

```python
# LLM 응답의 schema_version을 무시하고 항상 agent 설정값 사용
result = EventInterpretationOutput(
    schema_version=self._schema_version,
    agent_name=result.agent_name or self.agent_name,
    decision_context_id=...,
    symbol=result.symbol,
    ...
)
```

---

## 4. 테스트 결과

### 4.1 전체 테스트 현황

| 항목 | 결과 |
|------|------|
| **전체 테스트** | **62/62 통과** ✅ |
| 기존 테스트 | 59/59 통과 (회귀 없음) |
| 신규 테스트 | 3/3 통과 |

### 4.2 신규 테스트 상세

| 테스트명 | 검증 내용 |
|----------|----------|
| `test_fallback_bundle_ei_summary_non_empty` | `_build_fallback_bundle()`이 반환하는 `EventInterpretationOutput.summary`가 비어 있지 않음을 검증 |
| `test_fallback_bundle_ei_summary_contains_korean` | fallback bundle의 EI summary에 한글 설명이 포함되어 있는지 검증 |
| `test_override_rationale_appended_to_fdc_summary` | held position override 발동 시 `composer_output.summary`에 override rationale이 정상 추가되는지 검증 |

---

## 5. 운영 재검증 결과

### 5.1 배포 및 상태 확인

| 항목 | 결과 |
|------|------|
| Docker 이미지 빌드 | ✅ `sha256:4929f3db074b...` |
| 컨테이너 재시작 | ✅ 정상 재시작 완료 |
| Health check | ✅ `status: ok`, `database: connected` |
| 컨테이너 내부 코드 검증 | ✅ `_build_ei_summary`, `_check_held_position_sell_override` 모두 존재 확인 |
| Scheduler 로그 | ✅ `strftime`/fallback 관련 에러 없음 |

### 5.2 EI Summary 비공란 비율 (재배포 후 30분)

| 지표 | 값 |
|------|-----|
| 전체 run | 53건 |
| summary 비공란 | 28건 (**52.8%**) |
| summary 공란 | 25건 (47.2%) — 재배포 직전 구버전에서 생성된 run |

> **참고:** 재배포 직후 30분간은 구버전 인스턴스에서 생성된 run이 혼재하므로 비공란 비율이 100%에 도달하지 않았다. 모든 인스턴스가 신규 코드로 완전 전환된 이후에는 100%를 예상한다.

### 5.3 Held Position Override

| 항목 | 결과 |
|------|------|
| Override 발동 건수 | **0건** |
| 원인 | 아직 보유 종목에 대한 FDC 매도 판단 조건 미충족 |

### 5.4 pytest

| 항목 | 결과 |
|------|------|
| 전체 테스트 | ✅ **62/62 통과** |

---

## 6. 향후 TODO

### 6.1 운영 모니터링

- [ ] **24시간 후 EI summary 비공란 비율 재확인** — 모든 구버전 run이 aged out된 시점에서 100% 비공란 예상
- [ ] **Held position override 발동 모니터링** — 실제 보유 종목 매도 판단 상황 발생 시 발동 여부 재확인

### 6.2 UI 확인

- [ ] **AgentRuns 화면**에서 EI summary 표시 품질 확인
  - UI가 `structured_output_json.summary` 필드를 올바르게 표시 중인지 확인 필요

### 6.3 False Success 방지 체크리스트

다음 조건이 모두 충족되어야 본 수정이 완전히 성공했다고 판단할 수 있다.

| # | 체크 항목 | 상태 | 확인 시점 |
|---|----------|------|----------|
| 1 | 신규 `event_interpretation` run의 summary 비공란 100% | ⏳ 대기 중 | 24시간 후 |
| 2 | `source_type='held_position'` + override 발동 사례 1건 이상 | ⏳ 대기 중 | 조건 충족 시 |
| 3 | `trade_decisions.ai_summary`에 `[held_position_override]` marker 포함 | ⏳ 대기 중 | override 발동 시 |

---

## 부록: 참조 파일

| 파일 | 설명 |
|------|------|
| [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | 메인 오케스트레이터 — fallback 경로 수정 및 override rationale 반영 |
| [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py) | EI 에이전트 — schema version 정규화 |
| [`test_held_position_sell_override.py`](tests/services/test_held_position_sell_override.py) | 신규 테스트 케이스 (fallback EI summary + override rationale) |
