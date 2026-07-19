# EI Summary 저장 개선 + Held Position Sell 판단 경로 보강 — 보고서

> **작성일**: 2026-05-20 13:20 KST  
> **관련 PR/작업**: Task 1 (EI summary), Task 2 (Held position sell override)

---

## 1. EI Summary 생성 방식

### 1.1 문제
`EventInterpretationOutput`에 top-level `summary` 필드가 없어, `AgentRuns` 화면에서 EI의 summary가 빈 문자열로 표시됨.

### 1.2 해결
- [`EventInterpretationOutput`](src/agent_trading/services/ai_agents/schemas.py:278)에 `summary: str = ""` 필드 추가
- [`_build_ei_summary()`](src/agent_trading/services/ai_agents/event_interpretation.py:44) 함수 구현 — `aggregate_view`와 `events`만으로 deterministic 한국어 요약 생성
  - `no_material_events=True` → `"유의미한 신규 이벤트 없음. 전반 {bias}."`
  - 이벤트 있음 → `"({count}건) {대표이벤트 preview}, 전반 {bias}, 근거:{strength}"`

### 1.3 중요 원칙
- **추가 LLM 호출 없음** — 기존 출력만 재조합
- `StubEventInterpretationAgent`도 동일한 함수 사용

### 1.4 생성 예시
| 조건 | 출력 |
|------|------|
| 이벤트 없음, 중립 | `"유의미한 신규 이벤트 없음. 전반 중립."` |
| 이벤트 1건, 긍정, 근거 moderate | `"(1건) 매출이 전년 대비 15% 증가했습니다, 전반 긍정, 근거:moderate"` |
| 이벤트 없음, 부정 | `"유의미한 신규 이벤트 없음. 전반 부정적."` |

---

## 2. Held Position Sell 판단 보강 방식

### 2.1 문제
실제 보유 종목이 여러 개 있지만, `trade_decisions`가 대부분 `HOLD/buy`로 남고 `REDUCE/EXIT sell`이 거의 나오지 않음. 
FDC가 `source_type=held_position`에 대해 "need clear signal" 정책으로 보수적 판단을 하는 것이 원인.

### 2.2 해결
- [`_check_held_position_sell_override()`](src/agent_trading/services/decision_orchestrator.py:459) 메서드 추가
- `assemble()` 메서드에서 agent 실행 후, recording 후, `_ensure_trade_decision()` 전에 override 체크

### 2.3 Override 조건
```
source_type == "held_position"
  AND ar_output is not None AND fdc_output is not None
  AND fdc_output.decision_type NOT IN ("REDUCE", "EXIT")
  AND (
    ar_output.risk_opinion IN ("reject", "reduce")
    OR (ar_output.risk_opinion == "review" AND ar_output.risk_score >= 0.6)
    OR ar_output.risk_score >= 0.8
  )
```

### 2.4 보호 장치
1. `source_type != "held_position"` → 즉시 None 반환 (buy 경로 보존)
2. FDC가 이미 REDUCE/EXIT → 이중 override 방지
3. `risk_flags`에 concentration 관련 → EXIT, 기본 → REDUCE
4. override 시 rationale에 근거 상세 기록

---

## 3. 변경 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/services/ai_agents/schemas.py`](src/agent_trading/services/ai_agents/schemas.py) | `EventInterpretationOutput`에 `summary` 필드 추가 |
| [`src/agent_trading/services/ai_agents/event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py) | `_build_ei_summary()` 함수 추가, `run()`에서 summary 생성 |
| [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `_check_held_position_sell_override()` 메서드 추가, `assemble()`에 override 로직 삽입 |
| [`tests/services/ai_agents/test_event_interpretation.py`](tests/services/ai_agents/test_event_interpretation.py) | `_build_ei_summary()` 테스트 8개 (신규) |
| [`tests/services/test_held_position_sell_override.py`](tests/services/test_held_position_sell_override.py) | `_check_held_position_sell_override()` 테스트 13개 (신규) |

---

## 4. 테스트 결과

| 테스트 파일 | 통과 | 설명 |
|-----------|------|------|
| `tests/services/ai_agents/test_event_interpretation.py` | 8/8 | `_build_ei_summary()` — no_material, bias별, 이벤트 포함, stub |
| `tests/services/test_held_position_sell_override.py` | 13/13 | 모든 override 조건/보호 장치 |
| `tests/services/test_decision_orchestrator.py` | 40/40 | 기존 회귀 없음 |
| **합계** | **61/61** | |

---

## 5. 운영 검증 결과

### 5.1 EI summary 저장 확인
```sql
SELECT agent_type, structured_output_json->>'summary' AS summary
FROM trading.agent_runs
WHERE agent_type = 'event_interpretation'
  AND structured_output_json->>'summary' != ''
ORDER BY created_at DESC LIMIT 5;
```

결과: ✅ 5개 레코드 모두 summary 정상 저장
- `"유의미한 신규 이벤트 없음. 전반 중립."`

### 5.2 Trade decisions 확인
```sql
SELECT symbol, decision_type, side, source_type, rationale
FROM trading.trade_decisions
ORDER BY created_at DESC LIMIT 5;
```

결과: ✅ `REDUCE sell` 판단 포함
- `000150` — REDUCE sell, 포지션 집중도 62.4%로 축소 판단

### 5.3 Scheduler 로그
- `strftime`/`fallback`/`AttributeError` 에러 없음
- Health check 정상 (`status: ok`)
- pre-market → intraday phase 정상 진행

### 5.4 Docker 배포
- 새 이미지 `agent_trading-app:latest` 정상 빌드
- 컨테이너 내부 코드 검증: `summary` 필드 ✅, `_check_held_position_sell_override` ✅, `_build_ei_summary` ✅

---

## 6. Follow-up 항목

| 우선순위 | 항목 | 설명 |
|---------|------|------|
| P1 | FDC prompt 개선 | `held_position` + risk 신호 시 REDUCE/EXIT을 더 적극적으로 고려하도록 prompt 강화 |
| P2 | Source type 바이어스 분석 | 현재 `held_position`의 "need clear signal" 정책이 실제로 어느 정도 bias를 만드는지 측정 |
| P3 | 포지션 집중도 metric | `_check_held_position_sell_override()`가 concentration `risk_flags`에 의존하는데, deterministic concentration 계산을 추가 검토 |
| P4 | UI 개선 | `AgentRunDetailPanel`에서 EI summary 표시 방식 개선 (현재는 formatEiOutput 기반 2순위) |
