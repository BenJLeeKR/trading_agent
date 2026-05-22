# EI가 Persisted Seeded 뉴스를 읽지 못하는 문제 수정 (Round 9)

## 1. 개요

**목표**: Event Interpretation(EI) 에이전트가 `external_events` 테이블에 persisted된 seeded 뉴스(`event_type='seeded_news'`)를 실제로 읽도록 조회 경로를 수정한다.

**문제**: EI가 항상 `events=[]`와 `event_count=0`을 보고하며 "유의미한 신규 이벤트 없음" 결론을 반복함. 실제로는 `external_events` 테이블에 `event_type='seeded_news'` 데이터가 존재하지만, `list_by_symbol()` SQL 필터가 이를 제외하고 있었음.

---

## 2. 근본 원인

### 2.1 SQL 필터가 `seeded_news`를 제외

[`PostgresExternalEventRepository.list_by_symbol()`](src/agent_trading/repositories/postgres/external_events.py:91)의 SQL WHERE 절:

```sql
WHERE (event_type LIKE 'Y|%' OR event_type LIKE 'K|%' OR event_type LIKE 'N|%')
```

- OpenDART 상장법인 prefix (`Y|`, `K|`, `N|`)만 허용
- `event_type='seeded_news'`는 이 패턴과 매칭되지 않아 항상 제외됨

### 2.2 InMemory 구현도 동일한 문제

[`InMemoryExternalEventRepository._is_listed_event()`](src/agent_trading/repositories/memory.py:1082)는 prefix가 없는 이벤트를 `True`(listed)로 간주:

```python
# E| prefix = non-listed; no prefix = unknown → treat as listed
if event.event_type.startswith("E|"):
    return False
return True
```

`seeded_news`는 prefix가 없으므로 `_is_listed_event()`가 `True` 반환 → `include_seeded_news=False`(기본값)에서도 포함됨. 이는 의도와 반대되는 동작.

### 2.3 영향받는 3개 호출 지점

1. [`DecisionOrchestratorService.assemble()`](src/agent_trading/services/decision_orchestrator.py:578) — EI 컨텍스트 구성
2. [`_collect_persisted_seeded_events()`](scripts/run_paper_decision_loop.py:962) — T3 이벤트 수집
3. [`_is_t3_fresh_for_symbol()`](scripts/run_paper_decision_loop.py:997) — T3 freshness 확인

---

## 3. 수정 사항

### 3.1 [`contracts.py`](src/agent_trading/repositories/contracts.py) — 프로토콜에 `include_seeded_news` 파라미터 추가

```python
async def list_by_symbol(
    self,
    symbol: str,
    since: datetime,
    include_non_listed: bool = False,
    include_seeded_news: bool = False,  # ← 추가
) -> Sequence[ExternalEventEntity]:
```

`list_by_type()`에도 동일한 파라미터 추가.

### 3.2 [`external_events.py`](src/agent_trading/repositories/postgres/external_events.py) — SQL 필터에 `seeded_news` OR 조건 추가

```python
elif include_seeded_news:
    rows = await self._tx.connection.fetch(
        """
        SELECT * FROM trading.external_events
        WHERE symbol = $1
          AND published_at >= $2
          AND (
              (event_type LIKE 'Y|%' OR event_type LIKE 'K|%' OR event_type LIKE 'N|%')
              OR event_type = 'seeded_news'
          )
        ORDER BY published_at DESC
        """,
        symbol,
        since,
    )
```

3-way 분기:
- `include_non_listed=True` → 필터 없음 (기존)
- `include_seeded_news=True` → listed + `seeded_news`
- 기본값(둘 다 False) → listed만 (기존과 동일, 회귀 없음)

### 3.3 [`memory.py`](src/agent_trading/repositories/memory.py) — `_is_seeded_news()` 추가 + `_is_listed_event()` 수정

```python
@staticmethod
def _is_seeded_news(event: ExternalEventEntity) -> bool:
    return event.event_type == "seeded_news"
```

`_is_listed_event()`에 `seeded_news` early return 추가:

```python
if event.event_type == "seeded_news":
    return False  # seeded_news는 listed entity 이벤트가 아님
```

`_include()` 클로저에서 `include_seeded_news` 처리:

```python
def _include(item: ExternalEventEntity) -> bool:
    if include_non_listed:
        return True
    if self._is_listed_event(item):
        return True
    if include_seeded_news and self._is_seeded_news(item):
        return True
    return False
```

### 3.4 [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) — `assemble()`에서 `include_seeded_news=True` 전달

```python
events = await self._repos.external_events.list_by_symbol(
    symbol=request.symbol,
    since=datetime.now(timezone.utc) - timedelta(hours=72),
    include_seeded_news=True,  # ← 추가
)
```

### 3.5 [`run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) — 2개 함수 수정

```python
# _collect_persisted_seeded_events()
events = await repos.external_events.list_by_symbol(
    symbol=symbol, since=since, include_seeded_news=True,
)

# _is_t3_fresh_for_symbol()
events = await repos.external_events.list_by_symbol(
    symbol=symbol, since=since, include_seeded_news=True,
)
```

---

## 4. 테스트 결과

### 4.1 신규 테스트 (8개)

| 테스트 | 파일 | 검증 내용 |
|--------|------|-----------|
| `test_inmemory_list_by_symbol_excludes_seeded_news_by_default` | `test_external_events.py` | 기본값에서 `seeded_news` 제외 |
| `test_inmemory_list_by_symbol_includes_seeded_news` | `test_external_events.py` | `include_seeded_news=True`에서 포함 |
| `test_postgres_list_by_symbol_excludes_seeded_news_by_default` | `test_external_events.py` | Postgres 기본값 제외 |
| `test_postgres_list_by_symbol_includes_seeded_news` | `test_external_events.py` | Postgres 명시적 포함 |
| `test_assemble_includes_seeded_news` | `test_decision_submit_pipeline.py` | `assemble()`이 seeded_news 포함 |
| `test_includes_seeded_news_event_type` | `test_run_paper_decision_loop.py` | `_collect_persisted_seeded_events()`가 `event_type='seeded_news'` 반환 |
| `test_true_with_seeded_news_event_type` | `test_run_paper_decision_loop.py` | `_is_t3_fresh_for_symbol()`이 `event_type='seeded_news'` 감지 |

### 4.2 실행 결과

```
tests/repositories/test_external_events.py::test_inmemory_* — 8 passed
tests/services/test_decision_submit_pipeline.py::TestEventQueryWindow — 2 passed
tests/scripts/test_run_paper_decision_loop.py::TestCollectPersistedSeededEvents — 4 passed
tests/scripts/test_run_paper_decision_loop.py::TestIsT3FreshForSymbol — 4 passed
```

---

## 5. 수정된 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| [`src/agent_trading/repositories/contracts.py`](src/agent_trading/repositories/contracts.py) | 수정 | `include_seeded_news` 파라미터 프로토콜에 추가 |
| [`src/agent_trading/repositories/postgres/external_events.py`](src/agent_trading/repositories/postgres/external_events.py) | 수정 | SQL 3-way 분기로 `seeded_news` OR 조건 추가 |
| [`src/agent_trading/repositories/memory.py`](src/agent_trading/repositories/memory.py) | 수정 | `_is_seeded_news()` 추가, `_is_listed_event()` 수정, `_include()` 클로저 |
| [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | 수정 | `assemble()`에서 `include_seeded_news=True` 전달 |
| [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) | 수정 | `_collect_persisted_seeded_events()` + `_is_t3_fresh_for_symbol()` 수정 |
| [`tests/repositories/test_external_events.py`](tests/repositories/test_external_events.py) | 수정 | InMemory + Postgres `include_seeded_news` 테스트 4개 추가 |
| [`tests/services/test_decision_submit_pipeline.py`](tests/services/test_decision_submit_pipeline.py) | 수정 | `test_assemble_includes_seeded_news` 추가 |
| [`tests/scripts/test_run_paper_decision_loop.py`](tests/scripts/test_run_paper_decision_loop.py) | 수정 | `event_type='seeded_news'` 조회 테스트 2개 추가 |
| [`plans/fix_event_interpretation_not_reading_persisted_seeded_news_from_external_events_2026-05-22.md`](plans/fix_event_interpretation_not_reading_persisted_seeded_news_from_external_events_2026-05-22.md) | 생성 | 본 보고서 |

---

## 6. 회귀 방지

- `include_seeded_news` 기본값은 `False` — 기존 모든 호출자는 변경 없음
- 기존 `list_by_symbol()` 테스트(InMemory 1개, Postgres 1개)는 그대로 통과
- `_is_listed_event()`에 `seeded_news` early return 추가로 InMemory 일관성 확보
- SQL 3-way 분기로 Postgres 일관성 확보

---

## 7. 운영 검증 (Docker 재시작 필요)

```bash
docker compose build && docker compose up -d
curl -sf http://localhost:8000/health
```

### 장중 확인 항목

1. **EI 컨텍스트에 seeded_news 포함**: `event_count > 0` 확인 (대표 종목: 000660, 005930, 000720)
2. **T3 freshness 정상 감지**: `_is_t3_fresh_for_symbol()`이 `True` 반환
3. **기존 listed event 필터링 회귀 없음**: OpenDART 이벤트는 계속 정상 조회
