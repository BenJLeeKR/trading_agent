# `core_risk_off` `slow_score_v5` shadow 완화 후속 백로그

## 1. 목적

- `core_risk_off` 차단군에서
  `overall_missing` 보정 이후에도
  active 표본이 전부 `deep_negative`로 남는 원인을
  `slow_score_v5` 하위 성분 기준으로 더 정밀하게 분해한다.
- `deep_negative` 전체를 풀지 않고,
  `최고 기대수익률` 목표와 정렬되는
  제한적 shadow 완화 경로만 검증한다.
- 최종 목표는
  `WATCH`만 늘리는 완화가 아니라,
  실제 `BUY candidate → submit` 전환 가능성이 있는
  구간만 선별적으로 승격하는 것이다.

## 2. 현재 기준선

### 2.1 최근 실측 결론

- 기간:
  `2026-07-06 ~ 2026-07-10`
- 분석 산출물:
  - [`logs/trigger_proxy_attribution_2026-07-06_2026-07-10_v5_rerun_after_hydration_fix.json`](../logs/trigger_proxy_attribution_2026-07-06_2026-07-10_v5_rerun_after_hydration_fix.json)
  - [`plans/[ANALYSIS] core_risk_off_floor_v5_report_measurement_2026-07-11.md`](./%5BANALYSIS%5D%20core_risk_off_floor_v5_report_measurement_2026-07-11.md)

### 2.2 확인된 사실

1. `overall_missing`은 분석 경로 기준 해소됐다.
   - 원인:
     `2026-07-06` 일부 decision이
     `2026-07-03 20:00 KST`의 구형 snapshot을 참조했고,
     해당 snapshot에 `shadow_overall_score_v5`,
     `shadow_slow_score_v5`가 없었다.
   - 보정:
     snapshot의 저장 feature 컬럼으로
     `shadow v5`를 재구성하는 fallback을 추가했다.

2. 현재 병목은 `missing`이 아니라
   실제 `slow_score_v5`의 하방 편향이다.
   - active `core_risk_off` 표본 `35건`
   - `mild_relax = 0`
   - `moderate_relax = 0`
   - active 전부 `deep_negative`

3. `deep_negative` 전체 완화는 지금 근거가 부족하다.
   - `deep_negative`
     - `T+1 평균 = -1.79097%`
     - `T+3 평균 = -5.39322%`
     - `T+3 양수 비율 = 14.29%`
   - `inactive`
     - `T+1 평균 = -0.41536%`
     - `T+3 평균 = -3.16742%`
     - `T+3 양수 비율 = 21.05%`
   - 즉, `deep_negative`가 `inactive`보다 나쁘므로
     전체 완화는 `최고 기대수익률` 목표와 정렬되지 않는다.

### 2.3 하위 성분 분해 결과

- `slow_relax_candidate_items`
  - `deep_tail = 35`
  - `edge_deep = 0`
  - `moderate_candidate = 0`
  - `mild_candidate = 0`

- `slow_momentum_band_items`
  - `deep_negative = 25`
    - `T+3 평균 = -5.04635%`
  - `moderate_negative = 10`
    - `T+3 평균 = -6.26040%`

- `slow_trend_band_items`
  - `deep_negative = 29`
    - `T+3 평균 = -6.24912%`
  - `moderate_negative = 4`
    - `T+3 평균 = -0.25782%`
    - `T+3 양수 비율 = 50%`
  - `micro_negative = 2`
    - proxy 표본 부족

### 2.4 현재 해석

- `slow_momentum`은 아직 완화 근거가 약하다.
- 반면 `slow_trend`의 `moderate_negative` 구간은
  표본은 작지만 상대적으로 덜 나쁘며,
  shadow 완화 후보로 먼저 관측할 가치가 있다.
- 따라서 다음 shadow 완화는
  `slow_trend`만 별도 경계 완화 후보로 분리해야 한다.

## 3. 후속 작업 원칙

1. `deep_negative` 전체 완화 금지
2. `slow_momentum`과 `slow_trend` 동시 완화 금지
3. `slow_trend`만 먼저 shadow 완화 후보로 분리
4. authoritative 경로 즉시 변경 금지
5. 최소 3거래일 추가 관측 후 승격 여부 판단
6. 판단 기준은 `WATCH 증가`가 아니라
   `후행 proxy 개선 + churn 악화 없음`이다
7. `pre-BUY staging` 표본이 잡히더라도
   `inactive / eligibility 차단`만 반복되면
   `slow floor` 완화보다 앞서
   `activity / eligibility` 병목을 먼저 분리한다

## 4. 구체 후속 작업

### 4.1 작업 A — `slow_trend` 전용 shadow 완화 버킷 추가

- 목적:
  `slow_trend`가 `deep_negative` 전체를 대표하는지,
  아니면 경계 구간이 과도하게 묶여 있는지 분리한다.

- 제안 버킷:
  - `trend_strict_ready`
  - `trend_mild_candidate`
  - `trend_moderate_candidate`
  - `trend_edge_deep`
  - `trend_deep_tail`

- 기준안:
  - `price_vs_sma_60_pct >= -0.5`
    - `trend_strict_ready`
  - `-2.5 < price_vs_sma_60_pct <= -0.5`
    - `trend_mild_candidate`
  - `-6.0 < price_vs_sma_60_pct <= -2.5`
    - `trend_moderate_candidate`
  - `-12.0 < price_vs_sma_60_pct <= -6.0`
    - `trend_edge_deep`
  - `<= -12.0`
    - `trend_deep_tail`

- 구현 위치:
  - `src/agent_trading/services/trigger_proxy_attribution.py`
  - 필요시 `deterministic_trigger_engine.py` metadata에도
    shadow 분류 필드 추가

#### 작업 A 체크리스트

- [x] `slow_trend` 전용 shadow 버킷 명칭을 최종 고정했다
- [x] `price_vs_sma_60_pct` 구간 경계를 코드/문서 기준으로 고정했다
- [x] `trigger_proxy_attribution.py`에 `slow_trend_relax_candidate_band` 분류 helper를 추가했다
- [x] sample row에 `slow_trend_relax_candidate_band`를 기록한다
- [x] active/inactive 모두에서 예외 없이 bucket이 채워지는지 테스트했다
- [x] 경계값(`-0.5`, `-2.5`, `-6.0`, `-12.0`) 테스트를 추가했다

### 4.2 작업 B — `slow_trend` shadow 완화 후보를 별도 집계로 노출

- attribution payload에 아래 집계 추가
  - `slow_trend_relax_candidate_items`
  - `slow_trend_relax_candidate_report`
  - `slow_trend_path_items`

- sample row에 아래 필드 추가
  - `slow_trend_relax_candidate_band`
  - `price_vs_sma_60_pct`
  - `return_3m_pct`
  - `shadow_component_scores_v5.slow_trend`
  - `shadow_component_scores_v5.slow_momentum`

#### 작업 B 체크리스트

- [x] attribution payload에 `slow_trend_relax_candidate_items`를 추가했다
- [x] attribution payload에 `slow_trend_relax_candidate_report`를 추가했다
- [x] attribution payload에 `slow_trend_path_items`를 추가했다
- [x] sample row에 `price_vs_sma_60_pct`를 노출했다
- [x] sample row에 `return_3m_pct`를 함께 노출했다
- [x] sample row에 `shadow_component_scores_v5.slow_trend`를 함께 노출했다
- [x] sample row에 `shadow_component_scores_v5.slow_momentum`를 함께 노출했다
- [x] report helper 테스트를 추가했다

### 4.3 작업 C — `slow_momentum`은 관측 전용 유지

- 현재는 완화안 적용 금지
- 다만 다음 집계는 유지
  - `slow_momentum_band_items`
  - `return_3m_pct` 구간별 proxy
  - `momentum reason code`별 proxy

- 목적:
  `slow_momentum moderate_negative`가
  실제로 완화 후보가 되는지 추가 표본으로 확인

#### 작업 C 체크리스트

- [x] `slow_momentum` 관련 authoritative 완화는 적용하지 않았다
- [x] `slow_momentum_band_items` 집계가 유지되는지 확인했다
- [x] `return_3m_pct` 구간별 집계가 유지되는지 확인했다
- [x] `momentum reason code`별 proxy 집계가 유지되는지 확인했다
- [x] `slow_momentum moderate_negative` 표본 수를 일자별로 추적 가능하게 했다

### 4.4 작업 D — `shadow → buy/submit` 전환 가능성 추적 추가

- 현재는 후행 proxy만 볼 수 있고,
  실제 주문 후보로 연결됐는지까지는 부족하다.
- 아래를 추가 계측한다.
  - `shadow_relax_projection_candidate`
  - `shadow_relax_projection_selected`
  - `shadow_relax_projection_block_reason`
  - `shadow_relax_projection_would_buy`

- 목적:
  shadow 완화가 단순히 `WATCH`만 늘리는지,
  아니면 실제 `BUY candidate` 증가 경로를 만드는지 확인

#### 작업 D 체크리스트

- [x] `shadow_relax_projection_candidate` 필드를 추가했다
- [x] `shadow_relax_projection_selected` 필드를 추가했다
- [x] `shadow_relax_projection_block_reason` 필드를 추가했다
- [x] `shadow_relax_projection_would_buy` 필드를 추가했다
- [x] shadow 완화 후보가 `WATCH`만 증가시키는지 구분 가능해졌다
- [x] shadow 완화 후보가 실제 `BUY candidate`로 이어질 수 있는지 구분 가능해졌다
- [x] projection 관련 집계 테스트를 추가했다
- [x] `slow_floor_relax_ready` 코호트 sample row를 별도 노출했다
- [x] ready 코호트의 `BUY threshold gap / ranking gap / watch shape reason`을 계측했다
- [x] active `trend_moderate_candidate` / `slow_floor_relax_ready`의 `deterministic_buy_shape_block_reason` 집계를 추가했다
- [x] active `watch reason × buy-shape` 교차 집계와 projection 집계를 추가했다
- [x] `core_watch_path_only|watch_from_exit_setup` 전용 병목 집계와 sample 노출을 추가했다
- [x] `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate` 3건 전용 집계를 추가했다
- [x] 3건 코호트의 `signal_both_floor_miss`를 `overall/slow` 우선 병목으로 분해했다
- [x] 3건 코호트의 `slow_floor_shadow_relax_path`를 직접 집계했다
- [x] 3건 코호트의 `limited_slow_floor_shadow_path / limited_slow_floor_transition_stage`를 추가해 제한 완화 다음 병목을 직접 집계한다
- [x] `candidate_ready_watch_only_core_path` 코호트의 `WATCH -> BUY shape` 미전환 원인을 `entry gap / ranking gap / trigger shape` 기준으로 분해했다
- [x] `candidate_ready_watch_only_core_path` 코호트의 `entry_gap_band(large/moderate/small/ready)` 집계와 일자별 bucket을 추가했다
- [x] `entry_gap_band`별 `candidate/select/would_buy/submitted` projection 집계를 추가했다
- [x] 상위 `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate` 코호트 전체의 `buy_candidate_threshold_gap_band` 집계를 추가했다
- [x] 같은 코호트의 `limited_slow_floor_transition_stage × buy_gap_band` 교차 집계를 추가했다
- [x] target 코호트와 strict `authoritative core BUY path`를 같은 `entry_score / buy_gap / ranking_gap` band로 비교하는 계측을 추가했다
- [x] broader baseline 기준 strict `authoritative core BUY path` 표본이 0건임을 확인했다
- [x] strict BUY baseline 부재를 보완하기 위해 `pre-BUY staging cohort`(`watch_from_entry_setup`, `entry_score>=0.52`, `0.55<=entry_score<0.65`) 비교 계측을 추가했다
- [x] `pre-BUY staging cohort`별 `entry_score / buy_gap / ranking_gap / projection / sample` 리포트를 추가했다
- [x] `2026-07-01 ~ 2026-07-10` 재집계에서 `pre-BUY staging` 표본이 전부 `inactive` 경로이며 `candidate/select/would_buy/submitted`가 0임을 확인했다
- [x] `pre-BUY staging activity_gate`를 `activity_detail` 수준으로 세분화하는 계측을 추가했다
- [x] `low_relative_activity` 표본을 `max(volume_surge_ratio, turnover_surge_ratio)` band로 분리했다
- [x] `participation_rate_blocked` 표본을 `participation_rate` band로 분리했다
- [x] sample row에 `average_volume_20d / average_turnover_20d / volume_surge_ratio / turnover_surge_ratio / recommended_max_order_value / activity_participation_rate`를 노출했다
- [x] `2026-07-01 ~ 2026-07-10` 재집계에서 `entry_score>=0.52` 표본 2건이 `low_relative_activity_max_0_95_to_1_10` 1건과 `low_relative_activity_max_lt_0_80` 1건으로 갈림을 확인했다
- [x] 같은 구간 `0.55<=entry_score<0.65` 표본 1건은 `low_relative_activity_max_0_95_to_1_10`으로 확인했다
- [x] `pre_buy_staging_low_relative_activity_boundary_report` 전용 리포트를 추가했다
- [x] `low_relative_activity_max_0_95_to_1_10` 경계 코호트의 `cohort별 projection / trade_date별 projection` 실측을 `2026-06-01 ~ 2026-07-10` 재집계 기준으로 확인했다
- [x] `low_relative_activity_max_0_95_to_1_10` 경계 코호트의 `activity hard block`이 실제 `candidate` 전환 전 1차 병목인지 `entry/ranking gap`보다 앞서는지 추가 분해했다
- [x] `activity_first_small_entry_gap` / `activity_first_moderate_entry_gap` 코호트에서 `shadow_activity_pass`만 풀렸을 때 `top-k` 또는 `buy shape`가 다음 1차 병목인지 shadow counterfactual을 추가 계측한다
- [x] `buy_shape_after_activity_small_entry_gap` / `buy_shape_after_activity_moderate_entry_gap` 코호트를 `watch_from_entry_setup` / `watch_from_exit_setup` / `core_watch_gap_bridge`와 `entry gap band` 기준으로 재분해해 실제 다음 병목이 `entry setup WATCH`인지 확인한다
- [ ] `watch_from_entry_setup|small_entry_gap` / `watch_from_entry_setup|moderate_entry_gap` 코호트의 `T+1 / T+3 / MFE / MAE`와 `candidate -> selected -> would_buy -> submitted` 전환을 누적 관측해, 제한 완화 검증 대상 band를 좁힌다

### 4.5 작업 E — 장후 자동 배치 리포트 확장

- `trigger_proxy_attribution` 장후 배치 결과에 아래를 포함
  - `slow_trend_relax_candidate_items`
  - `slow_momentum_band_items`
  - `slow_trend_band_items`
  - `slow_component_path_items`
  - `shadow_relax_projection_*`

- 운영 요약에는 아래 수치를 남긴다
  - `trend_moderate_candidate_count`
  - `trend_edge_deep_count`
  - `trend_deep_tail_count`
  - `shadow_relax_projection_selected_count`

#### 작업 E 체크리스트

- [x] 장후 `trigger_proxy_attribution` 배치가 새 집계 필드를 출력한다
- [x] 장후 결과 JSON에 `slow_trend_relax_candidate_items`가 저장된다
- [x] 장후 결과 JSON에 `slow_momentum_band_items`가 저장된다
- [x] 장후 결과 JSON에 `slow_trend_band_items`가 저장된다
- [x] 장후 결과 JSON에 `slow_component_path_items`가 저장된다
- [x] 운영 요약에 `trend_moderate_candidate_count`가 남는다
- [x] 운영 요약에 `trend_edge_deep_count`가 남는다
- [x] 운영 요약에 `trend_deep_tail_count`가 남는다
- [x] 운영 요약에 `shadow_relax_projection_selected_count`가 남는다
- [x] 운영 요약에 `slow_floor_relax_ready_count / slow_floor_relax_watch_only_core_path_count`가 남는다
- [x] 운영 요약에 `watch_only_core_path large/moderate/small/entry_ready` entry-gap count가 남는다
- [x] 운영 요약에 `entry_gap_band`별 `candidate/would_buy/submitted` 전환 count가 남는다

### 4.6 작업 F — strict signal miss와 eligibility 차단축 직결 계측

- 목적:
  `shadow_topk_candidate` 미진입의 직접 원인인
  strict `overall/slow` 동시 미통과와,
  실제 `WATCH` 고착을 만드는 eligibility 차단축을
  같은 payload에서 바로 비교 가능하게 만든다.

- 추가 집계:
  - `eligibility_block_reason_primary_items`
  - `shadow_signal_floor_block_path_items`
  - `watch_eligibility_block_path_items`

- sample row 추가 필드:
  - `eligibility_block_reason_primary`
  - `shadow_signal_floor_block_path`
  - `watch_eligibility_block_path`

- fallback 원칙:
  - 명시 `eligibility_reasons`가 없더라도
    `shadow_activity_pass`,
    `shadow_overall_score_v5`,
    `shadow_slow_score_v5`,
    `shadow_rank_candidate_score`
    기준으로 1차 차단축을 추론한다.

#### 작업 F 체크리스트

- [x] `trigger_proxy_attribution.py`에 `eligibility_block_reason_primary` helper를 추가했다
- [x] `trigger_proxy_attribution.py`에 `shadow_signal_floor_block_path` helper를 추가했다
- [x] `trigger_proxy_attribution.py`에 `watch_eligibility_block_path` helper를 추가했다
- [x] 명시 `eligibility_reasons`가 없을 때 fallback 추론 규칙을 추가했다
- [x] attribution payload에 세 집계를 모두 추가했다
- [x] 단위 테스트를 보강하고 통과를 확인했다
- [x] `2026-07-06 ~ 2026-07-10` 재집계로 실제 분포를 확인했다

### 4.7 작업 G — active core risk-off 전용 `slow_trend` 비교 리포트 추가

- 목적:
  전체 표본 기준 집계와 별개로,
  실제 승격 판단 대상인 active `core_risk_off`만 잘라서
  `trend_moderate_candidate / trend_edge_deep / trend_deep_tail`
  후행 proxy와 projection 전환 수치를 즉시 읽을 수 있게 한다.

- 추가 리포트:
  - `active_slow_trend_relax_candidate_items`
  - `active_slow_trend_relax_candidate_report`
  - `active_slow_trend_projection_items`

- 판단 효용:
  - 다음 장후부터
    `trend_moderate_candidate`의 `T+1 / T+3` 빈칸 여부를
    전체 sample 재가공 없이 바로 확인할 수 있다.
  - `candidate_count → selected_count → would_buy_count → submitted_count`
    전환도 same-band 기준으로 직접 본다.

#### 작업 G 체크리스트

- [x] active `core_risk_off`만 대상으로 한 `slow_trend` band report를 추가했다
- [x] active `core_risk_off`만 대상으로 한 projection band count report를 추가했다
- [x] 단위 테스트를 보강하고 통과를 확인했다
- [x] `2026-07-06 ~ 2026-07-10` 재집계로 새 필드 생성을 확인했다

### 4.8 작업 H — `trade_date + band` 코호트 직접 판정 필드 추가

- 목적:
  다음 의사결정 시점인
  `2026-07-10|trend_moderate_candidate`
  2건을 raw sample 재가공 없이
  한 줄의 코호트 집계로 바로 읽는다.

- 추가 필드:
  - `active_slow_trend_trade_date_band_items`
  - `active_slow_trend_trade_date_projection_items`

- 사용 예시:
  - `2026-07-10|trend_moderate_candidate`
    - `sample_count`
    - `T+1 / T+3 / MFE / MAE`
    - `candidate_count / selected_count / would_buy_count / submitted_count`
  - 즉, `2026-07-13` 장후에는 같은 bucket 한 줄만 보면
    `T+1 + projection 전환`을 바로 판단할 수 있다.

#### 작업 H 체크리스트

- [x] active `trade_date + slow_trend band` aggregate field를 추가했다
- [x] active `trade_date + slow_trend band` projection field를 추가했다
- [x] 단위 테스트를 보강하고 통과를 확인했다
- [x] `2026-07-06 ~ 2026-07-10` 재집계에서 `2026-07-10|trend_moderate_candidate` bucket 생성을 확인했다

## 5. 검토 방법

### 5.1 관측 기간

- 최소 `3거래일`
- 가능하면 `5거래일`

### 5.2 비교 단위

1. `inactive`
2. `deep_negative`
3. `trend_edge_deep`
4. `trend_moderate_candidate`
5. `trend_mild_candidate`

### 5.3 비교 지표

모든 bucket에 대해 아래를 비교한다.

1. `T+1 평균 수익률`
2. `T+3 평균 수익률`
3. `T+3 양수 비율`
4. `T+3 MFE`
5. `T+3 MAE`
6. `sample_count`

### 5.4 승격 판단 기준

- `trend_moderate_candidate`가
  최소한 `inactive`와 비슷하거나 더 좋아야 한다.
- `trend_moderate_candidate`가
  기존 `deep_negative`보다 확실히 좋아야 한다.
- `MAE`가 과도하게 더 나빠지면 기각한다.
- `WATCH` 증가만 있고
  `BUY candidate` 또는 `submit` 경로 증가가 없으면 보류한다.
- churn 관련 부작용이 보이면 기각한다.

#### 실측 검토 체크리스트

- [x] 최소 3거래일 표본이 쌓였다
- [x] 가능하면 5거래일 표본까지 확보했다
- [x] `inactive` 대비 `trend_moderate_candidate`의 `T+1`을 비교했다
- [x] `inactive` 대비 `trend_moderate_candidate`의 `T+3`을 비교했다
- [x] `deep_negative` 대비 `trend_moderate_candidate`의 `T+1`을 비교했다
- [x] `deep_negative` 대비 `trend_moderate_candidate`의 `T+3`을 비교했다
- [x] `T+3 양수 비율`을 함께 비교했다
- [x] `T+3 MFE / MAE`를 함께 비교했다
- [x] 표본 수가 너무 적어 해석 불가한 bucket을 별도 표시했다
- [x] churn 또는 저유동성 부작용 유무를 함께 점검했다

## 6. 기대수익률 관점의 개선사항

### 6.1 하지 말아야 할 것

1. `deep_negative` 전체 완화
2. `buy threshold` 단순 하향
3. `slow_momentum`과 `slow_trend` 동시 완화
4. `low_relative_activity` hard block 해제 선행

### 6.2 먼저 해야 할 것

1. `slow_trend` 경계 구간만 shadow 완화 후보화
2. `slow_momentum`은 관측 유지
3. `shadow → buy/submit` 전환 계측 추가
4. 3거래일 이상 누적 후행 proxy 비교

### 6.3 기대수익률 목표와의 정렬 논리

- 현재 `deep_negative` 군을 넓게 풀면
  기대수익률이 낮은 종목까지 의사결정 경로에 들어오게 된다.
- 반대로 `slow_trend moderate_negative`처럼
  장기 추세 패널티는 남아 있지만
  완전한 구조적 하락군은 아닌 구간만 분리하면,
  과도 차단을 줄이면서도
  하락 확률이 높은 군을 통째로 허용하는 실수를 피할 수 있다.
- 따라서 본 백로그의 목적은
  “완화 자체”가 아니라
  “기대수익률이 덜 훼손되는 좁은 경계 구간만 검증 후 선택적 승격”이다.

## 7. 권장 실행 순서

1. `slow_trend_relax_candidate` 계측 필드 추가
2. 장후 attribution payload / 요약 리포트 확장
3. 최소 3거래일 자동 관측
4. `inactive` / `deep_negative` / `trend_moderate_candidate` proxy 비교
5. 통과 시에만 `authoritative` 후보 설계 문서 작성
6. 그 전까지는 shadow-only 유지

## 7-A. 단계별 진행 체크리스트

### 단계 1. 구현 준비

- [x] 실측 기준선 문서를 최신 상태로 확인했다
- [x] 변경 대상 파일 목록을 확정했다
- [x] 기존 v5 진단 필드와 충돌 여부를 검토했다

### 단계 2. 계측 구현

- [x] 작업 A 체크리스트를 모두 완료했다
- [x] 작업 B 체크리스트를 모두 완료했다
- [x] 작업 C 체크리스트를 모두 완료했다
- [x] 작업 D 체크리스트를 모두 완료했다
- [x] 작업 F 체크리스트를 모두 완료했다
- [x] 작업 E 체크리스트를 모두 완료했다
- [x] 작업 G 체크리스트를 모두 완료했다
- [x] 작업 H 체크리스트를 모두 완료했다

### 단계 3. 로컬/테스트 검증

- [x] 단위 테스트를 통과했다
- [x] attribution 스크립트 수동 실행이 성공했다
- [x] JSON 출력에 새 필드가 실제로 보인다

### 단계 4. 장후 실측 운영

- [x] 첫 장후 배치에서 새 집계가 생성됐다
- [ ] 2거래일 연속 장후 배치가 정상 적재됐다
- [x] 3거래일 누적 표본이 확보됐다

### 단계 5. 분석 및 판단

- [x] 실측 검토 체크리스트를 모두 점검했다
- [x] `trend_moderate_candidate`가 승격 후보인지 판단했다
- [x] `slow_momentum`은 계속 관측만 유지할지 판단했다
- [x] `deep_negative` 전체 완화 금지 원칙을 재확인했다

### 단계 6. 승격 또는 보류

- [ ] 승격 기준을 충족해 authoritative 설계 문서를 작성했다
- [x] 또는 근거 부족으로 shadow-only 유지 결론을 기록했다
- [x] 결론을 `[PRIORITY_MAP]`와 관련 분석 문서에 반영했다

## 9. 최신 실측 메모

- `2026-07-06 ~ 2026-07-10` 재집계 기준
  `shadow_relax_projection_candidate=5`,
  `selected=0`,
  `would_buy=0`,
  `submitted=0`이다.
- 즉 현재 병목은 `submit` 이후가 아니라
  `shadow_topk_candidate` 진입 이전 단계다.
- 후보 5건의 `shadow_relax_projection_block_reason`은
  전부 `shadow_topk_candidate_miss` 또는
  `momentum_deep_negative_guard`로 확인됐다.
- 후보 sample은 모두 `primary_candidate=WATCH`,
  `candidate_intent=watch`,
  `final_decision_type=watch`로 남아
  현재 상태에서는 `BUY path`로 전환되지 않는다.
- `shadow_topk_candidate_gate_reason` 실측은
  active 35건 전부 `signal_both_floor_miss`였다.
  즉 현재 `top-k candidate` 미진입의 직접 원인은
  `ranking/activity/strategy`보다
  strict `overall/slow` 동시 미통과다.
- `watch_primary_candidate_reason` 실측은
  `watch_with_eligibility_block=35`,
  `watch_setup_but_ineligible=15`,
  `core_watch_path_only=5`로 집계됐다.
  즉 `WATCH` 고착도 대부분은
  감시 후보가 BUY threshold를 넘어서서가 아니라
  buy eligibility를 통과하지 못한 상태에서 발생한다.
- `momentum_reason_code_items`는
  `momentum_3m_negative=25`,
  `momentum_3m_negative_shadow_v5=8`,
  `momentum_3m_soft_negative_shadow_v5=2`로 집계됐고,
  일자별 `slow_momentum moderate_negative` 표본은
  `2026-07-06=2`, `2026-07-07=2`, `2026-07-09=2`, `2026-07-10=4`다.
- 같은 기간 재집계에서
  `eligibility_block_reason_primary_items`는
  `eligibility_core_risk_off_ranking_blocked=35`,
  `eligibility_risk_off_block=24`,
  `eligibility_low_relative_activity=20`,
  `eligibility_negative_overall_floor=13` 순으로 나타났다.
- `shadow_signal_floor_block_path_items`는
  active 표본 대부분이
  `overall_fail|slow_fail|deep_negative|deep_negative|...`
  경로에 몰려 있어,
  strict `overall/slow` 동시 미통과가
  실제 top-k 미진입의 직접 병목임을 재확인했다.
- `watch_eligibility_block_path_items` 상위 경로는
  `non_watch_primary|eligibility_core_risk_off_ranking_blocked=20`,
  `watch_setup_but_ineligible|eligibility_low_relative_activity=15`,
  `watch_with_eligibility_block|eligibility_negative_overall_floor=13`이다.
- 같은 재집계 산출물을 `ops-scheduler` summary parser로 읽었을 때
  운영 요약에
  `trend_moderate_candidate_count=4`,
  `trend_edge_deep_count=14`,
  `trend_deep_tail_count=53`,
  `shadow_relax_projection_selected_count=0`
  이 실제로 노출되는 것까지 확인했다.
- 추가로 운영 요약에
  `slow_floor_relax_ready_count`,
  `slow_floor_relax_activity_blocked_count`,
  `slow_floor_relax_watch_only_core_path_count`
  를 함께 노출하도록 보강해,
  장후 배치 결과만으로도
  ready 코호트가 `WATCH`에 머무는지 즉시 확인 가능하게 했다.
- 다만 `2026-07-11` 현재 DB 상태로
  `2026-07-01 ~ 2026-07-10` 재집계를 다시 실행한 최신 산출물에서는
  `trend_moderate_candidate_count=13`,
  `slow_floor_relax_ready_count=0`,
  `slow_floor_relax_activity_blocked_count=0`,
  `slow_floor_relax_watch_only_core_path_count=0`으로 재산출됐다.
  즉 과거 메모의 `ready=1` 관측치는
  당시 시점 데이터와 현재 재집계 결과가 달라졌으므로,
  다음 단계에서 diff 원인 분석이 필요하다.
- 추가 원인 분해 결과,
  이 차이는 데이터 자체가 아니라
  `trigger_proxy_attribution` 메인 JSON의 generic 필드
  `core_risk_off_floor_report / core_risk_off_floor_diagnostics`
  와 `core_risk_off_floor_v5_report / core_risk_off_floor_v5_diagnostics`
  를 혼용해서 본 데서 비롯됐다.
- generic diagnostics는 non-v5 helper를 사용하므로
  같은 active `trend_moderate_candidate 4건`이
  `double_deep_miss / signal_score_missing`로 보였고,
  v5 diagnostics에서는
  기존 메모처럼 `slow_floor_relax_ready=1` 경로가 유지된다.
- 따라서 후속 장후 실측과 운영 요약은
  반드시 `core_risk_off_floor_v5_*` 기준으로 읽어야 하며,
  이번 턴에서 `ops-scheduler` summary parser도
  v5 report/diagnostics를 우선 읽도록 수정했다.
- 추가로 `active_slow_floor_relax_ready_samples` 필드를 붙여
  ready 코호트 sample row 자체를 별도 노출하도록 보강했다.
  최신 재집계 기준 ready 코호트는
  `2026-07-03 / 002790` 1건이며,
  `ranking_score=0.4166`,
  `entry_score=0.2479`,
  `shadow_overall_score_v5=-0.1274`,
  `shadow_slow_score_v5=-0.43`,
  `shadow_relax_projection_block_reason=shadow_topk_candidate_miss`,
  `watch_primary_candidate_reason=core_watch_path_only`
  상태로 직접 확인된다.
- 같은 sample에 대해 gap 계측을 추가한 결과,
  `deterministic_buy_shape_block_reason=watch_from_exit_setup`,
  `buy_candidate_threshold_gap=0.4021`,
  `core_risk_off_ranking_min_gap=0.0634`,
  `shadow_topk_ranking_min_gap=0.0`으로 나타났다.
  즉 현재 병목은
  `ranking` 자체가 전혀 안 되는 상태가 아니라,
  `WATCH`가 exit setup 성격으로 형성되고
  `entry_score`가 BUY threshold와 아직 멀리 떨어진 상태라는 점이다.
- `2026-07-01 ~ 2026-07-10` 최신 재집계에서
  active `trend_moderate_candidate` 4건은 전부
  `deterministic_buy_shape_block_reason=watch_from_exit_setup`으로 집계됐다.
  같은 4건의 후행 proxy는
  `T+1 평균 = 2.1376%`,
  `T+3 평균 = 4.3830%`,
  `T+3 양수 비율 = 100%`다.
- 같은 재집계의 active `core_risk_off` 전체 기준으로도
  `watch_from_entry_setup`은 0건이었고,
  `watch_from_exit_setup=21건`,
  `non_watch_primary=28건`으로 집계됐다.
  즉 현재 shadow 관찰군은
  `entry형 WATCH`가 아니라
  거의 전부 `exit형 WATCH`와 `core WATCH path`에서 형성되고 있다.
- `active_watch_reason_buy_shape_matrix_items` 기준으로는
  `core_watch_path_only|watch_from_exit_setup=8건`,
  `watch_with_eligibility_block|watch_from_exit_setup=13건`,
  `watch_from_entry_setup` 관련 active matrix는 0건이다.
- projection 집계 기준으로도
  `core_watch_path_only`는 `candidate=3 / selected=0`,
  `watch_with_eligibility_block`는 `candidate=6 / selected=0`,
  전체 `watch_from_exit_setup`는 `candidate=9 / selected=0`이다.
  따라서 현재 병목은
  `WATCH 형성`이 아니라
  그 이후 `selected` 전환 이전 단계에 그대로 머문다는 점이다.
- 새 전용 집계 기준으로
  `core_watch_path_only|watch_from_exit_setup` 8건은
  전부 `gate_reason=signal_both_floor_miss`,
  전부 `eligibility=eligibility_core_risk_off_ranking_blocked`였다.
- 같은 8건의 `projection_block_reason`은
  `shadow_topk_candidate_miss=3`,
  `trend_outside_target=4`,
  `momentum_deep_negative_guard=1`로 갈렸다.
  즉 이 코호트 전체도 다시
  `trend_moderate_candidate 3건`과
  `trend_edge_deep/deep_tail 5건`으로 나눠서 봐야 한다.
- 실제 sample 기준으로
  `shadow_topk_candidate_miss` 3건은
  `2026-07-02 000240`,
  `2026-07-03 002790`,
  `2026-07-10 002790`이며
  모두 `slow_trend_relax_candidate_band=trend_moderate_candidate`다.
- 새 전용 집계 기준으로
  이 3건은 전부
  `projection_block_reason=shadow_topk_candidate_miss`,
  `gate_reason=signal_both_floor_miss`,
  `eligibility=eligibility_core_risk_off_ranking_blocked`로 동일하게 묶였다.
- trade-date projection 기준으로도
  `2026-07-02`, `2026-07-03`, `2026-07-10`
  각 1건씩 모두 `candidate=1 / selected=0 / would_buy=0 / submitted=0`이다.
- 후행 proxy는
  `T+1 평균 = 2.1376%`,
  `T+3 평균 = 4.3830%`,
  `T+3 양수 비율 = 100%`로 유지된다.
- `shadow_signal_floor_miss_detail` 실측 기준으로는
  `overall_near_slow_deep=2건`,
  `overall_deep_slow_near=1건`이다.
  즉 현재 3건 코호트의 주 병목은
  `overall`보다 `slow floor` 쪽이 더 크다.
- 표본별로는
  `2026-07-02 / 000240`만 `overall_deep_slow_near`,
  `2026-07-03 / 002790`, `2026-07-10 / 002790`는
  모두 `overall_near_slow_deep`다.
- 따라서 다음 우선 작업은
  `ranking 완화`가 아니라
  `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
  3건 코호트에 한정한
  `slow floor` shadow 제한 완화안을 설계하고,
  그 영향만 계속 실측하는 것이다.
- 최신 `slow_floor_shadow_relax_path` 집계 기준으로는
  `slow_floor_relax_ready=1건`,
  `slow_floor_relax_activity_blocked=1건`,
  `overall_floor_first=1건`이다.
- 즉 실제 다음 shadow 완화 대상은
  3건 전체가 아니라
  `overall_near_slow_deep`이면서
  `ready` 또는 `activity_blocked`로 남은 2건이다.
- 표본 기준으로는
  `2026-07-03 / 002790 = slow_floor_relax_ready`,
  `2026-07-10 / 002790 = slow_floor_relax_activity_blocked`,
  `2026-07-02 / 000240 = overall_floor_first`다.
- 같은 기간 `slow_floor_relax_ready` 1건도
  `watch_from_exit_setup + core_watch_path_only + shadow_topk_candidate_miss`
  조합으로 고정되어 있었다.
  즉 현재 ready 코호트는
  `entry setup WATCH`가 아니라
  `exit setup WATCH`가 그대로 남아 있는 형태다.
- 따라서 다음 우선 작업은
  `watch_from_exit_setup`가
  `trend_moderate_candidate`에서 반복적으로 나타나는 구조가
  실제 기대수익률 우위와 일관적인지,
  그리고 `watch_from_entry_setup` 대비
  정말 authoritative 완화 후보로 볼 수 있는지
  코호트 비교로 더 분해하는 것이다.
- active `core_risk_off` 35건만 다시 잘라보면
  실제 후행 proxy 비교가 가능한 구간은
  `trend_edge_deep(4건)`와 `trend_deep_tail(29건)`이며,
  `trend_moderate_candidate(2건)`는 모두 `2026-07-10` 표본이라
  아직 `T+1 / T+3` proxy가 비어 있다.
- 이를 반복 재가공하지 않도록
  `active_slow_trend_relax_candidate_report`와
  `active_slow_trend_projection_items`를 추가했다.
  최신 재집계 기준
  `trend_moderate_candidate`는
  `sample_count=2`, `candidate_count=2`, `selected_count=0`,
  `would_buy_count=0`, `submitted_count=0`으로 바로 확인된다.
- `2026-07-06 ~ 2026-07-10` 재집계에서
  실제 `T+3`가 채워진 active 표본은 14건이며,
  모두 `trend_edge_deep` 또는 `trend_deep_tail`에 속했다.
  `trend_moderate_candidate`는 아직 전부 `2026-07-10` 표본이라
  `T+3`가 0건이다.
- 후속 판단용으로
  `active_slow_trend_trade_date_band_items`,
  `active_slow_trend_trade_date_projection_items`
  를 추가했다.
  최신 기준
  `2026-07-10|trend_moderate_candidate`는
  `sample_count=2`, `candidate_count=2`, `selected_count=0`,
  `would_buy_count=0`, `submitted_count=0`으로 바로 읽힌다.
- 따라서 현재는
  `trend_moderate_candidate` 승격 여부를 판단할 수 없고,
  `shadow-only 유지`가 맞다.
- 다음 우선 작업은
  `overall/slow strict miss` 중에서도
  `slow_trend` 경계 완화 shadow와 결합했을 때
  실제 `ranking_blocked / low_relative_activity / negative_overall_floor`
  어느 축이 먼저 줄어드는지
  장후 누적 관측으로 검증하는 것이다.
- `2026-07-01 ~ 2026-07-10` 재집계 기준으로는
  active `trend_moderate_candidate`가 총 4건 확인됐다.
  - `2026-07-02`: `000240`
  - `2026-07-03`: `002790`
  - `2026-07-10`: `000080`, `002790`
- 이 4건의 후행 proxy는
  `T+1 평균 = 2.1376%`,
  `T+3 평균 = 4.3830%`,
  `T+3 양수 비율 = 100%`로
  `inactive` / `deep_negative` 대비 우위였다.
- 하지만 동일 4건 모두
  `candidate_count=4`, `selected_count=0`,
  `would_buy_count=0`, `submitted_count=0`이다.
- 개별 코호트 분해 결과
  4건 모두 `shadow_relax_projection_block_reason=shadow_topk_candidate_miss`,
  `shadow_topk_candidate_gate_reason=signal_both_floor_miss`였다.
- 즉 현재 직접 병목은
  `top-k 순위 경쟁`이 아니라
  `shadow_topk_candidate` 진입 이전의
  strict `overall/slow` 동시 미통과다.
- 같은 4건은 모두
  `eligibility_block_reason_primary=eligibility_core_risk_off_ranking_blocked`
  로도 기록돼,
  이후 authoritative 검토 전에는
  `signal floor` shadow 완화와 `ranking blocked` 완화의
  선후관계를 분리해서 검증해야 한다.
- 같은 4건에 대해
  `shadow_signal_floor_miss_detail`를 추가로 분해한 결과,
  `overall_near_slow_deep=3`,
  `overall_deep_slow_near=1`이다.
- 즉 `trend_moderate_candidate` 다수는
  `overall`보다 `slow`의 깊은 음수 때문에 strict floor에서 막힌다.
- 따라서 다음 shadow 관측은
  `overall floor` 전체 완화가 아니라
  `slow_trend` 중심의 제한적 `slow floor` shadow 완화가 우선이다.
- `slow_momentum`은 이번 단계에서도 완화 근거가 충분하지 않으므로
  계속 관측 전용으로 유지한다.
- 추가 `slow_floor_shadow_relax_path` 실측 결과,
  active `trend_moderate_candidate` 4건은
  `slow_floor_relax_ready=1`,
  `slow_floor_relax_activity_blocked=2`,
  `overall_floor_first=1`로 분해됐다.
- 즉 실제 다음 관측 대상으로 남는 것은
  `trend_moderate_candidate` 전체가 아니라
  `slow_floor_relax_ready` 1건 코호트다.
- 이 결과는
  `low_relative_activity` hard block을 유지한 상태에서도
  `slow_trend` 중심 shadow 관측을 좁은 범위에서 계속할 수 있다는 근거다.
- 날짜 단위 재집계 기준
  현재 `slow_floor_relax_ready` 코호트는
  `2026-07-03` 1건뿐이며,
  `candidate_count=1`, `selected_count=0`,
  `would_buy_count=0`, `submitted_count=0`이다.
- 따라서 다음 후속 작업은
  `slow_floor_relax_ready` 코호트의
  `selected=0` 직접 원인을 장후 리포트에서 더 세밀하게 추적하는 것이다.
- 추가 직접 원인 집계 기준으로
  같은 `2026-07-03` 코호트는
  `projection_block_reason=shadow_topk_candidate_miss`,
  `gate_reason=signal_both_floor_miss`,
  `watch_reason=core_watch_path_only`로 확인됐다.
- 전환 단계 집계 기준으로도
  동일 코호트는 `watch_only_core_path=1`이다.
- 날짜별 전환 단계 집계 기준으로는
  `2026-07-03|watch_only_core_path=1`이다.
- 즉 현재 ready 코호트조차
  `BUY candidate` 구조로 넘어간 것이 아니라
  strict gate 하에서 `WATCH`에 머무는 상태다.
- 다음 우선 작업은
  `slow_floor_relax_ready` 코호트가
  `WATCH -> BUY candidate`로 전환될 수 있는지를
  장후 누적 관측으로 확인하는 것이다.
- 제한 `slow floor` shadow 재집계 기준
  `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
  3건은 아래처럼 직접 분해된다.
  - `candidate_ready=1`
    - `2026-07-03 / 002790`
    - 그러나 `limited_slow_floor_transition_stage=candidate_ready_watch_only_core_path`
  - `activity_blocked=1`
    - `2026-07-10 / 002790`
  - `overall_floor_first=1`
    - `2026-07-02 / 000240`
- 즉 `slow_trend` 제한 완화 shadow를 넣어도
  바로 `BUY candidate`가 열리는 것이 아니라,
  현재 첫 후행 병목은
  `watch_only_core_path`와 `activity_blocked`다.
- 따라서 다음 우선 작업은
  `candidate_ready_watch_only_core_path`
  코호트의 `WATCH -> BUY shape` 전환 조건을
  별도 shadow로 계측하는 것이다.
- 해당 후속 계측 결과,
  현재 유일한 `candidate_ready_watch_only_core_path`
  표본 `2026-07-03 / 002790`는
  `watch_only_core_path_shadow_reason=exit_setup_large_entry_gap`
  으로 분류됐다.
  - `buy_candidate_threshold_gap=0.4021`
  - `core_risk_off_ranking_min_gap=0.0634`
- 즉 현재 1차 병목은 `ranking`보다
  `BUY threshold`까지의 큰 `entry gap`이며,
  `watch_from_exit_setup` shape 자체는
  그 다음 해석 보조축으로 보는 것이 맞다.
- 따라서 다음 우선 작업은
  `candidate_ready_watch_only_core_path`
  코호트에서
  `entry gap`이 큰 경우와 작은 경우를 분리해
  추가 표본을 누적 관측하는 것이다.
- 이를 위해
  `watch_only_core_path_entry_gap_band`
  와
  `trade_date|entry_gap_band`
  집계를 추가했다.
  현재 재집계 기준으로는
  `2026-07-03|large_entry_gap=1`만 존재한다.
- 같은 값이 `ops-scheduler`의
  장후 `trigger_proxy_attribution` summary parser에도 반영되도록
  `watch_only_core_path_large_entry_gap_count`,
  `watch_only_core_path_moderate_entry_gap_count`,
  `watch_only_core_path_small_entry_gap_count`,
  `watch_only_core_path_entry_ready_count`
  를 추가했다.
- 추가로
  `watch_only_core_path_entry_gap_projection_items`
  와
  `trade_date|entry_gap_projection`
  집계를 붙여,
  각 gap band별로
  `candidate_count / selected_count / would_buy_count / submitted_count`
  를 직접 비교할 수 있게 했다.
- 같은 값이 `ops-scheduler` summary parser에도 반영되도록
  `watch_only_core_path_*_entry_gap_candidate_count`,
  `watch_only_core_path_*_entry_gap_would_buy_count`,
  `watch_only_core_path_*_entry_gap_submitted_count`
  도 함께 노출되게 했다.
- `2026-07-01 ~ 2026-07-10` 구간을
  최신 코드 기준으로 다시 재집계한
  `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v12_entry_gap_recheck.json`
  기준으로도
  `candidate_ready_watch_only_core_path`의 `entry_gap_band`는
  `2026-07-03|large_entry_gap=1`만 유지됐다.
  - `moderate_entry_gap=0`
  - `small_entry_gap=0`
  - `entry_ready=0`
- 즉 현재 상태는
  단순히 `2026-07-10` 이후 후행 proxy가 덜 채워진 문제가 아니라,
  **현행 shadow 조건과 과거 원자료 기준으로는
  `moderate/small/entry_ready` band 자체가 아직 발생하지 않는 상태**다.
- 같은 재집계에서
  유일한 `large_entry_gap` 1건은
  `candidate_count=1`,
  `selected_count=0`,
  `would_buy_count=0`,
  `submitted_count=0`,
  `T+1=+1.4583%`,
  `T+3=+3.3333%`,
  `T+3 MFE=+4.7917%`,
  `T+3 MAE=-0.4167%`로 재확인됐다.
- 따라서 현재 단계의 결론은
  `entry_gap_band` 누적 관측 자체는 계속 유지하되,
  authoritative 완화는 여전히 금지하고
  `shadow-only 유지`가 맞다.
- 이어서 `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v13_buy_gap_diagnostics.json`
  기준으로
  상위 `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
  3건 전체를 다시 보면
  `buy_candidate_threshold_gap_band`는 아래처럼 분해된다.
  - `large_entry_gap=2`
    - `2026-07-03 / 002790`
    - `2026-07-10 / 002790`
  - `buy_gap_missing=1`
    - `2026-07-02 / 000240`
  - `moderate_entry_gap=0`
  - `small_entry_gap=0`
  - `entry_ready=0`
- 단계 교차 기준으로도
  `candidate_ready_watch_only_core_path|large_entry_gap=1`,
  `activity_blocked|large_entry_gap=1`,
  `overall_floor_first|buy_gap_missing=1`
  로만 나타났다.
- 즉 `candidate_ready_watch_only_core_path` 내부만 좁게 봐서
  `large`만 남는 것이 아니라,
  상위 target 코호트 전체에서도
  `non-null buy gap`은 전부 `large`다.
- 현재 해석상
  `moderate/small/entry_ready` 표본 부재의 주된 원인은
  단순 후행 proxy 미적재보다
  `shadow_entry_score` 자체의 하방 편향으로 보는 쪽이 더 타당하다.
- 따라서 다음 우선 작업은
  `watch_from_exit_setup` target 코호트의
  `shadow_entry_score / buy gap / ranking gap` 분포를
  authoritative BUY 경로와 나란히 비교해서,
  현재 구조가 정말 `entry_score` 병목인지 추가 분해하는 것이다.
- 후속 `v15` strict 비교 계측 결과,
  `2026-06-01 ~ 2026-07-10` 전체에서도
  strict 기준의 `authoritative core BUY path`
  (`buy_candidate=true` 또는 `candidate_intent=buy` 또는 `primary_candidate=buy_candidate`)
  표본은 `0건`이었다.
- 즉 현재는
  target 코호트가 BUY로 못 가는 문제를 넘어,
  비교군이 되어야 할 실운영 `core BUY` baseline 자체가 비어 있다.
- 이 결과는
  `entry_score` 하방 편향 가설을 약화시키지 않고,
  오히려 시스템 전체에서
  `BUY path`가 열리지 않는 구조적 병목이 있음을 시사한다.
- 따라서 다음 우선 작업은
  `actual BUY baseline`과의 직접 비교에서 한 단계 앞당겨,
  `watch_from_entry_setup` 또는 `entry_score >= 0.52` 근접군처럼
  **pre-BUY staging cohort**를 비교군으로 재정의하는 것이다.

## 8. 관련 문서

- [`plans/[PRIORITY_MAP] remaining_work_priority_map.md`](./%5BPRIORITY_MAP%5D%20remaining_work_priority_map.md)
- [`plans/[ANALYSIS] core_risk_off_floor_v5_report_measurement_2026-07-11.md`](./%5BANALYSIS%5D%20core_risk_off_floor_v5_report_measurement_2026-07-11.md)
- [`plans/[ANALYSIS] signal_backbone_slow_score_threshold_tuning_2026-07-09.md`](./%5BANALYSIS%5D%20signal_backbone_slow_score_threshold_tuning_2026-07-09.md)
- [`plans/[PLAN] core_risk_off_ranking_relaxation_phase1.md`](./%5BPLAN%5D%20core_risk_off_ranking_relaxation_phase1.md)
- [`plans/[DESIGN] deterministic_trigger_eligibility_and_ranking_v1.md`](./%5BDESIGN%5D%20deterministic_trigger_eligibility_and_ranking_v1.md)
