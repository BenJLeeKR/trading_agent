# 설정 스키마 상세 설계 v1

## 1. 목적

클라이언트별, 환경별, 전략별 설정을 안전하게 주입하고 버전 관리하기 위한 구조를 정의한다.

## 2. 최상위 구조

```yaml
client_id: client_alpha
environment: paper
config_version: 2026-05-01.v1

broker:
  primary: koreainvestment
  account_ref: paper-main-01
  product_scope:
    - kr_stock

trading_session:
  timezone: Asia/Seoul
  markets:
    - KRX
  allow_preopen: false
  allow_after_hours: false

strategy:
  strategy_id: swing_equity_v1
  rebalance_mode: event_driven
  max_positions: 12
  max_holding_days: 20

risk:
  trade_risk_pct: 0.3
  daily_loss_limit_pct: 2.0
  weekly_loss_limit_pct: 5.0
  max_drawdown_pct: 10.0
  per_position_loss_limit_pct: 1.0
  max_single_position_pct: 10.0
  max_sector_exposure_pct: 25.0
  max_theme_exposure_pct: 30.0
  max_gross_exposure_pct: 95.0
  max_net_exposure_pct: 95.0
  min_cash_buffer_pct: 5.0
  include_open_orders_in_exposure: true
  risk_reducing_orders_allowed_during_kill_switch: true
  kill_switch:
    max_rejects_per_hour: 10
    max_data_delay_seconds: 5

execution:
  order_type_default: limit
  limit_price_offset_bps: 5
  max_slippage_bps: 20
  max_spread_bps: 30
  max_order_participation_rate_pct: 5.0
  max_orderbook_top_depth_pct: 20.0
  cancel_after_seconds: 30
  replace_after_seconds: 20
  allow_market_order: false
  allow_partial_fill: true
  retry_policy: reconcile_before_retry
  unknown_state_policy: block_until_reconciled
  idempotency_lock_ttl_seconds: 300
  order_state_stuck_alert_seconds: 120

ai:
  model_id: model_registry/gpt-primary
  prompt_id: prompt_registry/trade_decision/v1
  temperature: 0.2
  seed: 42

data_quality:
  max_quote_delay_seconds: 3
  max_orderbook_delay_seconds: 3
  max_position_snapshot_age_seconds: 10
  max_cash_snapshot_age_seconds: 10
  reject_on_stale_market_data: true
  reject_on_missing_orderbook: true
  anomaly_detection:
    max_price_jump_bps: 500
    max_spread_bps: 100
    require_cross_source_validation: false

guardrail:
  rule_set_version: guardrail/v1
  block_on_any_failed_hard_rule: true
  require_risk_check_passed: true
  require_compliance_check_passed: true
  require_execution_check_passed: true
  minimum_required_edge_bps: 30
  block_if_net_expected_value_below_threshold: true

validation:
  paper_min_trading_days: 20
  paper_max_order_error_rate_pct: 1.0
  paper_max_reconciliation_mismatch_per_day: 3
  canary_max_capital_pct: 2.0
  canary_max_orders_per_day: 5
  canary_requires_manual_approval: true
  promote_to_live_requires_review: true

observability:
  alert_channel: slack-trading-ops
  persist_raw_agent_output: true
  persist_broker_raw_payload: true
  mask_sensitive_payload_fields: true
  audit_log_required_for_live: true
  halt_live_if_audit_log_unavailable: true
  metrics_flush_interval_seconds: 10
```

## 3. 설정 카테고리

### 3.1 broker

- 브로커 선택
- 계좌 참조
- 상품 범위
- capability override optional

### 3.2 trading_session

- 시간대
- 거래 시장
- 거래 가능 세션
- 휴장일 소스

### 3.3 strategy

- 전략 식별자
- 진입/청산 파라미터
- 포지션 수 제한
- 종목 universe

### 3.4 risk

- 일손실 한도
- 종목당 손실 한도
- 익스포저 한도
- 상관관계/섹터 편중 한도
- kill switch 조건

### 3.5 execution

- 기본 주문 타입
- 가격 오프셋
- 취소/정정 정책
- 재시도 정책

### 3.6 ai

- 모델 버전
- 프롬프트 버전
- deterministic 제어값

## 4. 스키마 검증 규칙

- 모든 퍼센트 값은 `0 <= x <= 100`
- live 환경에서 `persist_raw_agent_output`은 true 권장
- live 환경에서는 `daily_loss_limit_pct`, `max_single_position_pct` 필수
- paper와 live가 같은 `account_ref`를 사용할 수 없다
- capability override는 브로커 실제 capability를 확장할 수 없고 축소만 가능하다

## 5. 버전 관리 원칙

- 설정은 immutable version으로 저장한다.
- 수정은 overwrite가 아니라 새 버전 생성이다.
- trading runtime은 시작 시 config version을 고정하고 세션 중 변경 시 명시적 reload 이벤트를 받아야 한다.

## 6. 비밀값 처리

자격증명은 config 본문에 직접 넣지 않는다.

- 허용: secret reference
- 금지: appkey/appsecret/token 평문

예시:

```yaml
secrets:
  broker_credential_ref: secret://trading/kis/paper/main
```

## 6.1 공용 설정 계층과 개인 비밀 계층 분리 원칙

향후 멀티 사용자 운영으로 확장할 때도,
모든 설정을 사용자별로 복제하지 않고 아래처럼 계층을 분리하는 것을 기본 원칙으로 한다.

### 개인별로 반드시 분리할 항목

- KIS App Key / App Secret / 계좌번호 / 상품코드
- AI provider API key, provider별 개인 모델 override
- NAVER / DART 등 외부 유료 API credential
- 사용자별 주문 가능 계좌 매핑
- 사용자별 live/paper 활성화 상태
- 사용자별 리스크 한도 override

위 항목은 공용 config 본문에 직접 저장하지 않고
반드시 `secret reference + account/client mapping`으로만 주입한다.

### 공용으로 재사용 가능한 항목

- instrument master
- universe freeze, feature freeze 산출 로직
- deterministic trigger / eligibility / ranking 규칙
- 시장 세션 정보, 휴장일 정보, 장 상태 정보
- feature 계산식과 backend math engine
- broker adapter 코드와 오류 정규화 규칙
- audit / replay / reconciliation 프레임워크
- 운영 대시보드의 공통 집계 로직

단, 위 항목도 **산출 로직**은 공용이어도
실행 결과 row는 `client_id`, `account_id`, `config_version_id` 등
소유 경계가 분리되어야 한다.

### 권장 계층 구조

```yaml
shared_policy:
  universe_policy_ref: policy/universe/v1
  trigger_policy_ref: policy/trigger/v1
  feature_set_version: feature/v1
  broker_adapter_profile: koreainvestment/v1

client_overrides:
  risk_profile_ref: risk/client_alpha/v3
  execution_profile_ref: execution/client_alpha/v2
  ai_profile_ref: ai/client_alpha/v5

secrets:
  broker_credential_ref: secret://trading/client_alpha/kis/live/main
  ai_provider_credential_ref: secret://trading/client_alpha/llm/primary
  naver_credential_ref: secret://trading/client_alpha/naver/news
```

### 후속 리팩토링 원칙

- `AppSettings()` 전역 env 해석은 운영 단일 인스턴스 bootstrap까지만 허용한다.
- 멀티 사용자 실행 경로에서는 `client runtime config + secret resolver`가
  broker / AI / news adapter를 동적으로 조립해야 한다.
- 동일한 공용 policy를 여러 사용자가 공유하더라도,
  주문 실행과 브로커 rate limit budget은 계좌 단위로 분리한다.

## 7. Pydantic 예시 스키마

```python
from pydantic import BaseModel, Field
from typing import Literal


class KillSwitchConfig(BaseModel):
    max_rejects_per_hour: int = Field(ge=1)
    max_data_delay_seconds: int = Field(ge=1)


class RiskConfig(BaseModel):
    daily_loss_limit_pct: float = Field(ge=0, le=100)
    per_position_loss_limit_pct: float = Field(ge=0, le=100)
    max_single_position_pct: float = Field(ge=0, le=100)
    max_gross_exposure_pct: float = Field(ge=0, le=100)
    kill_switch: KillSwitchConfig


class RootConfig(BaseModel):
    client_id: str
    environment: Literal["paper", "live"]
    config_version: str
    risk: RiskConfig
```

## 8. 운영 규칙

- live 설정 활성화는 승인 워크플로를 거친다.
- 전략 비활성화는 설정 삭제가 아니라 status 변경으로 처리한다.
- 브로커 장애 시 emergency config profile로 전환 가능해야 한다.

## 9. `risk.max_single_position_pct` 운영 변경 경로

**구현 완료.** 과거에는 이 값을 바꾸는 유일한 방법이 `trading.config_versions`
row를 직접 DB에서 조작하는 것뿐이었다(운영 승인 경로 없음, §5의 immutable
버전 원칙을 지킬 보장도 없었음). 이제는 다음 두 경로 중 하나로 안전하게
새 버전을 발행할 수 있다 — 둘 다 같은 서비스 함수
(`agent_trading.services.config_version_admin.publish_max_single_position_pct()`)
를 공유하므로 검증/부작용은 완전히 동일하다.

### Admin API

```
POST /config-versions/risk/max-single-position-pct
Authorization: Bearer <admin 토큰>
Content-Type: application/json

{
  "client_id": "<UUID>",
  "environment": "paper",
  "max_single_position_pct": "15",
  "reason": "risk appetite 상향 조정"
}
```

- `require_admin`이 걸려 있다 — `orders.py`의 `PUT /orders/{id}/status`와
  동일한 게이팅 패턴(admin role 토큰 필요).
- 응답에 `previous_max_single_position_pct`/`new_max_single_position_pct`/
  `config_version_id`/`previous_config_version_id`가 함께 나와, 무엇이
  바뀌었는지 바로 확인할 수 있다.

### CLI(운영자가 직접 실행)

```bash
# 미리보기(기본값, 아무것도 쓰지 않음)
python -m scripts.publish_max_single_position_pct \
  --client-id <UUID> --environment paper \
  --max-single-position-pct 15 --activated-by ops-jay --reason "..."

# 실제 발행
python -m scripts.publish_max_single_position_pct \
  --client-id <UUID> --environment paper \
  --max-single-position-pct 15 --activated-by ops-jay --reason "..." --apply
```

### 이 경로가 §5의 immutable 원칙을 지키는 방법

- 기존 활성 `config_version` row는 **절대 UPDATE하지 않는다.** 그
  `config_json`을 그대로 복제한 뒤 `risk.max_single_position_pct`만 바꿔
  **새 row**를 추가하고, 그 row의 `activated_at`을 현재 시각으로 설정한다.
  `get_active()`가 `activated_at DESC`로 조회하므로 새 row가 곧바로
  "활성 버전"이 된다 — 과거 row는 그대로 남아 `get_active_at()`을 통한
  replay(특정 시점의 실제 유효 설정 재현)에 계속 쓰인다.
- 안전장치: `0 < max_single_position_pct <= 100`만 허용한다. `0` 이하는
  거부한다 — `sizing_engine.py`의 `_apply_concentration_constraint()`가
  `<= 0`을 "제약 조건 자체를 건너뜀"으로 해석하기 때문에, 0을 허용하면
  운영자가 의도와 반대로(더 엄격하게 만들려다가) 안전장치를 완전히 꺼버릴
  수 있다. 활성 버전이 아예 없는 client×environment, 그리고 현재
  활성값과 동일한 값의 중복 발행도 거부한다.
- 모든 변경은 `audit_logs`에 before/after 값과 `activated_by`/`reason`이
  함께 기록된다.
- 다른 risk/execution 키(`min_cash_buffer_pct`, `execution.max_order_value`
  등)는 이번 관리 경로의 범위 밖이며 그대로 보존된다 — 새 버전은
  `risk.max_single_position_pct` 한 키만 바뀐, 나머지는 기존 활성 버전과
  동일한 config_json을 갖는다.
