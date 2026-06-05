# 2026-06-03 linked fill snapshot 기반 부분체결 사유 메타데이터 보강

## 목적

- `plans/2026-06-03_remaining_work_priority_map.md`의
  `Fill History Phase 3` / `부분체결 자동 판정 고도화` 흐름에 따라,
  linked `VTTC0081R` snapshot이 주문 상태를 직접 확정한 경우
  그 근거를 주문 row에 더 직접적으로 남긴다.
- 특히 `partially_filled`로 전이된 주문이
  **얼마나 체결됐고, 얼마나 남았고, 어떤 해석 규칙으로 판단됐는지**
  를 `status_reason_message`만 봐도 읽을 수 있게 한다.

## 문제

기존 `OrderSyncService._build_truth_probe_reason_message()`는
`TruthProbeReason.FILL_SNAPSHOT`일 때도 다음 수준의 일반 메시지만 남겼다.

```text
Truth probe resolved via linked fill snapshot: status=partially_filled, odno=...
```

이 메시지의 한계:

1. 실제 체결 수량이 얼마인지 알 수 없음
2. 요청 수량 대비 잔여 수량이 얼마인지 알 수 없음
3. `fill_snapshot_incremental_sum`으로 해석된 것인지,
   `fill_snapshot_cumulative_max`로 해석된 것인지 드러나지 않음

즉, linked fill snapshot이 `partially_filled`를 만들더라도
운영자나 후속 배치 입장에서는 “왜 partial이 됐는지”를 다시 snapshot row까지 내려가 확인해야 했다.

## 변경 내용

### 1. `truth_probe_fill_snapshot` 메시지에 수량 근거 포함

파일:
- `src/agent_trading/services/order_sync_service.py`

변경:
- `_build_truth_probe_reason_message()`를 `@staticmethod`에서 instance method로 전환
- `probe_reason == TruthProbeReason.FILL_SNAPSHOT`일 때
  `_resolve_linked_fill_snapshot_quantity(order)`를 다시 호출해
  해석 결과를 메시지에 포함

이제 메시지는 다음 정보를 포함한다.

- `status`
- `filled`
- `requested`
- `remaining`
- `source`
- `odno`

예시:

```text
Truth probe resolved via linked fill snapshot:
status=partially_filled,
filled=5,
requested=10,
remaining=5,
source=fill_snapshot_incremental_sum,
odno=BRK-...
```

### 2. 기존 reason code는 유지

변경하지 않은 것:
- `status_reason_code`는 계속 `truth_probe_fill_snapshot`

이유:
- downstream 집계/분류 체계를 깨지 않으면서
  `message`만 더 풍부하게 만드는 것이 이번 단계의 목적이기 때문이다.

## 테스트

파일:
- `tests/services/test_order_sync_service.py`

추가한 검증:
- linked fill snapshot 2건 (`3 + 2`)이 있는 주문을
  `sync_order_post_submit()`에 실제로 태웠을 때
  - 최종 상태가 `PARTIALLY_FILLED`
  - `status_reason_code == truth_probe_fill_snapshot`
  - `status_reason_message`에
    - `filled=5`
    - `requested=10`
    - `remaining=5`
    - `source=fill_snapshot_incremental_sum`
    가 포함되는지 확인

## 검증 결과

### 테스트

```bash
pytest -q tests/services/test_order_sync_service.py \
  -k 'LinkedFillSnapshotTruth or truth_probe_fill_snapshot or buy_position_fill'
```

결과:
- `4 passed`

### 정적 검증

```bash
python3 -m py_compile src/agent_trading/services/order_sync_service.py
```

결과:
- 통과

## 효과

이제 linked fill snapshot이 주문 상태를 확정한 경우,
주문 row 하나만 봐도 다음을 바로 알 수 있다.

1. full fill인지 partial fill인지
2. 실제 해석된 체결 수량
3. 요청 수량 대비 남은 수량
4. `incremental_sum` / `cumulative_max` 중 어떤 규칙이 적용됐는지

즉, `fill snapshot`이 “상태를 만들었다”는 사실뿐 아니라
**어떤 수치 근거로 그 상태가 만들어졌는지**가 함께 남는다.

## 다음 작업

1. `fill_snapshot_cumulative_max` 케이스에도 같은 수준의 운영 검증 사례 추가
2. linked fill snapshot이 존재하는 주문에 대해
   `position_delta` fallback을 더 축소할 수 있는지 검토
3. order detail API 또는 후속 리포트에서
   `truth_probe_fill_snapshot` 메시지를 구조화된 summary로 노출
