# Core Risk-Off Ranking Block 완화 Phase 1

> 작성일: 2026-07-01

## 1. 목적

`core_risk_off_ranking_blocked`가
현재 기대수익률 최대화 관점에서
과도 차단인지 실측 기반으로 재평가하고,
안전한 완화 경로를
`shadow -> top-k allow -> limited apply`
순서로 구체화한다.

## 2. 실측 요약

실측 구간:

- `2026-06-01` ~ `2026-07-01`
- `symbol + trade_date` 첫 decision 기준
- 총 `1034 symbol-day`

핵심 bucket:

- `eligibility_risk_off_block`
  - `93건`
  - `T+3 평균 약 -2.67%`
  - `T+5 평균 약 -3.04%`
  - `hit rate 약 32.5%`
- `eligibility_core_risk_off_ranking_blocked`
  - `28건`
  - `T+3 평균 약 +8.29%`
  - `hit rate 100%`
  - `T+3 MFE 약 +10.61%`
  - `T+3 MAE 약 -1.33%`
- `eligibility_low_relative_activity`
  - `49건`
  - `T+3 평균 약 -5.41%`
  - `T+5 평균 약 -8.17%`
  - `hit rate 약 18.9%`

결론:

1. `risk_off_block` 전체 해제는 부적절
2. `low_relative_activity`는 hard block 유지
3. 완화 실험은 `core_risk_off_ranking_blocked`로 한정

## 3. 채택안

### 3.1 authoritative path

- 기존 `hard_block_v1` 유지
- 장중 실주문 동작은 즉시 변경하지 않음

### 3.2 shadow path

- 새 shadow mode:
  `shadow_topk_exception_v2`
- 단순 penalty 실험 대신
  cycle-level 상대 순위 기반 top-k 예외 허용 구조 사용

## 4. shadow candidate 규칙

아래를 모두 만족할 때만
`shadow_topk_candidate=true`로 기록한다.

1. `source_type == "core"`
2. `risk_off + bearish_trend`
3. authoritative 결과에서
   `eligibility_core_risk_off_ranking_blocked` 포함
4. `overall >= 0.0`
5. `slow >= -0.05`
6. `preferred_strategy`가 허용 집합 포함
7. `max(volume_surge_ratio, turnover_surge_ratio) >= 1.10`
8. `ranking_score >= 0.22`

## 5. cycle top-k 규칙

정렬:

1. `ranking_score DESC`
2. `entry_score DESC`
3. `symbol ASC`

선정:

- `shadow_topk_cap = 2`
- 상위 `2개`만 `shadow_topk_selected=true`

기록 metadata:

- `shadow_group_size`
- `shadow_rank`
- `shadow_topk_selected`
- `shadow_rank_candidate_score`

## 6. 코드 수정안

### 6.1 per-symbol 엔진

파일:
- [`src/agent_trading/services/deterministic_trigger_engine.py`](../src/agent_trading/services/deterministic_trigger_engine.py)

수정:

- 기존 `shadow_penalty_v1` 상수 제거 또는 deprecated 처리
- `shadow_topk_exception_v2` metadata 생성
- `shadow_topk_candidate` 판정 로직 추가

### 6.2 batch projector

신규 파일:
- `src/agent_trading/services/core_risk_off_topk_projection.py`

역할:

- cycle 전체 assessment를 입력으로 받아
  `shadow_topk_selected` 계산

### 6.3 loop integration

반영 후보:

- `scripts/run_decision_loop.py`
- 또는 cycle aggregation을 담당하는 상위 orchestration layer

동작:

1. per-symbol deterministic trigger 계산
2. batch projector 호출
3. metadata merge
4. shadow 단계에서는 decision 행동 미변경

### 6.4 authoritative prepass 적용 현황

- `2026-07-01` 기준 `run_decision_loop.py`에
  same-cycle authoritative prepass가 반영되었다.
- 적용 순서:
  1. cycle 시작 시 `core` universe 대상 baseline deterministic trigger 계산
  2. `project_core_risk_off_topk_exceptions(...)`로 `shadow_topk_selected` 산출
  3. 선택된 symbol만 `request.metadata.deterministic_trigger_override`에
     `core_risk_off_topk_v1` payload 주입
  4. `DecisionOrchestratorService.assemble()`가 동일 cycle 안에서
     override를 읽어 deterministic trigger를 재평가
- 이 경로는 `ranking` hard block만 완화하고,
  아래 hard block은 그대로 유지한다.
  - `eligibility_low_average_volume`
  - `eligibility_low_turnover`
  - `eligibility_low_relative_activity`
  - `eligibility_participation_rate_blocked`
- 즉, `selected top-k`가 되더라도
  liquidity / turnover / participation / signal floor를 우회하지 않는다.

## 7. apply 단계 승격 조건

다음을 만족할 때만
`apply_core_risk_off_topk_v1` feature flag 승격 검토:

1. `shadow_topk_selected` bucket의
   T+3 / T+5 proxy가 계속 양호
2. 장중 BUY 후보 수가 과도하게 폭증하지 않음
3. EV gate 통과율이 의미 있게 개선
4. churn 증가가 제한적
5. low liquidity / participation block과 충돌하지 않음

## 7-A. `apply_core_risk_off_topk_v1` 구체 계약

### 7-A.1 목적

`shadow_topk_selected=true`로 검증된 `core` 후보만
제한적으로 `risk_off_exception_eligible=true`로 승격하여,
`risk_off_block` 및 `core_risk_off_ranking_blocked`의 일부를
정교하게 우회한다.

### 7-A.2 비목표

아래는 이 flag가 하지 않는다.

1. `risk_off` 구간 전체 BUY 허용
2. `low_relative_activity` 해제
3. `buy_candidate_threshold=0.65` 완화
4. `event_overlay` 경로 동시 변경

### 7-A.3 feature flag 형태

권장 런타임 스위치:

- `DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK=0|1`

기본값:

- `0`

즉, 기본은 shadow-only이며
운영자가 명시적으로 켜기 전에는 authoritative 동작이 바뀌지 않는다.

### 7-A.4 apply 승격 전제조건

아래를 모두 만족하는 종목만
`apply_core_risk_off_topk_v1` 적용 대상이다.

1. `source_type == "core"`
2. `core_risk_off_experiment.active == true`
3. `core_risk_off_experiment.shadow_topk_candidate == true`
4. `core_risk_off_experiment.shadow_topk_selected == true`
5. 현재 authoritative eligibility reasons에
   `eligibility_core_risk_off_ranking_blocked` 포함
6. `eligibility_low_relative_activity` 미포함
7. `eligibility_participation_rate_blocked` 미포함
8. `overall >= 0.0`
9. `slow >= -0.05`
10. 허용 strategy

### 7-A.5 apply 시 변경되는 것

`apply_core_risk_off_topk_v1=1`일 때,
위 전제조건을 만족하는 종목에 한해
다음만 바뀐다.

1. `risk_off_exception_eligible = true`
2. `core_risk_off_experiment.apply_ready = true`
3. metadata에 아래 추가
   - `risk_off_exception_eligible = true`
   - `risk_off_exception_path = "core_risk_off_topk_v1"`
   - `risk_off_exception_shadow_rank`
   - `risk_off_exception_shadow_group_size`

즉,
`expected_value_gate`와 pre-AI short-circuit이
이미 참조하는 `risk_off_exception_eligible` 경로를 재사용한다.

### 7-A.6 apply 시에도 바뀌지 않는 것

아래는 그대로 유지한다.

1. `buy_candidate_threshold = 0.65`
2. `low_relative_activity` hard block
3. `participation_rate` hard block
4. `negative overall/slow floor`
5. `event_overlay` 정책

즉, 이 flag는
`risk_off` 억제 장치 중에서도
`core_risk_off_ranking_blocked`만 부분 완화한다.

### 7-A.7 구현 위치

최종 적용 위치는
후처리 patch가 아니라
**AI 호출 전 deterministic prepass**다.

이유:

1. pre-AI short-circuit이 `eligibility_reasons`와
   `risk_off_exception_eligible`를 직접 참조한다.
2. `expected_value_gate`도 동일 필드를 참조한다.
3. cycle 종료 후 DB patch는 attribution용 shadow에는 충분하지만,
   같은 cycle의 실제 BUY/AI 경로를 바꾸지는 못한다.

현재 구현은 아래 순서로 반영되었다.

1. cycle 시작 시점 deterministic prepass
2. `core_risk_off_topk_projection`
3. request/assembled_context에 projection merge
4. `apply_core_risk_off_topk_v1=1`이면
   selected 후보만 `risk_off_exception_eligible=true`

### 7-A.8 롤아웃 순서

1. 장후 `core_risk_off_topk_items` 실측 검증
2. `shadow_topk_selected` bucket의 T+3/T+5 품질 재확인
3. 1일 `dry-run only`
4. 다음 1일 `submit on + limited monitor`
5. 이상 없으면 유지

### 7-A.9 성공 기준

1. `final_buy`가 소폭 회복되되 과도하게 폭증하지 않음
2. `risk_off_block` 전체 완화 없이도
   `core` missed opportunity 감소
3. `expected_value_gate` 통과율 악화 없음
4. churn / duplicate buy 증가 제한적

### 7-A.10 2026-07-01 ~ 2026-07-02 post-apply 실측

실측 구간:

- `2026-07-01` ~ `2026-07-02`
- `DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK=1`
- 운영 DB `trade_decisions`, `order_requests`,
  `order_submission_attempts` 기준

집계 결과:

1. 전체 decision row
   - 총 `1802`건
   - `core_risk_off_ranking_blocked` `508`건
2. `symbol + trade_date` 첫 decision 기준
   - 총 `42 symbol-day`
   - `core_risk_off_ranking_blocked` `13 symbol-day`
3. `shadow_topk_candidate`
   - `0건`
4. `shadow_topk_selected`
   - `0건`
5. `risk_off_exception_path`
   - `0건`
6. `final_buy`
   - `0건`
7. `order_requests`
   - `0건`
8. `accepted submit attempts`
   - `0건`

즉, 현재 구간에서는
`shadow_topk_selected -> risk_off_exception_path -> final_buy/submit`
전환율을 계산할 표본 자체가 없었다.

### 7-A.11 post-apply 실측 해석

핵심 해석:

1. `apply` flag는 켜져 있었지만
   실제 완화 경로는 한 번도 활성화되지 않았다.
2. 따라서 `core_risk_off_ranking_blocked` 감소량은
   현재 구간 기준 `0건`이다.
3. 완화 경로를 통한 BUY / submit이 없었으므로
   이 변경으로 인한 churn 부작용도
   현재 구간에서는 `0건`이다.

원인 분해:

1. `core_risk_off_ranking_blocked` `508`건 중
   `core_risk_off_experiment.active=true`는 `394`건이었다.
2. 그러나 `shadow_signal_pass=true`는 `0건`,
   `shadow_activity_pass=true`는 `55`건,
   `shadow_strategy_pass=true`는 `394`건이었다.
3. 즉, 현재 병목은 `strategy`가 아니라
   `signal floor` 쪽이다.
4. 같은 blocked row에서
   `max(ranking_score)=0.2798`,
   `max(entry_score)=0.0767`,
   `평균 max(relative activity)=0.8305`였다.
5. 현재 구간에서는
   shadow 후보 조건 중
   `overall/slow/signal` 계열이 먼저 전부 막히고 있어,
   `top-k allow`가 실제로 작동하기 전에
   후보군이 소거되고 있다.

### 7-A.12 현 시점 결론과 다음 단계

현 시점 결론:

1. `apply_core_risk_off_topk_v1` 자체가 churn을 유발했다고 볼 근거는 없다.
2. 반대로, 기대했던 `blocked 완화` 효과도 아직 실현되지 않았다.
3. 따라서 다음 단계는
   `top-k cap` 조정이 아니라
   `shadow_signal_pass` 산식과
   `overall/slow floor` 충돌 여부를 먼저 계측/점검하는 것이다.

우선 점검 순서:

1. `core_risk_off_ranking_blocked` 표본에서
   `shadow_signal_pass=false`를 만드는
   세부 하위 조건을 추가 계측
2. `overall >= 0.0`, `slow >= -0.05`,
   `entry_score` 하한 중
   어떤 조건이 실질 병목인지 분해
3. 병목이 확인되면
   `risk_off_block` 전체 완화가 아니라
   `core_risk_off_ranking_blocked` 한정
   `shadow_signal_pass` 기준만 소폭 완화 검토

### 7-A.13 1차 분해 결과와 신규 계측 필드

`2026-07-01 ~ 2026-07-02` `core_risk_off_ranking_blocked` 표본을
`decision_context.signal_feature_snapshot_id`로
`signal_feature_snapshots`에 조인해 재실측한 결과:

1. 총 `523` row
2. `overall >= 0.0`
   - `0건`
3. `slow >= -0.05`
   - `0건`
4. `overall >= 0.0 and slow >= -0.05`
   - `0건`
5. `entry_score >= 0.05`
   - `63건`
6. `shadow_signal_pass=true`
   - `0건`
7. `shadow_activity_pass=true`이지만
   `shadow_signal_pass=false`
   - `61건`
8. 평균
   - `overall_score ≈ -0.6558`
   - `slow_score ≈ -0.7987`
   - `entry_score ≈ 0.0232`
9. 최대
   - `overall_score = -0.525`
   - `slow_score = -0.39`
   - `entry_score = 0.0767`

해석:

1. 현 구간에서는 `entry_score`보다
   `overall/slow floor`가 훨씬 먼저 병목이다.
2. 즉, `shadow_signal_pass=false`의 주 원인은
   `entry_score 부족`이 아니라
   `overall < 0.0` 및 `slow < -0.05`다.
3. 따라서 다음 완화 검토는
   `top-k cap`보다 먼저
   `signal floor`의 구체 분해 데이터를 더 모은 뒤 진행해야 한다.

이를 위해 `core_risk_off_experiment` metadata에 아래 관측 필드를 추가했다.

- `shadow_overall_score`
- `shadow_slow_score`
- `shadow_entry_score`
- `shadow_overall_pass`
- `shadow_slow_pass`
- `shadow_entry_observe_min`
- `shadow_entry_observe_pass`
- `shadow_signal_fail_reasons`

주의:

- `shadow_entry_observe_*`는
  현재 authoritative gating이 아니라
  `entry_score` 충돌 여부를 장중 데이터에서 읽기 위한
  관찰용 필드다.
- 현재 기준으로
  `shadow_topk_candidate` 산식 자체는 바뀌지 않았다.

## 9. `overall/slow floor` shadow 완화안

### 9.1 배경

`2026-07-02` 실측 기준
`core_risk_off_ranking_blocked` 표본은
`ranking`과 `activity`보다
`overall/slow floor`에서 먼저 전부 막히고 있었다.

핵심 수치:

1. `shadow_signal_pass=true`
   - `0건`
2. `shadow_core_risk_off_overall_floor_blocked`
   - `135건`
3. `shadow_core_risk_off_slow_floor_blocked`
   - `135건`
4. `shadow_activity_pass=true`
   - `54건`

즉, 다음 단계는
`top-k cap` 조정이 아니라
`signal floor`를 어떤 범위까지 shadow에서 관측할지
먼저 고정하는 것이다.

### 9.2 목표

이번 단계의 목표는
`overall/slow floor`를 바로 완화하는 것이 아니라,
아래를 장중 실측 가능하게 만드는 것이다.

1. 현재 blocked 표본이
   `mild negative`인지
   `deep negative`인지 구분
2. `overall/slow floor`를 일부 완화했을 때
   실제로 top-k 후보가 생기는지 확인
3. churn 없이 기대수익률 개선 가능성이 있는
   `relax bucket`만 다음 apply 후보로 승격

### 9.3 비목표

이번 shadow 완화안은 아래를 하지 않는다.

1. `apply_core_risk_off_topk_v1`의 authoritative 조건 변경
2. `risk_off` 전체 BUY 허용
3. `low_relative_activity` hard block 해제
4. `buy_candidate_threshold=0.65` 완화
5. `event_overlay` lane 동시 변경

### 9.4 shadow floor bucket 정의

`core_risk_off_experiment` 안에
아래 관측 bucket을 추가하는 것을 기준안으로 한다.

#### bucket A. `shadow_floor_mild_relax_v1`

- 목적:
  현재 strict floor(`overall >= 0.0`, `slow >= -0.05`)는 못 넘지만,
  일반 negative floor보다 약간만 낮은 표본을 분리
- 조건:
  - `overall >= -0.10`
  - `slow >= -0.15`
- 해석:
  deterministic BUY eligibility의 기존 negative floor와
  충돌하지 않는 범위의 보수적 후보군

#### bucket B. `shadow_floor_moderate_relax_v1`

- 목적:
  strict floor는 못 넘지만,
  `mild`보다 한 단계 더 약한 signal을 분리
- 조건:
  - `overall >= -0.25`
  - `slow >= -0.25`
- 추가 제약:
  - `entry_score >= 0.12`
  - `ranking_score >= 0.26`
  - `shadow_activity_pass == true`
  - `shadow_strategy_pass == true`
- 해석:
  즉시 apply 대상이 아니라
  향후 missed opportunity가 반복될 때만
  검토할 관찰 bucket

#### bucket C. `shadow_floor_deep_negative_v1`

- 목적:
  완화 검토 대상 밖의 구간을 분리
- 조건:
  - bucket A/B 미충족
- 해석:
  이 구간은
  현 단계에서는 shadow top-k 후보로도 보지 않는다.

### 9.5 authoritative와 shadow의 경계

authoritative 경계는 그대로 유지한다.

1. strict signal floor
   - `overall >= 0.0`
   - `slow >= -0.05`
2. general negative floor
   - 기존 deterministic eligibility 규칙 유지
3. `risk_off_exception_eligible`
   - 현재처럼 `shadow_topk_selected + strict floor pass`일 때만 가능

즉, 이번 변경은
`candidate 생성 규칙 완화`가 아니라
`후보 관찰 bucket 분해`다.

### 9.6 metadata 계약

`core_risk_off_experiment`에 아래 필드를 추가하는 것을 기준안으로 한다.

1. `shadow_floor_bucket`
   - `strict_pass`
   - `mild_relax`
   - `moderate_relax`
   - `deep_negative`
2. `shadow_floor_relax_pass`
   - bucket A 또는 B 충족 여부
3. `shadow_floor_relax_reason_codes`
   - 예:
     - `shadow_core_risk_off_floor_mild_relax_pass`
     - `shadow_core_risk_off_floor_moderate_relax_pass`
     - `shadow_core_risk_off_floor_deep_negative`
4. `shadow_floor_relax_entry_min`
5. `shadow_floor_relax_ranking_min`

이미 반영된 필드와 결합해
아래를 row 단위로 바로 읽을 수 있게 한다.

1. strict floor 실패 사유
2. relax bucket 소속 여부
3. activity/strategy까지 통과했는지
4. top-k 후보가 될 잠재성이 있는지

### 9.7 코드 반영 기준

대상 파일:

- [`src/agent_trading/services/deterministic_trigger_engine.py`](../src/agent_trading/services/deterministic_trigger_engine.py)

추가 함수 기준안:

1. `_classify_core_risk_off_shadow_floor_bucket(...)`
   - 입력:
     - `overall`
     - `slow`
     - `entry_score`
     - `ranking_score`
     - `shadow_activity_pass`
     - `shadow_strategy_pass`
   - 출력:
     - `bucket`
     - `relax_pass`
     - `reason_codes`

2. `_build_core_risk_off_shadow_experiment_metadata(...)`
   - 기존 metadata에
     `shadow_floor_bucket`,
     `shadow_floor_relax_pass`,
     `shadow_floor_relax_reason_codes`
     병합

중요:

- `shadow_topk_candidate` 산식은
  다음 단계 전까지 그대로 유지
- 즉, bucket A/B로 분류되더라도
  아직 `shadow_topk_candidate=true`로 자동 승격하지 않는다

### 9.8 후속 실측 기준

하루 이상 장중 실측 후
아래를 확인한다.

1. bucket A `mild_relax` 표본 수
2. bucket B `moderate_relax` 표본 수
3. 각 bucket에서
   `activity_pass=true` 비율
4. 각 bucket에서
   `ranking_score`, `entry_score` 상위 표본 분포
5. 실제 후행 수익률 proxy가
   기존 `core_risk_off_ranking_blocked` 평균보다 나아지는지

### 9.9 승격 기준

authoritative 적용 후보는
우선 bucket A만 검토한다.

승격 전제:

1. `mild_relax` 표본이 최소 `20 symbol-day` 이상 누적
2. `activity_pass=true`와 동시 충족 표본이 존재
3. 후행 수익률 proxy가
   baseline blocked군보다 유의하게 개선
4. 동일 symbol 재진입 churn 징후가 증가하지 않음

bucket B는
bucket A가 충분히 검증된 뒤에만
검토한다.

## 8. 비채택안

### 8.1 risk_off 전체 해제

- 실측 기준 성과가 나쁘므로 비채택

### 8.2 low_relative_activity 완화

- 실측 기준 성과가 나쁘므로 비채택

### 8.3 penalty-only 완화

- 절대 점수 calibration 의존이 커서 비채택
- 현재 bucket 평균 score scale과 맞지 않음
