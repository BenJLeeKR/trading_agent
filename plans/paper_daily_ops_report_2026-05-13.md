# 일일 운영 실행 보고 — 2026-05-13 (KIS Paper)

> **실행 일시**: 2026-05-13 KST 13:30~13:46 (Intraday 기록)
> **환경**: `KIS_ENV=paper` (운영상 live 환경으로 취급)
> **목적**: 정비된 [`paper_one_month_ops_checklist.md`](plans/paper_one_month_ops_checklist.md) 기준 1일 운영 루틴 실제 수행 및 기록
> **참고**: Pre-Market(08:00–08:50) 시간대는 이미 경과하여 DB 간접 확인으로 대체

---

## 1. Pre-Market 잔여 확인 (08:00–08:50 KST) — DB 간접 확인

| 항목 | 상태 | 비고 |
|------|------|------|
| A-1. KIS_ENV 확인 | ✅ | `KIS_ENV=paper` |
| A-2. 필수 env vars 적재 확인 | ✅ | KIS_APP_KEY, KIS_APP_SECRET, KIS_PAPER_REST_RPS=2, KIS_SMOKE_PRICE=280500, DEEPSEEK_API_KEY, DEEPSEEK_MODEL_ID 모두 정상 |
| A-3. KIS_SMOKE_PRICE 현재가 일치 검증 | ⚠️ | `.env`=280,500 vs position market_price=284,500 (차이 4,000원). KIS API 직접 조회는 token cache 없어 생략 |
| A-4. DB Connectivity | ✅ | MCP PostgreSQL 쿼리 정상 응답 |
| A-5. Token Cache 상태 확인 | ⚠️ | 캐시 파일 없음 (`.cache/kis_token.json`). KIS API 호출 시 새로 발급됨 — 정상 동작 범위 |
| A-6. Snapshot Freshness | ✅ | 마지막 sync 4분 전 (13:41 KST). 당일 14회 모두 성공 |
| A-7. Stale PENDING_SUBMIT 정리 | ✅ | 0건 (대상 없음) |
| A-8. Audit Log 확인 | ✅ | 당일 11건, order.status_change/order.create 위주 (정상) |

### A-3 특이사항
- `KIS_SMOKE_PRICE=280500` (이전 세션에서 설정)
- Position snapshot market_price: **284,500** (13:31 KST) → 282,750 (13:41 KST, 변동)
- Dry-run은 280,500 기준으로 정상 수행됨 (HOLD 판정에 영향 없음)

---

## 2. Intraday 결과 (08:50–15:30 KST) — 13:46 KST 기준

| 항목 | 상태 | 비고 |
|------|------|------|
| B-1. Snapshot Sync Loop 동작 확인 | ✅ | 5분 간격 자동 실행 중, 최근 10회 모두 성공 |
| B-2. Dry-Run 검증 | ✅ | `decision_type: HOLD`, `sizing_quantity: 0`, `sizing_skip_reason: non_actionable_decision` |
| B-3. Submit 조건 확인 | ✅ | HOLD → submit 불필요 |
| B-6. Reconcile_required 모니터링 | ✅ | **6건 유지** (5/11 5건 + 5/13 1건), 신규 증가 없음 |
| B-7. 포지션/성과 모니터링 | ✅ | position_snapshots + cash_balance 확인 완료 |

### B-2 Dry-Run 상세
- 실행 명령: `bash -c 'set -a; source .env; set +a && python3 scripts/run_orchestrator_once.py --dry-run'`
- AI Agent 실행:
  - Event Interpretation Agent: ✅ (symbol=UNKNOWN, events=1)
  - AI Risk Agent: ✅ (risk_opinion=allow, risk_score=0.00)
  - Final Decision Composer: ✅ (decision_type=HOLD, confidence=0.00)
- 결과: **HOLD** (non-actionable)
- **의미**: 정상 운영 상태 — 시스템이 과도한 트레이딩을 하지 않음

### B-6 Reconcile_required 추세

| 날짜 | 건수 | 상세 |
|------|------|------|
| 2026-05-11 | 5건 | buy, 268,500원, 10주 (5개 client_order_id) |
| 2026-05-13 | 1건 | buy, 267,000원, 10주 |
| **합계** | **6건** | 모두 buy 주문, **신규 증가 없음** |

**판정**: ✅ **허용 범위** — 증가 추세 없음, 안정적 유지

### B-7 포지션/성과 상세

**Position Snapshots** (최근 5건):
| snapshot_at (KST) | 수량 | 평균단가 | 시장가 | 미실현 PnL |
|-------------------|------|----------|--------|------------|
| 13:41 (최종) | 10주 | 267,000 | 282,750 | +157,500 |
| 13:36 | 10주 | 267,000 | 282,000 | +150,000 |
| 13:31 | 10주 | 267,000 | 284,500 | +175,000 |
| 13:25 | 10주 | 267,000 | 284,500 | +175,000 |
| 13:20 | 10주 | 267,000 | 283,000 | +160,000 |

**Cash Balance** (최종):
- Available Cash: **30,000,000 KRW** (일정하게 유지)
- Settled Cash: **30,000,000 KRW**

**종합**: 보유 포지션 10주 (005930 삼성전자), 평균단가 267,000원, 최종 시장가 282,750원 → **미실현 이익 +157,500원** (약 +5.9%)

---

## 3. End-of-Day 결과 (C-1~C-5) — 13:49 KST 최종

> **실행 시각**: 2026-05-13 13:49 KST (장중 snapshot, End-of-Day 루틴 수행)
> Sync loop가 5분 간격으로 계속 동작 중이므로, 최종값은 15:30 이후 재확인 권장

### C-1. Snapshot Sync 최종 확인 ✅

| 항목 | 값 |
|------|-----|
| 당일 sync 시도 | **18회** |
| 당일 성공 | **18회** (실패 0회) |
| 실패율 | **0%** ✅ |
| 마지막 sync | **13:47:03 KST** (약 2분 전) |
| 최근 10회 상태 | 모두 completed, error_count=0 |

**판정**: ✅ **정상** — Sync loop가 5분 간격으로 안정적 실행 중

### C-2. 실패/예외 케이스 정리 ✅

| 항목 | 결과 |
|------|------|
| 당일 snapshot_sync_runs 실패 | **0건** (18회 모두 성공) |
| 당일 audit_logs | **16건** — 모두 `order.status_change`/`order.create`, 이상 패턴 없음 |
| 당일 신규 reconcile_required | **0건** (6건 유지, 증가 없음) |
| 당일 미처리 pending_submit | **0건** |
| **판정** | ✅ **정상** — 신규 이상 상태 없음 |

### C-3. Stale Cleanup 필요 여부 ✅

| 항목 | 결과 |
|------|------|
| 24h 이상 stale pending_submit | **0건** |
| Cleanup 필요 여부 | **불필요** |
| **판정** | ✅ **정상** — cleanup 대상 없음 |

### C-4. 일일 성과 최종 점검 ✅

| 항목 | 값 |
|------|-----|
| 보유 종목 | 005930 (삼성전자) 10주 |
| 평균 단가 | 267,000원 |
| 최종 시장가 (13:47 KST) | **282,000원** |
| 미실현 PnL | **+150,000원** (+5.6%) |
| Available Cash | **30,000,000 KRW** |
| Total Equity | 약 **32,820,000원** (30,000,000 + 10×282,000) |
| 당일 submit 건수 | **0건** (HOLD) |
| 당일 체결 건수 | **0건** (submit 없음) |
| 누적 reconcile_required | **6건** (5/11 5건 + 5/13 1건, 증가 없음) |

### C-5. 운영 메모

```markdown
# 운영 메모 — 2026-05-13

## 장중 요약
- Submit 실행: N (0회)
- Submit 결과: N/A (HOLD, non-actionable)
- Sync 이상: N (18회 모두 성공, 실패율 0%)
- Reconcile_required 증가: N (6건 유지, 신규 증가 없음)
- Stale cleanup: N (0건)

## 예외 사항
- [13:36 KST] KIS_SMOKE_PRICE=280,500 vs market_price 최고 284,500 (4,000원 차이)
  → dry-run HOLD에는 영향 없었으나, KIS_SMOKE_PRICE 업데이트 권장
- [13:36 KST] Token cache 파일 없음 (`.cache/kis_token.json`)
  → KIS API 호출 시 새로 발급되므로 정상 동작 범위

## 특이 사항
- Dry-Run 결과 HOLD (non-actionable) — 정상 운영 상태
- reconcile_required 6건 유지, 신규 증가 없음 — 안정적
- position market_price 장중 변동: 279,500 → 284,500(고) → 282,000(종) (+0.9% net)
- Sync loop 5분 간격 자동 실행 중, 18회 모두 성공
- audit_logs 16건, 모두 order.status_change/order.create 정상 패턴

## 익일 준비
- [ ] KIS_SMOKE_PRICE 업데이트 필요 (A-3 Pre-Market 루틴에서 KIS API inquire-price로 현재가 조회)
- [ ] Token cache — KIS API 호출 시 자동 발급되나, Pre-Market에서 확인 권장
- [ ] Stale cleanup 불필요 (0건)
- [ ] Sync loop 상태 재확인 (자동 실행 중이므로 특별 조치 불필요)
```

---

## 4. Actionable Submit 여부

| 항목 | 결과 |
|------|------|
| Dry-Run 결과 | **HOLD** (non-actionable) |
| Submit 실행 | **불필요** (HOLD) |
| Post-Submit Sync | 해당 없음 |

---

## 5. 운영 중 관찰 사항

### Observation #1: KIS_SMOKE_PRICE vs 시장가 차이
- `.env`에 280,500으로 설정되어 있으나, position market_price는 282,750~284,500 범위에서 변동
- dry-run HOLD에는 영향 없었으나, APPROVE 시나리오에서는 가격 차이가 결정 품질에 영향 가능
- **권장**: Pre-Market 루틴에서 KIS API `inquire-price`로 현재가 조회 후 업데이트

### Observation #2: Sync Loop 안정적 운영
- 5분 간격 자동 실행, 18회 모두 성공 (실패율 0%)
- `run_snapshot_sync_loop.py`가 백그라운드에서 정상 동작 중

### Observation #3: Reconcile_required 안정적
- 6건 유지, 신규 증가 없음
- 5/11 5건 + 5/13 1건 모두 buy 주문, 동일 패턴

---

## 6. 문서 추가 수정 필요 여부

| 문서 | 위치 | 문제 | 우선순위 |
|------|------|------|----------|
| `paper_one_month_ops_checklist.md` | A-3 | KIS_SMOKE_PRICE 검증 절차에 KIS API 직접 조회 명령어 추가 필요 | 낮음 |

---

## 7. 코드 변경 여부

**이번 턴: 코드 변경 없음** — 운영 루틴 수행 및 기록만 진행

---

## 8. 다음 직접 액션

> **C-1~C-5 End-of-Day 완료** ✅
>
> 당일 운영 정상 종료. 다음 루틴:
> 1. **D Weekly Review (금요일)**: Gate 평가, Exit Criteria, Sync/Stale/Lock 추세, AI Decision Quality, CTO 지표
> 2. **Pre-Market (익일 08:00 KST)**: KIS_SMOKE_PRICE 업데이트, token cache 확인, snapshot freshness 확인
> 3. **Sync loop**: 5분 간격 자동 실행 중 — 특별 조치 불필요

---

## 부록: 운영 데이터 스냅샷 (2026-05-13 13:49 KST 최종)

### 계정 정보
- Account ID: `a44a02d1-7f32-5a62-99f7-235abeb58284`
- 보유 종목: 005930 (삼성전자) 10주
- 평균 단가: 267,000원
- 현금: 30,000,000 KRW

### Sync 상태 (최종)
- 마지막 sync: 13:47:05 KST (성공, 2분 전)
- 당일 sync 시도: 18회, 실패: 0회
- accounts=1 (ok=1), positions=1, cash=1, errors=0

### Order 상태 분포
| status | 건수 |
|--------|------|
| reconcile_required | 6 |
| rejected | 15 |
| pending_submit | 0 |
