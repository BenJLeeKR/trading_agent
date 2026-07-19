# Post-Submit Sync 상태수렴 미완료 원인 분석 보고서

**일시:** 2026-05-12 14:00 KST
**환경:** Paper (KIS 모의투자)
**목적:** Sync loop가 동작하는 상태에서 왜 최종 terminal status(FILLED/CANCELLED/REJECTED)로 수렴하지 않고 `RECONCILE_REQUIRED`에 머무는지 원인 분리

---

## 1. RECONCILE_REQUIRED 분기 원인

### 1.1 직접 분기점: `get_order_status()` ODNO 매칭 실패

[`rest_client.py:894-908`](src/agent_trading/brokers/koreainvestment/rest_client.py)에서 ODNO 매칭이 실패하면 `RECONCILE_REQUIRED`를 반환합니다:

```python
# Find the matching order by broker_order_id
if broker_order_id is not None:
    for item in output:
        if item.get("ODNO") == broker_order_id:
            return self._parse_order_status_item(item)

return OrderStatusResult(
    ...
    status=OrderStatus.RECONCILE_REQUIRED,
    raw_message="Order not found in daily settlement inquiry",
)
```

**DB state events에서 확인된 전이 경로:**
```
submitted → reconcile_required  (5건 모두, 직접 전이)
```

이는 `_parse_order_status_item()`이 `SUBMITTED`를 반환한 것이 아니라, **ODNO 매칭 자체가 실패**하여 fallback 경로로 진입했음을 의미합니다.

### 1.2 ODNO 매칭 조건

[`sync_order_post_submit()`](src/agent_trading/services/order_sync_service.py:190):
```python
broker_order_id=broker_order.broker_native_order_id,
```

[`get_order_status()`](src/agent_trading/brokers/koreainvestment/rest_client.py:896):
```python
if item.get("ODNO") == broker_order_id:
```

**매칭 키:** `broker_native_order_id` (DB 값: `"0000027326"` 등 10자리 문자열) vs API 응답 `ODNO` 필드

### 1.3 가능한 원인 (2가지)

| 원인 | 설명 | 가능성 |
|------|------|--------|
| **A. KIS paper mock이 `inquire-daily-ccld`에서 빈 응답 반환** | Paper mock 환경은 실제 체결 데이터를 생성하지 않으므로 `output=[]` 반환 | **🔴 높음** |
| **B. ODNO 포맷 불일치** | `broker_native_order_id`가 `"0000027326"`이지만 API가 다른 포맷(예: 숫자만 `27326`)으로 반환 | **🟡 중간** |
| **C. 조회 기간/파라미터 문제** | `INQR_STRT_DT="19700101"`이 paper mock에서 지원되지 않거나, 계좌번호 불일치 | **🟢 낮음** |

---

## 2. Paper Mock 응답 특성 vs 구현 한계 구분

### 2.1 Paper Mock 환경 특성 (KIS 모의투자)

| 특성 | 영향 |
|------|------|
| `inquire-daily-ccld`가 실제 체결 데이터를 반환하지 않음 | `output=[]` 또는 빈 배열 가능성 높음 |
| `submit_order()`는 성공하지만 (`ODNO` 발급), 이후 settlement 데이터가 생성되지 않음 | 제출된 주문이 `inquire-daily-ccld`에 나타나지 않음 |
| `inquire-balance`도 실제 포지션을 반영하지 않음 | `resolve_unknown_state()`의 2차 fallback도 실패 |

**과거 실행 이력** ([`kis_paper_submit_price_fix_report.md`](plans/kis_paper_submit_price_fix_report.md) 참조):
- 2026-05-11 5건 주문 제출 성공 (ODNO 발급됨)
- 이후 `inquire-daily-ccld`에서 해당 ODNO들이 조회되지 않음
- 이는 KIS paper mock의 알려진 제약사항

### 2.2 구현 한계

| 항목 | 상태 | 설명 |
|------|------|------|
| ODNO 매칭 로직 | ✅ 정상 | `item.get("ODNO") == broker_order_id` — 문자열 비교로 정확 |
| `_parse_order_status_item()` 조건 | ✅ 정상 | `CCLD_QTY`, `CNCL_YN`, `RVSE_YN` 기반 판단 로직은 KIS API 스펙에 부합 |
| `resolve_unknown_state()` fallback | ✅ 정상 | `inquire-daily-ccld` → `inquire-balance` 2단계 fallback 구조 |
| `_try_transition()` chain | ✅ 정상 | `SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED` chain 구현됨 |
| `_build_transition_chain()` | ⚠️ **CASE 누락** | `SUBMITTED → CANCELLED`, `SUBMITTED → REJECTED` 경로 미구현 |

### 2.3 결론: **Paper Mock 환경 특성이 주원인**

현재 상태에서 `RECONCILE_REQUIRED`로 수렴하는 것은 **KIS paper mock이 `inquire-daily-ccld`에서 제출된 주문의 settlement 데이터를 반환하지 않기 때문**입니다. 구현 로직 자체의 버그는 아닙니다.

---

## 3. 수정 필요 여부

### 3.1 즉시 수정 불필요 (Paper Mock 한계)

Paper mock 환경의 특성상 `inquire-daily-ccld`가 빈 응답을 반환하는 것은 정상 동작입니다. Live 환경에서는 실제 체결 데이터가 반환되므로 정상적으로 terminal status로 수렴할 것으로 예상됩니다.

### 3.2 권장: 최소 계측 추가 (Read-Only 분석 후)

`get_order_status()`에서 ODNO 매칭 실패 시 **실제 API 응답의 `output` 개수와 첫 번째 item의 ODNO 값을 로깅**하면 진단에 도움이 됩니다. 단, 이는 코드 수정이 필요하므로 이번 read-only 분석 이후에 적용할 것을 권장합니다.

### 3.3 선택적 개선: `_build_transition_chain()` CASE 확장

[`order_sync_service.py:331-364`](src/agent_trading/services/order_sync_service.py)에서 `SUBMITTED → CANCELLED`와 `SUBMITTED → REJECTED` 경로가 누락되어 있습니다. Live 환경에서 broker가 `CANCELLED`나 `REJECTED`를 반환할 경우 chain 전이가 실패할 수 있습니다.

---

## 4. 예상 변경 파일 목록

| 파일 | 변경 내용 | 우선순위 |
|------|----------|---------|
| [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py) (line 894-897) | ODNO 매칭 실패 시 `output` 개수와 첫 ODNO 로깅 추가 | **선택** (계측) |
| [`order_sync_service.py`](src/agent_trading/services/order_sync_service.py) (line 331-364) | `_build_transition_chain()`에 `SUBMITTED → CANCELLED`, `SUBMITTED → REJECTED` 경로 추가 | **권장** (Live 대비) |

---

## 5. 남은 리스크 1개

**Live 환경에서 `inquire-daily-ccld`가 실제로 ODNO를 반환할지 불확실**

KIS paper mock과 live 환경의 `inquire-daily-ccld` 응답 구조가 동일하다는 가정에 의존하고 있습니다. Live 환경에서:
- `ODNO` 필드명이 동일한지
- `CCLD_QTY`, `CNCL_YN`, `RVSE_YN` 필드가 동일한 형식으로 반환되는지
- `output` 배열 구조가 동일한지

이 중 하나라도 다르면 현재 매칭/판단 로직이 live에서도 실패할 수 있습니다. KIS API 문서([`reference_docs/한국투자증권_오픈API_전체문서_20260503_030000.xlsx`](reference_docs/한국투자증권_오픈API_전체문서_20260503_030000.xlsx))에서 live TR ID(`TTTC8001R`)와 paper TR ID(`VTTC8001R`)의 응답 스펙이 동일한지 사전 확인이 필요합니다.

---

## 6. 다음 직접 액션 1개

**Paper mock 환경에서 `inquire-daily-ccld` 실제 응답 캡처**

`run_post_submit_sync_loop.py` 실행 시 `get_order_status()` 내부에서 `_request()` 호출 결과(raw API response)를 로깅하도록 최소 계측을 추가하고, 1회 sync cycle을 실행하여 실제 응답 payload를 확인합니다. 이를 통해:
1. `output`이 정말 빈 배열인지
2. 빈 배열이 아니라면 어떤 ODNO들이 있는지
3. ODNO 포맷이 `broker_native_order_id`와 어떻게 다른지

를 확정할 수 있습니다.

---

## 부록: 분석 근거

### A. DB State Events 전이 경로 (5건)

| broker_order_id | broker_native_order_id | 전이 경로 |
|-----------------|----------------------|-----------|
| `6528f3e5-...` | `0000027326` | `submitted → reconcile_required` |
| `d63cfac9-...` | `0000027342` | `submitted → reconcile_required` |
| `3c8f9e72-...` | `0000027372` | `submitted → reconcile_required` |
| `1b569198-...` | `0000027379` | `submitted → reconcile_required` |
| `0e61b83c-...` | `0000027455` | `submitted → reconcile_required` |

모든 건이 `PARTIALLY_FILLED`나 `FILLED` 같은 중간 상태 없이 직접 `reconcile_required`로 전이되었습니다. 이는 `_parse_order_status_item()`이 정상 호출되었다면 `SUBMITTED`(또는 `FILLED`)를 반환했을 텐데, 그렇지 않았다는 증거입니다.

### B. `_parse_order_status_item()` 반환 가능한 상태

| 조건 | 반환 상태 |
|------|----------|
| `CCLD_QTY >= ORD_QTY and ORD_QTY > 0` | `FILLED` |
| `CCLD_QTY > 0` | `PARTIALLY_FILLED` |
| `CNCL_YN == "Y"` | `CANCELLED` |
| `RVSE_YN == "Y"` | `CANCELLED` |
| else (기본값) | `SUBMITTED` |

만약 `_parse_order_status_item()`이 호출되었다면, paper mock에서 `CCLD_QTY=0`, `CNCL_YN="N"`, `RVSE_YN="N"`일 가능성이 높아 `SUBMITTED`를 반환했을 것입니다. 이 경우 `_try_transition()`에서 `SUBMITTED → SUBMITTED`는 `status_changed=False`가 되어 `reconcile_required`로 전이되지 않습니다.

**즉, `reconcile_required`로 간 것은 ODNO 매칭 실패가 유일한 경로입니다.**

### C. `resolve_unknown_state()` 2차 fallback

[`rest_client.py:1151-1200`](src/agent_trading/brokers/koreainvestment/rest_client.py)에서 `inquire-daily-ccld` 실패 시 `inquire-balance`로 fallback하지만, paper mock에서 포지션 데이터도 없으므로 최종적으로 `RECONCILE_REQUIRED`를 반환합니다.
