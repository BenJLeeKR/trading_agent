# held_position SELL lane 유지 + 일반 submit cap 우회 차단

## 배경

이전 수정으로 `held_position` 기반 위험 축소 SELL이 같은 cycle 안의 일반 BUY submit 슬롯에 막히지 않도록 분리했다.

하지만 그 상태에서 scheduler가 일반 일일 budget이 소진된 날에도 `run_decision_loop --submit`을 유지하면, 같은 invocation 안의 `core` 종목이 다시 1건 submit될 여지가 남는다.

즉:

- 목표: `held_position SELL`은 계속 제출 가능
- 문제: `core BUY/일반 submit`은 일일 cap을 우회하면 안 됨

## 직접 원인

기존 구조:

1. `run_ops_scheduler.py`는 일반 budget이 소진되어도 held-position SELL을 살리기 위해 `--submit` 실행을 유지
2. `run_decision_loop.py`는 `submit=True`만 보면 `core` 종목도 submit 후보로 간주
3. 그 결과 일반 submit budget이 이미 소진된 날에도 `core` 종목이 추가 submit될 가능성이 남음

## 수정 내용

### 1. scheduler → decision loop 명시 플래그 추가

`run_decision_loop.py`에 아래 CLI 플래그를 추가했다.

- `--allow-general-submit`
- `--no-allow-general-submit`

기본값은 `True`.

### 2. per-symbol submit helper에 일반 lane 허용 여부 반영

`_compute_symbol_submit_mode()`에 `allow_general_submit` 인자를 추가했다.

- `held_position` 종목:
  - 기존대로 dedicated lane 유지
  - cycle cap + symbol dedupe만 적용
- `core` 종목:
  - `allow_general_submit=False`면 무조건 `dry_run`
  - 일반 budget이 살아 있을 때만 기존 submit slot 로직 사용

### 3. scheduler에서 실제 budget 상태를 플래그로 전달

`run_ops_scheduler.py`의 `_decision_command()`에 `allow_general_submit` 인자를 추가했다.

- `general_budget_ok=True` → `--submit`
- `general_budget_ok=False` → `--submit --no-allow-general-submit`

이렇게 하면:

- held-position SELL은 계속 submit path 가능
- core/general submit은 일일 cap 이후 더 이상 우회 불가

## 기대 효과

- 위험 축소용 SELL lane은 유지
- 일반 BUY/일반 core submit은 일일 cap을 넘겨서 추가 제출되지 않음
- scheduler 정책과 per-symbol 실행 정책이 서로 일관되게 맞물림

## 테스트

실행:

`pytest -q tests/scripts/test_run_decision_loop.py tests/scripts/test_run_ops_scheduler.py -k "allow_general_submit or HeldPositionSellBudget or decision_submit_command"`

결과:

- `23 passed`

추가 검증:

- `core` 종목은 `allow_general_submit=False`일 때 submit 금지
- `held_position` 종목은 일반 submit budget 소진 상태에서도 lane 유지
- scheduler command builder가 `--no-allow-general-submit`를 실제로 붙이는지 확인
