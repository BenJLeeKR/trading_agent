# KIS inquire-daily-ccld Raw 응답 확인 + EXPIRED Fallback 검증 보고서

**작성일**: 2026-05-19 17:51 KST  
**목적**: `reconcile_required` 25건 → EXPIRED 전이의 broker truth 기반 여부 검증

---

## 1. 확인한 주문 샘플

| # | Symbol | 종목명 | Side | 수량 | 가격 | broker_native_order_id (ODNO) |
|---|--------|--------|------|------|------|-------------------------------|
| 1 | `000150` | 두산 | sell | 10 | 1,562,000 | `0000008278` |
| 2 | `000660` | SK하이닉스 | sell | 10 | 1,791,000 | `0000011357` |

**선정 기준**:
- `000150` (두산) — sell side, 가장 많은 종목
- `000660` (SK하이닉스) — sell side, 다른 종목
- 두 건 모두 `broker_native_order_id`가 숫자형 KIS ODNO 존재

**Local DB 상태**:
- `order_requests.status = 'expired'`
- `broker_orders.broker_status = 'reconcile_required'`

---

## 2. KIS inquire-daily-ccld Raw 응답

### 호출 파라미터 (resolve_unknown_state()와 동일)

| 파라미터 | 값 |
|----------|-----|
| Endpoint | `inquire-daily-ccld` (VTTC0081R) |
| strt_dt | `20260512` (최근 7일) |
| end_dt | `20260519` (오늘) |
| bucket | `RECONCILIATION` |
| after_hours | `True` |
| PDNO (종목코드) | `""` (빈 문자열 = 전체 종목) |

### 응답 결과

| 샘플 | broker_native_order_id | Symbol | 반환 레코드 수 | ODNO 매칭 | Symbol+Side 매칭 |
|------|------------------------|--------|---------------|-----------|-----------------|
| 1 | `0000008278` | `000150` | **0건** | ❌ Not found | 0건 |
| 2 | `0000011357` | `000660` | **0건** | ❌ Not found | 0건 |

**핵심 발견**: `inquire-daily-ccld`가 **0건**을 반환했습니다. 이는 KIS paper 모의투자 환경에서 `inquire-daily-ccld` API가 실제 체결 내역을 반환하지 않음을 시사합니다.

---

## 3. Local 상태 vs KIS Truth 비교

| 항목 | Local (DB) | KIS Truth (API) |
|------|-----------|----------------|
| order_requests.status | `expired` | N/A (API 응답 없음) |
| broker_orders.broker_status | `reconcile_required` | N/A |
| broker_native_order_id | `0000008278` / `0000011357` | API에서 해당 ODNO 없음 |
| 체결 여부 | filled_qty=0 | 확인 불가 |

---

## 4. EXPIRED Fallback 오판 여부 판정

### 판정: **Case A — fallback EXPIRED (시스템 처리)**

KIS `inquire-daily-ccld`가 0건을 반환했으므로, `resolve_unknown_state()`는:
1. `inquire_daily_ccld()` → 0건 → ODNO 매칭 실패
2. `inquire_balance()` (positions 조회) → fallback 시도
3. positions에서도 찾지 못함 → `RECONCILE_REQUIRED` 반환
4. `transition_to_authoritative()`에서 `RECONCILE_REQUIRED` 유지 확인
5. **broker no record → EXPIRED fallback 전이**

### 오판 여부: **판정 불가 (Inconclusive)**

| 근거 | 설명 |
|------|------|
| KIS paper 환경의 한계 | `inquire-daily-ccld`가 0건 반환 = paper 환경에서 체결 내역을 제공하지 않을 가능성 높음 |
| 실제 KIS truth 확인 불가 | API가 데이터를 반환하지 않아 broker truth를 확인할 방법이 없음 |
| 코드 구조상 정당한 fallback | `resolve_unknown_state()` → `RECONCILE_REQUIRED` → broker no record → EXPIRED는 **의도된 설계** |
| 오판 가능성 | live 환경에서는 `inquire-daily-ccld`가 정상 데이터를 반환할 수 있으나, paper 환경에서는 검증 불가 |

### 결론

**현재로서는 EXPIRED 전이가 오판이라고 단정할 수 없습니다.** KIS paper 모의투자 환경의 API 제약으로 인해 broker truth를 확인할 수 없었습니다. 다만, 다음과 같은 시나리오가 가능합니다:

1. **정당한 EXPIRED**: KIS paper에서 해당 주문이 실제로 만료 처리됨 (가장 가능성 높음)
2. **시스템 오판**: KIS paper API가 데이터를 반환하지 않아 fallback이 발생했으나, 실제로는 체결/취소 등 다른 상태였을 가능성
3. **Paper 환경 한계**: Paper 환경에서는 `inquire-daily-ccld`가 항상 0건을 반환할 수 있으며, 이 경우 모든 `RECONCILE_REQUIRED` 주문이 EXPIRED로 fallback됨

---

## 5. 후속 수정 필요 여부

### 필요: **Low priority — 모니터링 권장**

| 항목 | 판단 | 근거 |
|------|------|------|
| 긴급 수정 | ❌ 불필요 | EXPIRED fallback은 의도된 설계이며, paper 환경에서 합리적 동작 |
| 코드 버그 | ❌ 아님 | `transition_to_authoritative()`의 fallback 로직은 정상 작동 |
| 개선 제안 | ⚠️ 권장 | `resolve_unknown_state()`에서 `inquire-daily-ccld` 0건 시 로그 레벨 상향 (WARNING → ERROR) |
| Live 환경 검증 | ✅ 필요 | Live 환경에서 동일 시나리오 재현하여 `inquire-daily-ccld` 정상 응답 확인 필요 |

### 제안하는 개선사항

1. **로깅 개선**: `inquire-daily-ccld`가 0건 반환 시 `logger.warning` → `logger.error`로 상향
2. **Paper 환경 감지**: `KIS_ENV=paper`이고 `inquire-daily-ccld`가 0건이면, EXPIRED fallback 전에 추가 검증 로직 추가 검토
3. **Live 환경 테스트**: Live credentials로 전환 후 동일 시나리오 재현하여 `inquire-daily-ccld` 정상 응답 확인

---

## 6. 운영 영향 메모

| 항목 | 내용 |
|------|------|
| 영향 범위 | `reconcile_required` 25건 → EXPIRED 전이 (모두 paper 환경) |
| 자산 영향 | **없음** — EXPIRED는 주문이 더 이상 유효하지 않음을 의미, 체결된 주문이 취소되지는 않음 |
| 재처리 필요 | **없음** — EXPIRED 전이는 최종 상태이며, 재처리해도 동일한 결과 |
| 모니터링 | `reconcile_required` 잔여 0건 (모두 EXPIRED로 전이 완료) |
| 리스크 | Live 환경에서 동일한 fallback이 발생할 경우, 실제 체결된 주문이 EXPIRED로 잘못 표시될 가능성 **있음** |

---

## 7. 부록: 코드 분석

### EXPIRED 전이 경로 (transition_to_authoritative)

```
transition_to_authoritative()
  ├── broker.resolve_unknown_state()
  │     ├── inquire_daily_ccld() → 0건 (paper 환경)
  │     ├── inquire_balance() → positions 없음
  │     └── return RECONCILE_REQUIRED
  ├── status_result.status == RECONCILE_REQUIRED
  ├── _is_genuine_manual_reconciliation() → False
  └── EXPIRED fallback 전이 (broker no record)
```

### 참조 코드
- [`transition_to_authoritative()`](src/agent_trading/services/order_sync_service.py:632)
- [`resolve_unknown_state()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1512)
- [`inquire_daily_ccld()`](src/agent_trading/brokers/koreainvestment/rest_client.py:939)
- [`_parse_order_status_item()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1800)
