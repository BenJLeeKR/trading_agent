# Reconcile Required Convergence Validation — 2026-05-19

**검증 일시**: 2026-05-19 15:12 ~ 15:30 KST (UTC+9)
**검증자**: Runtime Convergence Validation (automated)
**DB 환경**: paper (KIS 모의투자)

---

## 1. Baseline

| 항목 | Count |
|------|-------|
| broker_orders reconcile_required | **25** |
| order_requests reconcile_required | **25** |
| 불일치 건수 (broker_orders만 RR) | **0** (모두 일치) |

- broker_orders와 order_requests의 reconcile_required 상태가 완전히 일치함 (25/25)
- 불일치 건수 0 → orphan 상태는 없음

## 2. Symbol/Side 분포

| Symbol | Side | Count |
|--------|------|-------|
| 000150 | sell | 4 |
| 000150 | buy | 4 |
| 000810 | buy | 3 |
| 000810 | sell | 2 |
| 000990 | buy | 2 |
| 000210 | buy | 2 |
| 003490 | buy | 2 |
| 001740 | buy | 1 |
| 000660 | sell | 1 |
| 004000 | buy | 1 |
| 000660 | buy | 1 |
| 000270 | buy | 1 |
| 005830 | buy | 1 |

**총 13개 종목, 25건** — 000150 (8건)과 000810 (5건)이 전체의 52% 차지

## 3. 날짜별 분포

| Date | Count |
|------|-------|
| 2026-05-19 | 7 |
| 2026-05-18 | 18 |

- 5/18일 18건 (buy 위주), 5/19일 7건 (sell 위주)
- 5/18일 주문은 02:00~03:38 KST 사이에 생성됨 (장 시작 전 pre-market?)
- 5/19일 주문은 09:32~10:10 KST 사이에 생성됨 (장중)

## 4. Cycle별 Count 변화

| Cycle # | Time (KST) | broker_orders RR | order_requests RR | 소요 시간 | 비고 |
|---------|-----------|-----------------|-------------------|---------|------|
| 0 (pre) | 15:12:44 → 15:14:37 | 25 | 25 | 113.3s | pre-market phase, 첫 cycle |
| 1 | 15:16:59 → 15:18:29 | 25 | 25 | 90.4s | intraday phase |
| 2 | 15:20:58 → 15:22:16 | 25 | 25 | 77.6s | decision_submit_gate 실패 후 |
| 3 | 15:23:50 → 15:27:35 | 25 | 25 | 85.4s | |
| 4 | 15:27:35 → 15:28:52 | 25 | 25 | 71.9s | |

**5 cycles 모두 count 변화 없음 — 25건 유지, 단 한 건도 해결되지 않음**

## 5. 샘플 주문 전이 추적

| broker_order_id | Symbol | Side | Cycle 0 | Cycle 1 | Cycle 2 | Cycle 3 | Cycle 4 | 최종 상태 |
|-----------------|--------|------|---------|---------|---------|---------|---------|----------|
| 7365c36d | 000810 | sell | RR | RR | RR | RR | RR | reconcile_required |
| baf8a26b | 000810 | sell | RR | RR | RR | RR | RR | reconcile_required |
| 569b2acb | 000660 | sell | RR | RR | RR | RR | RR | reconcile_required |
| d9a47f11 | 000150 | sell | RR | RR | RR | RR | RR | reconcile_required |
| 455e3a04 | 000150 | sell | RR | RR | RR | RR | RR | reconcile_required |
| 7bf16e48 | 000150 | sell | RR | RR | RR | RR | RR | reconcile_required |
| c410c868 | 000150 | sell | RR | RR | RR | RR | RR | reconcile_required |
| 16027a2a | 005830 | buy | RR | RR | RR | RR | RR | reconcile_required |
| 5522523c | 000810 | buy | RR | RR | RR | RR | RR | reconcile_required |
| 1b20a4b8 | 000660 | buy | RR | RR | RR | RR | RR | reconcile_required |

**모든 샘플 주문이 5 cycles 동안 reconcile_required 상태 유지 — 전이 없음**

## 6. 예산 사용 관찰

### INQUIRY budget exhaustion 로그
- **Cycle 0**: `resolve_unknown_state failed` for 5개 주문 (broker_order_id: 7365c36d, baf8a26b, 569b2acb, d9a47f11, 455e3a04) — `[global] Global REST cap exhausted (remaining=0/1)`
- **Cycle 1**: 동일 5개 주문 budget exhaustion
- **Cycle 2**: 동일 5개 주문 budget exhaustion
- **Cycle 3**: 동일 5개 주문 budget exhaustion
- **Cycle 4**: 동일 5개 주문 budget exhaustion

### RECONCILIATION budget 사용
- `_sync_reconcile_required_orders()` 실행 로그 없음 (해당 함수가 호출되지 않음)
- reconciliation budget 관련 로그 미발견

### _sync_reconcile_required_orders() 실행 횟수
- **0회** — post-submit-sync 로그에서 `_sync_reconcile_required_orders` 호출 없음
- 대신 `resolve_unknown_state`가 호출되었으나 모두 budget exhaustion으로 실패

### inquire-daily-ccld matching 실패
- Cycle 0: 10건의 `inquire-daily-ccld: all matching strategies FAILED`
- Cycle 1: 7건의 matching 실패
- Cycle 2: 7건의 matching 실패
- **matching 실패 패턴**: `output_count=0, odnos_in_response=[]` — KIS API 응답에 주문번호(odno)가 없어 매칭 불가

## 7. 잔존 패턴 분류

### A. Budget 미도달 (Global REST cap exhausted)
- **영향**: 5개 주문이 매 cycle마다 budget exhaustion으로 `resolve_unknown_state` 실패
- **원인**: KIS paper 환경의 REST rate limit이 초당 1건으로 제한되어 있음 (`KIS_PAPER_REST_RPS=1`)
- **영향 범위**: 5/25 = 20%의 주문이 budget 부족으로 미처리

### B. Broker truth 조회 실패 (inquire-daily-ccld matching failure)
- **영향**: 모든 25개 주문에 대해 `inquire-daily-ccld` API 호출은 성공했으나, 응답에서 해당 주문의 odno(주문번호)를 찾지 못함
- **원인**: `odnos_in_response=[]` — KIS 모의투자 API가 체결내역 조회 시 해당 주문을 반환하지 않음
- **가능한 원인**:
  1. 모의투자 환경에서 주문이 실제로 체결되지 않아 odno가 생성되지 않음
  2. 조회 기간(INQR_STRT_DT/INQR_END_DT)이 부적절
  3. 주문이 API로 접수되었으나 KIS 내부에서 소실됨

### C. Matching 실패
- 모든 matching strategy가 실패하여 `resolve_unknown_state`로 fallback
- Fallback에서도 budget exhaustion으로 실패

### D. Genuine manual reconciliation
- 해당 사항 없음 — 모든 주문이 자동으로 reconcile_required 상태가 되었으며, 수동 개입 없음

## 8. 예산 정책 평가

### limit=5 적절성
- `resolve_unknown_state`는 5개 주문까지만 시도되고 나머지는 budget exhaustion
- **limit=5는 부적절**: 25개 주문 중 5개(20%)만 처리 가능
- paper 환경 RPS=1에서 5회 API 호출에 약 5초 소요 — 실제로는 budget이 더 빨리 소진됨

### RECONCILIATION budget 용량
- `_sync_reconcile_required_orders()`가 호출되지 않아 reconciliation budget이 사용되지 않음
- post-submit-sync가 `resolve_unknown_state`만 호출하고 reconciliation 함수는 호출하지 않음

### polling cadence 충돌 여부
- post-submit-sync: ~30초 간격으로 실행 (실제로는 71~113초 소요)
- snapshot-sync: 300초 간격
- **충돌 발견**: post-submit-sync가 71~113초 소요되면서 snapshot-sync와 간격이 좁혀짐
- decision_submit_gate (124초 timeout) 후 post-submit-sync가 지연됨

## 9. 최종 판정

### ❌ 재block (Convergence Failure)

**이유**:
1. **5 cycles 동안 count 변화 0** — 25건 모두 reconcile_required 상태 유지
2. **단 한 건도 해결되지 않음** — updated=0, filled=0
3. **근본 원인 미해결**:
   - `inquire-daily-ccld` API가 모의투자 환경에서 주문번호(odno)를 반환하지 않음
   - `resolve_unknown_state`가 budget exhaustion으로 20%만 시도
   - `_sync_reconcile_required_orders()`가 호출되지 않음
4. **수렴 불가능** — 현재 메커니즘으로는 reconcile_required 상태가 해결될 수 없음

## 10. Follow-up

### 남은 과제
1. **KIS paper API odno 문제 진단**
   - `inquire-daily-ccld` API가 paper 환경에서 odno를 반환하지 않는 원인 파악
   - 조회 기간(INQR_STRT_DT)을 더 넓게 설정하여 테스트
   - KIS paper API의 체결내역 조회 한계 확인

2. **`_sync_reconcile_required_orders()` 호출缺失**
   - post-submit-sync 로직에서 reconciliation 함수가 호출되지 않는 이유 분석
   - `resolve_unknown_state` 실패 시 reconciliation 함수로 fallback하도록 수정

3. **Budget 정책 재검토**
   - paper 환경 RPS=1에서 budget limit=5는 비현실적
   - budget 소진 시 재시도 메커니즘 추가
   - INQUIRY와 RECONCILIATION budget 분리

4. **Backfill 스크립트 활용**
   - `scripts/backfill_reconcile_required_orders.py`를 사용하여 강제 해결 시도
   - `scripts/cleanup_orphan_reconcile_required.py`로 orphan 정리

### 운영자 관측 포인트
- post-submit-sync cycle 소요 시간이 71→113초로 증가 추세 (budget exhaustion으로 인한 재시도?)
- decision_submit_gate가 124초 timeout으로 실패 (연쇄 영향)
- 5/18일 18건의 주문이 24시간 이상 reconcile_required 상태로滞留
- scheduler heartbeat는 정상 (last_heartbeat_at: 2026-05-19T06:20:50Z)
- health endpoint: status=ok, database=connected, scheduler.healthy=true
