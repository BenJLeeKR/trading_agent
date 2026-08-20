# SPPV-3 이후 단계 — 전역 최적성 근사 정책평가(Policy Evaluation/Optimization) 체계 설계 (2026-08-20 KST, read-only 설계)

## 0. 이 문서의 성격

이 문서는 **구현 문서가 아니라 설계 문서**다. 코드 변경은 없으며, 이번 턴은
read-only 조사(코드/DB/기존 문서) + 설계 문서화 + `[PRIORITY_MAP]`/
`[BACKLOG]` 반영까지만 수행한다.

**경로 선택 근거**: `docs/10_signal_research_sppv/`는 "신호 자체의 예측력을
검증하는 연구"(SPPV 계열) 전용 경로이고, 이 문서는 그 연구 결과를
전제로 삼아 **운영 정책 구조 전체(gate+threshold+downstream+execution
제약)를 평가/비교하는 다음 단계 아키텍처**를 설계한다 — 신호 연구 자체가
아니라 그 연구를 소비하는 후속 실행 계획이라는 점에서
`docs/40_action_plans/`(예: `submit_budget_two_stage_design_2026-08-11.md`가
같은 성격으로 이미 이 경로에 있다)가 더 적절하다고 판단했다.

---

## 1. 배경 (factual)

- `SPPV-3`(신호 예측력 실증 검증, `[DESIGN] signal_predictive_power_
  validation.md`)는 4개 검증 축(①alpha 자체 예측력, ②정리된 gate 통과
  후 성과, ③downstream 분리 순수 deterministic 성과, ④funnel 전환
  기여도)으로 재정의됐고(§29~30), 축 1/3 분석이 2026-08-04~08-06에
  일부 착수됐다(§31~35). **문서상 마지막 실질 갱신은 2026-08-06이며,
  4개 축 중 축 1(1차 창)·축 3만 부분 진행됐고 종합 Go/Hold 판정은
  아직 내려지지 않았다** — 즉 **SPPV-3는 착수됐으나 완료되지 않은
  상태**다(이후 이 세션의 여러 read-only 턴에서 "SPPV-3가 여전히
  다음 주력 작업"이라는 문구가 반복적으로 등장 — 다른 트랙 작업이
  이어지는 동안 SPPV-3 자체는 계속 대기 상태로 남아 있었다).
- 이 시스템의 목표는 "손실 0"이 아니라 **"감내 가능한 손실 제약 아래
  최고의 기대수익률"**이다(`agent_workspace_guide.md`, 2026-07-14
  사용자 확정) — 이 문서의 objective function 설계는 이 원칙을
  그대로 따른다.
- `expected_value_gate.py`의 `expected_return_bps`/`net_expected_value_
  bps` 등은 **`score_anchor`(entry_score/exit_score 등 기존 deterministic
  점수)를 그대로 100배/40배 스케일링한 휴리스틱 공식**이지, 과거 실현
  수익률에 실증적으로 적합(fit)된 값이 아니다(코드 확인: `expected_
  return_bps = score_anchor * 100.0`). **이는 SPPV-3 축 1이 검증
  대상으로 삼고 있는 바로 그 "점수가 실제로 예측력이 있는가"라는
  질문 자체가 아직 열려 있다는 뜻**이며, 이번 설계 문서가 다루는
  정책평가 체계는 이 사실을 전제로 삼아야 한다(§6에서 재론).
- DB 스키마에는 이미 `trading.replay_bundles`(decision_context_id별
  replay용 번들 URI/체크섬) 테이블이 존재하지만 **실측상 0행**이다 —
  재현성 인프라가 설계는 됐으나 실제로 채워진 적이 없다.
- `trading.config_versions`(정책 버전/체크섬 저장용 테이블)도 존재하나
  **3행뿐**이고 마지막 갱신이 2026-08-14다 — 이 세션에서 실제로 있었던
  다수의 gate/threshold 변경(B축 안A, R1~R5 리팩터링, submit budget
  D안, held_position FDC 제한 등)은 전부 **git commit으로만
  기록되고 `config_versions`에는 반영되지 않았다** — "정책 버전"의
  authoritative한 출처가 현재는 DB가 아니라 **git commit SHA**라는
  뜻이다.

---

## 2. Q1. 정책(policy)의 최소 단위는 무엇인가

| 후보 | factual 설명 | 판단 |
|---|---|---|
| `entry_score` 수식만 | `deterministic_trigger_engine.py`의 점수 계산 함수 하나 | **너무 좁음** — 점수만 바꿔도 하류 gate/threshold가 그 점수를 어떻게 소비하는지에 따라 결과가 완전히 달라진다(이 세션에서 반복 확인된 패턴: `ranking_score`/`relative_activity` 등 점수 자체보다 그 점수를 소비하는 gate 임계값이 실제 차단의 authoritative 원인이었던 사례 다수). |
| BUY lane 전체(`entry_score+threshold+ranking+downstream+EV/eligibility`) | 이 세션에서 실제로 조사 단위가 된 범위(`buy_path_variable_gate_matrix.md`) | **1차 최소 단위로 적절** — 지금까지의 모든 실측(B축/C축/R1~R5)이 이 경계 안에서 이뤄졌고, 이 경계 밖(제출 이후 체결/포지션 관리)은 별도 정책 축으로 분리해도 손실이 크지 않다. |
| 주문 제출 전후 제약 포함 end-to-end 결정 정책 | submit_lane_gate/execution_service까지 포함 | **2차 확장 단위** — "제약 하 기대수익 최대화"를 온전히 평가하려면 결국 submit budget(하루 몇 건까지 살 수 있는가), 유동성/체결 슬리피지까지 들어가야 objective function이 완전해진다(§3 참고). 다만 1차 착수에는 과도한 범위. |
| holding/churn-control까지 포함한 전체 trading policy | held_position 유지/축소/재진입 쿨다운까지 | **최종 목표 단위이나 지금 당장은 아님** — held_position 쪽은 이번 세션에서 별도 트랙(FDC decision_type 제한, source_policy_guard)으로 이미 부분 정리 중이라, 정책평가 체계가 성숙하기 전에 이 범위까지 한 번에 끌어들이면 평가 대상이 너무 넓어져 "무엇이 무엇을 바꿨는지" 귀속이 어려워진다. |

**판정(해석)**: **정책 최적화 단위는 "BUY lane 전체"(entry_score → gate/
threshold → downstream override → EV gate → sizing 직전까지)로 1차
고정**하고, submit budget/execution 제약은 **objective function의
"제약 조건"**으로 포함하되 "최적화 대상 자체"로는 1차에서 제외한다.
held_position(매도/축소) 정책은 별도 트랙으로 유지한다 — SELL/REDUCE는
"위험 축소"가 목적이라 "기대수익 최대화" objective와 다른 최적화
기준(손실 제한/리스크 감내)이 필요하고, 두 정책을 하나의 objective로
섞으면 지금까지 이 세션이 지켜온 "SELL/REDUCE와 BUY를 뭉뚱그리지
않는다"는 원칙에 위배된다.

---

## 3. Q2. Objective Function 초안

### 3.1 기본 형태(제안)

```
maximize  E[ net_return | policy π, constraints C ]
subject to:
  - max_drawdown(π) <= 감내 가능 손실 상한(정책적으로 정의, 하드 아님 — VaR/risk_limit_snapshots와는 별개의 "선호" 제약)
  - VaR/risk_limit_snapshots 하드 한도 (불변, 협상 대상 아님)
  - compliance/규정 하드 한도 (불변)
  - turnover/churn <= 운영상 허용 회전율
  - submit_budget(하루 general BUY 건수) <= 운영 정책 상한
  - liquidity/participation <= 유동성 제약(호가 스프레드, 평균거래대금 대비 주문 비중)
```

### 3.2 각 축 분리(해석 — 이 저장소 맥락에 맞춘 제안)

| 축 | 채택안 | 근거 |
|---|---|---|
| gross vs net return | **net return(수수료+세금+슬리피지 반영) 채택** | `realized_pnl_events.realized_pnl_net`가 이미 fee/tax 반영해 저장 중 — gross만 보면 "손실 최소화 하 기대수익 최대화"라는 목표와 어긋난다(비용을 무시한 착시 가능). |
| 평균 vs median vs hit-rate | **평균(mean) 기대수익률을 1차 지표로, hit-rate/median은 보조 진단 지표로** | 이 시스템 목표가 "손실 0"이 아니라 "기대수익 최대화"이므로 hit-rate 단독 최적화는 명시적으로 금지된 방향(사용자 지침)이다. 다만 평균만 보면 극단치(한두 건의 대박)에 좌우될 수 있어 median/분포 형태를 **진단용**으로 병기해야 한다. |
| drawdown 제약 | **하드 제약이 아니라 "감내 가능 손실 상한"이라는 소프트 제약으로 objective에 포함** | `risk_limit_snapshots`/VaR류 하드 한도는 이미 별도로 존재하며 이 objective가 대체하지 않는다 — 이 objective의 drawdown 제약은 "정책 비교 시 어느 정책이 같은 기대수익 대비 더 큰 낙폭을 만드는가"를 비교하는 **2차 지표**로 쓴다. |
| turnover/churn penalty | **포함, 명시적 페널티 항으로** | `submit_lane_gate.py`/`held_position_sell_cycle`류 로직이 이미 "동일 cycle 중복 방지"를 다루고 있어 churn 개념이 시스템에 이미 존재 — 정책평가에서도 "더 자주 사고팔아서 기대수익이 늘어난 것처럼 보이는" 착시를 걸러야 한다. |
| liquidity/participation 제약 | **제약 조건으로 포함(최적화 대상 아님)** | 현재 실측 구조상 실제 체결 슬리피지/유동성 데이터가 제한적(§4에서 상술) — 지금은 "위반 여부"만 걸러내는 하드/소프트 제약으로 두고, 향후 데이터가 쌓이면 objective 항으로 승격을 검토한다. |
| submit budget/capital usage 제약 | **제약 조건으로 포함** | 이미 운영 중인 daily cap(`max_general_buy_submit_per_day`)이 자연스러운 제약 변수 — 정책평가는 "이 제약이 주어졌을 때 그 예산을 어떤 후보에 배분하는 게 최선인가"를 비교하는 문제로 정의되어야 한다(예산 자체를 늘리는 것은 별도 정책 결정이지 이 objective의 최적화 대상이 아니다). |
| holding horizon | **T+1~T+N 다중 horizon 병행 관측(단일 horizon 고정 금지)** | 이 시스템은 실제 청산 시점이 AI(REDUCE/EXIT)/사용자 판단에 따라 가변적이라, 단일 고정 horizon(예: T+5)만 보면 실제 정책의 청산 행태와 괴리된 가상의 수익률을 측정하게 된다. 최소 T+1/T+5/T+20 3개 창을 병행 관측하고, **실제 realized_pnl_events(실제 청산 시점 기준)를 authoritative 값으로 삼아야 한다**(§4.5).

### 3.3 objective function 초안(문장형, factual한 구성요소만)

> "제약(하드 리스크 한도, 컴플라이언스, submit budget, 유동성) 위반이
> 없는 정책 후보들 중에서, 동일 기간·동일 유니버스에 대해 **realized_
> pnl_net(청산 완료분) + virtual mark-to-market(미청산분, 최근
> position_snapshots 기준) 합의 평균 기대수익(bps 단위, 연환산 비교
> 가능하도록 정규화)이 가장 높은 정책을 채택 후보로 본다. 단, 같은
> 기대수익 구간에서는 max_drawdown/변동성이 더 낮은 정책을 우선한다."

이 objective는 **수학적으로 증명된 전역 최적**이 아니라, **정의된
제약 안에서 관측 가능한 정책 후보 집합 사이의 상대 비교 기준**이다 —
"전역 최적성 근사"라는 표현은 "이 objective 기준으로 후보들을 비교해
상대적으로 더 나은 쪽을 찾아간다"는 뜻이지, "이 objective가 진짜 최적해임을
증명한다"는 뜻이 아니다(§9에서 재확인).

---

## 4. Q3. 현재 로그/DB만으로 반사실(counterfactual) 정책평가가 가능한가

| 항목 | 가능/불가능 | factual 근거 |
|---|---|---|
| feature snapshot만으로 다른 score식 replay | **부분 가능** | `signal_feature_snapshots`에 `sma_5/20/60`, `return_1m/3m_pct`, `volatility_20d_pct`, `atr_14_pct`, `rsi_14`, `fast_score`/`slow_score`/`overall_score`, `component_scores_json`(중간 분해)이 저장돼 있어, **점수 공식 자체를 다시 계산**하는 것은 가능하다. 단 `entry_score`/`exit_score`/`ranking_score`/`portfolio_allocation` 등 **최종 합성 점수 자체는 별도 테이블에 저장되지 않고 `trade_decisions.decision_json`에만(그 cycle 당시 계산값으로) 남는다** — feature snapshot을 재입력해 "다른 gate 계수"로 재계산하는 것은 가능하지만, "다른 feature 정의(예: SMA 기간 자체를 바꾼 경우)"의 replay는 원본 OHLCV/bar 데이터가 별도로 남아있는지에 달려 있다(이번 조사에서 원본 bar 데이터 테이블 존재 여부까지는 확인하지 않음 — 미확정). |
| `trade_decisions.decision_json`만으로 gate 재판정 | **부분 가능** | `decision_json`에 `deterministic_trigger`/`strategy_selection`/`portfolio_allocation`/`expected_value_gate` 등 하위 dict가 실제로 저장돼 있음(이 세션에서 여러 번 직접 SQL로 확인 — `decision_json -> 'deterministic_trigger' -> 'metadata' ->> 'risk_tone'` 등). 다만 **이 값들은 "그 cycle에 실제로 계산된 스냅샷"이지, 코드가 바뀐 뒤 재계산한 값이 아니다** — 새 gate 계수로 "재판정"하려면 결국 코드를 새 파라미터로 재실행해야 하며, `decision_json`은 그 재실행에 필요한 **입력 feature**를 제공할 뿐 재판정 엔진 자체는 아니다. |
| 어떤 필드가 없어서 replay가 깨지는가 | **다음이 확인됨(factual)** | (1) `expected_value_gate`의 `score_anchor`가 어떤 원본 점수(entry_score vs exit_score vs 기타)에서 왔는지는 `_resolve_score_anchor()` 코드를 함께 봐야 알 수 있고 `decision_json`만으로는 역산이 불완전할 수 있다(미확정 — 실제 필드 존재 여부는 직접 대조 필요). (2) `replay_bundles` 테이블이 있으나 0행이라 **이 목적을 위해 설계된 인프라가 실제로는 사용되지 않고 있다.** (3) `config_versions`가 3행뿐이라 "이 결정이 어떤 정책 버전에서 나왔는가"를 코드 변경 시점(git commit)과 자동으로 연결할 방법이 DB 안에는 없다. |
| pre-AI skip(trade_decisions 미생성) 구간 처리 | **불가능(현재 구조로는)** | 이 세션에서 반복 확인: `_evaluate_pre_ai_validation_result()`/`_evaluate_pre_agent_short_circuit()`가 스킵을 결정하면 **`trade_decisions` row 자체가 생성되지 않는 경로가 있다**(held_position skip, general_buy_budget_exhausted 등). 로그(`SUBMIT_PIPELINE_TRACE`, `[SYMBOL_DONE] ... skip_reason=...`)에만 흔적이 남고, `guardrail_evaluations`에 기록되는 경우와 안 되는 경우가 섞여 있다(Pass 2 drop 경로는 기록 안 됨, Pre-AI gate 경로는 기록됨 — 이전 세션 실측). **이 population(스킵된 후보)의 "만약 진행됐다면 어땠을까"는 현재 저장 구조로는 재구성 불가능** — 애초에 그 시점의 feature snapshot이 남아있다는 보장이 없다(스킵이 feature 조회보다 먼저 일어나는 경로도 있음). |
| order fill / realized PnL / virtual entry price 중 무엇이 authoritative | **`realized_pnl_events`가 청산분의 authoritative 값(fee/tax 반영된 net)**, 미청산 포지션은 **`position_snapshots`의 최신 `market_price` 기준 mark-to-market이 유일한 대안**(factual) | `realized_pnl_events`는 실제 매도 체결 시점 기준으로 계산되므로 "실현된" 성과의 정답이다. 다만 **미청산(보유 중) 포지션의 기대수익 기여는 이 테이블에 없다** — 정책평가가 "지금 산 게 얼마나 좋았는가"를 판단하려면 미청산분도 mark-to-market으로 함께 봐야 하는데, 이 mark-to-market 값이 시점별로 계속 변하므로 "정책 A vs B 비교" 시점을 고정하지 않으면 비교 자체가 흔들린다(§7의 신규 로그 제안으로 연결). |

**종합 판정(해석)**: **"완전한 반사실 재현"은 지금 불가능하고, "제한된
범위의 재현"만 가능하다.** 구체적으로: (1) 이미 실행된 정책이 만든
feature/gate 판정 스냅샷을 다시 읽어 **다른 임계값으로 재판정**하는
것은 가능(가장 저비용, 즉시 착수 가능), (2) **다른 feature 정의**나
**pre-AI에서 스킵된 population**에 대한 반사실은 원본 데이터 자체가
없어 불가능, (3) 이 간극을 메우는 것이 이번 설계의 Stage A(§7)다.

---

## 5. Q4. 정책평가 방법론 비교

| 방법 | 구현 난이도 | 필요 전제(로그/데이터) | 편향 위험 | 운영 리스크 | 기대수익 판단력 | 전역 최적성 근사 정도 |
|---|---|---|---|---|---|---|
| ① 단순 replay/backtest(저장된 feature로 다른 threshold 재판정) | 낮음 | 현재도 부분 충족(§4) | **높음** — look-ahead bias(미래 정보 누설) 위험, 실제 체결 불가능한 가격 가정 위험 | 없음(코드 실행만) | 낮음~중간(1차 필터링용) | 낮음 — "이 threshold였으면 통과했을 후보 집합"만 보여줄 뿐, 실제로 그 정책이 운영됐다면 다른 population이 됐을 수 있음(다른 정책이 submit budget/포지션을 다르게 소비했을 것이므로) |
| ② shadow policy + paper execution(이미 이 저장소에 loss-cut shadow 패턴으로 존재) | 중간 | shadow 전용 로깅(이미 `loss_cut_shadow` 유사 패턴 존재 — `decision_json.loss_cut_shadow`) | 중간 — 실제 자본 배분과 분리돼 있어 "실제로 샀다면 있었을 슬리피지/기회비용"을 과소평가 가능 | 낮음(실주문 없음) | 중간~높음 — 실제 운영 데이터 흐름 위에서 병행 관측 가능 | 중간 |
| ③ off-policy evaluation(IPS/SNIPS/doubly robust) | **높음** | 각 결정 시점의 "정책이 각 후보를 선택할 확률"(propensity)이 필요 — 이 시스템은 deterministic gate가 대부분이라 확률적 정책이 아님(hard threshold) | **매우 높음** — propensity가 0/1에 가까운 deterministic 정책에서는 IPS류 방법이 분산 폭발(거의 모든 가중치가 0 또는 무한대)로 사실상 무의미 | 낮음 | 이론상 최고(정확한 반사실) — 그러나 이 시스템 구조에서는 전제가 깨짐 | **이 저장소 현재 구조에서는 적용 난이도 대비 실익이 낮음** — deterministic gate를 랜덤화(예: threshold 근처 후보를 확률적으로 통과/차단)하지 않는 한 propensity 추정 자체가 불가능 |
| ④ regime-stratified walk-forward evaluation | 중간 | `market_regime`/`strategy_selection` 레이블이 이미 `decision_json`에 존재 | 중간 — regime 분류 자체의 시차/오분류 위험 | 없음 | 높음 — 이 세션에서 이미 여러 번 이 방식(국면별 표본 분리)으로 실측해왔음(B축/C축 분석 전부 이 패턴) | 중간~높음 — "이 저장소가 이미 익숙하게 하고 있는 방식"의 자연스러운 확장 |
| ⑤ constrained Bayesian/grid policy search(threshold 조합 탐색) | 중간~높음 | ①의 replay 인프라가 선행돼야 함 | 낮음~중간 — 탐색 공간이 좁으면 과적합 위험(과거 데이터에만 맞는 threshold) | 없음(오프라인) | 높음 — "여러 후보 정책을 동시에 비교"라는 이번 턴 목표에 가장 직접 부합 | 높음(제약된 탐색 공간 안에서는) |
| ⑥ online limited rollout/traffic split | 낮음(개념) / **높음(운영 리스크 관리)** | 실주문 분리 실행 인프라, A/B 배분 로직 | 낮음(실측이므로 편향 없음) | **매우 높음** — 실자본 배분, 소액이라도 규정/컴플라이언스 이슈 가능 | 최고(진짜 실측) | 이론상 최고이나 **이 시스템의 "감내 가능한 손실" 원칙과 신중히 병행해야 함** — 1차 도입 대상 아님 |

**판정(해석)**: **④(regime-stratified walk-forward)를 축으로, ①(replay)을
전처리 단계로, ⑤(constrained grid search)를 정책 비교 단계로 결합**하는
것이 이 저장소에 맞다. ③(off-policy evaluation, IPS류)은 이 시스템이
확률적 정책이 아니라 **결정론적(hard threshold) 정책**이라는 구조적
이유로 1차 도입에서 제외한다(과장 금지 원칙에 따라 "가능하지만 비추천"이
아니라 "현재 구조에서는 전제 자체가 성립하지 않는다"로 명확히 기록).
②(shadow)는 이미 loss-cut 트랙에서 유사 패턴이 있어 재사용 가능하고,
⑥(online rollout)은 최종 단계로 남겨둔다.

---

## 6. Q5. 1차 정책평가 아키텍처(단계 제안)

- **Stage A — Replay-ready logging contract 확정**: 지금 스킵/미기록
  구간(§4, §7)을 메우고, "이 결정이 어떤 feature/gate 파라미터로
  만들어졌는지"를 100% 재현 가능하게 만드는 단계. **코드/스키마 변경이
  필요하나 정책 로직 자체는 바꾸지 않는다.**
- **Stage B — Constrained candidate policy set 비교(오프라인)**: Stage A로
  확보된 로그 위에서, 현재 운영 정책과 소수의 대안 threshold/gate
  조합을 replay로 비교. **regime-stratified(④)로 국면별 분리 필수.**
- **Stage C — Shadow execution(병행 관측)**: Stage B에서 유망하다고
  판단된 후보 1~2개를 실주문 없이 shadow로 병행 기록(이미 `loss_cut_
  shadow` 패턴 존재 — 동일 인프라 재사용 검토).
- **Stage D — Limited online rollout**: Stage C 결과가 충분히 쌓이고
  사용자가 명시적으로 승인한 경우에만, 아주 제한된 범위(예: 특정
  source_type 하나, 특정 예산 비중)로 실제 정책을 교체해 실측.

**단계 간 게이트**: 각 단계는 이전 단계의 "충분한 표본"과 "사용자 승인"
없이 다음 단계로 자동 진행하지 않는다 — 이 세션 전체에서 반복된
원칙(read-only 조사 → 사용자 확인 → 구현)과 동일한 리듬을 유지한다.

---

## 7. Q7. 지금 당장 추가로 저장/로그해야 할 것(가장 중요)

| 항목 | 현재 상태(factual) | 필요한 보강(제안) |
|---|---|---|
| raw feature 재현성 | `signal_feature_snapshots`에 지표값은 있으나, **그 지표를 만든 원본 bar/OHLCV 데이터가 별도로 남아있는지 이번 조사에서 확인 못함**(미확정) | feature 재계산이 아니라 "다른 feature 정의" 실험까지 하려면 원본 bar 보존 여부 확인이 선행 필요 — 다음 턴 조사 항목으로 남김. |
| 중간 score decomposition | `component_scores_json`(signal_feature_snapshots)과 `decision_json`의 하위 dict가 부분적으로 이를 제공 | `entry_score`/`exit_score`/`ranking_score`/`portfolio_allocation` 등 **최종 합성 점수 자체와 그 구성 항(가산/감산 각 항목의 개별 기여도)을 별도 필드로 명시적으로 저장**해야 "이 항을 바꾸면 무엇이 달라지는가"를 재계산 없이 바로 비교 가능. |
| gate reason / threshold margin | reason_codes는 풍부하게 남지만 **"threshold까지 얼마나 여유/부족했는가"(margin)는 대부분 저장되지 않음**(pass/fail만 남고 수치 자체는 유실되는 경우 다수 — 이 세션에서 여러 번 "그 값 자체가 없어서 원인 분해가 어려웠다"는 패턴 반복 확인) | 모든 hard gate 판정에 **판정 당시 실제 값 vs threshold 값**을 한 쌍으로 저장(예: `entry_score=0.63 vs threshold=0.65`) — margin 분포를 봐야 "threshold를 살짝 조정하면 얼마나 바뀌는지"를 계산할 수 있다. |
| policy version/fingerprint | `config_versions`(3행, 2026-08-14 이후 갱신 없음)만 존재 — 실제 정책 변경은 git commit으로만 추적됨 | 매 결정에 **적용된 코드의 git commit SHA(또는 최소한 배포 시점 buildinfo)**를 남기는 최소 필드 하나만 추가해도, "이 표본이 어떤 정책 버전에서 나왔는지"를 사후에 완벽히 재구성할 수 있다 — 가장 저비용·고효용 항목으로 판단. |
| candidate universe snapshot | `universe_anchor`(intraday freeze)가 이미 일부 저장됨(이 세션에서 여러 번 확인) | 이미 상당 부분 충족 — 추가로는 "이번 cycle에서 pre-AI/deterministic 단계에 의해 후보에서 아예 제외된 심볼 목록"까지 남기면 population 편향(생존 편향) 분석이 가능해진다. |
| virtual entry / actual fill / realized pnl 연결 | `realized_pnl_events`(청산분)만 authoritative, 미청산 mark-to-market은 `position_snapshots` 최신값에 의존 | **정책 비교 시점을 고정한 스냅샷 테이블**(예: "정책평가 기준일의 각 포지션 mark-to-market 값")을 별도로 스냅샷 떠 두지 않으면, 비교 시점이 다른 두 정책의 미청산 성과를 공정하게 비교하기 어렵다 — Stage A에서 이 스냅샷 메커니즘을 설계해야 한다. |
| skip/pre-ai gate population 추적 | Pass2 drop/pre-agent short-circuit 등 **일부는 trade_decisions가 아예 생성되지 않음**(이전 세션 실측으로 이미 확인된 사실) | **모든 스킵 경로에 최소한의 population 레코드(symbol, cycle, 스킵 사유, 그 시점 feature snapshot id)를 남기는 경량 테이블**이 필요 — `guardrail_evaluations`를 이 목적에 맞게 확장하거나, 신규 경량 로그 테이블을 신설하는 두 가지 안이 있다(이번 문서는 설계만, 구현 방식은 다음 턴에서 결정). |

---

## 8. Q6. `SPPV-3`와의 관계

- **SPPV-3가 끝나야만 가능한 것**: "이 정책이 실제로 알파가 있는 신호
  위에서 작동하는가"라는 전제 확인 — 만약 SPPV-3 축 1(alpha 자체
  예측력)이 최종적으로 "유의미한 예측력 없음"으로 결론 나면, 이번
  문서가 설계하는 정책평가 체계는 **"노이즈 위에서 최적 threshold를
  찾는" 무의미한 작업**이 될 위험이 있다. 따라서 **Stage B(정책 후보
  비교)의 실제 착수는 최소한 SPPV-3 축 1의 Go/Hold 판정이 나온
  뒤여야 한다.**
- **SPPV-3와 병행 가능한 것**: Stage A(로깅 계약 보강)는 SPPV-3의
  결론과 무관하게 지금 시작해도 안전하다 — 오히려 SPPV-3 축 2/4(gate
  통과 후 성과, funnel 전환 기여도)가 필요로 하는 데이터 요구사항과
  이번 문서 §7의 요구사항이 상당 부분 겹친다(예: threshold margin,
  population 추적). **Stage A를 SPPV-3 축 2/4의 실측 인프라로 공유
  설계하면 중복 작업을 피할 수 있다.**
- **SPPV-3 없이 하면 왜 위험한가**: SPPV-3가 검증하려는 것은 "신호
  자체가 진짜인가"이고, 이 문서가 설계하는 것은 "그 신호를 정책이
  얼마나 잘 쓰고 있는가"다. 전자가 거짓이면 후자를 아무리 잘해도
  기대수익은 오르지 않는다 — **순서를 바꿔 정책 최적화부터 진행하면,
  실제로는 예측력 없는 신호에 대한 threshold를 정교하게 다듬는
  헛수고**가 될 수 있다.
- **SPPV-3 결과가 탐색 공간 축소에 기여하는 방식**: 축 1이 "이 feature는
  국면 X에서만 유의미"로 결론 내리면, Stage B의 정책 후보 탐색은 그
  국면에서만 활성화되는 threshold 조합으로 탐색 공간을 좁힐 수 있다
  (전 국면에 걸쳐 같은 threshold를 탐색하는 것보다 훨씬 효율적).

**요약(해석)**: 이번 설계는 SPPV-3를 **대체하거나 우회하지 않는다** —
오히려 SPPV-3를 "정책평가 체계의 필수 선행 입력을 만드는 하위 검증
단계"로 재정의한다. SPPV-3가 축 1에서 최종 Go 판정을 내리기 전까지,
이 문서의 Stage B 이후 단계는 **설계는 해두되 실제 착수는 보류**한다.

---

## 9. 리스크 / 한계 / 미확정

- **"전역 최적성"이라는 표현에 대한 명시적 한정**: 이 문서가 설계하는
  체계는 수학적으로 전역 최적을 증명하는 것이 **아니다.** 정의된
  objective function과 제약 조건 안에서, **관측 가능한(=이미 로그로
  남길 수 있는) 정책 후보 집합** 사이의 상대 비교일 뿐이며, 탐색하지
  않은 정책 공간(예: 완전히 다른 feature 설계)에 대해서는 아무것도
  말해주지 않는다.
- 원본 bar/OHLCV 데이터의 장기 보존 여부는 이번 조사에서 확인하지
  못했다(미확정) — Stage A 착수 전 확인 필요.
- `expected_value_gate.py`의 `expected_return_bps`가 실제 realized
  return과 상관관계가 있는지는 **아직 검증되지 않았다**(이게 바로
  SPPV-3 축 1이 다루는 질문) — 이번 objective function 설계는 이
  값을 "가정"으로만 쓰고, 검증된 사실로 취급하지 않는다.
- off-policy evaluation(IPS류)이 이 시스템 구조(결정론적 gate)에서
  구조적으로 어렵다는 판정은 코드 리뷰 기반 판단이며, 향후 gate
  일부를 의도적으로 확률화(예: threshold 근처 후보를 일정 확률로
  통과)하는 실험을 설계하면 재검토될 수 있다 — 이번 문서에서는
  제안만 하고 실행하지 않는다.
- Stage A의 "스킵 population 추적" 신규 테이블/필드의 구체적 스키마는
  이번 설계 문서에서 확정하지 않았다 — 다음 구현 턴에서 확정 필요.

---

## 10. 성공 기준(제안)

- **Stage A 성공 기준**: 하루치 운영 데이터에 대해, "이 cycle에 어떤
  후보가 있었고, 어떤 이유로 무엇이 스킵/차단됐고, 통과한 것들의
  gate margin이 얼마였는지"를 **DB 쿼리만으로(코드 재실행 없이)** 100%
  재구성할 수 있으면 성공.
- **Stage B 성공 기준**: 현재 운영 정책과 최소 1개 이상의 대안 정책
  후보에 대해, 동일 기간·동일 유니버스 기준으로 objective function
  값(평균 net 기대수익, 제약 위반 여부)을 **재현 가능하게** 비교
  제시할 수 있으면 성공. "더 나은 정책을 확정한다"가 아니라 "비교
  가능한 근거를 만든다"가 이 단계의 성공 기준이다.
- **전체 트랙 성공 기준**: 향후 gate/threshold 변경 제안이 나올 때마다
  "감으로" 판단하지 않고, 이 체계를 통해 **"제약 위반 없이 objective가
  개선되는가"**를 최소한 오프라인 replay 수준에서라도 먼저 확인한 뒤
  구현에 들어가는 관행이 자리 잡으면 성공.

---

## 11. Stage A 구현 설계 (2026-08-20 KST 2차 확장, read-only 조사)

§7이 나열한 Stage A 요구사항을 **실제 구현 가능한 최소 contract**로
좁힌다. 이번 조사에서 코드/DB를 직접 대조해 "이미 있는 것"과 "정말
새로 필요한 것"을 분리했다 — 새 테이블을 늘리기 전에 기존 저장 경로
재사용 가능성을 먼저 확인했다.

### 11.1 Stage A 목적 재정의

Stage A의 목적은 "완벽한 replay 엔진을 만드는 것"이 아니라, **"이
cycle에 무엇이 있었고, 무엇이 왜 스킵/차단됐고, 통과한 것의 margin이
얼마였는지를 DB 쿼리만으로 100% 재구성 가능하게 만드는 최소 계약"**
을 확정하는 것이다(§10과 동일 기준). Stage B(정책 후보 비교)가 실제로
착수 가능한 상태가 되기 위한 **전제 인프라**이며, 그 자체로 정책
판단을 내리지 않는다.

### 11.2 authoritative source 표 (Q2)

| 항목 | authoritative source | factual 근거 |
|---|---|---|
| candidate population | `scripts/run_decision_loop.py`의 `universe`(`_load_trading_universe_with_anchor`) + `decision_json.universe_anchor` | 매 cycle의 유니버스 스냅샷은 이미 `universe_anchor`로 각 trade_decision에 남는다(intraday freeze 재사용 여부까지 포함) — **이미 충분**. |
| pre-AI skip population | **`guardrail_evaluations`(rule_set_version=`pre_ai_gate_v1`)** — 단, `decision_context_id`/`trade_decision_id`가 항상 NULL(실측: 최근 3일 48건 전부 NULL) | 이미 이 population을 어느 정도 담고 있으나(symbol/market/account_id/source_type/stop_reason/`rule_results` 안에 `current_signal_feature_snapshot_id`까지 포함), **Pass 2 budget-drop 스킵은 이 테이블에 아예 안 씀**(이전 세션에서 이미 확인된 gap) — population이 경로별로 불균일. |
| deterministic trigger decomposition | `trade_decisions.decision_json.deterministic_trigger`(trade_decision 생성된 경우만) | trade_decision이 없는 스킵 건은 이 decomposition 자체가 유실됨(guardrail_evaluations.rule_results에 일부만 남을 수 있음, 스킵 사유에 따라 다름). |
| gate별 차단 사유 | `decision_json.reason_codes` + `guardrail_evaluations.blocking_rule_codes` | 두 곳에 나뉘어 있고 서로 다른 gate 계층(AI 선택지 제한 vs 최종 안전판, 이전 PR #289에서 확인한 구분)을 반영 — **하나로 합치면 안 되고, "어느 계층의 사유인지" 구분 필드가 필요**. |
| 최종 decision | `trade_decisions`(decision_type/side/reason_codes) | 이미 authoritative. |
| actual order/fill | `order_requests` + `broker_fill_snapshots`/`fill_events` | 이미 authoritative, 이번 조사에서 스키마 변경 불필요로 판단. |
| realized pnl | `realized_pnl_events.realized_pnl_net`(fee/tax 반영) | 이미 authoritative(§4에서 이미 확인). |
| 미청산 mtm | **`position_snapshots`(market_price/unrealized_pnl, snapshot_at 시계열)** | **직전 설계(§4)에서 "mtm 비교 기준 불완전"이라 판단했으나, 재조사 결과 `position_snapshots`가 이미 계좌×종목×시각별 mark-to-market 시계열을 저장 중임을 확인했다 — 완전히 새로 만들 필요는 없다.** 부족한 것은 "정책 비교 시점을 고정해 어느 snapshot을 기준으로 삼을지"를 정하는 **as-of 쿼리 계약**뿐이다(§11.6). |
| policy version | **없음(신뢰 가능한 authoritative source 부재)** | `config_versions`는 3행뿐, 마지막 갱신 2026-08-14 — 이 세션에서 실제 있었던 다수의 gate 변경(B축 안A, R1~R5, submit budget D안, held_position FDC 제한 등)은 전부 git commit으로만 존재하고 `config_versions`에는 반영 안 됨. **이번 조사에서 신규로 확인**: `trade_decisions`/`guardrail_evaluations` 어디에도 "이 결정을 만든 코드의 버전"을 가리키는 필드가 전혀 없다 — §11.5에서 최소 필드 제안. |
| replay input bundle | **없음(스키마만 존재, 코드 0건)** | `trading.replay_bundles`는 `db/migrations/0001_initial_schema.sql`(최초 커밋)에 정의된 뒤 **`src/agent_trading/` 전체에서 이 테이블을 참조하는 코드가 0건**(repository도 없음, `grep -rn replay_bundle src/` 결과 0건) — "실사용 0행"이 아니라 "쓰는 코드 자체가 없다"가 더 정확한 factual 서술이다. 설계 의도(컬럼: `bundle_uri`+`checksum`)는 **외부 blob 저장소 경로를 가리키는 포인터**였지, JSON을 직접 담는 구조가 아니었다 — 이 방향을 그대로 따르면 blob 저장소 인프라까지 새로 구축해야 해서 Stage A 범위를 벗어난다(§11.4에서 대안 제시). |

### 11.3 Q1 — Stage A 최소 범위

| 분류 | 항목 |
|---|---|
| **반드시 지금(Stage A) 추가** | (1) 모든 스킵 경로(pre-AI gate뿐 아니라 Pass 2 budget-drop 포함)가 **동일한 방식으로** population을 남기도록 통일 — 지금처럼 경로별로 있다 없다 하면 population 자체가 편향된다. (2) 매 결정(및 스킵)에 **policy fingerprint(최소 git commit SHA)** 1개 필드 저장 — 가장 저비용·고효용. (3) hard gate 판정에 "실제 값 vs threshold" margin 쌍 저장(현재 pass/fail만 남는 gate 다수). |
| **있으면 좋지만 Stage B 전엔 없어도 됨** | (4) mtm as-of 쿼리 계약 문서화(테이블 자체는 이미 있음 — 조회 규칙만 정하면 됨, §11.6). (5) `entry_score`/`ranking_score` 등 최종 합성 점수의 항목별 기여도 명시적 필드(현재도 `component_scores_json`/`decision_json`에 일부 있어 완전 신규는 아님). |
| **Stage C 이후로 미뤄도 됨** | (6) `replay_bundles`(외부 blob) 실사용 전환 — Stage A/B는 DB 쿼리만으로 충분히 재구성 가능하므로, 외부 bundle 아카이브는 "정책 후보가 여러 개로 늘어나 DB 쿼리 비용이 부담되는 시점"(Stage C 이후)에 재검토. (7) 완전한 원본 bar/OHLCV 재현성 확인(§9 미확정 유지). |

### 11.4 Q3 — pre-AI skip population 보존 설계안 비교

| 안 | population 보존력 | 구현 범위 | replay 친화성 | 운영 리스크 | 중복/정합성 |
|---|---|---|---|---|---|
| ① `guardrail_evaluations` 확장(모든 스킵 경로가 여기 쓰도록 통일) | **높음** — 이미 pre_ai_gate 경로가 검증된 스키마(symbol/market/account_id/source_type/stop_reason/rule_results)로 쓰고 있어, 그 계약을 Pass 2 drop 등 나머지 경로로 넓히기만 하면 됨 | **낮음** — 신규 테이블 없이 기존 `add()` 호출 지점만 늘리면 됨(Pass 2 drop 경로에 호출 추가) | 높음 — 이미 `current_signal_feature_snapshot_id`까지 남기고 있어 replay 입력으로 바로 쓸 수 있음 | 낮음 | `decision_context_id`/`trade_decision_id`가 계속 NULL이라 다른 population과 조인이 약함 — 이 필드에 **"이 스킵이 속한 cycle 식별자"**(예: cycle_index+run 식별자)를 새 컬럼으로 추가하면 해소 가능(마이그레이션 1건) |
| ② 별도 `policy_evaluation_events`류 신규 테이블 | 높음(설계 자유도 최대) | **높음** — 신규 테이블+마이그레이션+repository+모든 스킵/통과 지점에서 이중 기록 | 높음(전용 스키마) | 중간 — 기존 `guardrail_evaluations`와 목적이 겹쳐 "어디를 봐야 하는지" 헷갈리는 이원화 위험 | 기존 테이블과 데이터 중복(같은 스킵 사유가 두 곳에 남음) — "무턱대고 새 테이블을 늘리지 말라"는 이번 턴 원칙에 정면으로 위배 |
| ③ `replay_bundles` 실사용 전환 | 중간(포인터 방식이라 실제 내용은 외부 저장소에 의존) | **가장 높음** — 외부 blob 저장 인프라(S3/파일시스템 경로 규약)까지 새로 구축해야 함 | 초기엔 낮음(구축 전까지 아무 데이터 없음) | 중간(외부 저장소 장애/권한 관리 추가) | 없음(기존 스키마 그대로 채우는 것뿐이나, 채우는 코드 자체가 처음부터 필요) |
| ④ 로그만 유지, DB 미적재 | 낮음 — 이 세션에서 반복 확인된 문제: 컨테이너 재기동 시 로그 보존기간이 짧고(`docker logs --since` 조회가 컨테이너 시작 시점 이후로 제한되는 사례를 이전 턴에서 실제로 겪음), grep 기반 집계는 Stage B의 재현 가능한 replay 입력이 될 수 없음 | 없음(현행 유지) | **낮음** — Stage B가 요구하는 "DB 쿼리만으로 재구성"이라는 성공 기준(§10)을 원천적으로 만족 못 함 | 없음(현행 유지이므로) | 없음 |

**판정(해석)**: **①(`guardrail_evaluations` 확장)을 채택한다.** 이미
검증된 스키마와 이미 정확히 이 목적으로 쓰이고 있는 pre_ai_gate 경로가
있어 재사용 비용이 가장 낮고, "새 테이블을 늘리지 말라"는 이번 턴
원칙과도 부합한다. 유일한 보강 포인트는 **cycle 식별자 컬럼 1개
추가**(§11.7 작업 단위로 분해)뿐이다. ②는 기존 자산과 목적이 겹쳐
과설계, ③은 Stage A 범위를 벗어나는 인프라 비용, ④는 Stage B 성공
기준을 만족 못 해 배제한다.

### 11.5 Q4 — policy version / fingerprint 설계

| 안 | 최소 구현 비용 | 효과 |
|---|---|---|
| git commit SHA만 남기기 | **가장 낮음** — 배포 시점에 이미 알 수 있는 값(예: `git rev-parse HEAD`)을 컨테이너 환경변수로 주입하고, 이를 매 결정에 문자열 하나로 저장 | 코드가 그 시점에 정확히 어떤 상태였는지 100% 재현 가능(git이 이미 진짜 authoritative 버전 관리 시스템이므로) |
| `config_version_id`+git SHA 병행 | 중간 — `config_versions` row도 함께 갱신해야 함 | `config_versions`는 원래 "설정값"(threshold 숫자 등 데이터)을 위한 것이지 "코드 로직 자체의 버전"을 위한 것이 아니다 — 이번 세션의 변경 대부분(B축 안A, R1~R5)은 데이터가 아니라 **코드 로직**이 바뀐 것이라 `config_versions`만으로는 못 잡는다. |
| policy fingerprint(JSON hash) 별도 저장 | 높음 — "정책을 구성하는 요소들"을 JSON으로 직렬화해 해시해야 함, 무엇을 포함할지 정의 자체가 추가 설계 필요 | git SHA보다 더 세밀할 수 있으나, 코드 로직 변경까지 포함하려면 결국 "코드 전체"를 해시 대상에 넣어야 해 git commit SHA와 실질적으로 같은 정보를 더 비싸게 얻는 셈 |
| replay bundle 안에 캡슐화 | §11.4에서 이미 Stage A 범위 밖으로 판정 | 해당 없음 |

**판정(해석)**: **git commit SHA 하나만 매 결정에 남기는 것이 최소
구현으로 가장 효과적**이다. 어느 계층에 남길지는 — `trade_decisions`
(정상 결정)과 `guardrail_evaluations`(스킵 결정) **양쪽 모두에 동일한
필드명**으로 남겨야 두 population을 정책 버전 기준으로 합쳐 볼 수
있다. 신규 컬럼 1개(`policy_git_sha` 또는 유사명)를 두 테이블에
추가하는 것이 최소 구현이다(마이그레이션 2건 분량이나 성격은 동일).

### 11.6 Q5/Q6 — replay-ready bundle 최소 contract, mtm 연결 범위

- **`decision_json` 재사용만으로 충분한가**: **거의 충분하다(해석)** —
  `deterministic_trigger`/`strategy_selection`/`portfolio_allocation`/
  `expected_value_gate` 하위 dict가 이미 저장되고 있어, "정상적으로
  trade_decision이 생성된 population"에 한해서는 **별도 bundle 없이
  `decision_json` 자체가 사실상의 bundle**이다. 부족한 것은 (a) 스킵
  population(§11.4에서 guardrail_evaluations 확장으로 해소), (b)
  policy fingerprint(§11.5), (c) gate margin(§11.3의 (3))뿐이다.
  **별도의 새 "bundle" 스키마를 새로 설계하지 않고, 기존 `decision_
  json`/`guardrail_evaluations.rule_results`의 계약을 다듬는 것으로
  충분하다는 것이 이번 조사의 핵심 결론이다.**
- **realized pnl + mtm — Stage A에서 어디까지**: **Stage A는 realized_
  pnl_net(authoritative, 이미 충분) 경로 정리만 하고, mtm은 "as-of
  조회 규칙 문서화" 수준으로 가볍게 포함한다.** `position_snapshots`
  테이블 자체는 이미 존재하고 이미 시계열로 쌓이고 있어(§11.2), Stage A
  에서 새 스냅샷 메커니즘을 만들 필요가 없다 — 단, "정책 A와 B를
  비교할 때 어느 시각의 `position_snapshots` 행을 mtm 기준으로 쓸지"
  (예: 비교 시각 직전 최신 snapshot, 또는 비교 시각과 가장 가까운
  snapshot)에 대한 **명시적 규칙이 없다는 점**만 문서로 못박는다.
  이 규칙 자체를 코드로 구현하는 것은 Stage B 착수 직전으로 미룬다
  (지금 구현해도 Stage A 성공 기준에 필수는 아님).

### 11.7 Q7 — 구현 작업 단위 분해

| 단위 | 목적 | 변경 파일 후보 | 저장/계약 변화 | 테스트 범위 | 운영 리스크 | 선행 조건 |
|---|---|---|---|---|---|---|
| **A-1a**: Pass 2 budget-drop 스킵도 `guardrail_evaluations`에 기록 | pre-AI gate 경로와 population 계약 통일 | `scripts/run_decision_loop.py`(`_general_lane_dropped_result()` 주변) | 신규 컬럼 없음 — 기존 `add()` 호출을 이 경로에도 추가 | 신규 단위 테스트(해당 경로에서 guardrail row 1건 생성 확인) | 낮음(로깅 추가뿐, 판정 로직 무변화) | 없음 — 독립 착수 가능 |
| **A-1b**: `guardrail_evaluations`에 cycle 식별자 컬럼 추가 | 스킵 population을 같은 cycle의 통과 population과 조인 가능하게 | 마이그레이션 1건, `guardrail_evaluations.py`(add 시그니처), 호출부 전체 | **스키마 변경(신규 컬럼, nullable)** | repository 단위 테스트 + 호출부 회귀 테스트 | 낮음(nullable 추가라 하위 호환) | A-1a와 병행 가능 |
| **A-2**: policy git SHA 필드 추가 | 정책 버전 fingerprint 확보 | 마이그레이션 1건(두 테이블), `trade_decisions.py`/`guardrail_evaluations.py`(add 시그니처), 값 주입 지점(배포 환경변수 → 결정 생성 코드) | **스키마 변경(신규 컬럼, nullable)** | repository 테스트 + 값 주입 지점 단위 테스트 | 낮음(nullable, 값 없으면 NULL로 기록) | 없음 — 독립 착수 가능, A-1과 순서 무관 |
| **A-3**: hard gate margin(실제값 vs threshold) 저장 | replay 시 "threshold를 얼마나 바꾸면 결과가 달라지는지" 계산 가능하게 | `deterministic_trigger_engine.py`, `expected_value_gate.py`, `strategy_selection.py`(각 hard gate 판정 지점) | `decision_json` 하위 dict에 필드 추가(스키마 변경 아님, JSONB라 마이그레이션 불필요) | 각 gate별 단위 테스트(margin 값 검증) | 낮음~중간(판정 로직 자체는 안 바뀌지만 여러 파일에 걸친 필드 추가라 회귀 검증 범위가 넓음) | 없음, 단 A-1/A-2보다 변경 파일 수가 많아 더 큰 작업 |
| **A-4**: mtm as-of 조회 규칙 문서화(+ 필요시 조회 헬퍼 함수) | 정책 비교 시 미청산 성과를 공정하게 비교 | 신규 read-only 헬퍼(예: `services/policy_evaluation_mtm.py`) 또는 문서만 | 코드 변경 없음(문서) 또는 read-only 조회 함수 신규 추가만(쓰기 없음) | 조회 함수를 만든다면 그 함수 단위 테스트만 | 낮음(read-only) | A-1~A-3 완료 후 착수(Stage B 직전이 자연스러움) |

**권장 착수 순서**: A-1a → A-2 → A-1b → A-3 → (Stage B 직전) A-4.
A-1a/A-2는 스키마 변경이 없거나 최소(nullable 컬럼 1개)라 리스크가
가장 낮고 즉시 착수 가능 — **이 둘을 Stage A의 "1차 구현 단위"로
추천한다.**

### 11.8 `SPPV-3`와 병행 가능성 재확인

A-1a/A-1b/A-2/A-3 전부 **정책 로직을 바꾸지 않는 순수 관측성 보강**
이라 `SPPV-3`의 결론(축 1 Go/Hold)과 무관하게 지금 병행 가능하다 —
오히려 A-3(gate margin)은 `SPPV-3` 축 2(정리된 gate 통과 후 성과)가
"threshold 근처 표본"을 분석할 때 그대로 재사용 가능한 데이터라
**공유 착수가 더 효율적**이다.

## 12. Stage A-1a + A-2 구현 완료(2026-08-20 KST 3차 확장, 코드 구현)

### 12.1 A-1a — Pass 2 general lane drop을 `guardrail_evaluations`에 기록

- `scripts/run_decision_loop.py`에 신규 `_record_pass2_general_lane_
  drop_guardrail_evaluation()` 추가 — `_run_general_lane_pass2()`의
  3개 드롭 지점(symbol dedupe 2곳 + budget exhausted 1곳) 전부에서
  호출한다.
- `gate_phase=pass2_general_lane_drop`으로 pre-AI gate 경로
  (`gate_phase=pre_ai_gate`)와 명시적으로 구분했다 — population
  contract(symbol/market/source_type/stop_reason/rule_results)는
  기존 `_record_pre_ai_guardrail_evaluation()`과 최대한 맞췄다.
- 판정 로직(누가 드롭되는지, 어떤 candidate가 남는지)은 **전혀 바꾸지
  않았다** — `_general_lane_dropped_result()` 호출부 뒤에 기록 호출을
  추가했을 뿐이다. 기록 실패(DB 예외 등)는 best-effort로 로그만 남기고
  Pass 2 진행에 영향을 주지 않는다.

### 12.2 A-2 — policy git commit SHA를 `trade_decisions`/
`guardrail_evaluations`에 저장

- 신규 마이그레이션 `db/migrations/0065_add_policy_git_sha_columns.sql`
  — 두 테이블에 `policy_git_sha VARCHAR(64)` nullable 컬럼 추가
  (additive only, 기존 행에 영향 없음).
- `src/agent_trading/config/settings.py`에 `resolve_policy_git_sha()`
  추가 — `AGENT_TRADING_GIT_SHA` 환경변수를 읽어 반환, 미설정 시
  `None`.
- `guardrail_audit.persist_validation_result()`(모든 guardrail
  evaluation 기록의 단일 진입점)에서 `policy_git_sha`를 한 번만
  주입 — pre_ai_gate/scheduler_gate/pass2_general_lane_drop 등
  **모든 guardrail 기록 경로에 자동으로 반영**된다(개별 호출부를
  일일이 고칠 필요 없음).
- `decision_factory.build_trade_decision_entity()`에 `policy_git_sha`
  파라미터 추가, `decision_orchestrator._ensure_trade_decision()`에서
  `resolve_policy_git_sha()` 값을 전달 — 정상 생성된 결정에도 동일한
  필드명으로 남는다.
- `docker-compose.yml`의 `ops-scheduler` 서비스에 `AGENT_TRADING_
  GIT_SHA: "${AGENT_TRADING_GIT_SHA:-}"` 배선 추가, `scripts/harness/
  contracts/runtime_env_wiring.json`에 항목 등록(`required_in_
  compose: false` — 관측성 전용이라 값이 없어도 실패 대상 아님),
  `.env.example`에 문서화. 실제 값은 배포 스크립트가 `export
  AGENT_TRADING_GIT_SHA=$(git rev-parse HEAD)` 형태로 주입해야
  채워진다(이번 턴은 배선까지만 — 실제 배포 스크립트 변경은 범위
  밖).

### 12.3 왜 판정 로직 무변화인가

A-1a는 이미 결정된 드롭 결과(`_general_lane_dropped_result()`가
반환하는 값)를 그대로 기록만 하고, 무엇을 드롭할지 결정하는 로직
(`_general_lane_priority_key()`, budget 비교식)은 건드리지 않았다.
A-2는 `policy_git_sha` 필드를 관측성 목적의 nullable 컬럼으로만
추가했고, 이 값이 어떤 gate/threshold 판정에도 입력으로 쓰이지
않는다 — 순수 기록용이다. 두 변경 모두 기존 pytest 스위트(신규 테스트
포함 총 220여 건)가 회귀 없이 통과함을 확인했다.

### 12.4 검증 결과(factual)

- `tests/services/ai_agents/test_settings.py`(+4),
  `tests/services/test_validators.py`(+2),
  `tests/services/test_decision_factory.py`(+2),
  `tests/scripts/test_run_decision_loop.py`(+2) 신규 테스트 전부 PASS.
- `tests/scripts/test_run_decision_loop.py`(132건),
  `tests/services/test_decision_orchestrator.py`(98건) 전체 회귀 없음.
- `accept db-structure`/`accept env`/`accept style`/`accept no-bypass`
  (hard_bypass_count=0)/`accept architecture` 전부 PASS.
- `accept backend-file`/`accept script-file`: 정상 대상 파일은 전부
  PASS. `guardrail_evaluations.py`/`trade_decisions.py`는 `no_safe_
  test_candidate_found`로 FAIL 표시되나(전담 DB-free 단위 테스트가
  구조적으로 없음), `git stash`로 이번 변경 이전 코드에서도 동일하게
  FAIL함을 확인 — 이번 변경과 무관한 기존 한계. `settings.py`도
  import-graph로 선택된 2개 무관 파일(`test_kis_realtime_quote_
  source.py`, `test_broker_capacity.py`)에서 기존 실패가 재현되나
  마찬가지로 `git stash` 대조로 무관함을 확인.
  **[2026-08-20 후속 보강]** `tests/repositories/test_postgres_
  guardrail_evaluations_policy_git_sha.py`/`test_postgres_trade_
  decisions_policy_git_sha.py` 신규 추가(DB-free, fake connection으로
  INSERT SQL/파라미터 직접 검증) — 기존 `seeded_postgres_data`(실제
  Postgres 연결) 기반 파일과는 별도 파일로 분리했다(같은 파일에
  합치면 import-graph가 그 파일 전체를 선택해 기존 DB-integration
  테스트까지 함께 실행하려다 접속 실패로 깨짐을 실제로 재현/확인 후
  분리 결정). 이제 `accept backend-file`이 두 대상 파일 모두 **직접
  PASS**한다(더 이상 `no_safe_test_candidate_found`가 아님).

### 12.5 미확정

- Postgres 실접속 상태에서 `trade_decisions`/`guardrail_evaluations`
  `add()`의 실제 INSERT(신규 컬럼 포함)가 정상 동작하는지는 이번
  턴(DB write 금지)에서 실측하지 못했다 — 다음 턴에서 dev 환경 DB로
  확인 필요.
- 배포 스크립트가 실제로 `AGENT_TRADING_GIT_SHA`를 채워 넣도록
  만드는 작업은 이번 범위 밖이다 — 코드/배선은 값을 받을 준비가
  됐으나, 실제 운영에서 이 값이 채워지려면 별도 배포 스크립트 수정이
  필요하다.
- Stage A-1b(cycle 식별자 컬럼)/A-3(gate margin)/A-4(mtm as-of 규칙)는
  §11.7 계획 그대로 다음 구현 턴 대상으로 남는다.

## 13. Stage A-1b 구현 완료 — decision cycle 식별자(2026-08-20 KST, 코드 구현)

### 13.1 무엇을 구현했는가

`guardrail_evaluations`에 `decision_cycle_id VARCHAR(128)` nullable
컬럼을 추가했다(마이그레이션 0066). `trade_decisions`는 이번 범위에
포함하지 않았다 — 정상 생성된 결정은 `decision_context_id`가 이미
NULL이 아니라서 cycle 단위 조인에 그 자체로 충분하고, cycle 식별자가
꼭 필요한 population(pre-AI 스킵/Pass 2 drop)은 애초에
`decision_context_id`가 없는 경로이기 때문이다.

### 13.2 식별자 형식

`decision_cycle_id = f"decision_submit_gate:{now.isoformat()}#{cycle_
count}"` — 예: `decision_submit_gate:2026-08-20T09:05:12+09:00#1`.

- `now`(=due_at)는 `run_ops_scheduler.py`가 cycle 시작 시 이미
  `CADENCE_TRACE decision_submit_gate action=start`에 쓰던 바로 그
  타임스탬프다 — 새로 계산하지 않고 재사용했다.
- `#{cycle_count}`는 `run_decision_loop.py` subprocess 내부에서
  여러 cycle이 도는 수동/단독 실행 상황에서만 의미가 생긴다 — 운영
  경로(scheduler `--count 1`)에서는 항상 `#1`로 고정돼 사실상
  무영향이다.
- symbol별 동적 상태나 in-flight 카운터는 전혀 쓰지 않는다 — scheduler
  가 cycle 시작 전에 이미 확정한 값 하나만 그대로 흘려보낸다.

### 13.3 생성 → 전달 경로

```
run_ops_scheduler.py (cycle 시작, now 확정)
  └─ decision_cycle_id = f"decision_submit_gate:{now.isoformat()}"
  └─ _decision_command(decision_cycle_id=...) → argv에 --decision-cycle-id 추가
       └─ subprocess: scripts/run_decision_loop.py --decision-cycle-id "..."
            └─ _parse_args() → args.decision_cycle_id
            └─ _run_loop(decision_cycle_id=...)
                 └─ while 루프 매 cycle마다:
                      cycle_decision_cycle_id = f"{decision_cycle_id}#{cycle_count}"
                      ├─ _execute_symbol_cycle(...) → _run_one_cycle(decision_cycle_id=...)
                      │     └─ pre-AI gate 스킵 시 _record_pre_ai_guardrail_evaluation(decision_cycle_id=...)
                      └─ _run_general_lane_pass2(decision_cycle_id=...)
                            └─ dedupe/budget 드롭 시 _record_pass2_general_lane_drop_guardrail_evaluation(decision_cycle_id=...)
```

공통 저장 계약은 `validators.ValidationContext.decision_cycle_id` →
`build_validation_context(decision_cycle_id=...)` →
`ValidationResult.to_guardrail_evaluation()` → `GuardrailEvaluationEntity.
decision_cycle_id` → `PostgresGuardrailEvaluationRepository.add()`
INSERT 파라미터, 단 하나의 경로로 통일했다 — pre-AI gate와 Pass 2
drop이 서로 다른 필드명/스키마를 쓰지 않는다.

### 13.4 pre-AI gate / Pass 2 drop이 같은 contract로 묶이는 방식

두 경로 모두 최종적으로 **같은 함수**(`persist_validation_result()`)
를 거쳐 **같은 컬럼**(`decision_cycle_id`)에 값을 남긴다. 차이는
`gate_phase` 메타데이터(`pre_ai_gate` vs `pass2_general_lane_drop`)
뿐이다 — 이번 턴 이전부터 유지해 온 "같은 경로인 척 섞지 않는다"는
원칙(Stage A-1a)을 그대로 지키면서, cycle 단위 조인만 새로 가능해진
것이다. 예를 들어 다음 SQL로 "같은 cycle에서 어떤 종목이 pre-AI에서
스킵됐고 어떤 종목이 Pass2에서 drop됐는지"를 한 번에 볼 수 있다:

```sql
SELECT decision_cycle_id,
       rule_results->>'gate_phase' AS gate_phase,
       rule_results->>'symbol' AS symbol,
       blocking_rule_codes
FROM trading.guardrail_evaluations
WHERE decision_cycle_id = 'decision_submit_gate:2026-08-20T09:05:12+09:00#1'
ORDER BY evaluated_at;
```

### 13.5 왜 판정 로직 무변화인가

`decision_cycle_id`는 어떤 gate/threshold/submit 판정 함수의 입력으로도
쓰이지 않는다 — 오직 기록(guardrail_evaluations INSERT)에만 실린다.
`_run_general_lane_pass2()`/`_run_one_cycle()`의 기존 파라미터(budget,
priority, source_type 등)는 전혀 바뀌지 않았고, 새 파라미터는 전부
`= None` 기본값이라 호출부를 안 고친 기존 테스트/경로는 그대로
동작한다.

### 13.6 검증 결과(factual)

- 신규 테스트 13건 전부 PASS: `test_run_decision_loop.py`(+4: pre-AI
  기록/Pass2 드롭 전달/cycle 전체 동일값/미제공시 None),
  `test_run_ops_scheduler.py`(+2: argv에 플래그 포함/미제공시 생략),
  `test_validators.py`(+4: context 전달/entity 매핑/end-to-end 저장/
  미제공시 None), `test_postgres_guardrail_evaluations_policy_git_
  sha.py`(+3: INSERT 파라미터 포함/None 허용/policy_git_sha와 동시
  저장).
- 기존 회귀 없음: `test_run_decision_loop.py`(136건),
  `test_run_ops_scheduler.py`/`test_validators.py`/두 repository
  DB-free 파일(171건, 통합 실행).
- `accept backend-file guardrail_evaluations.py` → PASS,
  `accept script-file run_decision_loop.py` → PASS, `accept
  script-file run_ops_scheduler.py` → PASS, `accept style`/`accept
  no-bypass`(hard_bypass_count=0)/`accept architecture`/`accept
  db-structure` 전부 PASS.

### 13.7 미확정

- Postgres 실접속 상태에서 `decision_cycle_id` 컬럼 INSERT가 실제로
  동작하는지는 이번 턴(DB write 금지)에서 미실측 — §12.5와 동일한
  성격의 미확정.
- `_record_scheduler_guardrail_evaluation()`(구 단일-pass 경로,
  `gate_phase=scheduler_gate`)는 이번 턴 범위에 포함하지 않았다 —
  pre-AI gate/Pass 2 drop 두 경로만 필수로 요구됐고, 세 번째 경로까지
  넓히면 범위가 커진다고 판단했다. 다음 턴에서 필요성을 재검토할 수
  있다.
- `trade_decisions`에 동일 개념의 cycle 식별자가 필요해질지(예:
  Stage B에서 "정상 결정과 스킵을 완전히 대칭적으로 조인해야 하는"
  요구가 생기는 경우)는 아직 열려 있다 — 지금은 불필요하다고 판단
  했다.
