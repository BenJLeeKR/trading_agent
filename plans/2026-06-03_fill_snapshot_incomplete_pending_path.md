# 2026-06-03 `FILL_SNAPSHOT_INCOMPLETE` 후속 수렴 경로 정리

## 목적

- `plans/[PRIORITY_MAP] remaining_work_priority_map.md` 기준
  `FILL_SNAPSHOT_INCOMPLETE 주문의 후속 수렴 경로 정리`를 진행한다.
- linked `VTTC0081R` snapshot row는 들어왔지만 아직 positive fill quantity가 없어
  상태를 확정할 수 없는 주문을, 단순 내부 reason이 아니라
  **주문 row에서 직접 추적 가능한 pending 상태**로 남긴다.

## 문제

이전 단계에서 다음이 구현되어 있었다.

1. linked fill snapshot row가 존재하면
2. BUY position fallback으로 바로 덮어쓰지 않고
3. `_try_truth_probe()`가 `TruthProbeReason.FILL_SNAPSHOT_INCOMPLETE`를 반환

하지만 이 reason은 내부 반환값 수준에 머물렀다.

즉:
- `sync_order_post_submit()`가 끝난 뒤에도
- 주문 row 자체에는 왜 아직 `submitted`/`reconcile_required`인지
  충분한 근거가 남지 않았다.

운영 관점에서 부족했던 점:

1. DB에서 incomplete snapshot 대기 상태를 직접 찾기 어려움
2. 다음 cycle에서 같은 주문이 계속 남아 있을 때 “왜 남아 있는지”가 불분명
3. sync 결과에도 pending 성격이 드러나지 않음

## 변경 내용

파일:
- `src/agent_trading/services/order_sync_service.py`

### 1. pending reason builder 추가

신규 helper:
- `_build_pending_truth_probe_reason_message()`

현재 지원하는 pending reason:
- `TruthProbeReason.FILL_SNAPSHOT_INCOMPLETE`

생성되는 정보:
- `snapshot_rows`
- `positive_rows`
- `odno`
- `"Awaiting next fill sync / broker status convergence."`

예시 메시지:

```text
Linked fill snapshots exist but do not yet resolve a positive filled quantity;
snapshot_rows=1, positive_rows=0, odno=BRK-...
Awaiting next fill sync / broker status convergence.
```

### 2. 상태 변화가 없어도 주문 row의 reason 갱신

변경:
- `sync_order_post_submit()`에서
  - `truth_probe_reason_str == fill_snapshot_incomplete`
  - `status_changed == False`
  인 경우,
  `orders.update_status()`를 **같은 status 값으로 다시 호출**하여
  `status_reason_code/message`만 갱신

사용되는 code:
- `truth_probe_fill_snapshot_incomplete`

즉, 주문 상태는 그대로 `submitted`라도
이유는 explicit하게 남는다.

### 3. SyncOrderResult.error에도 pending 상태 반영

반환:
- `error="truth_probe_pending:fill_snapshot_incomplete"`

의미:
- 이것은 hard conflict가 아니라
  “후속 fill sync / broker convergence를 기다리는 중”이라는 신호다.

## 테스트

파일:
- `tests/services/test_order_sync_service.py`

추가한 검증:

### `test_sync_order_post_submit_persists_fill_snapshot_incomplete_reason`

시나리오:
- BUY 주문
- linked fill snapshot row 1건 존재
  - `filled_quantity=0`
- broker `resolve_unknown_state()` 결과는 여전히 `SUBMITTED`

기대:
- 주문 상태는 그대로 `SUBMITTED`
- 하지만
  - `status_reason_code == "truth_probe_fill_snapshot_incomplete"`
  - `status_reason_message`에
    - `snapshot_rows=1`
    - `positive_rows=0`
    - `Awaiting next fill sync`
  포함
- `SyncOrderResult.error == "truth_probe_pending:fill_snapshot_incomplete"`

## 검증 결과

```bash
pytest -q tests/services/test_order_sync_service.py \
  -k 'FILL_SNAPSHOT_INCOMPLETE or truth_probe_fill_snapshot or buy_position_fill'
```

결과:
- `1 passed` (관련 신규/선택 테스트)

정적 검증:

```bash
python3 -m py_compile src/agent_trading/services/order_sync_service.py
```

결과:
- 통과

## 효과

이제 incomplete snapshot 대기 상태는 다음처럼 보인다.

1. 상태값은 그대로 유지 (`submitted` 등)
2. 하지만 `status_reason_code/message`에
   “linked fill snapshot은 들어왔지만 아직 확정 불가”가 남음
3. sync 결과도 `truth_probe_pending:fill_snapshot_incomplete`로 남음

즉, 이후 운영자는
“왜 이 주문이 아직 terminal로 안 갔는지”를
주문 row만 보고도 이해할 수 있다.

## 다음 작업

1. `truth_probe_fill_snapshot_incomplete` 주문 집계/리포트화
2. 후속 fill sync에서 positive row가 들어왔을 때 자동 해소되는지 장중 실측
3. 필요 시 API / 주문 상세 응답에 pending truth probe summary 추가
