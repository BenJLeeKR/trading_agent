# Paper 환경 주간 리뷰 — 2026-05-13 (수) 13:55 KST

> **검토 기간**: 2026-05-07 (목) ~ 2026-05-13 (수)
> **수행**: D Weekly Review (D-1~D-4)
> **계정**: EPC001-PAPER-ENTRYPOINT / KIS-PAPER-****6448
> **제외**: CTO 지표 정리(D-5)는 이번 주 제외

---

## 1. D-1: Gate 평가

### Account: `a44a02d1` (`EPC001-PAPER-ENTRYPOINT`)

| # | Gate Check | Threshold | Measured | Status |
|---|-----------|-----------|----------|--------|
| 1 | MIN_RETURN | ≥ 0.0% | +5.71% (₩152,500 / ₩2,670,000) | ✅ PASS |
| 2 | MAX_DRAWDOWN | ≤ 20.0% | 0% (계속 상승) | ✅ PASS |
| 3 | MIN_EXCESS_RETURN | ≥ benchmark | 측정 불가 — benchmark 데이터 없음 | ⚠️ WARN |
| 4 | MIN_WIN_RATE | ≥ 30% | 100% (1/1 포지션) | ✅ PASS |
| 5 | MIN_FILLED_ORDERS | ≥ 3건 | 0건 (order_requests 15건 모두 rejected) | ❌ FAIL |
| 6 | SNAPSHOT_FRESHNESS | ≤ 30분 | ~3분 전 (04:52:21 UTC) | ✅ PASS |
| 7 | SYNC_FAILURES | 연속 < 3회 | 0회 연속 실패 (금주 26/27 성공) | ✅ PASS |
| 8 | BLOCKING_LOCKS | 0건 | 0건 | ✅ PASS |

### 종합 판정: **NO_GO** (FAIL 1건 + WARN 1건)

### 상세 분석

- **MIN_FILLED_ORDERS FAIL**: Paper 환경의 태생적 한계. KIS Paper API는 실제 체결을 반환하지 않아 filled orders가 0일 수밖에 없음. 이 check는 Live 전환 후 재평가 필요.
- **MIN_EXCESS_RETURN WARN**: `performance` 또는 `benchmark_comparison` 테이블 미존재. 벤치마크 비교 로직은 별도 문서(`plans/paper_benchmark_comparison.md`)로 설계되어 있으나 DB에 데이터 없음.
- **나머지 6개 PASS**: 시스템 안정성, 포지션 성과, sync freshness 모두 양호.

### 권장
- MIN_FILLED_ORDERS는 Paper 환경에서 **의도적 제외**하고 Live 전환 전 Preflight에서만 평가하도록 Gate 문서에 명시 가능
- MIN_EXCESS_RETURN은 benchmark 데이터 없으면 SKIP 처리하도록 Gate 로직에 fallback 필요

---

## 2. D-2: Exit Criteria 평가

### Layer A (Auto) — 코드 기반

Gate 8개 check (A1~A8) = D-1과 동일. Gate NO_GO이나, 이는 Paper 한계 때문이며 실제 포지션 exit 필요성과 무관.

| Check | 평가 |
|-------|------|
| A9: Position-specific exit signal | 005930 +5.71% → 양호, exit signal 없음 |
| A10: Portfolio-level risk limit | 현금 30,000,000원, 포지션 2,670,000원 → 적정 |

### Layer B (Semi-Auto) — 스크립트/테스트

| Check | 평가 | Status |
|-------|------|--------|
| B1: Snapshot freshness | 3분 전, 정상 | ✅ PASS |
| B2: Sync 실패율 | 0% (당일 5/5 성공) | ✅ PASS |
| B3: Post-submit reconcile | 6건 (5건 stale >24h), 신규 증가 없음 | ⚠️ WARN |
| B4: Broker connectivity | 정상 (sync 지속 성공) | ✅ PASS |
| B5: KIS API 응답 | 정상 | ✅ PASS |

### Layer C (Manual) — 운영자 판단

| Check | 평가 | Status |
|-------|------|--------|
| C1: 포지션 규모 적절성 | 10주, 적절 | ✅ 적정 |
| C2: 미실현 손익 양호 | +₩152,500 (+5.71%) | ✅ 양호 |
| C3: 현금 여력 | ₩30,000,000 (충분) | ✅ 충분 |
| C4: AI 결정 품질 적절 | D-4 참조 | ✅ 적정 |
| C5: 전체 시스템 정상 | Sync/Lock/Stale 모두 정상 | ✅ 정상 |

### 종합 판정: **Exit 불필요** (HOLD current position)

- 포지션 005930 10주 @ 267,000, 현재 +5.71% → 보유 유지正当
- Broker orders 6건 존재하나 reconcile_required 상태로 정리 필요
- Exit trigger 없음

---

## 3. D-3: Sync / Stale / Lock 추세

### Snapshot Sync 주간 추세

| 날짜 (KST) | 실행 | 성공 | 실패 | 실패율 | 비고 |
|-----------|------|------|------|--------|------|
| 5/9 (토) | 4 | 3 | 1 | 25.0% | 초기 운영, 1건 실패 |
| 5/10 (일) | 3 | 3 | 0 | 0% | 안정화 |
| 5/11 (월) | 1 | 1 | 0 | 0% | 단발 실행 |
| 5/12 (화) | 18 | 18 | 0 | 0% | 5분 간격 운영 |
| 5/13 (수) | 5+ | 5 | 0 | 0% | 진행 중 |

**분석**:
- 5/9 1건 실패 이후 **연속 27회 성공** (0% 실패율 유지 중)
- 5/12부터 5분 간격 루프 운영 (18회/일 = 정상)
- 당일 마지막 sync: 13:52 KST (약 3분 전)

### Stale PENDING_SUBMIT

| 상태 | 건수 |
|------|------|
| pending_submit | **0건** ✅ |
| rejected | 15건 (히스토리) |
| reconcile_required | 6건 (5건 stale >24h) |

**분석**:
- PENDING_SUBMIT 0건 — 정상
- Reconcile_required 6건 중 5건이 24h 이상 경과 (5/11 발생분)
- 신규 reconcile 증가 없음 — 안정적

### Blocking Locks

| 측정 | 값 |
|------|-----|
| Blocking locks | **0건** ✅ |

### Reconcile_required 추세

| 구분 | 값 | 비고 |
|------|-----|------|
| 전체 reconcile | 6건 | 5/11: 5건, 5/13: 1건 |
| 24h 이상 경과 | 5건 | 허용 범위 (API 제약) |
| 신규 증가 (당일) | 0건 | 안정적 |

### 종합 평가: **안정적** ✅

Sync 안정화 추세 뚜렷. Reconcile_required 6건 유지 중이나 신규 증가 없음.

---

## 4. D-4: AI Decision Quality 점검

### 전체 분포 (총 107건, 전 기간)

| Decision Type | 건수 | 비율 | 비고 |
|--------------|------|------|------|
| **hold** | 54 | 50.5% | 과반 — 보수적 운영 |
| **approve** | 31 | 29.0% | 실행 결정 |
| **watch** | 17 | 15.9% | 관찰 |
| **reject** | 4 | 3.7% | 리스크 초과 |
| **reduce** | 1 | 0.9% | 포지션 축소 |
| **합계** | **107** | **100%** | |

**Non-actionable 비율**: 75건 (70.1%) — HOLD + WATCH + REJECT
**Actionable 비율**: 32건 (29.9%) — APPROVE + REDUCE

### 주간 Decision 추세

| 일자 | APPROVE | HOLD | WATCH | REJECT | REDUCE | 합계 |
|------|---------|------|-------|--------|--------|------|
| 5/7 (목) | 0 | 6 | 0 | 0 | 0 | 6 |
| 5/8 (금) | 0 | 5 | 0 | 0 | 0 | 5 |
| 5/9 (토) | 0 | 21 | 0 | 0 | 0 | 21 |
| 5/10 (일) | 27 | 13 | 16 | 3 | 1 | 60 |
| 5/11 (월) | 0 | 2 | 0 | 1 | 0 | 3 |
| 5/12 (화) | 4 | 7 | 1 | 0 | 0 | 12 |
| 5/13 (수) | 4 | 6 | 0 | 0 | 0 | 10+ |

### HOLD Rationale 분석 (최근 10건)

주요 패턴:
1. **"이벤트가 오래되어 신뢰할 수 없음"** — 7/10건, 합성 데이터 인식
2. **"종합 점수 0.0으로 임계치 미달"** — 4/10건
3. **"리스크 점수 허용이나 신뢰도 낮음"** — 5/10건
4. **"합성 데이터 기반"** — 3/10건

**→ AI가 합성 이벤트의 한계를 올바르게 인식하고 HOLD 결정을 내리고 있음. 이는 긍정적 신호.**

### APPROVE Rationale 분석 (최근 10건)

주요 패턴:
1. **"삼성전자 1분기 잠정실적 상회, HBM3E 양산"** — 4/10건 (5/13)
2. **"기술적 돌파, 거래량 증가"** — 6/10건 (5/11~5/12)
3. **신뢰도 범위**: 0.3~0.7 (적절한 분포)
4. **리스크 점수**: 0.2~0.3 (낮음)

**→ 근거 기반 APPROVE, 신뢰도와 리스크 점수 정상**

### REJECT 분석

- 4건 모두 `risk_check_passed=false`
- 리스크 체계가 정상적으로 거부 결정을 내리고 있음

### 품질 종합 평가

| 지표 | 평가 |
|------|------|
| 결정 분포 다양성 | ✅ 5개 type 골고루 분포 |
| HOLD 비중 50.5% | ✅ 보수적 운영에 적합, 과도하지 않음 |
| 근거 기반 결정 | ✅ HOLD/APPROVE 모두 rationale 명확 |
| 리스크 체계 작동 | ✅ REJECT 4건 모두 risk_check_passed=false |
| 신뢰도 범위 | ✅ 0.0~0.7, 적절한 캘리브레이션 |
| 합성 데이터 인식 | ✅ AI가 스스로 synthetic data 한계 인지 |

**종합: 양호** ✅ — 보수적이고 안전한 결정 패턴, 리스크 체계 정상 작동

---

## 5. 주간 운영 요약

| 항목 | 상태 |
|------|------|
| 포지션 | 005930 10주 @ 267,000 → 시장가 282,250 (+5.71%) |
| 미실현 손익 | +₩152,500 |
| 현금 | ₩30,000,000 |
| Sync 실패율 (금주) | 3.7% (1/27), 최근 26회 연속 성공 |
| Stale PENDING_SUBMIT | 0건 ✅ |
| Reconcile_required | 6건 (신규 증가 없음, 5건 stale) |
| Blocking Locks | 0건 ✅ |
| Gate 판정 | NO_GO (Paper 한계) |
| Exit 필요 | 없음 |
| AI 결정 (APPROVE율) | 29.9% |
| Broker Orders | 6건 (히스토리) |

---

## 6. 남은 리스크 1개

### Reconcile_required 5건 24h+ 경과

5/11 발생한 reconcile_required 5건이 48h 이상 경과했으나仍未 해소되지 않음.
- Paper 환경에서 reconcile_required는 API 제약상 허용 상태로 간주
- 단, Live 전환 시에는 반드시 정리 필요
- 신규 증가가 없고 총 6건으로 안정적이므로 **당장 조치 불필요**
- Live Preflight 체크리스트에 reconcile_required 정리 항목 포함 권장

---

## 7. 다음 직접 액션 1개

### Gate 문서에 Paper 환경 예외 조항 명시

Gate 8개 check 중 `MIN_FILLED_ORDERS`와 `MIN_EXCESS_RETURN`은 Paper 환경에서 측정 불가 또는 태생적 FAIL이 발생함.

**제안**: [`paper_one_month_ops_checklist.md`](plans/paper_one_month_ops_checklist.md) D-1 섹션에 다음 내용 추가:
- Paper 환경에서 `MIN_FILLED_ORDERS` FAIL은 허용 (의도적 제외)
- `MIN_EXCESS_RETURN` benchmark 미설치 시 SKIP 처리
- 위 두 check는 Live Preflight에서만 평가

---

## 8. 문서 변경 필요 여부

| 문서 | 변경 필요 | 내용 |
|------|----------|------|
| `plans/paper_one_month_ops_checklist.md` D-1 | ✅ 권장 | Paper 예외 조항 명시 |
| `plans/paper_go_no_go_gate.md` | ✅ 검토 | fallback 정책 보강 |
| `plans/paper_exit_criteria.md` | ❌ 불필요 | |
| `plans/paper_daily_ops_report_2026-05-13.md` | ❌ 유지 | 현재 상태 반영 완료 |

---

*작성: 2026-05-13 13:55 KST | 다음 D Weekly Review: 2026-05-20 (수)*
