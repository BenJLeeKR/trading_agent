# Snapshot Sync Test Contract 회귀 수정 보고

## 직접 원인
`get_cash_and_positions()` 도입 후 `FakeKISRestClient`에 동일 메서드가 미구현되어,
`sync_kis_account_snapshots()`가 `rest_client.get_cash_and_positions()`를 호출할 때
`AttributeError`가 발생하여 3개 테스트 파일에서 32개 테스트가 실패.

## 수정 내역

### 1. `FakeKISRestClient.get_cash_and_positions()` 추가
- **파일**: [`tests/services/test_kis_snapshot_sync.py`](tests/services/test_kis_snapshot_sync.py:88)
- `CashAndPositionsResult` import 추가 (line 32)
- `get_cash_and_positions()` 메서드 구현 (line 88-108)
- `self.get_positions()`와 `self.get_cash_balance()`에 **delegate**하여,
  서브클래스(FailingClient 등)의 오버라이드가 정상 동작하도록 설계

### 2. Budget exhaustion 테스트 리팩토링 (2개)
`get_cash_and_positions()`가 하나의 API 호출이므로, 개별 `get_cash_balance()`/`get_positions()` 실패 시나리오가
더 이상 유효하지 않음. `get_cash_and_positions()`를 직접 오버라이드하여 예외를 발생시키도록 수정:

- **`test_cash_balance_budget_exhausted_cash_not_saved`** (line 474):
  - `get_cash_balance()` → `get_cash_and_positions()` 오버라이드로 변경
  - `positions_synced == 1` → `positions_synced == 0` (통합 호출 실패)

- **`test_positions_budget_exhausted_cash_still_saved`** (line 562):
  - `get_positions()` → `get_cash_and_positions()` 오버라이드로 변경
  - `cash_balance_synced is True` → `cash_balance_synced is False` (통합 호출 실패)
  - assert 메시지 `"budget exhausted"` → `"exhausted"` (BudgetExhaustedError __str__ 포맷)

## 영향 받은 테스트 파일
- `tests/services/test_kis_snapshot_sync.py`
- `tests/services/test_snapshot_sync.py`
- `tests/api/test_snapshot_sync_runs.py`

## 최종 테스트 결과

### Backend (snapshot sync)
```
tests/services/test_kis_snapshot_sync.py ... 97 passed
tests/services/test_snapshot_sync.py  ........ 97 passed (joint run)
tests/api/test_snapshot_sync_runs.py ........ 97 passed (joint run)
============================= 97 passed in 23.64s ==============================
```

### Frontend
```
Test Files  16 passed (16)
Tests       266 passed (266)
Duration    3.71s
```

## 판정
- [x] snapshot sync 테스트 회귀 해소 (32/32 → 0 failed)
- [x] 테스트 contract와 production contract 일치
  - `get_cash_and_positions()` 시그니처: `(self, *, after_hours: bool = False) -> CashAndPositionsResult`
  - `CashAndPositionsResult` 필드: `cash_balance`, `positions`, `raw_response`
- [x] Fake 구현이 서브클래스 오버라이드와 호환 (delegate 패턴)
- [x] Frontend 테스트 영향 없음 (266 passed)
- [x] 완료 판정 가능
