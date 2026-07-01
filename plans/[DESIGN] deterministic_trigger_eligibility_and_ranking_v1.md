# Deterministic Trigger Eligibility + Ranking V1 설계

> 작성일: 2026-06-17
>
> 목적:
> 현재 [`src/agent_trading/services/deterministic_trigger_engine.py`](../src/agent_trading/services/deterministic_trigger_engine.py)
> 의 `절대 threshold 중심 candidate 생성` 구조를
> `eligibility → ranking → candidate` 구조로 재설계하기 위한
> 구체 기준을 정의한다.

## 1. 왜 이 설계가 필요한가

현재 구현은 다음 특성을 가진다.

- `BUY_CANDIDATE`는 `entry_score >= 0.65`일 때만 생성된다.
- `WATCH`는 `watch_score >= 0.45`이면 생성된다.
- `core + no position` 경로에서는 `buy_gap <= 0.20`이면
  사실상 `WATCH` 바닥값 `0.45`가 부여된다.
- feature가 비어도 `_normalize_signed_score(None) == 0.5`라서
  정보 부족 상태가 중립 강도로 취급된다.

즉, 현재 구조는
`BUY는 좁은 절대 임계값`,
`WATCH는 넓은 완충 구간`
형태다.

이 구조는 운영 관측에서 다음 문제를 만들 수 있다.

1. 시장이 약간만 애매해져도 `BUY_CANDIDATE`가 급감한다.
2. feature coverage가 부족하거나 중립인 종목이 `WATCH`로 과다 유입된다.
3. `최대 기대 수익률` 관점에서 중요한
   `상대적으로 더 좋은 종목을 고르는 기능`보다
   `절대 문턱 통과 여부`가 지나치게 커진다.

따라서 다음 단계는
단순히 threshold 숫자를 조정하는 것이 아니라,
**적격성 판단과 상대 순위화를 분리하는 구조**여야 한다.

---

## 2. 최종 목표와의 정렬

핵심 목표는
`위험조정 기대수익률 최대화`다.

이 목표에 맞는 deterministic trigger는 다음 성질을 가져야 한다.

1. 진입 불가 또는 기대값이 너무 낮은 종목은
   초기에 제거해야 한다.
2. 남은 후보는
   `절대 점수`보다 `상대 기대값`에 따라 우선순위를 매겨야 한다.
3. `WATCH`는 기본 상태가 아니라
   `진입 직전 경계 상태` 또는 `후속 관찰 가치가 높은 상태`로 제한해야 한다.
4. 같은 장세라도
   `core / market_overlay / held_position`
   의 정책이 달라야 한다.

즉, 이 설계의 목적은
`BUY를 더 많이 만들기`가 아니라,
**적격 후보 집합 안에서 더 좋은 기대값을 가진 종목에
limited capital을 우선 배분하는 것**이다.

---

## 3. 현재 코드 기준 문제 정리

기준 코드:

- [`src/agent_trading/services/deterministic_trigger_engine.py`](../src/agent_trading/services/deterministic_trigger_engine.py)

### 3.0 2026-06-23 ~ 2026-07-01 실증 검증 반영

2026-06-23부터 2026-07-01 장중까지의 실제 `trade_decisions`와
KIS 일봉 후행 수익률을 붙여 검증한 결과,
현재 임계값 문제는 단순히 `BUY threshold`가 높다는 식으로
해석하면 안 된다.

검증 방식:

- 중복 cycle 왜곡을 줄이기 위해 `symbol + trade_date`별 첫 decision만 사용
- 후행 수익률 계산이 가능한 2026-06-23 ~ 2026-06-30 구간을 평가 표본으로 사용
- 표본: 57개 symbol, 186개 symbol-day
- proxy 지표:
  - T+1 종가 수익률
  - T+3 종가 수익률
  - T+3 MFE / MAE

핵심 관측:

- `BUY_CANDIDATE`는 0건이었다.
- `entry_score >= 0.65`도 0건이었다.
- `entry_score`와 T+3 수익률의 상관은 약 `-0.21`로,
  현재 score가 후행 기대수익률을 선형적으로 잘 설명한다고 보기 어렵다.
- `0.55 <= entry_score < 0.65` 구간은
  T+3 평균 수익률이 약 `-3.56%`로 나빠,
  `buy_candidate_threshold`를 단순히 0.55 부근으로 낮추는 것은
  기대수익률 극대화 기준에 부합하지 않는다.
- `primary_candidate=NO_ACTION` 중에서도
  T+3 MFE가 5% 이상인 missed opportunity가 반복적으로 발견됐다.
  이 문제는 threshold 숫자보다
  risk-off / source / event overlay 처리 방식과 더 관련이 컸다.

필터별 관측:

- `eligibility_low_relative_activity`
  - 26건
  - T+3 평균 약 `-2.85%`
  - hit rate 약 `26.9%`
  - 현재 기준에서는 유지가 타당하다.
- `eligibility_source_type_blocked`
  - 45건
  - T+3 평균 약 `-4.36%`
  - hit rate 약 `13.3%`
  - 현재 차단 정책은 기대수익률 관점에서 유지가 타당하다.
- `eligibility_core_risk_off_ranking_blocked`
  - 22건
  - T+3 평균 약 `+3.16%`
  - hit rate 약 `72.7%`
  - 과도 차단 가능성이 높으므로 우선 완화 실험 대상이다.
- `event_overlay`
  - 19건
  - T+1 평균 약 `+3.40%`
  - T+3 평균 약 `+2.38%`
  - hit rate 약 `73.7%`
  - 후보 전환 비중과 ranking 우선순위를 높일 근거가 있다.

설계 결론:

1. `buy_candidate_threshold=0.65`는 바로 낮추지 않는다.
2. `watch_candidate_threshold=0.45`는 넓은 관찰 bucket을 만드는 경향이 있어
   상향 또는 top-k projection 방식으로 재설계한다.
3. `eligibility_core_risk_off_ranking_blocked`는 hard block보다
   penalty + top-k 제한 방식으로 완화 실험한다.
4. `event_overlay`는 `core`보다 기대수익률 proxy가 좋았으므로
   source bonus 또는 별도 event top-k lane을 둔다.

### 3.1 threshold가 너무 직접적이다

현재는 아래와 같이
candidate 생성이 거의 threshold 비교에 의해 바로 결정된다.

- `buy_candidate_threshold = 0.65`
- `watch_candidate_threshold = 0.45`
- `reduce_candidate_threshold = 0.60`
- `sell_candidate_threshold = 0.75`

문제:

- score calibration이 조금만 흔들려도 candidate 개수가 급변한다.
- 기대수익률 최적화보다
  점수 calibration 안정성에 결과가 과도하게 의존한다.

### 3.2 WATCH가 너무 넓다

현재 watch score는 대략 아래 구조다.

- `0.45 <= entry_score < 0.65`
- `0.45 <= exit_score < 0.75`
- `core + no position`이면 `buy_gap <= 0.20`일 때 WATCH

문제:

- `BUY 직전 후보`뿐 아니라
  `애매한 종목 대부분`이 WATCH로 들어갈 수 있다.
- 결과적으로 `WATCH 증가 = BUY 부족` 현상이 생기기 쉽다.

### 3.3 missing coverage가 중립으로 처리된다

현재 `_normalize_signed_score(None) == 0.5`다.

문제:

- 정보가 없는 종목이 `약한 중립`이 아니라
  `관찰 가치가 있는 종목`처럼 해석될 수 있다.
- 기대수익률 관점에서는
  정보 부족은 `관망 가치`보다 `근거 부족`에 더 가깝다.

### 3.4 상대 순위가 없다

현재는 universe 내 상대 ranking 없이
종목별 절대 score만 본다.

문제:

- 전체 시장이 약한 날 `BUY=0`이 되기 쉽다.
- 반대로 전체 시장이 강한 날에는
  budget보다 많은 종목이 동시에 BUY threshold를 넘을 수 있다.
- 자본 배분은 본질적으로 상대 비교인데,
  candidate 생성이 이를 반영하지 못한다.

### 3.5 `eligibility_core_risk_off_ranking_blocked`는 바로 해제하면 안 된다

실증 검증에서
`eligibility_core_risk_off_ranking_blocked` bucket의
T+3 평균 수익률과 hit rate가 좋았지만,
이를 곧바로 hard block 해제로 연결하면 안 된다.

이유:

- 현재 차단 사유는 단순 ranking 하나만이 아니라
  risk-off regime 하에서의 보수적 진입 억제 장치다.
- 무차별 해제 시
  `risk_off` 구간에서 BUY 후보가 과도하게 증가할 수 있다.
- 따라서 1차는 `hard block -> full allow`가 아니라
  `hard block 유지 + shadow penalty 비교`가 맞다.

확정 원칙:

1. authoritative path는 당분간 `hard_block_v1` 유지
2. 실험 경로는 `shadow_penalty_v1` metadata로만 먼저 기록
3. shadow 결과가 반복적으로 유의미하면
   이후 `apply_penalty_v1`로 승격 검토

---

## 4. 제안 구조

V1.1 제안 구조는 아래 3단계다.

1. `Eligibility Gate`
2. `Ranking Layer`
3. `Candidate Projection`

흐름:

```text
signal_feature_snapshot
  + market_regime
  + strategy_selection
  + portfolio_allocation
  + position_snapshot
    -> eligibility 평가
    -> 적격 후보만 ranking
    -> BUY / WATCH / REDUCE / SELL candidate projection
```

이 구조에서 중요한 원칙:

- `eligibility`는 하한선이다.
- `ranking`은 상대 우선순위다.
- `candidate projection`은 downstream 설명/정책 연결용이다.

---

## 5. 새 출력 계약

기존 [`DeterministicTriggerAssessment`](../src/agent_trading/services/deterministic_trigger_engine.py)
를 확장하는 방향을 권장한다.

### 5.1 추가 필드

- `eligibility_passed: bool`
- `eligibility_reasons: tuple[str, ...]`
- `coverage_score: float | None`
- `ranking_score: float | None`
- `ranking_percentile: float | None`
- `ranking_bucket: str | None`
- `candidate_mode: str`
  - 예: `absolute_threshold_v1`
  - 예: `eligibility_ranking_v1`

### 5.2 의미

- `entry_score`
  - 절대적 진입 성향 점수
- `eligibility_passed`
  - 최소 요건 충족 여부
- `ranking_score`
  - 같은 batch 내부 상대 우선순위 점수
- `primary_candidate`
  - 최종 대표 candidate

즉, 이후에는
`entry_score는 높았지만 eligibility 탈락`,
`eligibility는 통과했지만 ranking이 낮아 WATCH`,
`ranking 상위라 BUY`
를 분리해서 볼 수 있어야 한다.

---

## 6. Eligibility Gate 설계

Eligibility는
`이 종목을 지금 진입 후보군에 올릴 자격이 있는가`
를 판단한다.

여기서 탈락한 종목은 ranking에 넣지 않는다.

### 6.0 저유동성 BUY 실행 가능성 gate 추가 원칙

최근 장중 운영에서
`deterministic primary_candidate = NO_ACTION`
상태의 초저유동성 `core` 종목이
AI override로 `APPROVE`까지 승격되고,
결과적으로 `시장가 대량 미체결 주문`이 반복 제출된 사례가 확인됐다.

핵심 목표인 `위험조정 기대수익률 최대화` 기준으로 보면,
이 문제는 단순 보수성 이슈가 아니라
`실행 불가능 또는 과도한 market impact가 예상되는 주문이
후보군에 남는 구조`
로 봐야 한다.

따라서 BUY eligibility에는
`신호 강도`뿐 아니라
`실행 가능성(execution feasibility)`을 포함해야 한다.

중요:

- 이 gate의 목적은 `BUY 수를 줄이기`가 아니다.
- 목적은 `기대값이 음수로 기울 가능성이 매우 큰 초저유동성 진입`을
  후보군 밖으로 먼저 제거하는 것이다.
- 즉, alpha 차단이 아니라
  `실행 비용이 alpha를 압도하는 구간`을 deterministic하게 제외하는 작업이다.

권장 구조:

1. `Universe / Eligibility` 단계에서 저유동성 BUY 비적격 종목 제거
2. `AI override`는 `적격 후보군 내부`에서만 허용
3. `Sizing / Execution` 단계에서 participation cap과 execution style로
   잔여 market impact를 추가 통제

즉, blanket ban이 아니라
`실행 불가능성 기반의 계층별 차단`이 맞다.

### 6.1 공통 원칙

BUY eligibility는 아래를 기본으로 본다.

1. `source_type != held_position`
2. `portfolio_allocation.max_new_capital_pct > 0`
3. `market_regime.risk_tone != risk_off` 또는
   `risk_off`라도 별도 완화 규칙 충족
4. feature coverage 충분
5. `slow_score`, `overall_score`가 최소 바닥 미달이 아님

### 6.2 권장 eligibility rule set

#### E1. source type 적격성

- `held_position`은 BUY eligibility 즉시 탈락
- `core`, `market_overlay`, `manual`만 BUY eligibility 대상

reason code 예:

- `eligibility_source_type_blocked`
- `eligibility_source_type_allowed`

#### E2. allocation budget 적격성

- `portfolio_allocation.max_new_capital_pct <= 0`
  -> BUY eligibility 탈락
- `recommended_max_order_value <= 0`
  -> BUY eligibility 탈락

reason code 예:

- `eligibility_allocation_blocked`
- `eligibility_allocation_available`

#### E3. feature coverage 적격성

coverage score 예시:

- `overall_score` 존재
- `fast_score` 존재
- `slow_score` 존재
- 핵심 reason code 존재
- snapshot freshness 적격

예시 계산:

- 핵심 4개 중 채워진 비율을 `coverage_score`로 사용

권장 기준:

- `coverage_score < 0.75`
  -> BUY eligibility 탈락
- `coverage_score < 0.50`
  -> WATCH eligibility도 기본 탈락

reason code 예:

- `eligibility_low_feature_coverage`
- `eligibility_feature_coverage_ok`

#### E4. regime 적격성

기본 규칙:

- `risk_off + bearish_trend + high_volatility`
  조합이면 BUY eligibility 탈락
- `range_bound`는 탈락이 아니라 ranking penalty

reason code 예:

- `eligibility_risk_off_block`
- `eligibility_regime_pass`

#### E5. signal floor 적격성

예시 기준:

- `overall_score < -0.10`
  -> BUY eligibility 탈락
- `slow_score < -0.15`
  -> BUY eligibility 탈락

#### E6. 유동성 / 체결 가능성 적격성

BUY eligibility는 아래 실행 가능성 조건을 추가로 본다.

1. 당일 누적 거래대금 하한
2. 당일 누적 거래량 하한
3. 예상 주문대금 / 당일 누적 거래대금 비율 상한
4. 예상 주문수량 / 당일 누적 거래량 비율 상한
5. 호가 정보 부재 + 저유동성 동시 발생 시 BUY eligibility 탈락 또는 강한 penalty

권장 이유:

- `현재가 기반 sizing`만으로는
  실제 체결 비용과 market impact를 반영할 수 없다.
- 특히 초저유동성 우선주/스팩/관리성 종목에서는
  `시장가 1회 제출`만으로도 기대값이 급격히 악화될 수 있다.
- 기대수익률 극대화 관점에서도
  `실행비용이 alpha를 압도하는 구간`은
  deterministic하게 제거하는 편이 맞다.

권장 reason code 예:

- `eligibility_low_turnover`
- `eligibility_low_intraday_volume`
- `eligibility_participation_rate_blocked`
- `eligibility_quote_depth_unknown`

권장 운영 원칙:

- `market_overlay`뿐 아니라 `core` BUY 경로에도 동일 적용
- `held_position`의 SELL/REDUCE에는 직접 적용하지 않음
- 단, BUY add-on 경로가 생기면 그때는 적용 대상에 포함

핵심은
`상대 ranking 이전에 절대적으로 너무 약한 종목`은 제거하는 것이다.

reason code 예:

- `eligibility_negative_overall_floor`
- `eligibility_negative_slow_floor`

### 6.3 WATCH eligibility

WATCH는 BUY보다 느슨하지만,
아무 종목이나 들어가면 안 된다.

권장 기준:

- BUY eligibility 실패 중에서도
  `coverage 부족`, `allocation 0`, `명백한 bearish`는
  WATCH보다 `NO_ACTION`으로 보낸다.
- WATCH는 아래 경우에만 허용:
  - BUY eligibility 대부분 충족
  - 다만 ranking이 낮거나 entry_score가 경계대
  - 또는 event/market follow-up 가치가 있는 종목

즉, WATCH는
`약한 종목 전체의 쓰레기통`이 아니라
`다음 승격 가능성이 있는 경계 후보군`이어야 한다.

---

## 7. Ranking Layer 설계

ranking은
`eligibility를 통과한 종목들 사이에서
어느 종목이 더 기대값이 높은가`
를 정렬하는 계층이다.

### 7.1 ranking 대상

BUY ranking 대상:

- source_type in (`core`, `market_overlay`, `manual`)
- BUY eligibility 통과

SELL/REDUCE ranking 대상:

- source_type == `held_position`
- 보유수량 존재
- exit eligibility 통과

### 7.2 ranking score 기본식

BUY ranking score 초안:

```text
ranking_score_buy =
  0.45 * normalized(entry_score)
  + 0.20 * normalized(slow_score)
  + 0.15 * regime_tailwind
  + 0.10 * strategy_alignment
  + 0.10 * allocation_quality
  - penalties
```

설명:

- `entry_score`를 그대로 쓰되,
  ranking의 중심은 유지
- `slow_score` 비중을 높여
  너무 단기적인 fast noise를 줄임
- `allocation_quality`는
  단순 `capital > 0`이 아니라
  실제 추천 자본 여유 수준 반영

### 7.3 regime별 보정

권장:

- `bullish_trend + risk_on`
  -> ranking score 소폭 가산
- `range_bound`
  -> ranking은 유지, BUY top-k 수 축소 가능
- `bearish_trend + risk_off`
  -> BUY ranking 강한 penalty 또는 eligibility 탈락

즉,
regime는 개별 종목 점수만 건드리는 것이 아니라
`후보 수(k)`에도 영향을 줘야 한다.

### 7.4 source_type별 보정

#### core

- 가장 안정적인 BUY source
- 기본 k 산정의 중심

#### market_overlay

- short-term opportunity 가능성이 높으므로
  fast score / turnover 성분 가중 가능
- 단, false positive가 높을 수 있어
  core보다 더 높은 coverage 요건 권장

#### manual

- operator watchlist 성격
- ranking 대상에는 넣되
  기본적으로 bonus는 주지 않는다

#### held_position

- BUY ranking 대상에서 제외
- 별도 exit ranking 사용

### 7.5 percentile / bucket

ranking 결과는 절대 점수만 저장하지 말고
batch 내부 percentile도 저장하는 것이 좋다.

예:

- `ranking_percentile = 0.92`
- `ranking_bucket = "top_10pct"`

이 값이 있어야
날짜별 BUY 부족이
`절대 점수 약세`인지
`상대 순위는 있었지만 eligibility에서 탈락했는지`
를 분리해서 볼 수 있다.

---

## 8. Candidate Projection 설계

eligibility와 ranking을 계산한 뒤,
최종 candidate를 projection한다.

### 8.1 BUY candidate

BUY는 아래 구조를 권장한다.

1. BUY eligibility 통과
2. ranking 대상 포함
3. batch 내 `top-k` 또는 `percentile cutoff` 충족

예:

- `top_k_buy = 3`
- 또는 `ranking_percentile >= 0.85`

권장:

- `top-k`와 `minimum ranking floor`를 함께 사용

예:

- 상위 3개라도 `ranking_score < 0.55`면 BUY 미부여

즉,
`무조건 k개 매수`가 아니라
`최소 질 기준을 넘는 상위 k개`다.

### 8.2 WATCH candidate

WATCH는 다음 경우에만 부여한다.

1. BUY eligibility는 대부분 통과
2. ranking은 top-k에 들지 못함
3. entry_score가 BUY floor 바로 아래
4. 후속 관찰 가치가 존재

권장 WATCH 조건:

- `eligibility_passed == True`
- `buy_candidate == False`
- `ranking_percentile`이 중상위권
- `entry_score`가 BUY floor 근처

즉, WATCH는
`top-k 바로 아래 후보군`
으로 재정의하는 것이 맞다.

### 8.2a 확정안: WATCH top-k + minimum floor

`12-d` 기준으로
`watch_candidate_threshold=0.45`의 절대 threshold 방식은
아래 batch projection 규칙으로 대체하는 설계를 확정한다.

핵심 원칙:

1. WATCH는 `애매한 종목 전체`를 담는 bucket이 아니다.
2. WATCH는 `BUY top-k 바로 아래의 추적 가치가 있는 후보군`만 담는다.
3. 따라서 WATCH는 `eligibility + ranking + minimum floor`를 동시에 만족해야 한다.

확정 규칙:

- BUY projection 전제
  - `eligibility_passed == True`
  - `ranking_score >= 0.55`
  - `ranking 상위 top_k_buy = 3`
- WATCH projection 전제
  - `eligibility_passed == True`
  - `buy_candidate == False`
  - `ranking_score >= 0.50`
  - `entry_score >= 0.52`
  - `ranking_percentile >= 0.60`
  - `WATCH top_k_watch = 8` 이내

즉, WATCH는 아래 집합이다.

```text
eligible
  AND not in BUY top-k
  AND ranking_score >= 0.50
  AND entry_score >= 0.52
  AND ranking_percentile >= 0.60
  AND watch_rank <= 8
```

추가 규칙:

- `eligibility_reasons`에 아래가 있으면 WATCH도 부여하지 않는다.
  - `eligibility_source_type_blocked`
  - `eligibility_low_feature_coverage`
  - `eligibility_allocation_blocked`
  - `eligibility_low_relative_activity`
  - `eligibility_low_turnover`
  - `eligibility_participation_rate_blocked`
- `held_position` 계열 WATCH는 본 규칙과 분리한다.
  - `held_position`은 exit monitoring 목적이므로
    BUY 인접 후보 WATCH와 같은 bucket으로 합치지 않는다.

해석:

- `ranking_score >= 0.50`는
  BUY floor(`0.55`)보다 약간 낮은 최소 질 기준이다.
- `entry_score >= 0.52`는
  기존 `0.45` threshold 대비 완충 구간을 대폭 줄여
  관찰 가치가 약한 종목을 WATCH에서 제거한다.
- `ranking_percentile >= 0.60`와 `top_k_watch = 8`를 같이 두는 이유는
  절대 score만 높고 상대 순위가 밀리는 종목,
  혹은 상대 순위만 간신히 상위권인 저품질 종목을 동시에 줄이기 위해서다.

권장 metadata 저장:

- `decision_json.deterministic_trigger.watch_projection_version = "watch_topk_floor_v1"`
- `decision_json.deterministic_trigger.watch_projection_inputs`
  - `top_k_buy`
  - `top_k_watch`
  - `buy_min_ranking_score`
  - `watch_min_ranking_score`
  - `watch_min_entry_score`
  - `watch_min_percentile`
  - `buy_rank`
  - `watch_rank`

이 metadata가 있어야
후속 shadow mode에서
`old absolute WATCH`와 `new top-k WATCH`를 정확히 비교할 수 있다.

### 8.3 NO_ACTION

다음은 WATCH가 아니라 `NO_ACTION`이 맞다.

- feature coverage 부족
- allocation 불가
- risk_off 강한 차단 구간
- slow/overall 음수 바닥 미달
- source_type 부적격

이렇게 해야 WATCH가 과다해지지 않는다.

### 8.4 core risk-off ranking 완화 실험 플래그 확정안

`12-d`의 다음 단계로
`eligibility_core_risk_off_ranking_blocked`는 아래 실험 플래그 계약으로 고정한다.

mode:

- `hard_block_v1`
  - 현재 authoritative 동작
- `shadow_penalty_v1`
  - 현재 authoritative 결과는 유지
  - 단, metadata에
    `penalty 적용 시 would_pass 여부`를 함께 기록
- `apply_penalty_v1`
  - 후속 단계에서만 사용
  - 실제 eligibility / ranking projection에 penalty 경로를 반영

shadow penalty 규칙:

- 적용 대상
  - `source_type == core`
  - `market_regime.risk_tone == risk_off`
  - `market_regime.regime_label == bearish_trend`
- 기존 hard block 기준
  - `ranking_score < 0.48`
- shadow penalty 계산
  - `adjusted_ranking_score = ranking_score - 0.08`
  - `shadow_min_score = 0.40`
  - `shadow_top_k_cap = 2`
- shadow pass 전제
  - `adjusted_ranking_score >= 0.40`
  - `overall >= 0.0`
  - `slow >= -0.05`
  - `max(volume_surge_ratio, turnover_surge_ratio) >= 1.20`
  - `preferred_strategy in {defensive_low_volatility_rotation, mean_reversion_bounce, event_continuation}`

즉,
ranking hard block을 완전히 없애는 것이 아니라
`risk-off core` 구간에서 극소수 후보만
penalty를 먹인 상태로 비교 평가하는 구조다.

권장 metadata:

- `decision_json.deterministic_trigger.core_risk_off_experiment`
  - `mode = hard_block_v1`
  - `shadow_mode = shadow_penalty_v1`
  - `active`
  - `ranking_min_score = 0.48`
  - `shadow_min_score = 0.40`
  - `shadow_penalty = 0.08`
  - `shadow_top_k_cap = 2`
  - `raw_ranking_score`
  - `adjusted_ranking_score`
  - `shadow_signal_pass`
  - `shadow_activity_pass`
  - `shadow_strategy_pass`
  - `shadow_would_pass`
  - `apply_ready = false`

평가 기준:

- `shadow_would_pass == true` 표본의
  T+1 / T+3 / T+5 후행 수익률
- BUY 후보 증가량
- `risk_off` 구간 churn 증가 여부
- 기존 `event_overlay` / `core` 후보와의 우선순위 충돌 정도

### 8.5 event_overlay source bonus / event top-k lane 확정안

`event_overlay`는 실측상
`core`보다 후행 기대수익률 proxy가 좋았으므로
즉시 threshold를 낮추기보다
`shadow event lane`을 먼저 붙여 비교한다.

mode:

- `no_bonus_v1`
  - 현재 authoritative 동작
- `shadow_event_lane_v1`
  - authoritative BUY eligibility / candidate는 유지
  - metadata에
    `event lane 적용 시 would_pass 여부`를 함께 기록
- `apply_event_lane_v1`
  - 후속 단계에서만 사용
  - 실제 batch projection에서
    `event_top_k` 후보 lane을 활성화

shadow 규칙:

- 적용 대상
  - `source_type == event_overlay`
- authoritative 유지 원칙
  - `risk_off` regime gate를 우회하지 않는다.
  - `eligibility_passed == false`면
    shadow 결과도 `would_pass = false`
- shadow bonus 계산
  - `adjusted_ranking_score = ranking_score + 0.06`
  - `shadow_min_score = 0.56`
  - `shadow_entry_min_score = 0.54`
  - `shadow_top_k_cap = 2`
- shadow pass 전제
  - `eligibility_passed == true`
  - `adjusted_ranking_score >= 0.56`
  - `entry_score >= 0.54`
  - `overall >= 0.0`
  - `slow >= -0.05`
  - `max(volume_surge_ratio, turnover_surge_ratio) >= 1.15`
  - `preferred_strategy == event_continuation`

즉,
`event_overlay` 전체를 무차별 우대하는 것이 아니라
이미 기본 eligibility를 통과한 event 후보 중
상위 극소수만 별도 lane으로 비교하는 구조다.

권장 metadata:

- `decision_json.deterministic_trigger.event_overlay_experiment`
  - `mode = no_bonus_v1`
  - `shadow_mode = shadow_event_lane_v1`
  - `active`
  - `base_eligibility_passed`
  - `shadow_bonus = 0.06`
  - `shadow_min_score = 0.56`
  - `shadow_entry_min_score = 0.54`
  - `shadow_top_k_cap = 2`
  - `raw_ranking_score`
  - `adjusted_ranking_score`
  - `shadow_signal_pass`
  - `shadow_activity_pass`
  - `shadow_strategy_pass`
  - `shadow_would_pass`
  - `apply_ready = false`

평가 기준:

- `event_overlay` 표본 중
  `shadow_would_pass == true` 후보의
  T+1 / T+3 / T+5 후행 수익률
- 동일 기간 `core` 대비 후보 전환 증가량
- `risk_off` blocked event 표본이
  여전히 `would_pass = false`로 남는지 여부
- 차후 batch projection에서
  `event_top_k = 2` lane 적용 시
  BUY churn 증가 없이 hit rate가 유지되는지 여부

---

## 9. held_position SELL/REDUCE에는 어떻게 적용할 것인가

`held_position`은 BUY와 같은 `eligibility + top-k`를 그대로 쓰지 않는다.

권장 구조:

1. `exit eligibility`
   - 실제 보유수량 존재
   - 최근 risk-reducing sell cooldown 미해당
   - stale / unknown state는 기존 guardrail 우선
2. `exit ranking`
   - `exit_score`
   - concentration 초과 정도
   - regime downside
   - signal deterioration
3. projection
   - 상위 위험 종목은 `SELL_CANDIDATE`
   - 그 아래는 `REDUCE_CANDIDATE`

즉,
BUY에서의 top-k와
SELL/REDUCE에서의 top-k는
동일 규칙이 아니라 별도 정책이어야 한다.

---

## 10. 현재 코드에 대한 구체 변경 포인트

기준 파일:

- [`src/agent_trading/services/deterministic_trigger_engine.py`](../src/agent_trading/services/deterministic_trigger_engine.py)

### 10.1 1차 리팩토링 범위

추가 helper 권장:

- `_build_feature_coverage_score()`
- `_assess_buy_eligibility()`
- `_assess_exit_eligibility()`
- `_build_buy_ranking_score()`
- `_build_exit_ranking_score()`
- `_project_buy_watch_candidates()`
- `_project_sell_reduce_candidates()`

### 10.2 함수 계약 변경

현재 함수는 단일 종목 입력만 받는다.

하지만 `top-k ranking`을 하려면
batch 문맥이 필요하다.

따라서 아래 중 하나가 필요하다.

#### 옵션 A. engine은 단일 종목 평가만 수행

- `eligibility_passed`
- `ranking_score`
- `entry_score`
- `exit_score`

만 반환하고,
실제 top-k 선발은 호출부에서 수행

장점:

- 함수 구조가 단순
- 테스트가 쉬움

단점:

- 호출부가 batch ranking 책임을 가짐

#### 옵션 B. batch-level evaluator 추가

예:

- `assess_deterministic_triggers_for_batch(items: list[...])`

장점:

- top-k 책임이 한 곳에 모임

단점:

- 기존 orchestrator 경로보다 설계 변경 폭이 큼

권장:

- **V1.1은 옵션 A**
- 즉, 단일 종목 engine은 `eligibility + ranking_score`까지만 계산
- batch top-k projection은 `DecisionOrchestrator` 상위 또는 별도 batch helper에서 수행

추가 확정:

- `src/agent_trading/services/deterministic_trigger_engine.py`
  는 계속 단일 종목 평가기 역할을 유지한다.
- `WATCH top-k + minimum floor` projection은
  `DecisionOrchestrator` 상위 batch helper 또는
  별도 `deterministic_trigger_projection` helper에서 수행한다.
- 이유:
  - 현재 engine 입력 계약은 단일 symbol 기준이다.
  - top-k는 universe batch 문맥이 필요하다.
  - 이 책임을 engine 내부로 밀어 넣으면
    orchestrator 호출 경계와 테스트 비용이 크게 커진다.

### 10.3 WATCH guard와의 관계

현재 [`src/agent_trading/services/decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py)
에는 deterministic WATCH 후보일 때
AI가 BUY/SELL로 승격하는 것을 제한하는 guard가 있다.

이 guard는 유지하되,
WATCH 생성 자체를 더 엄격히 줄여야 한다.

즉,
문제의 중심은 guard가 아니라
upstream WATCH candidate 과다 생성이다.

---

## 11. 관측/측정 설계

이 구조는 반드시 측정 가능해야 한다.

### 11.1 저장 권장 항목

`decision_json.deterministic_trigger`에 추가:

- `eligibility_passed`
- `eligibility_reasons`
- `coverage_score`
- `ranking_score`
- `ranking_percentile`
- `ranking_bucket`
- `candidate_mode`
- `batch_buy_rank`
- `batch_buy_candidate_cutoff`

### 11.2 핵심 지표

1. `eligibility_pass_rate`
2. `eligible_but_not_topk_count`
3. `watch_from_eligible_non_topk_count`
4. `watch_from_low_coverage_count`
5. `buy_candidate_topk_fill_rate`
6. `buy_candidate_post_decision_return_proxy`

### 11.3 검증 질문

- BUY 부족의 원인이
  `eligibility 탈락`인가,
  `ranking 하위`인가,
  `AI override`인가
- WATCH 증가의 원인이
  `경계 후보 증가`인가,
  `coverage 부족 종목 유입`인가

이 질문에 답할 수 있어야
기대수익률 최적화 실험이 가능하다.

---

## 12. 단계별 적용 계획

### 단계 1

- `feature coverage`
- `buy eligibility`
- `exit eligibility`
- `ranking_score`

만 추가

이 단계에서는
기존 absolute threshold를 유지하면서
측정만 먼저 붙여도 된다.

### 단계 2

- BUY를 `eligibility + ranking top-k` 구조로 변경
- WATCH를 `eligible but not top-k` 중심으로 축소

### 단계 3

- regime별 `k` 동적화
- source_type별 ranking weight 분리
- post-decision return proxy attribution 연결

---

## 13. 결론

`WATCH 축소 + BUY top-k 후보화`는
핵심 목표인 `최대 기대 수익률`에 부합할 수 있다.

단, 올바른 구현 형태는
단순 threshold 조정이 아니라
아래 구조다.

1. `Eligibility Gate`
   - 진입 자격이 없는 종목을 early reject
2. `Ranking Layer`
   - 적격 종목 안에서 상대 기대값 순위화
3. `Candidate Projection`
   - 상위 후보만 BUY
   - 경계 상위권만 WATCH
   - 나머지는 NO_ACTION

즉, 다음 구현의 방향은
`BUY를 더 많이 만들기`
가 아니라
**적격 후보 집합 안에서 더 높은 기대값 후보에
limited capital을 집중시키는 deterministic 구조를 세우는 것**
이어야 한다.
