# 2026-06-18 decision loop core cap 적용

## 배경

- 장중 실측에서 `decision_submit_gate` timeout의 직접 원인은
  `held/event/manual/market_overlay`가 아니라
  `source_type=core` 종목이 넓게 들어오면서
  비행동성 종목까지 `LLM assemble`을 반복 수행하는 구조에 있었다.
- 운영 안전장치로 scheduler timeout을 420초로 늘린 상태이지만,
  구조적으로는 장중 평가 대상 중 저우선순위 `core` 비중을 줄이는 것이 먼저다.

## 이번 변경

### 1. `core_cap` 계약 추가

- [`src/agent_trading/services/universe_selection_types.py`](../src/agent_trading/services/universe_selection_types.py)
  - `CompositionContext.core_cap: int | None` 추가
  - 의미:
    - `max_cap`: held 제외 전체 non-held cap
    - `core_cap`: 그 안에서 `source_type=core`가 차지할 수 있는 별도 상한

### 2. universe cap 적용 규칙 보강

- [`src/agent_trading/services/universe_selection.py`](../src/agent_trading/services/universe_selection.py)
  - `_apply_cap()`이 `HELD_POSITION`은 계속 무조건 포함
  - `EVENT_OVERLAY / MARKET_OVERLAY / MANUAL`은 `max_cap` 안에서 유지
  - `CORE`만 `core_cap` 도달 시 skip

즉,

- 보유 종목 보호는 유지
- 이벤트/마켓/수동 오버레이 우선순위는 유지
- 저우선순위 core만 줄여 장중 LLM 부하를 감축

### 3. decision loop 기본값 적용

- [`scripts/run_decision_loop.py`](../scripts/run_decision_loop.py)
  - `DEFAULT_TRADING_UNIVERSE_CORE_CAP = 12`
  - `TRADING_UNIVERSE_CORE_CAP` env override 지원
  - `_read_trading_universe()`가 기본적으로 `core_cap=12`를 사용

### 4. feature batch 영향 차단

- [`scripts/generate_signal_feature_snapshot_input.py`](../scripts/generate_signal_feature_snapshot_input.py)
  - feature 장후 배치는 `--core-cap` 인자를 별도로 받게 변경
  - 기본값은 `80`으로 두어,
    장중 decision loop 최적화가 장후 feature 적재 대상을 과도하게 줄이지 않게 분리

### 5. 운영 preview 노출

- [`src/agent_trading/api/routes/instruments.py`](../src/agent_trading/api/routes/instruments.py)
- [`src/agent_trading/api/schemas.py`](../src/agent_trading/api/schemas.py)
  - `GET /instruments/trading-universe/preview`에 `core_cap` 추가
  - preview 기본값도 `12`로 맞춰 운영자가 현재 장중 구성값을 그대로 볼 수 있게 정리

## 검증

- `tests/services/test_universe_selection.py`
  - `core_cap`이 core만 제한하고 event overlay는 유지되는지 확인
- `tests/scripts/test_run_decision_loop.py`
  - `_read_trading_universe(core_cap=1)` 반영 확인
- `tests/scripts/test_generate_signal_feature_snapshot_input.py`
  - feature batch 기본 인자 검증
- `tests/api/test_inspection.py`
  - preview API의 `core_cap` 노출 및 적용 확인

실행:

```bash
python3 -m pytest -q tests/services/test_universe_selection.py tests/scripts/test_run_decision_loop.py tests/scripts/test_generate_signal_feature_snapshot_input.py tests/api/test_inspection.py -k 'core_cap or trading_universe_preview or parse_args_defaults or read_trading_universe_applies_cap_overrides or read_trading_universe_applies_core_cap or test_custom_values or test_market_overlay_cap_default or test_pre_pool_size_default or test_core_cap_default'
```

결과:

- `11 passed`

## 다음 작업

1. 장중 실측으로 `source_type=core` 비중, cycle duration, timeout 재발률 변화 확인
2. `WATCH 급증 / BUY_CANDIDATE 부족`의 다음 구조 개선으로
   `eligibility + ranking` 기반 `BUY top-k projection` 설계 반영
3. 필요 시 `core_cap` 값을 고정 상수 대신
   장세/시간대/submit lane 상태 기반으로 동적으로 조정하는 후속 설계 검토
