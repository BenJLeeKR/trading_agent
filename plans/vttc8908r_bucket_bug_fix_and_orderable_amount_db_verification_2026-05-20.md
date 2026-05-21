# VTTC8908R Bucket Bug Fix + `orderable_amount` DB 저장 검증 보고서

**작성일**: 2026-05-20  
**대상 파일**: [`src/agent_trading/brokers/koreainvestment/rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py)  
**관련 Enum**: [`src/agent_trading/brokers/rate_limit.py`](../src/agent_trading/brokers/rate_limit.py)

---

## 1. Executive Summary

| 항목 | 내용 |
|------|------|
| **버그 유형** | False success — 코드는 배포되었지만 실제로는 동작하지 않음 |
| **영향** | 모든 스냅샷 레코드의 `orderable_amount`가 `NULL`로 기록됨 |
| **근본 원인** | [`get_orderable_cash()`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1282) 내부에서 존재하지 않는 `BucketType.SNAPSHOT` enum 멤버 참조 + 필수 API 파라미터 누락 |
| **수정 사항** | `BucketType.SNAPSHOT` → `BucketType.INQUIRY` + `CMA_EVLU_AMT_ICLD_YN`, `OVRS_ICLD_YN` 파라미터 추가 |
| **검증 결과** | `orderable_amount = 0.000000`이 DB에 정상 저장됨 ✅ |

---

## 2. Bug Root Cause Analysis

### Issue 1: 유효하지 않은 BucketType 참조 (Primary)

[`BucketType`](../src/agent_trading/brokers/rate_limit.py:29) enum은 다음 멤버만 정의하고 있다:

```python
class BucketType(str, Enum):
    AUTH = "auth"
    ORDER = "order"
    INQUIRY = "inquiry"
    RECONCILIATION = "reconciliation"
    MARKET_DATA = "market_data"
    REST_GLOBAL = "global"
```

**`SNAPSHOT` 멤버는 존재하지 않는다.** 수정 전 코드는 다음과 같았다:

```python
# Before (broken):
data = await self._request(
    "GET",
    endpoint_key="inquire_psbl_order",
    tr_id_key="inquire_psbl_order",
    bucket=BucketType.SNAPSHOT,  # ← AttributeError: type object 'BucketType' has no attribute 'SNAPSHOT'
    params=params,
)
```

실행 시 `AttributeError`가 발생했고, 이 예외는 아래 `except Exception` 블록에서 조용히 삼켜졌다:

```python
except Exception:
    logger.warning(
        "Failed to fetch orderable cash via VTTC8908R",
        exc_info=True,
    )
    return None
```

### Issue 2: 필수 API 파라미터 누락 (Secondary)

올바른 BucketType을 사용하더라도, KIS API `VTTC8908R`은 다음 두 파라미터를 필수로 요구한다:

| 파라미터 | 설명 | 필수 여부 |
|----------|------|----------|
| `CMA_EVLU_AMT_ICLD_YN` | CMA평가금액포함여부 | ✅ 필수 |
| `OVRS_ICLD_YN` | 해외포함여부 | ✅ 필수 |

수정 전에는 이 두 파라미터가 누락되어 있었으며, 누락 시 KIS API는 `OPSQ2001: INPUT_FIELD_NAME ...` 오류를 반환한다.

### False Success 메커니즘

```
코드 배포 성공 → get_orderable_cash() 호출 → AttributeError 발생
→ except Exception이 None 반환 → 스냅샷에 orderable_amount = NULL 저장
→ "배포 완료"라고 생각했지만 실제로는 한 번도 정상 동작하지 않음
```

---

## 3. Applied Fix

### 변경 사항 요약

| 항목 | 수정 전 | 수정 후 |
|------|---------|---------|
| BucketType | `BucketType.SNAPSHOT` ❌ | `BucketType.INQUIRY` ✅ |
| `CMA_EVLU_AMT_ICLD_YN` | 누락 ❌ | `"N"` ✅ |
| `OVRS_ICLD_YN` | 누락 ❌ | `"N"` ✅ |

### 수정된 코드

[`rest_client.py` 라인 1282-1353](../src/agent_trading/brokers/koreainvestment/rest_client.py:1282)

```python
async def get_orderable_cash(
    self,
    account_ref: str = "",
    symbol: str = "",
    price: str = "",
    order_type: str = "00",  # 00=지정가
) -> Decimal | None:
    try:
        params = {
            "CANO": self.account_number,
            "ACNT_PRDT_CD": self.account_product_code,
            "PDNO": symbol,
            "ORD_DVSN": order_type,
            "ORD_UNPR": price,
            "CMA_EVLU_AMT_ICLD_YN": "N",  # ← 추가됨
            "OVRS_ICLD_YN": "N",          # ← 추가됨
        }

        data = await self._request(
            "GET",
            endpoint_key="inquire_psbl_order",
            tr_id_key="inquire_psbl_order",
            bucket=BucketType.INQUIRY,   # ← SNAPSHOT → INQUIRY
            params=params,
        )

        output = data.get("output", {})
        if isinstance(output, list):
            output = output[0] if output else {}

        ord_psbl_cash = output.get("ord_psbl_cash")
        if ord_psbl_cash is not None and str(ord_psbl_cash).strip():
            return Decimal(str(ord_psbl_cash))

        logger.info(
            "ord_psbl_cash not present in VTTC8908R response; "
            "orderable_amount will remain None"
        )
        return None

    except Exception:
        logger.warning(
            "Failed to fetch orderable cash via VTTC8908R",
            exc_info=True,
        )
        return None
```

---

## 4. Helper 직접 호출 검증

[`_test_orderable_cash.py`](../_test_orderable_cash.py) 스크립트를 통해 `get_orderable_cash()`를 직접 호출한 결과:

```
[get_orderable_cash() 반환값]
  type   : <class 'Decimal'>
  value  : 0

✅ 성공: Decimal('0') 반환됨
```

One-shot raw API 응답과 일치:

| 항목 | 값 |
|------|-----|
| API 응답 `ord_psbl_cash` | `"0"` |
| `get_orderable_cash()` 반환 | `Decimal('0')` |

---

## 5. DB 저장 검증

### 조회 쿼리

```sql
SELECT snapshot_at, available_cash, settled_cash, orderable_amount 
FROM cash_balance_snapshots 
ORDER BY snapshot_at DESC 
LIMIT 6;
```

### 결과 테이블

| # | snapshot_at (UTC) | available_cash | settled_cash | orderable_amount | 비고 |
|---|-------------------|---------------|-------------|-----------------|------|
| 1 | 00:15:13 | -81,419,050 | -6,629,580 | `NULL` | ❌ 수정 전 |
| 2 | 00:17:16 | -81,419,050 | -6,629,580 | `NULL` | ❌ 수정 전 |
| 3 | 00:17:47 | -81,419,050 | -6,629,580 | `NULL` | ❌ 수정 전 |
| 4 | 00:22:20 | -81,419,050 | -6,629,580 | `NULL` | ❌ 수정 전 |
| 5 | **00:29:08** | -81,419,050 | -6,629,580 | **`0.000000`** ✅ | **✅ 수정 후** |
| 6 | **00:29:41** | -81,419,050 | -6,629,580 | **`0.000000`** ✅ | **✅ 수정 후** |

### 분석

- **00:15 ~ 00:22 (4회)**: `orderable_amount = NULL` — 버그로 인해 API 호출 실패, `None`이 저장됨
- **00:29 (2회)**: `orderable_amount = 0.000000` — 버그 수정 후 정상 저장 확인 ✅

> **참고**: `available_cash`와 `settled_cash`는 `get_cash_balance()` (VTTC8434R)를 통해 정상 조회되었으며, 이 API는 `BucketType.INQUIRY`를 올바르게 사용하고 있었기 때문에 영향이 없었다.

---

## 6. Ops-scheduler 로그 확인

수정 후 스냅샷 사이클 로그에서 다음 항목 확인:

```
orderable_amount=0 (source: VTTC8908R)
```

이는 스냅샷 사이클이 정상적으로 `VTTC8908R`을 호출하여 `orderable_amount`를 획득하고, 이를 DB에 저장했음을 의미한다.

---

## 7. 테스트 결과

| 테스트 스위트 | 실행 | 결과 |
|--------------|------|------|
| `tests/brokers/koreainvestment/test_snapshot.py` | `pytest tests/brokers/koreainvestment/test_snapshot.py -v` | ✅ 15/15 |
| `tests/brokers/koreainvestment/test_rest_client_submit.py` | `pytest tests/brokers/koreainvestment/test_rest_client_submit.py -v` | ✅ 9/9 |
| `tests/brokers/test_rate_limit.py` | `pytest tests/brokers/test_rate_limit.py -v` | ✅ 15/15 |
| **Total** | | **✅ 39/39** |

---

## 8. Docker 배포

```bash
# 이미지 재빌드
docker compose build --no-cache   # ✅ 성공

# 컨테이너 재시작
docker compose up -d              # ✅ 성공

# 헬스체크
curl -s http://localhost/health
# → {"status":"ok","database":"connected"}  ✅
```

---

## 9. Lessons Learned

### False Success의 위험성

이번 버그는 "코드가 배포되었다"는 것과 "코드가 실제로 동작하고 있다"는 것이 완전히 별개의 문제임을 명확히 보여준다.

| 잘못된 신호 | 현실 |
|------------|------|
| ✅ 컨테이너 정상 기동 | ❌ `get_orderable_cash()`는 한 번도 성공하지 못함 |
| ✅ `/health` 응답 OK | ❌ 모든 스냅샷의 `orderable_amount`가 `NULL` |
| ✅ 테스트 39개 통과 | ❌ `BucketType.SNAPSHOT` 존재 여부를 검증하는 테스트 없음 |

### 구체적 교훈

1. **Exception handler가 `None`을 반환하면 버그가 은폐된다**  
   [`except Exception`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1348)이 모든 예외를 잡아 `None`을 반환하므로, `AttributeError`가 발생해도 로그에만 기록되고 상위 호출자는 실패를 인지할 수 없다.

2. **검증은 다층적으로 이루어져야 한다**  
   - ✅ 코드 리뷰 (정적 분석)
   - ✅ 단위 테스트 통과
   - ✅ Helper 직접 호출 (동적 검증)
   - ✅ DB 저장 확인 (E2E 검증)
   - 위 세 가지가 모두 확인되어야 "동작한다"고 말할 수 있다.

3. **Enum 멤버 사용 전 존재 여부를 검증하는 테스트가 필요하다**  
   `BucketType`에 예상 멤버가 존재하는지 확인하는 단위 테스트를 추가하면, 이런 유형의 버그를 컴파일 타임(혹은 테스트 타임)에 잡을 수 있다.

### 권장 액션

- [ ] `tests/brokers/test_rate_limit.py`에 `BucketType` 멤버 존재 여부를 검증하는 테스트 케이스 추가 (예: `assert hasattr(BucketType, 'INQUIRY')`)
- [ ] Exception handler가 `None`을 반환할 때, 최소한 `logger.error` 수준으로 기록하거나 메트릭을 발생시키도록 개선
- [ ] 스냅샷 데이터 품질 모니터링: 일정 기간 `orderable_amount`가 계속 `NULL`이면 알람 발생

---

## 10. 참고 링크

| 항목 | 경로 |
|------|------|
| 버그 수정 코드 | [`rest_client.py:1282-1353`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1282) |
| BucketType enum 정의 | [`rate_limit.py:29-41`](../src/agent_trading/brokers/rate_limit.py:29) |
| 직접 호출 테스트 스크립트 | [`_test_orderable_cash.py`](../_test_orderable_cash.py) |
| 스냅샷 테스트 | [`tests/brokers/koreainvestment/test_snapshot.py`](../tests/brokers/koreainvestment/test_snapshot.py) |
| Rate limit 테스트 | [`tests/brokers/test_rate_limit.py`](../tests/brokers/test_rate_limit.py) |
| Rest client submit 테스트 | [`tests/brokers/koreainvestment/test_rest_client_submit.py`](../tests/brokers/koreainvestment/test_rest_client_submit.py) |
| KIS API 레퍼런스 (VTTC8908R) | [`reference_docs/kis_openapi_full_20260503_markdown/006_투자계좌자산현황조회.md`](../reference_docs/kis_openapi_full_20260503_markdown/006_투자계좌자산현황조회.md) |
