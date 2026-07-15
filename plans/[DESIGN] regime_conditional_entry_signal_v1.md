# 국면 분기형 진입 신호 설계 (regime_conditional_entry_signal v1)

작성일: 2026-07-15
상태: **설계 초안 + shadow 계산기 1차 실행 완료 — 실거래/`entry_score` 반영 없음.**
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

### 4.2 Phase 2(다음 턴 이후): 반복 shadow 로깅 + out-of-sample 누적

- 이 스크립트를 향후 3년 캐시를 갱신할 때마다(또는 별도 주기로) 함께
  실행해, **매번 다른 날짜의 스냅샷을 시계열로 누적**한다. 이는 새로운
  KIS 호출을 반복 발생시키지 않도록 캐시 우선 재사용을 유지한다.
- 충분한 관측치가 쌓이면(특히 하락장이 실제로 재발하면), §16 이원
  기준을 그대로 적용해 `regime_conditional_signal`을 **점수 하나의
  shadow feature가 아니라 entry 후보로서** 재검증한다 — 이는 §21
  모니터링 스크립트의 `TRIGGERED` 신호와 연동된다.

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

## 6. 다음 단계

1. Phase 2(반복 shadow 로깅)를 향후 SPPV 턴 또는 3년 캐시 갱신 시
   함께 수행한다 — 별도 스케줄러 등록은 운영 인프라 변경 금지 원칙에
   따라 이번 턴에는 하지 않는다.
2. §21 모니터링이 `TRIGGERED`로 전환되면, 이 문서 §4.3의 Go/No-Go
   기준으로 `regime_conditional_signal`을 정식 재검증한다.
3. §3의 `entry_score` 통합안은 제안 단계에 머문다 — `risk_off_
   penalty`와의 중복 여부는 SPPV-3(중복 penalty ablation) 착수 시
   함께 정리한다.
4. `event_driven_unstable` 국면은 여전히 신호 미산출 상태로 둔다 —
   표본이 쌓이기 전까지 임의로 채우지 않는다.
