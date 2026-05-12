# EI P1-A + P1-B 통합 검증 계획

## 1. 검증 목표

P1-A(prompt provenance 강화)와 P1-B(72h retention 확장)가 **함께 작동**하여 EI 입력 품질이 실제로 개선되었는지 확인.

### 현재 개별 테스트 상태

| 테스트 | 위치 | 검증 범위 | 상태 |
|--------|------|-----------|------|
| `TestEventQueryWindow::test_assemble_uses_72h_window` | [`test_decision_submit_pipeline.py:745`](../tests/services/test_decision_submit_pipeline.py:745) | `recent_events` inclusion/exclusion만 확인, prompt까지 확인 안 함 | ✅ PASS |
| `TestEventInterpretationAgentPrompt` (6 tests) | [`test_agents.py:1342`](../tests/services/ai_agents/test_agents.py:1342) | `_build_user_prompt()` 직접 호출, `assemble()` 통과 안 함 | ✅ PASS |

### 통합 검증이 필요한 이유

```
기존: event seed → _build_user_prompt()  (P1-A만 검증)
기존: event seed → assemble() → recent_events  (P1-B만 검증)
필요: event seed → assemble() → recent_events → _build_user_prompt()  (P1-A+P1-B 통합 검증)
```

---

## 2. 검증 시나리오

### 시나리오 1: 기본 통합 — 48h event가 provenance tag와 함께 prompt까지 도달

**목표**: P1-B(72h retention)로 조회된 event가 P1-A(provenance tag)와 함께 EI prompt에 표시되는지 확인.

**검증 데이터**:
```python
# Event A: 48h 전, 모든 필드 존재
ExternalEventEntity(
    source_name="opendart",
    source_reliability_tier="T1",
    event_type="K|분기보고서 (2026.03)",
    published_at=now - timedelta(hours=48),
    symbol="005930",
    issuer_code="00123456",
    ingested_at=now - timedelta(hours=48),  # stale
    severity="high",      # non-default
    direction="positive", # non-default
    headline="분기보고서",
)

# Event B: 96h 전 (window 밖)
ExternalEventEntity(
    published_at=now - timedelta(hours=96),
    symbol="005930",
    ...
)
```

**검증 항목**:
1. `recent_events`에 Event A 포함, Event B 제외 ✅ (P1-B)
2. Prompt에 `[src:opendart]` 포함 ✅ (P1-A)
3. Prompt에 `[tier:T1]` 포함 ✅ (P1-A)
4. Prompt에 `[K|분기보고서 (2026.03)]` 포함 ✅ (P1-A)
5. Prompt에 날짜 `[YYYY-MM-DD]` 포함 ✅ (P1-A)
6. Prompt에 `[issuer:00123456]` 포함 ✅ (P1-A)
7. Prompt에 `[severity:high]` 포함 ✅ (P1-A, non-default)
8. Prompt에 `[positive]` 포함 ✅ (P1-A, non-default)
9. Prompt에 `⚠️STALE` 포함 ✅ (P1-A, ingested_at=48h > 24h)

**예상 prompt 출력**:
```
  [src:opendart] [tier:T1] [K|분기보고서 (2026.03)] [2026-05-09] [issuer:00123456] [severity:high] [positive] ⚠️STALE 분기보고서
```

---

### 시나리오 2: Fresh event — ingested_at < 24h, published_at > 24h

**목표**: `ingested_at`은 fresh지만 `published_at`은 48h 전인 event.  
→ retention window(72h)에는 포함되지만 stale 마크는 없어야 함.

**검증 데이터**:
```python
ExternalEventEntity(
    published_at=now - timedelta(hours=48),  # 48h 전 공시
    ingested_at=now - timedelta(hours=1),    # 1h 전 수집 (fresh)
    symbol="005930",
    ...
)
```

**검증 항목**:
1. `recent_events`에 포함 ✅ (published_at 48h < 72h window)
2. Prompt에 ⚠️STALE **없음** ✅ (ingested_at 1h < 24h)
3. Prompt 날짜는 `published_at` 기준 `[2026-05-09]`로 표시 ✅

---

### 시나리오 3: Non-default-only 규칙 — severity/direction 생략

**목표**: `severity=medium`(default), `direction=neutral`(default)인 event는 해당 tag가 prompt에 없어야 함.

**검증 데이터**:
```python
ExternalEventEntity(
    severity="medium",    # default
    direction="neutral",  # default
    ...
)
```

**검증 항목**:
1. `[severity:medium]` 없음 ✅
2. `[positive]`/`[negative]` 없음 ✅

---

### 시나리오 4: issuer_code=None

**목표**: issuer_code가 없는 event는 `[issuer:...]` tag가 없어야 함.

**검증 데이터**:
```python
ExternalEventEntity(issuer_code=None, ...)
```

**검증 항목**:
1. `[issuer:` 문자열 없음 ✅

---

### 시나리오 5: 20-event cap

**목표**: 25개 event가 `recent_events`에 있더라도 prompt에는 20개만 표시되어야 함.

**검증 데이터**: 동일 symbol의 event 25개, 모두 published_at < 72h 내

**검증 항목**:
1. `recent_events` 길이 == 25 ✅
2. Prompt에서 `Recent events (25):` 표시 ✅
3. Prompt의 event 줄 수 == 20 ✅ (events[:20] slice)

---

## 3. 검증 스크립트

아래는 `tests/services/` 디렉토리에 추가할 통합 검증 테스트 클래스입니다.

### 파일: `tests/services/test_decision_submit_pipeline.py` (기존 파일에 추가)

`TestEventQueryWindow` 클래스 아래에 `TestP1AandP1BIntegration` 클래스를 추가:

```python
class TestP1AandP1BIntegration:
    """P1-A (prompt provenance) + P1-B (72h retention) 통합 검증.

    event seed → assemble() → recent_events → _build_user_prompt()
    전체 파이프라인이 의도대로 작동하는지 확인.
    """

    @pytest.mark.asyncio
    async def test_48h_event_has_provenance_tags_in_prompt(self) -> None:
        """시나리오 1: 48h event가 provenance tag와 함께 prompt에 표시됨."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        # 48h event (모든 provenance 필드 존재)
        event_48h = ExternalEventEntity(
            event_id=uuid4(),
            event_type="K|분기보고서 (2026.03)",
            source_name="opendart",
            published_at=now - timedelta(hours=48),
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now - timedelta(hours=48),
            severity="high",
            direction="positive",
            headline="분기보고서",
        )
        await repos.external_events.add(event_48h)

        # 96h event (window 밖)
        event_96h = ExternalEventEntity(
            event_id=uuid4(),
            event_type="Y|사업보고서 (2025.12)",
            source_name="opendart",
            published_at=now - timedelta(hours=96),
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now - timedelta(hours=96),
            headline="사업보고서",
        )
        await repos.external_events.add(event_96h)

        # assemble() 실행
        request = _make_request()
        intent = await svc.assemble(request)

        # --- P1-B 검증: retention window ---
        event_ids = {e.event_id for e in intent.context.recent_events}
        assert event_48h.event_id in event_ids, "48h event must be in 72h window"
        assert event_96h.event_id not in event_ids, "96h event must be outside 72h window"

        # --- P1-A 검증: provenance tags in prompt ---
        # assemble()이 만든 context로 EI prompt 생성
        agent = EventInterpretationAgent(provider_client=AsyncMock())
        ei_request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="integ-test-1",
            context=intent.context,
        )
        prompt = agent._build_user_prompt(ei_request)

        # Provenance tags 존재 확인
        assert "[src:opendart]" in prompt
        assert "[tier:T1]" in prompt
        assert "[K|분기보고서 (2026.03)]" in prompt
        date_str = (now - timedelta(hours=48)).strftime("%Y-%m-%d")
        assert f"[{date_str}]" in prompt
        assert "[issuer:00123456]" in prompt
        assert "[severity:high]" in prompt
        assert "[positive]" in prompt
        # stale: ingested_at=48h > 24h
        assert "⚠️STALE" in prompt

    @pytest.mark.asyncio
    async def test_fresh_ingestion_no_stale_despite_old_published(self) -> None:
        """시나리오 2: ingested_at fresh, published_at old → ⚠️STALE 없음."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="K|공시",
            source_name="opendart",
            published_at=now - timedelta(hours=48),  # 48h 전 공시 (72h window 내)
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now - timedelta(hours=1),    # 1h 전 수집 (fresh)
            headline="공시",
        )
        await repos.external_events.add(event)

        request = _make_request()
        intent = await svc.assemble(request)

        event_ids = {e.event_id for e in intent.context.recent_events}
        assert event.event_id in event_ids

        agent = EventInterpretationAgent(provider_client=AsyncMock())
        ei_request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="integ-test-2",
            context=intent.context,
        )
        prompt = agent._build_user_prompt(ei_request)

        # ingested_at=1h < 24h → stale 아님
        assert "⚠️STALE" not in prompt, (
            "Event ingested 1h ago must NOT have stale mark"
        )
        # published_at 날짜는 표시되어야 함
        date_str = (now - timedelta(hours=48)).strftime("%Y-%m-%d")
        assert f"[{date_str}]" in prompt

    @pytest.mark.asyncio
    async def test_default_severity_direction_omitted(self) -> None:
        """시나리오 3: severity=medium, direction=neutral → tag 생략."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="disclosure",
            source_name="opendart",
            published_at=now,
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now,
            severity="medium",    # default
            direction="neutral",  # default
            headline="test",
        )
        await repos.external_events.add(event)

        request = _make_request()
        intent = await svc.assemble(request)

        agent = EventInterpretationAgent(provider_client=AsyncMock())
        ei_request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="integ-test-3",
            context=intent.context,
        )
        prompt = agent._build_user_prompt(ei_request)

        assert "[severity:medium]" not in prompt
        assert "[positive]" not in prompt
        assert "[negative]" not in prompt

    @pytest.mark.asyncio
    async def test_no_issuer_code_tag_omitted(self) -> None:
        """시나리오 4: issuer_code=None → [issuer:...] tag 없음."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="disclosure",
            source_name="opendart",
            published_at=now,
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code=None,  # issuer 없음
            ingested_at=now,
            headline="test",
        )
        await repos.external_events.add(event)

        request = _make_request()
        intent = await svc.assemble(request)

        agent = EventInterpretationAgent(provider_client=AsyncMock())
        ei_request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="integ-test-4",
            context=intent.context,
        )
        prompt = agent._build_user_prompt(ei_request)

        assert "[issuer:" not in prompt

    @pytest.mark.asyncio
    async def test_20_event_cap_in_prompt(self) -> None:
        """시나리오 5: 25개 event → prompt에는 20개만 표시."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        # 25개 event seed (모두 72h window 내)
        for i in range(25):
            event = ExternalEventEntity(
                event_id=uuid4(),
                event_type=f"type_{i}",
                source_name="opendart",
                published_at=now - timedelta(hours=i),  # 0h ~ 24h 전
                source_reliability_tier="T1",
                symbol="005930",
                issuer_code="00123456",
                ingested_at=now - timedelta(hours=i),
                headline=f"event_{i}",
            )
            await repos.external_events.add(event)

        request = _make_request()
        intent = await svc.assemble(request)

        # recent_events에는 25개 모두 있어야 함
        assert len(intent.context.recent_events) == 25

        agent = EventInterpretationAgent(provider_client=AsyncMock())
        ei_request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="integ-test-5",
            context=intent.context,
        )
        prompt = agent._build_user_prompt(ei_request)

        # Prompt 헤더에는 전체 count 표시
        assert "Recent events (25):" in prompt

        # Prompt의 event 줄 수는 20개여야 함 ([:20] slice)
        event_lines = [line for line in prompt.split("\n") if line.startswith("  [src:")]
        assert len(event_lines) == 20, (
            f"Expected 20 event lines in prompt, got {len(event_lines)}"
        )

        # event_0 ~ event_19는 있어야 함
        assert "event_0" in prompt
        assert "event_19" in prompt
        # event_20 ~ event_24는 없어야 함
        assert "event_20" not in prompt
```

### 필요한 추가 import

```python
# test_decision_submit_pipeline.py 상단에 추가
from unittest.mock import AsyncMock
from agent_trading.services.ai_agents.event_interpretation import EventInterpretationAgent
from agent_trading.services.ai_agents.base import AgentExecutionRequest
```

---

## 4. 실행 방법

```bash
# 통합 검증만 실행
python3 -m pytest tests/services/test_decision_submit_pipeline.py::TestP1AandP1BIntegration -v

# 기존 P1-B 테스트와 함께 실행
python3 -m pytest tests/services/test_decision_submit_pipeline.py::TestEventQueryWindow tests/services/test_decision_submit_pipeline.py::TestP1AandP1BIntegration -v

# 기존 P1-A 테스트와 함께 실행 (회귀 확인)
python3 -m pytest tests/services/ai_agents/test_agents.py::TestEventInterpretationAgentPrompt tests/services/test_decision_submit_pipeline.py::TestP1AandP1BIntegration -v

# 전체 테스트 (Postgres 제외, 빠른 확인)
python3 -m pytest --ignore=tests/repositories/test_postgres_external_events.py --ignore=tests/integration --ignore=tests/smoke -x -v 2>&1 | tail -30
```

---

## 5. 예상 결과

| 시나리오 | 검증 내용 | 예상 |
|----------|-----------|------|
| 1 | 48h event → prompt에 provenance tag 8종 + stale | ✅ PASS |
| 2 | ingested_at fresh + published_at old → stale 없음, 날짜는 표시 | ✅ PASS |
| 3 | severity=medium, direction=neutral → tag 생략 | ✅ PASS |
| 4 | issuer_code=None → [issuer:...] 없음 | ✅ PASS |
| 5 | 25개 event → recent_events=25, prompt lines=20 | ✅ PASS |

---

## 6. 남은 리스크 1개

**DB 기반 통합 검증 부재**: 현재 검증은 InMemory repository 기반입니다. 실제 Postgres `list_by_symbol()` SQL (`WHERE symbol = $1 AND published_at >= $2`)도 동일한 72h window를 사용하지만, 이는 이미 [`test_postgres_list_by_symbol`](../tests/repositories/test_external_events.py:200)에서 `since` 파라미터 전달 방식으로 간접 검증됩니다. 다만 해당 테스트는 asyncpg loop attachment 문제로 현재 실행 불가능한 상태입니다.

---

## 7. 다음 직접 액션 1개

상기 검증 스크립트를 `tests/services/test_decision_submit_pipeline.py`에 추가하고 `python3 -m pytest tests/services/test_decision_submit_pipeline.py::TestP1AandP1BIntegration -v`로 실행. 5개 시나리오가 모두 PASS하면 P1-A+P1-B 통합 검증 완료.
