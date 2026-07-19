# Final Refactoring Cleanup — 리팩토링 최종 마감 계획 (수정)

**목표**: Phase 5 리팩토링 이후 남은 "필수 마감" 작업을 정리하여 "핵심 공사 완료" 상태를 "실질적 마감 완료" 상태로 전환한다.

**적용 기준**: 최근 compatibility 회귀를 고려, DecisionOrchestrator thin wrapper는 보류. 나머지 3개 항목만 진행.

---

## Q1-Q4 요약

### Q1. 이번 턴 진행 항목 (3개)

| # | 항목 | 위험도 | 파일 |
|---|------|--------|------|
| 1 | Module-level 상수 중복 통합 | 낮음 | `decision_orchestrator.py`, `execution_service.py` |
| 2 | `SubmitResult.intent` alias 제거 | 낮음 | `common_types.py` + 3개 테스트 |
| 3 | `scripts/run_agent_subprocess.py` stale import 수정 | 낮음 | `run_agent_subprocess.py` |

### Q2. 보류 항목 (1개)

| 항목 | 사유 |
|------|------|
| DecisionOrchestrator 4 thin wrapper 제거 | 최근 compatibility 회귀 발생 경험 있음 → risk 최소화를 위해 보류 |

---

## SubTask 상세

### SubTask 1: Module-level 상수 통합

**파일**: `src/agent_trading/services/decision_orchestrator.py`, `src/agent_trading/services/execution_service.py`

**변경**: 
- `decision_orchestrator.py`에서 중복 상수 4개 삭제:
  - `_PHASE55_SYNC_TIMEOUT` (line 101)
  - `_CIRCUIT_BREAKER_THRESHOLD` (line 120)
  - `_CIRCUIT_BREAKER_COOLDOWN` (line 121)
  - `_QUOTE_CACHE_TTL` (line 122)
- `execution_service.py`를 canonical source로 유지
- `decision_orchestrator.py`에서 `from agent_trading.services.execution_service import (...)`로 import

### SubTask 2: `SubmitResult.intent` alias 제거

**파일**: `src/agent_trading/services/common_types.py` + 테스트 3개

**변경**:
1. `common_types.py`:
   - `intent: OrderIntent | None = None` 필드 제거 (line 212)
   - `order: object | None = None` 필드 제거 (line 213, 함께 alias)
   - `build()` 메서드에서 `intent` 관련 로직 제거 (line 239-240, 254)
   - docstring 업데이트

2. **테스트 파일 3개**에서 `.intent` → `.order_intent` 변경:
   - `tests/services/test_safe_order_path_e2e.py` — 6건
   - `tests/services/test_decision_submit_pipeline.py` — 8건
   - `tests/services/test_paper_trading_scenarios.py` — 4건

### SubTask 3: `scripts/run_agent_subprocess.py` stale import 수정

**파일**: `scripts/run_agent_subprocess.py`

**변경**:
- `_dataclass_to_dict` → `dataclass_to_dict` (common_types에서 import)
- `_is_missing_agent_symbol` → `is_missing_agent_symbol` (translation에서 import)
- `_normalize_decision_type` → `normalize_decision_type` (translation에서 import)
- 사용부 4곳 이름 변경 (lines 602, 620, 675, 680)

### SubTask 4: pytest 검증

```bash
python3 -m pytest tests/ -x -q --tb=short 2>&1 | tail -30
```

### SubTask 5: 잔여 pre-existing issue 문서화

---

## 완료 기준

1. ✅ Module-level 상수 중복 0개
2. ✅ `SubmitResult.intent` alias 제거 완료
3. ✅ `scripts/run_agent_subprocess.py` stale import 수정 완료
4. ✅ pytest 전 구간 통과
5. ✅ Pre-existing issue 문서화 완료

---

## 제약 조건

- `python3`만 사용
- `/bin/bash` 기준
- `.env` 수정 금지
- 실행은 반드시 하위 Task로 분할 (Webview 에러 방지)
