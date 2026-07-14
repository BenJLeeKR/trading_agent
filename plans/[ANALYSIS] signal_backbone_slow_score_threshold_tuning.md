# `signal_backbone_v1` slow 구간 재설계 분석

> **📌 2026-07-14 근본 경계 (중요)**: 이 문서가 다루는 slow_score/threshold
> 튜닝은 **신호 체계의 예측력(미래 수익률 상관)이 실증 검증되지 않은 상태**
> 에서 이뤄진 것이다. slow_momentum/slow_trend는 과거 가격의 추세 상태를
> 기술하는 룰 기반 지표이며 가중치는 하드코딩 값이다. 이 문서의 shadow
> 실측 역시 단일 하락 국면·소표본·proxy 기반이라 일반화 불가.
> "무엇을 근거로 사고 파는가"의 토대 검증이 threshold 튜닝보다 선행되어야
> 한다. 상세: `plans/[ANALYSIS] foundational_design_review_objective_alignment_2026-07-14.md`.

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

### 2.1 일자별 실측 데이터 요약

아래 표는 실제 분석에 사용된
`core_risk_off_floor_v2_diagnostics.bucket_counts`와
`core_risk_off_floor_v2_report.proxy_availability`
실측값이다.

| 기준 일자 | strict_pass | mild_relax | moderate_relax | deep_negative | inactive | T+1 준비 | T+3 준비 | T+5 준비 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-07-06 재실행 | 0 | 0 | 0 | 7 | 5 | 7 | 7 | 0 |
| 2026-07-07 재실행 | 0 | 0 | 0 | 7 | 14 | 7 | 0 | 0 |
| 2026-07-08 재실행 | 0 | 0 | 0 | 6 | 16 | 6 | 0 | 0 |
| 2026-07-09 누적 보고서 | 0 | 0 | 0 | 40 | 165 | 34 | 21 | 7 |

이 표에서 바로 확인되는 사실:

1. `2026-07-06 ~ 2026-07-08`의 active 표본은 모두 `deep_negative`였다.
2. 즉, 당시 `mild_relax`나 `moderate_relax`가 비어 있는 이유는
   단순히 샘플 부족 때문이 아니라
   실제 입력 점수가 완화 구간까지 올라오지 못했기 때문이다.
3. 누적 보고서(`2026-07-09`)에서도
   `deep_negative=40`, `inactive=165` 구조가 유지되므로,
   문제는 일시적 노이즈가 아니라
   `slow` 입력 하방 구조가 반복적으로 나타나는 현상으로 봐야 한다.

### 2.2 누적 proxy 실측 표

`2026-06-26 ~ 2026-07-09` 누적 기준으로
실제로 비교한 값은 아래 두 bucket이다.

| bucket | sample_count | T+1 평균 수익률 | T+3 평균 수익률 | T+5 평균 수익률 | T+3 양수 비율 |
| --- | ---: | ---: | ---: | ---: | ---: |
| deep_negative | 40 | -1.0164% | -2.5735% | -3.2870% | 0.3810 |
| inactive | 165 | -0.0412% | -0.8611% | -0.6299% | 0.5417 |

이 표가 뜻하는 바:

1. `deep_negative`는 `inactive`보다
   `T+1`, `T+3`, `T+5`가 모두 더 나빴다.
2. `T+3 양수 비율`도 `0.3810`으로 낮아서,
   단순히 변동성은 크지만 수익 기회가 있다는 해석도 성립하지 않는다.
3. 따라서 `deep_negative` 전체를 허용하는 방향은
   실측 기준으로 방어할 수 없다.
4. 결론적으로 완화의 대상은
   `deep_negative` 본체가 아니라
   그 직전 경계 구간이어야 한다.

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

### 3.1 active `core_risk_off` 일자별 실측 표본

아래 표는 실제 분석에 사용한
`2026-07-06 ~ 2026-07-08` active `core_risk_off` 20건 전체다.

| 일자 | 종목 | return_3m_pct | price_vs_sma_60_pct | slow_momentum | slow_trend | overall_score |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2026-07-06 | 000080 | -10.26% | -7.82% | -0.80 | -0.80 | -0.5120 |
| 2026-07-06 | 000100 | -23.85% | -16.83% | -0.80 | -0.80 | -0.6346 |
| 2026-07-06 | 000120 | -25.10% | -15.31% | -0.80 | -0.80 | -0.6189 |
| 2026-07-06 | 000210 | -28.93% | -20.05% | -0.80 | -0.80 | -0.6380 |
| 2026-07-06 | 000670 | -32.41% | -28.64% | -0.80 | -0.80 | -0.7134 |
| 2026-07-06 | 000720 | -26.23% | -22.40% | -0.80 | -0.80 | -0.7167 |
| 2026-07-06 | 000880 | -4.33% | -11.87% | -0.35 | -0.80 | -0.4389 |
| 2026-07-07 | 000210 | -32.26% | -20.33% | -0.80 | -0.80 | -0.6853 |
| 2026-07-07 | 000670 | -36.18% | -28.53% | -0.80 | -0.80 | -0.6819 |
| 2026-07-07 | 000720 | -41.97% | -25.44% | -0.80 | -0.80 | -0.7167 |
| 2026-07-07 | 001040 | -21.47% | -18.12% | -0.80 | -0.80 | -0.6954 |
| 2026-07-07 | 001430 | -53.34% | -43.44% | -0.80 | -0.80 | -0.7370 |
| 2026-07-07 | 001680 | -10.12% | -6.68% | -0.80 | -0.80 | -0.4423 |
| 2026-07-07 | 002030 | -32.32% | -14.18% | -0.80 | -0.80 | -0.4659 |
| 2026-07-08 | 000100 | -26.33% | -16.62% | -0.80 | -0.80 | -0.6346 |
| 2026-07-08 | 000210 | -34.76% | -21.46% | -0.80 | -0.80 | -0.6853 |
| 2026-07-08 | 000670 | -38.09% | -32.02% | -0.80 | -0.80 | -0.6819 |
| 2026-07-08 | 000720 | -45.09% | -30.79% | -0.80 | -0.80 | -0.6853 |
| 2026-07-08 | 001430 | -56.62% | -46.26% | -0.80 | -0.80 | -0.7370 |
| 2026-07-08 | 002030 | -30.06% | -13.32% | -0.80 | -0.80 | -0.4794 |

### 3.2 분포 요약 표

| 항목 | 실측 결과 | 해석 |
| --- | --- | --- |
| 평균 `return_3m_pct` | `-30.4862%` | 3개월 수익률 자체가 이미 심한 음수 구간 |
| 평균 `price_vs_sma_60_pct` | `-22.0053%` | 장기 이평 대비 이탈도 역시 매우 깊음 |
| `return_3m_pct <= -15%` | `17 / 20` | 대다수가 경계 약세가 아니라 구조적 약세 |
| `price_vs_sma_60_pct <= -12%` | `17 / 20` | 장기 추세 훼손이 광범위함 |
| `slow_trend = -0.8` | `20 / 20` | 모든 표본에서 장기 추세 패널티가 최하단 |
| `slow_momentum = -0.8` | `19 / 20` | 거의 모든 표본에서 3개월 모멘텀도 최하단 |

### 3.3 왜 이 데이터가 현재 결론으로 이어지는가

이 문서의 핵심 결론은
`overall floor`를 바로 낮추는 것이 아니라
`slow_momentum / slow_trend`의 경계 구간만 재설계해야 한다는 것이다.
그 논리는 위 표에서 직접 나온다.

1. `overall`만 문제라면
   `slow_momentum` 또는 `slow_trend` 중 적어도 하나는
   `-0.35`, `-0.45` 같은 중간 구간에 넓게 분포해야 한다.
   그런데 실제로는 `slow_trend=-0.8`이 `20/20`,
   `slow_momentum=-0.8`이 `19/20`이다.
   즉, 병목은 `overall floor`가 아니라
   upstream `slow` 입력 그 자체다.
2. `000880`처럼
   `return_3m_pct=-4.33%`로만 보면 경계 약세처럼 보이는 종목도,
   `price_vs_sma_60_pct=-11.87%` 때문에
   `slow_trend=-0.8`이 유지되어
   최종 `overall=-0.4389`까지 내려간다.
   이 사례는 `slow_momentum`만 완화해도 부족하고,
   `slow_trend` 구간도 같이 봐야 한다는 근거다.
3. 반대로 `000100`, `001430` 같은 종목은
   `return_3m_pct`, `price_vs_sma_60_pct` 둘 다
   매우 깊은 음수다.
   이런 종목까지 같이 완화하면
   실측상 성과가 나쁜 `deep_negative` 본체를 허용하게 된다.
   그래서 완화는 반드시 경계 구간에만 국한돼야 한다.

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

### 4.1 `v2`로도 표본이 늘지 않은 실측 근거

`v2`가 실제로 충분히 표본을 만들었는지 여부는
아래 실측으로 판단했다.

| 기준 일자 | deep_negative | mild_relax | moderate_relax | 판단 |
| --- | ---: | ---: | ---: | --- |
| 2026-07-06 재실행 | 7 | 0 | 0 | 완화 구간 진입 표본 없음 |
| 2026-07-07 재실행 | 7 | 0 | 0 | 완화 구간 진입 표본 없음 |
| 2026-07-08 재실행 | 6 | 0 | 0 | 완화 구간 진입 표본 없음 |

이 표가 의미하는 바:

1. `v2`가 이론상 경계 구간을 만들었더라도,
   실제 active 표본은 그 경계 구간보다 더 깊은 음수에 있었다.
2. 따라서 `v2`가 실패한 이유를
   “완화안 자체가 틀렸다”라고 보기보다는,
   “완화 폭이 실제 분포보다 얕았다”라고 해석하는 것이 맞다.
3. 그래서 `v5`에서는
   `return_3m_pct`의 구조적 하락 기준을 `-20%`,
   `price_vs_sma_60_pct`의 구조적 추세 붕괴 기준을 `-12%`로 더 아래에 두고,
   그 위 구간을 다시 단계화했다.

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

### 6.1 `v5` 시뮬레이션에서 실제로 이동한 종목 예시

아래 종목들은 실제 `2026-07-08` snapshot 80건에
`v5` 구간을 대입했을 때
bucket이 바뀐 대표 예시다.

| 종목 | return_3m_pct | price_vs_sma_60_pct | baseline overall | v5 overall | baseline bucket | v5 bucket | 해석 |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| 004370 | -3.34% | -2.73% | -0.1650 | -0.0550 | moderate_negative | mild_negative | 얕은 하락 구간은 완화 대상 |
| 005830 | -6.77% | -2.11% | -0.1178 | -0.0243 | moderate_negative | mild_negative | `-5 ~ -10%` 경계 하락 완화 |
| 006040 | -7.02% | -1.69% | -0.1380 | -0.0445 | moderate_negative | mild_negative | SMA60 이탈이 얕은 경우 완화 |
| 009240 | -14.25% | -2.60% | -0.3338 | -0.2073 | deep_negative | moderate_negative | `-10 ~ -20%` 구간 재분배 효과 |
| 011070 | 123.75% | -9.11% | -0.1243 | -0.0582 | moderate_negative | mild_negative | 강한 모멘텀 종목의 과도한 trend 패널티 완화 |

이 표가 중요한 이유:

1. `v5`는 모든 종목을 일괄 완화하지 않는다.
2. 실제로 이동한 종목들은
   `return_3m_pct`, `price_vs_sma_60_pct` 중 적어도 하나가
   “구조 붕괴”보다는 “경계 약세”로 해석 가능한 케이스다.
3. 따라서 `v5`는
   **약세 경계 구간만 재분배한다**는 설계 의도와
   실측 결과가 서로 맞아떨어진다.

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

### 7.1 보호 효과가 있다고 본 구체 이유

아래 대표 표본은
`v5`를 적용해도 여전히 강한 음수로 남았다.

| 종목 | return_3m_pct | price_vs_sma_60_pct | fast_score | v5 slow_score | v5 overall | 판단 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 000100 | -23.85% | -16.83% | -0.4325 | -0.80 | -0.6346 | 구조적 하락 유지 |
| 000210 | -28.93% | -20.05% | -0.4400 | -0.80 | -0.6380 | 구조적 하락 유지 |
| 000670 | -32.41% | -28.64% | -0.6075 | -0.80 | -0.7134 | 구조적 하락 유지 |
| 001430 | -53.34% | -43.44% | -0.6600 | -0.80 | -0.7370 | 구조적 하락 유지 |

이 표에서 결론이 나오는 이유:

1. `return_3m_pct <= -20%`와 `price_vs_sma_60_pct <= -12%` 구간은
   `v5`에서도 그대로 `-0.8`로 남는다.
2. active `core_risk_off` 다수는 바로 그 구간에 속한다.
3. 따라서 `v5`는
   현재 실적이 나쁜 심한 하락군을 건드리지 않고,
   경계 구간만 분리해서 관측하는 안으로 해석할 수 있다.

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
