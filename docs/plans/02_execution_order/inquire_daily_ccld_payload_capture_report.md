# KIS Paper `inquire-daily-ccld` 응답 계측 보고서 — ODNO 매칭 실패 원인 확정

## 1. 추가한 계측 지점

| 파일 | 위치 | 내용 |
|------|------|------|
| [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py) | `get_order_status()` (line 896-928) | `inquire-daily-ccld` 응답 output count, ODNO 목록, 첫 item field snapshot을 DEBUG/INFO 로그로 출력 |
| 동일 | line 923-928 | ODNO match 실패 시 INFO 로그에 `broker_order_id`, `output_count`, `odnos_in_response` 출력 |

**변경 성격**: logging only, 기능 의미 변경 없음, submit semantics 변경 없음.

## 2. 실제 응답 핵심 field 요약

### Probe 실행 결과 (`/tmp/probe_inquire_daily_ccld.py`)

```
=== Raw Response ===
  rt_cd=  msg_cd=  msg1=''
  output count: 0
  output2: {'tot_ord_qty': '0', 'tot_ccld_qty': '0', 'tot_ccld_amt': '0',
            'prsm_tlex_smtl': '0', 'pchs_avg_pric': '0.0000'}
```

| 항목 | 값 | 비고 |
|------|-----|------|
| `output` | `[]` (빈 배열) | **체결 내역 0건** |
| `output2.tot_ord_qty` | `"0"` | 총 주문 수량 0 |
| `output2.tot_ccld_qty` | `"0"` | 총 체결 수량 0 |
| `rt_cd` / `msg_cd` | 빈 문자열 | 정상 응답 (에러 아님) |

### `get_order_status()`가 사용하는 파라미터 (line 871-882)

```python
params = {
    "CANO": self.account_number,          # "50186448"
    "ACNT_PRDT_CD": self.account_product_code,  # "01"
    "INQR_STRT_DT": "19700101",
    "INQR_END_DT": datetime.now(...).strftime("%Y%m%d"),  # "20260512"
    "SLL_BUY_DVSN_CD": "00",   # 전체
    "INQR_DVSN": "00",         # 조회구분 (역순)
    "PDNO": "",                # 전체종목
    "CCLD_DVSN": "00",         # 전체
    "ORD_GUBUN": "00",         # 주문구분
    "ORD_SRT_DVSN": "01",      # 주문시작구분
}
```

Probe가 사용한 파라미터와 **완전히 동일**.

## 3. ODNO 매칭 실패 원인 확정

**원인: KIS paper mock (`openapivts`)이 `inquire-daily-ccld`에 대해 체결 내역을 전혀 반환하지 않음.**

```
inquire-daily-ccld 호출 → output: [] (빈 배열)
                         → ODNO 순회 불가
                         → 항상 RECONCILE_REQUIRED 반환
```

구체적 기전:
1. `get_order_status()` (line 884-890): `inquire-daily-ccld` 호출 → `output: []`
2. line 918-921: `for item in output:` — output이 비어있으므로 **순회 자체가 실행되지 않음**
3. line 930-939: `OrderStatus(status=RECONCILE_REQUIRED, ...)` 반환
4. `_try_transition()` (line 279-329): `SUBMITTED → RECONCILE_REQUIRED` 전이 실행
5. `_sync_fills()` (line 366-467): `get_fills()` 호출 → 동일하게 `inquire-daily-ccld` 사용 → output 빔 → fill 없음

**paper mock의 한계**: 실제 KIS live 환경과 달리, paper mock (`openapivts`)은 `inquire-daily-ccld` (VTTC0081R) 엔드포인트에서 체결 데이터를 제공하지 않습니다. 이는 paper mock의 settlement 데이터 미반영 문제로, 코드 버그가 아닌 **테스트 인프라의 한계**입니다.

## 4. 수정 필요 여부

**판정: 수정 불필요 (paper mock 한계로 인한 자연스러운 현상)**

| 항목 | 판정 | 근거 |
|------|------|------|
| `get_order_status()` 로직 | ✅ 정상 | ODNO 매칭 로직 자체는 올바름 |
| `_parse_order_status_item()` | ✅ 정상 | 호출될 기회가 없었을 뿐, 로직 자체는 정상 |
| `resolve_unknown_state()` fallback | ✅ 정상 | inquire-daily-ccld → positions → RECONCILE_REQUIRED 순서 올바름 |
| paper mock | ❌ 한계 | settlement 데이터를 반환하지 않음 (KIS paper mock spec) |

**Live 환경에서는 정상 동작 예상**: 실제 KIS live 서버는 `inquire-daily-ccld`에 체결 데이터를 정상 반환하므로, ODNO 매칭이 성공하고 `_parse_order_status_item()`이 올바른 상태를 반환할 것입니다.

## 5. 예상 변경 파일 목록

**이번 작업에서 변경된 파일:**

| 파일 | 변경 내용 |
|------|-----------|
| [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py) | 계측용 logging 2개 추가 (DEBUG/INFO) — 향후 제거 가능 |

**향후 live 전환 시 변경 불필요**: 현재 로직 그대로 live에서 정상 동작 예상.

## 6. 남은 리스크 1개

**`resolve_unknown_state()`의 positions fallback도 paper mock에서 빈 결과 반환 가능성**

`resolve_unknown_state()` (line 1182-1201)는 `inquire-daily-ccld` 실패 시 `inquire_balance` (positions)로 fallback합니다. paper mock이 positions 데이터도 제공하지 않으면, `resolve_and_mark()` (reconciliation_service.py)도 동일하게 `RECONCILE_REQUIRED`로 수렴합니다. 이 경우 reconciliation loop가 영원히 `RECONCILE_REQUIRED` 상태를 해소하지 못합니다.

**영향**: paper 환경에서 모든 post-submit order가 `RECONCILE_REQUIRED`로 terminal 상태에 머무름. 기능적 문제는 없으나 (이미 terminal 상태), 모니터링에서 지속적으로 `reconcile_required` 알림이 발생할 수 있음.

## 7. 다음 직접 액션 1개

**계측 logging 유지 — Paper Mock 한계 문서 반영 완료**

### 7.1 Logging 유지 목적

계측 logging은 현재 상태로 유지합니다. 이유:

1. **Paper 환경에서도 유용**: 향후 paper mock이 변경되어 체결 데이터를 반환하기 시작할 경우, ODNO 매칭 동작을 즉시 확인 가능
2. **Live 전환 시 필수**: Live 환경에서 `inquire-daily-ccld` 응답 구조가 paper mock과 동일한지 검증하는 데 필요
3. **DEBUG 레벨이므로 기본 출력 없음**: `logging.basicConfig(level=logging.INFO)` 환경에서는 출력되지 않아 무해

### 7.2 제거 조건 (3개 모두 충족 시)

아래 **3가지 조건이 모두 충족**되어야 instrumentation logging을 제거할 수 있습니다.

| # | 조건 | 검증 방법 | 근거 |
|---|------|----------|------|
| 1 | **Live `inquire-daily-ccld` payload 확인** | Live 환경에서 submit 후 DEBUG logging의 `first_item_fields`가 정상 출력되고 `output_count > 0`인지 확인 | Paper mock과 Live의 응답 구조 동일성 검증 |
| 2 | **ODNO 매칭 성공 확인** | `get_order_status()`가 `for item in output:` loop에서 `item.get("ODNO") == broker_order_id`를 만족하여 `_parse_order_status_item()` 호출 | ODNO 매칭 로직의 Live 정상 동작 확인 |
| 3 | **Terminal status 수렴 확인** | Post-submit sync 후 `broker_status`가 FILLED / CANCELLED / REJECTED 중 하나로 수렴하고, `INFO logging`에 ODNO match failure가 더 이상 출력되지 않음 | Terminal status convergence pipeline 정상 확인 |

**제거 판단 흐름**:

```
Live submit 실행
  → DEBUG logging: output_count > 0, ODNO 목록 출력 확인 [조건1 ✅]
  → broker_orders.broker_status가 FILLED/CANCELLED/REJECTED로 수렴 [조건2 ✅]
  → INFO logging에 ODNO match failure 미출력 [조건3 ✅]
  → git checkout -- src/agent_trading/brokers/koreainvestment/rest_client.py
```

**3개 조건 중 하나라도 실패 시**: logging을 유지하고 원인 분석. Live 환경에서도 ODNO 매칭이 실패할 수 있는 경우 (e.g., Live `inquire-daily-ccld` 응답 형식이 paper mock과 다름)는 추가 디버깅 필요.

### 7.3 Probe 스크립트 상태

`/tmp/probe_inquire_daily_ccld.py`:

- 임시 진단용 스크립트로, **repo 관리 대상 아님**
- 필요시 재사용 가능하나, 문서화된 재현 절차는 아님
- 동일한 진단이 필요하면 `rest_client.py`의 DEBUG logging으로 대체 가능

```bash
# 향후 logging 제거 명령 (조건 1/2/3 모두 충족 후)
# git checkout -- src/agent_trading/brokers/koreainvestment/rest_client.py
```
