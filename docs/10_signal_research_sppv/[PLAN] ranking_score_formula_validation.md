# ranking_score 공식 검증 계획

작성일: 2026-07-28  
상태: [SPPV-2.122에서 갱신] §6 실행 체크리스트 전 항목 완료(진단·
분류까지, 완화안/코드 diff는 미착수 — SPPV-2.119~2.122 참고)

## 1. 문서 목적

이 문서는 `deterministic_trigger_engine.py`의 BUY용 `ranking_score`
공식이 현재 운영 데이터와 설계 목적에 맞는지 검증하기 위한 별도 계획
문서다.

이번 검증의 초점은 아래 4가지다.

1. `ranking_min_score=0.48` 임계치가 실제 분포에서 경계값으로 기능하는가
2. `entry_score`, `relative_activity`, `coverage_score`,
   `allocation_quality`, `regime_tailwind`, `strategy_alignment`
   6개 구성항목이 지금도 적절한가
3. 각 항목의 가중치(`0.55/0.10/0.20/0.10/0.03/0.02`)가 실제 설명력에
   비례하는가
4. 같은 축이 다른 BUY 차단 장치(`entry_score threshold`,
   `eligibility_low_relative_activity`, `risk_off+bearish_trend`
   hard gate 등)에서 중복 반영되어 과잉 차단을 만들고 있지는 않은가

## 2. 왜 지금 이 검증이 필요한가

최근 검증에서 아래 사실이 이미 확인됐다.

1. `core_risk_off_ranking_blocked` 모집단에서는 `raw_ranking_score`
   가 최근 3거래일/전체 이력 모두 `0.43~0.48` 구간에 **0건**이다.
2. `0.48`은 현재 데이터에서 "경계에 있는 좋은 후보를 조금만 더 받는
   선"이 아니라, 사실상 **도달 사례가 없는 상수**에 가깝다.
3. 실제 구현식은 설계 문서 초안식과 다르며, 코드가 먼저 굳고 문서가
   완전히 따라오지 못한 흔적이 있다.
4. `entry_score`, `relative_activity`, `coverage_score`, `regime`
   축은 ranking 안에서 한 번, eligibility 또는 candidate threshold에서
   또 한 번 반영되는 중복 구조가 존재한다.

따라서 지금 필요한 것은 숫자를 바로 낮추는 것이 아니라,
**무엇을 검증하고 무엇을 통과시키려는 공식인지부터 다시 닫는 작업**이다.

## 3. 현재 확인된 사실(출발점 고정)

### 3.1 실제 구현식

현재 BUY용 ranking 공식은 아래와 같다.

```python
ranking_score =
    0.55 * entry_score
    + 0.10 * relative_activity
    + 0.20 * coverage_score
    + 0.10 * allocation_quality
    + 0.03 * regime_tailwind
    + 0.02 * strategy_alignment
```

### 3.2 현재 남아 있는 미해결 질문

1. 왜 `slow_score`는 빠지고 `relative_activity`가 들어갔는가
2. 왜 `coverage_score`가 0.20처럼 큰 비중을 차지하는가
3. 왜 `regime_tailwind`와 `strategy_alignment`는 보조항으로만 남았는가
4. 왜 동일한 축이 ranking과 eligibility 양쪽에서 중복 반영되는가
5. 지금 모집단에서는 어떤 항목이 실제 변별력을 갖고, 어떤 항목은
   사실상 고정 바닥/고정 0으로만 작동하는가

## 4. 검증 범위

이번 트랙은 아래 4개 질문으로 분리한다.

### 4.1 트랙 A — 임계치 정합성

질문:

- `0.48`이 실제 분포에서 경계값 역할을 하는가
- 아니면 분포 바깥의 상시 봉쇄 상수인가

확인 항목:

- 최근 3거래일(KST) / 전체 이력 구간 분포
- `0.43~0.48`, `0.48 이상` 근접 표본 수
- 상위권 표본의 시간 집중도와 독립 표본성

### 4.2 트랙 B — 구성항목 적절성

질문:

- 6개 구성항목이 지금도 필요한가
- 어떤 항목은 빠져도 되고, 어떤 항목은 빠지면 안 되는가

확인 항목:

- 각 항목의 분포(평균/중앙값/최솟값/최댓값)
- 항목별 실제 변별력 유무
- 고정값처럼만 동작하는 항목 존재 여부

### 4.3 트랙 C — 가중치 적정성

질문:

- 현재 가중치가 실제 설명력 순서와 맞는가
- `entry_score` 중심 구조가 과도한가

확인 항목:

- 항목별 기여도 분해
- 상위 표본/실패 표본 비교
- 문서 초안식 vs 실제 구현식 차이

### 4.4 트랙 D — 다른 BUY 차단 장치와의 중복 적정성

질문:

- ranking에서 이미 본 항목을 eligibility나 threshold에서 다시 막는가
- 그 중복이 방어에 필요한가, 아니면 과잉 처벌인가

확인 항목:

- `entry_score`:
  `buy_candidate_threshold(0.65)` + ranking 가중치 중복
- `relative_activity`:
  ranking 가중치 + `eligibility_low_relative_activity` 하드 차단 중복
- `coverage_score`:
  ranking 가중치 + `eligibility_low_feature_coverage` 중복
- `regime`:
  `entry_score risk_off_penalty` + `regime_tailwind` + core risk-off hard gate
  중복
- `strategy_alignment`:
  `entry_score bonus` + ranking 가중치 중복

## 5. 검증 방법

### 5.1 코드 확인

- `src/agent_trading/services/deterministic_trigger_engine.py`
- 관련 함수:
  - `_build_buy_ranking_score`
  - `_build_entry_score`
  - `_assess_buy_eligibility`
  - `_assess_core_risk_off_buy_guard`
  - `_build_relative_activity_score`
  - `_build_feature_coverage_score`

### 5.2 문서 이력 확인

- `[DESIGN] deterministic_trigger_eligibility_and_ranking_v1.md`
- `[DESIGN] regime_conditional_entry_signal_v1.md`
- `[DESIGN] signal_predictive_power_validation.md`
- `[ANALYSIS] foundational_design_review_objective_alignment.md`

### 5.3 데이터 확인

- `trade_decisions.decision_json`
- `deterministic_trigger.metadata.core_risk_off_experiment.*`
- 최근 3거래일(KST) + 전체 이력

### 5.4 검증 원칙

- 코드 변경 금지
- DB read-only 조회만 사용
- Full pytest 금지
- 외부 API/KIS 호출 금지
- 추정과 실측을 분리

## 6. 실행 체크리스트

아래 체크리스트는 실제 턴 실행 시 그대로 따라갈 수 있도록 작성한다.
각 항목은 **완료/미완료**로 판정하고, 결과가 나오면 관련 canonical
문서에 짧게 반영한다.

### 6.1 트랙 A — 임계치 정합성

- [x] 최근 3거래일(KST) `core_risk_off_ranking_blocked` 모집단의
      `raw_ranking_score` 구간 분포 재집계(SPPV-2.119/§106, 재확인
      SPPV-2.121/§109.1)
- [x] 전체 이력 `raw_ranking_score` 구간 분포 재집계(SPPV-2.119/§106)
- [x] `0.43~0.48`, `0.48 이상` 근접 표본 수 확인 — 0건(양 창 모두,
      SPPV-2.119/§106)
- [x] 상위 20건의 독립 표본성 확인 — 전부 단일 종목(`002790`)
      반복 사이클(SPPV-2.119/§106.2)
- [x] `0.48`이 경계값인지 상시 봉쇄 상수인지 1차 판정 — 경계값
      아님, 모집단 품질 문제에 더 가까움(SPPV-2.118~2.119/§105~§106)

### 6.2 트랙 B — 구성항목 적절성

- [x] `entry_score` 분포와 상한 확인 — 전체 이력 mean 0.0485,
      max 0.2479(SPPV-2.120/§107)
- [x] `relative_activity` 분포와 상한 확인 — mean 0.0351, median
      0.0000, max 0.6830(SPPV-2.120/§107)
- [x] `coverage_score` 분포와 무분산 여부 확인 — 완전 고정 1.0
      (SPPV-2.120/§107)
- [x] `allocation_quality` 분포와 무분산 여부 확인 — 완전 고정
      0.25(SPPV-2.120/§107)
- [x] `regime_tailwind` 분포와 고정값 여부 확인 — 전수 0.0(SPPV-
      2.120/§107)
- [x] `strategy_alignment` 분포와 고정값 여부 확인 — 전수 0.0
      (SPPV-2.120/§107)
- [x] 6개 항목 중 실제 변별력 있는 항목 / 고정 바닥 항목 구분 —
      변별력 있는 항목 2개(`entry_score`/`relative_activity`),
      고정 바닥 4개(SPPV-2.120/§107)

### 6.3 트랙 C — 가중치 적정성

- [x] 실제 구현식과 설계 문서 초안식 차이 재확인(SPPV-2.120/§107.1)
- [x] 각 항목의 평균 기여도(가중치 반영 후) 계산(SPPV-2.120/§107.2)
- [x] 상위 표본에서 어떤 항목이 점수를 끌어올리는지 확인 —
      `entry_score`+`relative_activity`(SPPV-2.121/§109.3)
- [x] 저점 표본에서 어떤 항목이 점수를 눌러버리는지 확인 — 동일
      두 항목이 0으로 떨어지며 하락(SPPV-2.121/§109.3)
- [x] 현재 가중치가 설명력 순서와 일치하는지 1차 판정 — 불일치
      (최대 가중치 0.20인 `coverage_score`가 최소 설명력, SPPV-
      2.121/§109.3)

### 6.4 트랙 D — 다른 BUY 차단 장치와의 중복 적정성

- [x] `entry_score`가 threshold와 ranking에서 중복 반영되는지
      확인 — 역할 분리(후보생성 vs 순위화), 순차 구조로 판정
      (SPPV-2.121/§109.4.1, SPPV-2.122)
- [x] `relative_activity`가 ranking과 eligibility에서 중복
      반영되는지 확인 — entry+ranking 4겹 중 가장 심함(SPPV-
      2.121/§109.4.2, SPPV-2.122)
- [x] `coverage_score`가 ranking과 eligibility에서 중복 반영되는지
      확인 — ranking 쪽 변별력 소멸(SPPV-2.121/§109.4.3, SPPV-2.122)
- [x] `regime` 축이 entry_score/ranking/eligibility에서 몇 겹으로
      반영되는지 확인 — 3겹, 하드 게이트가 실질 전부 담당(SPPV-
      2.121/§109.4.4, SPPV-2.122)
- [x] `strategy_alignment`가 entry_score/ranking에서 중복
      반영되는지 확인 — 완전 동일 조건 순수 중복(SPPV-2.121/
      §109.4.5, SPPV-2.122)
- [x] 중복이 방어 목적상 필요한지 vs 과잉 처벌인지 1차 판정 —
      항목별로 분리 판정 완료(SPPV-2.122, 아래 §6.6 참고)

### 6.5 문서 반영 체크리스트

- [x] `signal_predictive_power_validation.md`에 최신 판정 반영
- [x] `regime_conditional_entry_signal_v1.md`에 상세 분석 반영
- [x] `foundational_design_review_objective_alignment.md`에 의미
      정리 반영
- [x] `remaining_work_priority_map.md`에 우선순위 변화 반영
- [x] `backlog.md`에 후속 검증 항목 상태 반영

### 6.6 최종 완료 기준 체크

- [x] threshold 재측정이 먼저인지 / 산식 재검토가 먼저인지 /
      모집단 재정의가 먼저인지 판정 — **산식 재검토가 1순위**,
      모집단 재정의가 2순위, threshold 재측정은 근본 원인 아님
      (SPPV-2.120/§107.7)
- [x] 중복 차단 정리가 별도 1순위인지 판정 — **중복 차단 정리는
      전체 4개 옵션 중 2순위**(산식 재검토 다음). 다만 항목별로는
      `relative_activity`/`strategy_alignment`가 중복 제거·정리
      대상, `entry_score`는 정당한 역할 분리, `regime`은 하드
      게이트 쪽은 정당하나 소프트 중복은 저위험 정리 후보,
      `coverage_score`는 역할 축소 후보(SPPV-2.122/§110)
- [x] 다음 턴 구현 과제가 있는지 여부 명시 — 이번 턴은 진단/분류
      까지만, 구현 과제는 §110.8에서 규명 과제로만 제시(완화안/
      diff 아님)
- [x] 추정과 실측을 분리한 최종 보고 작성 — SPPV-2.122/§110에서
      "사실"/"해석"/"미확정" 3분류로 작성

## 7. 완료 기준

아래 4가지가 모두 답변되면 이 계획은 완료로 본다.

1. `0.48`이 유지 가능한 경계값인지, 아니면 재설정 후보인지
2. 6개 구성항목 중 유지/재검토 후보가 무엇인지
3. 가중치 재조정이 필요한지, 아니면 항목 정의가 먼저인지
4. ranking과 다른 BUY 차단 장치 간 중복 중
   - 유지해야 하는 중복
   - 설명력 없이 과하게 누적되는 중복
   이 무엇인지

## 8. 예상 산출물

1. 항목별 분포표
2. 항목별 기여도 분해표
3. 중복 차단 매핑표
4. 최종 판정
   - `threshold 재측정 우선`
   - `산식 재검토 우선`
   - `모집단 재정의 우선`
   - `중복 차단 정리 우선`
   중 무엇이 1순위인지

## 9. 현재 시점의 잠정 가설(검증 전 가설)

이 문서는 아직 실행 전 계획이므로 아래는 가설일 뿐이다.

1. `0.48`은 현재 분포에서 높다.
2. 문제는 threshold 하나보다
   - 저품질 모집단
   - 중복 차단
   - 실측 근거가 약한 가중치
   가 함께 얽힌 구조일 가능성이 크다.
3. 따라서 단순 완화보다 **공식의 역할 정의를 먼저 다시 고정**해야 한다.

## 10. 다음 연결 문서

- `[DESIGN] signal_predictive_power_validation.md`
- `[DESIGN] regime_conditional_entry_signal_v1.md`
- `[ANALYSIS] foundational_design_review_objective_alignment.md`
- `[PRIORITY_MAP] remaining_work_priority_map.md`
- `[BACKLOG] backlog.md`
