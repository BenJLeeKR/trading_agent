# `core_risk_off_floor_v5_report` 실측 비교 분석

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

### 10.5 active 35건의 직접 차단 사유

`core_risk_off_floor_v5_diagnostics` 기준:

| blocking reason | sample_count |
| --- | ---: |
| `overall_below_mild_floor` | 28 |
| `overall_missing` | 7 |

즉, 현재 남은 병목의 본체는 `overall_missing`이 아니라
`overall_below_mild_floor` 28건이다.

다만 이 28건의 `overall_v5` 하방 편향은 다시 `slow_score_v5` 하방 편향에서 비롯되므로,
다음 단계는 `slow_trend / slow_momentum / volatility_penalty`의 가중치와 threshold를 shadow 실험으로 추가 완화하는 것이다.
