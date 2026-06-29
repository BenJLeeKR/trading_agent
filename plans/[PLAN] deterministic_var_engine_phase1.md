# Deterministic VaR Engine Phase 1

## 목적

`11-b`의 전용 deterministic VaR 엔진 착수 전에,
Phase 1에서 사용할 VaR 파라미터와 계산식을 먼저 고정한다.

이 문서는 아래 5가지를 확정하는 것이 목적이다.

1. 수익률 정의
2. sigma 계산식
3. confidence level
4. lookback
5. account VaR / marginal VaR / concentration penalty 수식

핵심 원칙은 아래와 같다.

- VaR는 항상 deterministic backend가 계산한다.
- `AI Risk Agent`는 VaR를 계산하지 않고 읽기만 한다.
- replay / audit / 사후 설명이 가능한 단순 수식부터 시작한다.
- Phase 1에서는 복잡한 covariance matrix 추정보다
  운영 일관성과 재현성을 우선한다.

---

## Phase 1 범위

### 포함

1. 1일 horizon 기준 parametric VaR
2. 계좌 총 VaR
3. 종목별 standalone VaR
4. 종목별 marginal contribution 근사치
5. concentration penalty
6. open order exposure 반영 규칙

### 비포함

1. full covariance matrix 기반 portfolio VaR
2. Monte Carlo VaR
3. Historical simulation VaR
4. intraday / overnight 분리 VaR
5. stress scenario loss
6. regime-aware multiplier

위 항목은 Phase 2 이후 확장 범위로 남긴다.

---

## 1. 수익률 정의

Phase 1 수익률 정의는 아래로 고정한다.

- 주기: **일간 close-to-close**
- 형식: **로그수익률**

수식:

```text
r_t = ln(C_t / C_{t-1})
```

여기서:

- `C_t`: t일 종가
- `C_{t-1}`: 직전 거래일 종가

### 왜 로그수익률을 쓰는가

1. additive 성질이 있어 누적 해석이 쉽다.
2. 변동성 추정과 parametric VaR 수식 연결이 단순하다.
3. 일간 수익률 절대값이 작은 구간에서는 운영 해석상 왜곡이 작다.

### 왜 close-to-close를 쓰는가

1. 현재 시스템의 `signal_feature_snapshot`이 일봉 기반이다.
2. 장후 배치 / 장전 리스크 배치와 시간축 정합성이 좋다.
3. KIS 일봉 수집 경로와 바로 연결 가능하다.

---

## 2. sigma 계산식

Phase 1 sigma는 **20거래일 realized volatility**로 고정한다.

수식:

```text
sigma_i = stddev(r_{i,t-19}, ..., r_{i,t})
```

여기서:

- `sigma_i`: 종목 i의 일간 변동성
- `stddev`: 표본 표준편차
- 입력 수익률: 최근 20개 거래일 로그수익률

### 연율화는 Phase 1에서 하지 않는다

Phase 1 VaR는 1일 horizon 기준이므로,
연율화 volatility를 따로 계산하지 않는다.

즉 내부 authoritative sigma는 아래다.

```text
daily_sigma_i = stddev(last_20_daily_log_returns)
```

### 구현 정합성 원칙

현재 `signal_feature_snapshot.volatility_20d_pct`는
이미 20일 변동성 feature를 갖고 있으므로,
Phase 1 구현은 아래 둘 중 하나를 선택한다.

1. 직접 로그수익률을 다시 계산해 authoritative sigma 생성
2. `signal_feature_snapshot.volatility_20d_pct`를 보조 검증용으로만 사용

권장안은 **1번**이다.

이유:

- VaR 엔진의 원천 계산 로직을 명확히 소유할 수 있다.
- feature layer 변경이 risk layer를 오염시키지 않는다.
- 같은 입력 일봉으로 replay 가능하다.

---

## 3. confidence level

Phase 1 confidence level은 **95%**로 고정한다.

즉 z-score는 아래를 사용한다.

```text
z_95 = 1.65
```

### 왜 95%를 쓰는가

1. 초기 live 운영에서 99%보다 과도한 보수화를 줄일 수 있다.
2. 기대수익률 최대화 목표와 운영 리스크 통제 사이의 균형이 더 좋다.
3. Phase 1에서는 concentration penalty와 open order exposure가 같이 붙으므로
   95%만으로도 차단력이 충분하다.

### Phase 2 이후 확장

Phase 2에서는 아래 이중 지표를 검토할 수 있다.

- `var_95_1d`
- `var_99_1d`

단, Phase 1 authoritative threshold는 `95%` 하나만 쓴다.

---

## 4. lookback

Phase 1 lookback은 **20거래일**로 고정한다.

즉 sigma 계산용 입력은:

```text
최근 21개 종가 -> 최근 20개 로그수익률
```

### 왜 20거래일을 쓰는가

1. 현재 시스템 전반에 이미 `20d` feature 축이 널리 사용된다.
2. 1개월 내외의 최근 변동성 상태를 반영하기에 충분하다.
3. 60일 / 120일보다 regime 변화 반영이 빠르다.
4. live 운영에서 설명하기 쉽다.

### lookback 부족 시 정책

Phase 1 minimum bar requirement:

- 종가 21개 이상 필수

부족하면:

- `var_status = insufficient_data`
- authoritative VaR 계산 불가
- 단, submit hard block으로 바로 연결하지 않고
  Phase 1에서는 `warning + fallback risk fact`로 처리한다.

즉 데이터 부족만으로 신규 주문을 전부 막지는 않는다.

---

## 5. 기본 값 정의

종목 i에 대해 아래 값을 정의한다.

```text
MV_i = 현재 종목 노출금액
sigma_i = 최근 20거래일 일간 로그수익률 표준편차
z = 1.65
```

여기서 `MV_i`는 아래 합으로 정의한다.

```text
MV_i = held_market_value_i + pending_buy_exposure_i - pending_sell_offset_i
```

Phase 1에서:

- `held_market_value_i = current_position_qty_i * reference_price_i`
- `pending_buy_exposure_i = 미체결 BUY 주문 잔량 * reference_price_i`
- `pending_sell_offset_i = 미체결 SELL 주문 잔량 * reference_price_i`

단, `pending_sell_offset_i`는 현재 보유수량을 초과하여 음수 과대차감하지 않도록 clamp 한다.

reference price 우선순위:

1. 최신 market price
2. signal feature 입력의 최신 종가
3. average price

---

## 6. 종목별 standalone VaR

Phase 1 종목별 standalone VaR 수식:

```text
VaR_i = z * sigma_i * MV_i
```

여기서:

- `VaR_i >= 0`
- `MV_i <= 0`이면 `VaR_i = 0`

설명:

- 방향성 기대수익을 넣지 않는다.
- 오직 절대 손실 위험액 근사치로만 사용한다.

---

## 7. 계좌 총 VaR

Phase 1 계좌 총 VaR는 full covariance portfolio VaR가 아니라,
**보수적 단순 합산형 VaR**로 시작한다.

수식:

```text
AccountVaR_base = Σ VaR_i
```

즉 Phase 1에서는 종목 간 상관계수 분산효과를 인정하지 않는다.

### 왜 단순 합산형으로 시작하는가

1. covariance 추정 품질보다 운영 안정성이 우선이다.
2. replay / audit / 설명이 매우 단순하다.
3. concentration penalty와 같이 쓰면 보수적 hard limit fact로 충분하다.

이 값은 이후 Phase 2에서 아래로 확장 가능하다.

- segment bucket diversification discount
- index membership 기반 partial offset
- full covariance portfolio VaR

---

## 8. marginal VaR

Phase 1 marginal VaR는 미분형 정밀 marginal VaR가 아니라,
**종목별 VaR 기여율 근사치**로 정의한다.

수식:

```text
MarginalContribution_i = VaR_i / AccountVaR_base
```

단:

- `AccountVaR_base <= 0`이면 `MarginalContribution_i = 0`

이 값은 strict mathematical marginal VaR라기보다
Phase 1 운영 지표로 본다.

즉 의미는:

- "현재 계좌 총 위험액 중 이 종목이 차지하는 비율"

Phase 2에서만 true marginal VaR 또는 incremental VaR를 검토한다.

---

## 9. concentration penalty

Phase 1 concentration penalty는
포지션 비중 기반 deterministic penalty로 고정한다.

정의:

```text
weight_i = MV_i / NAV
```

사전 조건:

- `NAV > 0`

config 기준 최대 단일 종목 비중:

```text
max_weight = max_single_position_pct / 100
```

penalty 수식:

```text
ConcentrationPenalty_i = max(0, (weight_i - max_weight) / max_weight)
```

계좌 penalty 집계:

```text
ConcentrationPenalty_account = max(ConcentrationPenalty_i)
```

### penalty 적용 방식

Phase 1 adjusted VaR:

```text
AccountVaR_adjusted = AccountVaR_base * (1 + ConcentrationPenalty_account)
```

즉 최대 과집중 종목 하나가 계좌 VaR를 증폭시키는 구조다.

### 왜 이 방식을 쓰는가

1. 과집중 위험을 직관적으로 설명할 수 있다.
2. sizing engine의 concentration rule과 개념적으로 정합성이 좋다.
3. full covariance 없이도 "큰 종목 한 개에 몰린 위험"을 hard fact에 반영할 수 있다.

---

## 10. authoritative 저장 값

Phase 1에서는 기존 `risk_limit_snapshot` 확장 방향을 권장한다.

최소 추가 필드 예시:

- `var_confidence_level`
- `var_horizon_days`
- `var_lookback_days`
- `portfolio_var_1d`
- `portfolio_var_1d_adjusted`
- `largest_var_symbol`
- `largest_var_contribution_pct`
- `concentration_penalty_pct`
- `var_status`
- `var_reason_codes`

symbol-level detail은 우선 JSON으로 둔다.

예:

- `symbol_var_json`
- `symbol_marginal_contribution_json`

---

## 11. threshold 집행 원칙

Phase 1에서는 VaR 계산과 threshold 집행을 분리한다.

즉 먼저 authoritative fact를 만든 뒤,
후단 `risk_validator_v1`가 아래를 평가한다.

예시:

```text
portfolio_var_1d_adjusted / NAV >= max_portfolio_var_pct
```

또는:

```text
largest_var_contribution_pct >= max_symbol_var_contribution_pct
```

Phase 1 문서 범위는 수치 계산 확정까지이고,
threshold 값 자체는 config schema 확장 문서에서 별도 정의한다.

---

## 12. 예외 및 fallback 정책

### 데이터 부족

- 최근 종가 21개 미만
- reference price 없음
- NAV 없음

처리:

- `var_status = insufficient_data`
- `portfolio_var_1d = null`
- `portfolio_var_1d_adjusted = null`
- `var_reason_codes`에 원인 기록

### 비정상 sigma

- sigma가 음수이거나 계산 불가한 경우는 `invalid_sigma`

### zero variance

- 최근 20거래일 수익률 분산이 0이면
  `var_status = zero_variance`
- 이 경우 `VaR_i = 0`으로 처리 가능하나,
  운영상은 warning reason을 함께 남긴다.

---

## 13. Phase 1 고정안 요약

Phase 1 VaR 파라미터는 아래로 고정한다.

1. 수익률 정의
   - 일간 close-to-close 로그수익률
2. sigma
   - 최근 20거래일 로그수익률 표본 표준편차
3. confidence level
   - 95%
   - `z = 1.65`
4. lookback
   - 20거래일
   - 종가 21개 필요
5. 계좌 VaR
   - `AccountVaR_base = Σ VaR_i`
   - `AccountVaR_adjusted = AccountVaR_base * (1 + ConcentrationPenalty_account)`
6. marginal contribution
   - `VaR_i / AccountVaR_base`
7. concentration penalty
   - 단일 종목 비중 초과분 기반 증폭

---

## 14. 다음 구현 단계

이 문서가 고정되면 다음 순서로 구현한다.

1. `risk_limit_snapshot` 확장 필드 설계
2. `deterministic_var_engine.py` 추가
3. snapshot sync 또는 장전 risk batch에서 VaR 계산/저장
4. `AI Risk Agent` prompt projection에 read-only 노출
5. `risk_validator_v1`가 VaR threshold를 authoritative하게 집행

---

## 연결 문서

- [`plans/[PRIORITY_MAP] remaining_work_priority_map.md`](./[PRIORITY_MAP]%20remaining_work_priority_map.md)
- [`plans/[ANALYSIS] var_compliance_guardrail_implementation_path.md`](./[ANALYSIS]%20var_compliance_guardrail_implementation_path.md)
- [`plan_docs/agents/03_risk_role_boundaries.md`](/workspace/agent_trading/plan_docs/agents/03_risk_role_boundaries.md)
