# BUY 경로 변수-게이트 전체 매트릭스

작성일: 2026-08-01 KST
상태: 리팩터링 기준선 확정

## 1. 목적

이 문서는 BUY 경로에서 어떤 변수들이 어떤 단계에서 쓰이고, 같은 의미의
정보가 어디서 중복 반영되며, 어떤 조합이 실질 병목으로 변하는지를 한 번에
보이기 위해 작성했다.

이번 분석의 초점은 개별 threshold 튜닝이 아니라 아래 3가지다.

1. 변수별 역할 위치를 전체 funnel 기준으로 매핑한다.
2. 중복은 역할 분리인지, 과잉 누적인지 분류한다.
3. 이후 재설계 우선순위를 `ranking_score` 단독이 아니라 BUY 경로 전체
   관점에서 재정의한다.

## 2. 범위

분석 범위는 아래 BUY 경로로 제한한다.

1. `signal_feature_snapshot`
2. `market_regime`
3. `strategy_selection`
4. `portfolio_allocation`
5. `deterministic_trigger`
6. `buy_candidate`
7. `candidate_vs_final` 및 AI 최종 intent
8. `expected_value_gate`
9. `submit translation` / submit lane

SELL/exit 경로, 관찰용 shadow-only 메타데이터, 장후 attribution 리포트는
이번 문서의 주범위가 아니다. 다만 BUY 판정에 간접 영향을 주는 경우에만
언급한다.

## 3. 코드 기준 BUY funnel

### 3.1 상류 입력

- `signal_feature_snapshot`: `overall_score`, `fast_score`, `slow_score`,
  `atr_14_pct`, `volume_surge_ratio`, `turnover_surge_ratio`,
  `average_volume_20d`, `average_turnover_20d`, `return_3m_pct`,
  `price_vs_sma_60_pct` 등
- `market_regime = classify_market_regime(snapshot)`
- `strategy_selection = select_strategy(market_regime, source_type)`
- `portfolio_allocation = assess_portfolio_allocation(...)`

### 3.2 deterministic BUY 후보

- `entry_score = _build_entry_score(...)`
- `ranking_score = _build_buy_ranking_score(entry_score, portfolio_allocation)`
- `core_risk_off_guard_active = _is_core_risk_off_regime(...)`
- core risk-off guard 통과 여부
- `_assess_buy_eligibility(...)`
- `buy_candidate = eligibility_passed and entry_score >= 0.65 and allocation_budget_ok ...`

### 3.3 하류 확정 및 제출

- `candidate_vs_final`: deterministic 후보와 AI 최종 intent 비교
- `final_intent`
- `expected_value_gate`
- `build_submit_order_request_from_decision()`

## 4. 단계별 역할 정의

| 단계 | 주요 함수/모듈 | 주역할 | 병목 성격 |
|---|---|---|---|
| 신호 생성 | `signal_feature_snapshots` | alpha/risk 원재료 생산 | 상류 |
| 국면 분류 | `market_regime.py` | 위험 상태 라벨링 | 상류 |
| 전략 선택 | `strategy_selection.py` | 선호 전략/보유 horizon 결정 | 중간 |
| 자본 배정 | `portfolio_allocation.py` | 신규 자본 허용량/주문 가능 크기 | 중간 |
| deterministic trigger | `deterministic_trigger_engine.py` | 후보 선별, 하드 게이트 | 핵심 |
| AI 판정 | `decision_orchestrator.py` | 후보 유지/축소/보류 | 하류 |
| EV gate | `expected_value_gate.py` | 비용 반영 기대수익 필터 | 하류 |
| submit translation | `translation.py` | 실제 주문 요청 생성 여부 | 최종 |

## 5. 변수-게이트 전체 매트릭스

| 변수/파생값 | 생성 위치 | 직접 사용 위치 | 역할 | 중복/충돌 판정 |
|---|---|---|---|---|
| `overall_score` | snapshot | `entry_score`(legacy), eligibility `overall >= -0.10`, core risk-off guard `overall >= 0.0`, D안 core ranking 정렬 | alpha + 하드 floor + universe 정렬 | **강한 중복 가능성**. 같은 snapshot 신호가 선별/게이트/유니버스 정렬에 3겹 사용 |
| `fast_score` | snapshot | `entry_score`(legacy) | alpha | 현재 BUY 차단의 직접 병목은 아님 |
| `slow_score` | snapshot | `entry_score`(legacy), eligibility `slow >= -0.15`, core risk-off guard `slow >= -0.05` | alpha + 추세 하드 floor | **중복 가능성 높음**. 완화 여부보다 역할 분리 재정의 필요 |
| `r3b_alpha_percentile` | snapshot/alpha precompute | `entry_score` | alpha 대표값 | 현재 entry 핵심 축. downstream 중복은 `entry_score`를 통해 간접 발생 |
| `market_regime.regime_label` | `classify_market_regime()` | `entry_score`, `strategy_selection`, `portfolio_allocation`, eligibility risk-off/bearish, AI 컨텍스트 | 위험/국면 공통 라벨 | **가장 넓은 반복 축**. soft penalty와 hard gate가 혼재 |
| `market_regime.risk_tone` | same | `entry_score`, `strategy_selection`, `portfolio_allocation`, AI 컨텍스트 | 위험 편향 | **강한 중복 가능성**. 같은 정보가 점수·전략·배정에 연속 주입 |
| `volatility_regime` | same | `portfolio_allocation`, AI 컨텍스트 | sizing/보수성 | 중복은 있으나 직접 BUY 하드 차단은 아님 |
| `preferred_strategy` | `strategy_selection` | `entry_score +0.05`, core risk-off guard 허용 전략 집합, AI 컨텍스트 | 전략 정렬 | **역할 분리 미흡**. bonus와 allowed-set gate 양쪽에 사용 |
| `preferred_time_horizon` | `strategy_selection` | `portfolio_allocation`, AI 컨텍스트 | sizing/설명 | 직접 병목은 약함 |
| `max_new_capital_pct` | `portfolio_allocation` | `entry_score` bonus/penalty, `allocation_budget_ok`, `ranking_score`의 `allocation_quality`, participation/feasibility | 자본 허용량 | **강한 중복**. 점수, 하드 예산, ranking, execution feasibility에 연속 사용 |
| `recommended_max_order_value` | `portfolio_allocation` | eligibility execution feasibility | 실행 가능성 | 정당한 하류 역할 |
| `allocation_budget_ok` | `portfolio_allocation` 파생 | eligibility, `buy_candidate` 최종식 | 예산 하드 게이트 | 정당 |
| `coverage_score` | deterministic trigger | eligibility `coverage >= 0.50` | feature completeness | ranking 직접항은 제거됨. 현재는 **하드 게이트 전용**으로 역할 단순화 |
| `relative_activity_score` | snapshot 파생 | `entry_score` bonus | 미시 유동성 가산 | ranking 직접항 제거 후 중복이 줄었지만 하드 게이트와 여전히 연동 |
| `volume_surge_ratio` / `turnover_surge_ratio` | snapshot | eligibility `>= 1.10`, core risk-off activity floor | 활동성 하드 게이트 | **강한 중복**. 일반 eligibility와 risk-off guard에 동시 사용 |
| `average_volume_20d` / `average_turnover_20d` | snapshot | eligibility absolute liquidity floor, EV cost inputs | 유동성/비용 | 역할 분리 존재. 다만 BUY 선별과 비용 산정 사이 의미 중첩 가능 |
| `entry_score` | deterministic trigger | `buy_candidate threshold 0.65`, `ranking_score`, 여러 분석/메타데이터 | alpha 대표 종합점수 | **핵심 중복 축**. BUY 후보 조건과 ranking_score의 기초값을 동시에 담당 |
| `ranking_score` | deterministic trigger | core risk-off guard, event shadow 관찰 | 예외적 상황의 추가 우선순위/차단 | 현재는 사실상 `entry_score + allocation_quality`의 축약형. 독립 설명력 약함 |
| `expected_value_gate` 입력군 | snapshot + decision context | EV gate, submit translation anchor | 비용 반영 기대수익 | deterministic BUY 이후 하류 병목. 상류 신호와 cadence mismatch 이력 있음 |
| `final_intent` | AI | submit translation | 최종 의사결정 | deterministic과 독립이어야 하나 실제로는 상류 컨텍스트 반복 반영 가능 |

## 6. 현재 `ranking_score`의 의미 축소

최근 정리 후 `ranking_score` 산식은 아래와 같다.

```text
ranking_score = 0.55 * entry_score + 0.10 * allocation_quality
```

이는 아래 사실을 뜻한다.

1. `ranking_score`는 더 이상 독립 alpha 조합식이 아니다.
2. 본질적으로 `entry_score`의 축약 복사본에 `allocation_quality`를 조금
   더한 값이다.
3. 그런데 이 값이 core risk-off guard에서 다시 하드 threshold로 쓰이면,
   `entry_score`로 한 번 선별한 뒤 거의 같은 축으로 다시 막는 구조가 된다.

즉 현재 `ranking_score`의 가장 큰 문제는 "가중치가 틀렸는가" 이전에
**독립 역할이 충분히 남아 있는가**다.

## 7. 중복/충돌 분류

### 7.1 정당한 역할 분리로 볼 수 있는 항목

- `coverage_score`
  - 현재는 ranking에서 제거되고 eligibility 하드 게이트로만 남았다.
  - 동일 정보의 다중 처벌 구조는 상당 부분 해소됐다.
- `recommended_max_order_value`
  - 점수화가 아니라 순수 execution feasibility 축이다.
- `expected_value_gate`
  - deterministic BUY 이후 비용 반영 하류 게이트라는 역할 자체는 분리돼 있다.

### 7.2 과잉 누적 가능성이 높은 항목

- `entry_score` → `ranking_score`
  - 같은 alpha 종합점을 후보 조건과 risk-off guard 양쪽에 재사용
- `market_regime`
  - `entry_score` soft penalty
  - `strategy_selection` defensive preference
  - `portfolio_allocation` cap 축소
  - eligibility `risk_off + bearish_trend` hard gate
- `portfolio_allocation.max_new_capital_pct`
  - `entry_score` 보너스/패널티
  - `allocation_budget_ok`
  - `ranking_score`
  - participation/feasibility
- `relative_activity` 계열
  - `entry_score` bonus
  - eligibility activity hard gate
  - core risk-off activity hard gate
- `preferred_strategy`
  - `entry_score` bonus
  - core risk-off allowed strategy gate

### 7.3 구조적 충돌 가능성이 있는 항목

- alpha와 risk가 같은 축에서 혼합되는 문제
  - `entry_score`는 alpha 점수여야 하는데 국면 penalty, allocation bonus,
    strategy bonus, activity bonus가 함께 섞여 있다.
- selection과 feasibility의 경계 불분명
  - `portfolio_allocation`과 `relative_activity`가 후보 선별 점수와
    실행 feasibility 양쪽에 동시에 관여한다.
- `ranking_score`의 용도 축소
  - 독립적 우선순위화 공식이 아니라 이미 정해진 `entry_score`의 재가공값에
    가까운데, 여전히 guard threshold로 쓰인다.

## 8. BUY 경로 단계별 핵심 해석

### 8.1 상류

상류는 snapshot과 regime이 사실상 모든 downstream 판단의 공통 원천이다.
문제는 여기서 생성된 정보가 아래 단계마다 다른 이름으로 재사용된다는
점이다.

### 8.2 deterministic BUY 후보

현재 가장 복잡한 중복은 이 구간에 집중된다.

1. `entry_score`가 alpha, risk, allocation, activity, strategy를 한 점수에
   섞는다.
2. `ranking_score`는 그 결과를 다시 압축해 risk-off guard에 투입한다.
3. eligibility는 다시 `overall/slow/activity/liquidity/allocation`을 하드
   게이트로 한 번 더 본다.

즉 **후보 선별, 위험 제한, 실행 가능성 판단이 한 레이어에 과밀하게 섞여
있다.**

### 8.3 AI 이후 하류

AI downgrade, EV gate, submit translation은 별도 축이지만, 이미 상류에서
강하게 걸러진 후보만 내려오기 때문에 "하류가 너무 보수적인가"를 보기 전에
상류 deterministic 경로의 의미 분리가 먼저 필요하다.

## 9. 현재 기준 1차 판정

### 9.1 가장 설명력이 큰 구조 문제

1. `entry_score`와 `ranking_score`의 역할 중복
2. `market_regime`의 soft/hard 다중 주입
3. `portfolio_allocation`의 score/gate/feasibility 삼중 역할
4. `relative_activity`의 bonus + hard gate 이중/삼중 사용

### 9.2 지금 당장 threshold보다 먼저 볼 것

1. `ranking_score`를 독립 순위화 공식으로 유지할지, 아니면 core risk-off
   guard의 보조 입력으로 축소할지
2. `entry_score`에서 alpha 외 보정 항목을 얼마나 분리할지
3. `portfolio_allocation`을 선별 점수에 넣는 것이 맞는지, 아니면 execution
   feasibility 전용으로 내릴지
4. `relative_activity`를 bonus로 둘지, hard gate로만 둘지

**[2026-08-01 KST 갱신] §9.2의 1번(`ranking_score` 유지/축소 여부)은
13.1.1에서 판정 C(제거/대체)로 닫혔다** — "유지할지 축소할지"라는 열린
질문이 아니라 대체 방향으로 확정됐다. 2~4번은 R2~R4의 별개 질문으로
남아 있으며 이번 갱신의 범위가 아니다.

## 10. 다음 분석 우선순위

1. `entry_score` 내부 보정항(`market_regime`, `strategy`, `allocation`,
   `relative_activity`)의 유지/이관/제거 분류
2. `ranking_score`를 "독립 우선순위화 공식"으로 다시 설계할지 여부 판단
3. `portfolio_allocation` 계열을 BUY 후보 점수에서 분리할지 검토
4. activity 계열을 soft bonus와 hard gate 중 어느 한쪽으로 축소할지 검토
5. AI downgrade/EV gate와 deterministic 상류 변수의 중복 컨텍스트 주입 여부
   별도 점검

## 11. 결론

현재 BUY 경로의 핵심 문제는 단일 threshold가 아니다. 더 근본적인 문제는
**같은 의미의 변수들이 alpha, risk, allocation, execution feasibility라는
서로 다른 역할로 충분히 분리되지 않은 채 여러 단계에서 재사용되는 구조**
다.

따라서 다음 단계는 "`몇 점을 낮출까`"보다 아래 순서가 맞다.

1. 변수별 역할을 다시 고정한다.
2. 역할이 겹치는 변수는 한 레이어로 모은다.
3. 그 뒤에 남는 threshold만 재측정한다.

## 12. 다음 단계 연결

이 문서는 구조 분석의 기준선이다. 실제 리팩터링은 바로 시작하지 않고,
먼저 아래 사전 검토 일정 문서를 따라 확인·검토 작업을 진행한다.

- `docs/20_system_analysis/buy_path_refactor_pre_roadmap_schedule.md`

즉 현재 순서는 다음과 같다.

1. 이 문서로 구조 문제를 고정
2. 사전 검토 일정에 따라 변수 역할/계약/상하류 경계를 확인
3. 그 다음에 Roadmap 작성
4. 마지막으로 최소 단위 diff 착수

## 13. 리팩터링 단위 초안

코드를 한 번에 갈아엎지 않고, 아래 단위로 쪼개는 것이 해석 가능성과
회귀 통제 측면에서 가장 안전하다.

### 13.1 R1 — `ranking_score` 역할 축소/대체

- 범위:
  - `ranking_score`를 독립 선별 공식으로 유지할지
  - 아니면 `core_risk_off guard` 보조 입력으로 축소할지
  - 혹은 `entry_score` 재사용을 없애고 별도 우선순위화 계층으로 대체할지
- 핵심 질문:
  - 지금 `ranking_score = 0.55 * entry_score + 0.10 * allocation_quality`
    가 별도 의미를 가지는가
  - guard threshold가 사실상 `entry_score` 2차 처벌인지
- 우선순위: **1순위**

**선행 확정 사실(이미 닫힘)**: 이 R1은 "새로 발견한 문제"가 아니라,
아래 사실이 이미 확정된 상태에서 남은 두 항만 판단하는 좁혀진 질문이다.

- `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §144~146(SPPV-2.157/2.158/2.159)에서:
  - `regime_tailwind`(0.03) 항은 이미 제거됨(코드 diff 반영 완료)
  - `ranking_score`의 실제 소비 경로가 `core_risk_off guard`와
    `event_overlay shadow` 두 곳뿐임이 전수 검증됨
  - 위 두 소비 경로 모두 `regime_tailwind` 제거로 실질 영향이 없거나
    범위 밖(shadow-only)임이 판정됨

따라서 R1의 실제 남은 범위는 `ranking_score`에서 이미 정리된 `regime_
tailwind`를 다시 다루는 것이 아니라, **남은 두 항(`entry_score`,
`allocation_quality`)의 존치·재정규화·대체 여부**로 한정된다.

#### 13.1.1 R1 결론(2026-08-01 KST 2차 확인) — **판정 C(제거/대체)**

**새로 확인한 사실**: `allocation_quality`가 `ranking_score`에 더하는
정보량을 코드 수준에서 직접 계산해 대조했다.

```text
entry_score의 자체 allocation 항(_build_entry_score):
  pct > 0 : + min(0.10, pct/100)
  pct <= 0: - 0.20

ranking_score의 allocation_quality 항(_build_buy_ranking_score):
  allocation_quality = clamp(pct/10, 0, 1)
  기여분 = 0.10 * allocation_quality
```

이 두 식을 `pct ∈ {1,3,5,8,10,15,30,100}`에서 직접 계산해 대조한 결과
(read-only 코드 확인, DB/외부 호출 없음), **`pct > 0`인 전 구간에서
`entry_score`의 자체 allocation 항과 `ranking_score`의 `allocation_
quality` 기여분이 소수점까지 정확히 일치**했다. `pct <= 0`에서는
`entry_score`가 이미 `-0.20` 페널티를 반영하고 `allocation_quality`는
`0`이 되어, `ranking_score` 쪽이 추가 정보를 주지 않는다(오히려
`entry_score`가 이미 신호를 담고 있다).

**결론**: `ranking_score = 0.55*entry_score + 0.10*allocation_quality`의
**두 항 모두 독립적인 추가 정보가 없다.**

1. `entry_score` 항 — 정의상 `entry_score`의 재사용(0.55배 스케일).
2. `allocation_quality` 항 — `entry_score`에 이미 담긴 동일한
   `max_new_capital_pct` 신호를 **완전히 동일한 형태로 한 번 더** 반영
   (같은 원본 값을 서로 다른 두 채널로 이중 계상).

이는 `coverage_score`(SPPV-2.137)·`strategy_alignment`(SPPV-2.146)·
`regime_tailwind`(SPPV-2.157/159)에서 이미 확인·제거한 **동일한 이중
계상 패턴**이며, 제거 전례와 일치한다.

**Q1 답 — 독립 순위화 공식으로 볼 여지**: 없다. 두 항 모두 `entry_score`
에서 파생되거나 이미 반영된 신호의 재적용이다.

**Q2 답 — `allocation_quality`의 BUY 경로 내 위치**: `ranking`(이
항 자체), `entry_score`의 자체 allocation 항(중복 원본),
`allocation_budget_ok`(하드 게이트), `recommended_max_order_value`
기반 execution feasibility — **최소 4곳에서 같은 `max_new_capital_pct`
가 재사용**되며, 이 중 `ranking`과 `entry_score` 두 곳은 수치까지
동일해 순수 중복이다.

**Q3 답 — 유지해야 한다면 어떤 역할인가**: 해당 없음(유지 근거 없음).

**Q4 답 — 제거/대체 이유 중 가장 큰 것**: **"독립 설명력 부재"가 근본
원인**이고, 그 구체적 기전이 "`entry_score` 2차 처벌"(같은 값을
0.55배로 다시 문턱질)과 "allocation 중복"(같은 신호를 형태까지 동일하게
재적용) **둘 다**다 — 어느 하나가 아니라 두 기전이 동시에 성립한다.

**Q5 답 — R2 선행 확인 필요 여부**: **불필요.** R1의 대체 대상은
`core_risk_off guard`(0.28/0.02/0.26)와 `event_overlay shadow`(0.56)
**두 곳이 참조하는 스칼라를 `ranking_score`에서 `entry_score`(재정규화된
threshold)로 바꾸는 것**이며, `entry_score` 내부 구조(R2의 대상)는
건드리지 않는다. R2는 `entry_score` 자체의 alpha/risk/sizing 내부 분리를
다루는 별개 질문이라, R1의 diff 설계와 독립적으로 진행할 수 있다.

**최종 판정: C — `ranking_score` 제거/대체가 맞다. 다음 턴은 대체
contract 설계 검토(diff 초안이 아니라 설계 검토)다.**

대체 방향의 골격만 기록한다(설계 확정은 다음 턴):
- `core_risk_off guard`(0.28/0.02/0.26)와 `event_overlay shadow`(0.56)
  두 소비 지점이 `entry_score`를 직접 참조하도록 바꾸고, threshold를
  `÷0.55` 비율로 재정규화하는 것이 무변화 리팩터링 원칙과 부합하는
  1차 후보다(코드 diff 전 재검증 필요).
- `ranking_score` 필드 자체를 완전히 제거할지, 관찰용으로만 남길지는
  하류 소비자(예: `trigger_proxy_attribution.py`의 관찰용 참조)에 대한
  영향 확인이 diff 설계 단계에서 필요하다.

### 13.2 R2 — `entry_score`의 alpha / risk / sizing 분리

- 범위:
  - `entry_score`에서 alpha 외 보정항(`market_regime`, `preferred_strategy`,
    `allocation`, `relative_activity`)을 유지/이관/제거로 분류
- 핵심 질문:
  - `entry_score`가 alpha 대표점수로 남아야 하는지
  - 아니면 risk/sizing 보정을 밖으로 밀어내야 하는지
- 우선순위: **2순위**

### 13.3 R3 — `portfolio_allocation`의 역할 분리

- 범위:
  - `max_new_capital_pct`, `allocation_budget_ok`,
    `recommended_max_order_value`를
    점수/하드게이트/실행 feasibility로 분리
- 핵심 질문:
  - sizing 정보가 후보 점수에 들어가는 것이 맞는지
  - execution feasibility 전용으로 내리는 것이 맞는지
- 우선순위: **3순위**

### 13.4 R4 — activity 계열의 soft/hard 중복 정리

- 범위:
  - `relative_activity_score`
  - `volume_surge_ratio`, `turnover_surge_ratio`
  - `average_volume_20d`, `average_turnover_20d`
- 핵심 질문:
  - bonus와 hard gate를 동시에 유지할 이유가 남아 있는지
  - risk-off guard와 일반 eligibility의 activity 중복을 줄여야 하는지
- 우선순위: **4순위**

### 13.5 R5 — 하류 contract 정리

- 범위:
  - `candidate_vs_final`
  - `expected_value_gate`
  - `submit translation`
- 핵심 질문:
  - 상류에서 제거된 변수 의미가 하류에서 다시 암묵적으로 주입되는지
  - 상류 리팩터링 뒤 하류 contract를 같이 손봐야 하는지
- 우선순위: **5순위**

### 13.6 이번 리팩터링 범위 밖

- SELL/exit 공식 재설계
- 관찰용 shadow 메타데이터 정리
- LLM 프롬프트 자체 재작성
- 브로커/KIS 경로 변경
- threshold 미세조정만을 목적으로 한 단독 변경

### 13.7 현재 권장 착수 순서

1. **R1**: [2026-08-01 KST 갱신] 판정 완료(C, 13.1.1) — 다음은 대체
   contract 설계 검토(diff 초안 아님)
2. **R2**: `entry_score`를 alpha 중심으로 재정렬할지 판단
3. **R3/R4**: allocation/activity를 점수 밖으로 내릴지 검토
4. **R5**: 상류 결정 이후 하류 연쇄 영향 확인

즉 현재는 "BUY 경로 전체 리팩터링"이라는 이름보다,
**R1(판정 완료)→R2→R3/R4→R5의 단계적 리팩터링**으로 보는 것이 정확하다.
