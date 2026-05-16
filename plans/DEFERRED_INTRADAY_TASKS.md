## Deferred Intraday Tasks

Last updated: 2026-05-16 KST

이 문서는 **장중에만 의미 있는 보류 작업**을 모아둔 목록이다.
사용자가 `월요일 장시작` 같은 시그널을 주면 이 파일 기준으로 우선 재개한다.

### 1. Live-info / Session / Scheduler 영업일 장중 최종 검증

- 상태: 보류
- 재개 조건: **월요일 장 시작 후**
- 목적:
  - `076` 영업일 판정(`is_trading_day=true`, `opnd_yn=Y`) 확인
  - 실제 phase 전이 확인
    - `PRE_MARKET`
    - `OPEN`
    - `CLOSING`
    - `AFTER_HOURS`
  - `session_events` 생성 확인
  - `holiday_client` / `market_state_client` cache hit 확인
  - Admin UI Scheduler Status 카드 장중 반영 확인
- 관련 보고서:
  - [live_info_business_day_intraday_runtime_validation_2026-05-18.md](/workspace/agent_trading/plans/live_info_business_day_intraday_runtime_validation_2026-05-18.md)

### 2. market_overlay 장중 실측

- 상태: 보류
- 재개 조건: **월요일 장 시작 후**
- 목적:
  - `trade_decisions.source_type='market_overlay'` 실제 생성 확인
  - `source_type × decision_type` 분포 장중 실측
  - `WATCH`가 `core` 외 `market_overlay`에서도 발생하는지 확인
- 참고:
  - market overlay 경로 자체는 활성화 hotfix 완료
  - 장전/비영업일 측정은 표본 가치가 낮음
- 관련 보고서:
  - [market_overlay_intraday_activation_validation_2026-05-16.md](/workspace/agent_trading/plans/market_overlay_intraday_activation_validation_2026-05-16.md)

### 3. WATCH 장중 분포 후속 측정

- 상태: 보류
- 재개 조건: **월요일 장 시작 후**
- 목적:
  - `core + weak evidence -> WATCH`가 장중에도 반복 재현되는지 확인
  - `WATCH submit 차단` 유지 확인
  - `APPROVE` 분포 훼손 없는지 확인
- 관련 보고서:
  - [watch_recovery_effect_measurement_2026-05-15.md](/workspace/agent_trading/plans/watch_recovery_effect_measurement_2026-05-15.md)

## 재개 우선순위

1. Live-info / Session / Scheduler 영업일 장중 최종 검증
2. market_overlay 장중 실측
3. WATCH 장중 분포 후속 측정
