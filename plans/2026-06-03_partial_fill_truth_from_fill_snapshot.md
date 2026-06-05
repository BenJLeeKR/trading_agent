# 부분체결 자동 판정 고도화 — linked fill snapshot 증분 해석

## 목적

- `Fill History Phase 3` 후속으로, linked `VTTC0081R` 체결 스냅샷이 있을 때
  부분체결/완전체결 자동 판정을 더 정확하게 만든다.
- 기존 구현은 `max(filled_quantity)`만 사용했기 때문에,
  개별 체결 row가 별도로 들어오는 경우 `3 + 7 = 10` 같은 완전체결도
  `max=7`로 읽어 `partially_filled`로 남길 수 있었다.

## 기존 한계

- 파일: `src/agent_trading/services/order_sync_service.py`
- 기존 `_infer_linked_fill_snapshot_truth()` 규칙:
  - linked snapshot 전부 조회
  - `max(filled_quantity)`만 사용
  - `max >= requested` → `filled`
  - 그 외 양수면 `partially_filled`

이 방식은 **누적 체결 표현**에는 안전하지만,
`broker_fill_id`가 있는 **증분 체결 표현**에는 보수적 과소판정을 만들 수 있다.

## 변경 내용

### 1. linked fill snapshot 해석 helper 추가

- 신규 dataclass:
  - `LinkedFillSnapshotTruth`
    - `filled_quantity`
    - `source`

- 신규 helper:
  - `_resolve_linked_fill_snapshot_quantity(order)`

### 2. 판정 규칙

#### 기본 규칙
- 여전히 기본값은 보수적으로 `max(filled_quantity)` 사용
- source: `fill_snapshot_cumulative_max`

#### 증분 합산 허용 규칙
- **모든 row에 `broker_fill_id`가 있고**
- **모두 서로 다른 값이며**
- **row가 2개 이상일 때만**
  - `sum(filled_quantity)`를 사용
  - 단, `sum <= requested_quantity`일 때만 허용
- source: `fill_snapshot_incremental_sum`

즉:
- `broker_fill_id`가 없으면 기존처럼 `max` 기준
- `broker_fill_id`가 있어도 합계가 요청수량을 넘으면 다시 `max` 기준으로 fallback

이 규칙은 보수성을 유지하면서도,
증분 체결 row를 실제 완전체결로 올바르게 해석할 수 있게 해 준다.

### 3. truth probe 연결

- `_infer_linked_fill_snapshot_truth()`가 이제
  - `_resolve_linked_fill_snapshot_quantity()`를 호출하고
  - 그 결과의 `filled_quantity`를 기준으로
    - `>= requested` → `filled`
    - `0 < qty < requested` → `partially_filled`
  로 판정한다.

## 테스트

- 파일: `tests/services/test_order_sync_service.py`

추가한 검증:

1. `broker_fill_id`가 서로 다른 2개 row
   - `3 + 7`, requested `10`
   - 기대 결과: `filled`

2. `broker_fill_id`가 서로 다른 2개 row
   - `3 + 2`, requested `10`
   - 기대 결과: `partially_filled`

3. 기존 단일 linked snapshot full-fill 테스트 유지

## 실행 결과

- `pytest -q tests/services/test_order_sync_service.py -k 'LinkedFillSnapshotTruth or truth_probe and not slow'`
  - `6 passed`

## 주의 사항

- 로컬 `python3 -m py_compile ...`는 `tests/services/__pycache__` 권한 문제로 실패할 수 있다.
- 이번 변경의 유효성은 서비스 테스트 통과로 검증했다.

## 기대 효과

1. linked fill snapshot이 있는 주문의 부분체결/완전체결 판정 정확도 상승
2. `position_delta` fallback에 의존해야 하는 케이스 축소
3. 이후 `order_sync_service`가 fill snapshot을 1급 truth source로 더 강하게 쓰는 기반 강화

## 다음 권장 작업

1. 실제 `broker_fill_id` 존재 패턴을 기준으로 운영 데이터 샘플링
2. 주문 상세 API에 `truth_source` (`fill_snapshot_incremental_sum` / `fill_snapshot_cumulative_max` / `broker_truth` / `position_fallback`) 노출
3. fill 발생 후 snapshot refresh 자동화
