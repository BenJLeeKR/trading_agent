# AR agent_runs `orderable_amount` 기준 판단 적용 검증 보고서

**작성일**: 2026-05-21 20:28 KST  
**분석 대상**: Docker PostgreSQL `agent_runs` (agent_type = `ai_risk`)  
**수정 반영 시점**: 2026-05-21 02:18 UTC (11:18 KST)  
**조회 범위**: 2026-05-21 02:18 UTC ~ 06:33 UTC (11:18 KST ~ 15:33 KST)  
**캐시 스냅샷 기준**: 2026-05-21 06:26:06 UTC (15:26 KST)

---

## 1. 프롬프트 변경 내용 확인

[`src/agent_trading/services/ai_agents/ai_risk.py:369-388`](../src/agent_trading/services/ai_agents/ai_risk.py:369)에 Cash Judgment Guide가 추가됨:

```python
# === Cash balance snapshot summary (if available) ===
cash = context.cash_balance_snapshot
if cash is not None:
    lines.append("")
    lines.append("=== Cash Balance ===")
    lines.append(f"  Available cash (deposit total, reference): {cash.available_cash}")
    lines.append(f"  Currency: {cash.currency}")
    if cash.orderable_amount is not None:
        lines.append(f"  Orderable amount (actual buyable cash): {cash.orderable_amount}")
    if cash.settled_cash is not None:
        lines.append(f"  Settled cash: {cash.settled_cash}")
    if cash.unsettled_cash is not None:
        lines.append(f"  Unsettled cash: {cash.unsettled_cash}")
    lines.append("")
    lines.append("  【Cash Judgment Guide】")
    lines.append("  - BUY feasibility / cash availability: Use 'Orderable amount' as primary criterion")
    lines.append("  - 'Available cash' is the total deposit (D+2 settlement basis), accounting reference only")
    lines.append("  - Do NOT conclude 'cannot buy' solely because 'Available cash' is negative")
    lines.append("  - Always base BUY feasibility judgment on 'Orderable amount'")
```

---

## 2. DB 조회 결과

### Cash Balance Snapshot (모든 AR run이 동일한 snapshot 참조)

| 항목 | 값 |
|------|------|
| `cash_balance_snapshot_id` | `cd3bd9e5-2fcd-4628-96f3-e5bd68271e16` |
| `available_cash` | **-6,629,580 원** (음수) |
| `orderable_amount` | **+9,050,070 원** (양수) |
| `settled_cash` | -2,794,295 원 |
| `snapshot_at` | 2026-05-21 06:26:06 UTC |

> **핵심**: `available_cash`는 **-6,629,580원**으로 음수이지만, `orderable_amount`는 **+9,050,070원**으로 양수입니다.
> 즉, 실제 매수 가능 금액은 9,050,070원이 존재하는 상황입니다.

---

## 3. Representative AR Runs 비교표

| # | Symbol | created_at (KST) | available_cash | orderable_amount | AR risk_opinion | AR summary 핵심 문구 | 판정 |
|---|--------|-----------------|---------------|----------------|----------------|--------------------|------|
| 1 | 001680 | 15:33:41 | -6,629,580 | **+9,050,070** | reject | "사용 가능한 현금이 -6,629,580원으로 부족하여 매수 주문이 불가능합니다" | ❌ |
| 2 | 001230 | 15:33:37 | -6,629,580 | **+9,050,070** | reject | "계좌의 현금 잔고가 음수이기 때문에 추가 매수 주문은 실행 불가능합니다" | ❌ |
| 3 | 001440 | 15:33:36 | -6,629,580 | **+9,050,070** | reject | "계좌 현금 잔고가 심각한 마이너스 상태이므로 실행 불가능" | ❌ |
| 4 | 001040 | 15:33:34 | -6,629,580 | **+9,050,070** | review | "계좌의 가용 현금이 -6,629,580원으로 음수이며 정산금도 -2,794,295원입니다" | ❌ |
| 5 | 000990 | 15:32:20 | -6,629,580 | **+9,050,070** | reject | "계좌의 현금 잔고가 심각한 마이너스 상태이므로 신규 매수 거래는 거부" | ❌ |
| 6 | 000100 | 15:32:05 | -6,629,580 | **+9,050,070** | reject | "계좌 현금 잔고가 -6,629,580원으로 결제 가능 자금이 부족합니다" | ❌ |
| 7 | 000210 | 15:32:00 | -6,629,580 | **+9,050,070** | reject | "현재 계좌 가용 현금이 -6,629,580원으로 부족하고" | ❌ |
| 8 | 000670 | 15:31:19 | -6,629,580 | **+9,050,070** | reject | "현금 잔고가 -6,629,580원으로 마이너스 상태여서 추가 자금이 없습니다" | ❌ |
| 9 | 000660 | 15:31:04 | -6,629,580 | **+9,050,070** | review | "현금 잔고가 마이너스로 매수 주문을 실행할 경우 추가적인 현금 부족을 초래" | ❌ |
| 10 | 000880 | 15:30:59 | -6,629,580 | **+9,050,070** | reject | "계좌에 사용 가능한 현금이 음수 상태이며, 추가 매수 시 레버리지가 증가" | ❌ |

> ✅ = 개선됨 (orderable_amount 우선 참조)
> ⚠️ = 부분 개선
> ❌ = 미개선 (여전히 available_cash 음수만으로 판단)

---

## 4. 상세 분석

### 4.1 모든 AR run의 공통 패턴

**Cash Balance 섹션에 `orderable_amount`가 프롬프트로 제공되었음에도 불구하고**, 모든 AR run이 `available_cash`의 음수 값(-6,629,580원)만을 근거로 "현금 부족 → reject" 판단을 내렸습니다.

**어떤 AR run도 `orderable_amount`(+9,050,070원)를 언급하거나 참조하지 않았습니다.**

### 4.2 run별 인용 분석

#### Run 1: 001680 (agent_run_id: 66ed4562)
- **summary**: "사용 가능한 현금이 -6,629,580원으로 부족하여 매수 주문이 불가능합니다"
- **opposing_evidence**: "계좌에 사용 가능한 현금이 음수(-6,629,580원)이므로 매수 주문을 집행할 수 없습니다."
- **판단 근거**: `available_cash` 음수만 참조. `orderable_amount` 미언급.

#### Run 2: 001230 (agent_run_id: 1e36d247)
- **summary**: "계좌의 현금 잔고가 음수이기 때문에 추가 매수 주문은 실행 불가능합니다"
- **opposing_evidence**: "계좌 가용 현금이 -6,629,580원으로 음수입니다."
- **판단 근거**: `available_cash` 음수만 참조. `orderable_amount` 미언급.

#### Run 3: 001440 (agent_run_id: d0f6a715)
- **summary**: "계좌 현금 잔고가 심각한 마이너스 상태이므로 실행 불가능하며 리스크가 매우 높습니다"
- **opposing_evidence**: "계좌 가용 현금이 -6,629,580 KRW로 매수 자금 부족"
- **판단 근거**: `available_cash` 음수만 참조. `orderable_amount` 미언급.

#### Run 4: 001040 (agent_run_id: 2652aaad)
- **summary**: "계좌의 가용 현금이 -6,629,580원으로 음수이며 정산금도 -2,794,295원입니다"
- **risk_opinion**: review (다른 run들과 달리 review)
- **판단 근거**: `available_cash`와 `settled_cash` 모두 음수임을 근거로 review. `orderable_amount` 미언급.

#### Run 5: 000990 (agent_run_id: 88b7b119)
- **summary**: "계좌의 현금 잔고가 심각한 마이너스 상태이므로 신규 매수 거래는 거부되어야 합니다"
- **opposing_evidence**: "사용 가능 현금이 -6,629,580 KRW로 크게 마이너스입니다."
- **판단 근거**: `available_cash` 음수만 참조. `orderable_amount` 미언급.

#### Run 6: 000100 (agent_run_id: 9834c4b5)
- **summary**: "계좌 현금 잔고가 -6,629,580원으로 결제 가능 자금이 부족합니다"
- **opposing_evidence**: "계좌 현금 잔고가 -6,629,580원으로 결제 가능 자금이 부족합니다."
- **판단 근거**: `available_cash` 음수만 참조. `orderable_amount` 미언급.

#### Run 7: 000210 (agent_run_id: 843fe4b0)
- **summary**: "현재 계좌 가용 현금이 -6,629,580원으로 부족하고 보유 포지션이 없어 신규 매수는 자금 부담을 가중시킵니다"
- **판단 근거**: `available_cash` 음수만 참조. `orderable_amount` 미언급.

#### Run 8: 000670 (agent_run_id: 26de8294)
- **summary**: "현금 잔고가 -6,629,580원으로 마이너스 상태여서 추가 자금이 없습니다"
- **opposing_evidence**: "현금 잔고가 -6,629,580원으로 마이너스 상태여서 추가 자금이 없습니다."
- **판단 근거**: `available_cash` 음수만 참조. `orderable_amount` 미언급.

#### Run 9: 000660 (agent_run_id: 23001039)
- **summary**: "현금 잔고가 마이너스로 매수 주문을 실행할 경우 추가적인 현금 부족을 초래할 수 있어 위험도가 매우 높습니다"
- **risk_opinion**: review
- **판단 근거**: `available_cash` 음수만 참조. `orderable_amount` 미언급.

#### Run 10: 000880 (agent_run_id: 214e4fb0)
- **summary**: "계좌에 사용 가능한 현금이 음수 상태이며, 추가 매수 시 레버리지가 증가하여 위험이 매우 높습니다"
- **판단 근거**: `available_cash` 음수만 참조. `orderable_amount` 미언급.

### 4.3 핵심 발견

| 항목 | 내용 |
|------|------|
| `orderable_amount` 언급한 run | **0 / 10** (0%) |
| `available_cash` 음수만으로 판단한 run | **10 / 10** (100%) |
| Cash Judgment Guide 준수 run | **0 / 10** (0%) |
| `risk_opinion = reject` | **8 / 10** (80%) |
| `risk_opinion = review` | **2 / 10** (20%) |

---

## 5. FDC 확인 결과

FDC (`final_decision_composer`)는 AR의 `risk_opinion`을 그대로 수용하여 모두 `HOLD` 결정을 내렸습니다.

| Symbol | AR risk_opinion | FDC decision_type | FDC summary |
|--------|----------------|-------------------|-------------|
| 001680 | reject | HOLD | "001680 — 리스크 평가 'reject'. FDC 생략." |
| 001230 | reject | HOLD | "001230 — 리스크 평가 'reject'. FDC 생략." |
| 001440 | reject | HOLD | "001440 — 리스크 평가 'reject'. FDC 생략." |
| 001040 | review | HOLD | "001040 — 유의미한 이벤트 없음. FDC 생략." |
| 000990 | reject | HOLD | "000990 — 리스크 평가 'reject'. FDC 생략." |

FDC downstream은 AR 판단을 정상적으로 전달받고 있으나, AR 판단 자체가 `orderable_amount`를 반영하지 못했으므로 FDC도 영향을 받지 않았습니다.

---

## 6. 최종 판정

### 판정: ❌ **미개선 (Not Improved)**

### 근거 요약

1. **Cash Judgment Guide가 프롬프트에 포함되었음에도**, 모든 AR run(10/10)이 `available_cash`의 음수 값만을 근거로 "현금 부족 → reject/review" 판단을 내렸습니다.
2. **어떤 AR run도 `orderable_amount`(+9,050,070원)를 언급하지 않았습니다.** 이는 프롬프트의 "Do NOT conclude 'cannot buy' solely because 'Available cash' is negative" 지시를 위반한 것입니다.
3. `orderable_amount`가 양수(+9,050,070원)임에도 불구하고, AR는 이를 완전히 무시하고 `available_cash`(-6,629,580원)만으로 판단했습니다.
4. 이는 LLM이 프롬프트의 명시적인 지시(Cash Judgment Guide)를 따르지 못한 사례로, **프롬프트 엔지니어링만으로는 부족**함을 시사합니다.

### 원인 추정

- **LLM의 인지 편향 (Cognitive Bias)**: `available_cash`가 음수(-6,629,580원)라는 강한 신호가 `orderable_amount`(+9,050,070원)라는 상대적으로 약한 신호를 압도함
- **프롬프트 구조 문제**: Cash Judgment Guide가 Cash Balance 섹션 내에 위치하지만, LLM이 "available_cash 음수 = 무조건 매수 불가"라는 사전 학습된 패턴을 override하지 못함
- **강화 방안 필요**: 프롬프트 수정만으로는 부족하며, 코드 레벨에서 `orderable_amount`를 우선 적용하거나, `available_cash` 음수 상황에서도 `orderable_amount`가 양수면 별도 로직으로 처리하는 하이브리드 접근 필요

---

## 7. Follow-up TODO

- [ ] **프롬프트 강화**: Cash Judgment Guide를 더 강조하거나, `available_cash` 값을 아예 프롬프트에서 제외하는 방안 검토
- [ ] **코드 레벨 개선**: `available_cash`가 음수여도 `orderable_amount`가 양수면 BUY를 허용하는 pre-processing 로직 추가
- [ ] **테스트 케이스 보강**: `available_cash` 음수 + `orderable_amount` 양수 시나리오에 대한 통합 테스트 추가
- [ ] **LLM 교체/업그레이드 평가**: 현재 사용 중인 모델이 복합적인 금융 지시를 따르지 못하는 근본 원인 분석
- [ ] **모니터링**: 향후 AR run에서 `orderable_amount` 언급 여부를 지속적으로 모니터링하는 대시보드 추가

---

## 부록: 쿼리 정보

```sql
-- 최신 AR agent_runs + cash_balance_snapshots 조인 쿼리
SELECT ar.agent_run_id, ar.agent_type, 
       ar.structured_output_json, 
       ar.created_at,
       dc.correlation_id,
       dc.cash_balance_snapshot_id,
       cbs.available_cash, 
       cbs.orderable_amount, 
       cbs.settled_cash,
       cbs.snapshot_at
FROM agent_runs ar
JOIN decision_contexts dc ON dc.decision_context_id = ar.decision_context_id
LEFT JOIN cash_balance_snapshots cbs ON cbs.cash_balance_snapshot_id = dc.cash_balance_snapshot_id
WHERE ar.agent_type = 'ai_risk'
  AND ar.created_at >= '2026-05-21 02:18:00+00'
ORDER BY ar.created_at DESC
LIMIT 10;
```
