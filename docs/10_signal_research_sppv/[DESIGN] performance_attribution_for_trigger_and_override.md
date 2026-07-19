# Trigger / Override Performance Attribution 설계

> 작성일: 2026-06-16
>
> 목적:
> deterministic trigger와 AI override가
> 실제 성과에 어떻게 기여했는지를
> `replay 가능`, `운영 관찰 가능`, `백엔드 deterministic 우선` 원칙 아래에서
> 단계적으로 측정하기 위한 설계를 정의한다.

## 1. 배경

현재까지 이미 확보된 기반은 다음과 같다.

- `signal_feature_snapshot` 계산/저장
- `market_regime / strategy_selection / portfolio_allocation`
- `deterministic_trigger`
- `candidate_vs_final`
- `candidate alignment diagnostics`
- `trigger execution attribution`

즉, 이제는 다음 질문을 다뤄야 한다.

1. 어떤 candidate가 실제 주문/체결로 이어졌는가
2. 어떤 override가 실행 전환율을 높이거나 낮췄는가
3. 어떤 override가 실제 기대수익률 개선에 기여했는가
4. 어떤 trigger bucket이 성과가 나쁜데도 계속 살아 있는가

다만 현재 데이터 모델에서는
`trigger → order → fill` 경로는 비교적 직접 추적 가능하지만,
`trigger → realized pnl`은 아직 완전하게 귀속하기 어렵다.

이유:

- 현재 `trade_decisions`는 decision truth다.
- `order_requests / broker_fill_snapshots / execution_attempts`는 execution truth다.
- 하지만 `포지션 청산 단위의 realized pnl attribution`은
  개별 trade decision 또는 candidate bucket에 완전히 귀속되도록
  아직 모델링되어 있지 않다.

따라서 V1은
`execution attribution`과 `performance attribution`을 분리해야 한다.

---

## 2. 설계 원칙

### 2.1 deterministic backend 우선

성과 attribution 계산은 LLM이 아니라 백엔드 집계 로직이 authoritative 해야 한다.

금지:

- LLM이 order/fill/PnL attribution을 계산하는 구조
- prompt 출력에서 성과 원인 분석을 truth source로 삼는 구조

허용:

- DB snapshot / order / fill / decision metadata를 이용한 deterministic 집계

### 2.2 live-safe 관점 유지

paper 환경이어도 live와 동일하게 취급한다.

따라서 attribution은
운영 안전성에 영향을 주지 않는 read-only 집계로 먼저 도입해야 한다.

### 2.3 execution attribution과 realized pnl attribution 분리

현재 바로 가능한 것:

- decision → order 생성 여부
- decision → filled 여부
- bucket별 execution conversion

현재 추가 설계가 필요한 것:

- decision / candidate / override 단위 realized pnl
- holding period 종료 후 attribution close-out
- partial fill / scale-out / multi-entry consolidation

### 2.4 source of truth 고정

V1에서 사용할 source는 아래로 고정한다.

- decision metadata truth:
  `trading.trade_decisions.decision_json.candidate_vs_final`
- order truth:
  `trading.order_requests`
- execution status truth:
  `trading.execution_attempts`
- fill truth:
  `trading.broker_fill_snapshots`
- account/position-level performance truth:
  기존 `performance_summary` / `performance_history` 계산 경로

---

## 3. Attribution 단계 정의

## 3.1 Stage A — Candidate Coverage

질문:

- 최근 decision 중 몇 %가 `candidate_vs_final`을 보유하는가
- 어떤 source_type에서 candidate 누락이 발생하는가

핵심 지표:

- `candidate_tracked_count`
- `candidate_coverage_rate`
- `source_type x candidate_missing_count`

현재 상태:

- 이미 일부 API로 확인 가능

## 3.2 Stage B — Execution Attribution

질문:

- 어떤 `candidate_intent`가 실제 주문으로 이어졌는가
- 어떤 `alignment_status`가 체결 전환율이 높은가

핵심 지표:

- `decision_to_order_rate`
- `decision_to_fill_rate`
- `alignment_status x order_conversion_rate`
- `candidate_intent x fill_conversion_rate`

현재 상태:

- `GET /performance-trigger-attribution`로 1차 확보됨

## 3.3 Stage C — Mark-to-Market Proxy Attribution

질문:

- 특정 bucket에서 생성된 decision이
  이후 일정 기간 동안 포지션/체결 성과와 어떤 방향 상관을 보이는가

V1 정의:

- 완전한 realized pnl이 아니라
  `post-decision performance proxy`를 먼저 도입한다.

예시:

- decision 후 `T+1`, `T+3`, `T+5` 기준 종가 수익률
- buy candidate의 후행 수익률
- sell / reduce candidate의 이후 하락 회피율

장점:

- 현재 포지션 close model이 완전하지 않아도 집계 가능
- trigger threshold 조정 실험에 바로 활용 가능

주의:

- 이는 `order execution performance`가 아니라
  `decision quality proxy`다

### 3.3a 2026-06-23 ~ 2026-07-01 임계값 실증 검증 메모

2026-07-01에 현재 `signal_feature`와 `deterministic_trigger`
임계값이 `최고 기대수익률` 목표에 부합하는지 1차 실증 검증을 수행했다.

검증 방식:

- `trade_decisions`에서 2026-06-23 이후 decision을 조회
- 중복 cycle 영향을 줄이기 위해
  `symbol + trade_date`별 첫 decision만 사용
- 후행 성과를 계산할 수 있는 2026-06-23 ~ 2026-06-30 decision을 평가 표본으로 사용
- KIS 일봉으로 T+1 / T+3 종가 수익률과 T+3 MFE / MAE를 계산
- 표본:
  - 57개 symbol
  - 186개 symbol-day

주요 결과:

- `BUY_CANDIDATE`와 `entry_score >= 0.65`는 0건이었다.
- `entry_score`와 T+3 수익률의 상관은 약 `-0.21`이었다.
- `0.55 <= entry_score < 0.65` 구간은
  T+3 평균 수익률이 약 `-3.56%`였다.
- 따라서 `buy_candidate_threshold`를 단순 하향하는 것은
  현재 표본 기준으로 기대수익률 개선 근거가 약하다.
- `WATCH` 최종 decision은 T+3 평균 약 `+0.88%`였지만,
  raw deterministic `PRIMARY_WATCH` bucket은 T+3 평균 약 `-0.71%`였다.
  이는 `WATCH` 후보를 넓은 완충 bucket으로 쓰면
  후보 품질이 떨어질 수 있음을 뜻한다.
- `eligibility_core_risk_off_ranking_blocked` bucket은
  T+3 평균 약 `+3.16%`, hit rate 약 `72.7%`로
  과도 차단 가능성이 있다.
- `event_overlay` bucket은
  T+1 평균 약 `+3.40%`, T+3 평균 약 `+2.38%`,
  hit rate 약 `73.7%`로
  우선순위와 후보 전환 비중을 높일 근거가 있다.

이 결과의 설계 반영:

1. `buy_candidate_threshold`는 바로 낮추지 않는다.
2. `watch_candidate_threshold=0.45`는
   상향 또는 top-k projection 방식으로 재설계한다.
3. `eligibility_core_risk_off_ranking_blocked`는
   hard block 대신 penalty + 제한적 top-k 방식의 shadow 실험 대상으로 둔다.
4. `event_overlay`는 source bonus 또는 별도 event top-k lane으로 평가한다.

주의:

- 이번 검증은 realized PnL attribution이 아니라
  post-decision return proxy다.
- KIS 일봉을 직접 조회해 계산했으므로,
  운영 반복 검증용으로는 별도 price history cache 또는
  `performance-trigger-proxy-attribution` 구현이 필요하다.

현재는 반복 검증용 1차 경로로
[`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)
를 추가했다.

- `symbol + trade_date`별 첫 decision 기준 추출
- KIS 일봉으로 T+1 / T+3 / T+5 후행 수익률 계산
- T+3 / T+5 기준 MFE / MAE 계산
- `primary_candidate`, `source_type`, `eligibility_reason`별 집계 출력

즉, `12-d`의 첫 체크리스트인
`repeatable script 또는 API`는 현재 스크립트 경로로 닫혔고,
후속으로 API 승격이 필요하면 같은 계산 계약을 재사용하면 된다.

추가로 스크립트는 아래 shadow 비교 섹션도 함께 출력한다.

- `watch_projection_items`
  - `legacy_watch_only`
  - `legacy_and_shadow_watch`
  - `shadow_watch_only`
  - `neither_watch`
- `core_risk_off_shadow_items`
  - `shadow_would_pass`
  - `shadow_blocked`
  - `inactive`
- `event_overlay_shadow_items`
  - `shadow_would_pass`
  - `shadow_blocked`
  - `inactive`

이로써 `12-d`에서 정의한
`WATCH top-k + minimum floor`,
`core risk-off shadow penalty`,
`event_overlay shadow lane`
세 변경안을 동일 기간 / 동일 표본에서
후행 수익률 proxy 기준으로 동시에 비교할 수 있다.

### 3.3.1 `core_risk_off_floor_diagnostics` 추가 설계

배경:

- `core_risk_off_floor_items`만으로는
  `mild_relax / moderate_relax` 표본이 왜 0인지 알 수 없다.
- 실제 bucket은
  [`src/agent_trading/services/deterministic_trigger_engine.py`](../src/agent_trading/services/deterministic_trigger_engine.py)의
  `_classify_core_risk_off_shadow_floor_bucket(...)`에서
  `overall / slow / entry_score / ranking_score / activity / strategy`
  6개 축으로 결정된다.
- 따라서 장후 attribution에는
  bucket 결과뿐 아니라
  bucket 진입 직전의 탈락 분해 정보가 함께 있어야 한다.

목표:

1. `mild_relax / moderate_relax / deep_negative`의 표본 수 비교
2. `mild_relax / moderate_relax` 미진입 원인의 분해
3. 각 탈락군의 후행 수익률 proxy 비교
4. 이후 authoritative 완화 여부 판단 근거 확보

#### 출력 JSON 계약

[`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)
payload에 아래 섹션을 추가한다.

1. `core_risk_off_floor_diagnostics`
   - `sample_count`
   - `active_sample_count`
   - `bucket_counts`
   - `overall_band_items`
   - `slow_band_items`
   - `moderate_gate_items`
   - `blocking_reason_items`
   - `bucket_path_items`
   - `samples`

2. `core_risk_off_floor_diagnostics.samples`
   - 목적:
     운영자가 개별 symbol-day 레코드의 진입/탈락 경로를
     직접 검토할 수 있게 한다.
   - 필드:
     - `trade_date`
     - `symbol`
     - `source_type`
     - `core_risk_off_active`
     - `shadow_floor_bucket`
     - `shadow_overall_score`
     - `shadow_slow_score`
     - `shadow_entry_score`
     - `shadow_ranking_score`
     - `shadow_overall_pass`
     - `shadow_slow_pass`
     - `shadow_signal_pass`
     - `shadow_activity_pass`
     - `shadow_strategy_pass`
     - `shadow_entry_observe_pass`
     - `shadow_topk_candidate`
     - `shadow_topk_selected`
     - `overall_band`
     - `slow_band`
     - `moderate_gate_bucket`
     - `blocking_reason`
     - `t1_return_pct`
     - `t3_return_pct`
     - `t5_return_pct`

#### 진단용 파생 분류 정의

1. `overall_band`
   - `strict_non_negative`
     - `overall >= 0.0`
   - `mild_window`
     - `-0.10 <= overall < 0.0`
   - `moderate_window`
     - `-0.25 <= overall < -0.10`
   - `deep_negative`
     - `overall < -0.25`
   - `missing`
     - `overall is None`

2. `slow_band`
   - `strict_non_negative`
     - `slow >= -0.05`
   - `mild_window`
     - `-0.15 <= slow < -0.05`
   - `moderate_window`
     - `-0.25 <= slow < -0.15`
   - `deep_negative`
     - `slow < -0.25`
   - `missing`
     - `slow is None`

3. `moderate_gate_bucket`
   - `moderate_ready`
     - moderate relax 추가 gate까지 모두 통과
   - `entry_below_0_12`
   - `ranking_below_0_26`
   - `activity_blocked`
   - `strategy_blocked`
   - `signal_window_miss`
   - `inactive`

4. `blocking_reason`
   - active row에 대해
     floor bucket이 왜 해당 위치에 머물렀는지
     우선순위 1개 reason으로 축약한다.
   - 우선순위:
     1. `inactive`
     2. `overall_missing`
     3. `slow_missing`
     4. `overall_below_mild_floor`
     5. `slow_below_mild_floor`
     6. `entry_below_0_12`
     7. `ranking_below_0_26`
     8. `activity_blocked`
     9. `strategy_blocked`
     10. `mild_relax_pass`
     11. `moderate_relax_pass`
     12. `strict_pass`

#### 집계 항목 정의

1. `bucket_counts`
   - `strict_pass / mild_relax / moderate_relax / deep_negative / unknown / inactive`

2. `overall_band_items`
   - `overall_band` 기준 aggregate
   - 각 bucket별
     `sample_count`, `t1/t3/t5`, `positive_t3_hit_rate`

3. `slow_band_items`
   - `slow_band` 기준 aggregate

4. `moderate_gate_items`
   - `moderate_gate_bucket` 기준 aggregate
   - `moderate_relax` 표본이 없는 원인이
     `entry / ranking / activity / strategy` 중 무엇인지 확인

5. `blocking_reason_items`
   - `blocking_reason` 기준 aggregate
   - 완화 우선순위를 직접 정하는 핵심 지표

6. `bucket_path_items`
   - `overall_band + slow_band + moderate_gate_bucket`를
     결합한 문자열 bucket
   - 예:
     - `mild_window|mild_window|signal_window_miss`
     - `moderate_window|moderate_window|activity_blocked`
     - `strict_non_negative|strict_non_negative|moderate_ready`

#### 코드 수정안

대상 파일:

1. [`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)
2. [`src/agent_trading/services/trigger_proxy_attribution.py`](../src/agent_trading/services/trigger_proxy_attribution.py)
3. [`tests/services/test_trigger_proxy_attribution.py`](../tests/services/test_trigger_proxy_attribution.py)
4. [`tests/scripts/test_run_ops_scheduler.py`](../tests/scripts/test_run_ops_scheduler.py)

1. `scripts/analyze_trigger_proxy_attribution.py`
   - `_load_first_symbol_day_decisions()`에서
     `core_risk_off_experiment` payload를 이미 읽고 있으므로,
     추가 DB schema 변경은 필요 없다.
   - `_run(...)` 내부에서
     `enriched_rows` 생성 후 아래 helper 호출을 추가한다.
     - `core_risk_off_floor_diagnostic_rows = build_core_risk_off_floor_diagnostic_rows(enriched_rows)`
     - `core_risk_off_floor_diagnostics = build_core_risk_off_floor_diagnostics_report(enriched_rows)`
   - payload에 아래 키를 추가한다.
     - `core_risk_off_floor_diagnostics`
     - `core_risk_off_floor_diagnostic_items`
       필요 시 `samples` 외 row 단위 전체 aggregate bucket용 보조 출력

2. `trigger_proxy_attribution.py`
   - helper 추가:
     - `_classify_overall_band(row)`
     - `_classify_slow_band(row)`
     - `_classify_core_risk_off_moderate_gate(row)`
     - `_classify_core_risk_off_blocking_reason(row)`
     - `build_core_risk_off_floor_diagnostic_rows(rows)`
     - `build_core_risk_off_floor_diagnostics_report(rows)`
   - `build_core_risk_off_floor_diagnostic_rows(rows)`는
     각 row에 아래 파생 필드를 붙인다.
     - `core_risk_off_active`
     - `shadow_floor_bucket`
     - `shadow_overall_score`
     - `shadow_slow_score`
     - `shadow_entry_score`
     - `shadow_ranking_score`
     - `shadow_overall_pass`
     - `shadow_slow_pass`
     - `shadow_signal_pass`
     - `shadow_activity_pass`
     - `shadow_strategy_pass`
     - `shadow_entry_observe_pass`
     - `shadow_topk_candidate`
     - `shadow_topk_selected`
     - `overall_band`
     - `slow_band`
     - `moderate_gate_bucket`
     - `blocking_reason`
     - `bucket_path`
   - `build_core_risk_off_floor_diagnostics_report(rows)`는
     위 파생 row를 기반으로
     `build_trigger_proxy_aggregate_items(...)`를 재사용해
     각 diagnostic bucket을 집계한다.

3. `tests/services/test_trigger_proxy_attribution.py`
   - 추가 테스트:
     - `overall_band` 분류 경계
     - `slow_band` 분류 경계
     - `moderate_gate_bucket` 분류 우선순위
     - `blocking_reason` 우선순위
     - diagnostics report가
       `mild_relax / moderate_relax / deep_negative` 외
       `entry_below_0_12`, `activity_blocked` 같은
       하위 원인 bucket을 제대로 집계하는지

4. `tests/scripts/test_run_ops_scheduler.py`
   - 현재 scheduler summary는
     `core_risk_off_floor_report`까지만 읽는다.
   - 장후 운영 요약에 바로 노출할 최소 metric만 추가한다.
     - `core_risk_off_floor_unknown_count`
     - `core_risk_off_floor_moderate_gate_activity_blocked_count`
     - `core_risk_off_floor_moderate_gate_ranking_below_0_26_count`
   - 단, 이 단계에서는 full diagnostics를
     `logs/trigger_proxy_attribution_YYYY-MM-DD.json`에서 읽고,
     scheduler summary에는 핵심 count만 올린다.

#### 운영 해석 기준

1. `mild_relax=0`, `moderate_relax=0`이면서
   `overall_band=mild_window`가 충분하면
   - slow floor 또는 moderate gate가 병목이다.

2. `moderate_window` 표본이 충분한데
   `moderate_gate_bucket=ranking_below_0_26`이 많으면
   - ranking floor 완화 검토 대상이다.

3. `activity_blocked`가 대부분이면
   - floor 완화보다
     `low_relative_activity` 또는
     `shadow_activity_min` 재검토가 먼저다.

4. `strategy_blocked`가 대부분이면
   - strategy selection과
     core risk-off admissible strategy 집합 불일치 문제다.

즉, `core_risk_off_floor_diagnostics`는
단순 관측 추가가 아니라
다음 authoritative 완화의 순서를 정하기 위한
진단 계층이다.

#### 2026-07-06 ~ 2026-07-07 실측 해석

재집계 결과:

1. `2026-07-06`
   - `active_sample_count = 21`
   - `moderate_gate_items.signal_window_miss = 21`
   - `blocking_reason_items.overall_below_mild_floor = 14`
   - `blocking_reason_items.overall_missing = 7`
2. `2026-07-07`
   - `active_sample_count = 28`
   - `moderate_gate_items.signal_window_miss = 28`
   - `blocking_reason_items.overall_below_mild_floor = 21`
   - `blocking_reason_items.overall_missing = 7`

판단:

1. 현재 `mild_relax / moderate_relax = 0`의 주원인은
   `entry_score`, `ranking_score`, `activity`, `strategy`가 아니다.
2. active row가 전부
   `overall / slow` floor 이전 단계에서 멈춘다.
3. 따라서 다음 실험 우선순위는
   `moderate gate` 완화가 아니라
   `overall shadow floor` 완화다.

#### 다음 단계 설계안

1. authoritative 규칙은 유지한다.
   - `overall >= 0.0`
   - `slow >= -0.05`
   - `risk_off_exception_eligible` 계산 경로도 즉시 변경하지 않는다.

2. shadow 진단 전용 완화안은
   `overall`만 소폭 완화한다.
   - `mild_relax_v2`
     - `overall >= -0.15`
     - `slow >= -0.15`
   - `moderate_relax_v2`
     - `overall >= -0.20`
     - `slow >= -0.25`
     - `entry_score >= 0.12`
     - `ranking_score >= 0.26`
     - `activity_pass = true`
     - `strategy_pass = true`

3. `slow` 완화는 보류한다.
   - 현재 실측으로는 `overall` 병목이 더 크다.
   - `slow`까지 함께 풀면 원인 분리가 깨진다.

4. `entry / ranking / activity / strategy` 완화는 보류한다.
   - 아직 그 gate까지 내려가는 active 표본이 충분히 없다.

즉, 다음 실험은
`shadow floor v2`를 추가 관측해
`overall`만 완화했을 때
`mild_relax / moderate_relax` 표본이 실제로 생기는지부터
확인하는 순서가 된다.

추가로 `2026-07-08` 기준,
`v2` historical backfill 재집계 결과에서도
`2026-07-06`, `2026-07-07` active row는
여전히 `mild_relax=0`, `moderate_relax=0`이었다.

따라서 현행 설계는
`v2`를 authoritative로 승격하는 것이 아니라,
다음 shadow 실험으로 `v3`를 병렬 추가한다.

- `mild_relax_v3`
  - `overall >= -0.20`
  - `slow >= -0.15`
- `moderate_relax_v3`
  - `overall >= -0.25`
  - `slow >= -0.25`
  - `entry_score >= 0.12`
  - `ranking_score >= 0.26`
  - `activity_pass = true`
  - `strategy_pass = true`

핵심 해석:

1. `v3`도 과거 `2026-07-06`, `2026-07-07` 구간에서는
   표본 확장을 만들지 못했다.
2. 이는 floor 숫자 자체보다
   `overall_missing` 및 `deep_negative` 분포가
   더 큰 병목임을 뜻한다.
3. 따라서 다음 검증 포인트는
   `v3` 자체 승격 여부보다
   장후 신규 데이터에서 `shadow_floor_relax_v3_bucket`이
   실제로 채워지는지와,
   upstream feature/score 생성 품질을 함께 보는 것이다.

## 3.4 Stage D — Realized PnL Attribution

질문:

- 어떤 override가 실제 실현손익 개선에 기여했는가
- 어떤 candidate_intent bucket이 장기적으로 돈을 버는가

이 단계는 아래 선행조건이 필요하다.

1. entry/exit chain linkage 강화
2. partial fill / split exit 귀속 규칙 확정
3. realized pnl lot matching 정책 고정
4. closing trade가 어떤 opening decision cluster를 닫는지 정의

즉, D 단계는 지금 바로 구현 대상이 아니라
별도 설계/데이터 모델 정리가 선행되어야 한다.

---

## 4. V1에서 바로 구현할 범위

## 4.1 포함 범위

이번 단계 이후 바로 구현 가능한 범위는 아래다.

1. `candidate / override post-decision return proxy`
2. `alignment_status x T+N return proxy`
3. `candidate_intent x T+N return proxy`
4. `source_type x override_applied x T+N return proxy`

이때 기준 가격은
가능하면 `trade_decisions.created_at`에 가장 가까운
동일 일자 snapshot / 종가 기준으로 고정한다.

현행 구현에서는 위 범위를
`holding_profile / reverse_trade / probe_churn`
운영 리포트 관점으로 먼저 구체화했다.

- `GET /performance-holding-profile-attribution`
  - `holding_profile`별
    decision / order / fill 전환
  - 평균 `edge_after_cost_bps`
  - buy fill 이후 첫 sell fill을 close-out proxy로 본
    평균 보유시간 / 평균 수익률
  - `reverse_trade` / `probe_churn` /
    `holding_profile_guard` 차단 분포
  - 계좌 기준 `opposite fill churn` 빈도

즉, 완전한 realized pnl attribution 이전에
현재 데이터 모델에서 deterministic하게 계산 가능한
`closed-trade proxy attribution`
을 먼저 확보한 상태다.

## 4.2 제외 범위

이번 단계에서 제외한다.

1. realized pnl을 decision bucket에 직접 귀속하는 기능
2. lot-level cost basis 재계산
3. fill-level slippage attribution
4. broker fee/tax를 포함한 완전 execution alpha attribution

---

## 5. 제안 API 구조

## 5.1 `GET /performance-trigger-proxy-attribution`

목적:

- trigger / override가 후행 수익률 proxy에서 어떤 분포를 보이는지 조회

권장 파라미터:

- `account_id`
- `lookback_days`
- `horizon_days` (`1 | 3 | 5`)
- `source_type` optional

응답 핵심:

- `tracked_decision_count`
- `proxy_available_count`
- `alignment_items`
- `candidate_intent_items`
- `recent_negative_outlier_items`

bucket별 항목 예시:

- `decision_count`
- `avg_return_pct`
- `median_return_pct`
- `positive_rate`
- `negative_rate`

추가로 현재 운영 리포트용으로는
다음 endpoint가 먼저 구현되었다.

## 5.1a `GET /performance-holding-profile-attribution`

목적:

- `holding_profile`별 기대수익률 anchor와
  실제 close-out proxy 결과를 함께 본다.
- reverse/probe/holding-profile guard가
  churn을 얼마나 차단했는지 같은 창에서 확인한다.

핵심 응답:

- `holding_profile_items`
- `guardrail_items`
- `edge_outcome_items`
- `realized_opposite_fill_churn_count`

주의:

- 여기서의 보유기간/수익률은
  `buy fill -> 이후 첫 sell fill`
  기준의 deterministic proxy다.
- partial fill / multi-entry / scale-out을 완전히 귀속한
  realized pnl attribution은 아직 아니다.

## 5.2 추후 `GET /performance-trigger-realized-attribution`

이 API는 지금 바로 만들지 않는다.

선행 설계 완료 후 별도 추가한다.

---

## 6. 계산 기준

## 6.1 candidate_intent 분류

현재 저장된 `candidate_vs_final.candidate_intent`를 사용한다.

허용 값:

- `buy`
- `sell`
- `watch`
- `no_action`

## 6.2 alignment_status 분류

현재 저장된 값을 그대로 사용한다.

예:

- `matched`
- `downgraded`
- `upgraded`
- `suppressed`
- `promoted_from_no_action`
- `diverged`

## 6.3 후행 수익률 proxy 정의

buy 계열:

- decision 시점 기준 `T+N` 종가 수익률

sell / reduce 계열:

- `회피 성과` 관점으로 해석해야 한다
- 기본 식:
  `-(T+N return_pct)`

즉, 매도 후보 이후 가격이 하락할수록
sell proxy score는 좋아진다.

watch:

- 기본적으로 성과 계산 대상이 아니라
  관찰 bucket으로 분리한다
- V1에서는 수익률 집계는 하되
  점수화보다는 분포 관찰용으로만 사용한다

## 6.4 override 성과 해석

`override_applied=true`인 decision은
아래 두 관점으로 분리 본다.

1. execution 측면:
   - order/fill 전환율이 좋아졌는가
2. proxy return 측면:
   - 후행 수익률/회피 성과가 좋아졌는가

즉, override의 평가는
단일 지표가 아니라
`실행 전환 + 후행 성과`를 같이 봐야 한다.

---

## 7. 데이터 의존성

V1 proxy attribution이 성립하려면 아래가 필요하다.

1. `signal_feature_snapshots` 또는 일봉 시세 접근 경로
2. decision 시점과 가격 시계열을 연결하는 lookup
3. symbol/market 매핑 안정성

권장 source:

- KIS 일봉 기반으로 생성된 snapshot 입력 또는
  별도 저장된 price history cache

비권장:

- decision 시점마다 외부 API를 즉시 재호출하여 과거 수익률을 계산하는 방식

이유:

- replay 비결정성 증가
- 외부 rate limit 의존
- 운영/분석 일관성 저하

---

## 8. 권장 구현 순서

1. `performance-trigger-proxy-attribution` 설계/구현
2. signal feature snapshot 또는 price snapshot 기반 후행 수익률 lookup helper 추가
3. bucket별 `avg/median/positive_rate` 집계 추가
4. Admin/ops에서 최근 outlier decision 샘플 노출
5. 별도 문서:
   `realized_pnl_attribution_for_trigger_and_override`

---

## 9. 완료 기준

이번 설계 단계의 완료 기준:

1. execution attribution과 realized pnl attribution의 경계가 문서화되어 있다
2. 현재 구조에서 가능한 V1 proxy attribution 범위가 정의되어 있다
3. 다음 구현 API의 응답 shape가 합의되어 있다
4. `실현손익 귀속은 별도 단계`라는 점이 명확히 정리되어 있다

---

## 10. 최종 결론

현재 구조에서 바로 할 수 있는 최선은
`trigger/override가 실제 실행으로 얼마나 이어졌는가`
를 먼저 보고,
그 다음
`trigger/override가 이후 성과 proxy에서 어떤 결과를 냈는가`
를 deterministic하게 붙이는 것이다.

즉, 다음 단계는
곧바로 복잡한 realized pnl attribution으로 뛰어드는 것이 아니라,

- execution attribution
- post-decision return proxy attribution

의 2단 구조로 가는 것이 맞다.

이 방식이
현재 데이터 모델과 운영 안정성 제약을 지키면서도,
`기대수익률 최대화`를 위한 threshold 조정과 override 평가를
가장 빠르게 가능하게 하는 경로다.
