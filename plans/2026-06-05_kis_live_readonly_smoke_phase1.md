# KIS 실계정/실운영 smoke 검증 1차

## 목적

`2026-06-03_remaining_work_priority_map.md`의
`5. KIS 실계정/실운영 smoke 검증` 항목을
실주문 없이 안전하게 진전시킨다.

이번 1차 범위는 다음 두 가지다.

1. live quote client가 paper trading client와 별도로
   **전용 live budget manager**를 갖도록 정리
2. `auth → approval → quote`만 확인하는
   **read-only smoke CLI** 추가

## 변경 내용

### 1. live quote client budget 분리

파일:
- `src/agent_trading/runtime/bootstrap.py`

변경 전:
- `_build_kis_live_quote_client()`가 `KISRestClient`를 만들지만
  `budget_manager`를 주입하지 않았다.

변경 후:
- `build_kis_budget_manager(kis_env="live", real_rest_rps=...)`로
  전용 live budget manager를 생성해 주입한다.

효과:
- live quote/read-only 경로도 명시적인 `global_rest` / bucket snapshot을 가짐
- paper submit / fill sync와 운영상 더 명확히 분리된다고 해석 가능

### 2. read-only smoke CLI 추가

파일:
- `scripts/evaluate_kis_live_readonly_smoke.py`

검증 항목:
- `KIS_LIVE_INFO_APP_KEY / SECRET` 존재 여부
- live quote client 생성
- `authenticate()`
- `get_approval_key()`
- `get_quote(symbol)`

제약:
- submit/cancel/amend 호출 없음
- quote 1건과 approval/read-only auth만 확인

출력:
- `READY / BLOCKED`
- text / json 지원

## 테스트

파일:
- `tests/brokers/test_kis_adapter_validation.py`
  - live quote client가 live budget manager를 갖는지 검증
- `tests/scripts/test_evaluate_kis_live_readonly_smoke.py`
  - credential 없음 → `BLOCKED`
  - mocked client 성공 → `READY`

## 의미

아직 `실계정 combined submit smoke`까지는 아니다.
하지만 다음을 확보했다.

- 실시간 정보 경로가 전용 live budget을 가진다는 점
- 실제 운영 credential이 존재할 때
  실주문 없이 `auth / approval / quote`를 점검할 수 있는 표준 smoke 경로

즉 문서 기준 `5. KIS 실계정/실운영 smoke 검증`은
이제 `미완료`가 아니라 `진행중`으로 올릴 수 있다.

