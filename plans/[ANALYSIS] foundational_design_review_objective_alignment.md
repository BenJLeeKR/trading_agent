# 근본 설계 검토 — 목표·소싱·신호·백테스트 정합성 분석

작성일: 2026-07-14
성격: 결정 기록(decision record) — 여러 문서(universe policy / entry_score /
core_risk_off / signal_backbone)에 걸친 교차 진단. 이 문서는 향후 작업이
"잘못된 레버"를 다시 당기지 않도록 근본 사실을 고정하기 위한 기준점이다.

## 수정 이력

- 작성자: Codex
- 수정일자: 2026-07-14
- 수정내용: 최고 기대수익률을 손실 제약 아래의 목적함수로 재정의하고,
  `2026-06-25` 이후 BUY 주문 0건의 DB funnel 실측과 `entry_score` 직접 병목,
  신호 검증부터 제한적 probe까지의 후속 순서를 반영했다.

- 작성자: Claude
- 수정일자: 2026-07-14
- 수정내용: SPPV-2(신호 예측력 확장 검증) 완료 결과를 반영해 2순위를
  완료로 갱신하고, quintile spread 정체(시장 베타 vs 알파) 진단을
  2.5순위로 신설, 3순위(entry_score 재현)를 조건부 보류로 재분류했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (2차)
- 수정내용: SPPV-2.5(quintile spread 정체 진단) 완료 결과를 반영 — pooled
  유의성이 국면 혼입 착시일 가능성이 높다는 결론을 2.5순위에 기록하고,
  3순위(entry_score 재현) 착수 조건을 "표본 확장 후 국면 내부 유의성
  재확인"으로 구체화했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (3차, 사용자 지적 반영)
- 수정내용: **SPPV-2.5의 "국면 혼입 착시" 결론을 방법론 오류로 폐기**했다.
  `regime_label`이 시장이 아니라 종목 자신의 신호로 판정되는 라벨이었음을
  코드로 재확인했고, KODEX 200 벤치마크 기준 재검증(SPPV-2.6)에서 그
  결론이 반박됨을 확인했다. 2.5순위를 2.6순위로 확장·교체하고, 3순위 보류
  사유를 "국면 혼입 의심"에서 "하락장 표본 부재"로 교체했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (4차)
- 수정내용: **SPPV-2.6의 "알파 근거 강화" 결론을 다시 하향 조정**했다.
  벤치마크(069500)를 평가 universe에서 제외하고 조회 기간을 3년으로
  확장(SPPV-2.7)해 실제 하락장 표본(96거래일)을 확보한 결과, pooled
  유의성이 소멸하고 하락장에서는 신호 방향이 역전/역방향으로 나타났다.
  2.6순위를 2.7순위로 확장·교체하고, 3순위 보류 사유를 "신호 feature
  재설계 검토 필요"로 재교체했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (5차, 검증 기간 재설계)
- 수정내용: 이 시스템이 3개월 이하 중단기 공격형이라는 전제로 **SPPV
  검증 기간 기준을 재설계**했다(SPPV-2.8). 3년 pooled를 기본값으로 두지
  않고, 최근 12개월을 1차(primary) 기본 창, 3년(SPPV-2.7 재사용)을 국면
  커버리지 2차(supplementary) 게이트로 분리했다. 기존 3년 캐시로 최근
  12개월을 실측한 결과 하락장 거래일이 0일이라 1차 창만으로는 필수 국면
  게이트를 통과할 수 없음이 확인됐고, 1차 pooled 유의성도 없었다(§14의
  보류 판정은 유지). 2.7순위 뒤에 2.8순위를 신설했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (6차, 실행 증빙 재검증)
- 수정내용: SPPV-2.8의 실행 증빙을 재검증한 결과, 최초 저장했던 실행
  로그가 실제로는 호스트 python 환경의 `dotenv` 미설치로 즉시 실패한
  트레이스였고, JSON 산출물은 (호스트가 아닌) 컨테이너에서 만든 진짜
  결과였으나 그 실행의 정상 로그가 남지 않았던 증빙 결함을 발견했다.
  컨테이너에서 재실행해 stdout을 로그로 캡처한 결과, 종료 코드 0/`HTTP
  Request:` 0건/최근 12개월 bearish_trend 0일/`overall_score` T+20
  t_NW=1.18 전부 동일하게 재현됨을 확인했다 — 결론과 판정은 변경 없이
  증빙만 보강했다. 상세는
  `plans/[DESIGN] signal_predictive_power_validation.md` §16.6.

- 작성자: Claude
- 수정일자: 2026-07-14 (7차, 신호 feature 재설계 검토 — SPPV-2.9)
- 수정내용: §14.5가 지시한 **신호 feature 재설계 검토를 실제로 수행**했다.
  `fast_score`/`slow_score`의 6개 sub-component를 분해 실측하고 신규 후보
  feature(`risk_adj_momentum_3m`, `reversal_1m`)를 §16 이원 기준으로
  검증했다. **`rsi_signal`이 T+20에서 유의하게 역방향(t_NW=-2.94)임을
  특정 — `fast_score` 실패 원인 중 하나로 확인.** `risk_adj_momentum_3m`
  (변동성 조정 모멘텀)은 3년 pooled 유의(t_NW=2.07) + 하락장 역전 없음
  으로 유일한 Watch 후보이나 1차 창 유의성 미달로 완전한 Go는 아니다.
  SPPV-3 착수는 계속 보류하되 구체적 다음 과제(`rsi_signal` 제거/반전한
  `fast_score_v2` 검증, `risk_adj_momentum_3m` 재검증)를 확정했다. 상세는
  `plans/[DESIGN] signal_predictive_power_validation.md` §17.

- 작성자: Claude
- 수정일자: 2026-07-14 (8차, §17.5 후속 3과제 — SPPV-2.10)
- 수정내용: §17.5가 지시한 후속 3과제를 실제로 수행했다. **`fast_score_v2`
  (rsi_signal 제거/부호반전) 두 변형 모두 No-Go** — 하락장 T+5 spread가
  원안(t_NW=-2.79)과 거의 동일하게 역전(drop -2.41, flip -2.32)돼
  `rsi_signal`이 부분 원인일 뿐 주된 원인이 아니었음을 재확인, §17의
  낙관적 프레이밍을 하향 조정한다. `risk_adj_momentum_3m`은 1차 창을
  18개월로 넓히자 T+20 t_NW=2.03으로 §16 게이트를 겨우 통과했으나 T+5는
  여전히 미달인 marginal 결과라 "Watch 유지, 조건부 상향"에 그친다.
  `reversal_1m`은 하락장 표본 반분 검증에서 방향은 일관되나(전반 1.87/
  후반 1.33) 개별 유의 문턱 미달로 Hold 유지. SPPV-3 착수는 계속 보류.
  상세는 `plans/[DESIGN] signal_predictive_power_validation.md` §18.

---

## 0. 이 문서가 나온 배경

- 최근 수 주간 "주문 0건" 문제를 두고 소싱(universe sourcing) 개선(UNIV-1~5),
  freeze 타이밍, F5 필터 등 여러 표면 작업을 진행했으나, 2026-07-14 실측에서
  **오늘 편입된 19개 종목 전체의 `entry_score`가 매수 threshold(0.65)에 단
  하나도 근접하지 못함**(1위 001450=0.5749)을 확인했다.
- 이로써 "소싱을 아무리 넓혀도 주문은 계속 0건일 것"이라는 지적이 제기됐고,
  근본 설계 3개 질문에 대한 문서 기반 재검토를 수행했다.

### 0.1 BUY 0건 운영 실측 기준선

2026-07-14 운영 DB를 `2026-06-25` 이후 `symbol + trade_date` 첫 decision으로
중복 제거해 재검증했다.

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

마지막 BUY 주문은 `2026-06-24`다. 정확히는 약 20일, 거래일 기준 약 14일의
BUY 0건 상태이며, 기간 표현과 별개로 매 거래일 최고 점수조차 threshold를
넘지 못한 것은 공격 목표와 진입 산식의 구조적 충돌을 뜻한다. eligibility
통과 21건도 후보가 되지 못했으므로 이 기간의 직접 병목은 하류 expected
value/compliance/broker가 아니라 `entry_score < 0.65`다.

---

## 1. 세 가지 근본 질문과 검토 결론

### Q1. "최고 기대수익률을 낼 종목을 찾는 작업"이 제대로 설계됐나?
**결론: 아니오 — 애초에 그렇게 설계된 적이 없다.**

- core universe 선정 기준은 ① `metadata.core_universe` 플래그 ② KOSPI100/200
  지수 편입 ③ 하드코딩 allowlist 90종목뿐(`universe_selection.py`
  `_is_core_seed_instrument`, `core_universe_seed.py`).
  `[POLICY] trading_universe_policy_v1.md` §4.1이 든 근거는 "유동성 충분 /
  슬리피지·노이즈 감소"로 **순수 방어적**이다.
- `[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md`가 스스로
  **"core 레이어는 100% 가격/모멘텀 무관, 수익률·추세 신호가 어디에도 없다"**
  고 인정한다.
- "최고 기대수익률(highest expected return)" 목표는 universe/selection
  정책 문서 어디에도 **없다**. KPI는 포함률·소요시간·전환율 등 운영 지표다.
  ("최고 기대수익률" 문구는 `[DESIGN] expected_return_holding_horizon_and_
  churn_control_refactor.md`에만 등장하며, 그마저 churn 제어·보유기간
  정렬 목적이다.)
- 기대수익률(`expected_value_gate`)은 존재하나 **이미 선정된 종목을 걸러내는
  사후 게이트**일 뿐, 소싱 단계에 피드백하지 않는다. alpha 탐색 장치는
  Layer 4 market-driven overlay 하나뿐이며 현재 하루 0~1종목 수준이다.

### Q2. 종목을 찾는 방식 전반의 설계가 합당한가?
**결론: 목표에 따라 정반대다.**

- 목표가 **"자본 보전 + paper 안전 검증"**이면 → 합당하다. 방어적으로 잘
  작동한다.
- 목표가 **"최고 기대수익률"**이면 → 부적합하다. 결정적 이유는 신호 체계:
  - `slow_score`(=0.6·slow_momentum+0.4·slow_trend), `fast_score`,
    `entry_score`는 전부 **과거 가격의 추세·모멘텀 상태를 기술하는 룰 기반
    지표**이지, 미래 수익률을 예측하도록 만든 지표가 아니다
    (`signal_backbone.py` `_score_return_3m`/`_score_price_vs_ma` 등 계단식
    상수 매핑).
  - 가중치(0.6/0.4, 0.55/0.45, entry_score 0.45/0.20/0.15, ranking
    0.55/0.10/0.20…)는 전부 **백테스트 근거 없는 하드코딩 매직 넘버**다.
  - `regime_label`(bearish_trend)·`risk_tone`(risk_off)도 **시장 지수가
    아니라 개별 종목의 과거 가격 feature + 하드코딩 임계값**으로 판정된다
    (`market_regime.py` `classify_market_regime`).

### Q3. entry_score / risk_off가 백테스트로 충분히 검증됐다고 결론지어도 되나?
**결론: 아니오 — 검증된 명제는 "이번 하락 국면에서 매수 억제가 옳았다"뿐이다.**

- **표본이 단일 하락 국면에 집중**: 최장 6주(2026-06-01~07-10), 핵심 분석은
  약 2주(2026-06-27~07-10), 일부는 3~4거래일. active 표본 20건 평균
  `return_3m_pct=-30.49%`, `slow_trend=-0.8`이 20/20. **상승장·횡보장
  표본 전무.**
- **실집행 백테스트가 아니다**: 문서 스스로 "체결 기반 정식 백테스터가
  아니라 후행 수익률 proxy 기반 shadow 실측"이라 명시
  (`[ANALYSIS] signal_backbone_slow_score_threshold_tuning_2026-07-09.md`).
  전 구간 `would_buy=0`, `submitted=0`.
- **핵심 결론의 표본이 빈약**: deep_negative vs inactive가 N=49 vs 155
  (재집계 N=35 vs 64), signal_backbone N=40 vs 165. 완화 후보군은
  N=3~4까지 축소되며 leave-one-out에서 T+3 수익률이 +0.85%↔-3.78%로
  부호가 뒤집힘("안정적 우위 아님"이라고 문서가 인정).
- **문서 스스로 검증 대상을 "하락장 방어"로 규정**했다. 어떤 항목도
  authoritative로 승격하지 않았고 "shadow-only 유지"를 반복 명시했다.

> ⚠️ **중요 경계**: 이전 세션에서 "매수 0건은 옳은 방어 → 완화 영구 중단"으로
> 확정한 것은 **여전히 유효하되, 그 유효 범위는 "이 하락 국면 한정"이다.**
> "모든 시장 국면에서 이 gate가 항구적으로 옳다"로 확대 해석하면 안 된다.
> 상승장/횡보장에서의 타당성은 **검증된 바 없다.**

---

## 2. 근본 원인 진단

지금까지의 "주문 0건" 문제의 표면 증상(소싱 부족, freeze 타이밍, F5 필터)
아래에 있는 **두 개의 진짜 뿌리**:

1. **목표-설계 불일치**: 시스템은 "자본 보전"용으로 설계됐는데 기대는
   "최고 기대수익률"에 있다. 방어 시스템에 공격을 기대한 구조다.
2. **검증되지 않은 신호 체계**: 종목의 좋고 나쁨을 판정하는 점수 자체가
   예측력(미래 수익률과의 상관)을 실증 검증받은 적이 없다. 이 토대가
   검증되기 전에는 gate 완화도 소싱 확장도 모래 위의 집이다.
3. **공격·방어 책임 중복**: 약한 signal이 이미 `entry_score`에 반영된 뒤
   `risk_off_penalty=-0.15`가 다시 차감되고, BUY eligibility가 동일한
   `bearish_trend + risk_off`를 다시 차단한다. 실측 297건 중 294건에 penalty가
   적용돼 리스크 제약이 사실상 상시 진입 금지로 동작했다.

→ 지난 세션의 "소싱 개선(UNIV-1~5)"은 **잘못된 레버**였다. 지금 국면에서
   소싱을 넓혀도 신규 종목 역시 같은 (미검증) entry_score를 거쳐 동일하게
   억눌리므로 주문 발생에 영향이 없다.

---

## 3. 목표 트레이드오프 정리표 (1순위 의사결정용)

시스템의 실제 목표를 확정하지 않으면 후속 작업의 성공 기준 자체가 없다.
두 목표는 정반대의 결론을 낸다.

| 관점 | 목표 A: 자본 보전(Capital Preservation) | 목표 B: 최고 기대수익률(Max Expected Return) |
|---|---|---|
| 현재 시스템 상태 | **이미 완성·정상 작동 중** | **핵심 엔진(검증된 예측 신호) 부재** |
| "주문 0건"의 의미 | 성공(하락장 손실 회피) | 실패(기회 미포착 + 검증 불가) |
| 필요한 다음 작업 | 없음 — 방어 모드 유지·모니터링만 | 신호 예측력 검증부터 재출발 |
| 신호 체계 요구수준 | 현 수준으로 충분(보수적 필터면 됨) | predictive power 실증 필수 |
| 리스크 성격 | 기회비용(안 사서 못 번 수익) | 실현손실 가능(사서 잃을 수 있음) |
| core universe 적합성 | 적합(방어적 대형주) | 부적합(alpha 소스 아님) |
| 완화 금지 원칙 | 그대로 유지 타당 | "국면 한정"이므로 재평가 대상 |

**결정 주체**: 이 선택은 기술 판단이 아니라 운영자(사용자)의 전략적 결정이다.

---

## 3.1 목표 확정 (2026-07-14, 사용자 결정)

> **✅ 목표 B(최고 기대수익률)로 확정.**
>
> 사용자 명시: *"이 시스템의 근본 목적은 최고 기대수익률이다. 기대수익률을
> 높이기 위해서는 아예 손실을 안 보는 것이 아니라, 일정 부분의 손실을
> 감내(손실은 최소화)하면서 투자하는 것이 목적이다."*
>
> 해석 — 목표는 **손실 제약 아래의 net expected return 극대화**다:
> - "주문 0건 = 손실 0"은 **성공이 아니라 실패**다(기회비용 = 미실현 수익).
> - 단, 무분별한 매수가 아니라 **손실을 최소화하면서** 감내 가능한 수준의
>   리스크를 지고 기대수익을 추구한다.
> - 수익률은 1순위 목적함수이고 VaR/drawdown/exposure/liquidity/compliance는
>   감내 불가능한 손실과 위반을 막는 제약조건이다.
> - 따라서 §3 표의 목표 B 열이 이 시스템의 기준이며, "신호 예측력 실증
>   검증"(2순위)이 즉시 착수 대상이 된다.
> - core_risk_off/entry_score 완화 금지 원칙은 "이번 하락 국면 한정"으로
>   그 유효 범위가 축소되며, 다른 국면에서의 타당성은 2순위 검증 결과에
>   따라 **재평가 대상**이 된다(무조건 완화가 아니라, 실증 기반 재설계).

## 4. 권장 진행 순서 (우선순위)

- **0순위(완료, 이 문서)**: 근본 진단 문서화 — 잘못된 레버 재발 방지 기준점.
- **1순위(완료, 2026-07-14)**: 목표 B(최고 기대수익률) 확정 — §3.1 참고.
- **2순위(완료, 2026-07-14 — SPPV-2)**: **신호 예측력 실증 검증** — core
  88종목 × cross-sectional 거래일별 IC × Newey-West 보정 × 국면별 분해
  완료. **결과: 8종목 파일럿(SPPV-1)의 "유의미"~"강함"(t=2.4~4.1)은
  overlap 편향의 산물이었음이 확인됐다** — 정확히 보정하면 전 신호·전
  horizon에서 |t_NW|<1.1로 통계적 유의성 없음. 단, 비용 차감 quintile
  spread(overall_score 기준 +3.88%p)는 방향성 있게 남아 있어 "완전
  무신호"로도 단정하지 않는다. 상세: `plans/[DESIGN] signal_predictive_
  power_validation.md` §9.
- **2.5순위(완료, 2026-07-14 — SPPV-2.5) — ⚠️ 방법론 오류로 결론 폐기**:
  quintile spread 정체 진단 시도. ~~결과: pooled 유의성이 국면 혼입 착시~~
  **오류 확인(사용자 지적): `regime_label`이 시장이 아니라 종목 자신의
  신호로 판정되는 라벨이었다(`market_regime.py:21-38`) — 검정 대상과 같은
  계열 변수로 조건화한 선택 편향.**
- **2.6순위(완료, 2026-07-14 — SPPV-2.6, 방법론 교정) — ⚠️ §2.7에서 표현
  하향 조정**: KODEX 200(069500, 이미 core universe 구성원)을 시장
  벤치마크로 써서 **거래일 단위 공통 국면**과 **초과수익**으로 재검증.
  ~~결과: "국면 혼입 착시" 결론은 반박되고, 최소 상승장 국면에서는 종목
  선택 알파일 가능성이 오히려 높아졌다.~~ **당시엔 벤치마크(069500)를
  평가 universe에도 포함시킨 자기참조 문제와 1년(하락장 0일) 표본
  한계가 있었다 — 아래 2.7순위에서 교정 후 결론이 다시 반박됨.**
- **2.7순위(완료, 2026-07-14 — SPPV-2.7, 자기참조 제거 + 3년 확장)**:
  평가 universe에서 벤치마크를 제외(core 87종목)하고 조회 기간을 3년
  (733일봉)으로 확장 — 시장 공통 국면 96거래일(15%)의 실제 하락장 표본을
  처음으로 확보했다. **결과: `overall_score` pooled spread 유의성이
  §12의 t_NW=2.30에서 **t_NW=1.32로 소멸**했고, 하락장 내부에서는 spread가
  **음수로 역전**(T+5 t_NW=-1.71)하거나 `fast_score`는 하락장에서 **유의
  하게 역방향**(T+5 t_NW=-2.79)이었다.** §2.6의 "알파 근거 강화" 결론은
  과도했음이 확인돼 하향 조정한다 — 안정적인 종목 선택 알파를 찾지
  못했다. 상세: `plans/[DESIGN] signal_predictive_power_validation.md`
  §14(최신 canonical 결론).
- **2.8순위(완료, 2026-07-14 — SPPV-2.8, 검증 기간 기준 재설계)**: 이
  시스템의 "3개월 이하 중단기 공격형" 성격에 맞춰 SPPV 검증의 기간(period)
  기준을 재설계했다 — 3년 pooled를 기본값으로 두지 않고 **최근 12개월을
  1차(primary) 기본 창, 3년(SPPV-2.7 재사용)을 국면 커버리지 확인용
  2차(supplementary) 게이트**로 분리했다. 기존 3년 캐시를 재사용해(신규
  KIS 호출 0건) 최근 12개월 창을 실측한 결과 **하락장(bearish_trend)
  거래일이 0일**로 나타나, "최근성 창"만으로는 필수 국면 게이트를 원천적
  으로 통과할 수 없음을 실증했고, 1차 pooled 유의성도 확보되지 않았다
  (`overall_score` T+20 t_NW=1.18). §14(SPPV-2.7)의 보류 판정은 유지되며,
  이번 작업은 앞으로의 재검증이 따를 **기간 기준을 확정**한 것이다.
  **(2026-07-14 6차 재검증)** 최초 저장 로그가 실패 트레이스였던 증빙
  결함을 발견해 컨테이너에서 재실행 — 종료 코드 0/KIS 호출 0건/
  bearish_trend 0일/t_NW=1.18 전부 재현 확인. 상세:
  `plans/[DESIGN] signal_predictive_power_validation.md` §16, §16.6.
- **2.9순위(완료, 2026-07-14 — SPPV-2.9, 신호 feature 재설계 검토)**:
  §14.5가 지시한 신호 feature 재설계 검토를 실행했다. `fast_score`/
  `slow_score`의 6개 sub-component를 분해 실측하고 신규 후보 feature
  (`risk_adj_momentum_3m`=변동성 조정 모멘텀, `reversal_1m`=단기 역추세)
  를 §16 이원 기준으로 검증했다. **결과: `rsi_signal`이 T+20에서 유의하게
  역방향(t_NW=-2.94)임을 특정** — `fast_score`가 반복적으로 실패/역전
  했던 원인 중 하나로 확인됨. `risk_adj_momentum_3m`은 3년 pooled
  유의(t_NW=2.07) + 하락장 역전 없음(t_NW=0.39)으로 유일한 Watch 후보
  이나 1차(최근 12개월) 유의성(t_NW=1.47)이 §16 게이트(|t|≥2) 미달 —
  **완전한 Go는 아니다**. `reversal_1m`은 하락장에서만 유의(t_NW=2.13)
  해 국면 조건부 후보로 분리 검토가 필요하다. SPPV-3 착수는 계속
  보류하되, 다음 과제를 구체화했다(`rsi_signal` 제거/반전한
  `fast_score_v2` 검증, `risk_adj_momentum_3m` 재검증). 상세:
  `plans/[DESIGN] signal_predictive_power_validation.md` §17.
- **2.10순위(완료, 2026-07-14 — SPPV-2.10, §17.5 후속 3과제)**: `fast_
  score_v2`(rsi_signal 제거/부호반전) shadow 2종, `risk_adj_momentum_3m`
  1차 창 18개월 확장, `reversal_1m` 하락장 반분 안정성을 실측했다.
  **결과: `fast_score_v2` 2종 모두 No-Go** — 하락장 T+5 spread가
  원안(t_NW=-2.79)과 거의 동일하게 역전(drop -2.41, flip -2.32) —
  `rsi_signal`이 부분 원인일 뿐 주된 원인이 아니었음을 재확인, §2.9의
  낙관적 프레이밍을 하향 조정. `risk_adj_momentum_3m`은 18개월 창에서
  T+20 t_NW=2.03으로 §16 게이트를 겨우 통과했으나 T+5는 미달인
  marginal 결과 — "Watch 유지, 조건부 상향". `reversal_1m`은 하락장
  반분 검증에서 방향 일관되나(전반 1.87/후반 1.33) 개별 유의 미달 —
  Hold 유지. SPPV-3 착수는 계속 보류. 상세:
  `plans/[DESIGN] signal_predictive_power_validation.md` §18.
- **3순위(보류 유지, 사유 재교체)**: **`entry_score`와 BUY funnel
  재현** — §2.7 확장 검증에서 하락장 안정성이 확인되지 않아 착수하지
  않는다. 대신 신호 feature 재설계 검토(§14.5, §17/§18 완료)로 무게
  중심이 이동한다. 착수 전제(feature 재검토 또는 추가 확장으로 안정적 알파 확인)가
  충족되면 regime/allocation/strategy를 복원하고 signal, `risk_off_
  penalty`, eligibility block의 중복 억제를 ablation한다. Virtual BUY별
  T+1/T+3/T+5/T+10/T+20, MFE/MAE, 비용 차감 수익률과
  `candidate → selected → would_buy → submitted`를 비교한다.
- **4순위**: out-of-sample 기대수익 양수와 손실 제약을 만족한 formula만
  shadow로 유지한 뒤 일일 top-k·최소 수량·계좌 위험한도 아래 제한적 paper
  probe 승격을 별도 승인한다. compliance/VaR/guardrail 경계는 유지한다.
- **차후 보류**: UNIV-5 및 소싱 확장(현 국면 효과 0 확인), freeze 타이밍/
  F5 수정(표면 증상). 어제 배포한 shadow 관측(F5 fallback/momentum)은
  데이터만 축적하도록 방치.

---

## 5. 관련 문서

- `plans/[POLICY] trading_universe_policy_v1.md` — 종목 정책(방어적 설계 확인)
- `plans/[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md` —
  소싱 개선 트랙(현 국면 효과 0으로 확인된 트랙)
- `plans/[ANALYSIS] core_risk_off_floor_v5_report_measurement_2026-07-11.md` —
  백테스트(하락국면 한정)
- `plans/[ANALYSIS] signal_backbone_slow_score_threshold_tuning_2026-07-09.md` —
  slow_score 튜닝(proxy shadow, 실집행 아님)
- `plans/[DESIGN] signal_predictive_power_validation.md` — 신호 IC,
  `entry_score`, 전체 BUY funnel과 제한적 probe까지의 단계별 검증 설계
- `plans/[PRIORITY_MAP] remaining_work_priority_map.md`
