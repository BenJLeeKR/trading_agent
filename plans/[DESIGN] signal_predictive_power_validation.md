# 신호 예측력 실증 검증 설계 (Signal Predictive Power / IC Validation)

작성일: 2026-07-14
상태: SPPV-2.5 완료 — **quintile spread의 pooled 유의성은 국면 혼입 착시로
판정, SPPV-3(entry_score 전체 재현) 착수 조건부 보류 유지.** §11 참고.
상위 문서: `plans/[ANALYSIS] foundational_design_review_objective_alignment_2026-07-14.md`
(최우선 작업 — 목표 B "최고 기대수익률" 확정과 BUY 주문 0건 복구를 위한 신호·진입 경로 검증)

## 수정 이력

- 작성자: Codex
- 수정일자: 2026-07-14
- 수정내용: 최고 기대수익률을 손실 제약 아래의 목적함수로 명확히 하고,
  `2026-06-25` 이후 BUY 주문 0건 실측, 통계 보정, `entry_score` 및 전체 BUY
  funnel back-simulation, 제한적 probe 승격 단계를 설계에 추가했다. 이어서
  관련 문서 기준 현재 진행 상태를 한눈에 확인할 수 있는 체크리스트를 추가했다.

- 작성자: Claude
- 수정일자: 2026-07-14
- 수정내용: **SPPV-2(통계 보정 확장) 실행 완료**. core 전체(88종목) ×
  cross-sectional 거래일별 Spearman IC × Newey-West 보정 × 국면별 분해 ×
  비용 차감 quintile 성과를 실측했다. **SPPV-1 파일럿의 낙관적 결론(t=2.4~4.1,
  "유의미"~"강함")이 overlap 편향의 산물이었음이 확인됐다** — 정확히 보정한
  cross-sectional IC는 전 신호·전 horizon에서 |t_NW|<1.1로 통계적 유의성
  없음. §9에 상세 결과와 조건부 보류(Hold) 판정을 기록했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (2차)
- 수정내용: **SPPV-2.5(quintile spread 정체 진단) 실행 완료**. `overall_score`
  quintile spread 자체를 Newey-West로 재검정(pooled t_NW=2.30, 유의)했으나,
  **국면 내부(within-regime) 분해에서는 어느 국면도 단독으로 유의하지
  않음**(최고 bullish_trend t_NW=1.55) — pooled 유의성이 국면 혼입(regime
  mix) 착시일 가능성이 높다는 결론. **SPPV-3(entry_score 전체 재현) 착수를
  계속 보류**한다. §11 상세 참고.

---

## 진행 체크리스트

이 문서를 `SPPV` 트랙의 **작업 진행 기준 문서**로 사용한다. 세부 근거는
`plans/[ANALYSIS] foundational_design_review_objective_alignment_2026-07-14.md`,
우선순위 반영 상태는 `plans/[PRIORITY_MAP] remaining_work_priority_map.md`,
백로그 승격 상태는 `plans/[BACKLOG] backlog.md`와 함께 동기화한다.

### A. 기준선 및 설계 정렬

- [x] 목표 함수와 손실 제약 정의를 `최고 기대수익률 + 손실 제약`으로 고정
- [x] `2026-06-25` 이후 BUY 주문 0건의 직접 병목이 `entry_score < 0.65`임을 실측
- [x] risk/compliance를 목적함수가 아닌 제약조건으로 재정의
- [x] `core_risk_off` 완화 중심 접근을 중단하고 신호/진입 경로 검증으로 전환
- [x] 관련 문서(`ANALYSIS`/`BACKLOG`/`PRIORITY_MAP`)에 방향 전환 반영

### B. SPPV 단계별 진행 상태

- [x] **SPPV-1** 파일럿 IC 측정 완료
  - 상태: core 8종목 pooled IC 산출 완료, 결론은 보류
  - 산출물: `logs/signal_ic_pilot_2026-07-14.*`
- [x] **SPPV-2** 통계 보정 확장 (완료, 2026-07-14)
  - 작업 범위: core 전체(88종목, point-in-time universe는 데이터 부재로 제외·
    한계로 명시) + 국면별 cross-sectional IC/ICIR + non-overlap/Newey-West +
    비용 차감 quintile 성과(T+1/T+3/T+5/T+10/T+20)
  - **결과: 정확히 보정한 cross-sectional IC는 전 신호·전 horizon에서
    |t_NW|<1.1 — 통계적 유의성 없음.** SPPV-1의 "유의미"~"강함" 결론은
    overlap 편향의 산물이었음이 확인됨. §9 상세 참고.
  - 산출물: `scripts/validate_signal_predictive_power_v2.py`(read-only),
    `logs/signal_ic_sppv2_expanded_2026-07-14.json`,
    `logs/sppv2_run_2026-07-14.log`
- [x] **SPPV-2.5** quintile spread 정체 진단 (완료, 2026-07-14)
  - 작업 범위: `overall_score` quintile spread 자체의 Newey-West 유의성
    검정 + 국면 내부(within-regime) 분해(bullish/bearish/range_bound 각각
    단독으로 spread 재계산)
  - **결과: pooled spread는 유의(T+20 t_NW=2.30)하나, 국면 내부 어느 곳도
    단독 유의하지 않음(최고 bullish_trend t_NW=1.55, range_bound t_NW=1.63,
    bearish_trend t_NW=0.38)** — pooled 유의성이 국면 혼입(regime mix)
    착시일 가능성이 높음. §11 상세 참고.
  - 산출물: `scripts/validate_signal_predictive_power_v2_5.py`(read-only),
    `logs/signal_ic_sppv2_5_regime_decomposition_2026-07-14.json`,
    `logs/_bars_cache_core88_2026-07-14/`(재사용 캐시)
- [~] **SPPV-3** `entry_score` point-in-time 재현 및 중복 penalty ablation
  - **조건부 보류 유지**: SPPV-2.5에서 국면 내부 유의성이 확보되지 않아,
    지금 SPPV-3으로 진행하면 검증 안 된 신호 위에 재현 작업을 쌓는 셈이
    된다. §11.5 다음 단계 참고 — 표본 확장(기간·종목 수) 후 국면 내부
    유의성이 재확인되어야 착수한다.
  - 작업 범위: regime/allocation/strategy/source 복원, signal 약세와
    `risk_off_penalty`/eligibility 중복 억제 분해
- [ ] **SPPV-4** 전체 BUY funnel back-simulation
  - 작업 범위: `candidate → selected → expected value → would_buy → submitted`
    counterfactual 전환과 MFE/MAE/낙폭 비교
- [ ] **SPPV-5** out-of-sample 기대수익 및 손실 제약 Go/No-Go 판정
  - 작업 범위: Virtual BUY 수익률, 승률, 비용 차감 성과, 손실 제약 동시 검증
- [ ] **SPPV-6** 제한적 paper probe
  - 착수 조건: SPPV-5에서 Go 판정 + 별도 승인

### C. 현재 판단 기준

- [x] 현재 최우선 작업은 `SPPV-2.5`(완료) → **표본 확장 재검증 또는 신호
  체계 재검토** 판단 필요
- [x] 단순 threshold 하향, risk/compliance 제거, broker submit 경계 변경은 금지
- [x] 잔여 quintile spread가 regime 컨파운드인지 확인 완료 — **국면 혼입
      착시 가능성이 높음으로 판정, `SPPV-3` 착수 보류 유지**
- [ ] `entry_score` 재현 결과를 바탕으로 shadow formula 후보를 확정
- [ ] Virtual BUY 기준 기대수익/손실 제약을 동시에 만족하는 공식 확보
- [ ] 제한적 paper probe 승격 승인 확보

### D. 체크리스트 운영 규칙

- [x] 단계 완료 시 본 문서 체크박스와 `수정 이력`을 함께 갱신
- [x] 세부 분석 결과는 `ANALYSIS` 문서에 누적하고, 본 문서에는 단계 상태만 요약
- [x] 우선순위 변경 시 `PRIORITY_MAP`의 최신 메모와 실행 순서를 동기화
- [x] 새 실행 항목이 생기면 `BACKLOG`에도 같은 용어(`SPPV-*`)로 반영

## 0. 목적

시스템의 신호(`slow_score`/`fast_score`/`overall_score` 및 구성요소
`slow_momentum`/`slow_trend`)가 **실제로 미래 수익률을 예측하는가**를
과거 데이터로 실증한다. 지금까지 이 신호들은 "좋으면 오를 것"이라는 가정
위에 하드코딩 가중치로 만들어졌을 뿐, 예측력이 검증된 적이 없다(근본 진단
Q2/Q3). 목표 B(최고 기대수익률)를 추구하려면 "무엇을 근거로 사고 파는가"의
토대인 이 신호의 예측력이 선결 검증 대상이다.

이 작업의 최종 목적은 IC 숫자 확인 자체가 아니라, 약 20일간 지속된
`2026-06-25` 이후 BUY 주문 0건 상태를 해소할 수 있는 **예측 가능한 진입
경로**를 만드는 것이다. 단순 threshold 완화는 금지하지만, 실측 근거를 갖춘
`entry_score`/가중치/중복 penalty 재설계와 제한적 probe 승격은 범위에 포함한다.

### 0.1 목표 함수와 손실 제약

이 시스템은 손실 0을 목표로 하지 않는다. 목표는 다음처럼 고정한다.

```text
maximize E[net forward return]
subject to
  허용 손실 한도
  VaR / drawdown / exposure limit
  유동성 및 주문 실행 가능성
  계좌 단위 위험 한도
```

수익률은 1순위 목적함수이고 리스크는 모든 후보를 제거하는 목적함수가 아니라
감내 가능한 손실 범위를 강제하는 제약조건이다. 따라서 약세 신호가 있다는
이유만으로 신호 산식, regime penalty, eligibility에서 동일 위험을 중복 차감하는
구조는 별도 검증 대상이다.

## 1. 검증 대상과 비대상

- **Phase 0 대상(순수 재계산 가능)**: `slow_momentum`, `slow_trend`, `slow_score`,
  `fast_score`, `overall_score`. `build_signal_snapshot(symbol, bars)`가
  일봉 리스트만으로 결정론적으로 재계산하는 순수 함수임이 확인됨
  (`signal_backbone.py:65-73`).
- **Phase 1~3 필수 대상**: `entry_score`, regime/allocation/strategy/source bonus,
  `risk_off_penalty`, BUY eligibility, ranking, expected value, AI decision,
  compliance/VaR, sizing, submit lane. `entry_score`는 외부 상태 히스토리를
  복원해야 하므로 Phase 0에서만 제외하며, 전체 작업 범위에서는 직접 병목으로
  다룬다. backbone 검증만 끝내고 작업을 닫지 않는다.
- **비대상**: broker submit 경계를 AI로 이동하는 변경, compliance/VaR hard
  limit 제거, 근거 없는 threshold 일괄 하향.

## 2. 방법론 — Rolling out-of-sample IC

1. **표본 기간**: 과거 약 1년 이상(상승·하락·횡보 국면 모두 포함) — 지난
   백테스트의 "단일 하락 국면 편향"(Q3)을 구조적으로 해소.
2. **데이터**: KIS `inquire_daily_itemchartprice`(일봉, 수정주가) — 호출당
   ~100거래일 제한이므로 날짜창을 슬라이딩하며 다회 병합. volume(`acml_vol`)/
   turnover(`acml_tr_pbmn`)까지 매핑해 fast_score 왜곡 방지.
3. **Rolling 재계산**: 각 거래일 T(최소 lookback 61봉 이후 ~ 마지막-5봉)마다
   `bars[:T+1]`을 슬라이스해 `build_signal_snapshot` 호출 → 그 시점의 신호값
   기록.
4. **Forward return**: 각 T에 대해 `(close[T+h]/close[T] - 1)`,
   h∈{1,3,5,10,20}. 원수익률과 시장/업종 대비 초과수익률을 함께 저장한다.
5. **비용·손실 측정**: 왕복비용/슬리피지 차감 수익률, MFE, MAE, 최대낙폭,
   양수 비율을 함께 계산한다.
6. **IC(Information Coefficient)**: 파일럿 pooled IC는 탐색용으로만 유지하고,
   본 검증은 거래일별 cross-sectional Spearman IC의 평균, ICIR, 부호 일관성을
   기본값으로 사용한다. 종목별 time-series IC는 별도 보조 지표로 분리한다.
7. **유의성 보정**: T+3/T+5 등 겹치는 forward window와 종목·거래일 군집을
   고려해 non-overlapping 표본, Newey-West 또는 block bootstrap을 적용한다.
   독립 표본을 전제한 단순 t-stat은 파일럿 참고값으로만 표기한다.
8. **표본 구성**: 현재 살아남은 core 종목만 쓰지 않고 가능한 범위에서 당시
   point-in-time universe와 편입·편출 종목을 포함해 선택·생존 편향을 줄인다.

## 3. 성공/실패 판정 기준

- |IC| < 0.02: 예측력 사실상 없음(노이즈)
- 0.02 ≤ |IC| < 0.05: 미약하나 존재
- 0.05 ≤ |IC| < 0.10: 유의미
- |IC| ≥ 0.10: 강함
- **부호도 중요**: 신호↑ → 수익률↑이면 양(+)의 IC(설계 의도대로). 음(-)이면
  신호가 역방향(설계 가정이 틀림).
- 위 IC 구간은 탐색용 분류일 뿐 승격 기준이 아니다. authoritative 후보가 되려면
  국면별 부호 일관성, 비용 차감 기대수익 양수, 손실 제약 충족, out-of-sample
  재현성을 모두 만족해야 한다.
- 단순 후보 증가나 WATCH 증가는 성공이 아니다. `Virtual BUY → eligibility →
  expected value → would_buy → submitted` 전환과 후행 성과가 함께 개선돼야 한다.

## 4. 단계

- **4.1 파일럿(완료)**: core 8종목 × 1년 × slow/fast/overall IC 측정. 목적은
  "파이프라인이 실제로 유효한 IC 숫자를 내는가" 확인 + 초기 신호. 산출물:
  `scripts/validate_signal_predictive_power.py`(read-only),
  `logs/signal_ic_pilot_2026-07-14.*`.
- **4.2 통계 보정 확장**: core 전체와 point-in-time 확장 universe를 대상으로
  국면별 IC, cross-sectional IC/ICIR, overlap 보정까지 수행한다.
- **4.3 `entry_score` 재현**: 거래일별 regime/allocation/strategy/source 상태를
  복원해 당시 `entry_score`와 BUY eligibility를 point-in-time으로 재계산한다.
- **4.4 중복 억제 분해**: 약한 signal, `risk_off_penalty=-0.15`, regime
  eligibility block이 동일 위험을 몇 번 반영하는지 ablation으로 분리한다.
- **4.5 전체 funnel back-simulation**: 각 shadow formula별 Virtual BUY를 만들고
  `candidate → selected → expected value → would_buy → submitted` 가상 전환율과
  비용 차감 수익률/MAE/낙폭을 비교한다.
- **4.6 제한적 probe**: out-of-sample 기대수익 양수와 손실 제약을 만족한 공식만
  일일 top-k, 최소 수량, 계좌 위험한도 아래 paper probe로 승격한다. 전체
  threshold 일괄 완화는 허용하지 않는다.

## 5. 안전 불변식

- Phase 0~4는 read-only/shadow: 운영 DB write 0, 주문 경로 0, 실시간 시세 구독 0.
- 4.6 probe는 별도 Go 승인 후에만 실행하며 deterministic risk/compliance/
  guardrail과 broker submit 경계를 그대로 유지한다.
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
1. **예측력 존재 가능성을 지지하는 초기 신호가 확인됐다.** slow_momentum
   (T+5 pooled IC=+0.10)과 overall_score(T+3~5 pooled IC=+0.07~0.08)는
   확장 검증 가치가 있다. 다만 overlap·군집 의존성을 보정하기 전에는
   "통계적으로 입증" 또는 "완전 노이즈 배제"로 확정하지 않는다.
2. **모든 IC의 부호가 양(+)** → 신호↑ → 미래수익률↑, 설계 의도대로 방향이
   맞다(역방향 아님).
3. **예측력이 신호별로 극명하게 갈린다:**
   - `slow_momentum`(3개월 수익률 기반)이 예측력의 **주력**.
   - `fast_score`는 사실상 **예측력 없음**(전 구간 t<2, T+1은 노이즈).
   - `slow_trend`(SMA60 이격)도 **약함**(t<2).
4. **horizon이 길수록 pooled IC 상승**(T+1<T+3<T+5) → 중기 예측에 적합할
   가능성이 있으나 T+10/T+20과 비용 차감 성과로 재확인한다.

### 실행 함의 (3순위 근거)
- `overall_score = 0.55·slow + 0.45·fast`인데 **fast가 노이즈이므로, 0.45
  가중치가 오히려 예측력을 희석**하고 있을 가능성이 높다(단독 slow_momentum
  IC 0.10 > overall 0.08). `slow_score = 0.6·momentum + 0.4·trend`의 trend
  0.4 가중치도 예측력 낮은 요소에 과다 배분.
- → 가중치 재조정 가설은 타당하지만 단일 IC 크기 비교만으로 비중을 바꾸지
  않는다. partial IC, ablation, train/validation/test 분리를 먼저 수행한다.

### 파일럿의 한계 (확장 시 보완 필요)
- **overlap 편향**: rolling로 매일 표본을 뽑아 forward window가 겹치므로
  유효 독립표본 수 < 1,640. **t-stat이 과대평가**됐을 수 있다(실제 유의성은
  다소 낮을 것). 확장 시 non-overlapping 표본 또는 Newey-West 보정 필요.
- **8종목·단일 1년·pooled**: 국면별(bullish/bearish/range) 분해 IC 미측정.
  상승/횡보장에서도 예측력이 유지되는지는 4.2 확장에서 확인.
- fast_score의 volume/turnover는 매핑했으나 수정주가 일관성은 미검증.

### 다음 단계
- 4.2 통계 보정 확장: core 전체 + point-in-time universe + 국면별 분해.
- 4.3 `entry_score` point-in-time 재현과 중복 penalty ablation.
- 4.5 전체 BUY funnel counterfactual 및 비용·손실 제약 검증.

## 7. BUY 주문 0건 운영 기준선 (2026-07-14 재검증)

운영 DB를 `2026-06-25` 이후 `symbol + trade_date` 첫 decision으로 중복 제거해
확인한 결과다.

| 항목 | 실측 |
|---|---:|
| 표본 | 297건 |
| `entry_score >= 0.52` | 24건 |
| `entry_score >= 0.65` | 0건 |
| `BUY_CANDIDATE` | 0건 |
| eligibility 통과 | 21건 |
| `risk_off_penalty` 적용 | 294건 |
| 최대 / 평균 `entry_score` | 0.6086 / 0.1699 |
| BUY 주문요청 / broker submit | 0건 / 0건 |

마지막 BUY 주문은 `2026-06-24`다. 이 기간에는 eligibility를 통과한 표본도
`entry_score` threshold를 넘지 못했으므로, BUY 0건의 직접적인 기계적 병목은
하류 expected value/compliance/broker가 아니라 `entry_score < 0.65`다.
하류 계층은 현재 현상의 1차 원인이 아니지만, 새 formula가 후보를 만들기
시작하면 전체 funnel에서 다시 검증한다.

## 8. 목표 BUY 경로의 책임 분리

```text
alpha / expected-return layer
  -> 미래 순수익 예측과 후보 순위화
entry projection layer
  -> entry_score / top-k / minimum edge
risk constraint layer
  -> VaR / drawdown / exposure / liquidity 한도
compliance / guardrail layer
  -> 금지 종목 / 주문 형태 / 계좌 상태 hard block
execution layer
  -> sizing / submit / post-submit convergence
```

시장 약세를 alpha, entry penalty, eligibility에서 반복 차감하지 않는다. 예측
신호는 기대수익을 순위화하고, risk/compliance는 감내 불가능한 손실과 위반만
authoritative하게 차단한다.

## 9. SPPV-2 확장 검증 결과 (2026-07-14)

### 9.1 실행 개요

- 대상: `APPROVED_CORE_UNIVERSE_SYMBOLS` core 종목 **88개 전체**(현재 생존
  종목만 — point-in-time universe는 §9.4 한계에서 별도 설명).
- 기간: 종목당 일봉 270개(약 1년), rolling 표본 190개/종목.
- 총 rolling 표본: **16,720건**.
- 국면 분포(자체 regime_label 기준): `bullish_trend` 8,356(50%),
  `range_bound` 4,989(30%), `bearish_trend` 3,127(19%),
  `event_driven_unstable` 248(1.5%) — **다국면 확보 확인**(SPPV-1의
  "단일 하락국면" 한계 해소).
- 산출: `scripts/validate_signal_predictive_power_v2.py`(read-only),
  `logs/signal_ic_sppv2_expanded_2026-07-14.json`,
  `logs/sppv2_run_2026-07-14.log`.

### 9.2 핵심 결과 — cross-sectional IC (거래일별, Newey-West 보정)

| 신호 | T+1 | T+3 | T+5 | T+10 | T+20 |
|---|---|---|---|---|---|
| slow_score | t=-0.71 | t=-0.12 | t=0.18 | t=0.55 | t=0.89 |
| fast_score | t=-0.25 | t=0.49 | t=0.27 | t=0.48 | t=0.62 |
| overall_score | t=-0.56 | t=0.16 | t=0.32 | t=0.62 | **t=1.08** |
| slow_momentum | t=-0.72 | t=-0.11 | t=0.22 | t=0.58 | t=0.85 |
| slow_trend | t=-0.84 | t=-0.15 | t=0.14 | t=0.57 | t=1.06 |

(non-overlapping 표본으로도 재계산했으며 결과는 동일하게 |t|<2 — 대표 값은
overlapping/non-overlapping 모두 `logs/signal_ic_sppv2_expanded_2026-07-14.json`
참고.)

**모든 신호·모든 horizon에서 |t_NW| < 1.1** — 통상 유의성 기준(|t|≳2)에
크게 못 미친다. **SPPV-1 파일럿에서 관측한 t=2.4~4.1("유의미"~"강함")은
overlap 표본(매일 rolling으로 뽑아 forward window가 겹침)과 pooled 처리로
인한 통계적 착시였다.** 정확한 거래일별 cross-sectional 설계 + Newey-West
보정을 적용하자 그 유의성이 전부 사라졌다 — SPPV-1 §"파일럿의 한계"에서
예견했던 우려가 실제로 확인된 것이다.

### 9.3 비용 차감 quintile 성과 (보조 지표 — 단순 통과율이 아닌 실제 수익률/승률)

`overall_score`/`slow_score`/`fast_score` 상위 20% vs 하위 20% 그룹의
왕복비용(30bp 가정) 차감 후 순수익률·승률(T+20 기준):

| 신호 | 상위 20% 순수익 / 승률 | 하위 20% 순수익 / 승률 | spread |
|---|---|---|---|
| overall_score | +5.83% / 56.1% | +1.94% / 50.1% | **+3.88%p** |
| slow_score | +3.83% / 51.3% | +1.91% / 50.1% | +1.93%p |
| fast_score | +4.36% / 54.3% | +3.56% / 53.0% | +0.80%p |

`overall_score`가 quintile spread 관점에서는 가장 뚜렷한 차이를 보이고,
`fast_score`는 여기서도 가장 약하다(§SPPV-1 결론과 방향 일치). 그러나
**이 spread가 cross-sectional IC의 t-stat과는 다른 이야기를 한다** — 일별
순위상관은 유의하지 않은데, 전체 표본을 누적한 quintile 평균은 차이를
보인다. 이는 (a) 진짜 알파가 날마다 미약하게 존재하지만 누적하면 드러나는
경우이거나, (b) `overall_score`가 상승장(bullish_trend, 표본의 50%) 종목을
체계적으로 더 자주 상위 quintile에 배치해 **시장 베타를 알파로 착시**하고
있는 경우일 수 있다. 이번 턴 산출물만으로는 두 가설을 구분할 수 없다 —
§9.5 다음 단계 참고.

### 9.4 국면별 분해 (T+5 기준)

| 신호 | range_bound | bullish_trend | bearish_trend | event_driven_unstable |
|---|---|---|---|---|
| overall_score | +0.027(미약) | +0.028(미약) | **-0.069(유의미, 역방향)** | +0.015(노이즈) |
| fast_score | +0.002(노이즈) | +0.049(미약) | **-0.105(강함, 역방향)** | -0.103(강함, n=248 소표본) |
| slow_momentum | +0.064(유의미) | -0.010(노이즈) | +0.003(노이즈) | +0.080(유의미, n=248 소표본) |

**하락국면(bearish_trend, n=3,127)에서 overall_score/fast_score의 IC가
음(-)으로 뒤집힌다** — 즉 하락장에서는 "신호가 좋다"고 나온 종목이 오히려
더 나쁜 성과를 냈다는 뜻이다. 이는 지금 운영 중인 `risk_off_penalty`/
eligibility 하락장 차단이 완전히 근거 없는 게 아니라, **하락장에서는
현재의 backbone 신호 자체가 방향을 신뢰하기 어렵다**는 정황 증거로
해석된다(다만 표본이 부족한 `event_driven_unstable`, n=248은 판정 보류).

### 9.5 한계 (반드시 인지)

- **point-in-time universe 미적용**: 현재 생존 core 88종목만 사용
  — survivorship bias 존재. 지수/편입 이력이 1년 전체를 커버하지 못해
  (가장 오래된 스냅샷 2026-06-27) 이번 턴에 시도하지 않았다.
- **시장/업종 대비 초과수익 미계산**: 설계(§2.4)에 명시했으나 이번 구현은
  절대수익률 + 비용차감만 계산했다. §9.3의 quintile spread가 시장 베타
  때문인지 검증하려면 이 초과수익 계산이 **선행 필요**하다.
- **round-trip 비용 30bp는 단순 고정 가정** — 운영 `expected_value_gate`의
  동적 비용 모델(회전율/랭킹 percentile 반영)과 다르다. 방향성 판단에는
  문제없으나 정밀 비교에는 한계.
- **block bootstrap 미구현** — Newey-West만 적용. 결론(유의성 없음)이
  이미 보수적 방향이라 우선순위는 낮으나 완전한 통계 보정은 아니다.

### 9.6 판정 — 조건부 보류(Hold)

**SPPV-3(entry_score 전체 재현)로 즉시 진행하지 않는다.** 이유:
`entry_score`/BUY funnel 재현은 상당한 리소스가 드는 작업인데, 그 입력이
되는 원신호(slow/fast/overall_score) 자체가 cross-sectional 유의성을
확보하지 못했다. 이 상태에서 SPPV-3/4를 밀어붙이면 "검증되지 않은 신호
위에 또 다른 재현 작업을 쌓는" 잘못된 레버가 될 위험이 크다.

다만 완전한 "신호 없음(No-Go 확정)"으로도 단정하지 않는다 — quintile
spread(overall_score 기준 +3.88%p)와 하락장 역방향 IC라는 **방향성 있는
잔여 신호**가 남아 있고, 그 정체(시장 베타 vs 잔여 알파)를 가리지 않은
상태이기 때문이다.

### 9.7 다음 단계 (SPPV-2.5, SPPV-3 착수 전 필수 진단)

1. **초과수익 기반 재검증**: 절대수익률 대신 (개별 종목 수익률 - 당일 core
   universe 평균 수익률) 초과수익으로 quintile spread와 cross-sectional IC를
   재계산 — §9.3 spread가 시장 베타 착시인지 판별.
2. **국면 내부(within-regime) quintile 분해**: bullish_trend 내부에서도
   상위/하위 quintile 차이가 유지되는지 확인(유지되면 알파, 사라지면 베타).
3. 위 진단에서 **초과수익 기준으로도 유의미한 spread가 남으면** → SPPV-3
   착수(entry_score 재현), **사라지면** → 현재 backbone 신호 체계
   재설계(가중치 조정이 아니라 feature 자체 재검토)로 전환.

## 10. 관련 산출물

- `scripts/validate_signal_predictive_power_v2.py`
- `logs/signal_ic_sppv2_expanded_2026-07-14.json`
- `logs/sppv2_run_2026-07-14.log`

## 11. SPPV-2.5 결과 — quintile spread 정체 진단 (2026-07-14) — ⚠️ §12에서 방법론 오류 확인, 결론 폐기

> **⚠️ 2026-07-14 정정 공지 (사용자 지적으로 발견)**: 아래 §11의 "국면
> 혼입(regime-mix) 착시" 결론은 **방법론 오류에 기반해 폐기됐다.**
> ① 여기서 쓴 `regime_label`은 시장 전체가 아니라 **평가 대상 종목 자신의**
> 기술적 상태(`classify_market_regime()`가 그 종목의 slow_score/return_3m
> 등만 입력받아 판정, `market_regime.py:21-38`)로, 검정 대상 신호
> (`overall_score`)와 같은 계열의 변수로 표본을 조건화한 선택 편향이었다.
> ② "로컬 캐시로 재조회 없이 재사용"이라는 아래 서술도 **사실이 아니었다**
> — 캐시 기능을 이 실행 직전에 추가했는데 캐시가 비어 있어 실제로는
> 352건 전부 KIS에 새로 요청했다(로그로 확인: `logs/sppv2_5_run_
> 2026-07-14.log`의 HTTP 요청 수 = SPPV-2와 동일한 352건). 데이터 자체는
> SPPV-2와 거의 동일한 기간·종목으로 재요청되어 실질적으로 동등하지만,
> "캐시 재사용"이라는 표현은 정정한다.
> 두 오류 모두 §12(시장 공통 국면 기준 재검증)에서 KODEX 200(`069500`)을
> 진짜 시장 벤치마크로 써서 다시 검증했고, **결론이 뒤집혔다** — §12 참고.
> 아래 §11 본문은 오류의 경위를 남기기 위해 삭제하지 않고 이력으로 보존한다.

### 11.1 실행 개요

- SPPV-2와 **동일 표본**(core 88종목, rolling 16,720건, 국면 분포
  range_bound 4,989/bullish_trend 8,356/bearish_trend 3,127/
  event_driven_unstable 248) — ~~로컬 캐시(`logs/_bars_cache_core88_
  2026-07-14/`)로 KIS 재조회 없이 재사용해~~ **(정정: 실제로는 캐시가
  비어 있어 352건 전부 재조회함, 위 정정 공지 참고)** 완전히 같은 표본
  정의(88종목·동일 기간)로 재요청해 비교했다.
- 산출: `scripts/validate_signal_predictive_power_v2_5.py`(read-only),
  `logs/signal_ic_sppv2_5_regime_decomposition_2026-07-14.json`.
- 방법: (1) SPPV-2의 quintile spread(상위 20% - 하위 20% net return)
  시계열 자체에 Newey-West 유의성 검정 적용, (2) 국면별(bullish/bearish/
  range_bound) 표본만으로 quintile을 다시 나눠 국면 내부에서도 spread가
  유지되는지 확인.

### 11.2 핵심 결과

| 신호 | horizon | 전체(pooled) t_NW | bullish_trend | bearish_trend | range_bound |
|---|---|---|---|---|---|
| overall_score | T+5 | 1.64 | 0.99 | -1.72 | 1.76 |
| overall_score | T+20 | **2.30(유의)** | 1.55 | 0.38 | 1.63 |
| slow_score | T+20 | 1.35 | 0.19 | 1.54 | 0.98 |
| fast_score | T+20 | 0.67 | 0.26 | -1.17 | 0.36 |

(`event_driven_unstable`는 n=7일로 표본 극소 — 판정 제외, 원본 수치는
JSON 산출물 참고.)

**`overall_score` T+20의 pooled spread(+3.88%p)는 Newey-West로도 유의
(t=2.30, 관례적 임계 |t|≈2 통과)하다.** 그러나 **이 유의성은 어느
개별 국면 내부에서도 재현되지 않는다** — 가장 근접한 bullish_trend(t=1.55),
range_bound(t=1.63) 모두 유의 임계를 넘지 못하고, bearish_trend는
사실상 0(t=0.38)이다.

### 11.3 해석 — ⚠️ 폐기 (§12에서 반박됨, 아래는 당시 추론 이력)

이 패턴은 통계적으로 **"국면 혼입(regime-mix) 착시"의 전형적 신호**다:
- 상승장 표본은 대체로 수익률이 높고, 하락장 표본은 대체로 낮다.
- `overall_score`가 상승장 종목을 상위 quintile에, 하락장/횡보장 성격의
  종목을 하위 quintile에 체계적으로 더 자주 배치한다면, **국면을 pooling한
  전체 표본에서는 spread가 부풀려지지만, 각 국면 "내부"(그 국면에 이미
  속한 종목들끼리의 상대 비교)에서는 그 효과가 사라진다.**
- 실제로 pooled t=2.30 > 어떤 개별 국면의 t보다도 크다는 것 자체가, 개별
  국면들의 "국면 평균 수준 차이"가 spread의 상당 부분을 설명한다는
  방증이다.

**따라서 `overall_score`가 종목 간 상대적 우열을 가리는 "종목 선택 알파"를
가지고 있다는 근거는 이번 진단에서 확보되지 않았다.** 국면(상승/하락/횡보)
자체를 맞히는 것과 종목을 고르는 것은 다른 문제이며, 이 신호는 후자를
아직 입증하지 못했다.

다만 **완전한 무신호(제로)로 단정하지도 않는다** — bullish_trend(t=1.55),
range_bound(t=1.63) 모두 방향은 일관되게 양(+)이고 유의 임계에 근접해
있다. 표본(국면 내부 거래일 수 ~183~190일)이 국면별로 쪼개지며 검정력이
줄어든 것이 원인일 수 있어, "신호 없음"과 "표본 부족으로 검출 못함"을
이번 데이터만으로는 완전히 구분할 수 없다.

### 11.4 판정 — ⚠️ 폐기(§12 참고), 당시 판정 이력

당시(오류 발견 전) 판정: 조건부 보류(Hold) 유지

**SPPV-3(entry_score 전체 재현)을 계속 보류한다.** 근거: 원신호의
종목-선택 알파가 국면 내부에서 통계적으로 확인되지 않았다. `entry_score`
재현은 상당한 리소스가 드는 작업인데, 그 입력 신호의 알파가 아직
입증되지 않은 상태에서 진행하는 것은 "검증되지 않은 신호 위에 재현 작업을
쌓는" 반복된 잘못된 레버가 될 수 있다.

동시에 신호 체계를 완전히 폐기(No-Go 확정)하지도 않는다 — 방향 일관성과
유의 임계 근접성이 "표본 확장 시 검출 가능한 약한 신호"의 가능성을
남긴다.

### 11.5 다음 단계 (택 1, 사용자/운영 판단 필요)

1. **표본 확장 후 재검증**: 기간을 1년→2~3년으로 늘리거나(국면 내부
   거래일 수 자체를 늘림), 종목을 core 88 → 확장 유니버스로 늘려(하루
   cross-section 크기를 키워 quintile 추정 정밀도 향상) 같은 국면 내부
   분해를 재실행한다. 이건 SPPV-3 착수 여부를 가리는 **마지막 진단
   라운드**로 제안한다.
2. **신호 체계 재검토로 전환**: 표본 확장에도 국면 내부 유의성이 확인되지
   않으면, 지금의 `slow_momentum`/`slow_trend`/`fast_score` 조합 자체가
   종목 간 상대 수익률을 가려내는 데 구조적 한계가 있다고 보고 — 가중치
   재조정이 아니라 **feature 구성 자체의 재설계**(예: 상대강도/업종
   중립화/펀더멘털 feature 추가)로 트랙을 전환한다.

이 판단은 추가 리소스 투입 여부를 정하는 것이라 사용자 확인을 권장한다.

## 12. 관련 산출물 (갱신)

- `scripts/validate_signal_predictive_power_v2.py`
- `scripts/validate_signal_predictive_power_v2_5.py`
- `logs/signal_ic_sppv2_expanded_2026-07-14.json`
- `logs/signal_ic_sppv2_5_regime_decomposition_2026-07-14.json`
- `logs/sppv2_run_2026-07-14.log`, `logs/sppv2_5_run_2026-07-14.log`
- `logs/_bars_cache_core88_2026-07-14/`(88종목 원본 일봉 캐시, 재사용 가능)
