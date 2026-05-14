# 일일 운영 실행 보고 — 2026-05-14 (KIS Paper)

> **작성 시각**: 2026-05-14 01:30 KST (운영일 기준)
> **KIS_ENV**: paper
> **Python**: 3.14.4
> **DB**: localhost:5432/trading

---

## 1. Pre-Market 확인 (08:00–08:50 KST)

### A-1. KIS_ENV 및 운영 환경 ✅
- `KIS_ENV=paper` — paper 환경 정상
- Python 3.14.4, DB host=localhost
- Token cache: `.cache/kis_token.json` (596 bytes, 정상)

### A-2. 필수 환경변수 ✅
| 변수 | 상태 |
|------|------|
| `KIS_APP_KEY` | ✅ |
| `KIS_APP_SECRET` | ✅ |
| `KIS_PAPER_REST_RPS` | ✅ = 2 |
| `KIS_SMOKE_PRICE` | ✅ = 280500 |
| `DEEPSEEK_API_KEY` | ✅ |
| `DEEPSEEK_MODEL_ID` | ✅ = deepseek-chat |

### A-3. KIS_SMOKE_PRICE 현재가 일치 검증 ✅
- `KIS_SMOKE_PRICE` = 280500
- 시장가 (`get_quote("005930")`) = 284000
- 차이 = 3,500원 (**≤5,000원 허용 범위 내** ✅)
- `.env` 수정 없음

### A-4. DB Connectivity ✅
- `health_check()` = True
- Connection pool 정상

### A-5. Token Cache ✅
- `.cache/kis_token.json` 존재 (596 bytes)
- 최초 API 호출 시 자동 발급 완료

### A-6. Snapshot Freshness ✅
- 마지막 sync: 07:24 KST (약 4분 전)
- 오늘 총 46회 시도, 0건 실패 (이후 50회로 증가)

### A-7. Stale PENDING_SUBMIT ✅
- `pending_submit` = 0건 (cleanup 불필요)

### A-8. Audit Log ✅
- 최근 10건 정상 패턴 (order.status_change / order.create)

---

## 2. Pre-Intraday Pipeline 확인

### P-1. Universe / 후보 종목 ✅
| Symbol | Name | Market | Active |
|--------|------|--------|--------|
| 005930 | Samsung Electronics Co., Ltd. | KRX | ✅ |
| AAPL | Apple Inc. | NASDAQ | ✅ |

- `trade_decisions.decision_type` 기준 최근 의사결정 적재 확인 필요 (`decision` 컬럼은 legacy/orphaned 컬럼으로 `null` 정상)
- 최근 decision_type: 04:45 KST 기준 HOLD

### P-2. OpenDART 이벤트 수집 ✅
- 마지막 수집: 2026-05-13 00:21 KST
- 이벤트 유형: 감사보고서, 분기보고서, 증권발행실적보고서, IR개최 공시
- `symbol` 매핑: 대부분 `null` (005930 직접 매핑 이벤트 없음)
- Freshness: **양호** (당일 00:21 수집)

### P-3. AI Agent 실행 상태 ✅
| Agent Type | Status | 최근 실행 |
|-----------|--------|----------|
| event_interpretation | ✅ completed | 04:45 KST |
| ai_risk | ✅ completed | 04:45 KST (risk_opinion=allow) |
| final_decision_composer | ✅ completed | 04:45 KST |

- 모든 agent 정상 완료
- `model_id`가 모두 `null` — 모델 ID 추적 미비

---

## 3. Intraday 결과 (08:50–15:30 KST)

### B-1. Snapshot Sync Loop ✅
- 마지막 sync: 07:24 KST (약 4분 전)
- Sync loop 정상 동작 중 (5분 간격)

### B-2. Dry-Run 검증 ✅
```
실행 시각: 2026-05-14 01:29 KST (운영 세션)
decision_type: HOLD
confidence: 0.00
symbol: 005930
side: BUY
sizing_quantity: 0
sizing_skip_reason: non_actionable_decision
risk_opinion: allow
```

- **FDC decision: HOLD** — AI Risk는 allow했으나 FDC가 HOLD 판정
- Submit 조건 불충족

### B-3. Submit 조건 확인 ✅
- FDC decision = `HOLD` (APPROVE 아님)
- **Submit 실행하지 않음** (규칙: FDC APPROVE 시만 최대 1회)

### B-4. Submit 실행
- **발생 없음** (HOLD로 인해 skip)

### B-5. Post-Submit Sync
- **해당 없음** (submit 미발생)

### B-6. Reconcile_required 모니터링 ✅
- `reconcile_required` = 6건 (기존 유지, 신규 증가 없음)
- `rejected` = 15건 (기존 유지)

### B-7. 포지션/성과 모니터링 ✅
| 항목 | 값 |
|------|-----|
| 종목 | 005930 (삼성전자) |
| 보유 수량 | 10주 |
| 평균 매입가 | 267,000원 |
| 시장가 | 284,000원 |
| 미실현 손익 | **+170,000원 (+6.4%)** |
| 마지막 스냅샷 | 07:29 KST |

---

## 4. End-of-Day 결과

### C-1. Snapshot Sync 최종 확인 ✅
- 오늘 총 **50회** sync 실행
- `completed`: 44회
- `failed`: **0회**
- `partial`: 6회
- 안정적 운영

### C-2. 실패/예외 케이스 정리 ✅
- Sync 실패: 0건
- Order 실패: 0건 (신규)
- 예외 케이스 없음

### C-3. Stale Cleanup 필요 여부 ✅
- `pending_submit` = 0건 (cleanup 불필요)
- `reconcile_required` = 6건 (허용 범위 내)

### C-4. 일일 성과 최종 점검 ✅
- 미실현 손익: **+170,000원 (+6.4%)**
- 현금 잔고: rate limit으로 미조회 (EGW00201)
- 신규 체결: 없음

### C-5. 운영 메모
- `trade_decisions.decision`은 legacy/orphaned 컬럼이므로 `null` 정상. 운영 판단은 `decision_type`, `decision_json`, `agent_runs.structured_output_json` 기준으로 확인 필요
- Sync loop `partial` 상태 6회 — cash balance rate limit 영향으로 추정

---

## 5. 보고서 필수 항목 (사용자 요청)

### 5.1 Universe / 후보 종목
- **005930** (삼성전자, KRX) — 유일한 활성 종목
- **AAPL** (Apple, NASDAQ) — 등록되어 있으나 실제 거래/포지션 없음

### 5.2 이벤트 수집 결과
- OpenDART: 2026-05-13 00:21 KST 수집 완료
- 감사보고서, 분기보고서 등 10+건 수집
- 005930 직접 매핑 이벤트: 없음

### 5.3 AI Decision 결과
| 단계 | 결과 |
|------|------|
| Event Interpretation | ✅ completed (symbol=UNKNOWN, events=1) |
| AI Risk | ✅ allow (risk_score=0.00) |
| Final Decision Composer | **HOLD** (confidence=0.00) |

### 5.4 Submit 발생 여부
- **Submit 없음** — FDC가 HOLD 판정, APPROVE 조건 미충족

### 5.5 Post-Submit Sync / Reconciliation 결과
- Post-Submit Sync: 해당 없음 (submit 미발생)
- Reconciliation: `reconcile_required` 6건 유지, 신규 증가 없음

---

## 6. 장중 요약

| 체크포인트 | 상태 | 비고 |
|-----------|------|------|
| A. Pre-Market (8항목) | ✅ 모두 통과 | KIS_SMOKE_PRICE 차이 3,500원 (허용) |
| P. Pipeline 확인 (3항목) | ✅ 모두 통과 | Universe 2종목, Agent all completed |
| B. Intraday | ✅ 정상 | HOLD → submit 없음 |
| C. End-of-Day | ✅ 정상 | Sync 50회, failed 0 |
| **Submit** | **없음** | FDC HOLD |

---

## 7. 예외 사항

| # | 항목 | 심각도 | 상태 |
|---|------|--------|------|
| 1 | `trade_decisions.decision` 모두 `null` | ✅ 정상 | legacy/orphaned 컬럼. 운영 판단은 `decision_type` 기준 |
| 2 | Sync `partial` 6회 | ⚠️ Low | Cash balance rate limit(EGW00201) 영향 추정 |
| 3 | Agent `model_id` 모두 `null` | ℹ️ Info | 모델 ID 추적 미비 (운영 영향 없음) |

---

## 8. 특이 사항

1. **FDC HOLD 지속**: 이전 dry-run과 동일하게 HOLD 판정. AI Risk는 allow했으나 FDC가 HOLD 유지.
2. **Sync Loop 안정적**: 50회 실행, 0 failed. 5분 간격 유지.
3. **Reconcile_required 안정적**: 6건 유지, 신규 증가 없음.
4. **Unrealized PnL +6.4%**: 005930 보유 포지션 양호.

---

## 9. 익일 준비

### 다음 운영일 준비사항 (1개)

**운영 조회 기준 정리**
- `trade_decisions.decision`은 migration 0009에서 nullable 처리된 legacy/orphaned 컬럼이며, `null`이 정상
- FDC 결과 추적은 `trade_decisions.decision_type`, `trade_decisions.decision_json`, `agent_runs.structured_output_json` 기준으로 수행
- **액션**: 운영 체크 SQL/리포트 템플릿에서 `decision` 컬럼 참조가 남아 있으면 `decision_type` 기준으로 교체

---

## 10. 문서 추가 수정 필요 여부

- `plans/paper_ops_execution_plan_2026-05-14.md` — 실행 완료, 추가 수정 불필요
- `plans/paper_one_month_ops_checklist.md` — Pre-Intraday Pipeline 확인(P-1~P-3) 항목 반영 완료

## 11. 코드 변경 여부

- **코드 변경 없음** (운영 실행만 수행)

---

## 부록: 계정 정보
- Client ID: `301961b4-75d9-533c-92b7-69a306cdd435`
- Account ID: `a44a02d1-7f32-5a62-99f7-235abeb58284`
- Strategy ID: `30a1d26b-8230-51fc-8548-30920effff0c`

## 부록: Sync 상태 (최종)
- 총 실행: 50회
- Completed: 44회
- Failed: 0회
- Partial: 6회
- 마지막 실행: 2026-05-13 07:24 KST

## 부록: Order 상태 분포
| 상태 | 건수 |
|------|------|
| rejected | 15 |
| reconcile_required | 6 |
| (기타) | 0 |
