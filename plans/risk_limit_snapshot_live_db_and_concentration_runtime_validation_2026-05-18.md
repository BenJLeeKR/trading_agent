# 보고서: risk_limit_snapshot_live_db_and_concentration_runtime_validation_2026-05-18.md

## 배경

Phase Z에서 `RiskLimitSnapshotEntity` 생성·저장 파이프라인을 복구했으나 실운영 검증이 필요했습니다. 본 Phase AA는 실DB 생성 여부와 concentration constraint 실운영 발동 여부를 검증하고, 미해결 문제에 대한 fallback을 적용한 최종 보고서입니다.

---

## 검증 결과

### 1. risk_limit_snapshots DB 생성 여부 → **0건** ❌

- Phase Z 코드 복구 후에도 `risk_limit_snapshots` 테이블에 0건
- **원인**: Cash sync 실패 (03:28 이후 3회 연속 `cash_synced_count=0`)
  - KIS API cash balance sync 실패 → `cash_balance=None` → `RiskLimitSnapshotEntity` 생성 조건 미충족 (`cash_balance is not None and cash_balance.total_asset is not None`)
- **2차 영향**: `STALE_SNAPSHOT_ACCOUNT` guardrail로 인해 모든 decision 차단

### 2. decision_contexts — risk_limit_snapshot_id 컬럼 없음

- `decision_contexts` 테이블에 `risk_limit_snapshot_id` 컬럼이 아예 존재하지 않음
- 즉, `AssembledContext.risk_limit_snapshot`은 항상 `None`
- → `nav=None` → concentration constraint bypass (early return)

### 3. Cash sync 실패 상세

- 05-18 03:28: 마지막 성공적 cash sync
- 이후 3회 연속 `cash_synced_count=0`
- 정확한 원인: KIS API 문제 (장외 시간 또는 rate limit)로 추가 진단 필요

### 4. 000150 (두산) 사례

- Position value: 약 63M
- Total asset (마지막 성공 시점): 29.6M
- **Concentration ratio: 213%**
- 그러나 `nav=None`으로 인해 concentration constraint 미발동
- 모든 decision: `approve/buy` — REDUCE/SELL 미생성

---

## 적용된 Fallback 수정

### File: [`src/agent_trading/services/decision_orchestrator.py:1178`](../src/agent_trading/services/decision_orchestrator.py:1178)

`_build_sizing_inputs()`에 NAV fallback 추가:

```python
nav = ctx.risk_limit_snapshot.nav if ctx.risk_limit_snapshot else None
# Fallback: risk_limit_snapshot이 없으면 cash_balance_snapshot.total_asset을 NAV로 사용
if nav is None and ctx.cash_balance_snapshot is not None and ctx.cash_balance_snapshot.total_asset is not None:
    nav = ctx.cash_balance_snapshot.total_asset
    logger.warning(
        "risk_limit_snapshot not available; using cash_balance_snapshot.total_asset as NAV fallback. "
        "account_id=%s nav=%s",
        ctx.cash_balance_snapshot.account_id, nav,
    )
```

### NAV 우선순위 (fallback chain)

```
priority 1: ctx.risk_limit_snapshot.nav (if risk_limit_snapshot exists and nav is not None)
priority 2: ctx.cash_balance_snapshot.total_asset (fallback, with WARNING log)
priority 3: None (no fallback → concentration constraint bypass)
```

### Test: [`tests/services/test_sizing_engine.py`](../tests/services/test_sizing_engine.py) — `TestNavFallbackFromCashBalance`

- `test_nav_fallback_from_cash_balance` 1개 추가
- Mock context: `risk_limit_snapshot=None`, `cash_balance_snapshot.total_asset=50000000`
- Assert: `inputs.nav == Decimal("50000000")`

### pytest 결과: 46 passed ✅ (기존 45 + 신규 1)

---

## 최종 판정

### C. 미해결 → **B. 부분 해결** (fallback 적용 후)

| 기준 | 상태 | 설명 |
|------|------|------|
| risk_limit_snapshots DB 생성 | ❌ | 0건 — cash sync 실패 |
| risk_limit_snapshot.nav 주입 | ❌ | DB에 row 없음 |
| cash_balance_snapshot.total_asset fallback | ✅ | 코드 적용, 테스트 통과, Docker 반영 |
| concentration constraint 발동 | ⚠️ | cash_balance_snapshot이 stale해도 마지막 값 사용 가능 |
| Docker 반영 | ✅ | 빌드/재기동/health 정상 |

### 남은 follow-up

1. **Cash sync failure root cause 진단 필요** (KIS API 문제 — 장외 시간 또는 rate limit)
2. **cash_balance_snapshot stale guardrail** (`STALE_SNAPSHOT_ACCOUNT`) — cash sync 실패 시 모든 decision 차단. Fallback이 있어도 cash_balance_snapshot이 None이면 소용없음
3. **decision_contexts에 risk_limit_snapshot_id 컬럼 추가** — 장기적으로 필요
4. **AR/FDC prompt에 concentration ratio 전달** — Phase Z 이후 다음 단계 (Phase Y 진단의 layer 2)

---

## 변경 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/services/decision_orchestrator.py:1178`](../src/agent_trading/services/decision_orchestrator.py:1178) | `_build_sizing_inputs()` NAV fallback from `cash_balance_snapshot.total_asset` |
| [`tests/services/test_sizing_engine.py`](../tests/services/test_sizing_engine.py) | `TestNavFallbackFromCashBalance` 클래스 + 1개 테스트 |

---

## Appendix: 관련 이전 보고서

- Phase Y: [`plans/overweight_position_auto_reduce_and_nav_cash_input_diagnosis_2026-05-18.md`](overweight_position_auto_reduce_and_nav_cash_input_diagnosis_2026-05-18.md) — 3-layered root cause 진단 (⚠️ 파일 미존재 — Phase Y 작성 필요)
- Phase Z: [`plans/risk_limit_snapshot_nav_recovery_and_live_concentration_enablement_2026-05-18.md`](risk_limit_snapshot_nav_recovery_and_live_concentration_enablement_2026-05-18.md) — `RiskLimitSnapshotEntity` pipeline 복구

---

**참고**: 이 보고서는 `plans/` 디렉토리에 저장되어야 합니다. 한국어로 작성하되 코드 식별자/파일명/CLI 명령어는 영어로 유지해주세요. attempt_completion으로 완료 보고 시 파일 경로와 간략한 요약을 제공해주세요.
