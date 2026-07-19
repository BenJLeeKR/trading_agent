# KIS 실계정 submit smoke Phase 3 — live submit preflight

## 배경

`[PRIORITY_MAP] remaining_work_priority_map.md`의 `5. KIS 실계정/실운영 smoke 검증`은
아직 `KIS real credential 확보 후 combined submit smoke` 1개가 남아 있다.

하지만 실제 실주문 smoke를 바로 치기 전에, 최소한 아래를 read-only로 먼저 확인해야 한다.

- `KIS_ENV=live` 설정 여부
- live 주문 credential / 계좌 설정 여부
- primary trading client 생성 가능 여부
- access token / approval key 발급 여부
- live 계좌 cash / positions 조회 가능 여부
- live 계좌 orderable cash 조회 가능 여부

이 preflight가 있어야, 이후 combined submit smoke 실패가
`실주문 경로 문제`인지 `기본 live 계정 연결 문제`인지 더 빨리 분리할 수 있다.

## 이번 작업

### 1. 신규 CLI 추가

- 파일: [`scripts/evaluate_kis_live_submit_preflight.py`](../scripts/evaluate_kis_live_submit_preflight.py)

검증 범위:

1. `KIS_ENV=live` 인지 확인
2. live 주문 credential / 계좌번호 설정 확인
3. `_build_kis_adapter()`로 primary trading client 생성
4. `authenticate()`
5. `get_approval_key()`
6. `get_cash_and_positions()`
7. `get_orderable_cash_result()`

출력 모드:

- `--output text`
- `--output json`

### 2. 상태 해석

- `READY`
  - live submit path preflight 통과
- `WARN`
  - 계정 연결은 됐지만 `orderable cash` 응답이 비어 있음
- `BLOCKED`
  - `KIS_ENV=live` 아님
  - credential / 계좌 설정 부족
  - auth / approval / cash 조회 실패

## 검증

실행:

```bash
pytest -q tests/scripts/test_evaluate_kis_live_submit_preflight.py
python3 -m py_compile scripts/evaluate_kis_live_submit_preflight.py \
  tests/scripts/test_evaluate_kis_live_submit_preflight.py
```

## 우선순위 맵 반영

이번 작업으로 `5. KIS 실계정/실운영 smoke 검증`은 다음 상태가 된다.

- [x] live-info read-only smoke
- [x] budget isolation smoke
- [x] live submit preflight(read-only)
- [ ] KIS real credential 확보 후 combined submit smoke

즉, 남은 실질 작업은 이제 **실주문이 포함된 combined submit smoke** 하나다.
