# held_position NO_ACTION FDC 실제 생략

## 목적

`held_position`의 `primary_candidate=NO_ACTION` 구간은 기존 shadow
관측에서 FDC 원본 판단과 최종 실행 의미가 일치했다. 이 구간만 실제 FDC
호출에서 제외해 strict queue의 수요를 줄인다. `WATCH`와
`risk_opinion in ("reject", "reduce")` REDUCE/SELL 후보 구간은 이번
변경에 포함하지 않고 shadow 관측을 계속한다.

## 변경 범위

- `scripts/run_agent_subprocess.py::_check_fdc_skip()`에 아래의 좁은 조건을
  추가했다.
  - `source_type == "held_position"`
  - 실제 보유 수량이 있음
  - `deterministic_trigger.primary_candidate == "NO_ACTION"`
- 조건이 맞으면 FDC만 생략하고 기본 `HOLD`를 전달한다. EI/AR는 이미
  완료된 상태이며, 이후 `DecisionOrchestratorService`의 held-position
  sell override 및 EV/order gate는 기존 경로 그대로 실행된다.
- summary는 `[규칙 기반 FDC 생략]`으로 시작해 AI 응답이 아니라 규칙
  기반 생략임을 명시한다. 최종 `HOLD`를 확정했다고 쓰지 않는다. AR
  위험 신호가 강하면 downstream override가 `REDUCE`/`EXIT`로 바꿀 수
  있기 때문이다.
- 실제 FDC를 생략한 결정은 `shadow_held_position_fdc_skip` 표본에
  기록하지 않는다. shadow 표본은 "실제 FDC를 호출했다면"이라는 비교
  목적을 유지해야 하므로, 실제 skip 결과를 넣으면 WATCH 확대 판단의
  분모가 오염된다.

## 불변 사항

- `WATCH` 실제 skip 없음.
- `risk_opinion=reduce`/`reject` REDUCE/SELL 후보 실제 skip 없음.
- provider limiter 정책, FIFO 재대기열, 주문 정책, EV gate, sell guard,
  sizing, DB 스키마 변경 없음.

## 검증

- `tests/scripts/test_fdc_skip.py`
  - NO_ACTION held_position만 생략하는지
  - WATCH와 core lane에는 적용되지 않는지
  - reason code와 summary가 규칙 기반 생략을 정확히 밝히는지
- `tests/services/test_decision_orchestrator.py`
  - 실제 FDC skip이 shadow 표본에 적재되지 않는지

## 배포 후 실측

1. `source_type='held_position'` 및 `primary_candidate='NO_ACTION'`에서
   `fdc_skipped=true`, `skip_reason_codes`에 `held_position_no_action`이
   기록되는지 확인한다.
2. 같은 구간의 `provider_http_attempt_count=0`과
   `provider_queue_timeout=0`을 확인한다.
3. held_position 전체 FDC 호출 수, `provider_queue_timeout` 비율, cycle
   wall-clock을 배포 전과 비교한다.
4. `WATCH` 및 REDUCE/SELL shadow key의 표본이 실제 FDC 호출 결과만으로
   계속 축적되는지 확인한 뒤, 두 구간의 실제 skip 확대 여부를 별도로
   판단한다.
