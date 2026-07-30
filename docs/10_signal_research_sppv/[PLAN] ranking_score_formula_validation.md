# ranking_score 공식 검증 계획

작성일: 2026-07-28  
상태: [SPPV-2.136에서 갱신] `relative_activity` 1안 적용 후
관측 단계 **종료**. 병합 이후 실제 경과 약 23시간(gate 모집단
n=616, 전체 BUY-path n=1,435 — 이전 두 턴(n=15/134) 대비 4~40배
확대, 병합 이전 1일치(n=1,037)와 같은 자릿수 도달)로 재확인한
결과, `buy_candidate`/`APPROVE`/`order_request`/`final_intent=
'buy'`/`shadow_topk_exception_v2`는 3개 관측 창(초기 1사이클→
누적 9사이클→누적 23시간) 전부에서 **일관되게 0 유지**. `ranking_
blocked` 비중은 병합 전후로 이동(99.9~100%→90~93%)했으나 병합
직전부터 이미 시작된 이동이고 예측과 반대 방향이라 **diff 인과
효과로 보지 않음**(교란 요인으로 판단). 핵심 병목은 여전히
`coverage_score`+절대 threshold(`0.48`/`0.22`) 조합.
**판정 전환: 1안(coverage_score+threshold 재설계 비교 착수)
채택** — 관측 단계는 이번 턴으로 종료, `coverage_score` 재설계
비교 착수 준비 완료(SPPV-2.119~2.136 참고)

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

**[SPPV-2.123에서 재판정, 2026-07-28 KST]** 아래 §6.1~§6.6은
"체크박스가 채워졌다"와 "검증이 실제로 끝났다"를 혼동한 부분이
있어 재검증했다. 이 재판정으로 일부 항목을 `실제 완료`에서
`부분 완료`로 되돌렸다(이력 보존 — 원래 완료 표시와 근거는 그대로
두고, 재판정 결과를 각 줄에 추가한다). 신규 트랙 E/F를 §6.7/§6.8
로 추가했다.

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

**[SPPV-2.123 재판정] §6.1 = 실제 완료.** 5개 하위 항목 모두
DB 실측(구간 분포, 근접 표본 0건, 상위 20건 반복성)에 기반하며
표본 반복성 문제와 무관하게 결론이 견고하다(구간 카운트는
집단 전체 카운트이지 특정 상위 표본에 의존하지 않음).

### 6.2 트랙 B — 구성항목 적절성

- [x] `entry_score` 분포와 상한 확인 — 전체 이력 mean 0.0485,
      max 0.2479(SPPV-2.120/§107)
- [x] `relative_activity` 분포와 상한 확인 — mean 0.0351, median
      0.0000, max 0.6830(SPPV-2.120/§107)
- [x] `coverage_score` 분포와 무분산 여부 확인 — 완전 고정 1.0
      (SPPV-2.120/§107). **[SPPV-2.123 추가 확인]** 같은 3거래일
      창(2026-07-24/27/28 KST)의 **일반 모집단**(`trade_decisions`
      전체, `eligibility_core_risk_off_ranking_blocked` 필터
      없음, n=4,510)에서도 `coverage_score`가 100% 1.0으로 확인됨.
      **[SPPV-2.124에서 보정]** `trade_decisions` **전체 이력**
      (n=68,724, 시간 범위 제한 없음)까지 넓혀 재확인한 결과,
      `coverage_score`는 distinct 2값(`1.0`: 35,873건,
      `0.1429`: 725건)으로 **완전 무분산이 아니다**(사실, 신규
      전체 이력 조회). 즉 SPPV-2.123의 "일반적 무분산"이라는
      표현은 **"최근 3거래일 창 기준"으로만 성립**하며, 전체
      이력 기준으로는 "98%가 1.0에 몰려 있으나 완전 고정은
      아님"으로 정정한다. **판정: 부분 확정**(최근 관측 창에서는
      거의 항상 1.0, 전체 이력에서는 드문 예외 존재).
- [x] `allocation_quality` 분포와 무분산 여부 확인 — 완전 고정
      0.25(SPPV-2.120/§107). **[SPPV-2.123 정정]** 같은 3거래일
      창의 일반 모집단(n=4,510)에서는 `max_new_capital_pct`가
      **2.5(3,191건)/3.0(1,319건) 두 값**으로 분산돼 있음을 확인.
      **[SPPV-2.124에서 정밀화]** `trade_decisions` 전체 이력
      (n=68,724)까지 넓혀 재확인한 결과, `max_new_capital_pct`는
      **distinct 1,929개 값**(0.0/1.5459/2.4123/.../4.0/5.0 등,
      2.5·3.0 외에도 매우 다양한 소수점 값 포함)으로 **풍부한
      연속 분산**을 보인다(사실, 신규 전체 이력 조회). 즉 "최근
      3거래일 창"만 보면 2값뿐인 약한 분산이었지만, "전체 이력"
      기준으로는 명백하고 풍부한 분산이 확인된다 — **직전 턴
      (SPPV-2.123)의 "일반적으로 분산이 존재한다"는 결론은
      방향은 맞았으나, 근거로 제시한 "2값(2.5/3.0)"이라는 표현이
      분산의 정도를 과소·모호하게 서술한 부분이 있어 이번 턴에서
      전체 이력 수치로 보강한다. 판정: 확정(전체 이력 기준 풍부한
      분산), 다만 최근 3거래일 창 단독으로는 부분 확정(2값뿐)이었음
      을 함께 기록한다.**
- [x] `regime_tailwind` 분포와 고정값 여부 확인 — 전수 0.0(SPPV-
      2.120/§107). **[SPPV-2.123 추가 확인]** 같은 3거래일 창의
      일반 모집단에서도 `risk_tone`이 100% `risk_off`로 확인됨.
      **[SPPV-2.124에서 보정]** `trade_decisions` 전체 이력
      (n=68,724)에서는 `risk_tone` 분포가 `None`(32,017건,
      `market_regime.py` 도입 이전 구간) / `risk_off`(36,433건) /
      `risk_on`(**42건**) / `neutral`(**232건**)으로, 완전
      무분산이 아니다(사실, §99에서 이미 확인한 2026-06-17~19
      과도기 구간의 잔존 사례). **판정: 부분 확정**(최근 관측
      창·현재 운영 국면에서는 거의 항상 `risk_off`(무분산에
      가까움), 전체 이력 기준으로는 드문 예외 존재).
- [x] `strategy_alignment` 분포와 고정값 여부 확인 — 전수 0.0
      (SPPV-2.120/§107). **[SPPV-2.123 정정]** 같은 3거래일 창의
      일반 모집단에서는 `preferred_strategy`가 `event_
      continuation`으로 **4.8%(217/4,510건)** 나타남. **[SPPV-
      2.124에서 보강]** 전체 이력(n=68,724)에서는 `entry_score`/
      `ranking_score`의 `strategy_alignment` 대상 집합
      `{swing_momentum, event_continuation}`에 해당하는 건수가
      `swing_momentum`(42건)+`event_continuation`(2,520건)=
      2,562건(전체의 3.7%)이다(사실, 신규 전체 이력 조회) —
      드물지만 실재하는 발동 사례다. **판정: 부분 확정**(이
      게이트 모집단 내부는 무분산 확정, 일반 모집단에서는 드물게
      발동 — "완전 무해"도 "흔한 발동"도 아닌 중간 상태).
- [x] 6개 항목 중 실제 변별력 있는 항목 / 고정 바닥 항목 구분 —
      **[SPPV-2.123 재판정, SPPV-2.124에서 보정]** 이 게이트
      모집단 안에서는 여전히 변별력 있는 항목 2개(`entry_score`/
      `relative_activity`)로 유지된다. 그 외 4개 항목의 "일반
      모집단에서의 무분산 여부"는 **관측 창에 따라 결론이 달라진다**
      — `coverage_score`/`regime_tailwind`는 최근 관측 창(3
      거래일)에서는 무분산이나 전체 이력에서는 드문 예외가 있어
      **부분 확정**, `allocation_quality`는 전체 이력 기준으로
      명백한 풍부한 분산이 있어 **확정**(다만 최근 3거래일 창만
      보면 2값뿐인 약한 분산), `strategy_alignment`도 전체 이력
      기준 드문 발동(3.7%)이 있어 **부분 확정**이다 — "일반
      모집단에서도 무분산 확정"이라는 SPPV-2.123의 일괄 서술은
      **과했다**(정정, 아래 재판정 참고).

**[SPPV-2.124에서 재판정] §6.2 = 부분 완료(SPPV-2.123의 "실제
완료 격상"을 다시 되돌림).** SPPV-2.123은 "최근 3거래일 일반
모집단"만 조회하고 이를 "일반적" 결론으로 과대 해석했다 — 이번
턴에 `trade_decisions` 전체 이력(n=68,724, 시간 제한 없음)까지
넓혀 재확인한 결과: `coverage_score`/`regime_tailwind`는 "최근
관측 창에서는 무분산"이 맞지만 전체 이력 기준으로는 드문 예외가
있어 **부분 확정**(완전 무분산 아님)으로 하향한다. `allocation_
quality`는 전체 이력 기준으로는 명백히 **확정**(풍부한 연속
분산)이지만, SPPV-2.123이 근거로 든 "3거래일 창 2값"이라는
표현은 분산의 정도를 실제보다 약하게 서술했다. `strategy_
alignment`는 전체 이력 기준 드문 발동(3.7%)이 있어 **부분 확정**
이다. 요컨대 **"관측 창을 명시하지 않은 일반화"가 이번 정정의
핵심 문제**였다 — §6.2는 4개 항목의 세부 판정이 관측 창별로
갈리므로 전체를 "실제 완료"로 부르기보다 **부분 완료**로
되돌린다.

### 6.3 트랙 C — 가중치 적정성

- [x] 실제 구현식과 설계 문서 초안식 차이 재확인(SPPV-2.120/§107.1)
      — 코드 read 기반, 표본 반복성과 무관, 견고함.
- [x] 각 항목의 평균 기여도(가중치 반영 후) 계산(SPPV-2.120/§107.2)
      — 전체 이력(n=11,971) 집계 기준, 견고함.
- [~] 상위 표본에서 어떤 항목이 점수를 끌어올리는지 확인 —
      `entry_score`+`relative_activity`(SPPV-2.121/§109.3).
      **[SPPV-2.123 재검증, 중대 정정]** "상위 50건"을 종목
      기준으로 재조회한 결과, **상위 50건 전부가 단일 종목
      (`002790`) 1개의 반복 사이클**이었다(distinct symbol=1,
      사실 신규 확인). 즉 이 결론은 "여러 상위권 후보의 공통
      패턴"이 아니라 **종목 1개의 특성**에 근거한 것이었다.
      distinct symbol 기준(종목당 최고 `ranking_score` 1개씩,
      n=25)으로 다시 봐도 상위 10개 종목은 0.30~0.42 범위에서
      `entry_score`/`relative_activity`가 여전히 유일한 변동
      원천이라는 **방향성은 유지**되지만, "상위 50건 평균
      기여도" 수치 자체는 표본 반복 편향이 있었다(사실, 신규
      확인).
- [~] 저점 표본에서 어떤 항목이 점수를 눌러버리는지 확인 — 동일
      두 항목이 0으로 떨어지며 하락(SPPV-2.121/§109.3).
      **[SPPV-2.123 재검증]** "하위 50건"도 5개 종목으로만
      구성되며 이 중 1개 종목(`000720`)이 35/50(70%)을 차지한다
      (사실, 신규 확인) — 상위 표본보다는 덜 심하지만 여전히
      반복 편향이 있다.
- [x] 현재 가중치가 설명력 순서와 일치하는지 1차 판정 — 불일치
      (최대 가중치 0.20인 `coverage_score`가 최소 설명력, SPPV-
      2.121/§109.3). **이 판정 자체는 유지된다** — `coverage_
      score`가 무분산이라는 사실은 §6.2에서 표본 반복과 무관하게
      전체 모집단(그리고 일반 모집단) 기준으로 확인됐으므로,
      가중치-설명력 불일치 결론은 표본 반복 편향의 영향을 받지
      않는다.

**[SPPV-2.123 재판정] §6.3 = 부분 완료.** 항목 3/4(가중치
불일치 판정 포함 대부분)은 표본 반복과 무관하게 견고하지만,
"상위/하위 50건 평균 기여도"라는 구체적 수치는 실제로는 소수
종목(상위 1개, 하위 5개 중 1개가 70%)의 반복 관측에 근거했다
— **"구조 설명(방향성)은 완료, 다표본 일반화는 미완료"**로
재분류한다. distinct-symbol 기준 재계산(§6.7 참고)으로 방향성은
유지됨을 이번 턴에 확인했으나, 이 자체도 n=25로 표본이 작아
"완전히 닫혔다"고 보기는 이르다.

### 6.4 트랙 D — 다른 BUY 차단 장치와의 중복 적정성

- [x] `entry_score`가 threshold와 ranking에서 중복 반영되는지
      확인 — 역할 분리(후보생성 vs 순위화), 순차 구조로 판정
      (SPPV-2.121/§109.4.1, SPPV-2.122). 코드 경로 기반, 견고함.
- [x] `relative_activity`가 ranking과 eligibility에서 중복
      반영되는지 확인 — entry+ranking 4겹 중 가장 심함(SPPV-
      2.121/§109.4.2, SPPV-2.122). 코드 경로 기반, 견고함.
- [x] `coverage_score`가 ranking과 eligibility에서 중복 반영되는지
      확인 — ranking 쪽 변별력 소멸(SPPV-2.121/§109.4.3, SPPV-2.122).
      **[SPPV-2.123 추가]** §6.2에서 일반 모집단 무분산도 확인돼,
      "ranking 쪽 변별력 소멸"이 이 게이트 특유가 아니라 일반적
      현상임이 보강됨.
- [x] `regime` 축이 entry_score/ranking/eligibility에서 몇 겹으로
      반영되는지 확인 — 3겹, 하드 게이트가 실질 전부 담당(SPPV-
      2.121/§109.4.4, SPPV-2.122). 코드 경로 기반, 견고함.
- [x] `strategy_alignment`가 entry_score/ranking에서 중복
      반영되는지 확인 — 완전 동일 조건 순수 중복(SPPV-2.121/
      §109.4.5, SPPV-2.122). 코드 경로(조건 집합 일치) 기반,
      견고함.
- [~] 중복이 방어 목적상 필요한지 vs 과잉 처벌인지 1차 판정 —
      항목별로 분리 판정 완료(SPPV-2.122). **[SPPV-2.123 재판정]**
      "존재 확인은 완료, 정당성(방어 목적상 필요 vs 과잉) 최종
      판정은 항목별로 강도가 다르다" — `entry_score`(정당,
      확정) / `relative_activity`·`strategy_alignment`(과잉
      가능성 높음, 코드 기반 확정에 가까움) / `coverage_score`
      (§6.2 갱신으로 "일반적으로도 변별력 없음"까지는 확정,
      다만 "그래서 과잉 처벌"이라고 부를지는 여전히 정책적 판단
      영역 — 부분 완료) / `regime` 하드 게이트(§102~§104의
      "정당/과잉 미확정" 판정 유지, 이번 트랙에서 별도로 닫지
      않음 — 미완료 상태 유지).

**[SPPV-2.123 재판정] §6.4 = 부분 완료.** "중복 존재 확인"
5개 항목은 전부 코드 경로 기반으로 견고하게 완료됐다(사실).
그러나 "정당성 vs 과잉 처벌"이라는 최종 판정 항목은 `entry_
score`/`relative_activity`/`strategy_alignment` 3개만 확정에
가깝고, `coverage_score`(정책 판단 필요)와 `regime` 하드
게이트(§102~§104 자체가 이미 미확정으로 열어둔 사안)는 여전히
열려 있다 — **"중복 존재 확인은 완료, 정당성 판정은 부분
완료"**로 재분류한다.

### 6.5 문서 반영 체크리스트

- [x] `signal_predictive_power_validation.md`에 최신 판정 반영
- [x] `regime_conditional_entry_signal_v1.md`에 상세 분석 반영
- [x] `foundational_design_review_objective_alignment.md`에 의미
      정리 반영
- [x] `remaining_work_priority_map.md`에 우선순위 변화 반영
- [x] `backlog.md`에 후속 검증 항목 상태 반영

**[SPPV-2.123 재확인] §6.5 = 실제 완료.** 매 턴 5개 canonical
문서 전부에 반영해왔고, 이번 턴(SPPV-2.123)도 동일하게 반영한다
— 절차적으로 견고하다.

### 6.6 최종 완료 기준 체크

- [x] threshold 재측정이 먼저인지 / 산식 재검토가 먼저인지 /
      모집단 재정의가 먼저인지 판정 — **산식 재검토가 1순위**,
      모집단 재정의가 2순위, threshold 재측정은 근본 원인 아님
      (SPPV-2.120/§107.7). **[SPPV-2.124 재확인] 이 순위 판정은
      §6.2/§6.3의 재판정과 무관하게 유지된다** — `coverage_
      score`가 이 게이트 모집단 안에서 무분산이라는 사실(§107,
      §109) 자체는 변하지 않았다. 다만 그 근거를 "일반 모집단
      에서도 항상 무분산"이라고 확대한 SPPV-2.123의 서술은
      과했으므로(§6.2/§6.7 재판정), 산식 1순위 판정의 근거는
      "이 게이트 모집단 내부의 무분산"으로 좁혀서 유지한다(더
      강해진 것이 아니라, 과대해석 없이도 원래부터 충분한
      근거였음을 재확인).
- [x] 중복 차단 정리가 별도 1순위인지 판정 — **중복 차단 정리는
      전체 4개 옵션 중 2순위**(산식 재검토 다음). (SPPV-2.122/§110)
      **[SPPV-2.123 재확인] 유지.**
- [x] 다음 턴 구현 과제가 있는지 여부 명시 — 이번 턴은 진단/분류
      까지만, 구현 과제는 §110.8/§6.7~§6.8에서 규명 과제로 제시
      (완화안/diff 아님)
- [~] 추정과 실측을 분리한 최종 보고 작성 — SPPV-2.122/§110에서
      "사실"/"해석"/"미확정" 3분류로 작성했으나, **§6.3의 표본
      반복 문제는 그 시점에 발견되지 못했다** — 이번 턴(SPPV-
      2.123)에서 발견·정정했다.

**[SPPV-2.123 재판정] §6.6 = 부분 완료 → 실제 완료로 격상
(이번 턴 보정 반영 후).** 4개 옵션 우선순위 판정 자체는 견고하게
유지되고, 이번 턴에 §6.2/§6.3의 재검증까지 반영해 "추정과 실측
분리"라는 마지막 기준까지 충족했다.

### 6.7 트랙 E — 일반 모집단 대조(신규, SPPV-2.123에서 1차 실행,
SPPV-2.124에서 전체 이력까지 확장·재판정)

**모집단 정의(SPPV-2.124에서 명확화, 이력별로 구분)**:
- "3거래일 일반 모집단" = `trade_decisions` 중 `created_at`을
  KST로 환산한 날짜가 `2026-07-24`/`2026-07-27`/`2026-07-28`인
  전체 레코드(게이트 필터 없음), n=4,510.
- "전체 이력 일반 모집단" = `trade_decisions` 테이블 전체 레코드
  (시간 범위 제한 없음, 게이트 필터 없음), n=68,724.

| 항목 | 3거래일 일반 모집단(n=4,510) | 전체 이력 일반 모집단(n=68,724) | 최종 판정 |
|---|---|---|---|
| `coverage_score` | 100% 1.0(무분산) | distinct 2값(1.0: 35,873건, 0.1429: 725건) | **부분 확정** |
| `allocation_quality`(`max_new_capital_pct`) | distinct 2값(2.5: 3,191건, 3.0: 1,319건) | distinct **1,929값**(0.0/4.0/5.0 등 포함, 풍부한 연속 분산) | **확정**(전체 이력 기준) |
| `regime_tailwind`(`risk_tone`) | 100% risk_off(무분산) | `risk_off` 36,433 / `None` 32,017 / `risk_on` **42** / `neutral` **232** | **부분 확정** |
| `strategy_alignment`(`preferred_strategy`) | `event_continuation` 4.8%(217건) | `{swing_momentum, event_continuation}` 합계 2,562건(3.7%) | **부분 확정** |

- [x] `coverage_score`가 일반 모집단에서도 무분산인지 확인 —
      **관측 창에 따라 다르다**: 3거래일 창은 무분산(사실),
      전체 이력은 98%가 1.0이나 완전 무분산은 아님(사실, 신규
      전체 이력 조회) — **부분 확정**.
- [x] `allocation_quality`가 일반 모집단에서도 무분산인지 확인 —
      **아니다, 분산이 존재한다**(사실). 3거래일 창(2값)보다
      전체 이력(1,929값)이 훨씬 풍부한 분산을 보여준다 — **확정**.
- [x] `regime_tailwind`(`risk_tone`)가 일반 모집단에서도 무분산인지
      확인 — **관측 창에 따라 다르다**: 3거래일 창은 무분산(사실,
      §99와 정합), 전체 이력은 `risk_on`/`neutral` 소수 존재(사실,
      2026-06-17~19 과도기 잔존) — **부분 확정**.
- [x] `strategy_alignment`(`preferred_strategy`)가 일반 모집단
      에서도 무분산인지 확인 — **아니다, 드물게 발동한다**(사실).
      3거래일 창 4.8%, 전체 이력 3.7% — **부분 확정**(흔하지 않지만
      실재).

### 6.8 트랙 F — 상위/하위 표본 반복성 보정(신규, 부분 착수)

- [x] 상위 50건/하위 50건의 distinct symbol 수 확인 — 상위
      50건=1개 종목(`002790`), 하위 50건=5개 종목(1개가 70%
      차지)(사실, 신규 확인).
- [x] distinct symbol 기준(종목당 최고 `ranking_score` 1개, n=25)
      재계산 — 상위 10개 종목 0.30~0.42, 하위 10개 종목 0.22~0.27
      로 방향성은 유지됨을 확인(사실).
- [x] **[SPPV-2.127에서 완료]** distinct symbol 기준으로
      **구성요소 기여도**(entry_score/relative_activity 기여분)
      까지 다시 계산해 §109.3의 "상위 50건 평균 기여도" 수치를
      종목 중복 제거 버전으로 교체. 아래 §6.10 참고.
- [x] **[SPPV-2.127에서 완료]** `002790`/`000720` 등 반복 종목이
      왜 같은 사이클에 반복 등장하는지 원인 확인 — **intraday
      decision loop의 고정 재평가 주기(5분) + signal_feature_
      snapshot의 1일 1회 갱신 구조**가 원인임을 확인(완화안 아님,
      원인 규명만). 아래 §6.11 참고.

### 6.10 SPPV-2.127 — distinct symbol 기준 기여도 재계산(완료,
2026-07-29 KST)

두 가지 모집단으로 분리해서 재계산했다(코드 read-only, DB
read-only, 신규 KIS 호출 0건).

**(A) `eligibility_core_risk_off_ranking_blocked` 게이트 모집단
내부(distinct symbol=25, 종목당 최고/최저 `ranking_score` 1개씩
대표값 사용)**:

| 그룹 | entry 기여 | activity 기여 | coverage 기여 | alloc 기여 | 기타 |
|---|---:|---:|---:|---:|---:|
| 상위 10개 종목 평균 | 0.1192 | 0.0305 | 0.2000 | 0.0250 | 0 |
| 하위 10개 종목 평균 | 0.0000 | 0.0000 | 0.2000 | 0.0250 | 0 |
| **차이** | **0.1192** | **0.0305** | 0 | 0 | 0 |

차이 합계 0.1497 중 `entry_score`+`relative_activity`가
**100.0%**를 설명한다(사실, 재계산). **[판정: 유지]** — 종목
반복 편향을 제거한 뒤에도 §109.3/§110의 결론("entry_score+
relative_activity가 차이를 설명, coverage/alloc은 무의미")이
**그대로 유지된다.**

**(B) 전체 이력 BUY 경로 전체(`deterministic_trigger.metadata.
eligibility_path == 'buy'`인 전체 레코드, distinct symbol=105,
row 수=35,149 — SELL/EXIT 경로의 `ranking_score`(다른 산식,
`_build_exit_ranking_score`)와 혼선되지 않도록 BUY 경로만
필터링했다)**:

| 그룹 | entry 기여 | activity 기여 | coverage 기여 | alloc 기여 | regime 기여 | strategy 기여 |
|---|---:|---:|---:|---:|---:|---:|
| 상위 10개 종목 평균 | 0.3567 | 0.0207 | 0.2000 | 0.0310 | 0.0030 | 0.0060 |
| 하위 10개 종목 평균 | 0.0000 | 0.0000 | 0.2000 | 0.0250 | 0.0000 | 0.0000 |
| **차이(상위10-하위10)** | **0.3567** | **0.0207** | 0.0000 | 0.0060 | 0.0030 | 0.0060 |

차이 합계 0.3924 중 `entry_score`+`relative_activity`가
**96.2%**를 설명한다(사실, 신규 재계산 — 게이트 밖 일반 BUY
모집단에서도 동일 방향 재확인). `coverage_score` 기여 차이는
**정확히 0**(상위·하위 그룹 모두 항상 1.0) — 이 모집단 밖에서도
변별력이 없음이 재확인된다. `allocation_quality`는 소폭
(0.006) 기여하는데, 이는 상위권 종목들이 `bearish_trend`가
아닌 국면에 속해 `max_new_capital_pct=3.0`(→ alloc=0.30)을
받는 경향과 관련된다(해석, 완전한 원인 규명은 범위 밖).

**최종 판정(§6.10)**: 원래 결론("차이는 사실상 `entry_score`+
`relative_activity`가 설명")은 **게이트 내부(100.0%)와 일반
BUY 경로 전체(96.2%) 양쪽 모두에서 유지된다** — 종목 반복
편향을 제거해도 방향과 크기가 거의 그대로 재현됐다. `[PLAN]`
§6.8 잔여 항목 2개를 완료로 전환한다.

### 6.11 SPPV-2.127 — `002790`/`000720` 반복 등장 원인 규명(완료,
2026-07-29 KST)

| 항목 | `002790` | `000720` |
|---|---|---|
| 관측 창 내 총 레코드 수(`ranking_blocked` 사유 한정) | 239건 | 761건 |
| 관측된 거래일 수(UTC 날짜 기준) | 6일(07-03/09/10/14/15/16, 산발적) | 20일 이상(06-26~07-29, 거의 매 거래일) |
| 사이클 간 최소 간격 | 약 359초(≈6분) | 약 328초(≈5.5분) |
| `decision_type`(전 기간) | `WATCH`(불변) | `HOLD`(불변) |
| `candidate_set`(전 기간) | `['WATCH']`(불변) | `['NO_ACTION']`(불변) |
| `eligibility_reasons`(전 기간) | 4개 조합 불변(`..._ranking_blocked` 포함) | 4개 조합 불변(동일) |
| `entry_score` 추이 | `0.2479 → 0.1413`(하루 단위로 변화, 완만히 감소) | `0.0063 → 0.0`(거의 항상 0에 근접, 고착) |

**원인 규명(사실 기반)**:
1. **최소 사이클 간격(약 328~359초)이 `run_decision_loop.py`의
   `DEFAULT_INTERVAL_SECONDS = 300`(5분)과 정합**한다(사실,
   코드 확인) — intraday decision loop가 장중 고정 주기로 매
   사이클마다 `trade_decisions`에 새 행을 저장하는 **설계된
   동작**이며, 저장/로깅 버그가 아니다.
2. §101에서 이미 확인한 대로 `signal_feature_snapshot`은 **하루
   1회**만 갱신되므로, 같은 거래일 안의 모든 사이클은 **동일한
   입력**으로 `entry_score`/`ranking_score`를 재계산한다 —
   이것이 하루 안에서 값이 거의 동일하게 반복되는 직접 원인이다
   (사실, §101과 정합).
3. `eligibility_core_risk_off_ranking_blocked` 게이트가 하루
   내내 동일하게 걸려 있어 `decision_type`/`candidate_set`이
   하루 종일(그리고 여러 날에 걸쳐) 바뀌지 않는다 — "특정 gating
   상태가 고정된 채 계속 기록"되는 것도 사실로 확인된다.

**`002790`와 `000720`의 차이(사실)**: 두 종목 모두 **같은
메커니즘**(5분 주기 loop × 1일 1회 snapshot × 고정 게이트)으로
반복되지만, **정도가 다르다** — `002790`은 산발적인 6개 거래일
에만 나타나고 `entry_score`가 완만히 변화(0.25→0.14)하는 반면,
`000720`은 관측 창 대부분(20일+)에 걸쳐 연속 등장하며
`entry_score`가 거의 항상 0에 고착돼 있다. 이는 `000720`이
`core` 유니버스에 더 지속적으로 포함되고 신호가 만성적으로
약한 종목인 반면, `002790`은 유니버스 포함이 더 간헐적임을
시사한다(해석 — 유니버스 포함 조건 자체의 원인 규명은 이번
턴 범위 밖).

**최종 판정(§6.11)**: 반복 등장은 **"같은 사이클 구조상 정상
반복"**이다(3개 확인 항목 모두 사실로 뒷받침) — 저장/집계
방식의 결함이 아니다. 다만 이 정상 반복 구조 때문에, **row
단위 통계는 관측 빈도가 높은 종목(예: `002790`/`000720`)에
과대 가중되므로, 앞으로 이 계열 분석은 distinct-symbol 기준을
기본으로 삼아야 한다**(방법론적 시사점, 완화안 아님).

### 6.9 SPPV-2.125 재검증 — 모집단 정의·필드 경로 정밀화(신규,
2026-07-28 KST, 완료)

**[SPPV-2.125에서 정밀화]** SPPV-2.124가 "전체 이력 일반
모집단 n=68,724"라고 단일 숫자로 표기한 것은 **`trade_decisions`
테이블 전체 행 수(사실, 정확)**이지만, 각 필드(`coverage_score`/
`allocation_quality`/`risk_tone`)의 **실제 유효값 존재 모집단은
서로 다르며 68,724보다 작다**는 점이 명시되지 않아 오해를 낳을
수 있었다. read-only 재조회로 정확한 경로·모집단·재현성을
다시 닫는다(코드 미수정, Full pytest 미실행, 신규 KIS 호출 0건).

**Q1. `n=68,724`가 어떤 조건으로 집계됐는지**

- `select count(*) from trading.trade_decisions` → **68,724**
  (WHERE 조건 없음, `trade_decisions` 테이블 전체 행, 사실).
- `decision_json ? 'deterministic_trigger'`(JSONB 키 존재 연산자)
  → **38,667**(사실, 신규 재확인). 즉 68,724건 중 **30,057건은
  `deterministic_trigger` 키 자체가 없다**(사실).
- `decision_json ? 'portfolio_allocation'` → **38,762**(사실) —
  `deterministic_trigger`(38,667)와 정확히 같지 않다(95건 차이,
  두 키의 존재 조건이 완전히 동일하지 않음).
- SPPV-2.124의 python 집계 코드는 `dj.get('deterministic_
  trigger') or {}`처럼 **키가 없으면 빈 dict로 대체**한 뒤 하위
  필드를 조회했다 — 이 때문에 "값이 원래 없음(키 자체 부재)"과
  "값이 null임(키는 있으나 값이 null)"이 한 버킷(`None`)으로
  뭉쳐졌다. **이것이 사용자가 발견한 불일치의 정확한 원인이다.**

**Q2. `allocation_quality distinct 1,929`의 정확한 추출 경로**

- 코드: `deterministic_trigger_engine.py:1110-1113`
  `allocation_quality = _clamp((portfolio_allocation.max_new_
  capital_pct or 0.0) / 10.0)` — `_build_buy_ranking_score()`
  내부에서 `ranking_score` 계산에 실제로 쓰이는 것과 **동일한
  경로**임을 코드로 재확인(사실).
- JSON 경로: `decision_json.portfolio_allocation.max_new_
  capital_pct` — `portfolio_allocation`은 `decision_factory.py:
  251`에서 **`deterministic_trigger`와 별개의 top-level 형제
  키**로 직렬화된다(사실, 코드 확인) — 따라서 `deterministic_
  trigger`가 없어도 `portfolio_allocation`은 존재할 수 있다.
- **정확한 유효 모집단**: `decision_json ? 'portfolio_
  allocation'`인 **38,762건** 전부가 `max_new_capital_pct`
  non-null(사실, 재확인 — 결측 0건). **distinct 1,929값은 이
  38,762건 기준으로 재현됐다**(재확인 완료, 68,724 전체가
  아니라 38,762가 정확한 분모).

**Q3. "상위 50건=단일 종목(`002790`)" 주장의 필드 재확인**

- 사용한 필드: `decision_json.deterministic_trigger.ranking_score`
  (top-level 저장 필드, `round(ranking_score, 4)`로 반올림된
  값) — **shadow 필드가 아니다**(사실, 코드 재확인).
- 이 필드가 `eligibility_core_risk_off_ranking_blocked` 모집단
  (n=11,971) **전원에게 존재**함을 재확인(결측 0건, 사실).
- 같은 레코드의 shadow 필드(`deterministic_trigger.metadata.
  core_risk_off_experiment.raw_ranking_score`, 반올림 없는
  전체 정밀도)와 반올림 오차(1e-9) 이내로 **완전히 일치**함을
  10,444건 전수 대조로 재확인(불일치 0건, 사실) — 두 필드가
  같은 값의 다른 표현(반올림 vs 원본)임을 확정한다.
- **"상위 50건=단일 종목 `002790`" 결론을 이 필드(`ranking_
  score`) 기준으로 재현했다 — distinct symbol=1, 재확인 결과
  동일(재현됨). [SPPV-2.126에서 명시 보정] 이 결론은 전체
  `deterministic_trigger.ranking_score` 모집단(38,667건)이
  아니라 `eligibility_core_risk_off_ranking_blocked` 하드 게이트
  모집단 내부(n=11,971, §6.7/§109.2/§109.3 동일 모집단)의 상위
  50건에 한정된다 — 조건 없이 "top50=002790"이라고만 쓰면
  일반 BUY ranking 전체의 최상위권이 이 종목이라는 뜻으로
  오독될 수 있어, 이번 턴부터 항상 게이트 모집단 조건을 함께
  표기한다.**

**Q4. 문서 정정 필요 여부 판정**

- 핵심 수치(`allocation_quality distinct 1,929`, `coverage_
  score distinct 2`, `top50=002790 단독`[`eligibility_core_
  risk_off_ranking_blocked` 게이트 모집단 내부 한정, n=11,971])
  는 **모두 그대로 재현됐다** — 값 자체를 정정할 필요는 없다.
- 다만 §6.7의 "전체 이력 일반 모집단(n=68,724)"이라는 표기는
  **coverage_score/risk_tone 분석에는 정확한 분모가 아니다** —
  정확한 분모는 아래와 같이 필드별로 다르다(정밀화):
  - `allocation_quality`: 분모 **38,762**(`portfolio_allocation`
    존재, `deterministic_trigger`와 무관).
  - `coverage_score`: 분모 **36,598**(`deterministic_trigger`
    존재 38,667건 중 `coverage_score` non-null인 건수).
  - `risk_tone`(`regime_tailwind`): `deterministic_trigger`
    존재 38,667건 기준 `risk_off` 36,433 / `risk_on` 42 /
    `neutral` 232 / **null(값 자체가 없음)** 1,960 — SPPV-2.124가
    "None: 32,017"이라고 쓴 것은 **"deterministic_trigger 키
    자체가 없는 30,057건" + "키는 있으나 risk_tone 값이 null인
    1,960건"이 합쳐진 수치**였다(정밀화, 완전히 틀린 것은
    아니나 두 종류의 "없음"을 구분하지 않아 부정확했다).
- **결론: 표에 적힌 distinct-값 수치들은 재현됐으나, 분모
  ("n=68,724")는 3개 필드 각각 다른 정확한 값(38,762/36,598/
  38,667)으로 대체해야 한다** — 아래 §6.7 보정표 참고.

**§6.7 보정표(SPPV-2.125, 정확한 분모 반영)**:

| 항목 | 정확한 유효 모집단 분모 | distinct 값 | 최종 판정(불변) |
|---|---:|---|---|
| `coverage_score` | 36,598(`deterministic_trigger` 존재 38,667건 중 non-null) | 2(1.0: 35,873 / 0.1429: 725) | 부분 확정 |
| `allocation_quality` | 38,762(`portfolio_allocation` 존재, 전부 non-null) | 1,929 | 확정 |
| `regime_tailwind`(`risk_tone`) | 38,667(`deterministic_trigger` 존재, 이 중 1,960건은 값 자체가 null) | risk_off 36,433/risk_on 42/neutral 232/null 1,960 | 부분 확정 |

**재현 여부 요약**: `allocation_quality distinct=1,929`(재현),
`coverage_score distinct=2`(재현), `top50=002790 단독`(재현,
단 `eligibility_core_risk_off_ranking_blocked` 게이트 모집단
내부 한정, n=11,971 — 전체 `deterministic_trigger.ranking_
score` 모집단 38,667건 전체의 최상위가 아님) — **값은 전부
재현됨**. `n=68,724`라는 분모 표기(재현 안 됨, 정밀화 필요 —
위 보정표로 대체).

### 6.12 SPPV-2.128 — `regime_tailwind`/`strategy_alignment` 고정
여부: 설계 의도 vs 부산물(신규, 2026-07-29 KST, 완료)

`[PRIORITY_MAP]` SPPV-3 1순위 과제. 코드 read-only 재확인 +
전체 이력(n=38,997) DB 조회로 검증했다.

- [x] **코드 경로 재확인**: `regime_tailwind`는 `source_type`
      분기 없이 `risk_tone`에만 의존(사실). `strategy_alignment`는
      `strategy_selection.py`에 **`source_type=='event_overlay'`
      전용 override**가 존재해, `regime_label != 'bearish_trend'`
      이면 `risk_off`여도 `event_continuation`을 강제 부여함을
      확인(사실, 코드).
- [x] **전체 이력 0-아닌 사례 확인**: `regime_tailwind=1.0`은
      42건, 전부 `market_overlay` 소스·2026-06-18(유일한 `risk_
      on` 관측일)에서만 발생. `strategy_alignment=1.0`은 2,573건
      (`event_overlay` 2,531 + `market_overlay` 42) — **`core`
      소스에서는 전체 이력을 통틀어 단 한 번도 0이 아닌 사례가
      없음**(사실).
- [x] **설계 문서 대조**: `event_overlay` override는 코드에
      명시적으로 분리된 조건 분기로 존재 — 의도된 설계로 판단.
      `regime_tailwind`는 소스 무관 규칙이라 `core`만 예외적으로
      죽이는 설계가 아니라, 상류 `risk_tone` 상시화(§99~§101
      기진단)의 영향을 받는 구조.
- [x] **최종 판정**: `strategy_alignment`(`core` 소스 기준)는
      **설계 의도대로 죽어 있는 항**, `regime_tailwind`는 **설계
      자체는 정상이나 상류 이상으로 실질적 효력을 잃은 부산물적
      결과** — 둘의 성격이 다름을 확정. 코드 버그 아님.

상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
entry_signal_v1.md` §116.

### 6.13 SPPV-2.129 — §6.12 수치·해석 정밀 보정(신규, 2026-07-29
KST, 완료)

**전제**: §6.12의 결론을 뒤집는 것이 아니라 수치·해석 정밀도를
현재 기준으로 보정한다.

- [x] **분모 재확인**: `n=38,997`(§6.12 작성 시점)/`n=39,027`
      (사용자 재확인 시점)/`n=39,113`(이번 턴 재조회, 2026-07-29
      KST 10:55 기준)이 서로 다른 이유는 계산 오류가 아니라
      **`trade_decisions`가 5분 주기로 계속 자라는 운영 테이블
      이기 때문**(사실, §115.2와 정합). 앞으로는 조회 시각을
      함께 명시한다.
- [x] **`strategy_alignment=1.0` 재확인**: 이번 턴 기준
      `event_overlay 2,535 + market_overlay 42 = 2,577`. `market_
      overlay=42`는 과거 확정 구간(2026-06-18)이라 조회 시점과
      무관하게 안정적이나, `event_overlay` 쪽은 계속 늘어난다
      (사실).
- [x] **핵심 정정**: "`strategy_alignment`(core 기준)는 설계
      의도대로 죽어 있는 항"이라는 §6.12의 표현은 **과했다**.
      `strategy_selection.py`를 재확인한 결과, `core`도 `event_
      overlay` 전용 override와 **무관하게** `regime_label ∈
      {bullish_trend, event_driven_unstable}`이면서 `risk_tone
      ≠ risk_off`이면 `strategy_alignment=1`에 도달할 수 있는
      **일반 경로가 이미 존재**한다(사실, 코드 재확인). 전체
      이력에서 `core` 소스의 `(regime_label, risk_tone)` 조합을
      전수 조사한 결과 `bullish_trend`(2,593건)/`event_driven_
      unstable`(60건) 관측 사례가 **전부 `risk_off`와 겹쳐** 이
      경로에 도달한 사례가 0건이었다(사실).
- [x] **낮춰 쓴 최종 판정**: `strategy_alignment`(core)는 "설계
      배제"가 아니라 **"일반 경로는 있으나 상류 `risk_tone`
      상시화 때문에 아직 도달 사례가 없는 항"**으로 정정 —
      `regime_tailwind`와 **근본 원인이 사실상 동일**하다.
      `event_overlay` 전용 override는 실재하지만 이것이 "core가
      죽은 이유"는 아니다(별개의 우회 메커니즘일 뿐). `regime_
      tailwind` 해석(설계 정상, 상류 이상의 부산물)은 **정정
      없이 유지**한다.

상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
entry_signal_v1.md` §117.

### 6.14 SPPV-2.130 — 산식 재설계 준비: 4개 항목 역할 재분류(신규,
2026-07-29 KST, 완료 — "고정 여부 확인" 단계 종료 선언)

**[SPPV-2.130] `regime_tailwind`/`strategy_alignment` "고정
여부 확인" 단계(§6.12/§6.13, §116/§117)는 이 항목으로 종료한다.**
이번 턴은 그 결과를 바탕으로 4개 항목(`coverage_score`/
`regime_tailwind`/`relative_activity`/`strategy_alignment`)을
설계 관점에서 재분류하는 **산식 재설계 준비 단계**다.

- [x] **트랙 A-1(`coverage_score`)**: 전체 이력에서 실제 관측
      값이 `1.0`(36,383건)/`0.1429`(725건, 그중 723건이
      `eligibility_low_feature_coverage`로 하드 차단) 단 2개뿐임을
      확인 — 하드 게이트 통과 후에는 100% 상수. **분류: 다른
      계층으로 이관 검토.**
- [x] **트랙 A-2(`regime_tailwind`)**: `entry_score` penalty +
      core risk-off 하드 게이트가 이미 같은 신호를 강하게
      처리하고 있어 `ranking`의 0.03 가중치는 정책적 존치
      근거가 약함. **분류: 역할 축소 검토.**
- [x] **트랙 B-1(`relative_activity`)**: 4계층(entry_score/
      ranking/eligibility/core guard) 역할표 재정리 — 소프트
      2곳(entry+ranking)은 과잉 중복, 하드 2곳은 국면별 차등
      정당화 여지 있음. **분류: 중복 제거/정리 검토**(소프트
      2곳이 1차 대상).
- [x] **트랙 B-2(`strategy_alignment`)**: `entry_score`+
      `ranking`이 완전히 동일한 조건 집합을 검사 — 현재는 미발동
      이나 살아나면 구조적으로 확정된 중복. **분류: 중복 제거/
      정리 검토**(시급성은 낮음).
- [x] **우선순위**: 1순위 `coverage_score`, 2순위 `relative_
      activity`, 3순위 `strategy_alignment`, 4순위 `regime_
      tailwind`.
- [x] **설계안 비교 단계 진입 가능 여부**: 1·2순위는 **즉시
      설계안(A/B) 비교 단계 진입 가능**(추가 사실 확인 불필요).
      3·4순위는 방향은 확정됐으나 우선순위상 후순위로 대기.

상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
entry_signal_v1.md` §118.

### 6.15 SPPV-2.131 — `coverage_score`/`relative_activity` 설계안
A/B 비교(신규, 2026-07-29 KST, 완료 — §6.14 마지막 판정 재보정)

**[SPPV-2.131에서 재판정]** §6.14의 "1·2순위는 즉시 설계안(A/B)
비교 단계 진입 가능(추가 사실 확인 불필요)"이라는 판정을
**부분 완료로 재조정한다** — 이번 턴에 실제로 A/B를 비교해 본
결과, "방향"은 확정할 수 있었으나 "diff 초안 착수"에는 각각
1개씩 추가 확인 과제가 남아 있음을 확인했다(이력 보존, 원문은
그대로 두고 이 항목에서 갱신 사실만 추가).

- [x] `coverage_score` A안(ranking 제거, eligibility 전용
      이관)/B안(가중치 축소) 비교 — **A안 우선 권고**. 다만
      `ranking_score` 절대 스케일이 0.20 낮아지면 `_CORE_RISK_
      OFF_RANKING_MIN_SCORE=0.48` 등 기존 절대 threshold와의
      상호작용을 먼저 재계산해야 diff 착수 가능(사실, 코드
      구조 확인 — `ranking_score`가 하드 게이트 파라미터로
      직접 쓰임).
- [x] `relative_activity` A안(소프트 2곳 중 1곳만 유지)/B안
      (소프트 유지+역할 분리) 비교 — **A안 우선 권고**. 다만
      "`entry_score` 쪽 유지 vs `ranking_score` 쪽 유지" 중
      어느 것이 하드 게이트와 더 정합적인지는 아직 실측 데이터로
      확정하지 않았다(잠정 해석만 제시).
- [x] 최종 비교표 작성 완료(§119.4).
- [x] "지금 바로 diff 초안으로 넘어갈 안" 판정 — **둘 다 아직
      아니다**. 각 1개씩의 확인 과제(§119.6 1·2순위) 완료 후
      다음 턴에서 diff 초안 착수 가능.

상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
entry_signal_v1.md` §119.

### 6.16 SPPV-2.132 — 남은 2개 확인 과제 검증(신규, 2026-07-29
KST, 완료 — §6.15의 미확정 2건을 닫음)

- [x] **`coverage_score` A안 threshold 연쇄영향 정량 재계산**:
      `0.48`/`0.22`(코드 상수 `_CORE_RISK_OFF_RANKING_MIN_SCORE`/
      `_CORE_RISK_OFF_SHADOW_MIN_SCORE`) 기준 shadow 재계산 결과,
      단순 제거 시 `0.48` 통과율이 일반 BUY 경로 전체 이력 기준
      14.8%→0.34%, `0.22` 통과율이 `ranking_blocked` 게이트
      내부 100%→0.4%로 붕괴함을 확인(사실, 신규 DB 재계산).
      **판정: A안은 threshold 재설계와 반드시 묶여야 하며, 이번
      턴 기준 diff 착수 불가.**
- [x] **`relative_activity` 유지 위치(entry_score vs ranking_
      score) 비교**: 1안(ranking에서 제거, entry 유지)과 2안
      (entry에서 제거, ranking 유지) 모두 threshold 통과율
      영향이 작음(14.8%→14.3%, 양안 동일)을 확인 — `coverage_
      score`와 달리 이 항목은 **threshold 재설계 없이 안전하게
      정리 가능**함을 확정(사실, 신규 DB 재계산). diff 범위
      비교 결과 **1안(ranking에서 제거)이 더 보수적**(entry_
      score의 `buy_candidate_threshold=0.65` 하드 게이트를
      건드리지 않음). **판정: 1안은 지금 바로 diff 초안 작성
      가능.**
- [x] **최종 판정**: `coverage_score`=diff 보류(threshold
      재설계 선행 필요), `relative_activity`=**1안으로 diff
      초안 작성 가능**(이번 턴 첫 실행 가능 판정).

상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
entry_signal_v1.md` §120.

### 6.17 SPPV-2.133 — `relative_activity` 1안 diff 실제 적용(신규,
2026-07-29 KST, 완료 — §6.16의 diff 착수 가능 판정을 실행에 옮김)

- [x] **코드 변경**: `src/agent_trading/services/deterministic_
      trigger_engine.py`의 `_build_buy_ranking_score`에서
      `relative_activity` 계산/항(`0.10*relative_activity`)과
      미사용이 된 `signal_feature_snapshot` 매개변수를 제거.
      `entry_score` 쪽(`_build_entry_score`의 `relative_activity_
      bonus`)은 변경 없음. `coverage_score`/threshold 상수는
      손대지 않음(사실).
- [x] **최소 검증**: `tests/services/test_deterministic_trigger_
      engine.py`(20 passed), `test_trigger_proxy_attribution.py`
      + `test_decision_orchestrator.py` + `test_core_risk_off_
      topk_projection.py`(93 passed), `test_decision_factory.py`
      + `test_expected_value_gate.py`(12 passed), 하네스
      `accept backend-file`(PASS). Full pytest/외부 API 호출
      없음(사실).
- [x] **테스트 보정 1건**: `test_trigger_engine_marks_risk_off_
      exception_eligible_for_strong_core_setup`가 `_CORE_RISK_
      OFF_RANKING_MIN_SCORE=0.48` 경계 바로 위(구 ranking_score
      ≈0.46~0.48대)에 있던 fixture라 항 제거로 통과 기준을
      밑돌게 됨 — 테스트 의도(강한 core setup에서 예외 자격
      성립)를 유지한 채 `turnover_surge_ratio`만 1.60→2.50으로
      최소 보정(신규 ranking_score=0.4849). §120에서 예측한
      "일반 모집단 영향은 미미(14.8%→14.3%)하나 개별 경계 사례는
      이동할 수 있음"이 실제 코드 반영 단계에서 구체적으로
      확인된 사례(해석).
- [x] **범위 준수**: `coverage_score` threshold 재설계는 이번
      턴에서 착수하지 않음(별도 트랙 유지).

상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
entry_signal_v1.md` §121.

### 6.18 SPPV-2.134 — `relative_activity` 1안 적용 후 영향 확인 +
다음 설계 분기 확정(신규, 2026-07-29 KST, 완료)

- [x] **배포 확인**: `app`/`ops-scheduler` 컨테이너의 코드가
      병합된 `main`과 동일(md5sum 일치), 사이클마다 새 서브프로세스
      기동 구조라 병합 직후 첫 사이클부터 신규 코드 적용됨을 확인
      (사실).
- [x] **적용 전/후 비교**(read-only): 병합 직전 30분(n=120) vs
      병합 이후 1개 사이클(n=15) — `ranking_score` 평균/중앙값
      0.3358/0.3037→0.3319/0.2811(미세 이동, 표본 극소로 해석
      보류), `ranking_blocked` 비중 46.7%→53.3%(표본 15건 단일
      창 변동, 의미 있는 변화로 해석하지 않음), `buy_candidate`
      0/120→0/15(**변화 없음**), `shadow_topk_exception_v2`
      발동 0건 유지(**변화 없음**).
- [x] **관측 한계 명시**: 병합 이후 경과 약 6분, 사이클 1회만
      확보 — `ranking_score` 분포의 실제(장기) 이동 여부는 이번
      자료로 판정 불가(미확정, 명시).
- [x] **핵심 병목 재판정**: `eligibility_core_risk_off_ranking_
      blocked`가 여전히 최다 차단 사유, `buy_candidate`는 여전히
      0 — 핵심 병목은 여전히 `coverage_score`+절대 threshold
      (`0.48`/`0.22`) 조합(기존 판정 재확인, 신규 반박 근거 없음).
- [x] **다음 1순위 결정**: **2안 채택** — `coverage_score`
      threshold 재설계로 바로 가지 않고, 1~2 거래일 추가 운영
      관측을 먼저 축적한 뒤 §120 예측치(14.8%→14.3%)와의 실측
      부합 여부를 확인하고 진행 여부를 결정.

상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
entry_signal_v1.md` §122.

### 6.19 SPPV-2.135 — `relative_activity` 1안 적용 후 운영 관측
추가 축적(신규, 2026-07-29 KST, **진행 중** — 관측 단계 미종료)

- [x] **관측 창 크기 확인**: 병합 이후 실제 경과 시간 약 41분,
      초기 1사이클(n=15/16) 대비 누적 약 9사이클(n=134)로 확대.
      "5거래일 수준 관측"은 캘린더 시간 제약으로 이번 턴에서
      확보 불가함을 명시(사실).
- [x] **초기 창 vs 누적 창 비교**: `ranking_score` 평균/중앙값
      거의 동일(0.3305/0.2811 → 0.3323/0.2983), `ranking_
      blocked` 비중 56.2%→47.8%(병합 이전 기준값 46.7%에 더
      가깝게 회귀 — 초기 1사이클이 편향 표본이었을 가능성). `buy_
      candidate`/`APPROVE`/`order_request`/`final_intent='buy'`/
      `shadow_topk_exception_v2`는 초기·누적 창 모두 **0으로
      동일**(변화 없음).
- [x] **`eligibility_passed=True` 4건 검토**: 전부 동일 core
      종목·동일 ranking_score(0.5428)의 반복 관측, `buy_
      candidate=False`/`primary=WATCH`로 귀결 — 기존 WATCH 고정
      패턴으로 판단, diff 효과로 해석하지 않음.
- [x] **핵심 병목 재판정**: `coverage_score`+절대 threshold
      (`0.48`/`0.22`) 조합으로 재확인(신규 반박 근거 없음).
- [x] **다음 1순위 결정**: **2안(추가 관측 연장) 유지** — 캘린더
      시간이 41분만 경과해 "5거래일 수준" 요청 기준에 크게
      못 미침. `coverage_score` threshold 재설계 착수는 다음
      거래일 이후 재확인 후 결정.

**[PLAN] 상태 요약**: `relative_activity` 적용 후 관측 단계는
**아직 진행 중**(종료 아님). `coverage_score` 재설계 착수 준비는
**아직 되지 않음**(추가 관측 필요).

상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
entry_signal_v1.md` §123.

### 6.20 SPPV-2.136 — `relative_activity` 1안 적용 후 운영 관측
추가 축적(2차, 최종 판정)(신규, 2026-07-30 KST, **완료 — 관측
단계 종료**)

- [x] **관측 창 확대 확인**: 병합 이후 실제 경과 약 23시간, gate
      모집단 n=616/전체 BUY-path n=1,435 — 이전 두 턴(n=15/134)
      대비 4~40배 확대, 병합 이전 1일치(gate n=1,037)와 같은
      자릿수 도달(사실).
- [x] **게이트 모집단 기준 재집계(§120과 동일 정의로 통일)**:
      `ranking_blocked` 비중 병합 전 3일 99.9~100.0% → 병합
      직전 30분 93.3% → 초기 1사이클 90.0% → 누적 23시간 90.7%
      — 병합 직전부터 이미 이동 시작, 예측(제거 시 소폭 하락)과
      반대 방향·더 큰 폭 → **diff 인과 효과 아님(교란 요인)**으로
      판정.
- [x] **핵심 출력 변수 안정성 확인**: `buy_candidate`/`APPROVE`/
      `order_request`/`final_intent='buy'`/`shadow_topk_
      exception_v2`는 표본이 40배 확대되는 3개 관측 창 전부에서
      **일관되게 0** — 우연한 소표본 효과가 아니라 안정적 패턴으로
      판단.
- [x] **`eligibility_passed=True`(전체 BUY-path) 125건 상세**:
      `001450`/`001800`/`000810` 3개 종목의 반복 관측(고정
      ranking_score 4종)뿐, 전부 `buy_candidate=False` — 기존
      WATCH 고정 패턴 재확인, diff 효과 아님.
- [x] **핵심 병목 재판정**: `coverage_score`+절대 threshold
      (`0.48`/`0.22`) 조합 재확인(신규 반박 근거 없음).
- [x] **다음 1순위 결정(전환)**: **1안(coverage_score+threshold
      재설계 비교 착수) 채택** — SPPV-2.134/2.135의 "2안(관측
      연장)"에서 전환. 표본이 병합 이전 1일치와 같은 자릿수에
      도달했고 핵심 출력 변수가 그 규모에서도 안정적으로 0을
      유지해, 추가 관측을 늘려도 이 결론이 달라질 가능성은 낮다고
      판단.

**[PLAN] 상태 요약**: `relative_activity` 적용 후 관측 단계는
**이번 턴으로 종료**. `coverage_score`+threshold 재설계 비교
착수 준비는 **완료**(단, 완화안 확정/코드 diff 착수는 별도 승인
필요).

상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
entry_signal_v1.md` §124.

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
