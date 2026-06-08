# KIS Live/Paper Budget Isolation Smoke — Phase 2

## 목적

`[PRIORITY_MAP] remaining_work_priority_map.md`의
`5. KIS 실계정/실운영 smoke 검증` 항목 중
아래 두 하위 과제를 실제 런타임 기준으로 검증한다.

1. `fill sync와의 실제 budget 경쟁 실측`
2. `paper 전용 우회 정책이 live에도 불필요하게 남아 있지 않은지 확인`

실주문은 수행하지 않고, 다음 두 종류의 **read-only 호출**만 사용한다.

- live-info 경로: `authenticate()` + `get_approval_key()` + `get_quote()`
- paper truth 경로: `VTTC0081R` (`inquire_daily_ccld`)

---

## 구현 내용

### 1. 새 smoke CLI 추가

파일:
- [`scripts/evaluate_kis_budget_isolation_smoke.py`](../scripts/evaluate_kis_budget_isolation_smoke.py)

검증 항목:
- paper trading client 생성 가능 여부
- live quote client 생성 가능 여부
- paper global bucket이 `FileBackedGlobalBucket` 인지
- live global bucket이 paper shared bucket과 분리된 in-process bucket인지
- live quote 호출 후 paper global remaining 이 감소하지 않는지
- paper truth query 호출 후 live global remaining 이 감소하지 않는지

즉, **서로 다른 env 경로가 같은 global budget 을 잘못 공유하지 않는지**를
실제 네트워크 호출 전후 snapshot 기준으로 확인한다.

---

### 2. 판정 기준

`READY`
- live quote 성공
- paper truth query 성공
- paper global bucket = shared/file-backed
- live global bucket = non-shared
- live 호출이 paper budget 을 깎지 않음
- paper truth query 가 live budget 을 깎지 않음

`WARN`
- live quote 는 성공했지만
- paper truth query 가 budget exhaustion 으로 완료되지 못함

`BLOCKED`
- client 생성 실패
- live quote 실패
- 기타 예외

---

## 테스트

파일:
- [`tests/scripts/test_evaluate_kis_budget_isolation_smoke.py`](../tests/scripts/test_evaluate_kis_budget_isolation_smoke.py)

검증 케이스:
1. live/paper budget 분리가 정상일 때 `READY`
2. paper truth query 가 `BudgetExhaustedError`일 때 `WARN`
3. live client 자체가 없을 때 `BLOCKED`

---

## 기대 효과

이 작업으로 다음을 더 명확히 검증할 수 있다.

1. live info quote 경로가 paper shared global budget 을 잠그지 않는지
2. paper fill truth/sync 조회가 live quote budget 을 오염시키지 않는지
3. paper 전용 shared-budget / pacing 정책이 live read-only 경로로 새지 않는지

즉, `KIS 실계정/실운영 smoke 검증`의 남은 범위 중
**실주문 없이도 확인 가능한 교차-env budget/정책 분리**를 먼저 닫는다.
