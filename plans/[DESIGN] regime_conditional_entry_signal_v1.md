# 국면 분기형 진입 신호 설계 (regime_conditional_entry_signal v1)

작성일: 2026-07-15
상태: **설계 초안 + shadow 계산기 1차 실행 완료 + Phase 2 누적 사이클
구축·실행 완료(§6) + entry_score 중복 penalty ablation 실측 완료(§8) +
중복 억제 시계열 누적·국면 정의 비교 체계 구축(§9) — 실거래/
`entry_score` 반영 없음.**
상위 문서: `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`
(§4 판정 — "국면 분기형 entry 설계로 전환"), `plans/[DESIGN] signal_
predictive_power_validation.md`(§16 이원 기준, §19/§20/§21 근거 실측),
`plans/[ANALYSIS] foundational_design_review_objective_alignment.md`
§8(책임 분리).

## 0. 이 문서의 위치와 경계

이 문서는 SPPV-2.15(종합 판정)가 지시한 **다음 착수 형태**를 실제
설계 문서로 구체화한 것이다. 아래는 **설계 초안**이며 다음 세 가지를
아직 하지 않는다(작업 원칙 준수):

- **운영 `entry_score` 코드를 변경하지 않는다.** 이 문서와 shadow
  스크립트는 read-only 계산기이며 `deterministic_trigger_engine.py`의
  `_build_entry_score()`를 호출/수정하지 않는다.
- **broker submit 경계를 넘지 않는다.** shadow 계산 결과는 로그 파일로만
  남으며 주문 경로에 어떤 영향도 주지 않는다.
- **deterministic risk/compliance/guardrail 경계를 바꾸지 않는다.**
  아래 §3의 통합 방안은 "제안"이며, 실제 코드 변경은 이 문서가 Go
  판정을 받고 사용자가 승인한 뒤 별도 턴에서 진행한다.

## 1. 왜 이 설계가 필요한가 — 실측 근거 요약

`plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`
§1의 종합표(SPPV-2.9~2.14, 87종목×3년×56,753표본)가 이 설계의 유일한
근거다. 핵심 3가지:

1. **정적(static) 단일 가중 신호는 상승/횡보장에서도 안정적 알파를
   내지 못한다** — `overall_score`/`slow_score`/`fast_score` 전부
   §14(3년 확장)에서 pooled 유의성을 잃었고(§14 참고), 가장 근접한
   `risk_adj_momentum_3m`도 marginal(t≈2.0)이다.
2. **하락장에서는 방향이 통째로 바뀐다** — 추세추종형 신호(`fast_
   trend`, `sma5_over_sma20_gap`, `relative_strength_rank_1m` 등)는
   하락장에서 무신호이거나 유의하게 역전하고, 되돌림형 신호(`reversal_
   1m`, `rsi_mean_reversion`)는 **하락장에서만** 유의하다(종합표 §2.1).
3. **국면에 따라 신호를 "전환"하는 것만으로 트랙 최고 성과가
   났다** — `regime_switch_v1`(비하락장=`risk_adj_momentum_3m`,
   하락장=`reversal_1m`)의 2차(3년) pooled 유의성은 T+5=2.60/
   T+20=2.36으로, 이 트랙에서 시도한 모든 정적 신호를 통틀어 가장
   높다(§19.4, §20.2). 다만 1차(최근 12개월) 게이트는 하락장 표본
   부재로 구조적으로 미달이다.

이 세 사실을 종합하면, **가중치를 더 튜닝하거나 새 feature를 하나 더
추가하는 것보다, "국면에 따라 다른 신호를 쓴다"는 구조 자체를 entry
설계에 명시적으로 반영하는 것이 실측으로 뒷받침되는 다음 단계**다.

## 2. 설계 — 국면별 신호 선택 매트릭스

### 2.1 국면 판정 기준(재사용, 신규 로직 없음)

시장 공통 국면은 기존 SPPV-2.6 이후 확립된 방법 그대로 사용한다 —
**KODEX 200(069500, core universe 구성원이지만 평가 대상에서는 제외)의
자기 자신의 rolling 기술적 상태**를 운영 코드 `classify_market_regime()`
(`market_regime.py`)에 입력해, 그날 하나의 라벨을 만든다. 이 라벨을
그날의 모든 개별 종목이 공유한다(§12.2, SPPV-2.6에서 확립).

### 2.2 국면별 채택/폐기 신호

| 국면 | 채택 신호 | 폐기(사용 안 함) | 근거 |
|---|---|---|---|
| **비하락장**(`bullish_trend`, `range_bound`) | `risk_adj_momentum_3m` = `return_3m_pct / max(volatility_20d_pct, 1.0)` | `fast_trend`, `sma5_over_sma20_gap`, `rsi_signal`, `relative_strength_rank_1m`, `money_flow_5d`(전부 무신호 또는 marginal 이하) | §17.2: `risk_adj_momentum_3m` bullish t_NW=1.51, range t_NW=2.09 — 유일하게 두 비하락장 국면 모두에서 방향 일관된 양(+) |
| **하락장**(`bearish_trend`) | `reversal_1m` = `-return_1m_pct` | 위와 동일 + `risk_adj_momentum_3m` 자체(하락장 t_NW=0.39로 무의미) | §17.2/§18.4: `reversal_1m` bearish T+5 t_NW=2.13(유일하게 하락장에서 유의한 후보) |
| **판정 불가**(`event_driven_unstable`, 표본 3년 기준 6일뿐) | **신호 미산출(neutral/보류)** | 전부 | 표본이 `MIN_REGIME_TRADING_DAYS=30` 미달 — 어떤 신호도 이 국면에서 검증된 바 없음(§16.6, §17.5, §20.5 반복 확인). 근거 없이 아무 신호나 대입하지 않는다 |

이 매트릭스는 §19.4에서 검증한 `regime_switch_v1`과 **동일한 정의**다
— 이번 문서는 그것을 "shadow feature 하나"에서 "entry 설계의 명시적
분기 규칙"으로 격상한 것이지, 새 로직을 발명한 것이 아니다.

### 2.3 통합 스코어 정의

```text
regime_conditional_signal(symbol, date) =
    risk_adj_momentum_3m(symbol, date)   if common_market_regime(date) in {bullish_trend, range_bound}
    reversal_1m(symbol, date)            if common_market_regime(date) == bearish_trend
    None (신호 미산출)                    if common_market_regime(date) == event_driven_unstable 또는 판정 불가
```

`risk_adj_momentum_3m`과 `reversal_1m`은 서로 스케일이 다르므로(전자는
"수익률/변동성" 비율, 후자는 "-1개월 수익률 %") **직접 비교하지
않는다** — 국면이 배타적으로 하나만 선택되므로 스케일 정합성 문제
자체가 발생하지 않는다(그날 그날 종목 간 cross-sectional quintile
비교에만 쓰이기 때문).

## 3. 기존 `entry_score`와의 연결 방안 (제안, 아직 미적용)

`_build_entry_score()`(`deterministic_trigger_engine.py:1115-1170`)의
현재 구조:

```python
score = 0.0
score += 0.45 * _normalize_signed_score(overall)   # ← alpha layer
score += 0.20 * _normalize_signed_score(fast)       # ← alpha layer
score += 0.15 * _normalize_signed_score(slow)        # ← alpha layer
# 이하 regime bonus/penalty, allocation, strategy, source, activity — risk/제약 layer
```

**제안**: `foundational_design_review...md` §8의 책임 분리(alpha /
entry projection / risk constraint / compliance / execution)를 그대로
유지하면서, **alpha layer(0.45+0.20+0.15=0.80 가중치 블록)만** 아래로
교체를 검토한다:

```python
# 제안 (미적용) — alpha layer만 교체
score += 0.80 * _normalize_signed_score(regime_conditional_signal)
# regime bonus/penalty, allocation, strategy, source, activity는 그대로 유지
```

**이 교체를 지금 적용하지 않는 이유**:
1. `regime_conditional_signal`의 하락장 절반(`reversal_1m`)은 §16
   1차 게이트를 아직 통과하지 못했다(§21 모니터링, 현재
   `NOT_TRIGGERED`) — 실거래 반영 전 반드시 통과해야 하는 전제조건이
   아직 충족되지 않았다.
2. 현재 `risk_off_penalty`(-0.15, market_regime.risk_tone=='risk_off'
   일 때)와 `regime_conditional_signal`의 하락장 분기가 **의미상
   중복될 위험**이 있다 — 둘 다 "하락장이면 무언가를 조정한다"는
   로직이기 때문이다. 이 중복을 해소하는 것은 SPPV-3(entry_score
   재현 + 중복 penalty ablation)의 원래 범위이며, 이 문서 하나로
   결론 내지 않는다.
3. `entry_score`의 나머지 0.20(allocation/strategy/source/activity)은
   `regime_conditional_signal`과 무관한 독립 축이라 그대로 둔다 — §8의
   책임 분리 원칙(risk/compliance는 alpha가 아니라 제약조건)을 지킨다.

## 4. shadow 검증 계획

### 4.1 Phase 1(이번 턴 — 완료): 정의 확정 + 1회성 shadow 스냅샷

이번 턴에 `scripts/shadow_regime_conditional_entry_signal.py`(read-only)
를 작성해 **"오늘(가장 최근 캐시 일자) 기준으로 이 신호가 core
universe 각 종목에 대해 어떤 값을 내는가"**를 1회 계산·기록했다.
DB write 없음, 주문 경로 없음. §5에 실행 결과 기록.

### 4.2 Phase 2(이번 턴부터 실행 가능 — §6에서 구현·실행 완료)

- 이 스크립트를 향후 3년 캐시를 갱신할 때마다(또는 별도 주기로) 함께
  실행해, **매번 다른 날짜의 스냅샷을 시계열로 누적**한다. 이는 새로운
  KIS 호출을 반복 발생시키지 않도록 캐시 우선 재사용을 유지한다.
- 충분한 관측치가 쌓이면(특히 하락장이 실제로 재발하면), §16 이원
  기준을 그대로 적용해 `regime_conditional_signal`을 **점수 하나의
  shadow feature가 아니라 entry 후보로서** 재검증한다 — 이는 §21
  모니터링 스크립트의 `TRIGGERED` 신호와 연동된다.
- 구체적 실행체와 누적 형식은 §6(Phase 2 shadow 누적 사이클 — 2026-07-15
  구현 완료)에 기록한다.

### 4.3 Go/No-Go 판정 기준(§16 그대로 재사용, 신규 기준 없음)

- **1차(최근 12개월) 유의성**: `regime_conditional_signal`의 pooled
  quintile spread가 |t_NW|≥2를 만족해야 한다.
- **2차(3년) 국면 무역전**: 국면별 분해에서 어떤 국면도 유의하게
  반대 부호가 나오면 안 된다.
- **추가(이 설계 고유)**: 하락장 분기(`reversal_1m`)가 실제로 발동한
  기간이 §16의 `MIN_REGIME_TRADING_DAYS`(30일) 이상 최근 12개월 창에
  존재해야 한다 — 이는 §21 모니터링 스크립트의 `TRIGGERED` 판정과
  동일하다.

이 세 조건을 모두 만족하기 전까지는 `entry_score` 반영을 시도하지
않는다.

## 5. Shadow 계산기 실행 결과 (2026-07-15, Phase 1)

`scripts/shadow_regime_conditional_entry_signal.py`(read-only)를
실행했다. 3년 캐시(`logs/_bars_cache_core87_3y_2026-07-14/`)를
재사용해 **신규 KIS 호출 0건**으로, 캐시에 있는 가장 최근 거래일(각
종목의 forward-return 계산 없이 raw feature만 필요하므로 실제 마지막
봉 날짜까지 사용 가능) 기준 87종목 전체의 `regime_conditional_signal`
값을 계산·기록했다.

**실행 결과** (종료 코드 0, `HTTP Request:` 0건, 87/87종목 성공):

| 항목 | 값 |
|---|---|
| 기준일 | 2026-07-14 |
| 시장 공통 국면 | `range_bound` |
| 사용된 신호 | `risk_adj_momentum_3m`(비하락장 분기, 87종목 전체) |
| 신호 산출 종목 | 87/87(판정불가 0종목) |
| 상위 5종목(신호값) | 009150(14.91), 011070(14.56), 066570(11.77), 402340(10.41), 000810(9.39) |
| 하위 5종목(신호값) | 010130(-12.25), 120110(-10.74), 298020(-10.73), 051915(-10.45), 251270(-9.78) |

**해석**: 오늘(2026-07-14)은 시장 공통 국면이 `range_bound`이므로 87
종목 전체가 `risk_adj_momentum_3m` 분기를 사용했다 — `reversal_1m`
분기(하락장 전용)는 이번 스냅샷에서는 한 번도 발동하지 않았다. 이는
§21 모니터링(최근 12개월 창에 `bearish_trend` 0일, `NOT_TRIGGERED`)과
정합적이다 — **이번 실행 자체는 "설계가 실제로 동작하는가"를 검증한
것이지, "신호가 유의한가"를 다시 검증한 것이 아니다.** 유의성 검증은
이미 §17.2/§19.4에서 3년치로 완료됐고, 이번 실행은 그 정의를 실시간
(현재 시점) 데이터에 1회 적용해본 **연결성 확인(smoke test)**이다.
산출: `logs/shadow_regime_conditional_entry_signal_2026-07-15.json`,
`logs/shadow_regime_conditional_entry_signal_run_2026-07-15.log`.

## 6. Phase 2 — shadow 누적 사이클 구축·실행 (2026-07-15)

### 6.1 왜 별도 오케스트레이터가 필요한가

Phase 1의 `scripts/shadow_regime_conditional_entry_signal.py`는 "실행할
때마다 그날의 스냅샷 JSON 하나"만 남긴다 — 반복 실행해도 이전 결과와
연결되지 않고, `scripts/monitor_regime_switch_v1_gate.py`의 게이트
판정과 별개로 돌아간다. Phase 2가 실제로 "누적"이 되려면 (1) 게이트
판정과 신호 계산을 **한 번의 실행으로 묶고**, (2) 그 결과를 **시계열
이력 파일에 추가(append)**하며, (3) 같은 거래일을 중복 기록하지 않아야
한다. 이 세 가지를 위해 새 로직을 짜지 않고 기존 두 스크립트의 계산
함수를 그대로 import해 재사용하는 오케스트레이터를 만들었다.

### 6.2 구현 — `scripts/run_regime_conditional_shadow_cycle.py`

- **벤치마크(069500) bars를 1회만 조회**해 (a) 게이트 판정(§21 로직,
  `_build_benchmark_daily_series` 재사용)과 (b) 오늘 신호 계산(§22
  로직, `_build_benchmark_regime_by_date`/`_latest_regime_and_signal`
  재사용) 양쪽에 함께 쓴다 — 중복 KIS 호출이 생기지 않는다.
- **누적 이력**: `logs/regime_conditional_signal_shadow_history.jsonl`
  (append-only, JSON Lines, 거래일당 1줄). 각 줄은 `trade_date`,
  `common_market_regime`, `gate_status`,
  `gate_bearish_days_recent_12m`, `symbol_count_with_signal`,
  `signal_source_distribution`(신호 산출 종목이 몇 개나 `risk_adj_
  momentum_3m`/`reversal_1m`을 썼는지 집계)을 담는다 — 87종목 전체의
  개별 값까지는 담지 않아(상세는 별도 당일자 JSON 참고) 파일이 시간이
  지나도 가볍게 유지된다.
- **중복 방지**: 실행 전 이력 파일을 읽어 이미 기록된 `trade_date`
  집합을 만들고, 오늘 날짜가 이미 있으면 새 줄을 추가하지 않는다 —
  같은 날 여러 번 실행해도 이력이 부풀지 않는다(재실행으로 실제
  검증했다 — §6.3).
- **당일 상세 스냅샷도 함께 저장**: Phase 1과 동일한 포맷으로
  `logs/shadow_regime_conditional_entry_signal_<날짜>.json`(87종목
  개별 값 전체)을 남긴다 — 이력 파일은 "요약", 이 파일은 "상세"로
  역할을 분리한다.
- **게이트 상태에 따른 안내**: 게이트가 `TRIGGERED`/`PARTIAL`이면
  화면에 §4.3 재검증 절차(runbook)를 그대로 출력한다 — 자동 재검증은
  하지 않는다(3년 캐시 재구축은 비용이 크고 신중한 판단이 필요하므로
  사람이 다음 턴에 명시적으로 착수한다).

### 6.3 실행 결과 (2026-07-15)

3년 캐시 재사용, **신규 KIS 호출 0건**, 종료 코드 0.

| 실행 | 결과 |
|---|---|
| 1차 실행 | 게이트: 기준일 2026-06-16, 국면분포 `{bullish_trend: 239, range_bound: 6}`, 판정 `NOT_TRIGGERED`. 신호: 기준일 2026-07-14, 국면 `range_bound`, 87/87종목 `risk_adj_momentum_3m` 분기. 이력에 1줄 추가(누적 거래일 1개). |
| 2차 실행(즉시 재실행, 중복 방지 검증) | 동일 결과 계산됐으나 **"2026-07-14는 이미 이력에 존재 — 중복 추가 skip"** 정상 출력, 이력 줄 수 그대로 1개 유지 |

**해석**: 게이트(2026-06-16 기준)와 신호 계산(2026-07-14 기준)의
기준일이 다른 것은 §21.3에서 이미 설명한 정상적 지연이다 — 게이트
판정은 forward-return 계산이 가능한 날짜까지만 국면을 라벨링하는
`_build_benchmark_daily_series`(T+20 확보 필요)를 재사용하기 때문에
약 20거래일 지연이 생기고, 신호 계산은 forward-return이 필요 없는
`_build_benchmark_regime_by_date`를 써서 최신 봉 날짜까지 라벨링한다.
이 둘은 서로 다른 목적(게이트=과거 12개월 분포 판정, 신호=오늘 값
계산)에 맞게 각기 다른 기존 함수를 정확히 재사용한 결과이지 오류가
아니다. 중복 방지 로직이 실제로 두 번째 실행에서 발동해, 반복 실행
시에도 이력 파일이 부풀지 않음을 확인했다.

산출: `scripts/run_regime_conditional_shadow_cycle.py`(read-only),
`logs/regime_conditional_signal_shadow_history.jsonl`,
`logs/shadow_regime_conditional_entry_signal_2026-07-14.json`,
`logs/run_regime_conditional_shadow_cycle_run_2026-07-15.log`.

## 7. 다음 단계

1. `scripts/run_regime_conditional_shadow_cycle.py`를 향후 SPPV 턴
   또는 3년 캐시 갱신 시마다 함께 실행해 이력을 계속 쌓는다 — 별도
   스케줄러 등록은 운영 인프라 변경 금지 원칙에 따라 이번 턴에는
   하지 않는다(수동/다음 턴 관행으로 유지).
2. 게이트가 `TRIGGERED`로 전환되면, §6.2의 runbook(오케스트레이터가
   화면에 출력하는 절차)을 그대로 따라 §4.3의 Go/No-Go 기준으로
   `regime_conditional_signal`을 정식 재검증한다.
3. §3의 `entry_score` 통합안은 제안 단계에 머문다 — `risk_off_
   penalty`와의 중복 여부는 SPPV-3(중복 penalty ablation) 착수 시
   함께 정리한다.
4. `event_driven_unstable` 국면은 여전히 신호 미산출 상태로 둔다 —
   표본이 쌓이기 전까지 임의로 채우지 않는다.
5. 이력 파일(`logs/regime_conditional_signal_shadow_history.jsonl`)이
   충분히 쌓이면(예: 국면 분포가 실제로 변화하는 시점), 이 파일
   자체를 §16 이원 기준 재검증의 "실시간 1차 표본"으로 활용하는 방안을
   검토한다 — 지금은 3년 과거 재구축 캐시에 의존하지만, 누적이 쌓이면
   실제 shadow 관측치로 1차 유의성을 확인할 수 있게 된다.

## 8. `entry_score` 중복 penalty ablation — Phase 0 shadow 실측 (2026-07-15)

### 8.1 배경 — SPPV-3 착수 전제

§3에서 언급한 대로, `entry_score`에 `regime_conditional_signal`을
반영하지 않는 이유 중 하나는 현재 `entry_score`/`_assess_buy_
eligibility`의 "국면이면 무언가를 차감/차단한다"는 로직이 여러 곳에
중복돼 있고(`plans/[ANALYSIS] foundational_design_review_objective_
alignment.md` §2 근본 진단), 이 중복을 해소하지 않은 채 새 신호를
얹으면 또 다른 중복을 만들 위험이 있기 때문이다. 이번 턴에 이 중복을
**말로만 지적하지 않고 오늘 시점 실제 데이터로 정량화**했다.

**중요한 경계**: 운영 DB(`trade_decisions`)를 직접 조회하는 것은
자동 승인 경계 밖의 프로덕션 읽기로 판단돼 이번 턴에 시도하지
않았다(harness가 차단). 대신 SPPV 트랙 전체가 지금까지 해온 방식 —
운영 코드(`build_signal_snapshot`, `classify_market_regime`,
`_build_entry_score`, `_assess_buy_eligibility`)를 그대로 재사용하는
read-only 재계산 — 을 동일하게 적용했다. 이는 실제 DB 데이터가 아니라
**오늘 시점 실시간 시세로 재구성한 shadow 값**이라는 한계가 있지만,
코드 경로 자체는 운영 함수를 직접 호출한 것이라 신뢰도가 높다.

### 8.2 실행 개요

`scripts/shadow_entry_score_penalty_ablation.py`(read-only)가 core
87종목(벤치마크 제외) × 오늘(3년 캐시 최신 봉) 기준으로, Phase
0(재구성 가능 — signal_backbone 순수 함수 + **종목별(per-symbol)**
`classify_market_regime`)만으로 아래 세 개의 독립적인 penalty/차단
축을 평가했다. Phase 1~3(allocation/strategy/실제 실행 이력)은
재구성 불가로 `None`을 그대로 전달했다(운영 함수가 이 경우 해당
가산/차감 항을 자연스럽게 건너뛴다 — 새 로직을 만들지 않았다).

- **축 A**: `entry_score`의 regime penalty(`risk_tone=='risk_off'`
  일 때 -0.15, `_build_entry_score` 그대로 호출)
- **축 B**: `_assess_buy_eligibility`의 regime 차단(`risk_tone==
  'risk_off' and regime_label=='bearish_trend'`, core 심볼은 예외
  없이 차단)
- **축 C**: `_assess_buy_eligibility`의 signal floor 차단
  (`overall<-0.10` 또는 `slow<-0.15`)

3년 캐시 재사용, **신규 KIS 호출 0건**, 종료 코드 0, 87/87종목 성공.
산출: `logs/shadow_entry_score_penalty_ablation_2026-07-15.json`,
`logs/shadow_entry_score_penalty_ablation_run_2026-07-15.log`.

### 8.3 실측 결과

| 항목 | 값 |
|---|---|
| 축 A(entry_score regime penalty 적용) | 85/87 |
| 축 B(eligibility regime 차단) | 60/87 |
| 축 C(eligibility signal floor 차단) | 75/87 |
| A∩B | 60 |
| A∩C | 74 |
| B∩C | 60 |
| A∩B∩C | 60 |
| 아무 축도 안 걸림 | 1/87 |
| 운영 `_assess_buy_eligibility` 그대로 호출 — 통과 | 6/87 |
| 〃 — 차단 | 81/87 |
| 종목별(per-symbol) `regime_label` 분포 | bearish_trend 60 / range_bound 18 / bullish_trend 7 / event_driven_unstable 2 |
| 종목별 `risk_tone` 분포 | risk_off 85 / neutral 2 |

### 8.4 해석 — 중복은 "이론"이 아니라 오늘 "정확히" 재현된다

1. **B∩A/B∩C가 모두 60 = B(60) 전체와 일치한다.** 즉 eligibility의
   regime 차단이 발동한 60개 종목은 **예외 없이 전부** entry_score의
   regime penalty와 signal floor 차단도 동시에 걸린다 — 근본 진단
   §2가 "약한 signal이 이미 반영된 뒤 risk_off_penalty가 다시
   차감되고, eligibility가 동일한 조건을 다시 차단한다"고 서술한
   것이 추상적 우려가 아니라 **오늘 데이터로 100% 재현되는 사실**임을
   확인했다.
2. **종목별(per-symbol) 국면이 시장 공통(market-common) 국면과
   완전히 다르다.** 오늘 시장 공통 국면(§6, KODEX 200 벤치마크
   기준)은 `range_bound`인데, `entry_score`가 실제로 쓰는 **종목별**
   `classify_market_regime()` 기준으로는 87종목 중 60개(69%)가
   `bearish_trend`로 판정된다. 이는 §12.1(SPPV-2.6)에서 코드로
   확인했던 "종목별 regime_label은 시장이 아니라 그 종목 자신의
   신호"라는 문제가 여전히 운영 코드에 살아있고, 오늘도 실제로
   시장 판단과 크게 어긋난 결과를 내고 있음을 보여준다.
3. **eligibility 통과율(6/87≈6.9%)은 과거 DB 기준선(2026-06-25~,
   21/297≈7%)과 크게 다르지 않다** — 오늘 실시간 재구성 값이 과거
   실측 패턴과 대략 일치해, 이 ablation이 특이한 하루의 우연이
   아니라 상시적인 구조적 패턴일 가능성을 시사한다(다만 표본이
   하루치뿐이라 결론으로 확정하지는 않는다 — §8.6 다음 단계 참고).

### 8.5 `regime_conditional_signal` 설계와의 연결

이 결과는 §2/§3에서 이미 제기한 우려를 강화한다. `regime_conditional_
signal`이 쓰는 국면 정의는 **시장 공통(market-common, KODEX 200
벤치마크 기준)**인 반면, `entry_score`의 regime penalty/eligibility
차단이 쓰는 국면 정의는 **종목별(per-symbol)**이다 — 이 둘은 오늘
데이터에서 이미 크게 다른 결과(시장 공통=range_bound vs 종목별
69%가 bearish_trend)를 낸다. 따라서 `entry_score`에 `regime_
conditional_signal`을 반영하려면 **regime penalty/eligibility의
국면 정의도 시장 공통 기준으로 함께 맞출지, 아니면 종목별 정의를
유지한 채 신호만 교체할지**를 먼저 결정해야 한다 — 이 결정 없이
신호만 바꾸면 "새 신호는 시장 공통 국면을 보는데 risk_off_penalty는
여전히 종목별 국면을 본다"는 **네 번째 불일치**가 추가될 위험이 있다.

### 8.6 다음 단계 — SPPV-3 착수를 위해 남은 것

1. **국면 정의 통일 여부 결정**: `regime_conditional_signal` 통합
   시 entry_score의 regime penalty/eligibility도 시장 공통 국면
   기준으로 바꿀지 사용자 확인이 필요하다 — 이는 코드 변경 범위를
   크게 좌우한다.
2. **표본 확장**: 이번 실측은 오늘 하루치(87종목)뿐이다. §6의 Phase 2
   누적 사이클을 이 ablation에도 연결해, 매일 한 번씩 세 축의
   교집합을 누적하면 "오늘의 우연"인지 "상시 구조"인지 판별할 수
   있다 — 다음 턴 후보로 남긴다.
3. **DB 실측과의 교차검증(보류)**: 이번 턴은 운영 DB 접근 없이
   진행했다 — 실제 `trade_decisions.decision_json`과 대조하는 것은
   사용자가 명시적으로 그 DB 조회를 승인한 뒤 별도로 진행한다.
4. 위 결정들이 정리되면 SPPV-3(entry_score point-in-time 재현 및
   중복 penalty ablation 본작업)에 정식 착수할 수 있다 — 이번 §8은
   그 "준비" 단계다.

## 9. 중복 억제 시계열 누적 + 국면 정의 비교 체계 (2026-07-15)

### 9.1 왜 하루치 관찰로 끝내면 안 되는가

§8은 오늘 하루치(87종목)로 "A∩B∩C=60=B 전체"와 "종목별 국면이 시장
공통 국면과 전혀 다르다"는 두 가지를 확인했다. 그러나 §8.6에서 이미
인정했듯, 하루치 표본만으로는 "오늘의 우연"과 "상시 구조"를 구분할 수
없다. §6(Phase 2)이 `regime_conditional_signal`에 대해 이미 확립한
"반복 실행 → 누적 이력" 패턴을 이 ablation에도 그대로 적용해야
같은 문제를 겪지 않는다.

### 9.2 구현 — `scripts/run_entry_score_penalty_ablation_cycle.py`

새 계산 로직을 만들지 않고 두 기존 함수를 그대로 재사용했다:

- `scripts/shadow_entry_score_penalty_ablation.py`의
  `_reconstruct_symbol_state()`(§8의 penalty 축 A/B/C 계산, 종목별
  `classify_market_regime` 재사용)
- `scripts/shadow_regime_conditional_entry_signal.py`의
  `_build_benchmark_regime_by_date()`(§22의 시장 공통 국면 계산)

이 둘을 합쳐 종목마다 **"종목별 regime_label"과 "시장 공통 국면"을
같은 실행에서 나란히 계산**하고, 다음을 누적 이력 파일
(`logs/entry_score_penalty_ablation_history.jsonl`, append-only,
거래일당 1줄, 같은 거래일 재실행 시 중복 skip — §6이 확립한 것과
동일한 이력 패턴)에 기록한다:

- A/B/C 각 축의 발동 건수와 A∩B∩C
- 종목별 `regime_label` 분포 vs 시장 공통 국면
- **국면 일치/불일치 건수**, 그중 "시장은 비하락장인데 종목별로는
  하락장" 방향과 "시장은 하락장인데 종목별로는 비하락장" 방향을
  분리 집계(divergence의 방향성까지 구분)

당일 상세(87종목 개별 값)는 별도 파일(`logs/entry_score_penalty_
ablation_<날짜>.json`)로 남겨 이력 파일은 가볍게 유지한다 — §6과
동일한 "요약 이력 vs 당일 상세" 역할 분리.

### 9.3 실행 결과 (2026-07-15)

3년 캐시 재사용, **신규 KIS 호출 0건**, 종료 코드 0, 87/87종목 성공.

| 실행 | 결과 |
|---|---|
| 1차 실행 | 시장 공통 국면(2026-07-14)=`range_bound`. A=85/B=60/C=75/A∩B∩C=60(§8과 완전히 일치, 정합성 재확인). 종목별 분포: bearish_trend 60/range_bound 18/bullish_trend 7/event_driven_unstable 2. **국면 일치 18건, 불일치 69건(79%)** — 그중 "시장 비하락장인데 종목별 하락장" 60건, "시장 하락장인데 종목별 비하락장" 0건(애초에 시장이 하락장이 아니므로 당연히 0). 이력에 1줄 추가(누적 거래일 1개). |
| 2차 실행(즉시 재실행, 중복 방지 검증) | 동일 결과 계산됐으나 "2026-07-14는 이미 이력에 존재 — 중복 추가 skip" 정상 출력, 이력 줄 수 그대로 1개 유지 |

### 9.4 해석(쉬운 설명)

- **entry_score 세 겹 차단은 우연이 아니다.** 오늘 실측에서도 §8과
  정확히 같은 숫자(A=85, B=60, C=75, 교집합=60)가 나왔다 — 같은
  날짜의 같은 데이터를 다시 계산한 것이므로 당연한 재현이지만, 두
  스크립트(§8과 §9)가 서로 다른 코드 경로로도 동일한 결과를 낸다는
  **교차 검증**이 됐다.
- **종목별 국면과 시장 국면은 5개 중 4개꼴로 다르다(79%).** 오늘
  시장은 "옆으로 횡보"(`range_bound`)로 판단됐는데, 실제 entry_score
  계산에 쓰이는 개별 종목 판정은 87개 중 60개(69%)가 "하락 추세"로
  나온다 — 즉 지금 운영 코드는 **시장이 하락장이 아닌 날에도** 개별
  종목 다수를 "하락장"으로 잘못(?) 분류해 risk_off_penalty와
  eligibility 차단을 발동시키고 있을 가능성이 있다. "잘못"이라고
  단정하지 않는 이유는, 종목별 판정이 그 종목 고유의 약세(개별
  기업 이슈 등)를 반영하는 것일 수도 있어서다 — 이 구분은 §9.6의
  비교 실험으로 가려야 한다.

### 9.5 종목별 국면 vs 시장 공통 국면 — 정리

| 구분 | 종목별(per-symbol) 국면 | 시장 공통(market-common) 국면 |
|---|---|---|
| 정의 | 그 종목 자신의 `overall_score`/`return_3m_pct`/`price_vs_sma_60_pct` 등을 `classify_market_regime()`에 입력 | KODEX 200(069500) 벤치마크의 rolling 기술적 상태를 같은 함수에 입력, 하루에 라벨 1개를 전 종목이 공유 |
| 현재 쓰이는 곳 | `entry_score`의 regime bonus/penalty, `_assess_buy_eligibility`의 regime 차단(운영 코드, 지금도 실사용 중) | `regime_conditional_signal`(§2, 아직 shadow 단계, 미적용) |
| 오늘 실측(2026-07-14) | bearish_trend 60/range_bound 18/bullish_trend 7/event 2 | range_bound 1개(전 종목 공유) |
| 알려진 문제 | §12.1(SPPV-2.6)에서 이미 "검정 대상 신호와 같은 계열 변수로 조건화한 선택 편향"으로 지적됨 — 그런데도 운영 코드는 여전히 이 정의를 쓴다 | SPPV 전체 트랙(§16 이하)이 검증에 사용한 정의 — 시장 전체 방향을 반영 |

**핵심 쟁점**: 지금 운영 중인 `entry_score`/eligibility는 "문제가 있다고
이미 알려진" 종목별 정의를 쓰고 있고, 검증된 `regime_conditional_
signal`은 "올바르다고 확인된" 시장 공통 정의를 쓴다 — 이 둘을 통합
하려면 반드시 하나로 맞춰야 하며, 그 결정은 실측 비교 없이 내릴 수
없다(§9.6).

### 9.6 SPPV-3 본작업용 비교 실험 설계

SPPV-3(entry_score point-in-time 재현) 착수 시, 다음 실험을 **반드시
포함**해야 한다 — 새 방법론이 아니라 이미 SPPV 트랙이 확립한 §16
이원 기준·3년 캐시·cross-sectional quintile spread를 그대로 재사용한다.

**실험 설계**:

1. 기존 3년 rolling 표본(87종목×56,753건, 이미 확보됨)에 대해, 각
   거래일·종목마다 **두 가지 eligibility 판정**을 병렬로 계산한다:
   - **변형 A(현행 유지)**: `_assess_buy_eligibility`를 그대로 호출 —
     regime 차단 조건에 **종목별** `regime_label`을 사용.
   - **변형 B(시장 공통 정렬)**: 동일한 `_assess_buy_eligibility`를
     호출하되, regime 차단 조건에 **시장 공통** 국면(벤치마크 기준,
     그날 전 종목 공유)을 대입.
2. 두 변형 각각에 대해 "eligibility 통과 종목의 T+5/T+20 forward
   return"을 quintile spread + Newey-West로 비교한다(§16과 동일한
   통계 방법) — **어느 정의가 실제로 좋은 종목을 통과시키는지**를
   가린다.
3. 두 변형의 **통과율 자체**도 비교한다 — 변형 B가 변형 A보다 통과율이
   높아지는지 낮아지는지(§8.4에서 종목별 정의가 시장보다 훨씬 자주
   "하락장"으로 판정하는 경향이 확인됐으므로, 변형 B는 통과율이
   높아질 가능성이 있다 — 다만 이것이 "더 정확한 판단"인지 "위험
   완화 약화"인지는 1번의 forward return 비교로만 판단한다).
4. **Go/No-Go**: 변형 B가 (a) 변형 A보다 통과 종목의 forward return이
   유의하게 낫거나 최소한 나쁘지 않고, (b) 하락장(§16 2차 기준)에서
   위험 신호를 놓치지 않는다는 것이 함께 확인돼야 "시장 공통 정렬"로
   전환한다. 둘 중 하나라도 실패하면 종목별 정의를 유지하되, `regime_
   conditional_signal` 쪽을 종목별 정의에 맞추는 대안도 함께 검토한다.

이 실험은 새 KIS 호출이 필요 없다 — 기존 3년 캐시와 이미 만들어둔
`_reconstruct_symbol_state`류 함수를 T+5/T+20 forward return과 결합
하기만 하면 된다. 다음 SPPV-3 착수 시 우선 수행 항목으로 지정한다.

### 9.7 다음 단계

1. `scripts/run_entry_score_penalty_ablation_cycle.py`를 `scripts/
   run_regime_conditional_shadow_cycle.py`와 함께 주기적으로(3년 캐시
   갱신 시 또는 매 SPPV 턴) 실행해 이력을 계속 쌓는다.
2. §9.6의 비교 실험을 SPPV-3 착수 시 최우선으로 수행한다 — 이 실험
   결과 없이 `regime_conditional_signal`을 `entry_score`에 통합하지
   않는다.
3. 두 이력 파일(`regime_conditional_signal_shadow_history.jsonl`,
   `entry_score_penalty_ablation_history.jsonl`)이 충분히 쌓이면,
   "국면 불일치 비율(79%)"과 "삼중 중복 비율" 자체가 시간에 따라
   안정적인지(오늘만의 우연이 아닌지) 재확인한다.
