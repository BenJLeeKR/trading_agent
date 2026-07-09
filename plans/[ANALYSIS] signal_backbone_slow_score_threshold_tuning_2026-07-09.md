# `signal_backbone_v1` slow 구간 재설계 분석

## 목적

- `signal_backbone_v1`의 `slow_momentum`, `slow_trend` 점수 구간이
  현재 `core_risk_off` 차단을 과도하게 강화하고 있는지
  코드 기준으로 분해한다.
- `2026-07-06 ~ 2026-07-09` 장후 실측과
  후행 수익률 proxy 관측 결과를 이용해
  어떤 threshold를 어느 수준으로 바꾸는 것이 맞는지
  구체 수정안을 설계한다.
- 여기서 말하는 `백테스트`는
  체결 기반 정식 백테스터가 아니라
  `trigger_proxy_attribution` 로그와
  `signal_feature_snapshots`를 이용한
  **후행 수익률 proxy 기반 shadow 실측**을 뜻한다.

## 1. 현행 코드 기준선

대상 코드:

- [`src/agent_trading/services/signal_backbone.py`](../src/agent_trading/services/signal_backbone.py)

현행 `slow_momentum`:

- `return_3m_pct >= 15.0` → `0.9`
- `return_3m_pct >= 5.0` → `0.55`
- `return_3m_pct <= -10.0` → `-0.8`
- `return_3m_pct <= -3.0` → `-0.35`

현행 `slow_trend`:

- `price_vs_sma_60_pct >= 5.0` → `0.8`
- `price_vs_sma_60_pct >= 1.5` → `0.45`
- `price_vs_sma_60_pct <= -5.0` → `-0.8`
- `price_vs_sma_60_pct <= -1.5` → `-0.45`

현행 결합식:

- `slow_score = 0.6 * slow_momentum + 0.4 * slow_trend`
- `overall_score = 0.55 * slow_score + 0.45 * fast_score`

이를 `overall` 직접 기여도로 풀면:

- `slow_momentum` 계수 = `0.6 * 0.55 = 0.33`
- `slow_trend` 계수 = `0.4 * 0.55 = 0.22`

따라서 하방 점수의 직접 영향은 다음과 같다.

- `slow_momentum = -0.8` → `overall`에 `-0.264`
- `slow_momentum = -0.35` → `overall`에 `-0.1155`
- `slow_trend = -0.8` → `overall`에 `-0.176`
- `slow_trend = -0.45` → `overall`에 `-0.099`

결론:

- 현재 구조에서 `slow_momentum`이 가장 큰 단일 하방 기여도를 가진다.
- 다만 실제 실측에서는 `slow_trend`도 거의 항상 `-0.8`로 같이 찍혀
  둘이 동시에 `overall`을 깊은 음수로 밀어내는 구조다.

## 2. 현재까지의 실측 / proxy 백테스트 요약

근거 자료:

- `logs/trigger_proxy_attribution_2026-07-06_rerun.json`
- `logs/trigger_proxy_attribution_2026-07-07_rerun.json`
- `logs/trigger_proxy_attribution_2026-07-08_rerun.json`
- `logs/trigger_proxy_attribution_2026-07-09.json`

누적 proxy 결과(`2026-06-26 ~ 2026-07-09`):

- `core_risk_off_floor_v2_report`
  - `deep_negative`
    - `sample_count = 40`
    - `t1_return_pct_avg = -1.0164`
    - `t3_return_pct_avg = -2.5735`
    - `t5_return_pct_avg = -3.2870`
    - `positive_t3_hit_rate = 0.3810`
  - `inactive`
    - `sample_count = 165`
    - `t1_return_pct_avg = -0.0412`
    - `t3_return_pct_avg = -0.8611`
    - `t5_return_pct_avg = -0.6299`
    - `positive_t3_hit_rate = 0.5417`

해석:

- `deep_negative`는 `inactive`보다
  `T+1`, `T+3`, `T+5` proxy가 모두 나쁘다.
- 따라서 현재 `deep_negative` 군을
  직접 허용하는 완화는
  기대수익률 관점에서 정당화되지 않는다.
- 완화의 대상은
  `deep_negative` 본체가 아니라
  경계 구간이 과하게 `deep_negative`로 떨어지는지 여부다.

## 3. `active core_risk_off` 실제 입력 분포

실측 대상:

- `2026-07-06 ~ 2026-07-08` 재집계 기준
- `active core_risk_off` 행 `20건`

실측 결과:

- `avg_return_3m_pct = -30.4862`
- `avg_price_vs_sma_60_pct = -22.0053`

`return_3m_pct` 분포:

- `<= -15%`: `17건`
- `(-15%, -10%]`: `2건`
- `(-5%, -2%]`: `1건`

`price_vs_sma_60_pct` 분포:

- `<= -12%`: `17건`
- `(-12%, -8%]`: `1건`
- `(-8%, -3%]`: `2건`

점수 분포:

- `slow_trend = -0.8`: `20 / 20`
- `slow_momentum = -0.8`: `19 / 20`
- `slow_momentum = -0.35`: `1 / 20`

해석:

- 지금 `mild_relax / moderate_relax`가 비어 있는 것은
  floor 수치가 살짝 빡빡해서가 아니다.
- 실제 active 행 다수가
  `3개월 수익률`, `SMA60 이격도` 둘 다
  구조적으로 심한 하방 구간에 있다.
- 즉, `overall floor`만 완화하면 안 되고
  완화하더라도 **경계 구간만** 풀어야 한다.

## 4. 기존 shadow v2의 한계

현재 shadow v2:

- `return_3m_pct`
  - `<= -15%` → `-0.8`
  - `<= -5%` → `-0.45`
  - `<= -2%` → `-0.20`
- `price_vs_sma_60_pct`
  - `<= -8%` → `-0.8`
  - `<= -3%` → `-0.45`
  - `<= -1%` → `-0.20`

문제:

1. `-10 ~ -15%`와 `-8 ~ -12%` 같은 경계 구간은 일부 완화됐지만,
   여전히 active `core_risk_off` 다수는
   `<= -15%`, `<= -12%`에 머물러
   분포상 거의 변화가 없다.
2. 반대로 완만한 약세 종목과
   이미 회복 기미가 있는 종목에 대해서는
   `mild_negative` 표본을 늘릴 수 있으나,
   현재 floor 진단이 기대한 만큼 늘지 않았다.
3. 즉, `v2`는 방향은 맞지만
   병목의 중심이 `-5%`, `-8%`보다 더 깊은 구간에 있다.

## 5. 제안 수정안: `signal_backbone_v1_shadow_v5`

### 5.1 설계 원칙

1. `deep_negative` 본체는 유지한다.
2. 경계 구간만 단계적으로 분해한다.
3. `slow_momentum`, `slow_trend`를 동시에 완화하되,
   둘 다 **완만한 음수 구간**에서만 완화한다.
4. weight 변경은 아직 하지 않는다.
   - 먼저 입력 구간 재설계 효과를 분리 측정해야 한다.

### 5.2 제안 구간: `slow_momentum`

현행:

- `<= -10` → `-0.8`
- `<= -3` → `-0.35`

제안 `v5`:

- `<= -20` → `-0.8`
- `(-20, -10]` → `-0.55`
- `(-10, -5]` → `-0.30`
- `(-5, -2]` → `-0.15`

의도:

- `-10 ~ -20%` 구간을 한 덩어리 `-0.8`로 보는 것을 중단한다.
- 하지만 `-20%` 이하의 구조적 하락은
  여전히 `-0.8`로 남긴다.

`overall` 직접 기여 변화:

- `-0.8` → `-0.264`
- `-0.55` → `-0.1815`
- `-0.30` → `-0.0990`
- `-0.15` → `-0.0495`

### 5.3 제안 구간: `slow_trend`

현행:

- `<= -5` → `-0.8`
- `<= -1.5` → `-0.45`

제안 `v5`:

- `<= -12` → `-0.8`
- `(-12, -6]` → `-0.50`
- `(-6, -2.5]` → `-0.25`
- `(-2.5, -0.5]` → `-0.10`

의도:

- `SMA60` 대비 `-5%` 이탈만으로 바로 구조 붕괴 취급하는 것을 피한다.
- 대신 `-12%` 이하만 `deep trend negative`로 유지한다.

`overall` 직접 기여 변화:

- `-0.8` → `-0.176`
- `-0.50` → `-0.110`
- `-0.25` → `-0.055`
- `-0.10` → `-0.022`

## 6. `v5` 시뮬레이션 결과

대상:

- `2026-07-08` 장후 `signal_feature_snapshots` `80건`
- 가정:
  - `fast_score`는 유지
  - `slow_momentum / slow_trend`만 `v5` 구간으로 재계산
  - weight는 현행 유지

결과:

- baseline bucket
  - `non_negative = 11`
  - `mild_negative = 5`
  - `moderate_negative = 10`
  - `deep_negative = 54`
- `v5` bucket
  - `non_negative = 10`
  - `mild_negative = 13`
  - `moderate_negative = 4`
  - `deep_negative = 53`

변화:

- `deep_negative`는 `54 → 53`
- `mild_negative`는 `5 → 13`
- 즉, 전체 위험 구조를 무너뜨리지 않으면서
  경계 종목만 `mild_negative`로 재분류하는 효과가 있다.

대표 변화 종목 예시:

- `004370`
  - `return_3m_pct = -3.34`
  - `price_vs_sma_60_pct = -2.73`
  - `overall: -0.1650 → -0.0550`
  - `moderate_negative → mild_negative`
- `005830`
  - `return_3m_pct = -6.77`
  - `price_vs_sma_60_pct = -2.11`
  - `overall: -0.1178 → -0.0243`
  - `moderate_negative → mild_negative`
- `009240`
  - `return_3m_pct = -14.25`
  - `price_vs_sma_60_pct = -2.60`
  - `overall: -0.3338 → -0.2073`
  - `deep_negative → moderate_negative`

주의:

- `000270`처럼 원래 `non_negative`였던 일부 종목이
  `mild_negative`로 내려오는 케이스도 있었다.
- 즉, 이 안은 모든 종목을 단순 완화하는 안이 아니라
  구간 재분배안이다.

## 7. active `core_risk_off` 보호 효과 점검

같은 `v5` 기준으로
`2026-07-06 ~ 2026-07-08` active `core_risk_off` 20건을 다시 대입하면:

- `migrated_to_moderate_or_better = 0`

대표 예시:

- `000100`
  - `return_3m_pct = -23.85`
  - `price_vs_sma_60_pct = -16.83`
  - `overall_v5 = -0.6346`
- `000210`
  - `return_3m_pct = -28.93`
  - `price_vs_sma_60_pct = -20.05`
  - `overall_v5 = -0.6380`
- `001430`
  - `return_3m_pct = -53.34`
  - `price_vs_sma_60_pct = -43.44`
  - `overall_v5 = -0.7370`

즉:

- 현재 실제로 문제인 active `core_risk_off` 심한 하락군은
  여전히 `deep_negative`에 남는다.
- `v5`는 경계 약세 구간을 풀되,
  구조적 붕괴 구간은 유지하는 안이다.

## 8. 권고안

### 바로 해도 되는 것

1. `shadow v5`를 추가한다.
   - authoritative 교체 아님
   - item-level 진단 필드와 bucket 집계만 추가
2. `trigger_proxy_attribution`에
   `v5` bucket별 후행 수익률 proxy를 추가한다.
3. `2026-07-10` 이후 최소 `3 거래일` 더 관측한다.

### 아직 하면 안 되는 것

1. `deep_negative` 직접 완화
2. `overall floor`만 먼저 내리는 것
3. `slow / overall` weight 변경을 선행하는 것
4. `volatility_penalty`까지 한 번에 같이 바꾸는 것

## 9. 구현 대상 정리

1. [`src/agent_trading/services/signal_backbone.py`](../src/agent_trading/services/signal_backbone.py)
   - `_score_return_3m_shadow_v5` 추가
   - `_score_price_vs_ma_shadow_v5_sma60` 추가
   - `component_scores_json`에 `shadow_*_v5` 추가
2. [`src/agent_trading/services/trigger_proxy_attribution.py`](../src/agent_trading/services/trigger_proxy_attribution.py)
   - `core_risk_off_floor_v5_report`
   - `core_risk_off_floor_v5_diagnostics`
3. [`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)
   - `v5` 요약 출력 추가
4. 테스트
   - `tests/services/test_signal_backbone.py`
   - `tests/scripts/test_build_signal_feature_snapshots.py`
   - `tests/services/test_trigger_proxy_attribution.py`

## 결론

- 현재 병목은 단순 `floor` 수치보다
  `slow_momentum`, `slow_trend`의 hard-negative 구간 정의다.
- 하지만 active `core_risk_off` 다수는
  실제로도 매우 깊은 하방 구간이므로
  강한 완화는 기대수익률 목표와 맞지 않는다.
- 따라서 다음 단계는
  **`deep_negative` 본체를 건드리지 않는 `shadow v5` 경계 구간 재분배안**이
  가장 적절하다.
