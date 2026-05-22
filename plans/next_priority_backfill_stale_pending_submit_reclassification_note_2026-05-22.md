# 다음 우선순위 메모

## 주제
기존 `stale_pending_submit_expired` 과거 row를 `submission_failed_no_broker_id` 계열로 백필 정리할지 검토/구현

## 배경
- stale `pending_submit` sell orphan에 대한 신규 정리 정책은 `REJECTED + submission_failed_no_broker_id` 방향으로 이미 반영됨
- 그러나 과거에 `EXPIRED + stale_pending_submit_expired`로 정리된 row가 남아 있음
- 현재 운영상 더 시급한 문제는 held_position sell이 `BUDGET_EXHAUSTED` 후 `active reconciliation lock`에 막히는 현상임

## 우선순위 판단
- 본 항목은 **다음 우선순위**로 유지
- 먼저 처리할 항목:
  1. held_position sell의 `BUDGET_EXHAUSTED` 직접 원인 확인
  2. `active reconciliation lock`이 후속 위험축소 매도까지 차단하는 정책 점검

## 이후 검토 포인트
- 과거 `stale_pending_submit_expired` row를 백필 재분류할지 여부
- `EXPIRED` 유지 vs `REJECTED` 전환 vs reason code만 보정
- explicit reject와 unknown orphan를 상태/사유 코드로 어떻게 구분할지
