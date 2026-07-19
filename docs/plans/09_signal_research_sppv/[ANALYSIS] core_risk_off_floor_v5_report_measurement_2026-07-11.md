# `core_risk_off_floor_v5_report` 실측 비교 분석

> **📌 2026-07-14 검증 범위 경계 (중요)**: 이 분석을 포함한 core_risk_off /
> entry_score 백테스트의 **유효 범위는 "이번 하락 국면 한정"이다.** 표본이
> 단일 급락 국면 약 2주에 집중(상승장·횡보장 표본 전무)이고, 실집행이 아닌
> 후행수익률 proxy shadow 관측이며, 핵심 비교가 N=35~49 소표본(완화 후보는
> N=3~4로 leave-one-out에서 부호 뒤집힘)이다. 따라서 "매수 억제가 옳았다"는
> 결론을 "모든 시장 국면에서 항구적으로 옳다"로 확대 해석하면 안 된다.
> 상세: `plans/[ANALYSIS] foundational_design_review_objective_alignment_2026-07-14.md`.

## 1. 목적과 결론

이번 분석의 목적은 `core_risk_off_floor_v5_report`의 `mild_relax` / `moderate_relax` 표본과 `T+1` / `T+3` 후행 수익률 proxy를 실측 비교하여, 현재 v5 완화안이 실제 완화 경로를 만들고 있는지 확인하는 것이다.

결론은 다음과 같다.

1. `2026-07-06` ~ `2026-07-09`에 생성된 기존 attribution 로그에는 `core_risk_off_floor_v5_report`와 `core_risk_off_floor_v5_diagnostics`가 없다.
2. 현재 저장소에서 실측 가능한 v5 결과는 `logs/trigger_proxy_attribution_2026-07-10.json` 1개이며, 이 파일의 분석 기간은 `2026-06-27` ~ `2026-07-10`이다.
3. 해당 v5 실측에서 active 표본 49건은 전부 `deep_negative`이고, `mild_relax` / `moderate_relax` / `strict_pass`는 모두 0건이다.
4. v5 완화안이 실제 완화 경로를 만들지 못한 직접 원인은 `shadow_overall_score_v5`와 `shadow_slow_score_v5`가 attribution 입력의 `core_risk_off_experiment`에 적재되지 않아, bucket 재분류 단계에서 모든 active row가 `overall_missing` → `deep_negative`로 떨어졌기 때문이다.
5. 따라서 이번 실측만으로는 v5 점수 정책 자체가 너무 엄격한지까지는 판정할 수 없고, 우선 v5 score field 적재/재집계 경로를 복구한 뒤 같은 기간을 재실행해야 한다.

## 2. 읽은 기준 문서와 코드

### 기준 문서

- `plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md`
- `plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md`
- `plan_docs/HANDOFF_TO_ROO_CODE.md`
- `plan_docs/detailed_design/README.md`
- `plan_docs/detailed_design/01_system_architecture.md`
- `plan_docs/detailed_design/02_order_execution_sequence.md`
- `plan_docs/detailed_design/03_data_model_erd.md`
- `plan_docs/detailed_design/08_ai_decision_policy.md`
- `plan_docs/detailed_design/09_market_and_event_data_policy.md`
- `plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md`
- `plans/README.md`
- `plans/[PRIORITY_MAP] remaining_work_priority_map.md`
- `plans/[BACKLOG] backlog.md`
- `plans/[CHECKLIST] after_market_measurement_validation.md`
- `plans/[ANALYSIS] signal_backbone_slow_score_threshold_tuning_2026-07-09.md`
- `plans/[GUIDE] end_to_end_order_flow_guide.md`

### 기준 코드

- `scripts/analyze_trigger_proxy_attribution.py`
- `scripts/build_signal_feature_snapshots.py`
- `src/agent_trading/services/trigger_proxy_attribution.py`
- `src/agent_trading/services/deterministic_trigger_engine.py`
- `src/agent_trading/services/signal_backbone.py`
- `tests/services/test_trigger_proxy_attribution.py`
- `tests/services/test_deterministic_trigger_engine.py`
- `tests/services/test_signal_backbone.py`
- `tests/scripts/test_build_signal_feature_snapshots.py`

## 3. 사용한 실측 데이터와 데이터 범위

### 로그 파일 존재 여부

| 파일 | 내부 분석 기간 | 표본 수 | v5 report | v5 diagnostics | 비고 |
| --- | --- | ---: | --- | --- | --- |
| `logs/trigger_proxy_attribution_2026-07-06.json` | `2026-06-23` ~ `2026-07-06` | 268 | 없음 | 없음 | v5 도입 전 산출물 |
| `logs/trigger_proxy_attribution_2026-07-06_rerun.json` | `2026-07-06` ~ `2026-07-06` | 12 | 없음 | 없음 | v5 도입 전 산출물 |
| `logs/trigger_proxy_attribution_2026-07-07.json` | `2026-06-24` ~ `2026-07-07` | 239 | 없음 | 없음 | v5 도입 전 산출물 |
| `logs/trigger_proxy_attribution_2026-07-07_rerun.json` | `2026-07-07` ~ `2026-07-07` | 21 | 없음 | 없음 | v5 도입 전 산출물 |
| `logs/trigger_proxy_attribution_2026-07-08.json` | `2026-06-25` ~ `2026-07-08` | 222 | 없음 | 없음 | v5 도입 전 산출물 |
| `logs/trigger_proxy_attribution_2026-07-08_rerun.json` | `2026-07-08` ~ `2026-07-08` | 22 | 없음 | 없음 | v5 도입 전 산출물 |
| `logs/trigger_proxy_attribution_2026-07-09.json` | `2026-06-26` ~ `2026-07-09` | 205 | 없음 | 없음 | 요청에 언급된 `2026-07-09_rerun_v5` 파일은 현재 저장소에 없음 |
| `logs/trigger_proxy_attribution_2026-07-10.json` | `2026-06-27` ~ `2026-07-10` | 204 | 있음 | 있음 | 현재 유일한 v5 실측 가능 로그 |

### DB 확인 상태

`PYTHONPATH=src python3 scripts/analyze_trigger_proxy_attribution.py --start-date 2026-07-06 --end-date 2026-07-10 --output json --write-json logs/trigger_proxy_attribution_2026-07-06_2026-07-10_v5_analysis.json --sample-limit 200 --sleep-seconds 0` 명령으로 DB 재집계를 시도했으나, 현재 환경에서 PostgreSQL `localhost:5432` 연결이 거부되어 신규 DB 적재 결과를 직접 재조회하지 못했다. 따라서 이 문서의 정량 수치는 저장소에 이미 존재하는 JSON 로그 기준이다.

## 4. 날짜별 bucket 분포

현재 저장소의 v5 bucket 분포는 `2026-07-10` 누적 로그에서만 확인된다. `2026-07-06` ~ `2026-07-09` 일자별 v5 분포는 해당 로그들에 v5 section이 없어 실측 불가다.

| 산출 파일 | strict_pass | mild_relax | moderate_relax | deep_negative | inactive | unknown | active 표본 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `logs/trigger_proxy_attribution_2026-07-10.json` | 0 | 0 | 0 | 49 | 155 | 0 | 49 |

핵심 관찰:

- active 49건 중 `mild_relax` / `moderate_relax`는 0건이다.
- active 49건 전부 `deep_negative`로 분류됐다.
- 전체 204건 중 155건은 `core_risk_off_experiment.active=false` 또는 experiment payload 부재로 `inactive`다.

## 5. T+1 / T+3 proxy 비교

`core_risk_off_floor_v5_report.items` 기준 비교 결과는 다음과 같다.

| bucket | sample_count | T+1 평균 수익률 | T+3 평균 수익률 | positive T+3 hit rate |
| --- | ---: | ---: | ---: | ---: |
| strict_pass | 0 | 없음 | 없음 | 없음 |
| mild_relax | 0 | 없음 | 없음 | 없음 |
| moderate_relax | 0 | 없음 | 없음 | 없음 |
| deep_negative | 49 | -0.8638% | -2.7372% | 32.14% |
| inactive | 155 | -0.3197% | -2.1956% | 46.36% |

해석:

- `mild_relax`와 `moderate_relax`의 표본이 0건이므로 두 완화 bucket의 T+1 / T+3 성과 우열은 비교할 수 없다.
- 현재 유일한 v5 실측에서 active 표본은 모두 `deep_negative`이며, 이 bucket의 `T+3` 평균은 -2.7372%로 음수다.
- 다만 이 결과는 v5 완화 정책 자체의 성과라기보다 v5 score field 미적재로 active 표본이 모두 missing 처리된 결과이므로, 정책 유효성 판단에는 재집계가 필요하다.

## 6. 코드 기준 원인 추적

### 6.1 어떤 score field가 bucket 분류에 쓰이는가

v5 bucket 분류는 `core_risk_off_experiment` payload 안의 아래 필드를 사용한다.

- `shadow_floor_relax_v5_bucket`
- `shadow_overall_score_v5`
- `shadow_slow_score_v5`
- `shadow_activity_pass`
- `shadow_strategy_pass`
- `shadow_entry_score`
- `raw_ranking_score`

`trigger_proxy_attribution.py`의 `build_core_risk_off_floor_v5_bucket_rows()`는 우선 payload의 `shadow_floor_relax_v5_bucket`을 읽고, 없거나 유효하지 않으면 `_resolve_shadow_floor_bucket()`에서 `shadow_overall_score_v5`와 `shadow_slow_score_v5`로 재분류한다.

### 6.2 v5 threshold

v5 완화 threshold는 다음과 같이 고정돼 있다.

| bucket | 필수 조건 |
| --- | --- |
| strict_pass | `overall >= 0.0` 그리고 `slow >= -0.05` |
| mild_relax | `overall >= -0.20` 그리고 `slow >= -0.15` |
| moderate_relax | `overall >= -0.25`, `slow >= -0.25`, `entry_score >= 0.12`, `ranking_score >= 0.26`, `shadow_activity_pass=true`, `shadow_strategy_pass=true` |
| deep_negative | 위 조건을 모두 만족하지 못함 |

### 6.3 실제 병목

`logs/trigger_proxy_attribution_2026-07-10.json`의 v5 diagnostics는 다음과 같이 집계된다.

| 진단 축 | bucket | 표본 수 | 의미 |
| --- | --- | ---: | --- |
| overall_band | missing | 204 | v5 overall score가 diagnostics 입력에서 전부 없음 |
| slow_band | missing | 204 | v5 slow score가 diagnostics 입력에서 전부 없음 |
| moderate_gate | inactive | 155 | active가 아닌 표본 |
| moderate_gate | signal_window_miss | 49 | active이지만 overall/slow score window가 없음 |
| blocking_reason | inactive | 155 | active가 아닌 표본 |
| blocking_reason | overall_missing | 49 | active 표본의 직접 차단 사유 |
| bucket_path | `missing|missing|inactive` | 155 | inactive 경로 |
| bucket_path | `missing|missing|signal_window_miss` | 49 | active이지만 v5 score missing 경로 |

따라서 현재 병목은 `slow` threshold 자체라기보다, v5 score field가 attribution payload까지 전달되지 않은 것이다. `overall`, `slow`, `shadow_component_scores_v5` 중에서는 `overall`과 `slow`가 먼저 missing이고, `shadow_component_scores_v5`는 현재 v5 diagnostics/report가 직접 사용하지 않는다. `reason_code` 역시 현재 로그에서는 v5 차단 원인 판별 전에 score missing으로 막혀, 실제 threshold 원인 분석에 충분한 근거가 없다.

### 6.4 실제 데이터 예시 수준의 설명

현재 `2026-07-10` 로그의 v5 diagnostics sample은 `sample_limit` 영향으로 앞쪽 inactive 표본만 들어 있다. 예를 들어 `2026-06-29`의 `000080`, `000100`, `000120` sample은 `core_risk_off_experiment`가 `{}`이고, `shadow_overall_score` / `shadow_slow_score`가 `None`이어서 `core_risk_off_floor_v5_bucket=inactive`, `bucket_path=missing|missing|inactive`로 기록된다.

active 49건은 sample 목록에는 포함되지 않았지만 aggregate diagnostics에서 모두 `bucket_path=missing|missing|signal_window_miss`, `blocking_reason=overall_missing`로 집계됐다. 즉 active row의 형태는 다음 경로로 해석된다.

```text
core_risk_off_experiment.active = true
shadow_overall_score_v5 = None
shadow_slow_score_v5 = None
→ overall_band = missing
→ slow_band = missing
→ moderate_gate_bucket = signal_window_miss
→ blocking_reason = overall_missing
→ core_risk_off_floor_v5_bucket = deep_negative
```

## 7. 수정 필요 여부 판단

이번 Task에서 정책 threshold를 조정하지 않았다. 이유는 다음과 같다.

1. 현재 실측은 v5 score field 미적재로 인해 `mild_relax` / `moderate_relax` 진입 가능성을 평가할 수 없다.
2. policy threshold 변경은 근거 없는 완화가 될 수 있다.
3. 먼저 `shadow_overall_score_v5`, `shadow_slow_score_v5`, 가능하면 `shadow_component_scores_v5`, `shadow_reason_codes_v5`가 `core_risk_off_experiment`와 attribution report까지 전달되는지 검증해야 한다.

다음 최소 보강 후보는 정책 변경이 아니라 계측 보강이다.

- `core_risk_off_floor_v5_diagnostics.samples`가 inactive 앞부분으로만 채워지지 않도록 active/deep_negative 우선 sample을 포함한다.
- `core_risk_off_experiment`에 `shadow_component_scores_v5`와 `shadow_reason_codes_v5`를 함께 적재해 `slow_momentum` / `slow_trend` 중 어떤 component가 병목인지 볼 수 있게 한다.
- `2026-07-06` ~ `2026-07-10` 구간을 v5 코드 기준으로 재집계하여 `logs/trigger_proxy_attribution_2026-07-06_2026-07-10_v5_rerun.json` 같은 별도 산출물을 남긴다.

## 8. `[PRIORITY_MAP]` 기준 진전 항목

이번 작업은 신규 주문 경로를 바꾸지 않고 장후 실측/성과 분석 체인을 점검한 것이므로, 우선순위 문서의 실행 안전성 항목이 아니라 장후 실측 검증 흐름에 대한 진전으로 보는 것이 맞다. 구체적으로는 다음 항목에 대한 판단 근거가 추가됐다.

- 장후 `trigger_proxy_attribution` 로그에 v5 section이 실제 포함되는지 확인했다.
- `core_risk_off_floor_v5_report`의 완화 bucket이 현재 실측에서 비어 있음을 수치로 확인했다.
- 완화 bucket 부재가 policy threshold 때문인지, 계측/적재 field missing 때문인지 분리했다.

## 9. 다음 단계 제안

1. DB/PostgreSQL 접근 가능한 운영 환경에서 `2026-07-06` ~ `2026-07-10` 구간을 v5 코드 기준으로 재실행한다.
2. 재실행 산출물에 `shadow_overall_score_v5` / `shadow_slow_score_v5`가 active row에 채워졌는지 먼저 확인한다.
3. active row에 score가 채워진 뒤에도 `mild_relax` / `moderate_relax`가 0이면, 그때 `slow_momentum`, `slow_trend`, `fast_score`, `reason_codes_v5` 분해로 threshold 병목을 다시 판정한다.
4. active/deep_negative sample이 diagnostics sample에 반드시 포함되도록 최소 계측 보강을 별도 Task로 진행한다.

## 10. `v5 field propagation` 복구 후 재실측 결과

`2026-07-11` 후속 작업에서 `scripts/analyze_trigger_proxy_attribution.py`에
`signal_feature_snapshots.component_scores_json` fallback을 추가하여,
과거 `trade_decision.decision_json`의 `core_risk_off_experiment`에 비어 있던
`shadow_overall_score_v5`, `shadow_slow_score_v5`,
`shadow_component_scores_v5`, `shadow_reason_codes_v5`,
`shadow_diagnostics_v5`를 재집계 시 보강하도록 수정했다.

이후 아래 명령으로 `2026-07-06` ~ `2026-07-10` 구간을 재집계했다.

```bash
docker compose exec -T ops-scheduler bash -lc 'cd /app && python3 scripts/analyze_trigger_proxy_attribution.py \
  --start-date 2026-07-06 \
  --end-date 2026-07-10 \
  --output json \
  --write-json /app/logs/trigger_proxy_attribution_2026-07-06_2026-07-10_v5_rerun.json \
  --sample-limit 200 \
  --sleep-seconds 0'
```

산출물:

- `logs/trigger_proxy_attribution_2026-07-06_2026-07-10_v5_rerun.json`

### 10.1 복구 여부

- active 표본: 35건
- 이 중 `shadow_overall_score_v5` / `shadow_slow_score_v5`가 실제로 채워진 표본: 28건
- 남은 7건은 `2026-07-06` 의사결정으로, 연결된 snapshot 자체가 v5 이전 산출물이라 v5 score가 여전히 비어 있다.

즉, 이전처럼 active 전부가 `overall_missing`으로 무너지는 상태는 해소되었고,

## 11. 제한 `slow floor` shadow 후속 관측 메모

`2026-07-01 ~ 2026-07-10` 재집계 기준으로
`core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
제한 코호트에 대해
`limited_slow_floor_shadow_path`,
`limited_slow_floor_transition_stage`
를 추가 계측한다.

이 계측의 목적은
`slow_trend` 제한 완화 shadow를 적용하더라도
바로 `BUY candidate`로 열리는지,
아니면 `watch_only_core_path`, `activity_blocked`,
`overall_floor_first` 같은 후행 병목이 남는지를
같은 payload에서 직접 확인하는 것이다.

따라서 다음 실측의 직접 판정 기준은
`WATCH 증가`가 아니라 아래 순서다.

1. `trend_moderate_candidate` 제한 코호트가 `candidate_ready`로 이동하는지
2. `candidate_ready` 이후 `projection_buy_shape`로 이어지는지
3. 이어지지 않으면 `watch_only_core_path`인지, 다른 buy-shape 차단인지
4. 이 경로가 `inactive` / `deep_negative` 대비 후행 proxy 우위를 유지하는지

## 12. `2026-07-01 ~ 2026-07-10` 제한 `slow floor` shadow 재집계 결과

테스트 통과 후 같은 기간을 다시 재집계하여
`core_risk_off_floor_v5_diagnostics` 안의
제한 코호트 집계를 직접 확인했다.

대상 코호트:

- `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`

집계 결과:

| 집계 축 | bucket | 표본 수 | T+1 평균 | T+3 평균 | 해석 |
| --- | --- | ---: | ---: | ---: | --- |
| `signal_floor_miss_detail` | `overall_near_slow_deep` | 2 | 1.4583% | 3.3333% | `slow` 쪽이 직접 병목 |
| `signal_floor_miss_detail` | `overall_deep_slow_near` | 1 | 2.8169% | 5.4326% | `overall`이 먼저 막음 |
| `limited_slow_floor_path` | `candidate_ready` | 1 | 1.4583% | 3.3333% | 제한 `slow floor` shadow 통과 |
| `limited_slow_floor_path` | `activity_blocked` | 1 | 없음 | 없음 | 상대활동성/활동성 후행 병목 |
| `limited_slow_floor_path` | `overall_floor_first` | 1 | 2.8169% | 5.4326% | 이번 완화 대상 아님 |
| `limited_slow_floor_transition_stage` | `candidate_ready_watch_only_core_path` | 1 | 1.4583% | 3.3333% | `BUY shape`로는 아직 미전환 |

개별 표본은 아래와 같이 해석된다.

1. `2026-07-03 / 002790`
   - `limited_slow_floor_shadow_path=candidate_ready`
   - `limited_slow_floor_transition_stage=candidate_ready_watch_only_core_path`
   - `shadow_overall_score=-0.1274`
   - `shadow_slow_score=-0.43`
   - `shadow_ranking_score=0.4166`
   - 즉 `slow_trend` 제한 완화 shadow를 주면
     `signal floor` 직접 병목은 넘어가지만,
     아직 `WATCH` 구조에 머물러 `BUY candidate`는 열리지 않는다.

2. `2026-07-10 / 002790`
   - `limited_slow_floor_shadow_path=activity_blocked`
   - `shadow_activity_pass=false`
   - 즉 같은 `overall_near_slow_deep`라도
     실제 다음 병목은 `activity`다.

3. `2026-07-02 / 000240`
   - `limited_slow_floor_shadow_path=overall_floor_first`
   - `shadow_overall_score=-0.415`
   - `shadow_slow_score=-0.19`
   - 즉 이 표본은 `slow`보다 `overall`이 먼저 막으므로,
     현재 `slow_trend` 제한 완화 shadow 대상에서 제외하는 것이 맞다.

추가 분해:

- `candidate_ready_watch_only_core_path` 1건에 대해
  `watch_only_core_path_shadow_reason`를 계측한 결과,
  `exit_setup_large_entry_gap=1`로 나타났다.
- 해당 표본의 세부값은 다음과 같다.
  - `trade_date=2026-07-03`
  - `symbol=002790`
  - `buy_candidate_threshold_gap=0.4021`
  - `core_risk_off_ranking_min_gap=0.0634`
- 추가 `entry_gap_band` 집계 기준으로도
  같은 표본은
  `large_entry_gap`
  으로 분류된다.
  일자별 bucket은
  `2026-07-03|large_entry_gap=1`이다.
- 동일 집계를 `ops-scheduler` summary parser로 읽었을 때도
  아래 운영 지표가 그대로 노출된다.
  - `watch_only_core_path_large_entry_gap_count=1`
  - `watch_only_core_path_moderate_entry_gap_count=0`
  - `watch_only_core_path_small_entry_gap_count=0`
  - `watch_only_core_path_entry_ready_count=0`
- 같은 코호트의 `entry_gap_projection` 집계는 현재 아래와 같다.
  - `large_entry_gap`
    - `sample_count=1`
    - `candidate_count=1`
    - `selected_count=0`
    - `would_buy_count=0`
    - `submitted_count=0`
  - 나머지 `moderate/small/entry_ready`는 모두 `0`

즉 현재 상태는
`large_entry_gap` 표본이
후행 proxy는 양호하지만
실제 주문 전환은 전혀 열리지 않는 구간임을 뜻한다.

같은 값은 `ops-scheduler` 장후 summary parser에서도 그대로 확인된다.

- `watch_only_core_path_large_entry_gap_count=1`
- `watch_only_core_path_large_entry_gap_candidate_count=1`
- `watch_only_core_path_large_entry_gap_would_buy_count=0`
- `watch_only_core_path_large_entry_gap_submitted_count=0`

즉 현재 유일한 제한 완화 ready 표본은
`ranking`도 부족하지만,
직접 1차 병목은 `BUY candidate threshold`까지의
큰 `entry gap`이다.

이번 재집계의 직접 결론은 다음과 같다.

1. `slow_trend` 제한 완화 shadow는
   최소 1건에서 `candidate_ready`를 만들 수 있다.
2. 하지만 그 1건도 바로 `BUY candidate`로 이어지지 않고
   `watch_only_core_path`에 머문다.
3. 그리고 그 `watch_only_core_path` 내부에서도
   현재 직접 1차 병목은 `entry gap`이다.
4. 따라서 다음 shadow 계측의 직접 대상은
   `overall floor` 전체 완화가 아니라
   `candidate_ready_watch_only_core_path`
   코호트의 `entry gap` 분포와 후행 proxy다.
현재는

1. `2026-07-06`의 구 snapshot 7건
2. 나머지 28건의 실제 정책 threshold

를 분리해서 볼 수 있다.

### 10.2 재실측 bucket 분포

| bucket | sample_count | 비고 |
| --- | ---: | --- |
| strict_pass | 0 | 없음 |
| mild_relax | 0 | 없음 |
| moderate_relax | 0 | 없음 |
| deep_negative | 35 | active 전부 |
| inactive | 64 | core risk-off active 아님 |

핵심은 `mild_relax` / `moderate_relax`가 0인 원인이 더 이상 단순 field missing만은 아니라는 점이다.

### 10.3 실제 정책 병목 분해

### 10.4 `WATCH` shape 분해 추가 실측

`2026-07-11` 후속 작업에서
`deterministic_buy_shape_block_reason`,
`buy_candidate_threshold_gap`,
`core_risk_off_ranking_min_gap` 계측을 보강하고,
`2026-07-01 ~ 2026-07-10` 구간을 다시 재집계했다.

추가 산출물:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v5_projection_v2_shape_breakdown.json`

핵심 결과는 다음과 같다.

| 코호트 | sample_count | 주요 shape | T+1 평균 | T+3 평균 | positive T+3 hit rate | 전환 상태 |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| active `trend_moderate_candidate` | 4 | `watch_from_exit_setup` 4건 | 2.1376% | 4.3830% | 100% | `candidate=4`, `selected=0`, `would_buy=0`, `submitted=0` |
| active `slow_floor_relax_ready` | 1 | `watch_from_exit_setup` 1건 | 1.4583% | 3.3333% | 100% | `candidate=1`, `selected=0`, `would_buy=0`, `submitted=0` |

세부 집계:

| 집계 축 | bucket | sample_count | 해석 |
| --- | --- | ---: | --- |
| `active_trend_moderate_deterministic_buy_shape_block_reason_items` | `watch_from_exit_setup` | 4 | `trend_moderate_candidate` 4건 전부가 진입형 WATCH가 아니라 exit형 WATCH 구조 |
| `active_trend_moderate_gate_reason_items` | `signal_both_floor_miss` | 4 | strict `overall/slow` 동시 미통과가 직접 gate |
| `active_trend_moderate_projection_block_reason_items` | `shadow_topk_candidate_miss` | 4 | top-k candidate 이전 단계에서 전부 정지 |
| `active_trend_moderate_eligibility_block_reason_items` | `eligibility_core_risk_off_ranking_blocked` | 4 | eligibility 차단도 동일 코호트에 중첩 |
| `active_slow_floor_relax_ready_deterministic_buy_shape_block_reason_items` | `watch_from_exit_setup` | 1 | ready 1건도 BUY 진입형이 아님 |
| `active_slow_floor_relax_ready_watch_reason_items` | `core_watch_path_only` | 1 | ready 1건은 core WATCH 경로에 머묾 |
| `active_slow_floor_relax_ready_projection_block_reason_items` | `shadow_topk_candidate_miss` | 1 | ready 1건도 selected로 승격되지 못함 |

이 실측이 의미하는 바는 다음과 같다.

1. 현재 `trend_moderate_candidate`의 후행 proxy는 좋다.
   - `inactive` / `deep_negative` 대비 우위다.
2. 그러나 그 4건이 모두 `watch_from_exit_setup`이라는 점은
   이 코호트가 아직 `진입형 BUY 준비군`으로 해석되기보다
   `기존 WATCH 구조의 exit 계열 변형`으로 남아 있음을 뜻한다.
3. 따라서 지금 단계에서
   `slow_trend moderate` 전체를 authoritative 완화로 승격하면,
   기대수익률 우위가 있는 경계 구간을 살리는 것이 아니라
   `exit setup WATCH`를 넓게 BUY 경로로 오해할 위험이 있다.
4. 다음 단계는
   `watch_from_exit_setup`와 `watch_from_entry_setup`,
   그리고 `core_watch_path_only` 코호트의
   후행 proxy와 전환 경로를 별도 비교하는 것이다.

### 10.5 active `WATCH reason × buy-shape` 교차 실측

같은 기간 재집계에
active `core_risk_off` 전용
`watch reason`, `deterministic buy-shape`,
그리고 두 축의 교차 matrix 집계를 추가했다.

추가 산출물:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v5_projection_v3_watch_shape_matrix.json`

핵심 결과:

| 집계 축 | bucket | sample_count | candidate_count | selected_count | T+3 평균 |
| --- | --- | ---: | ---: | ---: | ---: |
| active watch reason | `core_watch_path_only` | 8 | 3 | 0 | 2.8953% |
| active watch reason | `watch_with_eligibility_block` | 13 | 6 | 0 | -3.5729% |
| active buy-shape | `watch_from_exit_setup` | 21 | 9 | 0 | -1.4168% |
| active buy-shape | `watch_from_entry_setup` | 0 | 0 | 0 | 없음 |

교차 matrix:

| matrix bucket | sample_count | T+3 평균 | 해석 |
| --- | ---: | ---: | --- |
| `core_watch_path_only|watch_from_exit_setup` | 8 | 2.8953% | core WATCH 경로에서 형성된 exit형 WATCH는 상대적으로 양호 |
| `watch_with_eligibility_block|watch_from_exit_setup` | 13 | -3.5729% | eligibility 차단이 겹친 exit형 WATCH는 성과가 나쁨 |
| `watch_from_entry_setup` 관련 active matrix | 0 | 없음 | 현재 active 관측 구간에는 entry형 WATCH가 실질적으로 없음 |

이 결과로부터 도출되는 판단은 다음과 같다.

1. 직전 단계에서 본 `trend_moderate_candidate 4건`의 우수 proxy는
   `watch_from_exit_setup` 내부에서도
   특히 `core_watch_path_only` 쪽에 가까운 소수 코호트일 가능성이 높다.
2. 반대로 active 전체 `watch_from_exit_setup` 21건을 한 번에 보면
   `T+3 평균 = -1.4168%`로 성과가 약해진다.
3. 따라서 `watch_from_exit_setup` 전체를 authoritative 완화 후보로 보는 것은
   `최고 기대수익률` 목표와 충돌할 가능성이 높다.
4. 다음 shadow 검증은
   `watch_from_exit_setup` 전체가 아니라
   `core_watch_path_only|watch_from_exit_setup`처럼
   더 좁은 교차 코호트로 한정해야 한다.

### 10.6 `core_watch_path_only|watch_from_exit_setup` 전용 병목 실측

후속 작업에서 위 교차 코호트만 별도로 읽는 전용 집계를 추가했다.

추가 산출물:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v5_projection_v4_core_watch_exit.json`

전용 코호트 요약:

| 코호트 | sample_count | candidate_count | selected_count | T+3 평균 | positive T+3 hit rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| `core_watch_path_only|watch_from_exit_setup` | 8 | 3 | 0 | 2.8953% | 75% |

직접 병목 집계:

| 집계 축 | bucket | sample_count | 해석 |
| --- | --- | ---: | --- |
| gate | `signal_both_floor_miss` | 8 | 전 표본이 strict `overall/slow` 동시 미통과 |
| eligibility | `eligibility_core_risk_off_ranking_blocked` | 8 | 전 표본이 ranking blocked |
| projection block | `shadow_topk_candidate_miss` | 3 | target band 후보지만 selected 전환 실패 |
| projection block | `trend_outside_target` | 4 | trend deep 쪽이라 현재 shadow target 밖 |
| projection block | `momentum_deep_negative_guard` | 1 | momentum guard에 막힘 |

표본 분해:

| trade_date | symbol | trend band | projection block | T+1 | T+3 |
| --- | --- | --- | --- | ---: | ---: |
| 2026-07-02 | 000240 | `trend_moderate_candidate` | `shadow_topk_candidate_miss` | 2.8169% | 5.4326% |
| 2026-07-03 | 002790 | `trend_moderate_candidate` | `shadow_topk_candidate_miss` | 1.4583% | 3.3333% |
| 2026-07-10 | 002790 | `trend_moderate_candidate` | `shadow_topk_candidate_miss` | 미도래 | 미도래 |
| 2026-07-03 | 002030 | `trend_deep_tail` | `trend_outside_target` | 1.2571% | 7.7143% |
| 2026-07-07 | 002030 | `trend_deep_tail` | `trend_outside_target` | 0.3727% | -4.8988% |
| 2026-07-08 | 002030 | `trend_deep_tail` | `trend_outside_target` | 4.9867% | 미도래 |
| 2026-07-09 | 002030 | `trend_deep_tail` | `trend_outside_target` | -9.7524% | 미도래 |
| 2026-07-10 | 002030 | `trend_edge_deep` | `momentum_deep_negative_guard` | 미도래 | 미도래 |

이 실측이 의미하는 바는 다음과 같다.

1. `core_watch_path_only|watch_from_exit_setup` 전체는 성과가 나쁘지 않지만,
   내부적으로는 `trend_moderate_candidate 3건`과
   `trend_edge_deep/deep_tail 5건`이 섞여 있다.
2. 실제 shadow 완화 후보로 남는 것은
   `projection_block_reason=shadow_topk_candidate_miss`인
   `trend_moderate_candidate 3건`뿐이다.
3. 따라서 다음 단계는
   `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
   코호트만 따로 분리해
   `selected=0` 병목과 후행 proxy를 계속 관측하는 것이다.

### 10.7 `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate` 3건 코호트 실측

후속 작업에서 위 3건만 따로 읽는 전용 집계를 추가했다.

추가 산출물:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v5_projection_v5_core_watch_exit_trend_moderate.json`

코호트 요약:

| 코호트 | sample_count | candidate_count | selected_count | T+1 평균 | T+3 평균 | positive T+3 hit rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate` | 3 | 3 | 0 | 2.1376% | 4.3830% | 100% |

직접 병목은 완전히 동일했다.

| 집계 축 | bucket | sample_count |
| --- | --- | ---: |
| projection block | `shadow_topk_candidate_miss` | 3 |
| gate | `signal_both_floor_miss` | 3 |
| eligibility | `eligibility_core_risk_off_ranking_blocked` | 3 |

일자별 전환 상태:

| bucket | sample_count | candidate_count | selected_count | would_buy_count | submitted_count |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2026-07-02|core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate` | 1 | 1 | 0 | 0 | 0 |
| `2026-07-03|core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate` | 1 | 1 | 0 | 0 | 0 |
| `2026-07-10|core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate` | 1 | 1 | 0 | 0 | 0 |

표본 상세:

| trade_date | symbol | buy_candidate_threshold_gap | core_risk_off_ranking_min_gap | T+1 | T+3 | T+5 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2026-07-02 | 000240 | 없음 | 0.2228 | 2.8169% | 5.4326% | 2.4145% |
| 2026-07-03 | 002790 | 0.4021 | 0.0634 | 1.4583% | 3.3333% | 1.2500% |
| 2026-07-10 | 002790 | 0.5339 | 0.1886 | 미도래 | 미도래 | 미도래 |

이 결과로 확정되는 해석은 다음과 같다.

1. 이제 shadow 완화 후보는 사실상 이 3건 코호트로 수렴했다.
2. 성과 proxy는 우수하지만, 3건 모두 `selected=0`인 이유는
   `signal_both_floor_miss`와 `eligibility_core_risk_off_ranking_blocked`가 동시에 남아 있기 때문이다.
3. 따라서 다음 분석 축은
   `ranking 완화`를 바로 적용하는 것이 아니라,
   `signal_both_floor_miss` 내부에서
   `overall`과 `slow` 중 어느 floor가 더 우선 병목인지 먼저 분해하는 것이다.

### 10.8 `signal_both_floor_miss` 내부 분해 결과

후속 장후 재집계에서
`core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
3건 코호트의 `shadow_signal_floor_miss_detail`를 별도 집계했다.

추가 산출물:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v5_projection_v6_floor_detail_split.json`

집계 결과:

| miss detail | sample_count | T+1 평균 | T+3 평균 | 해석 |
| --- | ---: | ---: | ---: | --- |
| `overall_near_slow_deep` | 2 | 1.4583% | 3.3333% | overall은 경계 근처이나 slow가 더 깊게 음수 |
| `overall_deep_slow_near` | 1 | 2.8169% | 5.4326% | slow는 경계 근처이나 overall이 더 깊게 음수 |

표본별 분해:

| trade_date | symbol | miss detail | overall | slow | ranking gap | buy gap |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 2026-07-02 | 000240 | `overall_deep_slow_near` | -0.4150 | -0.1900 | 0.2228 | 없음 |
| 2026-07-03 | 002790 | `overall_near_slow_deep` | -0.1274 | -0.4300 | 0.0634 | 0.4021 |
| 2026-07-10 | 002790 | `overall_near_slow_deep` | -0.2421 | -0.4300 | 0.1886 | 0.5339 |

이로부터 도출되는 판단:

1. 3건 코호트의 다수는 `slow floor`가 주 병목이다.
   - 3건 중 2건이 `overall_near_slow_deep`
2. `ranking_blocked`는 공통으로 붙어 있지만,
   현재 우선 완화 후보는 `ranking`보다 `slow floor` shadow 쪽이 맞다.
3. 특히 `002790` 계열 2건은
   `overall`은 moderate window에 비교적 가까운데
   `slow=-0.43`으로 깊게 눌려 있어
   `slow_trend` 중심 shadow 완화 가설과 정합적이다.
4. 따라서 다음 단계는
   `overall floor` 전체 완화가 아니라
   이 제한 코호트에 대해서만 `slow floor` shadow 완화안을 설계하는 것이다.

### 10.9 `slow_floor_shadow_relax_path` 기준 최종 분해

같은 3건 코호트에 대해
`slow_floor_shadow_relax_path`를 직접 집계한 결과는 다음과 같다.

| path | sample_count | T+1 평균 | T+3 평균 | 해석 |
| --- | ---: | ---: | ---: | --- |
| `slow_floor_relax_ready` | 1 | 1.4583% | 3.3333% | `slow floor`만 완화되면 다음 단계 관측 후보 |
| `slow_floor_relax_activity_blocked` | 1 | 미도래 | 미도래 | `slow floor` 외에 activity 차단이 남음 |
| `overall_floor_first` | 1 | 2.8169% | 5.4326% | `slow floor`보다 `overall floor`가 선행 병목 |

표본 매핑:

| trade_date | symbol | miss detail | slow_floor_shadow_relax_path | activity_pass | ranking_score |
| --- | --- | --- | --- | --- | ---: |
| 2026-07-02 | 000240 | `overall_deep_slow_near` | `overall_floor_first` | false | 0.2572 |
| 2026-07-03 | 002790 | `overall_near_slow_deep` | `slow_floor_relax_ready` | true | 0.4166 |
| 2026-07-10 | 002790 | `overall_near_slow_deep` | `slow_floor_relax_activity_blocked` | false | 0.2914 |

이 결과로부터 바로 이어지는 결론:

1. `slow floor` shadow 제한 완화의 직접 타깃은
   3건 전체가 아니라 `002790` 2건이다.
2. 그중
   `2026-07-03` 표본은 이미 `ready`,
   `2026-07-10` 표본은 `activity_blocked`로 남아 있어
   다음 shadow 설계는
   `ready`와 `activity_blocked`를 분리해 다뤄야 한다.
3. `000240`은 `overall_floor_first`이므로
   이번 단계의 `slow floor` 제한 완화 대상에서 제외하는 것이 맞다.

v5 score가 채워진 active 28건의 분포:

| 지표 | 최소 | 평균 | 최대 |
| --- | ---: | ---: | ---: |
| `shadow_overall_score_v5` | -0.7505 | -0.5821 | -0.2421 |
| `shadow_slow_score_v5` | -0.8000 | -0.7232 | -0.4300 |

현재 v5 기준:

- `mild_relax`: `overall >= -0.20` 그리고 `slow >= -0.15`
- `moderate_relax`: `overall >= -0.25` 그리고 `slow >= -0.25` 외 추가 gate

실측 결과:

- `overall`가 `-0.25 ~ -0.20` 근처인 near-miss 표본은 2건 존재
- 하지만 `slow`가 `-0.25 ~ -0.15` 구간인 표본은 0건
- 즉, 현재 실질 병목은 `overall`보다 `slow_score_v5` 하방 편향이다.

### 10.4 component 기준 병목

재집계 산출물
`logs/trigger_proxy_attribution_2026-07-06_2026-07-10_v5_projection_v4.json`
기준으로 active `core_risk_off` 35건을
`slow_trend_relax_candidate_band`로 다시 나누면 다음과 같다.

| band | active 표본 | T+1 ready | T+3 ready | T+1 평균 | T+3 평균 | T+3 양수 비율 | T+3 MFE | T+3 MAE | projection candidate | selected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `trend_moderate_candidate` | 2 | 0 | 0 | 없음 | 없음 | 없음 | 없음 | 없음 | 2 | 0 |
| `trend_edge_deep` | 4 | 3 | 2 | -0.8576% | -0.2578% | 50.00% | 0.9121% | -4.2077% | 3 | 0 |
| `trend_deep_tail` | 29 | 23 | 12 | -1.9127% | -6.2491% | 8.33% | 1.3035% | -10.1577% | 0 | 0 |

추가 해석:

1. `trend_moderate_candidate`의 active 표본 2건은 모두 `2026-07-10` 의사결정이다.
   - 종목: `000080`, `002790`
   - `price_vs_sma_60_pct`: `-5.1646`, `-5.5371`
   - `slow_momentum`: 둘 다 `-0.55`
   - `slow_trend`: 둘 다 `-0.25`
   - 공통 차단 사유:
     - `eligibility_core_risk_off_ranking_blocked`
     - `shadow_topk_candidate_miss`
   - 즉, 아직 `T+1 / T+3` bar가 열리지 않아
     후행 proxy 비교의 핵심 자료가 비어 있다.

2. 현 시점에서 실제 수익률 비교가 가능한 것은
   `trend_edge_deep` 대 `trend_deep_tail`이다.
   - `trend_edge_deep`는
     `T+3 평균 -0.2578%`, `T+3 양수 비율 50%`, `T+3 MAE -4.2077%`
   - `trend_deep_tail`는
     `T+3 평균 -6.2491%`, `T+3 양수 비율 8.33%`, `T+3 MAE -10.1577%`
   - 따라서 `trend_edge_deep`는
     최소한 `trend_deep_tail`보다 훨씬 덜 나쁜 구간으로 보인다.

3. 하지만 이번 Task의 목표는
   `trend_moderate_candidate` 승격 가능성 판단이지,
   `trend_edge_deep` 완화가 아니다.
   따라서 현재 실측만으로는
   `trend_moderate_candidate`를 authoritative 후보로 올릴 근거가 아직 없다.

4. `WATCH → BUY/submit` 측면에서도 아직 진전이 없다.
   - `trend_moderate_candidate`의 `projection candidate`는 2건이지만
     `selected=0`, `would_buy=0`, `submitted=0`이다.
   - 즉 현재 상태는
     `slow_trend` 경계 완화 shadow가 있더라도
     실제 top-k selection 및 BUY 경로로는 이어지지 않는 단계다.

### 10.5 현재 판단

현재까지의 실측으로는 다음 결론이 타당하다.

1. `trend_moderate_candidate`는 아직 `T+1 / T+3` 후행 proxy가 비어 있어
   `inactive` 또는 `deep_negative` 대비 우위를 판단할 수 없다.
2. 따라서 지금 threshold를 완화하면
   `최고 기대수익률` 목표보다
   근거 없는 후보 확대가 먼저 발생할 가능성이 높다.
3. 다음 판단 시점은
   `2026-07-10` 표본 2건에 대해 최소 `T+1`,
   가능하면 `T+3`까지 확보된 뒤가 맞다.
4. 그 전까지는
   `shadow-only 유지`, `authoritative 금지`가 맞다.

### 10.6 `2026-07-06` 이후 재집계 기준 `T+3` actual band 분포

`2026-07-11` 시점에서
`2026-07-06 ~ 2026-07-10` 구간을 다시 재집계한
`logs/trigger_proxy_attribution_2026-07-06_2026-07-10_v5_projection_v6.json`
기준으로, active `core_risk_off` 35건 중
`T+3` 후행 proxy가 실제로 채워진 표본은 14건이다.

날짜별 / `slow_trend_relax_candidate_band`별 분포는 다음과 같다.

| trade_date | band | sample_count | symbols | T+3 평균 | T+3 양수 비율 | T+3 MFE | T+3 MAE |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| `2026-07-06` | `trend_edge_deep` | 1 | `000080` | `2.3256%` | `100.00%` | `2.3256%` | `-3.1229%` |
| `2026-07-06` | `trend_deep_tail` | 6 | `000100,000120,000210,000670,000720,000880` | `-9.2057%` | `0.00%` | `-0.2682%` | `-11.1302%` |
| `2026-07-07` | `trend_edge_deep` | 1 | `001680` | `-2.8412%` | `0.00%` | `-0.5014%` | `-5.2925%` |
| `2026-07-07` | `trend_deep_tail` | 6 | `000210,000670,000720,001040,001430,002030` | `-3.2925%` | `16.67%` | `2.8752%` | `-9.1852%` |

아직 `T+3`가 비어 있는 active 표본은 다음과 같다.

| trade_date | band | 미관측 표본 수 |
| --- | --- | ---: |
| `2026-07-08` | `trend_deep_tail` | 6 |
| `2026-07-09` | `trend_deep_tail` | 5 |
| `2026-07-09` | `trend_edge_deep` | 1 |
| `2026-07-10` | `trend_deep_tail` | 6 |
| `2026-07-10` | `trend_edge_deep` | 1 |
| `2026-07-10` | `trend_moderate_candidate` | 2 |

해석:

1. `T+3`가 실제로 채워진 구간은 현재 `trend_edge_deep`와 `trend_deep_tail`뿐이다.
2. `trend_moderate_candidate`는 아직 전부 `2026-07-10` 표본이라
   `T+3`가 하나도 없다.
3. 따라서 이번 재집계로 확인할 수 있었던 것은
   `trend_edge_deep`가 `trend_deep_tail`보다 훨씬 덜 나쁜 구간이라는 점이지,
   `trend_moderate_candidate`의 승격 타당성은 아니다.

후속 장후 판정을 위해 아래 diagnostics 필드를 추가했다.

- `active_slow_trend_trade_date_band_items`
- `active_slow_trend_trade_date_projection_items`

최신 재집계 기준
`2026-07-10|trend_moderate_candidate` bucket은 다음처럼 직접 읽힌다.

| bucket | sample_count | T+1 평균 | T+3 평균 | candidate_count | selected_count | would_buy_count | submitted_count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `2026-07-10|trend_moderate_candidate` | 2 | 없음 | 없음 | 2 | 0 | 0 | 0 |

즉 `2026-07-13` 장후에는 같은 bucket 한 줄에서
`T+1`과 projection 전환 유무를 바로 판단할 수 있다.

active + v5 score 존재 28건의 `shadow_component_scores_v5` 평균:

| component | 평균 |
| --- | ---: |
| `slow_trend` | -0.7286 |
| `slow_momentum` | -0.7196 |
| `fast_trend` | -0.4732 |
| `rsi_signal` | 0.0821 |
| `volatility_penalty` | -0.7643 |
| `volume_confirmation` | -0.0625 |

해석:

1. `slow_trend`와 `slow_momentum`이 모두 강한 음수다.
2. `volatility_penalty`도 평균 `-0.7643`으로 하방 기여가 매우 크다.
3. 반면 `rsi_signal`은 거의 중립~소폭 양수이고, 일부 표본은 `fast_trend`가 양수다.
4. 따라서 현재 v5 완화가 열리지 않는 주된 원인은
   - `below_sma60` 계열로 인한 `slow_trend` 음수
   - `momentum_3m_negative` 계열로 인한 `slow_momentum` 음수
   - `atr_expanded / volatility_*` 계열의 변동성 패널티
   의 조합이다.

### 10.7 `2026-07-01 ~ 2026-07-10` 확장 재집계 비교

`2026-07-10` 최신 코호트만으로는
`trend_moderate_candidate`의 `T+1 / T+3`가 비어 있었기 때문에,
동일 코드 기준으로 `2026-07-01 ~ 2026-07-10` 구간을 다시 재집계해
더 이른 active 표본까지 포함해 비교했다.

active `slow_trend_relax_candidate_band` 기준 결과는 다음과 같다.

| band | sample_count | T+1 평균 | T+3 평균 | T+5 평균 | T+3 양수 비율 | candidate_count | selected_count | would_buy_count | submitted_count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `trend_moderate_candidate` | 4 | `2.1376%` | `4.3830%` | `1.8322%` | `100.00%` | 4 | 0 | 0 | 0 |
| `trend_edge_deep` | 6 | `0.2940%` | `0.1436%` | `-2.7460%` | `75.00%` | 5 | 0 | 0 | 0 |
| `trend_deep_tail` | 39 | `-1.2212%` | `-3.9082%` | `-3.1271%` | `18.18%` | 0 | 0 | 0 | 0 |

비교 기준군:

| 비교군 | sample_count | T+1 평균 | T+3 평균 | T+5 평균 | T+3 양수 비율 | T+3 MFE | T+3 MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `inactive` | 120 | `-0.5129%` | `-3.0308%` | `-4.8530%` | `41.33%` | `3.8540%` | `-8.0463%` |
| `deep_negative` | 35 | `-1.7910%` | `-5.3932%` | 값 부족 | `14.29%` | `1.2476%` | `-9.3077%` |

해석:

1. active `trend_moderate_candidate` 4건은
   후행 proxy 기준으로 `inactive`와 `deep_negative`를 모두 상회한다.
2. `T+3 평균 +4.3830%`, `T+3 양수 비율 100%`는
   `slow_trend` 경계 완화 후보가
   단순 잡음이 아니라는 근거를 강화한다.
3. 그러나 이 4건 모두
   `candidate_count=4`, `selected_count=0`,
   `would_buy_count=0`, `submitted_count=0`으로 남는다.
4. 따라서 현 병목은
   `후행 수익률 proxy 부족`이 아니라
   `BUY candidate -> selected` 전환 이전 단계다.

### 10.8 `trend_moderate_candidate` 4건의 `selected=0` 원인 분해

확장 재집계로 확인된 active `trend_moderate_candidate` 4건은 다음과 같다.

| trade_date | symbol | shadow_overall_score | shadow_slow_score | ranking_score | activity_pass | strategy_pass | gate_reason | projection_block_reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `2026-07-02` | `000240` | `-0.4150` | `-0.1900` | `0.2572` | `False` | `True` | `signal_both_floor_miss` | `shadow_topk_candidate_miss` |
| `2026-07-03` | `002790` | `-0.1274` | `-0.4300` | `0.4166` | `True` | `True` | `signal_both_floor_miss` | `shadow_topk_candidate_miss` |
| `2026-07-10` | `000080` | `-0.2478` | `-0.4300` | `0.2860` | `False` | `True` | `signal_both_floor_miss` | `shadow_topk_candidate_miss` |
| `2026-07-10` | `002790` | `-0.2421` | `-0.4300` | `0.2914` | `False` | `True` | `signal_both_floor_miss` | `shadow_topk_candidate_miss` |

도출 과정:

1. 4건 모두 `slow_trend_relax_candidate_band=trend_moderate_candidate`다.
2. 4건 모두 `shadow_relax_projection_candidate=true`지만
   `shadow_topk_selected=false`다.
3. 그러나 직접 원인은 `top-k 경쟁 탈락`이 아니다.
   - 4건 모두 `shadow_topk_candidate=false`
   - 4건 모두 `shadow_topk_candidate_gate_reason=signal_both_floor_miss`
4. 즉 `selected=0`의 직접 원인은

### 10.9 `candidate_ready_watch_only_core_path` `entry_gap_band` 재확인

`2026-07-01 ~ 2026-07-10` 구간을
최신 코드 기준으로 다시 재집계해
`logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v12_entry_gap_recheck.json`
산출물을 추가 확인했다.

직접 확인한 집계:

| 집계 축 | bucket | sample_count | candidate | selected | would_buy | submitted | T+1 | T+3 | T+3 MFE | T+3 MAE |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_band_items` | `large_entry_gap` | 1 | - | - | - | - | `+1.4583%` | `+3.3333%` | `+4.7917%` | `-0.4167%` |
| `active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items` | `large_entry_gap` | 1 | 1 | 0 | 0 | 0 | - | - | - | - |
| `active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items` | `moderate_entry_gap` | 0 | 0 | 0 | 0 | 0 | - | - | - | - |
| `active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items` | `small_entry_gap` | 0 | 0 | 0 | 0 | 0 | - | - | - | - |
| `active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items` | `entry_ready` | 0 | 0 | 0 | 0 | 0 | - | - | - | - |

trade-date 기준으로도 결과는 동일했다.

| trade_date bucket | sample_count | candidate | selected | would_buy | submitted |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2026-07-03|core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate|candidate_ready_watch_only_core_path|large_entry_gap` | 1 | 1 | 0 | 0 | 0 |

해석:

1. 최신 재집계에서도
   `candidate_ready_watch_only_core_path`의 `entry_gap_band`는
   `large_entry_gap` 1건만 존재한다.
2. 즉 현재 `moderate_entry_gap`, `small_entry_gap`, `entry_ready`가 비어 있는 것은
   단순히 후행 proxy가 아직 덜 채워졌기 때문이 아니라,
   **현행 shadow 조건과 과거 원자료 기준으로는
   해당 band 자체가 아직 발생하지 않았기 때문**이다.
3. 따라서 다음 단계는
   신규 거래일 누적만 기다리는 것이 아니라,
   이 상태가 지속되면
   `entry gap` 분류 경계 또는 upstream `BUY threshold gap` 구조를
   다시 분해해야 한다.
4. 현재 근거만으로는
   `candidate_ready_watch_only_core_path`가
   `selected` 또는 `would_buy`로 이어지는 band가 확인되지 않았으므로
   `shadow-only 유지`, `authoritative 금지`가 맞다.

### 10.10 상위 target 코호트 `buy_candidate_threshold_gap_band` 재분해

위 `watch_only_core_path` 내부 band만으로는
`moderate/small/entry_ready`가 왜 비어 있는지 설명이 부족하므로,
같은 `2026-07-01 ~ 2026-07-10` 구간을
`logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v13_buy_gap_diagnostics.json`
기준으로
상위 `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
코호트 전체로 다시 분해했다.

직접 확인한 집계:

| 집계 축 | bucket | sample_count | candidate | selected | would_buy | submitted | T+1 | T+3 | T+3 MFE | T+3 MAE |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `active_core_watch_exit_trend_moderate_buy_gap_band_items` | `large_entry_gap` | 2 | - | - | - | - | `+1.4583%` | `+3.3333%` | `+4.7917%` | `-0.4167%` |
| `active_core_watch_exit_trend_moderate_buy_gap_band_items` | `buy_gap_missing` | 1 | - | - | - | - | `+2.8169%` | `+5.4326%` | `+6.4386%` | `-1.2072%` |
| `active_core_watch_exit_trend_moderate_buy_gap_projection_items` | `large_entry_gap` | 2 | 2 | 0 | 0 | 0 | - | - | - | - |
| `active_core_watch_exit_trend_moderate_buy_gap_projection_items` | `moderate_entry_gap` | 0 | 0 | 0 | 0 | 0 | - | - | - | - |
| `active_core_watch_exit_trend_moderate_buy_gap_projection_items` | `small_entry_gap` | 0 | 0 | 0 | 0 | 0 | - | - | - | - |
| `active_core_watch_exit_trend_moderate_buy_gap_projection_items` | `entry_ready` | 0 | 0 | 0 | 0 | 0 | - | - | - | - |

단계 교차 집계:

| transition stage x buy gap | sample_count | T+1 | T+3 | T+3 MFE | T+3 MAE |
| --- | ---: | ---: | ---: | ---: | ---: |
| `candidate_ready_watch_only_core_path|large_entry_gap` | 1 | `+1.4583%` | `+3.3333%` | `+4.7917%` | `-0.4167%` |
| `activity_blocked|large_entry_gap` | 1 | - | - | - | - |
| `overall_floor_first|buy_gap_missing` | 1 | `+2.8169%` | `+5.4326%` | `+6.4386%` | `-1.2072%` |

표본 row 요약:

| trade_date | symbol | transition stage | buy gap | gap band | ranking gap | activity pass | miss detail |
| --- | --- | --- | ---: | --- | ---: | --- | --- |
| `2026-07-02` | `000240` | `overall_floor_first` | `null` | `buy_gap_missing` | `0.2228` | `false` | `overall_deep_slow_near` |
| `2026-07-03` | `002790` | `candidate_ready_watch_only_core_path` | `0.4021` | `large_entry_gap` | `0.0634` | `true` | `overall_near_slow_deep` |
| `2026-07-10` | `002790` | `activity_blocked` | `0.5339` | `large_entry_gap` | `0.1886` | `false` | `overall_near_slow_deep` |

해석:

1. `candidate_ready_watch_only_core_path` 내부만 좁게 봐서 `large`만 남는 것이 아니다.
   상위 target 코호트 전체에서도
   `non-null buy gap`은 전부 `large_entry_gap`이다.
2. 따라서 현재 `moderate/small/entry_ready` 부재는
   단순 후행 proxy 미적재보다
   `shadow_entry_score` 자체가 `BUY threshold(0.65)`에서 너무 멀리 떨어져 있는
   구조적 하방 편향일 가능성이 더 높다.
3. 특히 `2026-07-03 / 002790`는
   `candidate_ready`까지는 도달했지만
   `buy_candidate_threshold_gap=0.4021`로 너무 커서
   여전히 `WATCH -> BUY shape` 전환이 열리지 않는다.
4. `2026-07-10 / 002790`는
   같은 symbol이라도 더 낮은 `entry_score`로
   `activity_blocked + large_entry_gap` 조합으로 후퇴했다.
5. 따라서 다음 단계는
   신규 거래일만 더 기다리는 것이 아니라,
   `watch_from_exit_setup` target 코호트의
   `shadow_entry_score / buy gap / ranking gap` 분포를
   authoritative BUY 경로와 직접 비교해
   실제 1차 병목이 `entry_score`인지 재확인하는 것이다.

### 10.11 strict `authoritative core BUY path` 비교 결과

후속 계측에서 비교군 정의를
`buy_candidate=true` 또는
`candidate_intent=buy` 또는
`primary_candidate=buy_candidate`
로 제한한 strict `authoritative core BUY path`로 고정하고,
두 구간을 다시 재집계했다.

- target 코호트 확인:
  `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v15_authoritative_compare_strict.json`
- broader baseline 확인:
  `logs/trigger_proxy_attribution_2026-06-01_2026-07-10_v15_authoritative_compare_strict.json`

직접 확인한 결과:

| 구간 | 집계 | 결과 |
| --- | --- | --- |
| `2026-07-01 ~ 2026-07-10` | target `entry_score_band` | `below_observe_floor=2`, `observe_band=1` |
| `2026-07-01 ~ 2026-07-10` | target `buy_gap_band` | `large_entry_gap=2`, `buy_gap_missing=1` |
| `2026-07-01 ~ 2026-07-10` | target `buy_ranking_gap_band` | `large_ranking_gap=2`, `moderate_ranking_gap=1` |
| `2026-06-01 ~ 2026-07-10` | strict `authoritative_core_buy_path_*` | 전부 `0건` |
| `2026-06-01 ~ 2026-07-10` | strict `authoritative_core_submitted_path_*` | 전부 `0건` |

해석:

1. 지금은 단순히 target 코호트가 BUY 전환을 못 하는 정도가 아니다.
   비교군이 되어야 할 strict `authoritative core BUY path` 자체가
   같은 운영 기간 전체에서 `0건`이다.
2. 따라서 `watch_from_exit_setup` target 코호트를
   실제 BUY baseline과 직접 비교해
   `entry_score` 병목을 판정하려던 원래 계획은,
   **baseline 부재** 때문에 그대로는 완료될 수 없다.
3. 다만 이 결과는
   `entry_score` 하방 편향 가설을 약화시키지 않는다.
   오히려 시스템 전체에서
   strict core BUY path가 전혀 열리지 않는 구조적 경직 상태를 뜻한다.
4. 따라서 다음 비교축은
   strict BUY baseline이 아니라
   `watch_from_entry_setup`,
   `entry_score >= 0.52`,
   `0.55 <= entry_score < 0.65`
   같은 **pre-BUY staging cohort**로 재정의하는 것이 타당하다.
   `shadow_topk_candidate` 진입 이전 단계의
   strict `overall/slow` 동시 미통과다.
5. 동시에 4건 모두
   `eligibility_block_reason_primary=eligibility_core_risk_off_ranking_blocked`다.
   따라서 authoritative buy path 기준에서는
   `ranking`도 여전히 낮다.

결론:

- shadow 완화 후보의 후행 proxy는 유망하다.
- 하지만 현재 코드는 그 후보를
  `shadow_topk_candidate`로 올리지 못하고 있다.
- 다음 단계는 `ranking` 완화보다 먼저,
  `trend_moderate_candidate` 전용 `overall/slow strict floor` shadow 완화를
  더 세분화해 관측하는 것이다.

### 10.12 `pre-BUY staging cohort` 재정의 비교 결과

strict `authoritative core BUY path`가 같은 운영 구간 전체에서 `0건`이었기 때문에,
비교군을 아래 3개 `pre-BUY staging cohort`로 재정의해
`2026-07-01 ~ 2026-07-10` 구간을 다시 재집계했다.

- `watch_from_entry_setup`
- `entry_score >= 0.52`
- `0.55 <= entry_score < 0.65`

사용 로그:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v16_pre_buy_staging_compare.json`

요약 표:

| 코호트 | 표본 수 | entry band | buy gap band | ranking gap band | candidate | selected | would_buy | submitted | 해석 |
| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `watch_from_entry_setup` | 0 | 없음 | 없음 | 없음 | 0 | 0 | 0 | 0 | active core staging 자체가 없음 |
| `entry_score >= 0.52` | 2 | `watch_band=2` | `moderate_entry_gap=2` | `small_ranking_gap=2` | 0 | 0 | 0 | 0 | 점수는 관찰 구간에 있으나 전부 비활성 경로 |
| `0.55 <= entry_score < 0.65` | 1 | `near_buy_floor=1` | `small_entry_gap=1` | `small_ranking_gap=1` | 0 | 0 | 0 | 0 | BUY 직전 staging 표본이 1건 있으나 역시 비활성 경로 |

샘플 해석:

1. `entry_score >= 0.52` 2건은
   `2026-07-08 / 001450`,
   `2026-07-09 / 000810` 이다.
   둘 다
   - `watch_primary_candidate_reason=watch_setup_but_ineligible`
   - `deterministic_buy_shape_block_reason=watch_from_entry_setup`
   - `eligibility_block_reason_primary=eligibility_low_relative_activity`
   - `shadow_activity_pass=false`
   상태였다.

2. `0.55 <= entry_score < 0.65` 1건은
   `2026-07-09 / 001450` 이다.
   - `effective_entry_score=0.55798`
   - `effective_buy_candidate_threshold_gap=0.09202`
   - `effective_buy_ranking_gap=0.0131`
   로 점수상으로는 `BUY` 근처에 더 가깝다.
   하지만
   - `watch_setup_but_ineligible`
   - `eligibility_low_relative_activity`
   - `shadow_activity_pass=false`
   때문에 역시 `candidate=0`, `selected=0`, `would_buy=0`, `submitted=0`으로 끝났다.

3. 즉 현재 병목은
   `strict BUY baseline 부재`만이 아니라,
   `pre-BUY staging` 표본이 생기더라도
   실제로는 `activity/eligibility`에서 먼저 멈추는 구조다.

정리:

1. 과거 10일 재집계에서도
   `moderate/small entry gap` 표본이 전혀 없는 상태는 아니다.
   다만 그 표본이 전부 `inactive / watch_setup_but_ineligible` 쪽에 있다.
2. 따라서 다음 우선 작업은
   `slow floor` 완화 수치 조정보다 먼저,
   `pre-BUY staging` 표본의
   `eligibility_low_relative_activity / shadow_activity_pass=false`
   병목을 별도 shadow 계측으로 분리하는 것이다.
3. 현 시점에서는
   `entry_score` 완화만으로 `BUY candidate -> submit`이 열릴 근거가 없다.

추가 확인:

- `2026-06-01 ~ 2026-07-10` 전체 재집계에서도 패턴은 유지됐다.
  - `watch_from_entry_setup = 1건`
    - `2026-06-18 / 005380`
    - `effective_entry_score=0.4624`
    - `candidate/select/would_buy/submitted = 0`
  - `entry_score >= 0.52 = 3건`
    - `2026-06-30 / 000660`
    - `2026-07-08 / 001450`
    - `2026-07-09 / 000810`
    - 공통적으로 `eligibility_low_relative_activity`,
      `shadow_activity_pass=false`,
      `watch_setup_but_ineligible`
  - `0.55 <= entry_score < 0.65 = 1건`
    - `2026-07-09 / 001450`
    - `small_entry_gap + small_ranking_gap`이지만
      여전히 `eligibility_low_relative_activity`,
      `shadow_activity_pass=false`
  - strict `authoritative core BUY path = 0건`

즉,
`pre-BUY staging` 표본을 더 길게 누적해도
지금까지는 `activity / eligibility`가 먼저 막는 구조가 반복된다.

### 10.12.1 `pre-BUY staging activity_gate` 세분화 결과

`activity / eligibility` 병목을 더 직접 보기 위해
`pre_buy_staging_activity_gate` 아래에
`pre_buy_staging_activity_detail` 계측을 추가하고
`2026-07-01 ~ 2026-07-10` 구간을 다시 재집계했다.

사용 로그:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v18_pre_buy_activity_detail.json`

핵심 결과:

1. `watch_from_entry_setup` active 표본은 여전히 `0건`이다.
2. `entry_score >= 0.52` 표본 2건은 모두
   `watch_setup_but_ineligible|eligibility_low_relative_activity` 경로다.
3. 다만 `low_relative_activity` 내부는 같은 깊이가 아니었다.
   - `2026-07-08 / 001450`
     - `volume_surge_ratio=0.9839`
     - `turnover_surge_ratio=0.9743`
     - `activity_detail=low_relative_activity_max_0_95_to_1_10`
   - `2026-07-09 / 000810`
     - `volume_surge_ratio=0.5527`
     - `turnover_surge_ratio=0.5654`
     - `activity_detail=low_relative_activity_max_lt_0_80`
4. `0.55 <= entry_score < 0.65` 표본 1건(`2026-07-09 / 001450`)도
   - `volume_surge_ratio=0.9879`
   - `turnover_surge_ratio=0.9919`
   - `activity_detail=low_relative_activity_max_0_95_to_1_10`
   로 확인됐다.

추가로 `2026-06-01 ~ 2026-07-10` 장기 재집계에서도
패턴은 유지됐다.

- 사용 로그:
  - `logs/trigger_proxy_attribution_2026-06-01_2026-07-10_v18_pre_buy_activity_detail.json`
- `watch_from_entry_setup` 1건(`2026-06-18 / 005380`)은
  `shadow_activity_blocked_without_explicit_activity_reason`으로 남았다.
- `entry_score >= 0.52` 3건은
  - `low_relative_activity_max_0_80_to_0_95=1`
  - `low_relative_activity_max_0_95_to_1_10=1`
  - `low_relative_activity_max_lt_0_80=1`
  로 분해됐다.
- `0.55 <= entry_score < 0.65` 1건은
  `low_relative_activity_max_0_95_to_1_10`이다.

정리 표:

| 코호트 | 표본 수 | activity gate | activity detail | 비고 |
| --- | ---: | --- | --- | --- |
| `watch_from_entry_setup` | 0 | 없음 | 없음 | active core staging 부재 유지 |
| `entry_score >= 0.52` | 2 | `eligibility_low_relative_activity=2` | `max_0_95_to_1_10=1`, `max_lt_0_80=1` | 경계 근처와 깊은 부족 표본이 혼재 |
| `0.55 <= entry_score < 0.65` | 1 | `eligibility_low_relative_activity=1` | `max_0_95_to_1_10=1` | BUY 직전 표본도 여전히 activity hard block |

현재 해석:

1. `pre-BUY staging` 표본의 1차 병목이 `low_relative_activity`라는 점은 유지된다.
2. 그러나 그 내부에는
   `1.10` 바로 아래의 경계 표본과
   `0.80` 미만의 깊은 부족 표본이 섞여 있다.
3. 따라서 다음 shadow 검증은
   `low_relative_activity` 전체 완화가 아니라,
   `max_0_95_to_1_10` 같은 경계 표본만 별도 코호트로 분리해
   후행 proxy와 `candidate -> selected -> would_buy -> submitted`
   전환 가능성을 보는 방향이 맞다.
4. 반대로 `max_lt_0_80`은 같은 `pre-BUY staging`이라도
   동일한 완화 후보로 묶으면 안 된다.

### 10.12.2 `low_relative_activity_max_0_95_to_1_10` 경계 코호트 전용 리포트

다음 후속 작업을 위해
`pre_buy_staging_low_relative_activity_boundary_report`
전용 집계를 추가하고
`2026-07-01 ~ 2026-07-10` 구간을 다시 재집계했다.

사용 로그:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v19_pre_buy_boundary_focus.json`

집계 결과:

| 집계 축 | bucket | sample_count | 해석 |
| --- | --- | ---: | --- |
| cohort | `entry_score_0_55_to_0_65` | 1 | `near_buy_floor` 경계 코호트 |
| cohort | `entry_score_ge_0_52` | 1 | `watch_band` 경계 코호트 |
| entry band | `near_buy_floor` | 1 | `2026-07-09 / 001450` |
| entry band | `watch_band` | 1 | `2026-07-08 / 001450` |
| buy gap band | `small_entry_gap` | 1 | BUY 직전이지만 아직 미전환 |
| buy gap band | `moderate_entry_gap` | 1 | BUY threshold까지 추가 gap 존재 |
| buy ranking gap band | `small_ranking_gap` | 2 | ranking은 두 표본 모두 거의 경계 근처 |

전환 집계:

| cohort | sample_count | candidate_count | selected_count | would_buy_count | submitted_count |
| --- | ---: | ---: | ---: | ---: | ---: |
| `entry_score_0_55_to_0_65` | 1 | 0 | 0 | 0 | 0 |
| `entry_score_ge_0_52` | 1 | 0 | 0 | 0 | 0 |

일자별:

| trade_date | cohort | entry_score | buy_gap_band | ranking_gap_band | candidate | selected | would_buy | submitted |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| `2026-07-08` | `entry_score_ge_0_52` | `0.5368` | `moderate_entry_gap` | `small_ranking_gap` | 0 | 0 | 0 | 0 |
| `2026-07-09` | `entry_score_0_55_to_0_65` | `0.5580` | `small_entry_gap` | `small_ranking_gap` | 0 | 0 | 0 | 0 |

해석:

1. `1.10` 바로 아래의 경계 activity 표본은
   분명히 `watch_band`와 `near_buy_floor`까지는 올라온다.
2. 특히 `2026-07-09 / 001450`는
   `small_entry_gap + small_ranking_gap`까지 도달했지만
   여전히 `candidate=0`이다.
3. 즉 이 경계 코호트는
   `entry_score / ranking_score`가 완전히 멀어서 막힌 것이 아니라,
   `activity hard block` 자체가 candidate 전환을 끊고 있는지
   다음 직접 검증 대상으로 삼을 가치가 있다.
4. 다만 현재 표본 수는 `2건`뿐이므로
   이 결과만으로 authoritative 완화를 결정하면 안 된다.

장기 구간 확인:

- `logs/trigger_proxy_attribution_2026-06-01_2026-07-10_v19_pre_buy_boundary_focus.json`
  의
  `core_risk_off_floor_v5_diagnostics.pre_buy_staging_low_relative_activity_boundary_report`
  를 같은 방식으로 확인했다.
- 결과는 단기 구간과 동일했고,
  추가 boundary 표본은 나타나지 않았다.

추가 해석:

1. `2026-06-01 ~ 2026-07-10`까지 범위를 넓혀도
   `low_relative_activity_max_0_95_to_1_10` 경계 코호트는
   `2026-07-08 / 001450`,
   `2026-07-09 / 001450`
   두 건뿐이다.
2. 따라서 현재 병목은
   "최근 기간만 봐서 표본을 놓쳤다"가 아니라,
   현행 정책과 과거 원자료 기준에서
   이 경계 코호트 자체가 드물다는 데 있다.
3. 다음 후속 작업은
   단순 기간 확대가 아니라,
   이 두 건이 왜 `candidate=0`에 머무는지
   `activity hard block` 자체를 더 직접 분해하는 것이다.

### 10.12.4 `activity hard block` 1차 병목 분해

후속 작업으로
`pre_buy_boundary_first_order_bottleneck`
진단 필드를 추가하고
`2026-07-01 ~ 2026-07-10` 구간을 다시 재집계했다.

사용 로그:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v21_pre_buy_boundary_bottleneck.json`

집계 결과:

| bottleneck bucket | sample_count | candidate_count | selected_count | would_buy_count | submitted_count |
| --- | ---: | ---: | ---: | ---: | ---: |
| `activity_first_small_entry_gap` | 1 | 0 | 0 | 0 | 0 |
| `activity_first_moderate_entry_gap` | 1 | 0 | 0 | 0 | 0 |

일자별:

| trade_date | symbol | cohort | bottleneck | entry_gap_band | ranking_gap_band | candidate | selected | would_buy | submitted |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| `2026-07-08` | `001450` | `entry_score_ge_0_52` | `activity_first_moderate_entry_gap` | `moderate_entry_gap` | `small_ranking_gap` | 0 | 0 | 0 | 0 |
| `2026-07-09` | `001450` | `entry_score_0_55_to_0_65` | `activity_first_small_entry_gap` | `small_entry_gap` | `small_ranking_gap` | 0 | 0 | 0 | 0 |

해석:

1. 두 표본 모두 `ranking_ready`에 가까운 `small_ranking_gap` 상태이며,
   ranking이 1차 병목으로 먼저 보이지 않는다.
2. `2026-07-09 / 001450`는 `small_entry_gap`까지 접근했는데도
   `activity_first_small_entry_gap`으로 분류됐다.
   즉 이 표본은 현재 계측 기준으로
   `entry`보다 `activity hard block`이 더 앞단 병목이다.
3. `2026-07-08 / 001450`도 `moderate_entry_gap`이 남아 있지만
   여전히 `activity_first_moderate_entry_gap`으로 분류되어,
   최소한 ranking 병목보다 activity 병목이 먼저 걸리는 구조다.
4. 따라서 다음 shadow 계측은
   `activity`를 풀면 바로 `candidate`가 되는지,
   아니면 그 다음 병목이 `top-k` 또는 `buy shape`로 이동하는지
   counterfactual 순서 분해로 이어져야 한다.

### 10.7.2 `activity` 해제 이후 `buy_shape` 세부 병목 분해

후속으로
`pre_buy_boundary_activity_counterfactual_next_gate`에 이어
`pre_buy_boundary_activity_buy_shape_detail`
계측을 추가하고
같은 구간을 다시 재집계했다.

사용 로그:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v23_activity_buy_shape_detail.json`

집계 결과:

| counterfactual next gate | sample_count | 해석 |
| --- | ---: | --- |
| `buy_shape_after_activity_moderate_entry_gap` | 1 | `activity`를 풀어도 즉시 `BUY`가 아니라 `moderate entry gap`을 가진 `buy_shape`에 머묾 |
| `buy_shape_after_activity_small_entry_gap` | 1 | `activity`를 풀어도 즉시 `BUY`가 아니라 `small entry gap`을 가진 `buy_shape`에 머묾 |

추가 `buy_shape` 세부 분해 결과:

| buy_shape detail | sample_count | candidate_count | selected_count | would_buy_count | submitted_count |
| --- | ---: | ---: | ---: | ---: | ---: |
| `watch_from_entry_setup|moderate_entry_gap` | 1 | 0 | 0 | 0 | 0 |
| `watch_from_entry_setup|small_entry_gap` | 1 | 0 | 0 | 0 | 0 |

일자별:

| trade_date | symbol | first bottleneck | next gate after activity | buy_shape detail | buy_shape reason | entry_gap_band | ranking_gap_band |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `2026-07-08` | `001450` | `activity_first_moderate_entry_gap` | `buy_shape_after_activity_moderate_entry_gap` | `watch_from_entry_setup|moderate_entry_gap` | `watch_from_entry_setup` | `moderate_entry_gap` | `small_ranking_gap` |
| `2026-07-09` | `001450` | `activity_first_small_entry_gap` | `buy_shape_after_activity_small_entry_gap` | `watch_from_entry_setup|small_entry_gap` | `watch_from_entry_setup` | `small_entry_gap` | `small_ranking_gap` |

해석:

1. `activity`를 풀어도 다음 1차 병목은 `top-k`가 아니고 `buy_shape`다.
2. 그 `buy_shape`도 `watch_from_exit_setup`가 아니라
   두 표본 모두 `watch_from_entry_setup`으로 수렴한다.
3. 즉 경계 코호트에서 현재 실제 순서는
   `low_relative_activity hard block -> watch_from_entry_setup 기반 buy_shape -> candidate 미전환`
   으로 보는 것이 맞다.
4. 또한 두 표본 모두 `small_ranking_gap`이므로
   지금 시점에서 우선 검증해야 할 대상은 ranking 완화가 아니라
   `watch_from_entry_setup` 내부의 `entry gap`과 `entry_score` 분포다.
5. 따라서 authoritative 완화는 계속 금지하고,
   다음 단계는 `buy_shape_after_activity_*` 코호트를
   `watch_from_entry_setup` 중심으로 더 세분화하여
   `entry_ready / small / moderate` band별 후행 proxy와 전환력을 누적 관측하는 것이다.

### 10.7.3 `watch_from_entry_setup|small/moderate_entry_gap` 전용 코호트 실측

후속으로
`watch_from_entry_setup|small_entry_gap`,
`watch_from_entry_setup|moderate_entry_gap`
전용 리포트를 추가하고
같은 구간을 다시 재집계했다.

중요한 점은,
아래 수치는 `2026-07-08`, `2026-07-09` 두 표본만 떼어 본 것이 아니라
`2026-07-01 ~ 2026-07-10` 전체 재집계 결과에서
해당 코호트에 실제로 걸린 표본만 추출한 것이다.
즉 표본 기준일 자체를 좁게 잡은 분석이 아니다.

사용 로그:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_v24_entry_setup_gap_cohorts.json`

집계 결과:

| cohort | sample_count | T+1 평균 | T+3 평균 | T+3 MFE | T+3 MAE | candidate | selected | would_buy | submitted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `watch_from_entry_setup|small_entry_gap` | 1 | `+5.8252%` | 없음 | 없음 | 없음 | 0 | 0 | 0 | 0 |
| `watch_from_entry_setup|moderate_entry_gap` | 1 | `-5.0066%` | 없음 | 없음 | 없음 | 0 | 0 | 0 | 0 |

개별 행 기준:

| trade_date | symbol | cohort | entry_score | entry_score_band | buy_gap | buy_gap_band | ranking_gap | ranking_gap_band | T+1 |
| --- | --- | --- | ---: | --- | ---: | --- | ---: | --- | ---: |
| `2026-07-09` | `001450` | `watch_from_entry_setup|small_entry_gap` | `0.5580` | `near_buy_floor` | `0.0920` | `small_entry_gap` | `0.0131` | `small_ranking_gap` | `+5.8252%` |
| `2026-07-08` | `001450` | `watch_from_entry_setup|moderate_entry_gap` | `0.5368` | `watch_band` | `0.1132` | `moderate_entry_gap` | `0.0247` | `small_ranking_gap` | `-5.0066%` |

해석:

1. 현재 표본 기준으로는 `small_entry_gap` 쪽이
   `moderate_entry_gap`보다 훨씬 유리한 초기 `T+1`을 보인다.
2. 반면 두 코호트 모두
   `candidate=0`, `selected=0`, `would_buy=0`, `submitted=0`이라
   실제 주문 전환력은 아직 전혀 열리지 않았다.
3. `small_entry_gap` 표본은 `near_buy_floor`까지 접근했지만
   여전히 `watch_from_entry_setup` 단계에 머문다.
4. `moderate_entry_gap` 표본은 아직 `watch_band`라서,
   같은 `watch_from_entry_setup`이어도
   `small`과 `moderate`를 같은 완화 후보로 묶는 것은 이르다.
5. 다만 현재는 `2026-07-08`, `2026-07-09` 표본이라
   `T+3 / MFE / MAE`가 아직 비어 있다.
   따라서 다음 판단은 추가 장후 배치 누적 후
   `small_entry_gap`의 후행 proxy 우위가 유지되는지부터 봐야 한다.
6. 후속 운영 관측 편의를 위해
   `ops-scheduler`의
   `trigger_proxy_attribution` summary parser에도
   아래 metric을 추가했다.
   - `pre_buy_boundary_entry_setup_small_gap_count`
   - `pre_buy_boundary_entry_setup_small_gap_candidate_count`
   - `pre_buy_boundary_entry_setup_small_gap_would_buy_count`
   - `pre_buy_boundary_entry_setup_small_gap_submitted_count`
   - `pre_buy_boundary_entry_setup_moderate_gap_count`
   - `pre_buy_boundary_entry_setup_moderate_gap_candidate_count`
   - `pre_buy_boundary_entry_setup_moderate_gap_would_buy_count`
   - `pre_buy_boundary_entry_setup_moderate_gap_submitted_count`

### 10.7.4 `2026-07-01 ~ 2026-07-10` 기준 hydration 보강 후 `entry_score` 하방 편향 구조 점검

이번 세션에서는
`core_risk_off` 완화 판단을 더 밀기 전에,
`analyze_trigger_proxy_attribution.py`의 hydration 범위를
`active=true` row에만 한정하지 않고
`source_type='core'` 전체 row로 넓혔다.

즉 이제는 `core_risk_off_experiment`가 비어 있거나
`active=false`여도,
연결된 `signal_feature_snapshot.component_scores_json`
또는 snapshot feature fallback에서
`shadow_overall_score_v5`,
`shadow_slow_score_v5`,
`shadow_fast_score_v5`,
`shadow_component_scores_v5`,
`shadow_reason_codes_v5`,
`shadow_diagnostics_v5`
를 같이 복원한다.

실측 결과:

- `2026-07-01 ~ 2026-07-10` 첫 symbol/day 기준
  `core` 표본은 `97건`
- 이 중
  `shadow_overall_score_v5`, `shadow_slow_score_v5`
  가 채워진 `core` 표본은 `97/97`
- `core_risk_off_experiment.active=true`
  표본은 `49건`이고,
  이 또한 `49/49`가 v5 score를 보유한다

따라서 7/11에 지적됐던
`v5 score hydration 누락`은
현재 분석 경로 기준으로는 해소됐다고 볼 수 있다.

동일 구간에서
`entry_score`를 직접 분해해보면,
진짜 병목은 `core_risk_off` 완화 경계보다
`entry_score`의 population-level 하방 편향에 더 가깝다.

핵심 수치:

| cohort | count | entry_score 평균 | entry_score 최대 | 해석 |
| --- | ---: | ---: | ---: | --- |
| 전체 first symbol/day | 169 | `0.1704` | `0.5893` | 전체 분포는 강하게 하방 편향 |
| `core` | 97 | `0.1578` | `0.5580` | 특히 core 평균이 매우 낮음 |
| `watch_from_entry_setup` 또는 `entry_score >= 0.52` | 27 | `0.5099` | `0.5893` | 근접군은 존재하지만 얇음 |
| `0.52 <= entry_score < 0.65` | 10 | `0.5540` | `0.5893` | BUY floor 근처까지는 오지만 `0.65`는 못 넘음 |

`core` 평균 `entry_score`의 항목별 평균 기여:

| 항목 | 평균 기여 |
| --- | ---: |
| `overall_term` | `+0.1465` |
| `fast_term` | `+0.0580` |
| `slow_term` | `+0.0532` |
| `bullish_term` | `+0.0175` |
| `risk_off_term` | `-0.1500` |
| `allocation_term` | `+0.0272` |
| `strategy_term` | `+0.0000` |
| `relative_activity_term` | `+0.0038` |

해석:

1. `core` 평균 분포에서는
   `risk_off_penalty=-0.15`가 거의 상수처럼 작동한다.
2. 반면 이를 상쇄해야 할
   `bullish_regime`, `strategy_alignment`, `relative_activity_bonus`
   는 평균적으로 매우 작다.
3. 특히 `core` 경로는
   `preferred_strategy='defensive_low_volatility_rotation'`
   가 많아
   `trigger_strategy_alignment(+0.05)`를 거의 받지 못한다.
4. 상위 `core` WATCH 근접군(`001450`, `000810`)도
   `slow_score`는 높지만
   `risk_off_penalty=-0.15`가 고정으로 깔리고,
   `relative_activity_bonus`가 0인 경우가 많아
   `0.53~0.56`에서 멈춘다.
5. 즉 최근 BUY 0건의 원인을
   `core_risk_off` shadow bucket 완화 여부로만 보는 것은 부정확하고,
   먼저 `entry_score`가 어떤 경로에서
   `0.65`를 넘지 못하는지 계층적으로 분해하는 쪽이 맞다.

따라서 다음 단계는
`core_risk_off` threshold 완화가 아니라,
`WATCH` 또는 `entry_score >= 0.52` 근접군을 중심으로
`overall / fast / slow / regime / strategy / relative activity`
기여도와
`watch_from_entry_setup` 미전환 병목을 추가 분해하는 것이다.

추가로 이번 턴에는
`scripts/analyze_trigger_proxy_attribution.py`에
`entry_score_bias_report`를 정식 payload로 추가했다.

신규 산출물:

- `logs/trigger_proxy_attribution_2026-07-01_2026-07-10_entry_bias_v2.json`

이 payload에는 아래가 같이 들어간다.

- `all`
- `core`
- `watch_candidate_all`
- `watch_from_entry_setup_or_ge_052`
- `near_buy_floor`
- `near_buy_floor_counterfactual`
- `top_core_samples`

따라서 이제는 ad-hoc 보조 스크립트 없이도
같은 재집계 결과 안에서
`entry_score` 하방 편향과
근접군의 counterfactual을 반복 측정할 수 있다.

`near_buy_floor_counterfactual` 실측 결과:

| cohort | 표본 수 | `risk_off_penalty` 제거 시 `0.65` 상회 | `strategy_alignment`만 추가 시 `0.65` 상회 | `relative_activity_bonus` 최대치 부여 시 `0.65` 상회 |
| --- | ---: | ---: | ---: | ---: |
| `0.52 <= entry_score < 0.65` | 10 | 10 | 0 | 5 |

해석:

1. `near_buy_floor` 10건은 모두
   `trigger_risk_off_penalty=-0.15`만 제거해도
   BUY threshold `0.65`를 넘는다.
2. 반면 `trigger_strategy_alignment(+0.05)`만으로는
   단독 상회 표본이 0건이다.
3. `relative_activity_bonus`를 최대치로 본 counterfactual도
   10건 중 5건만 `0.65`를 넘는다.
4. 즉 현재 `entry_score` 하방 편향의 1차 억제 항목은
   `risk_off_penalty`이고,
   `strategy_alignment`와 `relative_activity_bonus`는
   보조 억제 항목으로 보는 쪽이 맞다.
5. 다만 본 세션 기준 원칙은
   `core_risk_off` threshold 완화 중단이므로,
   위 수치는 즉시 완화 근거가 아니라
   **entry score 병목의 구조적 위치를 증명한 관측치**로만 사용한다.

근접군의 2차 억제 패턴:

| cohort | 표본 수 | `high_volatility` | `strategy_alignment` | `relative_activity_bonus` | 해석 |
| --- | ---: | ---: | ---: | ---: | --- |
| `watch_from_entry_setup_or_ge_052` | 27 | 26 | 15 | 9 | 거의 전 표본이 변동성 패널티를 같이 받음 |
| `near_buy_floor` | 10 | 10 | 7 | 1 | BUY 직전 표본도 변동성 패널티는 전부 존재 |
| `near_buy_floor_core` | 3 | 3 | 0 | 0 | core 근접군은 `strategy/activity` 보너스가 사실상 전무 |

즉 `core` 근접군은
`slow_score` 자체는 상당히 높은데도,

- `risk_off_penalty=-0.15`가 고정으로 깔리고
- `high_volatility`가 전부 동반되며
- `strategy_alignment`와 `relative_activity_bonus`가 비어 있는

형태가 반복된다.

따라서 다음 실측 분해 우선순위는
`slow_score` 추가 완화가 아니라
`fast_score`, `high_volatility`, `relative_activity_bonus` 부재가
`core` 근접군에서 어떻게 동시 발생하는지 확인하는 것이다.

`2026-07-12` 추가 분해 산출물:

- `logs/entry_score_joint_suppression_2026-07-01_2026-07-10.json`

동시 억제 패턴 실측:

| cohort | 표본 수 | 핵심 관측치 | 해석 |
| --- | ---: | --- | --- |
| `watch_from_entry_setup_or_ge_052` | 27 | `high_volatility 26/27`, `fast_score < -0.20` `14/27`, `fast_score >= 0` `3/27` | 근접군 대부분이 이미 fast layer 약세와 high volatility를 동시에 안고 있음 |
| `top_core_samples` 상위 10건 | 10 | `001450(2026-07-09)`만 `fast_score=+0.035`, 나머지 상위권은 모두 음수 fast | core 근접군은 `slow_score`가 높아도 fast layer가 entry 상향을 막고 있음 |
| `top_core_samples` 상위 10건 | 10 | `high_volatility 10/10`, `relative_activity_bonus 2/10` | core 근접군은 volatility tail이 거의 상수처럼 붙고 activity 보너스는 희소함 |

추가 해석:

1. `entry_score` 상단 근접군을 다시 봐도
   병목은 단일 `risk_off_penalty`가 아니라
   `weak fast_score + high_volatility + sparse activity bonus`
   조합에 더 가깝다.
2. 즉 `slow_score` 기반 완화나
   `risk_off_penalty` 단독 제거는
   구조적으로 잘못된 타격점일 가능성이 높다.
3. 다음 shadow formula는
   적어도 `fast_score` 하방 꼬리와
   `high_volatility` 구간을 함께 제어해야 한다.

### 10.7.5 `entry_score` shadow formula back-simulation (`2026-06-01 ~ 2026-07-10`)

이번 턴에는
`risk_off_penalty` 완화안을 실제로 넣지 않고,
과거 실측 row에 대해
virtual candidate를 만들어
후행 수익률로 먼저 검증했다.

산출물:

- `logs/entry_score_shadow_formula_backsim_2026-06-01_2026-07-10.json`

검증한 shadow formula:

1. `SF1_broad_remove_risk_off_near_buy_floor`
   - 조건:
     `0.52 <= entry_score < 0.65`
     그리고 `trigger_risk_off_penalty` 존재
   - 해석:
     near-buy 전 구간을 넓게 열어주는 공격형 완화안

2. `SF2_core_remove_risk_off_near_buy_floor`
   - 조건:
     `source_type='core'`
     그리고 `0.52 <= entry_score < 0.65`
     그리고 `trigger_risk_off_penalty` 존재

3. `SF3_core_watch_setup_no_bonus_remove_risk_off`
   - 조건:
     `SF2`
     + `trigger_watch_from_entry_setup`
     + `trigger_strategy_alignment` 없음
     + `trigger_relative_activity_bonus` 없음

실측 결과:

| formula | virtual candidates | T+1 평균 | T+1 승률 | T+3 평균 | T+3 승률 | T+5 평균 | T+5 승률 | 판정 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `SF1_broad_remove_risk_off_near_buy_floor` | 50 | `-1.4160%` | `37.50%` | `-5.2937%` | `23.26%` | `-8.4620%` | `14.29%` | `No-Go` |
| `SF2_core_remove_risk_off_near_buy_floor` | 4 | `+0.4006%` | `50.00%` | `-8.4906%` | `0.00%` | `-16.9434%` | `0.00%` | `No-Go` |
| `SF3_core_watch_setup_no_bonus_remove_risk_off` | 4 | `+0.4006%` | `50.00%` | `-8.4906%` | `0.00%` | `-16.9434%` | `0.00%` | `No-Go` |

해석:

1. `SF1`은 표본 수는 충분하지만
   `T+1`, `T+3`, `T+5`가 모두 음수이므로
   `최고 기대수익률` 목표와 정면 충돌한다.
2. `SF2`와 `SF3`은
   core 근접군만 남겼기 때문에
   `T+1`은 약하게 플러스지만,
   현재 확보된 `T+3/T+5`는
   단 하나의 오래된 표본(`2026-06-30 / 000660`)이
   크게 음수로 남아 있다.
3. 따라서 현재 시점에서
   `risk_off_penalty` 제거형 shadow formula는
   넓게도, 좁게도
   authoritative 승격 근거가 없다.
4. 즉 `entry_score` 병목이 확인됐더라도
   곧바로 `risk_off_penalty`를 풀어서는 안 되고,
   다음 후보는
   `high_volatility` 동반 구간과
   `fast_score` 하방 구간을 함께 제어하는
   더 좁은 shadow formula여야 한다.
7. `2026-07-12` 기준으로
   `2026-07-01 ~ 2026-07-11`까지 범위를 늘려
   재집계(`v25`)를 다시 실행했지만,
   두 코호트의 `T+3 / MFE / MAE`는 여전히 비어 있었다.
   이유는 표본 날짜가
   `2026-07-08(수)`,
   `2026-07-09(목)`인데,
   확장 종료일 `2026-07-11`은 `토요일`이라
   실제 추가 거래일이 열리지 않았기 때문이다.
   즉 현재 미완료 체크리스트의 blocker는
   코드 미구현이 아니라
   **후속 거래일 미도래**다.
8. 보수적으로 `fast_score`까지 같이 조여도
   아직 `Go` 근거는 없다.
   `0.52 <= entry_score < 0.65`와 `risk_off_penalty`를 만족하는
   50건에 대해 `fast_score >= -0.12`를 추가로 걸면
   표본은 17건으로 줄고,
   `T+1=+0.0883%`, `T+3=-3.1981%`, `T+5=-3.9202%`다.
   이는 broad formula보다 손실폭은 줄지만
   여전히 `최고 기대수익률` 기준에서는 `No-Go`다.
9. 따라서 다음 단계는
   `fast_score` 단일 협소화가 아니라
   `high_volatility` tail과 결합된
   더 좁은 joint shadow formula 설계여야 한다.

### 10.7.6 `fast_score + high_volatility` joint shadow formula back-simulation

산출물:

- `logs/entry_score_joint_shadow_formula_backsim_2026-06-01_2026-07-10.json`

검증한 추가 formula:

1. `SF7_market_high_vol_fast_ge_-0.12_no_rel_bonus`
   - 조건:
     `source_type='market_overlay'`
     + `trigger_high_volatility`
     + `fast_score >= -0.12`
     + `trigger_relative_activity_bonus` 없음

2. `SF8_high_vol_fast_ge_-0.12_no_rel_bonus_entry_ge_0.55`
   - 조건:
     `trigger_high_volatility`
     + `fast_score >= -0.12`
     + `trigger_relative_activity_bonus` 없음
     + `entry_score >= 0.55`

3. `SF9_all_high_vol_fast_ge_-0.12_no_rel_bonus`
   - 조건:
     `trigger_high_volatility`
     + `fast_score >= -0.12`
     + `trigger_relative_activity_bonus` 없음

실측 결과:

| formula | count | T+1 평균 | T+1 승률 | T+3 n | T+3 평균 | T+3 승률 | T+5 n | T+5 평균 | T+5 승률 | MFE3 | MAE3 | 판정 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `SF7_market_high_vol_fast_ge_-0.12_no_rel_bonus` | 4 | `+2.0353%` | `50.00%` | 4 | `+0.8455%` | `50.00%` | 4 | `+3.4324%` | `75.00%` | `+9.9445%` | `-4.3726%` | `Shadow-Watch` |
| `SF8_high_vol_fast_ge_-0.12_no_rel_bonus_entry_ge_0.55` | 6 | `+1.1106%` | `50.00%` | 4 | `+0.8455%` | `50.00%` | 4 | `+3.4324%` | `75.00%` | `+9.9445%` | `-4.3726%` | `Shadow-Watch` |
| `SF9_all_high_vol_fast_ge_-0.12_no_rel_bonus` | 10 | `+0.3675%` | `40.00%` | 6 | `-0.2309%` | `50.00%` | 6 | `+1.5371%` | `50.00%` | `+8.7332%` | `-5.9150%` | `No-Go` |

해석:

1. `SF7`, `SF8`은
   broad formula와 달리
   `T+3`, `T+5`가 모두 플러스로 돌아선
   첫 joint shadow formula다.
2. 다만 두 formula의 유효 `T+3/T+5` 표본은
   사실상 같은 4개 구표본에 기대고 있다.
   심볼도 `000660` 2건, `000810` 1건, `009150` 1건으로
   집중도가 높다.
3. 즉 이는 `authoritative Go`가 아니라
   **shadow-only watch candidate**다.
   더 많은 후속 거래일에서
   같은 band가 반복 재현되는지 확인해야 한다.
4. 반면 `SF9`처럼 범위를 조금만 넓혀도
   `T+3`가 다시 음수로 돌아간다.
   따라서 현 단계에서 완화는
   반드시 매우 좁은 구조로만 관찰돼야 한다.

추가 견고성 점검:

- `logs/entry_score_joint_shadow_formula_robustness_2026-06-01_2026-07-10.json`

leave-one-symbol-out 결과:

| formula | 제외 심볼 | T+3 평균 | T+5 평균 | 해석 |
| --- | --- | ---: | ---: | --- |
| `SF7_market_high_vol_fast_ge_-0.12_no_rel_bonus` | 없음 | `+0.8455%` | `+3.4324%` | base |
| `SF7_market_high_vol_fast_ge_-0.12_no_rel_bonus` | `000660` 제외 | `-3.7818%` | `+1.3744%` | 핵심 수익 기여 심볼 제거 시 성과 약화 |
| `SF8_high_vol_fast_ge_-0.12_no_rel_bonus_entry_ge_0.55` | 없음 | `+0.8455%` | `+3.4324%` | base |
| `SF8_high_vol_fast_ge_-0.12_no_rel_bonus_entry_ge_0.55` | `000660` 제외 | `-3.7818%` | `+1.3744%` | 동일하게 `000660` 의존도가 큼 |

해석 보강:

1. `SF7/SF8`은 broad formula 대비 분명히 개선됐지만,
   현재 플러스 수익률의 상당 부분이
   `000660` 2건에 기대고 있다.
2. 따라서 이 두 formula는
   `Go`는 물론이고
   “일반화 가능한 quasi-Go”로도 보기 어렵다.
3. 현 시점 최종 판정은
   **`Shadow-Watch` 유지, authoritative 승격 금지**다.

추가 중복 제거 점검:

- `logs/entry_score_joint_shadow_formula_symbol_dedup_2026-06-01_2026-07-10.json`

심볼당 1건만 남긴 뒤 재집계하면:

| formula | 방식 | T+3 평균 | T+5 평균 | 해석 |
| --- | --- | ---: | ---: | --- |
| `SF7_market_high_vol_fast_ge_-0.12_no_rel_bonus` | earliest per symbol | `+2.7413%` | `+1.6964%` | `000660`의 첫 관측치를 남기면 플러스 유지 |
| `SF7_market_high_vol_fast_ge_-0.12_no_rel_bonus` | latest per symbol | `-4.1351%` | `+3.7964%` | `000660`의 다음날 관측치로 바꾸면 T+3가 음수 전환 |
| `SF8_high_vol_fast_ge_-0.12_no_rel_bonus_entry_ge_0.55` | earliest per symbol | `+2.7413%` | `+1.6964%` | `001450`는 T+3 미관측, 핵심은 기존 3심볼 |
| `SF8_high_vol_fast_ge_-0.12_no_rel_bonus_entry_ge_0.55` | latest per symbol | `-2.3455%` | `+9.1947%` | 관측시점 선택에 따라 T+3 부호가 다시 바뀜 |

해석 보강:

1. `SF7/SF8`은
   같은 심볼이 연속 날짜로 중복 출현하는 구조를 걷어내도
   여전히 안정적 `Go`로 수렴하지 않는다.
2. 특히 `000660`의 어느 날짜를 대표값으로 남기느냐에 따라
   `T+3` 부호가 바뀐다.
3. 따라서 현재 관측은
   “formula 우위”라기보다
   “소수 심볼의 시점 민감 결과”로 보는 편이 맞다.

추가 전환 경로 점검:

- `logs/entry_score_joint_shadow_formula_transition_2026-06-01_2026-07-10.json`

| formula | count | eligibility_passed | buy_candidate | watch_candidate | submission_accepted | 최종 액션 분포 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `SF7` | 4 | 2 | 0 | 4 | 0 | `watch 2`, `hold 2` |
| `SF8` | 6 | 2 | 0 | 6 | 0 | `watch 4`, `hold 2` |

해석 보강:

1. `SF7/SF8`은 후행 수익률이 일부 개선돼 보여도
   현재 로그상 전부 `WATCH/HOLD`에 머물렀다.
2. 즉 `entry_score` 협소 완화 band를 찾는 것만으로는 부족하고,
   실제 다음 병목은
   `buy_candidate` 및 최종 매수 전환 경로가 열리지 않는 데 있다.
3. 따라서 다음 거래일 관측에서는
   단순 수익률뿐 아니라
   `candidate -> selected -> would_buy -> submitted`
   전환이 실제로 열리는지까지 같이 봐야 한다.

추가 코드/실측 대조:

1. 코드 기준으로
   `eligibility_passed=True` 이후 `buy_candidate`를 만드는 하드 조건은
   사실상 `entry_score >= 0.65`다.
   - `src/agent_trading/services/deterministic_trigger_engine.py`
   - `buy_candidate_threshold = 0.65`
2. `SF7/SF8` 표본 중
   실제로 `eligibility_passed=True`였지만 `buy_candidate=False`였던
   row는 2건뿐이다.
   - `2026-06-18 / 000660 / entry_score 0.5788 / gap 0.0712`
   - `2026-06-18 / 000810 / entry_score 0.5879 / gap 0.0621`
3. 이 2건을 “threshold만 낮춰 BUY로 넘긴다”는
   counterfactual로 보면
   `T+1 평균 +1.4711%`였지만
   `T+3 평균 -6.2780%`, `T+3 hit rate 0%`였다.
4. 추가로 `near_buy_floor` 전체를 다시 분해해도
   현재는 `ranking_score`가 높은 근접군이 더 낫다는 근거가 없다.
   - `ranking_score >= 0.60` 구간(2건):
     `T+3 평균 -6.2780%`
   - `0.55 <= ranking_score < 0.60` 구간(14건):
     `T+3 평균 -5.5901%`
   - `entry_score >= 0.58` 구간(8건):
     `T+3 평균 -7.5000%`

해석 보강:

1. 현재 병목이 `buy_candidate_threshold`인 것은 맞다.
2. 그러나 이 병목을 단순히 숫자 완화로 열면
   바로 기대수익률이 훼손될 가능성이 높다.
3. 따라서 다음 단계는
   `0.65` 자체를 내리는 것이 아니라,
   왜 `eligibility_passed` 이후에도
   상대적으로 좋은 표본과 나쁜 표본이 함께 `0.58` 근처에 뭉치는지,
   그 분리축을 더 찾아내는 방향이어야 한다.
4. 특히 현재 데이터에서는
   `ranking_score`를 약간 더 높게 요구하는 방식이나
   `entry_score` 상단 근접군을 BUY로 더 빨리 승격하는 방식 모두
   `최고 기대수익률` 기준과 맞지 않는다.

추가 lane 분해:

- `logs/entry_score_near_buy_cross_bucket_2026-06-01_2026-07-10.json`

`source_type / relative_activity / fast_band` 교차 집계 결과:

| bucket | count | T+3 평균 | T+5 평균 | 해석 |
| --- | ---: | ---: | ---: | --- |
| `market_overlay + no_rel_bonus + fast -0.12~-0.05` | 4 | `+0.8455%` | `+3.4324%` | 현재까지 유일하게 플러스가 나온 협소 lane |
| `market_overlay + no_rel_bonus + fast -0.20~-0.12` | 14 | `-6.3110%` | `-9.5145%` | fast가 한 단계만 더 나빠져도 급격히 악화 |
| `market_overlay + no_rel_bonus + fast < -0.20` | 7 | `-7.3044%` | `-10.0692%` | deep negative fast tail은 명확한 `No-Go` |
| `market_overlay + rel_bonus + fast -0.12~-0.05` | 3 | `-9.4574%` | `-9.6531%` | activity bonus가 붙어도 오히려 나빴음 |
| `reconciliation_overlay + no_rel_bonus + fast -0.12~-0.05` | 2 | `-2.3838%` | `-2.2535%` | 완화 근거 부족 |
| `event_overlay + no_rel_bonus + fast -0.20~-0.12` | 3 | `-4.2739%` | `-9.4760%` | broad 대비 덜 나쁘지만 여전히 `No-Go` |

해석 보강:

1. 현재 `near_buy_floor`에서
   살아남는 축은 `entry_score`나 `ranking_score` 숫자 자체가 아니라
   **source lane + fast band + relative activity state** 조합이다.
2. 특히 `relative_activity_bonus`는
   이 구간에서는 긍정 신호로 작동하지 않았다.
   적어도 현재 표본에서는
   `market_overlay + rel_bonus`가 오히려 더 나빴다.
3. 따라서 다음 shadow 관측은
   `market_overlay + no_rel_bonus + fast -0.12~-0.05`
   협소 lane을 중심으로 하되,
   이것 역시 표본이 4건뿐이므로
   즉시 승격이 아니라 누적 관측 대상으로만 유지해야 한다.

협소 lane 내부 추가 분해:

- `logs/entry_score_market_lane_inner_split_2026-06-01_2026-07-10.json`

대상:

- `market_overlay + no_rel_bonus + fast -0.12~-0.05` 4건

추가 비교 결과:

| split | count | T+3 평균 | T+5 평균 | 해석 |
| --- | ---: | ---: | ---: | --- |
| `return_3m_pct >= 100` | 3 | `+3.6988%` | `+6.9099%` | 중기 상승 추세가 강한 표본만 남기면 개선 |
| `return_3m_pct < 100` | 1 | `-7.7143%` | `-7.0000%` | 약한 추세 표본은 손실 |
| `price_vs_sma_60_pct >= 50` | 3 | `+3.6988%` | `+6.9099%` | SMA60 대비 괴리가 큰 표본이 상대적으로 우수 |
| `price_vs_sma_60_pct < 50` | 1 | `-7.7143%` | `-7.0000%` | 괴리가 낮은 표본은 손실 |
| `ranking_score >= 0.59` | 2 | `-6.2780%` | `+0.8203%` | ranking 상단이 오히려 좋은 분리축이 아님 |
| `volume_surge_ratio >= 0.7` | 2 | `-6.2780%` | `+0.8203%` | 단기 activity 확장은 오히려 불안정 |
| `volume_surge_ratio < 0.7` | 2 | `+7.9691%` | `+6.0445%` | 지나치게 뜨겁지 않은 표본이 오히려 나음 |

해석 보강:

1. 협소 lane 안에서도
   `ranking_score`는 좋은 분리축이 아니다.
2. 현재 남는 추가 설명력은
   `return_3m_pct`와 `price_vs_sma_60_pct` 같은
   **중기 추세 강도** 쪽에서 나타난다.
3. 즉 다음 shadow formula를 더 좁힌다면
   `market_overlay + no_rel_bonus + fast -0.12~-0.05`
   위에
   `return_3m_pct` 또는 `price_vs_sma_60_pct` 하한을
   shadow-only로 얹는 방향이 가장 합리적이다.

추가 trend-filtered shadow formula back-simulation:

- `logs/entry_score_trend_filtered_shadow_formula_backsim_2026-06-01_2026-07-10.json`

검증한 formula:

1. `SF10_market_no_rel_fast_band_trend3m100`
   - `market_overlay + no_rel_bonus + -0.12<=fast<-0.05 + return_3m_pct>=100`
2. `SF11_market_no_rel_fast_band_sma60_50`
   - `market_overlay + no_rel_bonus + -0.12<=fast<-0.05 + price_vs_sma_60_pct>=50`
3. `SF12_market_no_rel_fast_band_trend3m100_sma60_50`
   - `market_overlay + no_rel_bonus + -0.12<=fast<-0.05 + return_3m_pct>=100 + price_vs_sma_60_pct>=50`

실측 결과:

| formula | count | T+1 평균 | T+3 평균 | T+5 평균 | T+5 승률 | MFE3 | MAE3 | 판정 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `SF10` | 3 | `+2.7137%` | `+3.6988%` | `+6.9099%` | `100%` | `+11.4974%` | `-2.8778%` | `Shadow-Watch` |
| `SF11` | 3 | `+2.7137%` | `+3.6988%` | `+6.9099%` | `100%` | `+11.4974%` | `-2.8778%` | `Shadow-Watch` |
| `SF12` | 3 | `+2.7137%` | `+3.6988%` | `+6.9099%` | `100%` | `+11.4974%` | `-2.8778%` | `Shadow-Watch` |

해석 보강:

1. `return_3m_pct >= 100`과 `price_vs_sma_60_pct >= 50`은
   현재 표본에서는 사실상 같은 3건으로 수렴한다.
2. 이 3건의 후행 수익률은
   기존 `SF7/SF8`보다 더 좋다.
3. 그러나 표본이 `3건`뿐이므로
   아직 `Go`가 아니라
   **다음 장후 배치에서 우선적으로 누적 관측할 shadow formula**다.

### 10.8.1 strict floor 상세 분해

추가 진단 필드 `shadow_signal_floor_miss_detail`로
active `trend_moderate_candidate` 4건을 다시 분해하면 다음과 같다.

| detail | sample_count | 해석 |
| --- | ---: | --- |
| `overall_near_slow_deep` | 3 | `overall`는 완화 window 근처지만 `slow`가 깊게 음수 |
| `overall_deep_slow_near` | 1 | `slow`는 완화 window 근처지만 `overall`가 깊게 음수 |

개별 행 기준:

| trade_date | symbol | detail |
| --- | --- | --- |
| `2026-07-02` | `000240` | `overall_deep_slow_near` |
| `2026-07-03` | `002790` | `overall_near_slow_deep` |
| `2026-07-10` | `000080` | `overall_near_slow_deep` |
| `2026-07-10` | `002790` | `overall_near_slow_deep` |

이 분해가 의미하는 바는 다음과 같다.

1. active `trend_moderate_candidate`의 다수는
   `overall`보다 `slow`의 깊은 음수 때문에 strict floor에서 막힌다.
2. 따라서 다음 shadow 관측은
   `overall floor` 전체 완화가 아니라
   `slow_trend` 중심의 제한적 `slow floor` shadow 완화가 우선이다.
3. 동시에 `slow_momentum`까지 같이 풀면
   `overall_near_slow_deep`와 `double_deep_miss`가 뒤섞여
   기대수익률 검증력이 떨어지므로 금지 원칙을 유지해야 한다.

### 10.8.2 `slow floor shadow` 경로 실측

추가 계측 필드 `slow_floor_shadow_relax_path`로
active `trend_moderate_candidate` 4건을 다시 보면 다음과 같다.

| path | sample_count | 해석 |
| --- | ---: | --- |
| `slow_floor_relax_ready` | 1 | `slow floor` shadow 완화만으로 다음 관측 후보가 될 수 있는 표본 |
| `slow_floor_relax_activity_blocked` | 2 | `slow floor`는 풀려도 `low_relative_activity` 계열 hard block이 남는 표본 |
| `overall_floor_first` | 1 | `slow`보다 `overall` 쪽이 먼저 병목인 표본 |

해석:

1. active `trend_moderate_candidate` 4건 전체를 한 번에 풀어서는 안 된다.
2. 실제로 `slow floor` 중심 완화 관측 대상으로 남는 것은 1건뿐이다.
3. 2건은 `activity`가 먼저 막히므로,
   `low_relative_activity` hard block을 건드리지 않는 현재 원칙과 충돌하지 않는다.
4. 나머지 1건은 `overall_floor_first`라서
   `slow floor shadow` 대상이 아니라 별도 보류가 맞다.

즉, 다음 단계의 정확한 범위는
`trend_moderate_candidate` 전체가 아니라
`slow_floor_relax_ready` 코호트만 장후 누적 관측하는 것이다.

추가로 날짜 단위로 다시 잘라보면,
현재 확인된 `slow_floor_relax_ready` 코호트는
`2026-07-03` 1건뿐이다.

| trade_date | sample_count | T+1 평균 | T+3 평균 | candidate_count | selected_count | would_buy_count | submitted_count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `2026-07-03` | 1 | `1.4583%` | `3.3333%` | 1 | 0 | 0 | 0 |

즉, 현재까지의 실측에서는
`slow_floor_relax_ready`로 추려도
실제 `selected` 또는 `BUY path` 전환은 아직 전혀 열리지 않았다.
다음 관측의 초점은
이 코호트가 왜 계속 `selected=0`에 머무는지,
즉 `top-k selection` 이전/이후 어느 축에서 막히는지를
추가로 좁히는 것이다.

ready 코호트의 직접 원인도 별도 집계로 확인했다.

| 축 | bucket | sample_count |
| --- | --- | ---: |
| projection block reason | `shadow_topk_candidate_miss` | 1 |
| gate reason | `signal_both_floor_miss` | 1 |
| watch reason | `core_watch_path_only` | 1 |

즉 `2026-07-03`의 `slow_floor_relax_ready` 1건은

1. 후행 proxy는 양호했지만,
2. 여전히 strict `overall/slow` gate가 유지되는 구조라
   `shadow_topk_candidate`가 되지 못했고,
3. 실제 decision shape도 `WATCH`에 머물러
   `BUY candidate` 경로가 열리지 않았다.

추가로 ready 코호트의 전환 단계 집계는
`watch_only_core_path=1`로 확인됐다.

이는 다음을 의미한다.

1. 현재 ready 코호트는
   `buy_shape 진입 후 탈락` 단계가 아니다.
2. 더 앞단에서
   decision shape 자체가 아직 `core WATCH path`에 머물러 있다.
3. 따라서 다음 장후 관측의 핵심 질문은
   `selected 여부`보다 먼저
   `WATCH -> BUY candidate shape` 전환이 실제로 발생하는지다.

따라서 다음 장후 관측의 초점은
`slow_floor_relax_ready` 코호트가
언제 `WATCH`에서 `BUY candidate`로 넘어갈 수 있는지,
또는 계속 `core_watch_path_only`로만 남는지를 확인하는 것이다.

이 관측을 재가공 없이 보기 위해
`active_slow_floor_relax_ready_trade_date_transition_stage_items`
필드를 추가했다.

최신 재집계 기준:

| bucket | sample_count |
| --- | ---: |
| `2026-07-03|watch_only_core_path` | 1 |

즉 다음 장후부터는
`ready 코호트가 어떤 날짜에 어떤 전환 단계에 머무는지`
를 날짜 단위로 바로 비교할 수 있다.

추가로 이번 보강으로
`active_slow_floor_relax_ready_samples` 필드가 생겨
aggregate만이 아니라 sample row 자체를 직접 읽을 수 있게 됐다.

최신 재집계 기준 ready 코호트 sample:

| trade_date | symbol | primary_candidate | ranking_score | entry_score | shadow_overall_score_v5 | shadow_slow_score_v5 | projection_block_reason | watch_reason |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `2026-07-03` | `002790` | `WATCH` | `0.4166` | `0.2479` | `-0.1274` | `-0.43` | `shadow_topk_candidate_miss` | `core_watch_path_only` |

이 row는 다음을 보여준다.

1. ready 코호트는 실제로 `BUY candidate shape`까지 가지 못하고 있다.
2. `ranking_score`는 관측 후보 수준까지는 올라왔지만
   현재 core buy 경로를 열 만큼 충분하지 않다.
3. `overall`은 `moderate_negative` 경계까지 올라왔지만,
   `slow`는 여전히 `deep_negative`라
   strict signal gate가 유지된다.
4. 따라서 다음 shadow 관측의 핵심은
   `WATCH` 증가가 아니라
   이 ready sample이 실제로 `BUY candidate` shape로 전환되는지 여부다.

추가 gap 계측 기준으로 같은 sample은 다음과 같다.

| 항목 | 값 | 해석 |
| --- | ---: | --- |
| `deterministic_buy_shape_block_reason` | `watch_from_exit_setup` | 현재 WATCH shape는 진입 직전 관찰이 아니라 exit setup 계열에서 형성됨 |
| `buy_candidate_threshold_gap` | `0.4021` | `entry_score`가 BUY threshold `0.65`보다 아직 크게 낮다 |
| `watch_candidate_threshold_gap` | `0.0` | WATCH threshold는 이미 충분히 넘고 있다 |
| `core_risk_off_ranking_min_gap` | `0.0634` | core risk-off ranking hard min `0.48`보다 조금 부족하다 |
| `shadow_topk_ranking_min_gap` | `0.0` | shadow top-k 관찰 최소 기준 `0.22`는 이미 충족한다 |

즉 이 sample은
`ranking`이 아주 멀리 부족한 상태는 아니지만,
`entry_score`는 아직 BUY threshold와 큰 간격이 있고,
현재 WATCH도 `entry setup`보다 `exit setup` 성격이 강하다.
따라서 다음 단계는
threshold 완화보다 먼저
`watch_from_exit_setup`가 core 신규 진입 후보에서 어떤 비중으로 발생하는지,
그리고 그것이 실제 기대수익률 관점에서 유효한 선행 패턴인지 분해하는 것이다.

### 10.9 active 35건의 직접 차단 사유

`core_risk_off_floor_v5_diagnostics` 기준:

| blocking reason | sample_count |
| --- | ---: |
| `overall_below_mild_floor` | 28 |
| `overall_missing` | 7 |

즉, 현재 남은 병목의 본체는 `overall_missing`이 아니라
`overall_below_mild_floor` 28건이다.

다만 이 28건의 `overall_v5` 하방 편향은 다시 `slow_score_v5` 하방 편향에서 비롯되므로,
다음 단계는 `slow_trend / slow_momentum / volatility_penalty`의 가중치와 threshold를 shadow 실험으로 추가 완화하는 것이다.

### 10.10 2026-07-12 기준 최신 종합 결론

`2026-07-01 ~ 2026-07-10` 재집계와
`entry_score` 실측 로그를 함께 기준으로 보면,
이 문서의 초기 가설이었던
`core_risk_off slow floor` 완화 트랙은
이제 주 분석 축에서 내려놓는 것이 맞다.

핵심 이유는 다음과 같다.

1. `core_risk_off` v5 hydration 누락은 이미 해소됐다.
   같은 구간 `core` 97건 중
   `shadow_overall_score_v5 / shadow_slow_score_v5`는 `97/97`,
   active core `49/49`로 채워진다.
   따라서 지금 남은 문제를
   "관측 필드 누락 때문에 정확히 못 본다"로 돌릴 수는 없다.
2. 같은 구간 `core entry_score 평균`은 `0.1578`로 매우 낮다.
   `watch_from_entry_setup` 또는 `entry_score >= 0.52` 근접군은 `27건`,
   `0.52 <= entry_score < 0.65`는 `10건`뿐이다.
   즉 현재 주문 부재의 1차 병목은
   `risk_off` hard block보다
   `entry_score` 산출 자체의 하방 편향에 더 가깝다.
3. `near_buy_floor(0.52 <= entry_score < 0.65)` 10건 기준
   `risk_off_penalty=-0.15` 제거 시 `10/10`이 BUY floor `0.65`를 넘지만,
   `strategy_alignment(+0.05)`만으로는 `0/10`,
   `relative_activity_bonus` 최대치로도 `5/10`만 넘는다.
   따라서 현재 `entry_score` 하방 편향의 직접 구조는
   `risk_off_penalty` 1차 억제,
   `strategy / activity` 2차 억제로 읽는 편이 맞다.
   다만 이것은 즉시 완화 근거가 아니라
   구조 분해 결과로만 사용해야 한다.

#### 10.10.1 단순 완화안 No-Go 재확인

다음 broad / core 축 shadow formula는 모두
`최고 기대수익률` 기준에서 기각 상태를 유지한다.

| formula | count | T+1 | T+3 | T+5 | 판정 |
| --- | ---: | ---: | ---: | ---: | --- |
| `SF1_broad_remove_risk_off_near_buy_floor` | 10 | `-1.4160%` | `-5.2937%` | `-8.4620%` | `No-Go` |
| `SF2/SF3 core 축소안` | 4 | n/a | `-8.4906%` | `-16.9434%` | `No-Go` |
| `fast_score >= -0.12` 단일 필터 | 17 | `+0.0883%` | `-3.1981%` | `-3.9202%` | `No-Go` |

정리하면 다음과 같다.

- `risk_off_penalty`를 단독으로 제거하는 완화는 금지 유지가 맞다.
- `buy_candidate_threshold`를 단순히 내리는 것도 금지 유지가 맞다.
- `ranking_score`를 조금 더 높게 요구하거나,
  `entry_score` 상단 근접군을 빠르게 BUY로 승격하는 것도
  현재 데이터에서는 기대수익률 개선 근거가 없다.

#### 10.10.2 현재까지 남은 최선의 shadow-watch lane

최근 추가 실측에서 broad / core 완화안이 모두 꺾인 뒤,
상대적으로 가장 나은 lane은
아래 협소 조합으로 수렴한다.

- `market_overlay`
- `relative_activity_bonus 없음`
- `fast_score -0.12 ~ -0.05`

교차 집계 기준:

| bucket | count | T+3 평균 | T+5 평균 | 판정 |
| --- | ---: | ---: | ---: | --- |
| `market_overlay + no_rel_bonus + fast -0.12~-0.05` | 4 | `+0.8455%` | `+3.4324%` | `Shadow-Watch` |
| `market_overlay + no_rel_bonus + fast -0.20~-0.12` | 14 | `-6.3110%` | `-9.5145%` | `No-Go` |
| `market_overlay + no_rel_bonus + fast < -0.20` | 7 | `-7.3044%` | `-10.0692%` | `No-Go` |
| `market_overlay + rel_bonus + fast -0.12~-0.05` | 3 | `-9.4574%` | `-9.6531%` | `No-Go` |

즉, 현재 살아남는 분리축은
`entry_score` 숫자 자체보다는
`source lane + fast band + relative activity state` 조합이다.

추가 내부 분해 기준으로도
협소 lane 안에서 `ranking_score`는 좋은 분리축이 아니고,
`return_3m_pct` 및 `price_vs_sma_60_pct` 같은
중기 추세 강도가 설명력을 더 가진다.

| split | count | T+3 평균 | T+5 평균 | 해석 |
| --- | ---: | ---: | ---: | --- |
| `return_3m_pct >= 100` | 3 | `+3.6988%` | `+6.9099%` | 강한 중기 추세 표본만 남기면 개선 |
| `return_3m_pct < 100` | 1 | `-7.7143%` | `-7.0000%` | 약한 추세 표본은 손실 |
| `price_vs_sma_60_pct >= 50` | 3 | `+3.6988%` | `+6.9099%` | SMA60 대비 강한 상방 괴리 표본 우수 |
| `ranking_score >= 0.59` | 2 | `-6.2780%` | `+0.8203%` | ranking 상단은 좋은 분리축이 아님 |

#### 10.10.3 SF10 / SF11 / SF12 상태

현재까지 가장 좁고 성과가 나아진 shadow formula는
실질적으로 같은 3개 row로 수렴하는
`SF10 / SF11 / SF12`다.

| formula | count | T+1 | T+3 | T+5 | MFE3 | MAE3 | 판정 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `SF10_market_no_rel_fast_ge_-0.12_ret3m_ge_100` | 3 | `+2.7137%` | `+3.6988%` | `+6.9099%` | `+11.4974%` | `-2.8778%` | `Shadow-Watch` |
| `SF11_market_no_rel_fast_ge_-0.12_price_vs_sma60_ge_50` | 3 | `+2.7137%` | `+3.6988%` | `+6.9099%` | `+11.4974%` | `-2.8778%` | `Shadow-Watch` |
| `SF12_market_no_rel_fast_ge_-0.12_ret3m_ge_100_and_price_vs_sma60_ge_50` | 3 | `+2.7137%` | `+3.6988%` | `+6.9099%` | `+11.4974%` | `-2.8778%` | `Shadow-Watch` |

다만 이 결과는 여전히 소표본이며,
실제 전환력은 아직 열리지 않았다.

- `candidate -> selected -> would_buy -> submitted`
  실전 전환은 아직 `0` 상태다.
- 따라서 이 lane은
  "실행 후보"가 아니라
  "다음 추가 관측의 최우선 shadow-watch 대상"으로만 유지한다.

#### 10.10.4 현재 시점의 운영 결론

이 문서의 최신 결론을 운영 관점으로 정리하면 다음과 같다.

1. `core_risk_off` threshold 완화 트랙은 중단 상태를 유지한다.
2. 현재 1차 병목은 `entry_score` 하방 편향이며,
   특히 `risk_off_penalty + high_volatility + 음수 fast_score` 결합이 핵심 억제 구조다.
3. 다만 이 억제 구조를 완화하는 broad formula는
   모두 후행 수익률 기준 `No-Go`다.
4. 현재 남은 유의미한 shadow lane은
   `market_overlay + no_rel_bonus + fast -0.12~-0.05`
   위에 중기 추세 강도 조건을 얹은 `SF10~SF12`뿐이다.
5. 그마저도 표본이 `3건`에 불과하므로,
   authoritative 승격이나 threshold 조정은 아직 금지다.

#### 10.10.5 다음 우선 분석 과제

이후 분석은 `slow floor 완화`가 아니라
다음 방향으로 이동해야 한다.

1. `entry_score` 산출식 내부에서
   `risk_off_penalty`, `fast_score`, `high_volatility`,
   `strategy_alignment`, `relative_activity_bonus`가
   어떤 조합으로 하방 편향을 만드는지
   component 수준으로 더 직접 분해할 것
2. `watch_from_entry_setup` 및 `entry_score >= 0.52` 근접군을 대상으로
   `candidate -> selected -> would_buy -> submitted`
   전환력이 실제로 열리는 lane이 있는지 누적 관측할 것
3. `SF10~SF12`는 신규 완화안이 아니라
   `Shadow-Watch` lane으로만 유지하면서
   추가 `T+3 / T+5 / MFE / MAE`를 누적할 것
4. 실측 수익률 증명 없이
   `buy_candidate_threshold` 또는 `core_risk_off` 기준을
   직접 내리는 변경은 금지 유지할 것
