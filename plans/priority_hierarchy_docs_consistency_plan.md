# Priority Hierarchy 문서 정합성 보정 계획

## 목표
`UniverseSelectionService`의 source priority 정책 표현을 **실제 코드 기준**으로 일치시킴.
동작 변경 없음. 문서/주석만 수정.

## 실제 코드 기준 (변경 불가)
```python
# SourceType.priority() mapping
HELD_POSITION(0) > EVENT_OVERLAY(1) > MARKET_OVERLAY(2) > MANUAL(3) > CORE(4)
```
Lower value = higher priority.

## 수정 대상 4개 파일

### ❶ `src/agent_trading/services/universe_selection.py:559-567`
`_upsert_with_priority()` docstring 수정.

**변경사항**:
- `HELD_POSITION > MANUAL > EVENT_OVERLAY >= MARKET_OVERLAY > CORE`
- `Equal priority (EVENT/MARKET both=2)`

→
- `HELD_POSITION(0) > EVENT_OVERLAY(1) > MARKET_OVERLAY(2) > MANUAL(3) > CORE(4)`
- `MANUAL(3): reserved for future operator override; current precedence follows SourceType.priority().`
- `EVENT/MARKET both=2` 표현 제거 (EVENT=1, MARKET=2, MANUAL=3)

### ❷ `tests/services/test_universe_selection.py:461-467`
Comment block 수정.

**변경사항**:
- `HELD_POSITION(0) > MANUAL(1) > EVENT_OVERLAY(2) >= MARKET_OVERLAY(2) > CORE(3)`
- `Equal priority (EVENT/MARKET both=2)`

→
- `HELD_POSITION(0) > EVENT_OVERLAY(1) > MARKET_OVERLAY(2) > MANUAL(3) > CORE(4)`
- `MANUAL: reserved for future use; current precedence follows SourceType.priority().`
- `First-writer wins on equal priority (lower number = higher priority).`

### ❸ `plans/p2_backend_bugfix_plan.md:472-478`
❶과 동일한 docstring copy 수정.

### ❹ `plans/[DESIGN] universe_selection_service.md:277`
Priority 주석 값 보정.

**변경사항**:
- `0=held, 1=event, 2=market, 3=core` (MANUAL 누락, CORE=3)
→
- `0=held, 1=event, 2=market, 3=manual, 4=core`

## 검증
1. `python3 -m pytest -q tests/services/test_universe_selection.py tests/scripts/test_run_paper_decision_loop.py`
   → 76 passed, 0 warnings
2. `rg`로 stale priority description 잔류 확인
3. Docker 재빌드/재기동 및 `curl -f http://localhost:8000/health`
