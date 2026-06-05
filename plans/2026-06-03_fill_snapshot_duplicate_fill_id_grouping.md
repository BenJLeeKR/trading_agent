# 2026-06-03 linked fill snapshot 중복 `fill_id` 그룹핑 보강

## 목적

- `plans/2026-06-03_remaining_work_priority_map.md`의
  `Fill History Phase 3` 남은 세부 작업 중
  `같은 ODNO의 다회 조회/누적 체결 표현 차이를 흡수하는 규칙 정리`
  를 한 단계 더 진행한다.
- `VTTC0081R`를 여러 sync run에서 반복 조회할 때,
  같은 체결이 동일 `broker_fill_id`로 다시 들어오는 패턴을
  중복 합산하지 않도록 한다.

## 문제

기존 `_resolve_linked_fill_snapshot_quantity()` 규칙은 다음과 같았다.

1. 기본은 `max(filled_quantity)`
2. 단, `broker_fill_id`가 **모두 존재하고 서로 다른 경우**에만
   `sum(filled_quantity)` 허용

이 규칙의 한계:

- 같은 체결이 여러 sync run에서 다시 적재되어도
  `dedupe_key`가 다르면 row가 누적될 수 있다.
- 이때 `broker_fill_id`는 같고 row만 여러 개인 경우가 생길 수 있는데,
  기존 규칙은 이를 “증분 체결”로 보지 못하고 무조건 `max`로만 처리했다.
- 반대로 naive sum을 쓰면 같은 체결을 중복 합산할 위험이 있다.

즉, `fill_id` 단위로 먼저 그룹핑하는 규칙이 필요했다.

## 변경 내용

파일:
- `src/agent_trading/services/order_sync_service.py`

### 새 규칙

linked fill snapshot 수량 해석 순서:

1. 양수 `filled_quantity` row만 사용
2. `broker_fill_id`가 있는 row는 **fill_id별 최대 수량**만 취함
3. `fill_id` 없는 row가 섞여 있으면 보수적으로 `max` fallback
4. `fill_id`가 2개 이상 있고, `fill_id`별 최대 수량 합이
   `requested_quantity` 이하일 때만 증분 체결 합산 허용
5. 그 외에는 `cumulative max` 사용

즉:

- 같은 `fill_id`가 여러 번 반복되면 중복으로 합산하지 않음
- 서로 다른 `fill_id`만 증분 체결로 인정

### source 값 변경

증분 체결 합산 source를 더 구체적으로 바꿨다.

- 이전: `fill_snapshot_incremental_sum`
- 현재: `fill_snapshot_fill_id_max_sum`

의미:
- 단순 row 합이 아니라
- **fill_id별 최대 수량을 합산한 결과**라는 뜻을 명시한다.

## 테스트

파일:
- `tests/services/test_order_sync_service.py`

### 추가한 회귀 테스트

`test_try_truth_probe_groups_duplicate_fill_ids_before_sum`

시나리오:
- 요청 수량 10
- snapshot rows:
  - `CCLD-1`, qty=3
  - `CCLD-1`, qty=3  (같은 체결 재조회)
  - `CCLD-2`, qty=7

기대:
- `CCLD-1`은 한 번만 인정
- 최종 합산은 `3 + 7 = 10`
- truth probe 결과는 `FILLED`

### 기존 partial metadata 테스트 보정

기존 partial metadata 테스트의 source expectation도
`fill_snapshot_fill_id_max_sum`으로 업데이트했다.

## 검증

```bash
pytest -q tests/services/test_order_sync_service.py \
  -k 'LinkedFillSnapshotTruth or truth_probe_fill_snapshot or buy_position_fill'
```

결과:
- `5 passed`

정적 검증:

```bash
python3 -m py_compile src/agent_trading/services/order_sync_service.py
```

결과:
- 통과

## 효과

이제 linked fill snapshot truth는 다음 두 종류를 더 잘 구분한다.

1. **같은 체결의 반복 조회**
   - 동일 `fill_id` 반복 row는 중복 합산하지 않음
2. **실제 증분 체결**
   - 서로 다른 `fill_id`의 최대 수량만 합산

즉, `VTTC0081R`를 여러 번 끌어와 누적 적재한 환경에서도
`filled / partially_filled` 판정이 더 안정적으로 유지된다.

## 다음 작업

1. `fill_id`가 없는 row와 있는 row가 섞인 case의 운영 샘플 수집
2. linked fill snapshot이 존재하는 주문에서
   `position_delta` fallback 축소 범위를 추가 검토
3. order detail / report 계층에서
   `fill_snapshot_fill_id_max_sum` source를 구조화 표기할지 검토
