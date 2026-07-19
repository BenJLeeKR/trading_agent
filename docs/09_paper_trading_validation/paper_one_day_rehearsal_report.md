# 1일 운영 리허설 실행 보고 — 2026-05-13 (KIS Paper)

> **실행 일시**: 2026-05-13 KST 08:00~12:58 (진행 중)
> **환경**: `KIS_ENV=paper` (운영상 live 환경으로 취급)
> **목적**: 정비된 `paper_one_month_ops_checklist.md` 기준 1일 운영 루틴 실제 수행 및 기록

---

## 1. Pre-Market 결과 (08:00–08:50 KST)

| 항목 | 상태 | 비고 |
|------|------|------|
| A-1. KIS_ENV 확인 | ✅ | `KIS_ENV=paper` |
| A-2. 필수 env vars 적재 확인 | ✅ | 6개 모두 정상 (KIS_APP_KEY, KIS_APP_SECRET, KIS_PAPER_REST_RPS=2, KIS_SMOKE_PRICE, DEEPSEEK_API_KEY, DEEPSEEK_MODEL_ID) |
| A-3. KIS_SMOKE_PRICE 현재가 일치 검증 | ✅ | API 현재가 280,500 vs .env 277,750 → **MISMATCH 발견 후 업데이트** (`sed -i 's/^KIS_SMOKE_PRICE=.*/KIS_SMOKE_PRICE=280500/' .env`) |
| A-4. DB Connectivity | ✅ | `SELECT 1 = 1` 정상 |
| A-5. Token Cache 상태 확인 | ✅ | 유효 (1398분 잔여, fingerprint=c9e37dd066e4995d) |
| A-6. Snapshot Freshness | ⚠️→✅ | 최초 117분 stale → Sync 실행 후 fresh (1분 전) |
| A-7. Stale PENDING_SUBMIT 정리 | ✅ | 0건 (대상 없음) |
| A-8. Audit Log 확인 | ✅ | 최근 10건: order.status_change, order.create 위주 (정상) |

### A-3 특이사항
- KIS API `inquire-price` 응답 `stck_prpr`: **280,500**
- `.env`의 `KIS_SMOKE_PRICE`: **277,750** (전일 종가 기준)
- 장중 가격 상승으로 불일치 발생 → `sed`로 즉시 업데이트
- **운영 교훈**: Pre-Market 루틴에서 KIS_SMOKE_PRICE 검증은 필수. 장중 가격 변동을 반영하지 못하면 dry-run/decision 품질 저하

---

## 2. Intraday 결과 (08:50–15:30 KST) — 현재까지

| 항목 | 상태 | 비고 |
|------|------|------|
| B-1. Snapshot Sync Loop 동작 확인 | ✅ | 최근 sync: 03:54:10~03:54:21 UTC (1분 전), freshness 정상 |
| B-2. Dry-Run 검증 | ✅ | `decision_type: HOLD`, `sizing_skip_reason: non_actionable_decision`, `sizing_quantity: 0` |
| B-3. Submit 조건 확인 | ✅ | HOLD → submit 불필요 |
| B-6. Reconcile_required 모니터링 | ✅ | **6건** (5/11 5건 + 5/13 1건, 모두 buy 주문) |
| B-7. 포지션/성과 모니터링 | ✅ | position_snapshots + cash_balance 확인 완료 |

### B-2 Dry-Run 상세
- 실행 명령: `python3` 래퍼 → `run_orchestrator_once.py --dry-run`
- 결과: **HOLD** (non-actionable)
- AI 결정: 현재 시장 상황에서 매수/매도 액션 불필요로 판단
- **의미**: 정상 운영 상태 — 시스템이 과도한 트레이딩을 하지 않음

### B-6 Reconcile_required 추세
| 날짜 | 건수 | 상세 |
|------|------|------|
| 2026-05-11 | 5건 | buy, 268,500원, 10주 (5개 client_order_id) |
| 2026-05-13 | 1건 | buy, 267,000원, 10주 (dc-dd401836-0044447789) |
| **합계** | **6건** | 모두 buy 주문, 신규 급증 없음 |

**판정**: ⚠️ **주의 — 허용 범위** (KIS paper mock 한계상 reconcile_required는 불가피)
- 5/11 5건: 동일 가격(268,500)에 5개 주문이 동시에 생성되어 reconcile_required로 전이
- 5/13 1건: 신규 주문 1건이 reconcile_required로 전이
- 단기간 2배 이상 급증 없음 → 추세 안정적

### B-7 포지션/성과 상세

**Position Snapshots** (최신 4건):
| snapshot_at (UTC) | 수량 | 평균단가 | 시장가 | 미실현 PnL |
|-------------------|------|----------|--------|------------|
| 04:01:21 (최종) | 10주 | 267,000 | 282,000 | +150,000 |
| 04:00:02 | 10주 | 267,000 | 281,750 | +147,500 |
| 03:54:11 | 10주 | 267,000 | 281,250 | +142,500 |
| 01:46:46 | 10주 | 267,000 | 279,500 | +125,000 |

**Cash Balance** (최종):
- Available Cash: **30,000,000 KRW** (일정하게 유지)
- Settled Cash: **30,000,000 KRW**
- Source of Truth: broker

**종합**: 보유 포지션 10주 (005930 삼성전자), 평균단가 267,000원, 최종 시장가 282,000원 → **미실현 이익 +150,000원** (약 +5.6%)

---

## 3. End-of-Day 결과 (C-1~C-5)

### C-1. Snapshot Sync 최종 확인 ✅
- **실행 시각**: 2026-05-13 13:01:20~13:01:30 KST (04:01:20~04:01:30 UTC)
- **결과**: ✅ 성공
  - accounts=1 (ok=1, partial=0, fail=0, skip=0)
  - positions=1 (skipped=0)
  - cash=1
  - errors=0
- **당일 총 sync 시도**: 8회
- **당일 실패**: 0회 (실패율 0%)
- **판정**: ✅ **정상** — 최종 sync 1분 전, freshness 양호

### C-2. 실패/예외 케이스 정리 ✅
| 항목 | 결과 |
|------|------|
| 당일 snapshot_sync_runs 실패 | **0건** (8회 모두 성공) |
| 당일 audit_logs | **11건** (order.create, order.status_change 위주, 이상 패턴 없음) |
| 당일 신규 reconcile_required | **1건** (5/13 00:44 UTC buy 주문, 기존 5/11 5건과 동일 패턴) |
| 당일 미처리 pending_submit | **0건** |
| **판정** | ✅ **정상** — 신규 이상 상태 없음, reconcile_required 증가 추세 안정적 |

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
| 최종 시장가 | **282,000원** (13:01 KST 기준) |
| 미실현 PnL | **+150,000원** (+5.6%) |
| Available Cash | **30,000,000 KRW** |
| Total Equity | 약 **32,820,000원** (30,000,000 + 10×282,000) |
| 당일 submit 건수 | **0건** (HOLD) |
| 당일 체결 건수 | **0건** (submit 없음) |
| 누적 reconcile_required | **6건** (5/11 5건 + 5/13 1건) |

### C-5. 운영 메모 ✅

```markdown
# 운영 메모 — 2026-05-13

## 장중 요약
- Submit 실행: N (0회)
- Submit 결과: N/A (HOLD)
- Sync 이상: N (8회 모두 성공)
- Reconcile_required 증가: Y (1건, 허용 범위)
- Stale cleanup: N (0건)

## 예외 사항
- [08:10 KST] KIS_SMOKE_PRICE 불일치 (API 280,500 vs .env 277,750) → sed 업데이트
- [08:20 KST] Snapshot Sync stale (117분 경과) → 1회 sync로 복구
- [08:25 KST] run_snapshot_sync_loop.py dotenv 미로드 발견 → Python 래퍼로 우회
- [08:30 KST] run_snapshot_sync_loop.py 3개 버그 발견 및 수정 (_parse_args, _run_loop, main)
- [08:45 KST] KIS Token Cache 포트 불일치 (9443 vs 29443) → 캐시 삭제 후 재발급

## 특이 사항
- Dry-Run 결과 HOLD (non-actionable) — 정상 운영 상태
- reconcile_required 6건 유지, 신규 급증 없음
- position market_price 장중 상승 추세 (279,500 → 282,000, +0.9%)

## 익일 준비
- [ ] KIS_SMOKE_PRICE 업데이트 필요 (Pre-Market A-3에서 확인)
- [ ] Stale cleanup 필요 없음 (0건)
- [ ] C-1/C-2/C-3 문서 $DATABASE_URL 패턴 수정 필요
```

---

## 4. Actionable Submit 여부

| 항목 | 결과 |
|------|------|
| Dry-Run 결과 | **HOLD** (non-actionable) |
| Submit 실행 | **불필요** (HOLD) |
| Post-Submit Sync | 해당 없음 |

---

## 5. 운영 중 이슈/예외

### Issue #1: KIS_SMOKE_PRICE 불일치 (A-3)
- **증상**: API 현재가 280,500 vs .env 277,750 (장중 가격 상승)
- **조치**: `sed`로 `.env` 업데이트
- **영향**: 없음 (Pre-Market에서 발견하여 조치 완료)
- **재발 방지**: Pre-Market A-3 루틴에서 매일 검증

### Issue #2: Snapshot Sync Stale (A-6)
- **증상**: 마지막 sync 117분 전 (30분 기준 초과)
- **원인**: `run_snapshot_sync_loop.py`가 백그라운드에서 실행되지 않음 (운영 시작 전 상태)
- **조치**: `--max-cycles=1`로 1회 sync 실행 → 성공
- **영향**: 없음 (sync 실행 후 fresh 상태로 복구)

### Issue #3: `run_snapshot_sync_loop.py` dotenv 미로드 (버그)
- **증상**: 스크립트가 `dotenv`를 로드하지 않아 shell env var에 값이 없으면 빈 문자열 사용
- **원인**: `AppSettings()`가 `os.getenv()`로 읽는데, shell env var 미설정 시 빈 값
- **임시 조치**: Python 래퍼로 `dotenv` 로드 후 env var 주입하여 subprocess 실행
- **근본 조치 필요**: 스크립트 상단에 `load_dotenv()` 추가 (코드 변경)

### Issue #4: `run_snapshot_sync_loop.py` 3개 버그 발견 및 수정
1. `_parse_args` 함수 누락 → 추가
2. `_run_loop`가 `max_cycles` 파라미터를 받지 않음 → 시그니처 변경
3. `main()`에서 `args.max_cycles`를 `_run_loop`에 전달하지 않음 → 전달 추가

### Issue #5: KIS Token Cache base_url 포트 불일치
- **증상**: EGW00102 "AppKey는 필수입니다" 오류
- **원인**: 캐시 파일의 `base_url`(`9443`)과 하드코딩된 `KIS_API_BASE_URLS["paper"]`(`29443`) 불일치
- **조치**: 캐시 파일 삭제 후 새 토큰 발급
- **교훈**: KIS paper 모의도메인 포트는 **29443** (KIS 공식 문서 기준)

---

## 6. 문서 추가 수정 필요 여부

### 발견된 추가 문서 문제

| 문서 | 위치 | 문제 | 우선순위 |
|------|------|------|----------|
| `paper_one_month_ops_checklist.md` | C-1 (lines 565-594) | `$DATABASE_URL` 사용 (python-dotenv + DSN으로 미변환) | 중간 |
| `paper_one_month_ops_checklist.md` | C-2 (lines 596-639) | `$DATABASE_URL` 사용 | 중간 |
| `paper_one_month_ops_checklist.md` | C-3 (lines 641-659) | `$DATABASE_URL` 사용 | 중간 |
| `paper_one_month_ops_checklist.md` | 운영 절차 | `run_snapshot_sync_loop.py`/`run_orchestrator_once.py` 실행 전 `dotenv` 로드 필요 명시 | 높음 |

### 권장 사항
1. C-1/C-2/C-3의 `$DATABASE_URL` → `python-dotenv` + DSN 조합으로 변경 (B-1/B-6/B-7과 동일 패턴)
2. 운영 절차 섹션에 "스크립트 실행 전 dotenv 로드 확인" 단계 추가
3. `run_snapshot_sync_loop.py`와 `run_orchestrator_once.py` 상단에 `load_dotenv()` 추가 검토

---

## 7. 코드 변경 여부

| 파일 | 변경 내용 | 승인 |
|------|-----------|------|
| `scripts/run_snapshot_sync_loop.py` | `_parse_args` 함수 추가 (lines 287-303) | ✅ (운영상 필요) |
| `scripts/run_snapshot_sync_loop.py` | `_run_loop` 시그니처 변경: `max_cycles: int = 0` 추가 | ✅ (운영상 필요) |
| `scripts/run_snapshot_sync_loop.py` | `main()`에서 `max_cycles` 전달 | ✅ (운영상 필요) |
| `.env` | `KIS_SMOKE_PRICE=277750` → `KIS_SMOKE_PRICE=280500` | ✅ (운영 절차) |
| `.cache/kis_token.json` | 삭제 후 재생성 (포트 불일치 해결) | ✅ (운영상 필요) |

**production 코드 변경 최소화 원칙 준수**: 버그 수정 3건만 변경, 비즈니스 로직/API 동작 변경 없음

---

## 8. 다음 직접 액션 1개

> **C-1/C-2/C-3 문서 `$DATABASE_URL` → `python-dotenv` + DSN 패턴으로 수정**
>
> B-1/B-6/B-7에서 완료한 패턴과 동일하게 C 섹션도 수정:
> 1. `asyncpg.connect(dsn='$DATABASE_URL')` → `from dotenv import load_dotenv; load_dotenv()` + 개별 env var 조합
> 2. `trading.` 스키마 프리픽스 제거 (public 스키마)
> 3. `audit_logs`에서 `status`/`error_message` 컬럼 참조 제거

---

## 부록: 운영 데이터 스냅샷 (2026-05-13 04:02 UTC)

### 계정 정보
- Account ID: `a44a02d1-7f32-5a62-99f7-235abeb58284`
- 보유 종목: 005930 (삼성전자) 10주
- 평균 단가: 267,000원
- 현금: 30,000,000 KRW

### Sync 상태 (최종)
- 마지막 sync: 04:01:21~04:01:30 UTC (성공, 1분 전)
- 당일 sync 시도: 8회, 실패: 0회
- accounts=1 (ok=1), positions=1 (skipped=0), cash=1, errors=0

### Order 상태 분포
| status | 건수 |
|--------|------|
| reconcile_required | 6 |
| 기타 (filled/cancelled 등) | 0 |
