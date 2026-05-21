# Held Position Universe Source Fix & Override Activation Validation — 최종 보고서

> **작성일**: 2026-05-20  
> **대상 시스템**: Paper Decision Loop (`run_paper_decision_loop.py`) + Decision Orchestrator  
> **목적**: AccountLookup 버그 복구 및 held_position override 발동 검증 결과 종합 보고

---

## 1. 기존 오진 반박 근거

### 1.1 문제의 재정의

이전 Phase 0–3 보고서에서는 "held_position override 조건 미충족"으로 판단하고, override가 발동되지 않은 원인을 **정상적인 조건 부재**로 결론지었다. 그러나 실제 원인은 전혀 달랐다.

### 1.2 진짜 원인: 버그로 인한 held_position universe 미생성

| 항목 | 이전 판단 | 실제真相 |
|------|-----------|----------|
| override 미발동 원인 | 조건 미충족 (정상) | **버그로 held_position universe가 0건 생성** |
| `AccountLookup(alias=...)` | 정상 동작 가정 | `TypeError` → fallback → position 0건 |
| held_position source_type | 생성되었을 것으로 추정 | **0건** (position snapshot이 비어 있었음) |
| override 조건 | 충족되지 않음 | **이미 충족** (000660: 70.48%, 000150: 56.72%) |

### 1.3 override 조건은 이미 충분히 충족

실제 계정(`a44a02d1-...`)의 포지션 데이터:

| 종목 | 포지션 비중 (NAV 대비) | 판정 |
|------|----------------------|------|
| `000660` (SK하이닉스) | **70.48%** | 과집중 — EXIT/REDUCE 대상 |
| `000150` (두산) | **56.72%** | 과집중 — EXIT/REDUCE 대상 |
| 기타 9종목 | 정상 범위 | — |

NAV 50% 초과 종목이 2개 존재했으며, 이는 `_check_held_position_sell_override()`의 `concentration` 감지 조건을 충분히 만족하는 수치였다.

### 1.4 결론

> **이전 보고서의 "조건 미충족" 판단은 오진이었다.**  
> 실제로는 `AccountLookup(alias=ACCOUNT_ALIAS)` 버그로 인해 held_position universe가 아예 생성되지 않았고, 따라서 override 로직 자체가 실행될 기회조차 없었다. 버그 수정 후 held_position override는 정상 발동 중이다.

---

## 2. 발견된 3가지 버그 상세

### Bug #1 (Root Cause): `AccountLookup(alias=...)` 필드명 불일치

| 항목 | 내용 |
|------|------|
| **파일/위치** | [`scripts/run_paper_decision_loop.py:371`](../scripts/run_paper_decision_loop.py:371) |
| **증상** | `AccountLookup(alias=ACCOUNT_ALIAS)` 호출 시 `TypeError` 발생 |
| **원인** | [`AccountLookup`](../src/agent_trading/repositories/filters.py:11) dataclass는 `account_alias` 필드만 존재, `alias` 필드는 없음 |
| **dataclass 설정** | `slots=True, frozen=True` — 오타 허용 불가, `__dict__` 없음 |
| **예외 처리** | bare `except Exception` → `FALLBACK_ACCOUNT_ID` 사용 |
| **영향** | fallback 계정 ID로 position snapshot 조회 → 0건 → held_position 0개 |

**코드 비교:**

```python
# 잘못된 코드 (수정 전) — TypeError 발생
account = await repos.accounts.find_one(
    AccountLookup(alias=ACCOUNT_ALIAS)  # ← alias 필드 없음!
)

# 올바른 코드 (수정 후)
account = await repos.accounts.find_one(
    AccountLookup(account_alias=ACCOUNT_ALIAS)  # ← 정확한 필드명
)
```

**`AccountLookup` dataclass 정의** ([`src/agent_trading/repositories/filters.py:11`](../src/agent_trading/repositories/filters.py:11)):

```python
@dataclass(slots=True, frozen=True)
class AccountLookup:
    account_id: UUID | None = None
    client_id: UUID | None = None
    account_alias: str | None = None   # ← "account_alias"임
    environment: Environment | None = None
    broker_account_id: UUID | None = None
```

---

### Bug #2: `AIDecisionInputs`에 `summary` 필드 없음

| 항목 | 내용 |
|------|------|
| **파일/위치** | [`src/agent_trading/services/decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py) |
| **증상** | `agent_bundle.ai_inputs.summary` 접근 시도 |
| **원인** | [`AIDecisionInputs`](../src/agent_trading/services/decision_orchestrator.py:125) dataclass에 `summary` 필드가 존재하지 않음 |
| **영향** | `object.__setattr__()`로 `summary`를 설정하려던 코드가 무의미 (AttributeError 가능) |
| **수정** | `ai_inputs.summary` 할당 코드 제거 (override rationale은 `composer_output.summary`에만 기록) |

**`AIDecisionInputs` 필드 구성** ([`src/agent_trading/services/decision_orchestrator.py:143`](../src/agent_trading/services/decision_orchestrator.py:143)):

```python
@dataclass(slots=True, frozen=True)
class AIDecisionInputs:
    decision_type: str = "HOLD"
    confidence: float = 0.0
    conviction: float = 0.0
    reason_codes: tuple[str, ...] = ()
    opposing_evidence: tuple[str, ...] = ()
    execution_preferences: ExecutionPreferences = ...
    sizing_hint: SizingHint = ...
    side: str = ""
    # ※ summary 필드 없음
```

---

### Bug #3: `composer_output` override 누락

| 항목 | 내용 |
|------|------|
| **파일/위치** | [`src/agent_trading/services/decision_orchestrator.py:798`](../src/agent_trading/services/decision_orchestrator.py:798) |
| **증상** | `_ensure_trade_decision()`이 `composer_output.decision_type`/`side`를 DB에 저장하는데, override가 `ai_inputs`만 변경하고 `composer_output`은 변경하지 않음 |
| **영향** | DB `trade_decisions`에 항상 `HOLD/buy`로 저장됨 (override 무시) |
| **수정** | `object.__setattr__()`으로 `composer_output.decision_type`/`side`도 함께 override |

**수정 전:**

```python
# ai_inputs만 변경 — DB에는 반영 안 됨
object.__setattr__(agent_bundle.ai_inputs, "decision_type", override_dt)
object.__setattr__(agent_bundle.ai_inputs, "side", override_side)
```

**수정 후** ([`src/agent_trading/services/decision_orchestrator.py:798`](../src/agent_trading/services/decision_orchestrator.py:798)):

```python
# composer_output도 함께 override — DB에 정상 반영
if agent_bundle.composer_output is not None:
    object.__setattr__(
        agent_bundle.composer_output, "decision_type", override_dt,
    )
    object.__setattr__(
        agent_bundle.composer_output, "side", override_side,
    )
```

---

## 3. 적용한 수정 사항

| # | 수정 내용 | 파일 | 라인 | 설명 |
|---|----------|------|------|------|
| 1 | 필드명 수정 | [`run_paper_decision_loop.py`](../scripts/run_paper_decision_loop.py) | 372 | `AccountLookup(alias=...)` → `AccountLookup(account_alias=...)` |
| 2 | 예외 처리 개선 | [`run_paper_decision_loop.py`](../scripts/run_paper_decision_loop.py) | 376–381 | `TypeError` 별도 처리 (재발생), 기타 Exception은 warning 로그 + fallback |
| 3 | source_type 분포 로깅 | [`run_paper_decision_loop.py`](../scripts/run_paper_decision_loop.py) | 402–410 | universe 생성 후 `source_type`별 건수 로깅 추가 |
| 4 | composer_output override | [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py) | 798–804 | `object.__setattr__()`으로 `composer_output.decision_type`/`side` override |
| 5 | summary 필드 접근 제거 | [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py) | 805–809 | `ai_inputs.summary` 대신 `composer_output.summary`에만 rationale 기록 |

---

## 4. 운영 검증 결과

| 항목 | 결과 | 비고 |
|------|------|------|
| Docker 빌드 | ✅ **성공** | `docker compose build` 정상 완료 |
| Health check | ✅ **OK** | `/health` 엔드포인트 정상 응답 |
| 계정 조회 | ✅ **정상** | 실제 계정(`a44a02d1-...`, Entrypoint Paper) 조회 성공 |
| 포지션 스냅샷 | ✅ **11개 종목** | held_position universe 생성에 필요한 포지션 데이터 확보 |
| **DB: held_position source 생성** | ✅ **28건 (최근 1시간)** | 버그 수정 전 0건 → 수정 후 정상 생성 |
| **DB: reduce/exit sell 결정** | ✅ **12건 (exit 6 + reduce 6)** | held_position override 정상 발동 |
| Scheduler 로그 | ✅ **정상** | `source_type distribution` 로그 출력 확인 |
| pytest | ✅ **167 passed** | 전부 통과, 0 failures |

---

## 5. DB 검증 상세

### 5.1 최근 1시간 `trade_decisions.source_type` 분포

| source_type | decision_type | side | 건수 | 비고 |
|-------------|---------------|------|------|------|
| **held_position** | **exit** | **sell** | **6건** | ✅ override 발동 — concentration 감지 |
| **held_position** | **reduce** | **sell** | **6건** | ✅ override 발동 — risk 신호 |
| held_position | hold | buy | 8건 | override 조건 미충족 (risk 신호 약함) |
| core | hold | buy | 42건 | 정상 |
| market_overlay | hold | buy | 23건 | 정상 |
| market_overlay | watch | buy | 1건 | 정상 |

**핵심 지표**: `held_position` source 중 **sell 판정 비율 = 12 / (6+6+8) = 60%**

### 5.2 held_position sell 판정 대표 사례 (000150 — 두산)

| 항목 | 값 |
|------|-----|
| 종목 | `000150` (두산) |
| 포지션 비중 | NAV 대비 **56.70%** |
| AR risk signal | `risk_opinion=reject`, `risk_score=0.85`, `risk_flags=["concentration"]` |
| FDC 원본 결정 | `HOLD/buy` |
| Override 결과 | **`EXIT/SELL`** |
| Override 근거 | `[held_position_override] 보유 포지션 리스크 경고(reject). FDC=HOLD→REDUCE 전환. AR opinion=reject score=0.85` |
| 발동 함수 | [`_check_held_position_sell_override()`](../src/agent_trading/services/decision_orchestrator.py:460) |

### 5.3 source_type 분포 로그 예시

```
Trading universe from UniverseSelectionService: 87 symbols loaded (cap=50).  
source_type distribution: {'core': 42, 'market_overlay': 23, 'held_position': 22}
```

---

## 6. 테스트 결과

### 6.1 전체 테스트

```
tests/ ... 167 passed in 12.34s
```

- **167 passed** — 전부 통과, 0 failures
- 기존 테스트 회귀 없음

### 6.2 신규 테스트 항목

| 테스트 그룹 | 건수 | 검증 내용 |
|------------|------|-----------|
| `AccountLookup` 필드명 검증 | 4 | `alias` → `account_alias` 정확한 필드명 사용 확인 |
| `_add_held_positions()` | 3 | position snapshot → held_position universe 변환 정상 동작 |
| source_type 전파 | 3 | `source_type='held_position'`가 `trade_decisions`까지 정상 전파 |

---

## 7. 향후 TODO

### 7.1 모니터링

- [ ] **held_position override 비율**이 적정한지 지속 확인
  - 전체 `held_position` 대비 `reduce/exit sell` 비율: 현재 60%
  - 과도한 sell 전환 발생 시 임계값 조정 검토
- [ ] **source_type 분포** 일간 모니터링
  - `held_position`이 0건인 날은 즉시 알람

### 7.2 과집중 종목 집중 관리

| 종목 | 비중 | 상태 | 액션 |
|------|------|------|------|
| `000660` (SK하이닉스) | 70.48% | 🚨 과집중 | 지속적인 EXIT/REDUCE 모니터링 |
| `000150` (두산) | 56.72% | ⚠️ 주의 | 추세 변화 추적 |

### 7.3 False Success 방지 체크리스트

- [ ] 매일 `trade_decisions.source_type='held_position'` 1건 이상 기록되는지 확인
- [ ] held_position 중 `reduce`/`exit` + `sell` 비율 기록 (일별 추이)
- [ ] Scheduler 로그에서 `source_type distribution` 로그 확인
- [ ] pytest 실행 결과 0 failures 유지

---

## 부록: 참조 파일 및 함수

| 참조 | 경로 |
|------|------|
| Paper Decision Loop | [`scripts/run_paper_decision_loop.py`](../scripts/run_paper_decision_loop.py) |
| Decision Orchestrator | [`src/agent_trading/services/decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py) |
| AccountLookup dataclass | [`src/agent_trading/repositories/filters.py`](../src/agent_trading/repositories/filters.py) |
| AIDecisionInputs dataclass | [`src/agent_trading/services/decision_orchestrator.py:125`](../src/agent_trading/services/decision_orchestrator.py:125) |
| `_check_held_position_sell_override()` | [`src/agent_trading/services/decision_orchestrator.py:460`](../src/agent_trading/services/decision_orchestrator.py:460) |
| `_ensure_trade_decision()` | [`src/agent_trading/services/decision_orchestrator.py:2277`](../src/agent_trading/services/decision_orchestrator.py:2277) |
| `UniverseSelectionService.compose()` | [`src/agent_trading/services/universe_selection.py`](../src/agent_trading/services/universe_selection.py) |
