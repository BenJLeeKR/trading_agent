# EI P1-A 설계 — EI Prompt Provenance Context 개선

## 1. 배경 및 목적

### 1.1 현재 상태

P0-1/P0-2 검증 완료:

| 항목 | 결과 |
|------|------|
| OpenDART `symbol` 채움 | 80/100 (80%) ✅ |
| `symbol=null` rows | 20/100 (20%) — 전부 비상장/기타법인 |
| `issuer_code` → `symbol` 매핑 가능 | **0%** — P0-3 불필요 판정 |
| EI input prompt provenance | **없음** — `[event_type] headline` 만 전달 |

### 1.2 현재 EI Prompt 문제

[`_build_user_prompt()`](src/agent_trading/services/ai_agents/event_interpretation.py:217) 현재 출력:

```
Correlation ID: ...
Score: ...
Recent events (5):
  - [Y|분기보고서] (주)아이티센 — 분기보고서 ...
  - [Y|유상증자결정] ...
```

**누락된 provenance 정보**:
- `source_name` (어떤 source에서 온 이벤트인지)
- `source_reliability_tier` (신뢰도 계층)
- `published_at` (발행일 — 최신성 판단 근거)
- `issuer_code` (발행법인 코드)
- stale flag (ingested_at 기준 freshness budget 초과 여부)
- `severity` / `direction` (metadata — non-default만 표시)

### 1.3 P0-3 검증 결과 반영

```
P0-3 타당성 검증 결과: 20건의 symbol=null 이벤트는 전부 비상장/기타법인 공시
→ query 확장으로 EI에 불필요한 noise만 증가
→ P0-3 불필요, P1-A는 prompt quality 개선에 집중
```

**결정: `symbol=null` 이벤트를 EI에 포함하지 않음**

---

## 2. 핵심 질문에 대한 답변

### Q1. `symbol=null` 이벤트를 EI에 전부 넣으면 noise가 얼마나 커지는가?

| 항목 | 현재 | null 포함 시 |
|------|------|-------------|
| 평균 events/request (상장사 symbol 기준) | ~5건 | 동일 (query가 symbol 기반이므로) |
| Signal-to-noise ratio | 100% | 하락 (non-tradeable entity event 추가) |

**결론**: `list_by_symbol()` query를 확장하지 않으므로 noise 증가 없음.

### Q2. OpenDART report type 중 포함할 가치가 있는 것은?

분석한 15개 null-symbol issuer_code의 공시 유형 — **0건 포함 가치 있음**.

### Q3. 현재 universe가 좁은 상태에서 issuer-level non-tradable event를 EI에 넣는 것이 유익한가?

**아니오**. 현재 `instruments` 테이블에 등록된 한국 주식은 1건(005930 smoke_test)뿐.
실제 거래 대상 symbol(030200, 097950, etc.)은 모두 `symbol`이 채워져 EI에 정상 전달됨.

### Q4. EI prompt가 provenance를 더 잘 읽게 하려면 어떤 context가 필요한가?

| Context 항목 | `ExternalEventEntity` 필드 | 실데이터 확인 |
|-------------|--------------------------|---------------|
| Source name | `source_name` | `"opendart"` — 100/100 존재 |
| Reliability tier | `source_reliability_tier` | `"T1"` — 100/100 존재 (enum `T1_REGULATORY`의 `.value` = "T1") |
| Published date | `published_at` | 100/100 존재, format `2026-05-11T00:00:00.000Z` |
| Issuer code | `issuer_code` | 100/100 존재 (8자리 corp_code) |
| Stale flag | `ingested_at` 기준 > 24h | 현재 모두 fresh (오늘 ingestion) |
| Severity | `severity` | **100% default `"medium"`** — non-default만 표시 |
| Direction | `direction` | **100% default `"neutral"`** — non-default만 표시 |

### Q5. Selection layer를 orchestrator에서 할지, EI prompt에서 하게 할지?

**결정: Orchestrator에서 deterministic selection, EI는 받은 데이터만 해석**

근거:
- AI가 "이 이벤트는 무시하세요"하게 하면 token cost 낭비
- non-tradeable entity event는 orchestrator 레벨에서 제거하는 것이 효율적
- 현재 `list_by_symbol()`이 이미 symbol 기반 filtering 수행 중 — 이 contract 유지

---

## 3. P1-A 보정 설계 (사용자 피드백 6항목 반영)

### 3.1 보정 1: `severity` / `direction` source와 default 처리

**실데이터 확인 결과**:

| 필드 | 값 | 발생률 |
|------|-----|--------|
| `severity` | `"medium"` (default) | **100%** (100/100) |
| `severity` | `"high"` / `"low"` | **0%** |
| `direction` | `"neutral"` (default) | **100%** (100/100) |
| `direction` | `"positive"` / `"negative"` | **0%** |

**Source**: `ExternalEventEntity`의 dataclass default (`severity: str = "medium"`, `direction: str = "neutral"`). [`_raw_from_item()`](src/agent_trading/brokers/opendart_adapter.py:150)에서 이 필드를 명시적으로 설정하지 않음.

**규칙**: `non-default only`
- `severity != "medium"` → `[severity:high]` 또는 `[severity:low]`
- `direction != "neutral"` → `[positive]` 또는 `[negative]`
- 현재 OpenDART 데이터에서는 절대 나타나지 않지만, 미래 source를 위해 코드에 포함

### 3.2 보정 2: `published_at` vs stale 기준 분리

| 항목 | 기준 | 근거 |
|------|------|------|
| 표시 날짜 | `published_at` | 원본 공시일 (사용자에게 의미 있는 정보) |
| Stale 판정 | `ingested_at` 기준 > 24h | 우리 시스템이 이벤트를 수집한 시점 |
| Stale format | `⚠️STALE` suffix | 간결한 경고 표시 |

**이유**: `published_at`은 공시 원본 발행일(예: 2026-05-11). `ingested_at`은 우리 시스템이 수집한 시점.
- backlog 처리로 `published_at`이 오래된 이벤트가 들어올 수 있음
- stale = `(datetime.now(timezone.utc) - ingested_at) > timedelta(hours=24)`
- prompt에는 `published_at` 날짜 표시 → 별도 stale flag 추가

**실데이터**: 현재 100건 모두 동일 batch ingestion (`ingested_at` 동일), 모두 오늘 공시 (`published_at` = 2026-05-11). 모두 fresh.

### 3.3 보정 3: headline/summary truncation 정책

**실데이터 확인**:

| 지표 | 값 |
|------|-----|
| headline p50 | 21 chars |
| headline p90 | 36 chars |
| headline max | 43 chars |
| body_summary | **100% empty** (0 chars) |

**현재 코드**: `summary[:200]` — 이미 200자 제한이 걸려있고, 실제 데이터에서는 전부 empty.

**Truncation 정책**:
- Provenance tag 예상 길이: ~50-80 chars (source + tier + date + issuer_code)
- Headline 최대: 43 chars
- 합계: ~93-123 chars → 기존 `summary[:200]` 제한에 여유 있음
- **변경 없음**: `summary[:200]` 유지, 추가 truncation 불필요

### 3.4 보정 4: source tier의 source of truth

**Enum 정의**: [`SourceReliabilityTier`](src/agent_trading/domain/enums.py:139)

```python
class SourceReliabilityTier(str, Enum):
    T1_REGULATORY = "T1"    # OpenDART, KRX KIND
    T2_INSTITUTIONAL = "T2"
    T3_MEDIA = "T3"
    T4_LOW_CONFIDENCE = "T4"
```

**DB 저장 값**: `"T1"` (enum의 `.value`)

**Source of truth**: `e.source_reliability_tier` — entity의 필드값을 직접 사용
- Prompt에는 `[tier:T1]` 형태로 표시 (raw enum value)
- **하드코딩 금지**: `e.source_reliability_tier`를 그대로 쓰고, 테스트도 DB/entity 값 기준으로 검증

### 3.5 보정 5: 불필요한 태그 제거 테스트

**적용 규칙**:
- `severity == "medium"` (default) → `[severity:...]` 미표시
- `direction == "neutral"` (default) → `[positive]`/`[negative]` 미표시
- `ingested_at` 기준 24h 이내 → `⚠️STALE` 미표시
- `issuer_code`가 None → `[issuer:...]` 미표시
- `source_name`이 None/empty → `[src:...]` 미표시

**테스트 케이스**:
1. 모든 필드 존재 → 모든 태그 표시 확인
2. severity=medium → `[severity:...]` **없음** 확인
3. direction=neutral → `[positive]`/`[negative]` **없음** 확인
4. ingested_at < 24h → `⚠️STALE` **없음** 확인
5. issuer_code=None → `[issuer:...]` **없음** 확인

### 3.6 보정 6: 기존 테스트 회귀 방지

`_build_user_prompt()` 변경은 **prompt format만 변경**하고, **output schema는 변경하지 않음**.
- `EventInterpretationOutput` dataclass 변경 없음
- `InterpretedEvent` dataclass 변경 없음
- `run()` 메서드 로직 변경 없음
- 기존 test_event_interpretation 테스트는 출력(schema) 검증 — prompt format 변경의 영향 없음

**확인할 기존 테스트 최소 범위**:
1. `test_normalize_returns_external_event_entity` — schema/output 유지 확인
2. `test_normalize_preserves_event_type` — event_type 매핑 유지 확인
3. 기존 11개 OpenDART adapter 테스트 전부 통과

---

## 4. 변경 정책

| 정책 | 결정 | 근거 |
|------|------|------|
| `symbol=null` 이벤트 포함 | ❌ **제외** | 전부 non-tradeable entity, noise only |
| `list_by_symbol()` query 확장 | ❌ **변경 없음** | 현재 contract로 충분 |
| EI prompt provenance 강화 | ✅ **적용** | source/tier/date/issuer_code/stale 정보 추가 |
| severity/direction 표시 | ✅ **non-default only** | 100% default이므로 실질적 효과 없으나 미래 대비 |
| Stale flag | ✅ `ingested_at` 기준 > 24h | `published_at`은 표시용, stale 판단은 `ingested_at` |
| 최대 event limit | 20건 유지 | token budget 고려 |
| Tier 표시 | raw enum value (e.g., `"T1"`) | hardcode 금지, entity 필드 직접 사용 |

---

## 5. 변경 파일

| # | 파일 | 변경 유형 | 설명 |
|---|------|----------|------|
| 1 | [`event_interpretation.py:217`](src/agent_trading/services/ai_agents/event_interpretation.py:217) | 수정 (1 function) | `_build_user_prompt()` — provenance format 전체 교체 |
| 2 | [`test_event_interpretation.py`](tests/services/ai_agents/test_event_interpretation.py) | 추가 (~6 tests) | provenance tag 검증, non-default-only 검증, 기존 회귀 확인 |

---

## 6. TO-BE Prompt Format (최종)

```
Correlation ID: 550e8400-e29b-41d4-a716-446655440000
Symbol: 030200 | Market: KRX | Issuer code: 00190321
Score: 0.75 (threshold: 0.50) | Reason codes: MOMENTUM_POSITIVE, EVENT_TRIGGERED

Recent events (3):
  [src:opendart] [tier:T1] [Y|임원주요주주보고서] [2026-05-11] [issuer:00190321] headline text here
  [src:opendart] [tier:T1] [Y|분기보고서] [2026-05-10] [issuer:00190321] ⚠️STALE headline text here
  [src:opendart] [tier:T1] [Y|유상증자결정] [2026-05-09] [issuer:00190321] [severity:high] [positive] headline
```

**규칙**:
- `tier:` 값은 `e.source_reliability_tier` raw value (`"T1"`, `"T2"`, etc.)
- `severity:`는 non-default(`"medium"` 아닐 때)만 표시
- `direction`은 non-default(`"neutral"` 아닐 때)만 표시
- `⚠️STALE`는 `ingested_at` 기준 24h 초과 시만 표시
- `issuer:`는 `issuer_code`가 존재할 때만 표시

---

## 7. TO-BE 코드

```python
def _build_user_prompt(self, request: AgentExecutionRequest) -> str:
    context = request.context
    score = context.score
    events = context.recent_events or []

    lines: list[str] = [
        f"Correlation ID: {request.correlation_id}",
    ]

    # --- Score & symbol info ---
    if score:
        score_line = f"Score: {score.score} (threshold: {score.threshold})"
        if score.symbol:
            score_line = f"Symbol: {score.symbol} | {score_line}"
        lines.append(score_line)
        if score.reason_codes:
            lines.append(f"Reason codes: {', '.join(score.reason_codes)}")

    # --- Recent events with provenance ---
    now = datetime.now(timezone.utc)
    lines.append(f"Recent events ({len(events)}):")
    for e in events[:20]:
        headline = e.headline or "(no headline)"
        summary = e.body_summary or ""

        # Provenance tags — only non-None/non-empty, non-default
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
        # Non-default severity only
        if e.severity and e.severity != "medium":
            parts.append(f"[severity:{e.severity}]")
        # Non-default direction only
        if e.direction and e.direction not in ("neutral", ""):
            parts.append(f"[{e.direction}]")

        # Stale check — based on ingested_at, not published_at
        stale_mark = ""
        if e.ingested_at and (now - e.ingested_at).total_seconds() > 86400:  # 24h
            stale_mark = " ⚠️STALE"

        tagged = " ".join(parts)
        body = f" — {summary[:200]}" if summary else ""
        lines.append(f"  {tagged}{stale_mark} {headline}{body}")

    return "\n".join(lines)
```

---

## 8. 변경 영향 분석

| 영향 항목 | 평가 |
|-----------|------|
| Token count 증가 | event당 ~30-50 tokens (20 events → ~600-1000 tokens, 경미) |
| Event truncation | **영향 없음** — headline max 43 chars, body_summary 100% empty |
| EI output quality | 향상 예상 (provenance 정보로 더 정확한 판단 가능) |
| 기존 테스트 영향 | **없음** — output schema 유지, prompt format만 변경 |
| DB/API 영향 | 없음 (query contract 변경 없음) |
| Runtime 성능 | 영향 없음 (CPU only prompt build) |

---

## 9. 테스트 계획 (6 tests)

| # | 테스트 | 설명 |
|---|--------|------|
| 1 | `test_prompt_includes_provenance_tags` | 모든 필드 존재 시 `[src:...]`, `[tier:...]`, `[issuer:...]` 등 표시 확인 |
| 2 | `test_prompt_omits_default_severity_tag` | `severity="medium"` → `[severity:...]` 미표시 |
| 3 | `test_prompt_omits_default_direction_tag` | `direction="neutral"` → `[positive]`/`[negative]` 미표시 |
| 4 | `test_prompt_omits_stale_flag_when_fresh` | `ingested_at` < 24h → `⚠️STALE` 미표시 |
| 5 | `test_prompt_omits_issuer_tag_when_none` | `issuer_code=None` → `[issuer:...]` 미표시 |
| 6 | `test_prompt_includes_stale_flag` | `ingested_at` > 24h → `⚠️STALE` 표시 확인 |

**기존 테스트 회귀 확인**: 기존 test_event_interpretation의 schema 검증 테스트 전부 통과 확인.

---

## 10. 기대 효과

| 효과 | 설명 | 계측 방법 |
|------|------|----------|
| EI 판단 정확도 향상 | provenance 정보로 최신성/신뢰도 반영 가능 | EI output quality metric |
| 불필요한 noise 차단 | null-symbol 제외 + non-default-only 태그 규칙으로 signal ratio 유지 | events/request count |
| Debuggability 개선 | prompt에 더 많은 context로 문제 분석 용이 | log inspection |
| Token 효율 | 20건 limit + 간결 bracket format 유지 | prompt length monitoring |

---

## 11. 남은 리스크 1개

**`severity`/`direction`이 100% default이므로 provenance 개선의 실질적 효과가 prompt format에 국한됨**

현재 OpenDART 데이터는 `severity="medium"`, `direction="neutral"`이 100%. 즉 `[severity:high]`나 `[positive]` 같은 태그는 절대 나타나지 않음. P1-A의 실질적 개선은 `[src:opendart]`, `[tier:T1]`, `[2026-05-11]`, `[issuer:00190321]`, `⚠️STALE`에 집중됨. 만약 `severity`/`direction`을 source adapter에서 채우도록 개선한다면(`_raw_from_item()`에서 설정), 이 태그들이 유의미해짐 — 그러나 이는 별도 작업.

---

## 12. 다음 직접 액션 1개

**P1-A 구현 — Code 모드에서 2개 파일 변경**

1. [`event_interpretation.py:217`](src/agent_trading/services/ai_agents/event_interpretation.py:217) — `_build_user_prompt()` 메서드를 위 7항 TO-BE 코드로 교체
2. [`test_event_interpretation.py`](tests/services/ai_agents/test_event_interpretation.py) — 위 9항 6개 테스트 추가
3. 기존 테스트 전부 통과 확인 (`pytest tests/brokers/test_opendart_adapter.py -v` 등)
4. P1-B(시간 윈도우 확장)는 P1-A 안정화 후 결정
