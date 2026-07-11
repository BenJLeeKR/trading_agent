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

- [ ] `slow_trend` 전용 shadow 버킷 명칭을 최종 고정했다
- [ ] `price_vs_sma_60_pct` 구간 경계를 코드/문서 기준으로 고정했다
- [ ] `trigger_proxy_attribution.py`에 `slow_trend_relax_candidate_band` 분류 helper를 추가했다
- [ ] sample row에 `slow_trend_relax_candidate_band`를 기록한다
- [ ] active/inactive 모두에서 예외 없이 bucket이 채워지는지 테스트했다
- [ ] 경계값(`-0.5`, `-2.5`, `-6.0`, `-12.0`) 테스트를 추가했다

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

- [ ] attribution payload에 `slow_trend_relax_candidate_items`를 추가했다
- [ ] attribution payload에 `slow_trend_relax_candidate_report`를 추가했다
- [ ] attribution payload에 `slow_trend_path_items`를 추가했다
- [ ] sample row에 `price_vs_sma_60_pct`를 노출했다
- [ ] sample row에 `return_3m_pct`를 함께 노출했다
- [ ] sample row에 `shadow_component_scores_v5.slow_trend`를 함께 노출했다
- [ ] sample row에 `shadow_component_scores_v5.slow_momentum`를 함께 노출했다
- [ ] report helper 테스트를 추가했다

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

- [ ] `slow_momentum` 관련 authoritative 완화는 적용하지 않았다
- [ ] `slow_momentum_band_items` 집계가 유지되는지 확인했다
- [ ] `return_3m_pct` 구간별 집계가 유지되는지 확인했다
- [ ] `momentum reason code`별 proxy 집계가 유지되는지 확인했다
- [ ] `slow_momentum moderate_negative` 표본 수를 일자별로 추적 가능하게 했다

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

- [ ] `shadow_relax_projection_candidate` 필드를 추가했다
- [ ] `shadow_relax_projection_selected` 필드를 추가했다
- [ ] `shadow_relax_projection_block_reason` 필드를 추가했다
- [ ] `shadow_relax_projection_would_buy` 필드를 추가했다
- [ ] shadow 완화 후보가 `WATCH`만 증가시키는지 구분 가능해졌다
- [ ] shadow 완화 후보가 실제 `BUY candidate`로 이어질 수 있는지 구분 가능해졌다
- [ ] projection 관련 집계 테스트를 추가했다

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

- [ ] 장후 `trigger_proxy_attribution` 배치가 새 집계 필드를 출력한다
- [ ] 장후 결과 JSON에 `slow_trend_relax_candidate_items`가 저장된다
- [ ] 장후 결과 JSON에 `slow_momentum_band_items`가 저장된다
- [ ] 장후 결과 JSON에 `slow_trend_band_items`가 저장된다
- [ ] 장후 결과 JSON에 `slow_component_path_items`가 저장된다
- [ ] 운영 요약에 `trend_moderate_candidate_count`가 남는다
- [ ] 운영 요약에 `trend_edge_deep_count`가 남는다
- [ ] 운영 요약에 `trend_deep_tail_count`가 남는다
- [ ] 운영 요약에 `shadow_relax_projection_selected_count`가 남는다

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

- [ ] 최소 3거래일 표본이 쌓였다
- [ ] 가능하면 5거래일 표본까지 확보했다
- [ ] `inactive` 대비 `trend_moderate_candidate`의 `T+1`을 비교했다
- [ ] `inactive` 대비 `trend_moderate_candidate`의 `T+3`을 비교했다
- [ ] `deep_negative` 대비 `trend_moderate_candidate`의 `T+1`을 비교했다
- [ ] `deep_negative` 대비 `trend_moderate_candidate`의 `T+3`을 비교했다
- [ ] `T+3 양수 비율`을 함께 비교했다
- [ ] `T+3 MFE / MAE`를 함께 비교했다
- [ ] 표본 수가 너무 적어 해석 불가한 bucket을 별도 표시했다
- [ ] churn 또는 저유동성 부작용 유무를 함께 점검했다

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

- [ ] 실측 기준선 문서를 최신 상태로 확인했다
- [ ] 변경 대상 파일 목록을 확정했다
- [ ] 기존 v5 진단 필드와 충돌 여부를 검토했다

### 단계 2. 계측 구현

- [ ] 작업 A 체크리스트를 모두 완료했다
- [ ] 작업 B 체크리스트를 모두 완료했다
- [ ] 작업 C 체크리스트를 모두 완료했다
- [ ] 작업 D 체크리스트를 모두 완료했다
- [ ] 작업 E 체크리스트를 모두 완료했다

### 단계 3. 로컬/테스트 검증

- [ ] 단위 테스트를 통과했다
- [ ] attribution 스크립트 수동 실행이 성공했다
- [ ] JSON 출력에 새 필드가 실제로 보인다

### 단계 4. 장후 실측 운영

- [ ] 첫 장후 배치에서 새 집계가 생성됐다
- [ ] 2거래일 연속 장후 배치가 정상 적재됐다
- [ ] 3거래일 누적 표본이 확보됐다

### 단계 5. 분석 및 판단

- [ ] 실측 검토 체크리스트를 모두 점검했다
- [ ] `trend_moderate_candidate`가 승격 후보인지 판단했다
- [ ] `slow_momentum`은 계속 관측만 유지할지 판단했다
- [ ] `deep_negative` 전체 완화 금지 원칙을 재확인했다

### 단계 6. 승격 또는 보류

- [ ] 승격 기준을 충족해 authoritative 설계 문서를 작성했다
- [ ] 또는 근거 부족으로 shadow-only 유지 결론을 기록했다
- [ ] 결론을 `[PRIORITY_MAP]`와 관련 분석 문서에 반영했다

## 8. 관련 문서

- [`plans/[PRIORITY_MAP] remaining_work_priority_map.md`](./%5BPRIORITY_MAP%5D%20remaining_work_priority_map.md)
- [`plans/[ANALYSIS] core_risk_off_floor_v5_report_measurement_2026-07-11.md`](./%5BANALYSIS%5D%20core_risk_off_floor_v5_report_measurement_2026-07-11.md)
- [`plans/[ANALYSIS] signal_backbone_slow_score_threshold_tuning_2026-07-09.md`](./%5BANALYSIS%5D%20signal_backbone_slow_score_threshold_tuning_2026-07-09.md)
- [`plans/[PLAN] core_risk_off_ranking_relaxation_phase1.md`](./%5BPLAN%5D%20core_risk_off_ranking_relaxation_phase1.md)
- [`plans/[DESIGN] deterministic_trigger_eligibility_and_ranking_v1.md`](./%5BDESIGN%5D%20deterministic_trigger_eligibility_and_ranking_v1.md)
