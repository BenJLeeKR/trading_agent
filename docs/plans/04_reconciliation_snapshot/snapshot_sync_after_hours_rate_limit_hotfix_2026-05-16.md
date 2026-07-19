# Phase 16: snapshot-sync after-hours rate-limit hotfix

- **일자**: 2026-05-16
- **작업명**: snapshot-sync after-hours rate-limit hotfix
- **목표**: after-hours 모드에서 KIS `inquire-balance` endpoint 중복 호출로 인한 `EGW00201` (초당 거래건수 초과) rate-limit 오류 제거

---

## 1. 개요

`snapshot-sync` 컨테이너가 after-hours 모드에서 동일 KIS endpoint (`inquire-balance`)를 2회 연속 호출하여 KIS rate-limit(`EGW00201`)에 도달, `HTTP 500` 오류를 유발하는 현상을 해결하였다. after-hours에는 positions가 변하지 않는다는 점을 활용하여 `get_positions()` 호출을 생략하고 cash-only sync로 전환함으로써 rate-limit을 회피하였다.

---

## 2. Root Cause 분석

### 문제 증상

- `snapshot-sync` 컨테이너에서 `HTTP 500 Internal Server Error` 발생
- 응답 본문: `msg_cd=EGW00201` — **초당 거래건수 초과**
- 결과: `cash=0` 또는 `positions=0` 반환 → `CASH_SYNC_ZERO` guardrail 발동 → stale-snapshot 상태 유발

### 근본 원인

[`KISSyncSnapshotProvider.fetch_snapshot()`](src/agent_trading/brokers/koreainvestment/snapshot.py:58)가 after-hours 모드에서 동일 KIS endpoint를 2연타 호출:

```python
# Step 1 (L93): get_positions() → inquire-balance, AFHR_FLPR_YN="N"
raw_positions = await self._rest.get_positions()

# Step 2 (L149): get_cash_balance(after_hours=True) → inquire-balance, AFHR_FLPR_YN="Y"
raw_cash = await self._rest.get_cash_balance(after_hours=True)
```

| 호출 | endpoint | AFHR_FLPR_YN |
|------|----------|-------------|
| `get_positions()` | `/uapi/domestic-stock/v1/trading/inquire-balance` | `"N"` |
| `get_cash_balance(after_hours=True)` | 동일 | `"Y"` |

KIS rate-limit은 endpoint 단위로 적용된다. 동일 초에 `inquire-balance`를 2회 연속 호출하면 `EGW00201`(초당 거래건수 초과)가 발생한다.

---

## 3. 변경 사항 상세

### 3.1 [`src/agent_trading/brokers/koreainvestment/snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py)

`after_hours=True` 시 `get_positions()` 호출을 완전히 생략한다. after-hours에는 positions가 변하지 않으므로 cash-only sync로 충분하다.

**변경 전:**
```python
try:
    raw_positions = await self._rest.get_positions()
except Exception as exc:
    logger.warning(
        "fetch_snapshot: get_positions() failed — %s: %s",
        type(exc).__name__, exc,
    )
    raw_positions = []
```

**변경 후:**
```python
if after_hours:
    logger.info("After-hours mode — skipping positions fetch (cash-only sync)")
    raw_positions = []
else:
    try:
        raw_positions = await self._rest.get_positions()
    except Exception as exc:
        logger.warning(
            "fetch_snapshot: get_positions() failed — %s: %s",
            type(exc).__name__, exc,
        )
        raw_positions = []
```

### 3.2 [`src/agent_trading/services/snapshot_sync.py`](src/agent_trading/services/snapshot_sync.py)

`SnapshotFetchProvider` 프로토콜에 `after_hours: bool = False` 파라미터를 추가하여 KIS 구현체와 인터페이스를 일치시킨다.

### 3.3 [`tests/brokers/koreainvestment/test_snapshot.py`](tests/brokers/koreainvestment/test_snapshot.py)

`TestFetchSnapshot` 클래스에 2개의 신규 테스트를 추가한다:

1. **`test_fetch_snapshot_after_hours_skip_positions`** — after-hours 모드에서 positions fetch가 생략되고 cash-only로 동작하는지 검증
2. **`test_fetch_snapshot_after_hours_cash_balance_only`** — after-hours 모드에서 cash-balance만 단독 호출되는지 검증

### 3.4 [`tests/services/test_snapshot_sync.py`](tests/services/test_snapshot_sync.py)

`MockSnapshotProvider.fetch_snapshot()`에 `after_hours` 파라미터를 추가하고 after-hours 로직(positions 생략)을 구현한다.

---

## 4. 검증 결과

| 항목 | 결과 |
|------|------|
| pytest (koreainvestment/test_snapshot.py) | **11 passed** ✅ |
| pytest (services/test_snapshot_sync.py) | **24 passed** ✅ |
| Docker build (snapshot-sync) | ✅ 성공 |
| Container 상태 | ✅ **`Up`** (5초) |
| Scheduler 로그 | ✅ `"After-hours mode — skipping positions fetch (cash-only sync)"` |
| Health API | ✅ `status: ok` |

---

## 5. 파일 변경 요약

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| [`src/agent_trading/brokers/koreainvestment/snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py) | 수정 | `after_hours=True` 시 positions fetch 생략 |
| [`src/agent_trading/services/snapshot_sync.py`](src/agent_trading/services/snapshot_sync.py) | 수정 | 프로토콜에 `after_hours` 파라미터 추가 |
| [`tests/brokers/koreainvestment/test_snapshot.py`](tests/brokers/koreainvestment/test_snapshot.py) | 수정 | after-hours skip / cash-only 테스트 2개 추가 |
| [`tests/services/test_snapshot_sync.py`](tests/services/test_snapshot_sync.py) | 수정 | Mock에 `after_hours` 파라미터 추가 |

---

## 6. Rate-limit 개선 효과

| 구분 | 변경 전 | 변경 후 |
|------|---------|---------|
| after-hours 1 cycle 당 `inquire-balance` 호출 수 | **2회** (positions + cash) | **1회** (cash only) |
| `EGW00201` 발생 위험 | **높음** (동일 초 2연타) | **없음** (1회만 호출) |
| 데이터 정합성 | — | after-hours에 positions는 변하지 않으므로 영향 없음 |
| `CASH_SYNC_ZERO` | cash=0과 무관하게 positions 생략과도 무관 | 진짜 cash=0일 때만 발생 |

---

## 7. 후속 조치

| 우선순위 | 조치 사항 |
|----------|-----------|
| **P0** | 영업일 after-hours (15:31~16:31 KST)에 실제 운용 환경에서 rate-limit 해소 확인 |
| **P1** | intraday 모드에서도 동일 `inquire-balance` 2연타 구조 확인 (현재 rate-limit 도달하지 않는 범위인지 검토) |

---

## 참고 자료

- [`src/agent_trading/brokers/koreainvestment/snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py)
- [`src/agent_trading/services/snapshot_sync.py`](src/agent_trading/services/snapshot_sync.py)
- [`tests/brokers/koreainvestment/test_snapshot.py`](tests/brokers/koreainvestment/test_snapshot.py)
- [`tests/services/test_snapshot_sync.py`](tests/services/test_snapshot_sync.py)
- KIS API 가이드: `EGW00201` (초당 거래건수 초과)
