# 국면 분기형 진입 신호 설계 (regime_conditional_entry_signal v1)

작성일: 2026-07-15
상태: **설계 초안 + shadow 계산기 1차 실행 완료 + Phase 2 누적 사이클
구축·실행 완료(§6) + entry_score 중복 penalty ablation 실측 완료(§8) +
중복 억제 시계열 누적·국면 정의 비교 체계 구축(§9) + §9.6 비교 실험
실측 완료(§10) + A/B 불일치 표본 direct 비교·1차 창 재확인 완료(§11) +
**alpha layer vs regime_conditional_signal 직접 비교 완료(§12,
2차 창에서 유의한 우위 확인 — Conditional Go)** + **새 alpha 상위군과
기존 차단 축 결합 효과 검증 완료(§13, 당시 해석은 §14로 보정됨) —
가장 빈번한 차단 사유는 regime 축이 아니라 별개의 활동성(activity)
필터임을 신규 발견, 결합 판정 Watch(추가 검증 필요)** + **활동성
필터 정밀 ablation 완료(§14, 2026-07-16
해석 보정 반영) — 완전 제거는 No-Go(기대수익률 개선 근거 없음)로
확정, 임계값 1.10→1.00 완화는 방향은 유력하나 Watch(추가 검증
필요, "주범 확정"·"과잉 억제 확정"·"제거 시 개선" 결론은 보류)** —
실거래/`entry_score` 반영 없음.**
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

## 10. §9.6 비교 실험 실측 — 종목별 regime vs 시장 공통 regime의 forward return (2026-07-15)

### 10.1 실행 개요

`scripts/validate_entry_score_regime_definition_comparison.py`
(read-only)가 §9.6에서 설계한 실험을 그대로 실행했다 — 새 방법론이
아니라 §16 이원 검증이 확립한 cross-sectional quintile spread +
Newey-West 통계와 운영 함수 `_assess_buy_eligibility()`를 그대로
재사용한다. 3년 rolling 표본(87종목, 56,753건)에 대해 거래일·종목마다
**변형 A(현행, 종목별 `regime_label`)**와 **변형 B(시장 공통 국면,
KODEX 200 벤치마크 기준)**로 eligibility를 각각 재계산해, 통과 종목의
T+5/T+20 forward return을 비교했다.

**실행 결과(가정 없이 로그로 확인)**: 종료 코드 0, 87/87종목 성공,
**로그 내 `HTTP Request:` 카운트 0건** — 이번 실행도 3년 캐시가
완전히 재사용돼 신규 KIS 호출이 발생하지 않았음을 실제로 확인했다
(가정이 아니라 로그 기준 사실). 실행 시각 2026-07-15 11:18:30~
11:18:51(약 21초). 산출: `logs/signal_ic_entry_score_regime_
definition_comparison_2026-07-15.json`, `logs/entry_score_regime_
definition_comparison_run_2026-07-15.log`.

### 10.2 핵심 결과

| 항목 | 변형 A(종목별) | 변형 B(시장 공통) |
|---|---|---|
| eligibility 통과 표본 수 | 11,711/56,753(20.64%) | 10,639/56,752(18.75%) |
| T+5 통과군 평균 forward return | +0.9254%(t_NW=7.40) | **+1.0357%**(t_NW=7.70) |
| T+20 통과군 평균 forward return | +3.1861%(t_NW=7.31) | **+3.5780%**(t_NW=7.69) |
| (참고) baseline(전체 표본, eligibility 무관) | T+5 +0.6706%(t_NW=12.82) / T+20 +2.5912%(t_NW=11.82) | 〃 |
| 통과군 내부 quintile spread(T+20) | -1.5137%p(t_NW=**-2.84**, 유의 역전) | -1.8443%p(t_NW=**-3.06**, 유의 역전) |

### 10.3 해석(쉬운 설명)

1. **eligibility 필터 자체는 유효하다.** A/B 어느 정의를 쓰든,
   통과한 종목들의 평균 forward return(T+5/T+20)이 baseline(전체
   표본 평균)보다 높고 통계적으로 유의(t_NW 7.3~7.7, |t|≥2를 크게
   상회)하다 — "위험한 국면/약한 신호를 걸러낸다"는 eligibility의
   설계 의도가 실제로 작동하고 있다는 뜻이다.
2. **시장 공통 정의(B)가 종목별 정의(A)보다 두 지표 모두에서 낫다.**
   통과율은 더 낮으면서(18.75% < 20.64%, 더 엄격하게 걸러냄) 통과
   종목의 forward return은 더 높다(T+5: +1.04% > +0.93%, T+20:
   +3.58% > +3.19%). "더 많이 통과시켜서 좋아 보이는 착시"가 아니라
   "더 적게, 더 좋은 것만 통과"시킨다는 뜻이므로 **과잉 억제가 아니라
   더 정밀한 억제**로 해석된다.
3. **단, A와 B 차이 자체의 통계적 유의성은 이번 실행에서 검정하지
   않았다.** 두 정의 각각의 통과군이 baseline보다 유의하다는 것은
   확인했지만, "A의 평균과 B의 평균이 서로 유의하게 다른가"는 별도의
   대응표본(paired) 검정이 필요하다 — 두 통과군이 상당 부분 겹칠
   것이기 때문이다. 이 검정 없이 "B가 A보다 확실히 낫다"고 단정하지
   않는다.
4. **통과군 내부에서도 `overall_score` 기반 quintile spread는 여전히
   유의하게 역전(T+20 t_NW=-2.84~-3.06)한다.** 이는 §14의 3년 전체
   결론("`overall_score`가 안정적 알파를 못 낸다")이 eligibility를
   통과한 부분집합 안에서도 그대로 재현된다는 뜻이다 — eligibility
   필터는 유효하지만, 그 필터를 통과한 뒤 `overall_score`로 다시
   순위를 매기는 것은 여전히 실패한다. 이는 SPPV-3에서 반드시 별도로
   다뤄야 할 문제로 남긴다.

### 10.4 판정 — Watch(조건부 유리), 확정 Go 아님

**변형 B(시장 공통 정의)로의 전환은 §9.6의 Go 기준 (a)("통과 종목
forward return이 유의하게 낫거나 최소한 나쁘지 않음")를 방향상
충족한다** — 실측으로 더 나은 수치가 나왔다. 기준 (b)("하락장에서
위험 신호를 놓치지 않음")도 통과율이 더 낮아졌다는 사실 자체가
간접적으로 뒷받침한다(더 보수적으로 걸렀다).

**그러나 확정 Go로 선언하지 않는다** — ① A-B 차이 자체의 통계적
유의성 검정이 아직 없고, ② 표본이 3년 전체 pooled이며 최근 12개월
1차 게이트(§16)로는 아직 재확인하지 않았고, ③ 통과군 내부 quintile
spread가 여전히 역전된다는 문제가 남아있다. **"단순 통과율 증가만
보고 판단하지 말라"는 원칙에 따라, 판정은 Watch(조건부 유리, 시장
공통 정의가 더 나을 가능성이 실측으로 뒷받침됨)로 유지**하고, 다음
단계에서 A-B 차이의 직접 유의성 검정을 수행한 뒤 최종 판정한다.

### 10.5 다음 단계

1. A-B 차이(같은 종목·거래일 쌍에서 eligibility 판정이 갈린 표본만
   따로 추출)에 대한 대응표본 검정을 수행해 "시장 공통 정의가 통계적
   으로 유의하게 더 나은지"를 직접 확인한다.
2. §16 1차(최근 12개월) 창으로도 동일 비교를 반복해, 3년 pooled
   결과가 최근 시장에서도 재현되는지 확인한다.
3. 통과군 내부 quintile spread 역전 문제(§10.3-4)는 SPPV-3에서
   `overall_score` 자체의 재설계(§19 이하 feature 재설계 트랙과 연결)
   범위로 별도 다룬다.
4. 이 결과를 `entry_score`에 실제로 반영하는 결정은 위 1~2번 완료
   후 사용자 확인을 거쳐 진행한다 — 이번 턴은 shadow/validation
   범위에 머문다.

## 11. A/B 판정 불일치 표본 direct 비교 + 1차 창 재확인 (2026-07-15)

### 11.1 배경 — §10.5의 두 과제

§10(SPPV-2.20)의 비교는 "A 통과군 평균 vs B 통과군 평균"을 독립적으로
비교했다 — 그러나 두 통과군은 대부분(A 11,711건 중 10,639건, B
10,639건 중 10,639건 전부)이 겹치는 표본이라, "A와 B가 서로 다르게
판단한 표본"에서 어느 쪽이 옳았는지를 직접 보여주지 못했다. 이번 턴은
같은 종목-거래일 표본을 4개 배타적 집합(`A_only`/`B_only`/`both`/
`neither`)으로 분해하고, 최근 12개월(1차) 창에서도 같은 비교를
반복했다.

### 11.2 실행 개요

`scripts/validate_entry_score_regime_definition_ab_diff.py`
(read-only)가 §10의 표본 수집 함수(`_collect_symbol_rows`)를 그대로
재사용해 4개 집합을 분해했다. 3년 캐시 재사용, 종료 코드 0, 87/87종목
성공. **실제 KIS 호출 여부는 가정하지 않고 로그로 확인** — `HTTP
Request:` **0건**. 실행 시각 2026-07-15 22:19:22~22:19:45(약 23초).
산출: `logs/signal_ic_entry_score_regime_ab_diff_2026-07-15.json`,
`logs/entry_score_regime_ab_diff_run_2026-07-15.log`.

### 11.3 핵심 결과 — 예상 밖의 구조적 발견

**2차(3년, 56,753건)**:

| 집합 | 표본 수 | T+5 평균(t_NW) | T+20 평균(t_NW) |
|---|---|---|---|
| `A_only`(A만 통과, B는 차단) | 1,072 | -0.1694%(-0.62) | -0.7028%(-0.79) |
| `B_only`(B만 통과, A는 차단) | **0** | — | — |
| `both`(둘 다 통과) | 10,639 | +1.0357%(7.70) | +3.5780%(7.69) |
| `neither`(둘 다 탈락) | 45,042 | +0.6047%(11.80) | +2.4371%(11.63) |

**1차(최근 12개월, 21,315건)**:

| 집합 | 표본 수 |
|---|---|
| `A_only` | **0** |
| `B_only` | **0** |
| `both` | 5,468 |
| `neither` | 15,847 |

**가장 중요한 발견 — `B_only`가 3년·1차 창 모두에서 정확히 0건이다.**
이는 우연이 아니라 **구조적 사실**이다: 시장 공통 정의(B)의 eligibility
차단 조건은 `regime_label=='bearish_trend' and risk_tone=='risk_off'`
일 때만 발동하는데, 이 조건은 종목별 정의(A)가 이미 차단하지 않은
표본을 B가 "추가로" 차단하는 방향으로만 작동할 수 있다 — **B가 A를
포함하는 진부분집합(strict subset) 관계이지, A와 B가 서로 반대
방향으로 엇갈리는 관계가 아니다.** 즉 시장 공통 정의로 바꾼다는 것은
"통과 종목을 다르게 고르는 것"이 아니라 **"A가 통과시킨 것 중 일부
(`A_only`, 3년간 1,072건)를 추가로 걸러내는 것"**뿐이다.

### 11.4 A_only(=B가 추가로 차단하는 표본)의 품질

`A_only`(1,072건)의 forward return은 T+5 -0.17%/T+20 -0.70%로
**음수**이고, `both`(+1.04%/+3.58%)나 `neither`(+0.60%/+2.44%)보다도
낮다 — **방향은 "B가 추가로 차단하는 것이 맞다"는 §10의 결론과
일치**한다. 그러나 t_NW는 T+5 -0.62, T+20 -0.79로 **|t|<1, 통계적으로
전혀 유의하지 않다** — 표본이 1,072건으로 작지 않은데도 유의성이
나오지 않는다는 것은, 이 차이가 확실한 것이 아니라 노이즈에 가까울
수 있음을 뜻한다.

### 11.5 "일별 짝비교(day-matched paired diff)" 방법론이 이 데이터 구조에서
성립하지 않음을 확인

원래 §10.5는 "그날 `A_only`/`B_only` 둘 다 있는 날의 평균차를 모아
Newey-West로 검정"하는 방법을 계획했다. 그러나 `B_only`가 0건이므로
이 짝비교는 **정의상 계산할 표본이 없다**(n_days=0) — 이는 스크립트
결함이 아니라, §11.3에서 밝혀진 부분집합 구조의 직접적 귀결이다.
따라서 "A-B 차이의 유의성"을 검정하는 올바른 방법은 애초 계획했던
날짜-매칭 짝검정이 아니라, **`A_only`(B가 추가로 차단하는 유일한
표본군) 자체의 평균이 0과 다른지를 검정하는 것**으로 자연스럽게
단순화된다 — 이미 §11.4에서 그 검정을 수행했고, 결과는 유의하지 않다.

### 11.6 1차(최근 12개월) 창 — 재현 여부를 판단할 표본 자체가 없다

최근 12개월 창에서는 `A_only=0`, `B_only=0`이다 — A와 B가 **완전히
동일한 판정**을 내린다(both=5,468=A 통과 전체=B 통과 전체). 이는
§21 모니터링이 이미 확인한 사실(최근 12개월 창에 시장 공통
`bearish_trend`가 0일)과 정확히 정합적이다 — B의 차단 조건은 시장이
`bearish_trend`일 때만 발동하는데, 최근 12개월에는 그 조건이 발동할
기회 자체가 없었기 때문에 A와 B가 다를 수가 없다.

**따라서 "최근 12개월에서도 같은 방향성이 재현되는가"라는 질문에는
"재현 여부를 판단할 표본 자체가 존재하지 않는다"가 정확한 답이다.**
이는 "재현되지 않았다"(No-Go 근거)와는 다르다 — 검증 기회 자체가
아직 주어지지 않았을 뿐이다. §21 게이트가 `TRIGGERED`로 전환되기
전까지는 이 비교를 1차 창에서 반복해도 항상 같은(공집합) 결과가
나올 것이다.

### 11.7 판정 — Watch 유지(No-Go에 근접), 확정 Go 아님

공격형 시스템 관점에서 재확인한 결론:

1. **B로 전환해도 "더 좋은 종목을 새로 발굴"하는 효과는 없다** —
   `B_only`가 0이므로, B는 A가 이미 찾은 종목 집합에서 일부를 **빼는
   것**만 한다. 이는 "국면 정의를 바꾸면 기회가 늘어난다"는 가설을
   기각한다 — 공격형 목표(최고 기대수익률) 관점에서는 긍정적 신호가
   아니다(기회를 늘리지 않고 줄이기만 함).
2. **B가 추가로 빼는 종목(`A_only`)의 품질은 방향상 나쁘지만(-0.17%/
   -0.70%) 통계적으로 확실하지 않다(|t|<1).** §10에서 관측된 "B
   통과군이 A 통과군보다 forward return이 높다"는 결과의 메커니즘이
   이제 명확해졌다 — B가 나쁜 부분집합(`A_only`)을 빼기 때문에 남은
   평균이 올라가는 것인데, 그 나쁜 부분집합 자체가 유의하게 나쁜지는
   확인되지 않았다.
3. **최근 12개월(1차 게이트)에서는 이 차이 자체가 존재하지 않는다** —
   전환의 효과를 검증할 기회가 아직 없다.

**종합 판정: Watch 유지(No-Go에 근접), 시장 공통 정의로의 확정 전환
(Go)은 기각한다.** §9.6에서 세운 Go 기준("변형 B가 변형 A보다 통과
종목 forward return이 유의하게 낫거나 최소한 나쁘지 않음")은 이번
정밀 분해로 재검토하면 "B가 추가로 배제하는 부분의 품질이 유의하게
나쁘다"는 것이 확인돼야 충족되는데, 그 유의성이 나오지 않았다. 단순
통과율 감소나 "B 통과군 평균이 더 높다"는 집계 결과만으로 Go를
선언하지 않는다.

### 11.8 다음 단계

1. `A_only`(1,072건)의 표본을 국면별로 더 세밀하게 나눠(예: 실제
   하락폭 정도별) 유의성이 특정 하위구간에서만 나타나는지 확인한다 —
   지금은 하나로 뭉쳐 검정해 유의성이 희석됐을 가능성이 있다.
2. §21 게이트가 `TRIGGERED`로 전환되면(다음 하락장이 최근 12개월
   창에 들어오면) 이 비교를 반드시 재실행한다 — 지금은 표본 자체가
   없어 판단을 유보할 수밖에 없다.
3. "국면 정의 통일"이라는 방향 자체는 §10~11의 실측으로 근거가
   약해졌다 — SPPV-3의 우선순위를 "국면 정의 통일"에서 "`regime_
   conditional_signal`을 alpha layer에 직접 통합"(§3 제안)하는 쪽으로
   재조정할지 사용자와 논의한다.

## 12. alpha layer vs regime_conditional_signal 직접 비교 (2026-07-15)

### 12.1 배경 — 무게중심을 "차단(risk)"에서 "선별(alpha)"로 이동

§10~§11(SPPV-2.20/2.21)은 "국면 정의(종목별 vs 시장 공통) 자체를
바꾸는 것"을 검증했고, 그 결론은 명확히 Watch/No-Go에 근접했다 — 시장
공통 정의는 종목별 정의의 부분집합일 뿐 새로운 종목을 발굴하지
못했다(§11.3). 이는 **차단 축(누구를 걸러낼지)의 개선이 아니었다.**
이번 실험은 무게중심을 옮겨 **alpha 축(누구를 위로 올릴지)**을 직접
비교한다 — `entry_score`의 alpha layer(`overall_score`/`fast_score`/
`slow_score`를 0.45/0.20/0.15로 가중합) 자체를 `regime_conditional_
signal`(§2의 국면별 전환 신호)과 같은 3년 표본에서 맞대결시킨다.

### 12.2 현행 alpha layer의 코드 기준 정리

`_build_entry_score()`(`deterministic_trigger_engine.py:1128-1130`):

```python
score += 0.45 * _normalize_signed_score(overall)
score += 0.20 * _normalize_signed_score(fast)
score += 0.15 * _normalize_signed_score(slow)
```

`_normalize_signed_score(x) = clamp((x+1)/2)`(`:1252-1255`)는 모든
성분에 **동일한 선형 변환**(기울기 0.5, 절편 0.5)을 적용하므로, 위 식은

```text
alpha_layer = 0.4 + 0.5·(0.45·overall + 0.20·fast + 0.15·slow)
```

로 대수적으로 정리된다 — **순위(ranking)만 보면** 원 가중치 그대로의
`current_alpha_composite = 0.45·overall + 0.20·fast + 0.15·slow`와
완전히 같은 순서를 만든다(코드의 수학적 귀결, 근사가 아니다). 이번
실험은 `current_alpha_composite`를 그대로 계산해 비교 대상으로 삼았다
— 새 alpha layer를 발명한 것이 아니라 **현재 코드가 실제로 만드는
순위 그대로**를 재현했다.

### 12.3 실행 개요

`scripts/validate_alpha_layer_vs_regime_conditional_signal.py`
(read-only)가 3년 rolling 표본(87종목, 56,753건)에 대해 거래일마다
`current_alpha_composite`와 `regime_conditional_signal`을 함께
계산하고, §16 이원 검증 도구(cross-sectional quintile spread +
Newey-West)로 비교했다. 공정 비교를 위해 `regime_conditional_signal`
이 산출 가능한 표본(판정불가 국면 제외, 3년 56,235건/최근 12개월
21,315건)에서 `current_alpha_composite`도 별도로 재계산해 나란히
제시한다.

3년 캐시 재사용, 종료 코드 0, 87/87종목 성공. **실제 KIS 호출 여부는
가정하지 않고 로그로 확인** — `HTTP Request:` **0건**. 실행 시각
2026-07-15 23:10:51~23:11:13(약 22초). 산출: `logs/signal_ic_alpha_
layer_vs_regime_conditional_signal_2026-07-15.json`,
`logs/alpha_layer_vs_regime_conditional_signal_run_2026-07-15.log`.

### 12.4 핵심 결과

| 창 | horizon | 신호 | spread 평균 | t_NW | 양수 비율 |
|---|---|---|---|---|---|
| 2차(3년) | T+5 | `current_alpha_composite` | +0.275%p | 1.02 | 53.2% |
| 2차(3년) | T+5 | `regime_conditional_signal` | **+0.666%p** | **2.52** | **61.2%** |
| 2차(3년) | T+20 | `current_alpha_composite` | +1.043%p | 1.32 | 52.1% |
| 2차(3년) | T+20 | `regime_conditional_signal` | **+2.082%p** | **2.33** | **62.9%** |
| 1차(최근 12개월) | T+5 | `current_alpha_composite` | +0.716%p | 1.29 | 55.9% |
| 1차(최근 12개월) | T+5 | `regime_conditional_signal` | **+0.859%p** | 1.55 | **60.0%** |
| 1차(최근 12개월) | T+20 | `current_alpha_composite` | +1.952%p | 1.26 | 58.0% |
| 1차(최근 12개월) | T+20 | `regime_conditional_signal` | **+3.010%p** | 1.47 | **64.5%** |

### 12.5 해석 — "더 잘 고르는가"에 대한 답

1. **2차(3년) 창에서 `regime_conditional_signal`이 T+5/T+20 둘 다
   §16 유의 임계(|t_NW|≥2)를 통과한다(2.52, 2.33)** — 반면 현행
   alpha layer(`current_alpha_composite`)는 같은 표본, 같은 기간에서
   어디서도 유의하지 않다(1.02~1.39). 이는 §19/§20에서 이미 확인된
   `regime_conditional_signal`의 유의성이, 현재 실제로 운영 중인
   alpha layer와의 **직접 대결에서도 재현·재확인**됐다는 뜻이다.
2. **spread 크기, t값, 양수 비율 — 4개 관측치(2개 창×2개 horizon)
   전부에서 `regime_conditional_signal`이 `current_alpha_composite`
   보다 일관되게 우세하다.** 특히 T+20(더 긴 보유 기간)에서 격차가
   더 벌어진다(3년: 2.082%p vs 1.043%p, 거의 2배). 이는 "더 막는
   방법"이 아니라 **"더 공격적으로 좋은 종목을 위에 올리는" 관점에서
   실제로 우위가 있다**는 것을 뒷받침한다 — 방어적 차단 강화가 아니라
   선별 품질 개선으로 해석해야 한다.
3. **1차(최근 12개월)에서는 두 신호 모두 §16 임계를 통과하지
   못한다**(1.26~1.55) — 그러나 `regime_conditional_signal`은 여기
   서도 4개 지표 모두에서 `current_alpha_composite`보다 우세하다.
   1차 미달의 원인은 이미 §21에서 확인된 구조적 사실(최근 12개월에
   시장 공통 하락장이 0일이라 `reversal_1m` 분기가 전혀 발동하지
   못함)이지, `regime_conditional_signal` 자체의 결함이 아니다.

### 12.6 판정 — Conditional Go(2차 검증 통과, 1차 게이트 대기)

**단순 통과율 비교가 아니라 forward return 품질로 판단한 결과,
`regime_conditional_signal`이 현행 alpha layer보다 일관되게 우수하다
— 이 결과를 지나치게 보수적으로 눌러 해석하지 않는다.** 2차(3년)
창에서는 두 horizon 모두 통계적으로 유의한 우위를 확보했다. 다만
1차(최근 12개월) 게이트는 여전히 미달인데, 그 원인이 신호 자체의
결함이 아니라 최근 시장에 검증 기회(하락장)가 없었다는 §21의 구조적
사실에 있으므로, **Watch로 낮춰 부르지 않고 "Conditional Go"로
명시한다** — §21 모니터링이 `TRIGGERED`로 전환되는 즉시 1차 게이트를
재확인해 최종 Go 여부를 확정한다는 뜻이다.

**억지로 완전한 Go를 선언하지도 않는다** — §16의 이원 기준(1차+2차
모두 충족)을 자의로 낮추지 않고, 1차 게이트가 실제로 통과할 때까지는
`entry_score` 코드 변경을 보류한다.

### 12.7 다음 단계

1. §21 게이트가 `TRIGGERED`로 전환되면 이 비교를 최우선으로
   재실행한다 — 1차 창에서도 유의성이 확인되면 SPPV-3
   `entry_score` alpha layer 교체(§3 제안)를 정식 착수 후보로
   올린다.
2. `current_alpha_composite`가 3년 전체에서 유의성을 전혀 확보하지
   못했다는 사실은 §14(SPPV-2.7)의 "정적 단일 가중 신호는 안정적
   알파를 못 낸다"는 결론을 alpha layer 자체 수준에서 재확인한
   것이다 — `regime_conditional_signal`로의 교체가 단순 대안이
   아니라 필요한 개선이라는 근거가 더 쌓였다.
3. 이 비교 결과를 근거로 SPPV-3의 우선순위를 "국면 정의 통일"(§11,
   Watch/No-Go)에서 "alpha layer 교체"(§12, Conditional Go)로
   공식 재조정할지 사용자 확인을 받는다.

## 13. 새 alpha 상위군과 기존 차단 축 결합 효과 (2026-07-15)

> **[2026-07-16 §14 보정 안내]** 아래 §13.4~§13.6은 **활동성 필터
> ablation(§14)을 실행하기 전, 2026-07-15 당시의 1차 해석**이다.
> 당시에는 "차단된 표본도 forward return이 플러스"라는 사실만으로
> "과잉 억제의 강력한 증거"·"진짜 병목"·"주범" 같은 단정적 표현을
> 썼으나, 이는 옳은 판단 기준(=차단을 실제로 제거/완화했을 때
> 기대수익률이 개선되는가)으로 검증한 것이 아니었다. §14에서 실제로
> ablation한 결과, 완전 제거는 오히려 생존군 평균을 낮췄고(No-Go),
> 완화(1.10→1.00)도 방향만 확인됐을 뿐 확정 근거는 아니다(Watch).
> **이 문서를 읽는 사람은 §13.4~§13.6의 단정적 표현이 아니라 §14의
> 보정된 결론을 최종 판단 기준으로 삼아야 한다.** 아래 원문은
> 조사가 어떻게 활동성 필터를 발견하게 됐는지의 이력으로만 보존한다.

### 13.1 배경 — "더 잘 고르는 alpha"를 찾은 뒤에도 기존 차단이 그 효과를 죽이는가

§12(SPPV-2.22)는 `regime_conditional_signal`이 alpha layer로서 현행보다
유의하게 낫다는 것을 확인했다(Conditional Go). 그러나 그 확인은 "이
신호로 순위를 매기면 상위/하위 quintile 차이가 유의하다"는 것이었지,
**"실제로 이 신호를 alpha layer에 넣고 기존 차단 로직(§8에서 정량화한
세 축)을 그대로 두면 상위권 종목들이 살아남는지"**는 아직 확인하지
않았다. 이번 실험은 그 질문에 답한다 — 방어 강화가 아니라 "새 alpha가
찾은 좋은 종목이 기존 차단 때문에 다시 사라지는가"를 실측한다.

### 13.2 실행 개요

`scripts/validate_new_alpha_vs_existing_blocking_axes.py`(read-only)가
3년 rolling 표본(87종목)에서 거래일별 cross-sectional 상위 20%를
`regime_conditional_signal` 기준으로 뽑고, 그 상위군에 **운영 함수
`_build_entry_score()`/`_assess_buy_eligibility()`를 그대로 호출**해
(종목별 regime 기준, 현재 실제로 도는 로직) 생존/차단 여부와 forward
return을 비교했다. 3년 캐시 재사용, 종료 코드 0, 87/87종목 성공.
**실제 KIS 호출 여부는 가정하지 않고 로그로 확인** — `HTTP Request:`
**0건**. 산출: `logs/signal_ic_new_alpha_vs_existing_blocking_axes_
2026-07-15.json`, `logs/new_alpha_vs_existing_blocking_axes_run_
2026-07-15.log`.

### 13.3 핵심 결과 — 상위군의 60~68%가 차단된다

| 창 | 상위 20% 표본 | 생존 | 차단됨 |
|---|---|---|---|
| 2차(3년) | 10,999건 | 3,491건(31.7%) | **7,508건(68.3%)** |
| 1차(최근 12개월) | 4,165건 | 1,621건(38.9%) | **2,544건(61.1%)** |

| 창 | horizon | 상위군 전체(차단 없다고 가정) | 생존(현재 운영 로직) | 차단됨 |
|---|---|---|---|---|
| 2차(3년) | T+5 | +1.008%(t_NW=9.06) | +1.422%(t_NW=5.89) | +0.815%(t_NW=**6.86**) |
| 2차(3년) | T+20 | +3.554%(t_NW=10.35) | +4.381%(t_NW=5.78) | +3.170%(t_NW=**8.35**) |
| 1차(최근 12개월) | T+5 | +1.711%(t_NW=7.52) | +1.972%(t_NW=4.50) | +1.544%(t_NW=**6.29**) |
| 1차(최근 12개월) | T+20 | +5.721%(t_NW=8.16) | +5.871%(t_NW=4.54) | +5.626%(t_NW=**6.71**) |

**차단된 표본도 forward return이 강하게 유의하게 양(+)으로
관찰됐다** — 심지어 1차 창 T+20에서는 생존군(+5.87%)과 차단군
(+5.63%)의 차이가 거의 없었다. **이 시점(§14 검증 전)에는** 이를
"차단이 나쁜 종목을 걸러낸다"는 가정과 달리 "차단된 표본의 절대
다수가 손실이 아니라 플러스 수익을 내고 있었다"는 관찰로만 받아
들였다 — **다만 이 관찰은 "차단을 제거했을 때 기대수익률이 실제로
개선되는가"를 검증한 것은 아니었다.** 그 질문은 §14에서 별도
ablation으로만 답할 수 있었고, 실제로 §14에서는 완전 제거 시
생존군 평균이 오히려 낮아지는 결과가 나와(No-Go), "차단된 표본이
플러스였다"는 사실만으로 제거/완화가 유리하다고 단정할 수 없음이
드러났다.

### 13.4 (당시 해석, §14 보정 전) 차단 사유 재발견 — regime 축이 아니라 "활동성 필터"가 가장 빈번함

§8/§9/§11에서 계속 조사해온 세 축(entry_score regime penalty,
eligibility regime block, eligibility negative floor)이 이 차단의
가장 큰 원인일 것이라 예상했으나, `scripts/diagnose_blocked_reason_
distribution.py`(read-only, 신규 KIS 호출 0건, 종료 코드 0)로 실제
`_assess_buy_eligibility()`의 최종 실패 사유를 집계한 결과 **예상과
다른 분포가 나왔다**(아래는 "가장 빈번한 차단 사유"를 보여줄 뿐,
그 사유가 과잉 억제인지는 §13.5에서 보듯 이 시점엔 아직 검증되지
않았고, §14에서 별도로 ablation해야 판단할 수 있었다):

| 실패 사유 | 3년(7,508건 중) | 최근 12개월(2,544건 중) |
|---|---|---|
| `eligibility_low_relative_activity` | **5,983건(79.7%)** | **2,533건(99.6%)** |
| `eligibility_core_risk_off_guard_blocked`(§8의 축B) | 1,270건(16.9%) | 0건 |
| `eligibility_negative_overall_floor`(§8의 축C) | 253건(3.4%) | 11건(0.4%) |
| `eligibility_negative_slow_floor` | 2건(0.0%) | 0건 |

**`eligibility_low_relative_activity`가 차단의 압도적 대부분(3년
79.7%, 최근 12개월 99.6%)을 차지한다.** 이 조건은 코드
(`deterministic_trigger_engine.py:493-499`)에서 다음과 같이 정의된다:

```python
if (
    volume_surge_ratio is not None
    and turnover_surge_ratio is not None
    and max(volume_surge_ratio, turnover_surge_ratio) < 1.10
):
    reasons.append("eligibility_low_relative_activity")
    return False, tuple(reasons)
```

즉 **"거래량 급증 비율과 거래대금 급증 비율 중 큰 쪽이 평소 대비
10% 이상 늘지 않으면 차단"**하는 조건이다 — 국면(regime)이나 신호
강도(overall/slow)와 **전혀 무관한, 순수 유동성/활동성 게이트**다.
§8/§9/§11이 지금까지 조사한 "regime 관련 삼중 중복"은, 새 alpha
(`regime_conditional_signal`) 상위군의 차단 사유 중에서는 상대적으로
드물었다(3년 16.9%+3.4%=20.3%, 최근 12개월 0.4%) — **차단 빈도
기준으로는 완전히 별개의 네 번째 축(활동성 필터)이 가장 크게
나타났다.** (주의: "차단 빈도가 크다"는 그 자체로 "병목"이나
"과잉 억제"를 뜻하지 않는다 — 이는 §14에서 실제 ablation으로
검증해야 하는 별개의 질문이며, §13.5는 그 검증 이전의 추정임을
아래에서 밝힌다.)

### 13.5 (당시 해석, §14 보정 전) 과잉 억제 가능성에 대한 추정 — §14에서 대부분 반박·수정됨

1. **활동성 필터가 걸러낸 종목(3년 5,983건, 최근 12개월 2,533건)의
   forward return이 나쁘지 않다** — 이 필터가 알파와 무관하게
   작동하므로, "alpha가 찾은 좋은 종목"과 "최근 거래가 조용했던
   종목"이 상당 부분 겹칠 뿐, 실제 수익성과는 관계가 약할 수
   있다는 **추정**이 가능했다. 다만 이 추정은 "차단된 표본이
   플러스"라는 사실에만 근거했고, "제거했을 때 실제로 기대수익률이
   개선되는가"는 검증하지 않은 것이었다 — §14 ablation에서 완전
   제거는 오히려 생존군 평균을 낮추는 것으로 확인되어(No-Go), 이
   추정은 **반박됐다**.
2. "regime_conditional_signal을 넣어도 기존 차단 축이 그대로면
   효과가 상쇄되는가?"에 대한 답은 여전히 유효하다(60~68% 차단).
   그러나 그 상쇄의 **가장 빈번한 원인**은 §8/§9/§11이 조사한
   regime 관련 축이 아니라 활동성 필터(threshold 1.10)라는 것 —
   이는 SPPV-3의 조사 범위를 재조정할 근거가 됐다. **다만 당시
   "활동성 필터의 임계값(1.10)이 과도한지가 훨씬 더 큰 병목"이라고
   쓴 것은 앞질러 간 표현이었다 — "병목"인지 여부는 §14 ablation
   으로만 답할 수 있고, 그 결과는 완화 방향만 Watch(추가 검증
   필요)로 남았을 뿐 "병목 확정"은 아니다.**
3. 이 시점에는 활동성 필터를 제거했을 때의 forward return을 직접
   ablation하지 않았다(상위군 전체=차단 없음 가정 값을 근사치로만
   사용). **이 한계는 §14에서 실제로 해소됐다** — §14의 3개
   시나리오(현행/완화/완전 제거) 정밀 비교 결과를 최종 기준으로
   삼는다.

### 13.6 (당시 판정, §14로 갱신됨) Watch — alpha 자체는 Conditional Go 유지

**`regime_conditional_signal`의 alpha layer 대체 가치(§12)는 이번
실험으로 훼손되지 않았다** — 여전히 Conditional Go다(이 부분은
§14 이후에도 유효). **"결합 사용 시나리오"(새 alpha + 기존 차단
로직 그대로)는 확정 Go로 선언하지 않는다** — 이 시점엔 활동성
필터가 과잉 억제인지 아직 검증 전이었기 때문이다. **당시 판정:
Watch(추가 검증 필요).** §14에서 실제 ablation을 수행한 결과도
**결합 시나리오는 여전히 Watch로 유지**된다(완전 제거는 No-Go,
완화는 방향만 확인된 Watch) — 즉 이 판정 자체는 §14 이후에도
바뀌지 않았지만, 그 근거는 "필터가 과잉 억제라서"가 아니라
"완화가 개선을 보이는 방향이되 아직 확정 근거가 부족해서"로
바뀌었다는 점이 중요하다.

### 13.7 다음 단계 — 우선순위 재조정

1. **`eligibility_low_relative_activity` ablation 실험을 다음
   최우선으로 지정한다** — 이 필터를 제거(또는 임계값 완화)했을 때
   전체 BUY 후보 표본의 forward return이 개선되는지/악화되는지
   직접 검증한다. §8/§9/§11의 regime 축 조사보다 이 실험의 영향력이
   훨씬 크다는 것이 이번 턴에 확인됐다.
2. SPPV-3의 우선순위를 "국면 정의 통일"(§11) → "alpha layer
   교체"(§12) → **"활동성 필터 재검토"(§13, 신규 최우선)**로
   재조정할지 사용자 확인을 받는다.
3. §21 게이트가 `TRIGGERED`로 전환되는 시점과 별개로, 활동성 필터
   ablation은 지금 당장(신규 KIS 호출 없이) 수행 가능하다 — 다음
   턴 착수 후보로 남긴다.

## 14. `eligibility_low_relative_activity` 활동성 필터 정밀 ablation (SPPV-2.24)

§13.7에서 신규 최우선으로 지정한 활동성 필터 ablation을 실행했다.
스크립트: `scripts/validate_activity_filter_ablation.py`. 산출:
`logs/signal_ic_activity_filter_ablation_2026-07-16.json`, 실행 로그
`logs/activity_filter_ablation_run_2026-07-16.log` (신규 KIS 호출
0건 — `grep -c "HTTP Request:"` 확인, 기존 3년 캐시 88개 파일로
전량 서빙됨).

### 14.1 현행 코드 재확인

`deterministic_trigger_engine.py:493-499`:
```python
if (
    volume_surge_ratio is not None
    and turnover_surge_ratio is not None
    and max(volume_surge_ratio, turnover_surge_ratio) < 1.10
):
    reasons.append("eligibility_low_relative_activity")
    return False, tuple(reasons)
```
이 체크 직후의 참여율 체크 2개는 `portfolio_allocation.
recommended_max_order_value is not None`을 전제로 하는데, 이번
shadow 재구성(모든 SPPV 실험 공통)에서는 배분 상태를 시점 복원할 수
없어 `portfolio_allocation=None`을 그대로 사용한다 — 즉 이 체크
직후 항상 `eligibility_execution_feasibility_pass=True`로 낙하한다.
따라서 "활동성 필터 제거"는 곧 "그 사유로만 탈락한 표본을 즉시
통과 처리"와 동치이며, 별도 로직 재구현 없이 안전하게 시뮬레이션할
수 있음을 코드로 확인했다.

### 14.2 실험 설계

`regime_conditional_signal` 상위 20% 표본(§12/§13과 동일 정의) 중
활동성 필터를 제외한 다른 모든 체크를 이미 통과한 행을 대상으로,
활동성 비율 `max(volume_surge_ratio, turnover_surge_ratio)`의 임계값만
바꿔가며 3개 시나리오를 비교:

| 시나리오 | threshold |
|---|---|
| 현행 유지 | 1.10 |
| 완화 | 1.00 |
| 완전 제거 | 없음(필터 자체를 스킵) |

2차(3년, 56,753건 중 상위 10,999건)와 1차(최근 12개월, 21,315건 중
상위 4,165건) 두 창 모두에서 동일하게 산출.

### 14.3 실측 결과

**2차(3년, 상위 10,999건):**

| 시나리오 | 생존 n(%) | T+5 평균 | T+5 t_NW | T+5 양수율 | T+20 평균 | T+20 t_NW | T+20 양수율 |
|---|---|---|---|---|---|---|---|
| 현행(1.10) | 3,491(31.7%) | +1.4218% | 5.89 | 52.39% | +4.3809% | 5.78 | 51.76% |
| 완화(1.00) | 4,148(37.7%) | **+1.4894%** | **6.85** | **52.82%** | **+4.5601%** | **6.58** | 52.10% |
| 제거 | 9,474(86.1%) | +0.9833% | 8.02 | 50.74% | +3.8823% | 10.16 | **52.73%** |
| (참고)상위군 전체·무차단 | 10,999(100%) | +1.0079% | 9.06 | 51.20% | +3.5544% | 10.35 | 52.45% |

**1차(최근 12개월, 상위 4,165건):**

| 시나리오 | 생존 n(%) | T+5 평균 | T+5 t_NW | T+5 양수율 | T+20 평균 | T+20 t_NW | T+20 양수율 |
|---|---|---|---|---|---|---|---|
| 현행(1.10) | 1,621(38.9%) | +1.9724% | 4.50 | 53.92% | +5.8709% | 4.54 | 53.12% |
| 완화(1.00) | 1,931(46.4%) | **+2.1445%** | 5.48 | **55.15%** | **+6.4317%** | 5.44 | **54.17%** |
| 제거 | 4,154(99.7%) | +1.7090% | 7.48 | 53.61% | +5.7532% | 8.18 | 54.57% |
| (참고)상위군 전체·무차단 | 4,165(100%) | +1.7108% | 7.52 | 53.66% | +5.7210% | 8.16 | 54.48% |

두 창 모두 동일한 정성적 패턴: **평균 수익률·양수율 기준으로는
"완화(1.00)"가 최고점**이고, "완전 제거"는 오히려 "현행 유지"보다
낮아져 사실상 무차단 전체 평균에 수렴한다(2차 T+20 제거=3.8823%
vs 무차단 전체=3.5544% — 거의 동일). t_NW는 표본이 늘수록
표준오차가 줄어 제거 시나리오에서 가장 높게 나오지만, 이는 "표본이
많아서 통계적으로 유의해 보이는 것"일 뿐 평균 수익률 자체는
오히려 낮다 — 표본수 증가가 곧 품질 개선을 의미하지 않는다는
점을 데이터로 확인했다(사용자 지시사항 "통과율이 늘었다고 긍정
판단하지 말 것"과 정확히 일치하는 사례).

### 14.4 질문에 대한 답 (해석 보정판 — 2026-07-16 2차 검토 반영)

**보정 배경**: 최초 작성본은 "차단된 표본도 forward return이
플러스"라는 사실과 "완전 제거는 무차단 전체 수준으로 회귀한다"는
사실을 근거로 "필터는 주범이 아니다/과잉 억제가 아니다"라고 확정
서술했다. 그러나 이 판단 기준 자체가 틀렸다는 지적을 받았다 —
**옳은 비교 기준은 "차단된 표본이 플러스냐"가 아니라 "차단을
제거/완화했을 때 기대수익률이 실제로 개선되는가"다.** 아래는 이
기준으로 다시 정리한 결과다.

- **활동성 필터 제거가 기대수익률을 개선하는가?** → **아니오,
  개선된다는 근거는 없다.** 완전 제거 시 생존군의 평균 forward
  return과 양수율이 무차단 상위군 전체 수준으로 회귀(수렴)하며,
  현행(1.10) 유지 시의 생존군 평균보다도 낮다(2차 T+20 현행
  +4.381% vs 제거 +3.882% vs 무차단 전체 +3.554%). 즉 **현재
  실측상으로는 필터를 유지했을 때의 생존군 평균이 무차단 전체보다
  높다** — 이 하나의 사실만으로 필터를 "완전히 해롭다"고 볼 근거는
  없다.
- **임계값 완화(1.00)는 개선하는가?** → **방향성은 있으나 확정할
  수준은 아니다.** 생존 종목 수가 31.7%→37.7%(2차), 38.9%→
  46.4%(1차)로 늘면서 T+5/T+20 평균 수익률·t_NW·양수율이 현행보다
  소폭(0.07~0.18%p 수준) 높게 나왔고 두 창에서 방향이 일관됐다.
  다만 (a) 검증한 shadow threshold가 1.00 단 하나뿐이고, (b)
  개선폭이 크지 않으며, (c) 동일 표본·동일 window에서의 단일
  실험이라 out-of-sample 재확인이 없다는 점에서, 이를 "완화가
  기대수익률을 개선한다"는 확정 결론으로 쓰기에는 근거가 아직
  부족하다. **"완화 방향이 유력해 보이나, 확정 짓기 위해서는 추가
  검증(다른 threshold, 다른 기간)이 필요하다"는 수준으로만 기록한다.**
- **활동성 필터가 BUY 0건의 주범인가 / 과잉 억제인가?** →
  **이번 실측만으로는 확정할 수 없다.** §13에서 확인한 "차단
  사유의 79.7~99.6%를 차지"라는 사실은 이 필터가 가장 빈번하게
  작동하는 차단 축이라는 것을 보여줄 뿐, 그 자체로 "과잉 억제"나
  "주범"을 증명하지 않는다. 오히려 이번 실측은 (제거 시나리오가
  현행보다 낮은 평균을 보인다는 점에서) **필터를 완전히 없애는
  것이 정답이 아니라는 근거**는 제공했지만, 반대로 필터가
  "정당함/불필요함" 어느 쪽인지를 확정할 만큼 강한 근거는 아니다.
  **결론: "재검토가 필요한 후보"로 남기되, "주범 확정" 또는
  "과잉 억제 확정"이라는 표현은 쓰지 않는다.**

### 14.5 판정 — Watch(추가 검증 필요), 완전 제거만 No-Go로 확정

**활동성 필터 자체를 제거하는 안은 No-Go로 확정** — 데이터가
일관되게 기대수익률(평균 forward return)이 개선되지 않음을
보여준다(현행 유지보다도 낮음). **임계값을 1.10 → 1.00으로
완화하는 안은 Watch(방향은 유력, 확정 아님)** — 1차·2차 두 창
모두에서 생존 종목 수 증가와 함께 평균 수익률·t_NW·양수율이 소폭
개선되는 방향은 일관되게 관측됐으나, 개선폭이 작고 단일 threshold
실험이라 "Conditional Go"로 올리기에는 근거가 이르다. **필터
자체의 존폐(주범 여부/과잉 억제 여부) 판정도 Watch** — 확정하지
않는다. 이번 턴은 shadow 검증 범위이며, 실제
`deterministic_trigger_engine.py`의 threshold 상수는 이 문서가
더 강한 Go 판정을 확보하기 전까지 변경하지 않는다.

### 14.6 다음 단계

1. threshold를 1.00 외에도 추가로(예 0.95, 0.90) 스윕하여 완화
   방향의 개선이 재현되는지, 개선-정체/역전 지점(sweet spot)이
   있는지 확인하는 추가 shadow 실험 — 이것이 완화안을 Conditional
   Go로 올리기 위한 선행 조건이다.
2. 가능하면 표본 기간을 다르게 쪼개(예: 최근 6개월 vs 그 이전
   6개월) out-of-sample 재현성을 확인 — 현재는 동일 창 내 단일
   비교라 재현성 검증이 없다.
3. §13에서 남았던 "결합 사용 시나리오"의 Watch 판정은 이번 결과로도
   **Watch로 유지**한다 — 완화 방향이 유력하다는 정황은 늘었으나,
   확정 Go로 상향할 근거는 아직 없다.
4. threshold 상수를 실제 운영 코드에 반영하는 것은 위 1~2가
   Conditional Go 이상으로 확정된 뒤, 별도 턴에서 사용자 승인을
   받아 진행한다.
