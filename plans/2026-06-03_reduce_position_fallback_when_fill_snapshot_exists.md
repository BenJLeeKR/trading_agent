# 2026-06-03 linked fill snapshot 존재 시 BUY position fallback 축소

## 목적

- `plans/2026-06-03_remaining_work_priority_map.md` 기준
  `Fill History Phase 3` / `부분체결 자동 판정 고도화`의 다음 단계로,
  linked `VTTC0081R` snapshot이 이미 존재하는 주문에 대해서는
  `position_delta` fallback 의존을 더 줄인다.
- 즉, 직접 체결 진실원(`fill snapshot`)이 있는 주문은
  가능한 한 그 source를 우선 사용하고,
  불완전하더라도 바로 BUY position 추론으로 덮어쓰지 않도록 한다.

## 문제

기존 `_try_truth_probe()` 경로는 다음 순서였다.

1. linked fill snapshot으로 filled/partial 해석 시도
2. broker `resolve_unknown_state()` 호출
3. broker 결과가 non-terminal이면
4. BUY 주문은 `position_delta` 기반 추론 시도

이 구조의 문제:

- linked fill snapshot row가 **이미 존재**하더라도
- 그 row가 아직 양수 체결 수량을 만들지 못하면
- 곧바로 `position_delta` 추론으로 넘어갈 수 있었다.

즉, 직접 진실원 row가 있는데도
간접 추론(position snapshot)로 다시 상태를 덮어쓸 수 있는 구조였다.

## 변경 내용

파일:
- `src/agent_trading/services/order_sync_service.py`

### 1. linked fill snapshot 존재 여부를 먼저 명시적으로 조회

신규 helper:
- `_list_linked_fill_snapshots(order)`

의도:
- linked snapshot이 아예 없는지
- snapshot row는 있는데 아직 truth로 해석되지 않는지
를 구분하기 위함

### 2. `_infer_linked_fill_snapshot_truth()` / `_resolve_linked_fill_snapshot_quantity()`에 snapshot 주입 지원

변경:
- `snapshots: Sequence[BrokerFillSnapshotEntity] | None = None` 인자 추가

효과:
- `_try_truth_probe()`가 linked snapshot rows를 한 번 조회한 뒤
  같은 row 집합을 truth 해석 함수에 재사용한다.

### 3. 새 reason 추가: `FILL_SNAPSHOT_INCOMPLETE`

Enum:
- `TruthProbeReason.FILL_SNAPSHOT_INCOMPLETE`

의미:
- linked `VTTC0081R` snapshot row는 존재하지만
- 아직 positive filled quantity로 상태를 확정할 수 없음

### 4. BUY position fallback 조건 축소

이제 `_try_truth_probe()`는:

- linked snapshot rows가 **없을 때만**
  BUY position fallback (`BUY_POSITION_FILL`)을 시도
- linked snapshot rows가 **있는데 truth 해석이 안 되면**
  `FILL_SNAPSHOT_INCOMPLETE`로 반환하고
  BUY position fallback은 건너뜀

즉:

- `fill snapshot 없음` → position fallback 가능
- `fill snapshot 있음 but incomplete` → position fallback 금지

## 기대 효과

이 변경으로 linked fill snapshot이 존재하는 주문은:

1. direct truth source 우선
2. direct truth source가 불완전하면 “불완전” 상태를 그대로 남김
3. 간접 추론(position delta)로 즉시 덮어쓰지 않음

즉, 체결 진실원을 더 직접적으로 사용하는 방향으로 수렴한다.

## 테스트

파일:
- `tests/services/test_order_sync_service.py`

추가한 검증:

### `test_try_truth_probe_skips_buy_position_fallback_when_linked_snapshot_exists`

시나리오:
- BUY 주문
- linked fill snapshot row 1건 존재
  - `filled_quantity = 0`
- position snapshot만 보면 fill 추론이 가능해 보이는 상황
- broker `resolve_unknown_state()`는 `SUBMITTED`

기대:
- `probe_status is None`
- `probe_reason == TruthProbeReason.FILL_SNAPSHOT_INCOMPLETE`
- 즉, position fallback을 타지 않음

## 검증

```bash
pytest -q tests/services/test_order_sync_service.py \
  -k 'LinkedFillSnapshotTruth or FILL_SNAPSHOT_INCOMPLETE or truth_probe_fill_snapshot or buy_position_fill'
```

결과:
- `6 passed`

정적 검증:

```bash
python3 -m py_compile src/agent_trading/services/order_sync_service.py
```

결과:
- 통과

## 결과

이제 `fill snapshot`이 이미 존재하는 BUY 주문은,
설령 아직 incomplete row만 있더라도
`position_delta` 추론으로 바로 덮어쓰지 않는다.

따라서 `filled/partially_filled` 판정의 source of truth가
더 직접적인 방향으로 정렬된다.

## 다음 작업

1. `FILL_SNAPSHOT_INCOMPLETE` 주문의 후속 수렴 경로(추가 fill sync 후 재판정) 검토
2. `fill snapshot`이 있는 경우 `get_order_status()` / reconciliation 경로와의 우선순위 재정리
3. 장중 실데이터에서 `FILL_SNAPSHOT_INCOMPLETE` 발생 빈도 측정
