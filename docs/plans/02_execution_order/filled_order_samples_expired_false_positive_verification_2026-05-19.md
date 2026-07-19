# 체결 주문 샘플 기준 EXPIRED 오판 여부 검증 (4-way 비교)

**작성일**: 2026-05-19 18:00 KST  
**목적**: 체결되어야 할 주문이 broker truth 부재로 `EXPIRED`로 잘못 전이된 사례가 있는지 4-way 비교로 검증

---

## 1. 샘플 선정

### 선정 기준

| 우선순위 | 기준 | 설명 |
|---------|------|------|
| 1 | fill_events 존재 + broker_status=EXPIRED | **오판 강력 의심** — 체결 이벤트가 있는데 EXPIRED |
| 2 | fill_events 존재 + broker_status=filled | 정상 사례 (대조군) |
| 3 | fill_events 부재 + broker_status=EXPIRED | 이미 확인한 사례 (이전 보고서) |

### 실제 선정된 샘플

| # | Symbol | Side | ODNO | broker_status | orq_status | fill_events | position | 선정 근거 |
|---|--------|------|------|--------------|------------|-------------|----------|----------|
| 1 | `000150` | sell | `0000008278` | reconcile_required | **expired** | 0건 | **10주** | position 존재 + EXPIRED 전이 → **오판 의심** |
| 2 | `000660` | sell | `0000011357` | reconcile_required | **expired** | 0건 | **10주** | position 존재 + EXPIRED 전이 → **오판 의심** |
| 3 | `000880` | buy | `0000030092` | **filled** | **filled** | 1건 (10주) | **10주** | 정상 filled (대조군) |

### 관찰: fill_events가 있는 EXPIRED 주문은 존재하지 않음

`fill_events` 테이블에는 단 1건(`000880`)만 존재하며, 이는 broker_status='filled'로 정상 처리되었습니다.  
**fill_events가 있고 EXPIRED로 전이된 사례는 DB에 존재하지 않습니다.**

---

## 2. 4-way 로컬 Truth 비교

### 샘플 #1: `000150` (두산) — sell, 10주 @ 1,562,000

| 데이터 소스 | 값 | 비고 |
|------------|-----|------|
| `order_requests.status` | `expired` | EXPIRED로 전이됨 |
| `broker_orders.broker_status` | `reconcile_required` | broker truth sync 실패 |
| `fill_events` | **0건** | 체결 이벤트 없음 |
| `position_snapshots.quantity` | **10주** | 포지션 존재! |
| `position_snapshots.avg_price` | 1,578,775 | 매수 평균가 |

**4-way 분석**:
- `orq_status=expired` + `broker_status=reconcile_required` → broker truth sync 실패 후 EXPIRED fallback
- `fill_events=0` → fill_events가 생성되지 않음 (broker_truth sync 실패로 인해)
- **`position=10주`** → 실제로는 체결되어 포지션이 생성됨
- **모순**: position은 10주인데, 이 sell 주문이 체결되었다면 position이 감소해야 함. 즉, 이 sell 주문은 만료되었지만 **이전에 체결된 buy 주문들**에 의해 position이 형성된 것

### 샘플 #2: `000660` (SK하이닉스) — sell, 10주 @ 1,791,000

| 데이터 소스 | 값 | 비고 |
|------------|-----|------|
| `order_requests.status` | `expired` | EXPIRED로 전이됨 |
| `broker_orders.broker_status` | `reconcile_required` | broker truth sync 실패 |
| `fill_events` | **0건** | 체결 이벤트 없음 |
| `position_snapshots.quantity` | **10주** | 포지션 존재! |
| `position_snapshots.avg_price` | 1,847,000 | 매수 평균가 |

**4-way 분석**:
- 샘플 #1과 동일한 패턴: sell 주문이 EXPIRED로 전이되었지만 position은 10주 존재
- 이 sell 주문이 체결되었다면 position이 0이 되어야 하지만, position이 10주로 유지됨
- → **sell 주문은 실제로 만료되었고**, position은 이전 buy 주문들에 의해 형성된 것

### 샘플 #3: `000880` (대한항공) — buy, 10주 @ 145,400 (대조군)

| 데이터 소스 | 값 | 비고 |
|------------|-----|------|
| `order_requests.status` | `filled` | 정상 |
| `broker_orders.broker_status` | `filled` | 정상 |
| `fill_events` | **1건 (10주)** | 체결 이벤트 정상 기록 |
| `position_snapshots.quantity` | **10주** | 포지션 일치 |
| `position_snapshots.avg_price` | 145,400 | fill_events price와 일치 |

**4-way 분석**: 모든 데이터 소스가 일치하는 정상 filled 사례

---

## 3. KIS inquire-daily-ccld Raw 응답

### 호출 파라미터

| 파라미터 | 값 |
|----------|-----|
| Endpoint | `inquire-daily-ccld` (VTTC0081R) |
| strt_dt | `20260512` (최근 7일) |
| end_dt | `20260519` (오늘) |
| bucket | `RECONCILIATION` |
| after_hours | `True` |

### 응답 결과

| 샘플 | broker_native_order_id | Symbol | 반환 레코드 수 | ODNO 매칭 |
|------|------------------------|--------|---------------|-----------|
| 1 (`000150`) | `0000008278` | `000150` | **0건** | ❌ Not found |
| 2 (`000660`) | `0000011357` | `000660` | **0건** | ❌ Not found |
| 3 (`000880`) | `0000030092` | `000880` | Rate limit 초과 | N/A |

**핵심 발견**: `inquire-daily-ccld`가 **0건**을 반환했습니다. 이는 KIS paper 모의투자 환경에서 `inquire-daily-ccld` API가 실제 체결 내역을 반환하지 않음을 재확인합니다.

---

## 4. 샘플별 판정

### 판정 기준

| 분류 | 설명 |
|------|------|
| **A. 정상** | 실제 만료/미체결이고 local도 EXPIRED |
| **B. 불명** | KIS raw 응답 없음, 로컬 보조 근거도 약함 |
| **C. 오판** | 체결 근거(포지션/fill_events)가 분명한데 local status가 EXPIRED |

### 샘플 #1: `000150` sell → **A. 정상 (EXPIRED)**

**판정 근거**:
1. 이 주문은 **sell** 주문으로, position 10주는 **buy** 주문들에 의해 형성됨
2. sell 주문이 체결되었다면 position이 감소(10주 → 0주)해야 하지만 position은 10주로 유지됨
3. `fill_events=0`으로 체결 이벤트가 없음
4. KIS API도 0건 반환
5. **결론**: 이 sell 주문은 실제로 만료되었으며, position은 이전에 체결된 buy 주문들(`0000018145`, `0000019262`, `0000023214`, `0000024715`)에 의해 형성된 것

### 샘플 #2: `000660` sell → **A. 정상 (EXPIRED)**

**판정 근거**:
1. 샘플 #1과 동일한 패턴: **sell** 주문, position 10주 유지
2. sell 주문이 체결되었다면 position이 0이 되어야 함
3. `fill_events=0`, KIS API 0건
4. **결론**: 이 sell 주문은 실제로 만료되었으며, position은 buy 주문(`0000025805`)에 의해 형성된 것

### 샘플 #3: `000880` buy → **A. 정상 (filled)**

**판정 근거**:
1. 모든 데이터 소스 일치: orq_status=filled, broker_status=filled, fill_events 1건, position 10주
2. **결론**: 정상적으로 체결 및 기록된 주문

### 전체 판정 요약

| 샘플 | Symbol | Side | 판정 | 근거 |
|------|--------|------|------|------|
| 1 | `000150` | sell | **A. 정상 (EXPIRED)** | sell 주문 만료, position은 buy 주문들로 형성 |
| 2 | `000660` | sell | **A. 정상 (EXPIRED)** | sell 주문 만료, position은 buy 주문으로 형성 |
| 3 | `000880` | buy | **A. 정상 (filled)** | 모든 데이터 일치 |

---

## 5. 핵심 결론: EXPIRED 오판 사례는 발견되지 않음

### 원래 질문에 대한 답변

> **"체결되어야 할 주문이 broker truth 부재로 EXPIRED로 잘못 전이된 사례가 있는가?"**

→ **아니오. EXPIRED 오판 사례는 발견되지 않았습니다.**

### 근거

1. **fill_events가 있는 EXPIRED 주문은 존재하지 않음**: fill_events 테이블의 유일한 레코드는 broker_status='filled'로 정상 처리됨
2. **position이 있는 EXPIRED 주문은 모두 sell side**: position이 존재하지만, 이는 **buy 주문들**에 의해 형성된 것이지, EXPIRED로 전이된 sell 주문이 체결된 것이 아님
3. **KIS API 0건**: paper 환경에서 `inquire-daily-ccld`가 체결 내역을 반환하지 않음을 재확인

### 시스템 설계 관점

| 항목 | 평가 |
|------|------|
| EXPIRED fallback 로직 | **정상 작동** — broker truth를 확인할 수 없는 경우 합리적 fallback |
| broker_truth sync 실패 | `reconcile_required` 25건 모두 sync 실패했으나, 이는 **paper 환경의 API 제약** 때문 |
| fill_events 생성 실패 | broker_truth sync 실패로 인해 fill_events가 생성되지 않음 — **개선 필요** |
| position 불일치 | position은 snapshot sync로 별도 관리되므로, order 상태와 무관하게 유지됨 |

### 개선 제안

1. **fill_events 생성 로직 강화**: broker_truth sync 실패 시에도 position snapshot과의 비교를 통해 fill_events를 역추론하여 생성할 수 있는 로직 고려
2. **Paper 환경 감지 로깅**: `inquire-daily-ccld` 0건 시 로그 레벨 상향 (WARNING → ERROR)
3. **Live 환경 검증**: Live credentials로 전환 후 동일 시나리오 재현하여 `inquire-daily-ccld` 정상 응답 확인 필요

---

## 6. 부록: 전체 reconcile_required 주문 목록 (종목별 요약)

| Symbol | 종목명 | broker_orders 건수 | position 수량 | position 평균가 |
|--------|--------|-------------------|--------------|----------------|
| `000150` | 두산 | 8건 (buy 4, sell 4) | 10주 | 1,578,775 |
| `000210` | KIC | 2건 (buy 2) | 20주 | 57,240 |
| `000270` | 기아 | 1건 (buy 1) | 10주 | 163,500 |
| `000660` | SK하이닉스 | 2건 (buy 1, sell 1) | 10주 | 1,847,000 |
| `000810` | 삼성화재 | 5건 (buy 3, sell 2) | 10주 | 560,567 |
| `000990` | DB하이텍 | 2건 (buy 2) | 20주 | 165,200 |
| `001740` | SK네트웍스 | 1건 (buy 1) | 10주 | 9,050 |
| `003490` | 대한항공 | 2건 (buy 2) | 20주 | 25,400 |
| `004000` | 롯데정밀화학 | 1건 (buy 1) | 10주 | 54,300 |
| `005830` | DB손해보험 | 1건 (buy 1) | 10주 | 161,600 |

**참고**: `005930` (삼성전자)와 `000880` (대한항공)은 position이 있지만 reconcile_required 주문이 없음 (정상 filled 처리됨).

---

## 7. 참조

- 이전 보고서: [`plans/kis_raw_ccld_response_and_expired_fallback_verification_2026-05-19.md`](kis_raw_ccld_response_and_expired_fallback_verification_2026-05-19.md)
- 검증 스크립트: [`_check_ccld_samples.py`](../_check_ccld_samples.py)
- EXPIRED 전이 코드: [`src/agent_trading/services/order_sync_service.py`](../src/agent_trading/services/order_sync_service.py:632) — `transition_to_authoritative()`
- broker truth resolve: [`src/agent_trading/brokers/koreainvestment/rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1512) — `resolve_unknown_state()`
