# 신호 예측력 실증 검증 설계 (Signal Predictive Power / IC Validation)

작성일: 2026-07-14
상태: 파일럿 완료 — §6 결과 참고
상위 문서: `plans/[ANALYSIS] foundational_design_review_objective_alignment_2026-07-14.md`
(2순위 작업 — 목표 B "최고 기대수익률" 확정에 따른 신호 토대 검증)

---

## 0. 목적

시스템의 신호(`slow_score`/`fast_score`/`overall_score` 및 구성요소
`slow_momentum`/`slow_trend`)가 **실제로 미래 수익률을 예측하는가**를
과거 데이터로 실증한다. 지금까지 이 신호들은 "좋으면 오를 것"이라는 가정
위에 하드코딩 가중치로 만들어졌을 뿐, 예측력이 검증된 적이 없다(근본 진단
Q2/Q3). 목표 B(최고 기대수익률)를 추구하려면 "무엇을 근거로 사고 파는가"의
토대인 이 신호의 예측력이 선결 검증 대상이다.

**이 작업은 gate 완화가 아니라 순수 read-only 관측 분석이다** — 완화 금지
원칙과 충돌하지 않는다. DB/주문 경로를 일절 건드리지 않는다.

## 1. 검증 대상과 비대상

- **대상(순수 재계산 가능)**: `slow_momentum`, `slow_trend`, `slow_score`,
  `fast_score`, `overall_score`. `build_signal_snapshot(symbol, bars)`가
  일봉 리스트만으로 결정론적으로 재계산하는 순수 함수임이 확인됨
  (`signal_backbone.py:65-73`).
- **비대상(이번 범위 밖)**: `entry_score` — regime/allocation/strategy/
  position 등 외부 상태 히스토리에 의존해 순수 재계산 불가
  (`deterministic_trigger_engine.py:1115-1170`). entry_score는 overall_score
  위에 게이트를 씌운 것이므로, 토대인 overall_score의 예측력이 먼저
  검증되어야 의미가 있다. entry_score 자체의 IC는 regime 히스토리 스냅샷을
  별도 확보한 뒤 후속 단계에서 다룬다.

## 2. 방법론 — Rolling out-of-sample IC

1. **표본 기간**: 과거 약 1년(상승·하락·횡보 국면 모두 포함) — 지난
   백테스트의 "단일 하락 국면 편향"(Q3)을 구조적으로 해소.
2. **데이터**: KIS `inquire_daily_itemchartprice`(일봉, 수정주가) — 호출당
   ~100거래일 제한이므로 날짜창을 슬라이딩하며 다회 병합. volume(`acml_vol`)/
   turnover(`acml_tr_pbmn`)까지 매핑해 fast_score 왜곡 방지.
3. **Rolling 재계산**: 각 거래일 T(최소 lookback 61봉 이후 ~ 마지막-5봉)마다
   `bars[:T+1]`을 슬라이스해 `build_signal_snapshot` 호출 → 그 시점의 신호값
   기록.
4. **Forward return**: 각 T에 대해 `(close[T+h]/close[T] - 1)`, h∈{1,3,5}.
5. **IC(Information Coefficient)**: 전체 (신호값, forward_return) 쌍에 대한
   **Spearman 순위상관**. 신호별 × horizon별로 산출. numpy/scipy 부재이므로
   순수 파이썬으로 순위상관 구현(순위화 → 피어슨).
6. **유의성**: 표본 수 N과 t-stat = IC·√((N-2)/(1-IC²)) 병기.

## 3. 성공/실패 판정 기준 (업계 통상)

- |IC| < 0.02: 예측력 사실상 없음(노이즈)
- 0.02 ≤ |IC| < 0.05: 미약하나 존재
- 0.05 ≤ |IC| < 0.10: 유의미
- |IC| ≥ 0.10: 강함
- **부호도 중요**: 신호↑ → 수익률↑이면 양(+)의 IC(설계 의도대로). 음(-)이면
  신호가 역방향(설계 가정이 틀림).

## 4. 단계

- **4.1 파일럿**: core 8종목 × 1년 × slow/fast/overall IC 측정. 목적은
  "파이프라인이 실제로 유효한 IC 숫자를 내는가" 확인 + 초기 신호. 산출물:
  `scripts/validate_signal_predictive_power.py`(read-only),
  `logs/signal_ic_pilot_2026-07-14.*`.
- **4.2 확장**: 파일럿이 유효하면 core 전체(~90종목)로 확대, 국면별
  (bullish/bearish/range) 분해 IC까지.
- **4.3 판단**: IC 결과에 따라 3순위 분기 —
  - 예측력 있음 → 신호 강화·가중치 실증 최적화(하드코딩 매직넘버 교체)
  - 예측력 없음 → 신호 체계 재설계 (현재 룰 기반 → 실증 기반)

## 5. 안전 불변식

- read-only: DB write 0, 주문 경로 0, 실시간 시세 구독 0.
- KIS 호출은 과거 일봉 조회(read)만. rate budget 고려해 종목간 sleep.
- python3, 로그/산출은 `/workspace/agent_trading/logs`.
- 신호 재계산은 운영 코드(`build_signal_snapshot`)를 그대로 재사용 —
  검증용 별도 로직을 만들지 않아 운영과의 정합성 보장.

---

## 6. 파일럿 결과 (2026-07-14)

대상: core 대형주 8종목(삼성전자·SK하이닉스·NAVER·현대차·기아·셀트리온·
삼성바이오·KB금융) × 과거 약 1년(종목당 일봉 270개, rolling 표본 205개) →
**총 표본 1,640**. 산출: `logs/signal_ic_pilot_2026-07-14.json`.
Spearman 순위상관(IC), t = IC·√((N-2)/(1-IC²)). (|t|>2 대략 유의)

| 신호 | T+1 IC(t) | T+3 IC(t) | T+5 IC(t) |
|---|---|---|---|
| **slow_momentum** | +0.046(1.87) | +0.080(3.25) | **+0.101(4.11)** |
| **overall_score** | +0.038(1.52) | +0.070(2.84) | **+0.084(3.41)** |
| **slow_score** | +0.031(1.27) | +0.061(2.45) | +0.078(3.15) |
| slow_trend | +0.009(0.37) | +0.032(1.27) | +0.041(1.64) |
| fast_score | +0.011(0.45) | +0.025(1.01) | +0.031(1.27) |

### 핵심 결론
1. **신호에 예측력이 실재한다.** slow_momentum(T+5 IC=+0.10, t=4.11)과
   overall_score(T+3~5 IC=+0.07~0.08, t>2.8)는 통계적으로 유의한 양의
   예측력을 보인다. → **목표 B(최고 기대수익률) 추구의 토대가 존재한다.**
   "신호가 완전 노이즈"라는 최악 시나리오는 배제됐다.
2. **모든 IC의 부호가 양(+)** → 신호↑ → 미래수익률↑, 설계 의도대로 방향이
   맞다(역방향 아님).
3. **예측력이 신호별로 극명하게 갈린다:**
   - `slow_momentum`(3개월 수익률 기반)이 예측력의 **주력**.
   - `fast_score`는 사실상 **예측력 없음**(전 구간 t<2, T+1은 노이즈).
   - `slow_trend`(SMA60 이격)도 **약함**(t<2).
4. **horizon이 길수록 IC 상승**(T+1<T+3<T+5) → 이 신호들은 단기(1일)보다
   중기(3~5일) 예측에 적합하다.

### 실행 함의 (3순위 근거)
- `overall_score = 0.55·slow + 0.45·fast`인데 **fast가 노이즈이므로, 0.45
  가중치가 오히려 예측력을 희석**하고 있을 가능성이 높다(단독 slow_momentum
  IC 0.10 > overall 0.08). `slow_score = 0.6·momentum + 0.4·trend`의 trend
  0.4 가중치도 예측력 낮은 요소에 과다 배분.
- → **가중치를 예측력 실측 기반으로 재조정하면 신호 품질을 올릴 여지가
  크다**(하드코딩 매직넘버 → 실증 최적화). 이것이 3순위의 구체적 착수점.

### 파일럿의 한계 (확장 시 보완 필요)
- **overlap 편향**: rolling로 매일 표본을 뽑아 forward window가 겹치므로
  유효 독립표본 수 < 1,640. **t-stat이 과대평가**됐을 수 있다(실제 유의성은
  다소 낮을 것). 확장 시 non-overlapping 표본 또는 Newey-West 보정 필요.
- **8종목·단일 1년·pooled**: 국면별(bullish/bearish/range) 분해 IC 미측정.
  상승/횡보장에서도 예측력이 유지되는지는 4.2 확장에서 확인.
- fast_score의 volume/turnover는 매핑했으나 수정주가 일관성은 미검증.

### 다음 단계
- 4.2 확장: core 전체(~90종목) + 국면별 분해 + overlap 보정.
- 3순위: 가중치 실증 재조정(shadow 필드로 먼저 관측 → 승격).
