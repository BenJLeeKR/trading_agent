# KIS 실계정 combined submit smoke 실행기 (guarded)

## 배경

`[PRIORITY_MAP] remaining_work_priority_map.md`의 `5. KIS 실계정/실운영 smoke 검증`은
마지막으로 `KIS real credential 확보 후 combined submit smoke`가 남아 있다.

하지만 이 단계는 실제 live 주문을 내보낼 수 있으므로,
명시적 안전장치 없이 바로 실행하면 안 된다.

## 이번 작업

### 1. guarded runner 추가

- 파일: [`scripts/evaluate_kis_live_combined_submit_smoke.py`](../scripts/evaluate_kis_live_combined_submit_smoke.py)

동작:

1. 먼저 `evaluate_kis_live_submit_preflight.py`를 재사용해 live preflight 확인
2. `SubmitOrderRequest` 샘플 생성
3. broker adapter validation 수행
4. 기본값은 **dry-run**
   - 실제 submit 안 함
   - `READY` 상태로 “실행 준비 완료”만 반환
5. 실제 live submit은 아래 두 조건이 모두 있어야만 진행
   - `--execute-live-order`
   - `--confirm SUBMIT_REAL_ORDER`

즉, 명시적 opt-in 없이는 절대 실주문이 나가지 않는다.

### 2. 테스트 추가

- 파일: [`tests/scripts/test_evaluate_kis_live_combined_submit_smoke.py`](../tests/scripts/test_evaluate_kis_live_combined_submit_smoke.py)

검증 범위:

- preflight READY + dry-run → `READY`
- 실행 플래그는 있지만 확인 문구 틀림 → `BLOCKED`
- 실행 플래그 + 정확한 확인 문구 → 실제 `submit_order()` 호출

## 검증

```bash
pytest -q tests/scripts/test_evaluate_kis_live_combined_submit_smoke.py
python3 -m py_compile scripts/evaluate_kis_live_combined_submit_smoke.py \
  tests/scripts/test_evaluate_kis_live_combined_submit_smoke.py
```

추가로 실제 런타임 dry-run smoke도 실행해 확인했다.

```bash
python3 scripts/evaluate_kis_live_combined_submit_smoke.py --output text
```

실행 결과:

- `status=READY`
- `mode=dry_run`
- `preflight_status=READY`
- `request_validation_ok=True`
- `submitted=False`

즉, 현재는 **실주문 없이도**

1. live credential / 계좌 / approval preflight
2. sample submit request validation
3. guarded runner 안전장치

까지 모두 정상임을 확인한 상태다.

## 실제 live combined submit smoke 실행 결과

operator 승인 후 실제 submit 시도도 1회 실행했다.

실행:

```bash
python3 scripts/evaluate_kis_live_combined_submit_smoke.py \
  --symbol 005930 \
  --quantity 1 \
  --price 1 \
  --execute-live-order \
  --confirm SUBMIT_REAL_ORDER \
  --output text
```

결과:

- `preflight_status=READY`
- `request_validation_ok=True`
- 실제 `submit_order()` 호출 수행
- KIS 응답:
  - `rt_cd=7`
  - `msg_cd=KIOK0320`
  - `장운영시간이 아닙니다`

즉, **실 credential + live endpoint + 실제 submit 경로**가 브로커까지 정상 도달함을 확인했다.
이번 실행은 장외 시간이라 주문이 접수되지는 않았지만, smoke 목적의 end-to-end live submit 검증은 완료된 상태다.

## 우선순위 맵 반영

이번 작업으로 `5. KIS 실계정/실운영 smoke 검증`은 다음 상태가 된다.

- [x] live-info read-only smoke
- [x] budget isolation smoke
- [x] live submit preflight(read-only)
- [x] guarded combined submit smoke runner
- [x] 실제 real credential + operator 승인 하의 combined submit smoke 실행

즉 남은 것은 더 이상 “도구 부재”가 아니라,
**실제 운영 승인 하에 live submit smoke를 실행할지 여부**다.
