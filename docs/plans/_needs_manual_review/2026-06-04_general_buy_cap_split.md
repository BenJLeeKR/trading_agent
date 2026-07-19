# 2026-06-04 일반 submit cap을 일반 BUY cap으로 명확화

## 배경

- 기존 `--max-submit-per-day`는 이름상 “하루 주문 상한”처럼 보였지만, 실제 운영에서는
  `core` / `market_overlay`의 **일반 BUY lane**을 제어하는 용도로만 쓰이고 있었다.
- `held_position`의 `REDUCE/EXIT SELL`은 이미 별도 lane / 별도 카운트로 관리 중이라,
  같은 상한 이름 아래 두 의미가 섞여 있었다.
- 실제 2026-06-04 사례에서 `001740` BUY는 `general_submit_disabled_core`로 막혔고,
  이는 “하루 BUY 2건 후 차단”처럼 보였지만 설정 이름만 보면 오해하기 쉬웠다.

## 설계 결정

### 선택
- 운영 상한의 의미를 **일반 BUY submit 상한**으로 명확히 분리한다.

### 이유
1. 최근 실제 일반 lane 주문은 `core/market_overlay`의 BUY가 전부였다.
2. `held_position` 위험 축소 SELL은 이미 별도 budget이라 같은 이름으로 묶는 것이 오해를 만든다.
3. `BUY cap`, `SELL cap`, `held_position SELL cap`을 완전히 분리하는 더 큰 구조 변경보다
   현재 운영 흐름을 가장 적게 건드리면서 의미만 정확히 맞출 수 있다.

## 구현 내용

### 스케줄러 인자
- 신규 표준 인자:
  - `--max-general-buy-submit-per-day`
- deprecated alias 유지:
  - `--max-submit-per-day`
  - 내부적으로 `max_general_buy_submit_per_day`로 매핑

### 기본값
- 코드 기본값:
  - `DEFAULT_MAX_GENERAL_BUY_SUBMIT_PER_DAY = 6`
- 운영 compose 기본값:
  - `SCHEDULER_MAX_GENERAL_BUY_SUBMIT_PER_DAY=6` (미설정 시 fallback)

### DB submit count 의미
- `_get_db_submit_count()`는 이제
  - budget-consuming status
  - `td.side = 'buy'`
  - `held_position reduce/exit sell 제외`
  조건으로 **일반 BUY submit count**를 센다.

## 기대 효과

1. 운영자가 “하루 submit 2건”을 “BUY 2건”과 혼동하지 않게 된다.
2. 스케줄러 gate 로그와 운영 정책 의미가 일치한다.
3. 이후 필요 시
   - 일반 BUY cap
   - held_position SELL cap
   - 추가 SELL/general cap
   을 독립적으로 확장하기 쉬워진다.

## 검증

- `tests/scripts/test_run_ops_scheduler.py`
  - parse args 기본값 / legacy alias
  - DB fallback default
  - DB query가 `td.side = 'buy'`를 포함하는지
- `py_compile`
- `ops-scheduler` 재기동 후 실제 command line 확인

## 후속 작업

- 다음 거래일 장중에 `buy-block-summary`의
  - `general_submit_disabled_*`
  - `submit_budget_consumed_*`
  패턴이 cap 의미와 일치하는지 실측 확인
- 필요 시 `.env` 운영값을 `6`보다 더 높이거나 시간대별 cap으로 확장
