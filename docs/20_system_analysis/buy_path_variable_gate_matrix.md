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

**[2026-08-02 KST 표현 보정]** 위 2번의 "완전히 동일한 형태로 재적용"은
표현이 다소 강하다. 이번 턴 재확인 결과, `pct > 0` 구간에서는 두 항이
수치까지 일치하지만 `pct <= 0` 구간에서는 그렇지 않다(§13.1.2 참고).
따라서 이후로는 **"동일 원신호(`max_new_capital_pct`)의 중복 반영"**
으로 표현한다 — 전 구간에서 완전히 동일하다는 뜻이 아니라, 같은
원신호가 두 채널(엔트리 자체 항 + ranking의 allocation_quality 항)에
중복 반영된다는 뜻이다.

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
`core_risk_off guard`/`event_overlay shadow` 소비 지점이 참조하는
스칼라를 `ranking_score`에서 `entry_score`(재정규화된 threshold)로
바꾸는 것이며, `entry_score` 내부 구조(R2의 대상)는 건드리지 않는다.
R2는 `entry_score` 자체의 alpha/risk/sizing 내부 분리를 다루는 별개
질문이라, R1의 diff 설계와 독립적으로 진행할 수 있다. **[2026-08-02
KST 정정] "0.28/0.02/0.26"을 모두 같은 성격의 게이트처럼 썼으나, 이는
부정확하다 — §13.1.2에서 이 셋의 authoritative/shadow 구분을 다시
확정했다.**

**최종 판정: C — `ranking_score` 제거/대체가 맞다. 다음 턴은 대체
contract 설계 검토(diff 초안이 아니라 설계 검토)다.**

대체 방향의 골격만 기록한다(설계 확정은 다음 턴): [2026-08-02 KST
갱신] 아래 골격은 §13.1.2의 상세 설계 비교로 대체됐다.

### 13.1.2 R1 대체 contract 설계 비교(2026-08-02 KST, read-only 설계 검토)

**목적**: R1(판정 C)을 실제 diff로 착수 가능한 수준까지 좁힌다. 이번
절은 설계안 비교까지만 하며, 코드는 변경하지 않는다.

**전제(이미 닫힌 사실, 재검증하지 않음)**: `regime_tailwind` 제거
(SPPV-2.157/2.158/2.159), `strategy_alignment`/`coverage_score` 제거
(SPPV-2.146/2.137), R1 판정 C(§13.1.1) — 전부 참조만 하고 다시
검증하지 않는다.

#### (1) `ranking_score` 소비처 재확정 — authoritative / shadow / reporting

**새로 확인한 사실**: 지난 턴(§13.1.1)에서 "실제 게이트는
`core_risk_off guard`(0.28/0.02/0.26)와 `event_overlay shadow`(0.56)
두 곳"이라고 뭉뚱그려 썼는데, 이번 턴에 `_assess_core_risk_off_buy_
guard()`와 `_build_core_risk_off_shadow_experiment_metadata()`를 다시
읽어 **그 안에서도 authoritative와 shadow가 섞여 있음**을 확인했다.

| 소비처 | 함수 | threshold | 성격 | 실제 BUY 판정에 영향 |
|---|---|---|---|---|
| core risk-off 진짜 게이트 | `_assess_core_risk_off_buy_guard()` | `_CORE_RISK_OFF_RANKING_MIN_SCORE = 0.28` | **authoritative** | **예** — `risk_off_exception_eligible`을 결정, `_assess_buy_eligibility()`가 이 값으로 실제 eligibility를 가른다 |
| core risk-off shadow 관찰 | `_build_core_risk_off_shadow_experiment_metadata()` | `_CORE_RISK_OFF_SHADOW_MIN_SCORE = 0.02`, 그리고 `_classify_core_risk_off_shadow_floor_bucket()` 내부의 `0.26`(및 v2/v3/v5 변형) | **shadow(관찰용)** | 아니오 — `shadow_topk_candidate`/`shadow_floor_bucket` 등은 `decision_json`에만 기록되고, `risk_off_exception_eligible`은 외부에서 주입되는 `core_risk_off_topk_v1` override(운영자가 별도로 넣는 값)로만 갈린다. 이 shadow 계산 자체가 그 override 값을 만들어내지 않는다 |
| event_overlay shadow 관찰 | `_build_event_overlay_shadow_metadata()` | `_EVENT_OVERLAY_SHADOW_MIN_SCORE = 0.56` | **shadow(관찰용)** | 아니오 — `mode="no_bonus_v1"`, `shadow_would_pass`가 어디에도 승격되지 않음(기존 SPPV-2.157 결론 유지, 재검증 안 함) |
| 저장/직렬화 | `decision_factory.py:352-353` | 없음 | **plumbing(저장 경로)** | 게이트가 아니라 `decision_json.deterministic_trigger.ranking_score` 필드에 값을 옮겨 담는 지점 |
| 장후 attribution 리포트 | `trigger_proxy_attribution.py`(다수 지점, 자체 threshold `BUY_MIN_RANKING_SCORE`/`WATCH_MIN_RANKING_SCORE`/`0.26` 등 보유) | 독립적인 자체 threshold | **reporting(외부 관찰)** | 아니오 — `scripts/analyze_trigger_proxy_attribution.py`를 통해 실행되며 **DB write·`repos` 사용 없이 JSON 리포트 파일만 생성**함을 이번 턴에 확인. 이미 결정된 `trade_decisions`를 사후 집계하는 도구라 판정에 되먹임되지 않는다 |

**정정**: §13.1.1에서 "0.28/0.02/0.26"을 한 묶음처럼 썼던 것은 부정확
했다 — **authoritative는 `0.28` 하나뿐이고, `0.02`/`0.26`(및 v2/v3/v5)
은 shadow(관찰용)다.** `0.56`(event_overlay)은 기존 판정대로 shadow.

#### (2) `entry_score` 직접 대체의 수학적 보존 가능성

**새로 확인한 사실**: `ranking_score`와 `0.55*entry_score`의 차이를
전 구간에서 계산했다.

```text
ranking_score - 0.55*entry_score = 0.10 * allocation_quality(pct)

pct <= 0 : allocation_quality = 0        → 차이 = 0 (완전 보존)
pct >  0 : allocation_quality ∈ (0, 1]   → 차이 ∈ (0, 0.10] (편차 발생)
```

즉 `max_new_capital_pct <= 0`인 경우(신규 자본 배정이 없거나 예산 초과)
`ranking_score`는 `0.55*entry_score`와 **완전히 동일**하다. 편차가
생기는 것은 `pct > 0`일 때뿐이며, 그 편차는 **항상 0 이상 0.10 이하**로
한쪽 방향(ranking_score가 항상 더 높거나 같음)으로만 발생한다.

**이전 제거 사례와의 차이(중요)**: `coverage_score`(SPPV-2.137) 제거
때는 게이트를 통과한 모집단에서 그 값이 항상 `1.0`인 **상수**였기 때문에
threshold에서 정확히 같은 상수를 빼는 것으로 경계가 수학적으로 완전히
보존됐다. 이번 `allocation_quality`는 **상수가 아니라 `pct`에 따라
0~0.10 사이를 움직이는 변수**다. 따라서 `threshold ÷ 0.55` 같은 단순
재정규화는 **근사치일 뿐 경계를 완전히 보존하지 못한다** — `ranking_
score`가 `[0.28, 0.38]` 구간에 있으면서 그 이유가 순전히 `allocation_
quality` 덕분이었던 후보는, `entry_score` 단독 기준으로 재정규화한
threshold를 적용하면 판정이 바뀔 수 있다(운영 데이터 기반 실측이
diff 이전에 필요하다는 뜻이며, 이번 턴은 그 실측을 하지 않았다).

#### (3) 대체안 비교(A/B/C)

| 축 | A안: `entry_score` 직접 대체(필드 제거) | B안: 경량 별도 score 유지 | C안: authoritative만 교체 + 관찰용 잔존 |
|---|---|---|---|
| 정의 | `ranking_score` 계산·필드 자체를 없애고, 모든 소비처가 `entry_score`를 직접 참조 | `ranking_score` 필드는 유지, 공식만 경량화(예: `allocation_quality` 항 삭제, `0.55*entry_score`만 남김) | `ranking_score` 계산·공식은 **그대로 유지**하고, `0.28` 게이트만 `entry_score`(재정규화 threshold)를 참조하도록 교체 |
| 실제 BUY 판정 영향 범위 | `0.28` 게이트 1곳(유일한 authoritative) | `0.28` 게이트 1곳 | `0.28` 게이트 1곳(동일) |
| threshold 재정규화 필요 | 예, 필수(위 (2)의 근사치 한계 있음) | 예, 필수(공식이 바뀌므로) | 예, 필수(대상은 여전히 1곳뿐) |
| guard/shadow/metadata 영향 | shadow 메타데이터(`0.02`/`0.26`류, `0.56`)가 `ranking_score`를 참조하므로 **함께 재설계 필요** — 영향이 shadow까지 번짐 | 필드명이 그대로라 shadow 코드는 수정 불필요하나, **계산된 값 자체가 바뀌어 shadow threshold의 의미도 함께 이동**(재검증 필요) | **없음** — `ranking_score` 계산이 그대로라 shadow/이벤트 오버레이 쪽은 100% 무변화 |
| 하위 호환(reporting) | `trigger_proxy_attribution.py`가 참조하는 `decision_json.ranking_score` 필드가 사라져 **스크립트 수정 필요**(판정과 무관, 리포트 품질 문제) | 필드는 유지되나 값의 스케일이 바뀌어 **리포트 수치가 이동**(스크립트 수정은 불필요, 해석만 달라짐) | **완전 보존** — 계산이 그대로라 리포트 스크립트·수치 모두 무변화 |
| diff 난이도 | 높음(authoritative + shadow + reporting 다수 파일) | 중간(함수 1개 + 연쇄된 threshold 재조정, 소비자 코드는 안 건드림) | **가장 낮음**(함수 1개, 게이트 참조 대상 교체 + threshold 1개 재조정) |
| R1 결론(§13.1.1, "두 항 모두 독립 정보 없음")과의 정합성 | 정합적(무의미해진 필드를 완전히 걷어냄) | **낮음** — 독립 정보가 없다고 결론 낸 개념을 별도 필드로 계속 유지하는 것이라 결론과 다소 배치 | 정합적(개념은 남기되 그 개념이 실제 판정에 영향을 주는 지점만 정리) |

#### (4) 관찰용 소비자(`trigger_proxy_attribution.py` 등) 분리 판단

- **실제 판정에 영향 없음**: 위 (1)에서 확인. DB write·`repos` 사용이
  없고, 장후 별도 스크립트(`analyze_trigger_proxy_attribution.py`)로
  실행돼 JSON 리포트만 생성한다. `trade_decisions`/`order_requests`에
  되먹임되는 경로가 없다.
- **필드 제거 시 문제 성격**: A안을 택할 경우 이 스크립트가 참조하는
  `row.get("ranking_score")`가 `None`이 되어 리포트 값이 누락된다 —
  이는 **보고 품질 저하 문제**이지 BUY 판정 오류가 아니다.
- **계약 유지가 꼭 필요한가**: 이번 턴 기준으로는 **강제할 필요는
  없다**(판정에 영향이 없으므로) — 다만 이 스크립트가 SPPV 연구
  분석(예: SPPV-2.149의 D안 사후 검증, `trigger_proxy_attribution_
  *.json` 파일 기반 리포트)에 쓰이고 있어, 완전히 끊으면 **연구 연속성
  비용**이 발생한다. 이 비용은 diff 설계 단계에서 "필드를 유지한 채
  값만 재정의"(B/C안) 대비 "필드를 없애고 스크립트를 별도로 손보기"
  (A안) 사이의 트레이드오프로 반영해야 한다.

#### (5) 결론 — 1순위 권고안

**C안(authoritative만 교체 + 관찰용 잔존)을 권고한다.**

근거:
1. **BUY 판정 영향 범위, threshold 재정규화 필요성은 A/B/C 모두
   동일**(대상이 `0.28` 게이트 1곳뿐이므로) — 이 축은 안 선택에
   차별점이 안 된다.
2. **guard/shadow/metadata 영향과 하위 호환에서 C안만 완전 무변화**다
   — shadow 메타데이터·`event_overlay` shadow·`trigger_proxy_
   attribution.py` 전부 코드 수정이 필요 없다.
3. **diff 난이도가 가장 낮다** — 변경 범위가 `_assess_core_risk_off_
   buy_guard()` 호출부에서 참조하는 스칼라 하나와 그에 딸린 threshold
   재조정으로 한정된다.
4. R1의 결론("두 항 모두 독립 정보 없음")과 **정합적**이다 —
   `ranking_score`라는 개념 자체를 없애지는 않되(B안처럼 억지로
   유지하지도 않되), 그 개념이 실제 판정에 영향을 주는 유일한 지점만
   정리한다.

**"다음 턴에서 바로 diff 초안 가능한가" 판정**: **부분적으로 가능,
전제 조건 있음.** 코드 변경 범위(1개 함수, 1개 게이트 참조 교체)는
바로 diff 착수가 가능한 수준으로 좁혀졌다. 다만 (2)에서 확인한 대로
`entry_score` 재정규화 threshold가 **단순 상수 차감으로 완전히
보존되지 않는 근사치**이므로, diff 전에 **운영 데이터에서 `pct>0`이면서
`ranking_score ∈ [0.28, 0.38]` 구간에 걸린 실제 사례가 얼마나 있는지
read-only 실측**이 한 차례 더 필요하다(이번 턴에서는 수행하지 않음 —
DB 조회는 이번 턴 범위 밖이었다). 그 실측 결과 해당 구간의 사례가
0건이거나 무시할 수준이면 다음 턴에 바로 diff 초안으로 갈 수 있고,
유의미한 규모면 threshold 재산정 방법을 먼저 정해야 한다.

### 13.1.3 R1 — `ranking_score ∈ [0.28, 0.38]` 구간 실측 검증(2026-08-02 KST, read-only)

**목적**: §13.1.2 (5)에서 남긴 "diff 착수 전 운영 데이터 실측 필요"
전제 조건을 닫는다. 이번 절은 C안 착수 여부 판정을 위한 마지막 실측이며,
코드는 변경하지 않았다.

**조회 방법**: `trading_db`(PostgreSQL) 컨테이너에 read-only `SELECT`로
직접 접속해 `trading.trade_decisions.decision_json`에서
`deterministic_trigger.entry_score`, `deterministic_trigger.ranking_score`,
`deterministic_trigger.metadata.core_risk_off_guard_active`,
`portfolio_allocation.max_new_capital_pct`를 추출했다. `side='buy'`
필터만 적용했고, DB write·KIS 호출·코드 수정은 하지 않았다.

**모집단 정의**: `core_risk_off_guard_active=true`
그리고 `ranking_score ∈ [0.28, 0.38]`
그리고 `entry_score`, `portfolio_allocation.max_new_capital_pct`가
둘 다 존재하는 표본.

**집계 창별 비교표**(KST 거래일 기준):

| 집계 창 | 건수 | distinct symbol | 비고 |
|---|---|---|---|
| 최근 3거래일(07-29~07-31) | 191 | 4 | 07-29: 149건/3종목, 07-30: 42건/1종목, **07-31: 0건**(이 구간 표본 없음) |
| 최근 1개월(07-02~07-31, 달력 기준) | 2,385 | 13 | |
| 전체 이력(실제 관측 범위 2026-06-29~2026-07-30) | 2,455 | 13 | 전체 이력 최대 거래일도 07-30이며, 07-31에는 이 좁은 구간에 해당하는 표본이 원래 없다 |

**`allocation_quality` 분포**: 전체 2,455건에서 `max_new_capital_pct`
값은 **`2.5` 단일값**이었다(distinct 값 개수 1). 따라서
`allocation_quality = clamp(pct/10) = 0.25`로 전 구간에서 상수이며,
분포라고 부를 만한 퍼짐이 없다 — 이 좁은 `ranking_score` 구간 모집단
안에서는 자본 배정 여유도가 실질적으로 다양하지 않았다는 뜻이다.

**`ranking_score - 0.55*entry_score` 분포**: 최소 `0.2249`, 최대
`0.2933`, 평균 약 `0.235`(3거래일 구간은 `0.2249~0.2251`로 더 좁음).
이 편차는 `0.10*allocation_quality(=0.025)`보다 뚜렷하게 크다.
**새로 확인한 사실**: 이 편차는 §13.1.2 (2)에서 가정한
`0.10*allocation_quality` 단독으로는 설명되지 않으며, 이번 표본의
`ranking_score`가 이미 닫힌 `relative_activity`/`coverage_score`/
`strategy_alignment`/`regime_tailwind` 제거 diff(SPPV-2.133/2.138/
2.147/2.159)가 **실제 매매일에 전부 반영되기 전 시점의 값**을 담고
있기 때문으로 보인다 — `git log`로 확인한 각 제거 commit 시각은
2026-07-29 12:35 KST, 2026-07-30 12:59 KST, 2026-07-30 21:06 KST,
2026-08-01 19:44 KST이며, 마지막 두 건은 이번 모집단의 마지막 거래일
(07-30, 그리고 07-31은 이 구간 표본 자체가 0건)의 장중 시각보다
뒤에 반영됐다. **개별 항목(`regime_tailwind`/`strategy_alignment`/
`coverage_score`)의 제거 타당성 자체는 이미 닫힌 논의이므로 이번
턴에서 재검토하지 않는다** — 여기서는 "이 표본의 `ranking_score`가
어느 시점의 공식값을 담고 있는지"라는 해석 전제만 기록한다.
이 매핑이 정확히 어느 조합으로 0.2249~0.2933 범위를 만드는지는
**이번 턴에서 미확인**이다.

**대체 threshold 후보(§13.1.2 (2)의 근사 재정규화) 실측**: 후보
threshold `0.28 / 0.55 ≈ 0.5091`을 그대로 적용하면(즉 `entry_score
>= 0.5091`을 authoritative 게이트로 직접 대체) —

| 집계 창 | 표본 수(A) | 대체 threshold 통과 수(B) | 뒤집힘 수(A-B) | 뒤집힘 비율 |
|---|---|---|---|---|
| 최근 3거래일 | 191 | 0 | 191 | 100% |
| 최근 1개월 | 2,385 | 0 | 2,385 | 100% |
| 전체 이력 | 2,455 | 0 | 2,455 | 100% |

이 모집단의 `entry_score` 최댓값은 `0.2123`으로, 대체 threshold
`0.5091`에 전혀 도달하지 못한다. 즉 **이 좁은 구간 안에서는
"동일 원신호 중복 반영"으로 인해 지금은 `ranking_score`가 게이트를
통과시키지만, `threshold ÷ 0.55` 단순 재정규화를 그대로 쓰면 전량
(3거래일/1개월/전체 이력 모두 100%) 뒤집힌다.**

**상위 10개 표본**(distinct `symbol`+거래일 기준, `ranking_score` 내림차순):

| symbol | 거래일(KST) | ranking_score | entry_score | max_new_capital_pct | allocation_quality | 현재 authoritative 판정(`ranking_score` 게이트) | 대체 시 판정(`entry_score>=0.5091`) |
|---|---|---|---|---|---|---|---|
| 000210 | 2026-07-24 | 0.3791 | 0.1929 | 2.5 | 0.25 | 통과 | 차단 |
| 000100 | 2026-07-27 | 0.3776 | 0.2123 | 2.5 | 0.25 | 통과 | 차단 |
| 000210 | 2026-07-15 | 0.3670 | 0.1463 | 2.5 | 0.25 | 통과 | 차단 |
| 002030 | 2026-07-10 | 0.3601 | 0.1773 | 2.5 | 0.25 | 통과 | 차단 |
| 001680 | 2026-07-27 | 0.3596 | 0.2121 | 2.5 | 0.25 | 통과 | 차단 |
| 000150 | 2026-07-15 | 0.3509 | 0.1048 | 2.5 | 0.25 | 통과 | 차단 |
| 001680 | 2026-07-28 | 0.3325 | 0.1855 | 2.5 | 0.25 | 통과 | 차단 |
| 002840 | 2026-07-16 | 0.3317 | 0.1253 | 2.5 | 0.25 | 통과 | 차단 |
| 000080 | 2026-07-27 | 0.3299 | 0.1839 | 2.5 | 0.25 | 통과 | 차단 |
| 000080 | 2026-07-28 | 0.3190 | 0.1710 | 2.5 | 0.25 | 통과 | 차단 |

"현재 authoritative 판정"은 `_assess_core_risk_off_buy_guard()`의
`ranking_score >= 0.28` 1차 게이트 통과 여부만을 가리킨다(이 표본은
정의상 전부 이 게이트를 통과한다). `risk_off_exception_eligible` 최종
판정에 필요한 `overall`/`slow`/활동성/전략 조건은 이번 턴 조회 범위
밖이라 확인하지 않았다.

**C안 착수 가능 여부에 대한 이번 턴 결론**: §13.1.2 (2)에서 예고한
"단순 재정규화는 근사치일 뿐 경계를 완전히 보존하지 못한다"는 우려가
실측으로 확인됐다 — 그것도 근사 오차 수준이 아니라 **이 구간 표본
전량이 뒤집히는 수준**이다. 따라서 `threshold ÷ 0.55`를 그대로 쓰는
C안 diff는 **이 상태로는 착수할 수 없다**. C안 자체(authoritative
게이트 1곳만 `entry_score` 참조로 교체)의 구조적 장점(§13.1.2 (3)~(5))은
바뀌지 않지만, threshold를 `entry_score` 분포에 맞춰 별도로
재산정하는 절차가 diff 이전에 반드시 선행돼야 한다.

**미확인 사항**:
1. 이 표본의 `ranking_score`가 정확히 어떤 조합의 구버전 공식으로
   생성됐는지(제거 diff별 부분 반영 여부)는 미확인.
2. `risk_off_exception_eligible` 최종 판정(활동성/전략/신호 조건 포함)은
   미확인 — 이번 턴은 `ranking_score` 1차 게이트 실측으로 범위를
   한정했다.
3. `entry_score` 분포에 맞춘 대체 threshold 재산정 방법(예: 분포
   기반 재보정, 별도 안전계수 도입 등)은 이번 턴에서 설계하지 않았다.

### 13.1.4 R1 — `entry_score` 기반 새 threshold 산정 방식 설계 검토(2026-08-02 KST, read-only 설계 검토)

**목적**: §13.1.3에서 확인한 "`threshold ÷ 0.55` 단순 재정규화는 이
구간 표본을 전량 뒤집는다"는 실측 결과를 출발점으로, `_CORE_RISK_OFF_
RANKING_MIN_SCORE = 0.28`을 `entry_score` 기준으로 어떻게 치환해야
하는지 설계안을 좁힌다. 이번 절은 설계 비교까지만 하며, 코드는
변경하지 않는다.

**전제(이미 닫힌 사실, 재검증하지 않음)**: R1 판정 C(§13.1.1), 대체
contract 설계 비교·C안 권고(§13.1.2), `ranking_score ∈ [0.28, 0.38]`
구간 100% 뒤집힘 실측(§13.1.3), `regime_tailwind`/`strategy_
alignment`/`coverage_score` 제거(SPPV-2.133/2.138/2.147/2.159) — 전부
참조만 하고 다시 검증하지 않는다.

#### (1) `0.28 / 0.55`가 실패하는 구조 — 짧은 정리

- `allocation_quality`는 §13.1.3 실측 모집단(전체 이력 2,455건/13종목)
  전 구간에서 `max_new_capital_pct=2.5` 단일값으로 고정돼 있었고, 이에
  따라 `allocation_quality = clamp(2.5/10) = 0.25`도 상수였다.
- `ranking_score - 0.55*entry_score` 편차는 `0.2249~0.2933`(평균 약
  `0.235`)이었다 — `0.10*allocation_quality`(=`0.025`)만으로는 설명되지
  않는 큰 편차이며, §13.1.3에서 이미 기록한 대로 이 편차의 나머지는
  이 표본의 `ranking_score`가 아직 반영되지 않은 legacy 제거 diff
  구간의 값을 담고 있었기 때문으로 추정된다(개별 항목 타당성은 재검토
  대상 아님).
- **새로 확인한 사실**: `_build_entry_score()` 자체도 `max_new_capital_
  pct`를 이미 반영한다 — `pct > 0`이면 `min(0.10, pct/100)`을 더하고,
  `pct <= 0`이면 `-0.20`을 뺀다. `0 < pct <= 10` 구간에서
  `min(0.10, pct/100) = pct/100`이고, `ranking_score`의 `0.10*
  clamp(pct/10, 0, 1)`도 같은 구간에서 `pct/100`과 **수치까지 정확히
  동일**하다(둘 다 `pct=10`에서 `0.10`으로 캡). 즉 `allocation_quality`
  항은 `entry_score`가 이미 담고 있는 것과 **같은 값**을 다시 더하되,
  `ranking_score` 안에서는 `0.55` 가중치를 거치지 않고 **1.0 가중치로
  두 번째로 더해진다** — R1 결론("두 항 모두 독립 정보 없음", §13.1.1)
  을 수치 수준에서 재확인하는 사실이다.
- **authoritative 게이트가 실제로 요구하는 것이 무엇인지 분리**: 이
  게이트(`_assess_core_risk_off_buy_guard`)의 설계 의도는 "`ranking_
  score`라는 특정 산식값 0.28"이 아니라, **core risk-off 국면에서
  예외적으로 진입을 허용할 만큼 신호가 충분히 강한가**라는 운영
  목적상의 보수성이다. 즉 필요한 것은 (a) 옛 산식과 수학적으로
  한 치도 다르지 않은 "경계 보존"이 아니라, (b) 같은 보수성 수준을
  유지하는 재현 가능한 문턱이면 된다 — 다만 (b)를 무엇으로 정의할지가
  이번 절의 핵심 쟁점이다.

#### (2) 신규 threshold 산정안 비교(A/B/C)

| 축 | A안: 단순 선형 치환 | B안: 실측 기반 보정치 반영 | C안: 단일 threshold 대신 보조 조건 병행 |
|---|---|---|---|
| 정의 | `entry_score_min = 0.28 / 0.55 ≈ 0.5091`(`allocation_quality=0` 가정, 이미 §13.1.2/§13.1.3에서 검증) | `entry_score_min = (0.28 - 0.10*aq_typical) / 0.55`, `aq_typical`은 실측 모집단의 관측 상수(`0.25`) → `≈ 0.4636` | `ranking_score` 필드를 authoritative 경로에서 제거하되, 게이트 조건 자체는 `0.55*entry_score + 0.10*clamp(max_new_capital_pct/10, 0, 1) >= 0.28`을 호출부에서 직접(인라인) 계산 |
| 수학적 단순성 | **가장 단순**(상수 1개) | 단순하나 `aq_typical` 상수 산정 근거가 추가로 필요 | 상수는 그대로(`0.28`)지만 입력이 1개에서 2개(`entry_score`, `max_new_capital_pct`)로 늘어남 |
| 현재 실측과의 정합성 | **낮음** — §13.1.3에서 이 구간 표본 100% 뒤집힘으로 이미 기각 | **부분적** — `aq_typical=0.25`는 이번 실측 모집단(2,455건)에서는 상수로 관측됐으나, 이 좁은 `ranking_score ∈ [0.28,0.38]` 구간 밖(다른 국면·다른 `max_new_capital_pct` 값)에서도 상수인지는 미확인 | **완전 일치** — 근사가 아니라 기존 산식을 그대로 재현하므로 편차 자체가 존재하지 않음 |
| authoritative 경로 영향 범위 | `_assess_core_risk_off_buy_guard` 1곳(동일) | `_assess_core_risk_off_buy_guard` 1곳(동일) | `_assess_core_risk_off_buy_guard` 1곳(동일) |
| shadow/reporting 무변화 가능성 | 가능(§13.1.2 (1) 그대로 유지) | 가능(§13.1.2 (1) 그대로 유지) | 가능(§13.1.2 (1) 그대로 유지) — `ranking_score` 필드 계산 자체는 세 안 모두 안 건드림 |
| 코드 변경 난이도 | **가장 낮음**(상수 1개 교체) | 낮음(상수 1개 교체 + `aq_typical` 산정 근거를 주석/문서로 남겨야 함) | 낮음~중간(호출부에서 `portfolio_allocation` 인자를 추가로 참조해야 함 — 함수 시그니처 영향 있음) |
| 과완화 / 과차단 위험 | **과차단 확정**(§13.1.3 실측: 표본 100% 뒤집힘) | `aq_typical` 가정이 깨지는 국면(예: `max_new_capital_pct`가 이번 관측 범위 밖 값을 가지는 날)에서 과소/과다 양방향 위험 — 정기 재검증 필요 | **없음**(수학적으로 기존과 동일하므로 과완화/과차단 자체가 발생할 수 없음) |
| R1 결론("두 항 모두 독립 정보 없음", §13.1.1)과의 정합성 | 정합적(단일 항으로 축약) | 정합적(단일 항 + 보정 상수로 축약 시도) | **낮음** — `allocation_quality`를 여전히 별도 항으로 유지해, R1이 "제거 대상"으로 지목한 이중 반영 구조 자체는 코드상 그대로 남는다(다만 필드명 `ranking_score`는 authoritative 경로에서 제거됨) |

#### (3) 1순위 권고안

**C안(단일 threshold 대신 보조 조건 병행, 즉 기존 산식을 인라인으로
그대로 재현)을 권고한다.**

근거:
1. §13.1.3 실측이 보여준 위험(단순 재정규화 시 표본 100% 뒤집힘)은
   **근사 자체를 없애면 원천적으로 발생할 수 없다** — C안은 근사가
   아니라 기존 산식을 그대로 재현하므로 과완화/과차단 위험이 없다.
2. `aq_typical` 같은 관측 상수에 의존하는 B안은 이번 실측 모집단
   (좁은 `ranking_score ∈ [0.28, 0.38]` 구간)에서만 검증됐고, 더 넓은
   범위(다른 `max_new_capital_pct` 값)에서도 상수로 유지되는지는
   미확인이라 후속 재검증 부담이 남는다.
3. 코드 변경 범위는 `_assess_core_risk_off_buy_guard` 호출부가
   `portfolio_allocation`을 참조 인자로 추가하는 정도로, 여전히 국소적
   이다.

**단, 다음 한계를 명시한다**: C안은 authoritative 경로에서 `ranking_
score`라는 **필드/이름**은 제거하지만, R1이 지적한 "`entry_score`와
`allocation_quality`의 이중 반영"이라는 **구조**는 그대로 남긴다.
즉 R1의 "제거/대체" 판정을 필드 수준에서는 만족하지만, 이중 반영
구조를 완전히 해소하는 것은 아니다 — 이 구조적 잔여 문제는 R2
(`entry_score` 내부 보정항 분리, §13.2)에서 다룰 사안으로 남긴다.

**"다음 턴에서 바로 코드 수정 초안 작성 가능한가" 판정**: **가능**.
C안은 근사·재검증이 필요 없고(수학적으로 기존과 동일), 변경 대상이
`_assess_core_risk_off_buy_guard` 호출부와 그 인자 전달 경로로 좁혀져
있어 다음 턴에 바로 diff 초안을 작성할 수 있는 수준이다.

#### (4) `ranking_score` 완전 제거 vs authoritative 경로 한정 제거(재확인)

이 판단은 §13.1.2 (3)~(5)에서 이미 C안(authoritative만 교체, 관찰용
`ranking_score` 계산은 그대로 잔존)으로 닫혔고, 이번 턴에 다시 열지
않는다. 이번 절의 threshold 설계안(A/B/C) 중 어떤 것을 택하더라도
`ranking_score` 필드 자체의 계산 로직(`_build_buy_ranking_score`)은
건드리지 않으며, 그 값은 shadow(`_build_core_risk_off_shadow_
experiment_metadata`)·`event_overlay` shadow·`decision_json` 저장
경로에 그대로 남는다 — authoritative 경로 한 곳만 참조 대상을
바꾼다는 원칙은 A/B/C안 공통이다.

#### (5) 관찰용 소비자(`trigger_proxy_attribution.py` 등) — 이번 턴 확인 범위

- §13.1.2 (4)에서 이미 확인한 대로 DB write·`repos` 사용이 없는 순수
  reporting이며, 이번 턴 A/B/C안 어느 쪽을 택해도 **`ranking_score`
  필드 계산 자체가 바뀌지 않으므로 수정 없이 그대로 유지 가능**하다.
  authoritative 게이트 교체와 이 소비자의 동작은 서로 독립적이다.
- 별도 후속 정리가 필요한지는 이번 턴 범위에서 판단하지 않는다 —
  §13.1.2 (4)의 결론대로 "강제할 필요는 없으나 연구 연속성 비용을
  고려해 diff 설계 단계에서 트레이드오프로 반영"이라는 기존 입장을
  유지하며, 구체적인 후속 정리 트랙 분리 여부는 diff 착수 시점에
  별도로 정한다.

#### (6) 이번 턴 미확인 사항

1. `aq_typical=0.25`가 `ranking_score ∈ [0.28, 0.38]` 구간 밖에서도
   상수로 유지되는지(B안 검증에 필요)는 미확인.
2. C안 채택 시 `_assess_core_risk_off_buy_guard` 함수 시그니처 변경이
   호출부 전체(단위 테스트 포함)에 미치는 영향 범위는 이번 턴에서
   조사하지 않았다.
3. `risk_off_exception_eligible` 최종 판정(활동성/전략/신호 조건
   포함)에 대한 실측은 여전히 미확인(§13.1.3과 동일 범위 제한).

### 13.1.5 R1 — C안(보조 조건 병행) 코드 수정 초안 적용(2026-08-02 KST)

**목적**: §13.1.4에서 권고한 C안(보조 조건 병행)을 실제 코드 수정
초안으로 적용한다. `ranking_score` 공식(`_build_buy_ranking_score`)
자체는 바꾸지 않았고, authoritative 경로(`_assess_core_risk_off_buy_
guard`)만 대상으로 최소 범위 수정했다.

**무엇이 어떻게 바뀌었는지**:
- `_assess_core_risk_off_buy_guard()`의 매개변수를 `ranking_score:
  float | None`에서 `entry_score: float`, `portfolio_allocation:
  PortfolioAllocationAssessment | None`로 교체했다.
- 함수 내부에서 외부에서 전달받은 `ranking_score` 값을 참조하는 대신,
  `_build_buy_ranking_score(entry_score=entry_score, portfolio_
  allocation=portfolio_allocation)`을 **그 자리에서 직접 다시 호출**해
  authoritative 게이트 전용 점수(`core_risk_off_authoritative_score`)를
  얻고, 이 값을 `_CORE_RISK_OFF_RANKING_MIN_SCORE(0.28)`와 비교한다.
- `assess_deterministic_triggers()`의 호출부(228번째 줄 부근)도
  `ranking_score=ranking_score` 인자를 `entry_score=entry_score,
  portfolio_allocation=portfolio_allocation`로 교체했다.

**이번 안이 단순 선형 치환(A안)과 다른 이유**: A안은 `0.28`이라는
상수를 `0.55`로 나눠 `entry_score` 단독 threshold로 근사했고, 그
근사가 `allocation_quality`를 빠뜨려 §13.1.3에서 표본 100% 뒤집힘으로
이어졌다. 이번 C안은 threshold를 근사하지 않는다 — **"근사"가 아니라
"보존"**이다. `_build_buy_ranking_score()`를 authoritative 게이트
호출부에서 동일 입력(`entry_score`, `portfolio_allocation`)으로 다시
호출하므로, 산출되는 점수는 이전에 threading되던 `ranking_score` 변수
값과 **수치까지 정확히 동일**하다. 즉 게이트가 참조하는 대상이
"미리 계산돼 threading된 `ranking_score` 변수"에서 "그 자리에서
독립적으로 재계산한 동일 공식의 결과"로 바뀌었을 뿐, 계산 결과나
threshold 판정 경계는 **한 치도 바뀌지 않는다**.

**유지한 것 / 건드리지 않은 것**:
- `_build_buy_ranking_score()` 공식 자체 — 무변화.
- `decision_json.deterministic_trigger.ranking_score` 저장 경로 —
  `assess_deterministic_triggers()`가 계산하는 외부 `ranking_score`
  변수는 그대로 남아 `DeterministicTriggerAssessment.ranking_score`에
  저장되고 `decision_factory.py`를 거쳐 `decision_json`에 그대로
  기록된다.
- core shadow 메타데이터(`_build_core_risk_off_shadow_experiment_
  metadata`, `0.02`/`0.26`류 threshold) — 여전히 외부 `ranking_score`
  변수를 그대로 참조하며 무변화.
- `event_overlay` shadow 메타데이터(`_build_event_overlay_shadow_
  experiment_metadata`, `0.56` threshold) — 무변화.
- `trigger_proxy_attribution.py` 등 reporting 경로 — `ranking_score`
  필드 계산이 바뀌지 않았으므로 수정 없이 그대로 유지된다.
- `entry_score` 내부 구조(R2 대상) — 건드리지 않았다.

**실행한 검증과 결과**:
- `bash scripts/harness/run.sh accept backend-file src/agent_trading/
  services/deterministic_trigger_engine.py` → PASS
  (`py_compile_passed=1`, `tests_run_count=3`, `test_failed_count=0`)
- `bash scripts/harness/run.sh test-file tests/services/test_
  deterministic_trigger_engine.py` → 24 passed
- `bash scripts/harness/run.sh test-one "tests/services/test_
  deterministic_trigger_engine.py::test_trigger_engine_marks_risk_
  off_exception_eligible_for_strong_core_setup"` → 1 passed
- `bash scripts/harness/run.sh test-one "tests/services/test_
  deterministic_trigger_engine.py::test_trigger_engine_core_risk_off_
  ranking_boundary_shifts_by_coverage_score_weight"` → 1 passed
- `bash scripts/harness/run.sh test-one "tests/services/test_
  deterministic_trigger_engine.py::test_trigger_engine_applies_core_
  risk_off_topk_override_for_selected_candidate"` → 1 passed
- `bash scripts/harness/run.sh lint-path src/agent_trading/services/
  deterministic_trigger_engine.py` → All checks passed
- DB write·KIS 호출·전체 테스트(full pytest)·`.env` 수정은 하지 않았다.

**아직 운영 실측이 남아 있는지**: 이번 수정은 §13.1.4에서 이미 확인한
대로 **근사가 아니라 기존 산식의 인라인 재현**이므로, 별도의 운영
데이터 재실측 없이도 authoritative 판정 경계가 그대로 보존됨을
단위 테스트로 확인했다. 다만 아래는 여전히 미확인이다:
1. `_assess_core_risk_off_buy_guard` 시그니처 변경이 이 함수를 직접
   호출하는 다른 상류/하류 코드(현재 확인된 호출부는 1곳뿐)에 영향을
   주는지 — 이번 턴은 저장소 전수 검색으로 호출부가 1곳뿐임을
   확인했다.
2. `risk_off_exception_eligible` 최종 판정(활동성/전략/신호 조건
   포함)에 대한 운영 데이터 실측은 이번 턴 범위 밖(§13.1.3과 동일
   범위 제한).

### 13.1.6 R1 — authoritative 게이트 명시식 2차 수정(2026-08-02 KST)

**목적**: PR #98(§13.1.5)에서 적용한 C안은 `_assess_core_risk_off_buy_
guard()`가 `ranking_score`를 직접 참조하지 않도록 매개변수를
`entry_score`+`portfolio_allocation`으로 바꿨지만, 함수 내부에서는
여전히 `_build_buy_ranking_score()`를 **재호출**해 점수를 얻고 있었다.
이번 절은 그 재호출까지 제거하고, 게이트가 실제로 보는 조건을 코드
안에 직접 풀어 쓴다.

**PR #98 상태에서 무엇을 재호출하고 있었는지(먼저 확인한 사실)**:
`_assess_core_risk_off_buy_guard()`는 `core_risk_off_authoritative_
score = _build_buy_ranking_score(entry_score=entry_score, portfolio_
allocation=portfolio_allocation)`를 호출해 `0.55*entry_score + 0.10*
clamp(max_new_capital_pct/10, 0, 1)`를 그 함수에게 위임하고 있었다 —
계산 결과는 §13.1.5에서 확인한 대로 기존 `ranking_score`와 수치까지
동일했지만, "게이트가 무엇을 보는지"는 `_build_buy_ranking_score()`의
본문을 열어봐야 알 수 있는 상태였다.

**PR #98 대비 이번 턴의 정확한 차이**: PR #98은 "**기존 ranking 산식을
게이트 내부에서 재계산**"한 것이고, 이번 턴은 "**authoritative 게이트의
명시식 치환**"이다 — `_build_buy_ranking_score()` 호출 자체를 없애고,
그 자리에 동일한 산술식(`0.55*entry_score + 0.10*allocation_bonus_
like`)을 게이트 함수 안에 직접 적어 넣었다. `_build_buy_ranking_
score()`는 여전히 `ranking_score` 저장/shadow/reporting 경로를 위해
그대로 남아 있고, 이번 수정은 그 함수를 전혀 건드리지 않았다.

**구현**:
- 모듈 상수 3개를 새로 추가했다: `_CORE_RISK_OFF_ENTRY_SCORE_WEIGHT
  = 0.55`, `_CORE_RISK_OFF_ALLOCATION_BONUS_WEIGHT = 0.10`, `_CORE_
  RISK_OFF_ALLOCATION_NORMALIZER_PCT = 10.0` — `_build_buy_ranking_
  score()`가 쓰는 것과 같은 값이지만, 그 함수를 고치지 않고 게이트
  쪽에서만 이름을 붙여 참조한다(두 곳에 상수가 나뉘어 존재하는 트레이드
  오프는 아래 (2)에서 다룬다).
- `_assess_core_risk_off_buy_guard()` 내부에서 `allocation_bonus_
  like`(신규 자본 배정 여유도를 0~1로 정규화한 보조 조건)와
  `authoritative_entry_gate_score`(`0.28`과 실제로 비교되는 값)를
  지역 변수로 직접 계산한다. `_build_buy_ranking_score()` 호출은
  완전히 제거됐다.

**이 치환이 수치상 동일하게 유지되는지 테스트로 고정 가능한지(먼저
확인한 사실)**: 가능하다고 판단했고, 실제로 신규 회귀 테스트
`test_trigger_engine_core_risk_off_authoritative_score_matches_
ranking_score_formula`를 추가해 고정했다 — `assess_deterministic_
triggers()`가 반환한 `result.ranking_score`(여전히 `_build_buy_
ranking_score()`가 만든 값)와, `result.entry_score`를 다시
`_build_buy_ranking_score()`에 넣어 재계산한 값을 pass/blocked 경계
양쪽에서 비교한다. `entry_score`/`ranking_score`가 저장 시 각각 4자리로
반올림되므로 완전한 비트 단위 일치는 아니지만(허용 오차 `1e-3`), 두
계산식이 서로 다른 코드 경로로 분리된 뒤에도 어긋나지 않음을 이
테스트가 고정한다 — 둘 중 하나만 바뀌면 이 테스트가 실패한다.

**유지한 것 / 건드리지 않은 것**: `_build_buy_ranking_score()` 본문,
`decision_json.deterministic_trigger.ranking_score` 저장 경로, core
shadow 메타데이터(`0.02`/`0.26`류), `event_overlay` shadow(`0.56`),
`trigger_proxy_attribution.py` 등 reporting 경로, `entry_score` 내부
구조(R2 대상) — 전부 무변화.

**환경 관련 발견(검증 방법에 대한 중요한 사실)**: 이 로컬 서버의
`bash scripts/harness/run.sh accept backend-file`/`test-file`은
내부적으로 `docker exec agent_trading-app-1 ...`을 실행하는데, 이
컨테이너의 `/app`은 `/workspace/agent_trading_dev`(이번 작업 경로)가
아니라 `/workspace/agent_trading`(별도의 git clone, main 머지 뒤
별도 동기화 과정을 거쳐 갱신되는 배포 체크아웃)에 bind mount돼 있다.
즉 **병합 전 이 명령들은 이번 턴의 수정 내역을 반영하지 않은 stale
코드를 테스트한다.** 이번 턴은 이 사실을 확인한 뒤, 같은 이미지
(`agent_trading-app:latest`)로 `/workspace/agent_trading_dev`를 직접
mount하는 임시 컨테이너(`docker run --rm -v /workspace/agent_
trading_dev:/app -w /app agent_trading-app:latest python3 -m pytest
...`)를 별도로 띄워 **실제 변경분**을 검증했다 — production 체크아웃
(`/workspace/agent_trading`)은 직접 덮어쓰지 않았다(CI/CD 파이프라인을
우회하는 위험한 행동이라 배제). `run.sh`가 요구하는 표준 명령도 그대로
실행해 기록을 남겼지만, 그 결과는 stale 코드 기준일 수 있음을 함께
밝힌다.

**실행한 검증과 결과**:
- (dev tree 직접 검증, 임시 컨테이너) `docker run --rm -v /workspace/
  agent_trading_dev:/app -w /app agent_trading-app:latest python3 -m
  pytest tests/services/test_deterministic_trigger_engine.py -v` →
  **25 passed**(신규 회귀 테스트 포함)
- (dev tree 직접 검증) `... python3 -m py_compile src/agent_trading/
  services/deterministic_trigger_engine.py` → 통과(exit 0)
- (dev tree 직접 검증) `... python3 -m ruff check src/agent_trading/
  services/deterministic_trigger_engine.py` → All checks passed
- (dev tree 직접 검증) core risk-off guard 관련 selector 4건을 같은
  임시 컨테이너로 개별 실행 → 4 passed
- (표준 명령, stale 체크아웃 기준) `bash scripts/harness/run.sh
  accept backend-file src/agent_trading/services/deterministic_
  trigger_engine.py` → PASS(3 tests, `/workspace/agent_trading`
  기준이라 이번 턴 신규 테스트는 미포함)
- (표준 명령, stale 체크아웃 기준) `bash scripts/harness/run.sh
  test-file tests/services/test_deterministic_trigger_engine.py` →
  24 passed(같은 이유로 신규 테스트 미포함)
- DB write·KIS 호출·전체 테스트(full pytest)·`.env` 수정은 하지
  않았다.

**아직 운영 실측이 남아 있는지**: 이번 수정도 근사가 아니라 §13.1.5와
동일한 산식을 그대로 유지하므로, 추가 운영 데이터 실측은 필요 없다.
다만 아래는 여전히 미확인이다:
1. `_CORE_RISK_OFF_ENTRY_SCORE_WEIGHT`/`_CORE_RISK_OFF_ALLOCATION_
   BONUS_WEIGHT`가 `_build_buy_ranking_score()`의 `0.55`/`0.10`과
   앞으로도 어긋나지 않을지는 신규 회귀 테스트로만 고정돼 있다 —
   상수를 완전히 단일 지점화(공유 헬퍼로 추출)하지는 않았으며, 이는
   R2 논의(§13.2)에서 다룰 여지로 남긴다.
2. `risk_off_exception_eligible` 최종 판정(활동성/전략/신호 조건
   포함)에 대한 운영 데이터 실측은 여전히 미확인(§13.1.3과 동일 범위
   제한).
3. 이 로컬 서버의 `/workspace/agent_trading` 동기화 시점/방식(어떤
   프로세스가 언제 갱신하는지)은 이번 턴에서 조사하지 않았다 —
   병합 후 harness 표준 명령을 다시 실행해 재확인이 필요하다.

#### 검증 환경 설명 재확인/정정(2026-08-02 KST, PR #99 머지 후, read-only)

PR #99 완료 보고에 적은 위 환경 설명을 Codex의 지적을 계기로 다시
검증했다. **결론: 핵심 사실은 그대로 유지되지만, 표현 하나는 낮춰서
정정한다("병합 전"이라는 시점 조건을 더 분명히 함).**

**다시 확인해 그대로 유지되는 사실**:
1. `agent_trading-app-1` 컨테이너 mount 구조는 변함없다 —
   `docker inspect`로 `/app/src`, `/app/tests`, `/app/scripts`,
   `/app/pyproject.toml`이 전부 `/workspace/agent_trading_dev`가 아닌
   `/workspace/agent_trading`(별도 git clone)에서 bind mount됨을
   재확인했다.
2. PR #99 머지 시점 이전, 즉 코드가 아직 로컬 브랜치에만 있던 시점에
   `test-file`/`accept backend-file`이 신규 회귀 테스트를 반영하지
   못했던 것은 **정확한 관찰이었다** — 그 시점 `/workspace/agent_
   trading`의 git HEAD는 PR #98 머지 커밋(`004336ec`)에 머물러 있어
   PR #99의 수정 내역이 존재할 수 없었다.
3. `accept backend-file`의 `tests_run_count=3`과 `test-file`의
   `25 passed`는 **같은 것을 세는 지표가 아니다** — `accept backend-
   file`은 import-graph로 고른 **후보 파일 3개**(`test_deterministic_
   trigger_engine.py`, `test_run_decision_loop.py`, `test_agents.py`)
   각각에 대해 pytest를 1회씩 실행한 횟수(파일 단위)이고, `test-file`
   의 `25 passed`는 지정한 **파일 1개 안의 개별 테스트 함수 수**다.
   두 수치를 나란히 "3건 대 24건"처럼 비교한 것은 단위가 다른 값을
   비교한 것이라 오해의 소지가 있었다 — 이 부분은 표현을 낮춰
   정정한다.

**다시 확인해 낮춰서 정정하는 표현**: "병합 전 이 명령들은 이번 턴의
수정 내역을 반영하지 않은 stale 코드를 테스트한다"는 문장은, PR #99가
머지된 지금 같은 명령을 다시 실행해 보니 **머지 및 production 체크아웃
동기화가 끝나는 즉시 정확히 해소되는 시점 제약**임이 확인됐다. 실제로
이번 턴 PR #99 머지(HEAD `490a6ce1`) 직후 `/workspace/agent_trading`의
git HEAD도 `490a6ce1`로 이미 동기화돼 있었고, 이 상태에서 (Codex가
`scripts/harness/run.sh`에 작업 중인 미커밋 workspace-role 패치를
`git stash`로 잠시 걷어내고) 원래 커밋된 `run.sh`로 `test-file
tests/services/test_deterministic_trigger_engine.py`를 다시 실행하니
**정확히 25 passed**로 신규 회귀 테스트까지 정상 반영됨을 확인했다
(검증 뒤 `git stash pop`으로 Codex의 미커밋 변경을 원상 복구했다 —
이번 턴은 코드 수정 금지이므로 그 변경을 이어서 고치거나 되돌리지
않았다). 즉 "stale 코드를 테스트한다"는 표현은 **영구적 결함이 아니라
병합 전 한정 현상**으로 톤을 낮춰야 정확하다.

**Codex의 지적이 실제로 유효했는가에 대한 판정**: 부분적으로 유효
하다 — 핵심 메커니즘(별도 production 체크아웃을 mount)은 틀리지
않았지만, "병합 전"이라는 시점 조건과 "3건 대 24건"이라는 단위가 다른
수치 비교는 정밀도를 낮춰 다시 표현해야 했다. PR #99의 코드/테스트
결론(§13.1.6 본문의 authoritative 게이트 명시식 치환, 회귀 테스트,
25 passed) 자체에는 **영향이 없다** — 이 결론은 이미 dev tree를 직접
mount한 임시 컨테이너 실측과, 이번 재검증(원본 `run.sh`로 병합 후
25 passed 재확인)으로 이중 확인됐다.

**새로 확인한 사실(이번 재검증에서 처음 확인)**: `scripts/harness/
run.sh`에 `BASE_WORKSPACE_ROOT`/`DEV_WORKSPACE_ROOT`를 구분하는
workspace-role 인식 로직이 **미커밋 상태로 이미 작업 중**임을
발견했다(작성자 미상, 정황상 Codex로 추정). 이 로컬 패치는 `dev`
작업 경로에서는 `agent_trading-app-1`(production 컨테이너) 대신 host
`python3`를 쓰도록 분기하지만, 아직 host에 `pytest`가 설치돼 있지
않아 `dev` 경로에서 그대로 실행하면 `No module named pytest`로 실패
하는 **미완성 상태**다. 이 패치가 정확히 이번 절이 지적한 문제
(dev 작업 경로와 harness 검증 대상 불일치)를 겨냥하고 있다는 점은
이번 턴의 환경 설명이 근거 없는 우려가 아니었음을 뒷받침한다. 이번
턴은 이 패치를 완성하거나 커밋하지 않았다(코드 수정 금지 범위 밖).

### 13.2 R2 — `entry_score`의 alpha / risk / sizing 분리

- 범위:
  - `entry_score`에서 alpha 외 보정항(`market_regime`, `preferred_strategy`,
    `allocation`, `relative_activity`)을 유지/이관/제거로 분류
- 핵심 질문:
  - `entry_score`가 alpha 대표점수로 남아야 하는지
  - 아니면 risk/sizing 보정을 밖으로 밀어내야 하는지
- 우선순위: **2순위**

#### 13.2.1 `entry_score` 내부 항목 전수 분해(2026-08-02 KST, read-only 분석)

**목적**: R1(§13.1.1~§13.1.6)을 정리된 것으로 두고, 다음 리팩터링 단위를
R2(`entry_score` 내부 alpha/risk/sizing 분리)로 좁힌다. 이번 절은
`_build_entry_score()`를 전수 분해하고 BUY 경로 다른 지점과의 중복
여부를 매핑하는 read-only 분석이며, 코드는 변경하지 않았다.

**전제(이미 닫힌 사실, 재검증하지 않음)**: R1 판정 C(§13.1.1), C안
설계·실측(§13.1.2~§13.1.4), C안 코드 적용 2단계(§13.1.5~§13.1.6),
그 안에서 확정된 "`entry_score` 쪽 `+0.05`(전략 정합) 보정항은 그대로
유지한다"는 결정(§13.1.1 인용, `_build_buy_ranking_score()` 주석) —
전부 참조만 하고 다시 열지 않는다.

**(1) `entry_score` 내부 항목 분해표**

`_build_entry_score()`(`deterministic_trigger_engine.py`)를 코드
순서대로 분해하면 아래 6개 항목으로 나뉜다.

| 순번 | 계열 | 조건/가중치 | 근거 필드 |
|---|---|---|---|
| 1 | alpha | 기본: `0.45*overall + 0.20*fast + 0.15*slow`. `r3b_alpha_enabled`일 때만 `0.80*r3b_alpha_percentile`로 교체(SPPV-2.65) | `overall_score`/`fast_score`/`slow_score` 또는 `r3b_alpha_percentile` |
| 2 | regime/risk | `bullish_trend` `+0.10`, `risk_on` `+0.05`, `risk_off` `-0.15` | `market_regime.regime_label`/`risk_tone` |
| 3 | allocation | `max_new_capital_pct>0`이면 `+min(0.10, pct/100)`, 아니면 `-0.20` | `portfolio_allocation.max_new_capital_pct` |
| 4 | strategy | `preferred_strategy ∈ {swing_momentum, event_continuation}`이면 `+0.05` | `strategy_selection.preferred_strategy` |
| 5 | source-type(context/routing) | `market_overlay` `+0.05`, `held_position` `-0.35` | `source_type` |
| 6 | activity | `relative_activity_bonus>0`이면 `+min(0.10, bonus*0.10)` | `signal_feature_snapshot.volume_surge_ratio`/`turnover_surge_ratio` 파생(`_build_relative_activity_score`) |

**(2) BUY 경로 중복/충돌 매핑표**

각 항목의 근거 필드가 BUY 경로의 다른 지점에서도 다시 쓰이는지
전수 확인했다.

| 계열 | eligibility(`_assess_buy_eligibility`) | core risk-off guard(§13.1.6 명시식) | execution feasibility(eligibility 내 참여율 블록) | candidate_vs_final / 하류(AI 컨텍스트·EV gate) |
|---|---|---|---|---|
| alpha(`overall`/`slow`) | 하드 floor(`overall<-0.10`, `slow<-0.15`) | 하드 floor(`overall<0.0`, `slow<-0.05`, 별도 임계값) | 미사용 | `candidate_confidence`(=entry/exit/watch 중 최댓값)로 간접 노출, EV gate 미사용 |
| regime/risk | risk_off+bearish_trend 하드 게이트(`risk_off_exception_eligible` 분기) | `_is_core_risk_off_regime()`가 동일 필드로 활성 여부 판정 | 미사용 | `prompt_context_projection.py`에 `regime_label`/`risk_tone` 원문 주입 |
| allocation(`max_new_capital_pct`) | `allocation_budget_ok` 하드 게이트(`pct>0`) | `allocation_bonus_like`로 명시적 재사용(§13.1.6) | `recommended_max_order_value` 기반 참여율 계산(같은 `portfolio_allocation` 객체의 다른 필드) | `prompt_context_projection.py`에 `max_new_capital_pct` 원문 주입 |
| strategy(`preferred_strategy`) | 미직접 사용(하드 게이트 없음) | 허용 전략 집합(`defensive_low_volatility_rotation`/`mean_reversion_bounce`/`event_continuation`) — `entry_score` 쪽 집합과 `event_continuation`만 중첩 | 미사용 | `prompt_context_projection.py`에 `preferred_strategy` 원문 주입 |
| source-type | `held_position`/`reconciliation_overlay` 하드 차단 | `normalized_source_type == "core"` 조건으로 활성 여부 결정 | 미사용 | 미직접 사용(상류 라우팅 전용) |
| activity(`volume_surge_ratio`/`turnover_surge_ratio`) | 하드 게이트(`max(...)<1.10`) | 하드 게이트(`required_activity_min`, 기본 `1.20`/override 시 `1.10`) | 미사용(참여율은 `average_volume_20d`/`average_turnover_20d` 기준, activity와 다른 필드) | 미직접 사용 |

**(3) 항목별 4분류 판정**

| 계열 | 판정 | 근거 |
|---|---|---|
| alpha | **유지** | `entry_score`의 존재 이유 자체다. `overall`/`slow`가 eligibility·guard의 하드 floor에도 쓰이지만, 이는 "soft 가중 반영(alpha)"과 "hard floor(최소 신호 기준)"이라는 서로 다른 역할이라 R1 문서의 기존 관점(§5)과 정합적인 **정당한 역할 분리**로 본다. |
| regime/risk | **점수 밖 이관 검토** | `market_regime`은 이미 eligibility의 risk_off/bearish 하드 게이트, `core_risk_off_guard_active` 판정, AI 컨텍스트까지 3곳에 독립적으로 반영되고 있다. `entry_score` 내부의 soft 보너스/패널티(`±0.05~0.15`)는 이 3곳이 이미 다루는 것과 같은 신호(regime label/risk tone)를 **네 번째로** 반영하는 것이라 중복 폭이 가장 넓다. |
| allocation | **중복 제거 후보(최우선)** | §13.1.6에서 이미 확인했듯, `entry_score`의 allocation 보너스(`min(0.10, pct/100)`, `pct∈(0,10]`)는 authoritative 게이트의 `allocation_bonus_like`(`0.10*clamp(pct/10,0,1)`)와 **동일 신호를 두 가중치(0.55배 간접 + 1.0배 직접)로 중복 반영**한다 — 이는 근사가 아니라 수식으로 증명 가능한 중복이라 4분류 중 가장 확실한 후보다. |
| strategy | **유지(R1에서 이미 확정, 재론 안 함)** | `_build_buy_ranking_score()` 주석에 "entry_score 쪽 `+0.05`는 그대로 유지한다"고 이미 명시돼 있다(SPPV-2.146/§134.1). 이번 턴은 이 결정을 재검토하지 않는다. |
| source-type | **유지** | 점수 보정이라기보다 BUY/EXIT 경로 자체를 가르는 라우팅 신호라 다른 항목들과 성격이 다르다. eligibility의 하드 차단과 겹치지만, 이는 "진입 자체가 불가능한 source_type을 거르는 것"과 "그 안에서 점수를 미세 조정하는 것"이라는 별개 역할이다. |
| activity | **점수 밖 이관 검토(§13.4 R4 논의와 연계)** | `volume_surge_ratio`/`turnover_surge_ratio`가 eligibility·guard 양쪽의 하드 게이트로 이미 쓰이는데, `entry_score`의 soft 보너스는 그 위에 세 번째로 같은 신호에 보상을 얹는 구조다. 이 축은 이미 §13.4(R4, "bonus와 hard gate를 동시에 유지할 이유가 남아 있는지")에 정의된 우선순위 트랙과 겹치므로, R2 단독이 아니라 R4와 함께 다뤄야 한다. |

**(4) 이번 턴의 핵심 질문에 대한 답**

*"`entry_score`가 진짜 alpha 대표 점수로 남아야 하는가, 아니면
risk/sizing/execution 성격 항목을 밖으로 밀어내야 하는가?"*

**답: 전면 재정의는 필요 없고, 항목별 선택적 이관이 맞다.** 6개
항목 중 순수하게 "risk/sizing 성격이라 밖으로 밀어내야 할 후보"는
regime/risk와 allocation 2개뿐이다. alpha·strategy·source-type은
유지가 맞고(각각 alpha 본연, R1에서 이미 확정, 라우팅 전용), activity는
R2 단독 판단이 아니라 R4와 연계해서 봐야 한다. 즉 `entry_score`를
"alpha 전용으로 완전히 재정의"하는 것은 이번 실측 기준으로는
과도하며, **allocation 항목 하나만 먼저 손보는 것이 실제 중복 제거
효과 대비 리스크가 가장 작다.**

**(5) 다음 1순위 리팩터링 단위 권고**

**권고: `entry_score` 내부 allocation 보정항(±)을 별도 지역 변수/
헬퍼로 명시적으로 분리하는 무변화(behavior-unchanged) 리팩터링부터
착수한다.** 실제 수치를 바꾸는 제거·이관이 아니라, `_build_entry_
score()` 안의 `if portfolio_allocation.max_new_capital_pct > 0: ...`
블록을 이름 붙은 지역 변수(예: `entry_score_allocation_adjustment`)로
풀어 쓰고, 그 값이 authoritative 게이트의 `allocation_bonus_like`
(§13.1.6)와 같은 신호를 다른 가중치로 반영하고 있음을 코드 주석으로
명시하는 수준이다.

**왜 이 단위가 가장 작은 안전 단위인가**:
1. **수치 변화가 없다** — 지역 변수로 이름만 붙이는 것이라
   `buy_candidate_threshold(0.65)` 판정에 영향을 주지 않는다. R1에서
   `ranking_score` 대체가 실패했던 이유(§13.1.3, 단순 threshold
   재정규화가 표본 100%를 뒤집음)와 달리, 이번 단위는 threshold
   재산정이 아예 필요 없다.
2. **범위가 한 함수, 한 블록으로 좁다** — `_build_entry_score()`의
   allocation 블록(약 7줄) 하나만 대상이며, 호출부·시그니처 변경이
   없다.
3. **다음 단계(실제 제거/이관 여부 판단)의 선행 조건을 충족한다** —
   이 블록을 먼저 이름 붙여 분리해 두면, 다음 턴에 "이 항목이
   `buy_candidate_threshold`를 실제로 얼마나 넘기는 데 기여했는지"를
   운영 데이터로 실측할 때(§13.1.3과 같은 패턴) 대상 코드가 이미
   명확히 식별돼 있어 실측·제거 판단이 더 빨라진다.
4. **regime/risk 항목보다 먼저 다뤄야 한다** — regime/risk는 3곳
   (eligibility, guard, AI 컨텍스트)에 걸쳐 있어 영향 범위 분석이
   더 크고, allocation은 이미 §13.1.6에서 수식으로 증명된 중복이라
   분석이 끝나 있다. 작은 것부터 닫는 R1의 진행 방식(`buy_path_
   refactor_pre_roadmap_schedule.md` §2 "개별 threshold 조정보다
   변수 역할 분리를 먼저 닫는다")과 일치한다.

**미확인 사항**:
1. `entry_score`의 allocation 보정항이 `buy_candidate_threshold(0.65)`
   판정에 실제로 얼마나 기여했는지(운영 데이터 실측)는 이번 턴에서
   확인하지 않았다 — 다음 코드 수정 단위 착수 전 필요할 수 있다.
2. regime/risk 항목을 점수 밖으로 이관할 경우의 구체적 대상 위치
   (하드 게이트 강화 vs AI 컨텍스트 전용화)는 이번 턴에서 설계하지
   않았다.
3. activity 항목과 R4(§13.4) 트랙의 구체적 병합 순서는 이번 턴에서
   정하지 않았다.

#### 13.2.2 R2 1차 단위 적용 — allocation 보정항 지역 변수 분리(2026-08-02 KST)

**목적**: §13.2.1에서 권고한 다음 1순위 리팩터링 단위(allocation 보정항
분리)를 실제 코드 수정으로 적용한다. 이번 절은 **분리**만 하며,
제거·이관 여부 판단은 다음 턴으로 넘긴다.

**무엇을 어떻게 분리했는지**: `_build_entry_score()` 안의 allocation
블록(`if portfolio_allocation is not None: if pct>0: score += min(0.10,
pct/100.0) ... else: score -= 0.20`)을 이름 있는 지역 변수 `entry_
score_allocation_adjustment`로 분리했다. `portfolio_allocation`이
`None`이면 `0.0`, `pct>0`이면 `min(0.10, pct/100.0)`, 아니면 `-0.20`을
그대로 대입하고, 마지막에 `score += entry_score_allocation_adjustment`
한 줄로 합산한다. `reason_codes` append 조건과 순서는 그대로 유지했다.
코드 근처에 짧은 한국어 주석 1개를 추가해, 이 값이 authoritative
게이트의 `allocation_bonus_like`(§13.1.6)와 같은 `max_new_capital_pct`
원신호를 다른 가중치로 반영하고 있음을 명시했다.

**왜 "제거"가 아니라 "분리"인가**: 이번 수정은 계산되는 **값**을 한
치도 바꾸지 않는다 — 조건문 순서, 임계값(`0.10`, `100.0`, `-0.20`),
분기 구조가 전부 그대로이며, 단지 `score +=`로 즉시 누적되던 값을
먼저 이름 붙은 변수에 담았다가 같은 자리에서 합산하도록 바꿨을
뿐이다. §13.2.1에서 판정한 "중복 제거 최우선 후보"라는 분류는
그대로 유효하지만, **제거 여부(entry_score에서 아예 빼는 것)나
이관 여부(하드 게이트 전용으로 옮기는 것)는 이번 턴에서 결정하지
않았다** — 그 결정에는 §13.2.1의 미확인 사항 1번(운영 데이터 실측)이
선행돼야 하므로, 이번 턴은 다음 판단을 더 쉽게 하기 위한 **가독성/
분석 가능성 확보 단계**로 범위를 한정한다.

**무변화임을 보장하는 근거**:
1. `portfolio_allocation is None`이면 `entry_score_allocation_
   adjustment = 0.0`이고 `score += 0.0`은 기존에 이 블록 전체를
   건너뛰던 것과 결과가 같다.
2. `pct > 0`이면 `entry_score_allocation_adjustment = min(0.10,
   pct/100.0)`으로 기존 `score += min(0.10, pct/100.0)`과 값이 같고,
   `pct <= 0`이면 `-0.20`으로 기존 `score -= 0.20`과 값이 같다.
3. `reason_codes.append(...)` 두 줄은 위치·조건이 전혀 바뀌지 않았다.
4. 따라서 `entry_score` 최종값, `buy_candidate_threshold(0.65)` 판정,
   `_build_buy_ranking_score()`·authoritative 게이트(§13.1.6)·shadow·
   reporting 경로는 전부 무변화다 — 이 함수의 반환값에만 의존하는
   모든 하류 로직이 그대로다.

**실행한 검증과 결과**:
- (dev tree 직접 mount 임시 컨테이너 — 이유는 이전 턴에서 이미 문서화,
  재논의하지 않음) `python3 -m pytest tests/services/test_
  deterministic_trigger_engine.py -v` → **25 passed**(기존 회귀
  테스트 전부 무변화로 통과, 신규 테스트 추가 없음 — 순수 리팩터링이라
  기존 테스트만으로 충분히 고정된다고 판단)
- (dev tree 직접 mount) `python3 -m py_compile src/agent_trading/
  services/deterministic_trigger_engine.py` → 통과(exit 0)
- (dev tree 직접 mount) `python3 -m ruff check src/agent_trading/
  services/deterministic_trigger_engine.py` → All checks passed
- (dev tree 직접 mount) allocation 관련 selector 2건(`test_trigger_
  engine_instruments_buy_eligibility_failure_without_allocation_
  budget`, `test_trigger_engine_builds_buy_candidate_for_bullish_
  core`) 개별 실행 → 2 passed
- (표준 명령) `bash scripts/harness/run.sh accept backend-file
  src/agent_trading/services/deterministic_trigger_engine.py` → PASS
  (`tests_run_count=3`, `test_failed_count=0`)
- (표준 명령) `bash scripts/harness/run.sh test-file tests/services/
  test_deterministic_trigger_engine.py` → `workspace_role=dev` 경로가
  host `python3`로 분기해 `No module named pytest`로 실패(이전 턴에
  기록한 환경 사유, 재논의하지 않음) — dev tree 직접 mount 결과(25
  passed)로 대체 검증했다
- (표준 명령) `bash scripts/harness/run.sh accept docs` → PASS
- DB write·KIS 호출·전체 테스트(full pytest)·`.env` 수정은 하지
  않았다.

**다음 단계(제거/이관 판단, 1개)**: `entry_score_allocation_
adjustment`가 `buy_candidate_threshold(0.65)` 판정에 실제로 얼마나
기여했는지(예: 이 항 덕분에만 0.65를 넘긴 표본 규모)를 운영 데이터로
실측한 뒤, §13.2.1에서 이미 확인한 authoritative 게이트와의 중복을
근거로 **제거(entry_score에서 완전히 빼기)할지, 하드 게이트 전용으로
이관할지**를 결정한다 — R1(§13.1.3)에서 썼던 것과 같은 패턴(코드
변경 전 read-only 실측)을 따른다.

#### 13.2.3 R2 — `entry_score_allocation_adjustment` 기여도 실측(2026-08-02 KST, read-only)

**목적**: §13.2.2에서 분리한 `entry_score_allocation_adjustment`가
`buy_candidate_threshold(0.65)` 판정에 실제로 얼마나 기여했는지
운영 데이터로 실측해, 다음 코드 수정 단위(제거 vs 하드 게이트 전용
이관)를 판단할 근거를 만든다. 이번 턴은 read-only 실측이며 코드는
변경하지 않았다.

**조회 방법**: `trading_db`(PostgreSQL) 컨테이너에 read-only
`SELECT`로 직접 접속해 `trading.trade_decisions.decision_json`에서
`deterministic_trigger.entry_score`, `portfolio_allocation.max_new_
capital_pct`, `buy_candidate`, `eligibility_passed`,
`candidate_vs_final.final_intent`, `source_type`, `decision_type`,
`metadata.regime_label`/`risk_tone`를 추출했다. `entry_score_
allocation_adjustment`는 §13.2.2에서 이미 확인한 그대로 `pct>0`이면
`min(0.10, pct/100.0)`, 아니면 `-0.20`으로 SQL에서 재현했다(코드와
동일 계산, 근사 아님). `side='buy'` 필터만 적용했고, DB write·KIS
호출·코드 수정은 하지 않았다.

**집합 정의**: A = `entry_score >= 0.65`. B = `entry_score - entry_
score_allocation_adjustment < 0.65`(보정항 제거 시 문턱 미달). C =
A ∩ B(보정항 덕분에만 0.65를 넘긴 표본).

**새로 확인한 사실 1(집계 창별 비교표, Set A 기준)**:

| 집계 창 | 전체 표본(A) | distinct symbol | `buy_candidate=true` | `decision_type=approve` |
|---|---|---|---|---|
| 최근 3거래일(07-29~07-31) | 198 | 3 | 0 | 0 |
| 최근 1개월(07-02~07-31) | 633 | 5 | 126 | 24 |
| 전체 이력(06-20~07-31) | 675 | 6 | 168 | 24 |

**새로 확인한 사실 2(C 집합 규모, 핵심 결과)**: **세 집계 창 모두
C = 0건이다.** `entry_score_allocation_adjustment` 덕분에만
`buy_candidate_threshold(0.65)`를 넘긴 표본은 최근 3거래일/1개월/
전체 이력 어디에도 없었다.

**왜 0인지(구조적 이유, 새로 확인한 사실)**: 관측된 `max_new_capital_
pct` 값이 `{2.5, 3.0, 4.0}` 3개뿐이라 `entry_score_allocation_
adjustment`는 `{0.025, 0.03, 0.04}` 중 하나로 매우 좁게 고정돼
있었다. Set A 안에서 보정항을 뺀 값(`entry_score_without_
allocation`)의 `0.65` 대비 여유(margin)를 계산하면 최솟값이
`0.0038`(즉 `entry_score=0.6788`, `adj=0.025`인 표본), 최댓값
`0.1584`, 평균 `0.0850`이었다 — **가장 타이트한 표본조차 보정항
없이도 근소하게(0.0038) `0.65`를 넘겼다.**

**반대쪽 확인(요청 5번, "여유 있게 넘는 표본" 규모)**: Set A 675건
전부(100%)가 보정항 없이도 `0.65`를 넘긴다(= C가 0이므로 A 전체가
그 반대편이다). 여유가 `0.05` 미만으로 상대적으로 좁은 표본은 148건
(약 21.9%)이었으나, 이들도 전부 `0.65` 이상을 유지했다.

**decision_type/order_request 도달(추가 확인)**: `entry_score>=0.65`
인 675건 중 `decision_type='approve'`까지 간 것은 distinct (symbol,
거래일) 기준 단 1건 — `000810`, `2026-07-20`, `entry_score=0.7856`,
`adj=0.03`, `entry_score_without_allocation=0.7556`(보정항 없이도
`0.65`를 크게 상회). `order_requests` 테이블과 `trade_decision_id`/
`decision_context_id` 양쪽으로 조인해 확인한 결과, Set A 675건 전체
중 실제 `order_requests`에 도달한 건수는 **0건**이었다(이 population
자체가 하류에서 주문 제출까지 가지 못했다는 사실이며, 그 원인은
이번 턴 조사 범위 밖).

**"근접 사례" 상위 10건**(distinct `symbol`+거래일, `entry_score -
adjustment` 오름차순 — C 집합이 0건이라 대신 여유가 가장 좁았던
사례를 추출):

| symbol | 거래일(KST) | entry_score | entry_score_allocation_adjustment | entry_score_without_allocation | source_type | buy_candidate | final_intent | decision_type |
|---|---|---|---|---|---|---|---|---|
| 000720 | 2026-07-31 | 0.6788 | 0.025 | 0.6538 | event_overlay | false | no_action | hold |
| 000990 | 2026-07-30 | 0.6909 | 0.025 | 0.6659 | core | false | no_action | hold |
| 000660 | 2026-07-29 | 0.7491 | 0.03 | 0.7191 | event_overlay | false | watch | watch |
| 000660 | 2026-07-29 | 0.7491 | 0.03 | 0.7191 | event_overlay | false | no_action | hold |
| 001450 | 2026-07-24 | 0.7800 | 0.03 | 0.7500 | core | false | watch | watch |
| 001450 | 2026-07-24 | 0.7800 | 0.03 | 0.7500 | core | false | no_action | hold |
| 000810 | 2026-07-23 | 0.7800 | 0.03 | 0.7500 | core | false | no_action | hold |
| 000810 | 2026-07-23 | 0.7800 | 0.03 | 0.7500 | core | false | watch | watch |
| 001450 | 2026-07-22 | 0.7800 | 0.03 | 0.7500 | core | false | watch | watch |
| 001450 | 2026-07-22 | 0.7800 | 0.03 | 0.7500 | core | false | no_action | hold |

이 10건 전부 `entry_score_without_allocation`이 여전히 `0.65`를
넘고, `buy_candidate`는 어차피 `eligibility_passed=false`(507/675,
활동성·유동성 등 다른 하드 게이트) 때문에 `false`다 — 즉 이 표본들의
최종 판정은 애초에 allocation 보정항과 무관했다.

**분포(참고용, Set A 기준)**: `source_type`은 `core` 509 / `event_
overlay` 124 / `market_overlay` 42, `regime_label`은 `bullish_trend`
477 / `bearish_trend` 148 / `range_bound` 50, `risk_tone`은 `risk_
off` 633 / `risk_on` 42, `max_new_capital_pct`는 `3.0` 485 / `2.5`
148 / `4.0` 42로 나뉜다. `eligibility_passed` 분포는 `buy_candidate`
와 정확히 같다(675건 중 168건만 `true` — `buy_candidate`는
`eligibility_passed`가 선행 조건이라 항상 같은 부분집합이다).

**1순위 판정: A. 제거해도 영향 미미.**

근거:
1. **C 집합이 최근 3거래일/1개월/전체 이력 전부 0건**이다 — 근사가
   아니라 관측 가능한 전체 이력을 전수 조회한 결과다.
2. 가장 타이트한 표본(margin `0.0038`)조차 보정항 없이 `0.65`를
   넘겨, "우연히 아슬아슬하게 살아남은" 경계 사례조차 없다.
3. 유일하게 `decision_type=approve`까지 간 표본(`000810`,
   `2026-07-20`)도 보정항 없이 `margin 0.1056`(`0.7556-0.65`)으로
   여유가 크다.
4. `order_requests` 도달 건수 자체가 Set A 전체에서 0건이라, 이
   보정항이 실제 주문 제출 결과에 영향을 준 적도 없다.

**이번 턴 미확인 사항**:
1. `entry_score>=0.65`인 population 전체가 왜 `order_requests`에
   한 건도 도달하지 못했는지(하류 EV gate/AI downgrade 원인 추정,
   실제 규명은 이번 턴 범위 밖).
2. 이 실측은 `max_new_capital_pct`가 `{2.5, 3.0, 4.0}` 3개 값만
   관측된 기간에 한정된다 — 다른 값(예: 더 큰 자본 배정 여유)이
   나오는 국면에서도 C가 계속 0인지는 별도 실측이 필요하다.
3. 제거 vs 하드 게이트 전용 이관, 둘 중 어느 쪽으로 갈지에 대한
   구체적 코드 설계는 이번 턴에서 하지 않았다 — 다음 턴 과제로
   남긴다.

#### 13.2.4 R2 — 자본 보너스 점수 구조 분리(2026-08-02 KST, 동작 무변화 리팩터링)

**목적**: §13.2.3에서 실측한 판정 A(제거해도 영향 미미)를 근거로,
다음 턴에 "제거할지 authoritative 게이트 전용으로 이관할지"를 더
쉽게 판단할 수 있도록 `entry_score_allocation_adjustment`(자본
보너스/패널티 점수)의 계산 구조를 정리한다. 이번 턴은 **제거까지
가지 않고, 명시적 분리 + 소비 지점 정리 준비**까지만 진행했다 —
threshold·gate 기준값·shadow 기준값·reporting 값은 전혀 바꾸지
않았다.

**무엇을 어떤 구조로 분리했는지**: `_build_entry_score()` 안에 인라인
돼 있던 자본 보너스/패널티 블록을 `_build_entry_score_allocation_
adjustment()`라는 독립 helper 함수로 옮겼다. 이 helper는
`portfolio_allocation`과 (reason_codes append용) `reason_codes`만
받아, `max_new_capital_pct>0`이면 `min(0.10, pct/100.0)`, 아니면
`-0.20`을 반환한다(`None`이면 `0.0`). `_build_entry_score()`는 이제
`entry_score_allocation_adjustment = _build_entry_score_allocation_
adjustment(...)`를 호출해 받은 값을 `score`에 더하기만 한다 — **본체
(alpha 대표 점수 + regime/strategy/source-type/activity 보정)와
자본 보너스 점수가 코드상에서 함수 경계로 명확히 나뉜다.**

**왜 동작 무변화인가**:
1. helper의 반환값은 이전 인라인 블록이 계산하던 값과 **글자 그대로
   같은 산술식**이다(`min(0.10, pct/100.0)` / `-0.20` / `0.0`) —
   상수·분기 조건·순서를 하나도 바꾸지 않았다.
2. `reason_codes.append(...)` 두 호출은 helper 내부로 옮겨졌을 뿐,
   호출 시점(즉 `_build_entry_score()`에서 이 블록이 실행되던 바로
   그 위치)은 그대로라 `reason_codes` 리스트의 최종 순서가 바뀌지
   않는다.
3. `_build_entry_score()`의 반환값(`entry_score`), `_build_buy_
   ranking_score()`, authoritative 게이트(§13.1.6의 `entry_score`+
   `allocation_bonus_like` 명시식), core shadow(`0.02`/`0.26`류),
   `event_overlay` shadow(`0.56`), `decision_json` 저장 구조는 전부
   건드리지 않았다 — helper는 순수 함수 추출이라 호출부 시그니처도
   바뀌지 않는다.

**authoritative 경로에서 이 값이 현재 어디서 소비되는지(§13.2.1
매핑 재확인, 재론 없이 인용)**: `entry_score_allocation_adjustment`
는 `_build_entry_score()`가 만드는 `entry_score`에 반영된 뒤,
(1) `buy_candidate_threshold(0.65)` 판정, (2) `_build_buy_ranking_
score()`를 거쳐 저장되는 `ranking_score`, (3) authoritative 게이트
(`_assess_core_risk_off_buy_guard()`의 `entry_score`+`allocation_
bonus_like` 명시식, §13.1.6)에서 각각 다시 쓰인다. 이 세 소비 지점은
§13.2.1/§13.2.3에서 이미 매핑·실측한 그대로이며 이번 턴에 바뀐 것은
없다 — helper 추출은 "계산 근거를 한 곳에서 읽히게" 만드는 구조
정리일 뿐, 소비 지점 자체를 옮기거나 줄이지 않았다.

**실행한 검증과 결과**(변경 파일 기준 좁은 범위, dev tree 직접
mount — 이유는 이전 턴에 이미 문서화, 재논의하지 않음):
- `python3 -m pytest tests/services/test_deterministic_trigger_
  engine.py -v` → **25 passed**(기존 회귀 테스트 전부 무변화로 통과,
  신규 테스트 추가 없음 — 순수 함수 추출이라 기존 테스트만으로
  충분히 고정된다고 판단)
- `python3 -m py_compile src/agent_trading/services/deterministic_
  trigger_engine.py` → 통과(exit 0)
- `python3 -m ruff check src/agent_trading/services/deterministic_
  trigger_engine.py` → All checks passed
- (표준 명령, 별도 production 체크아웃 기준이라 이번 턴 변경 미반영
  — 이전 턴에 이미 문서화한 사유, 재논의하지 않음) `bash scripts/
  harness/run.sh accept backend-file src/agent_trading/services/
  deterministic_trigger_engine.py` → PASS(`tests_run_count=3`,
  `test_failed_count=0`)
- full pytest·KIS 호출·DB write·`.env` 수정은 하지 않았다.

**다음 단계(제거 vs 하드 게이트 이관 판단, 1개)**: §13.2.3에서
판정 A(제거해도 영향 미미)를 실측으로 확인했으므로, 다음 코드 수정
단위는 `_build_entry_score_allocation_adjustment()`의 결과를 **entry_
score에서 완전히 제거할지**, 아니면 **authoritative 게이트 쪽으로
이관해 entry_score와는 별개의 하드 게이트 조건으로만 남길지**를
결정하는 것이다. 이 helper 분리는 그 결정을 코드 레벨에서 실행하기
위한 준비 단계이며, 실제 제거/이관은 이번 턴 범위 밖이다.

#### 13.2.5 R2 — `entry_score`에서 자본 보너스 점수 제거 적용(2026-08-02 KST)

**목적**: §13.2.3의 실측 결론(판정 A: C 집합 = 0건, 제거해도 영향
미미)을 근거로, `entry_score`에서 자본 보너스/패널티 점수를 실제로
제거한다. authoritative 게이트(`core risk-off guard`) 쪽 로직은
이번 턴 범위 밖으로 두고 그대로 유지한다.

**`entry_score`에서 무엇을 제거했는지**: `_build_entry_score()`에서
`_build_entry_score_allocation_adjustment()` helper 호출과
`score += entry_score_allocation_adjustment` 합산을 제거했다. 이
helper가 더 이상 어디에서도 쓰이지 않아, helper 함수 자체도 완전히
삭제했다(재사용 흔적을 남기지 않음). 이 항이 붙이던 `reason_codes`
(`trigger_allocation_budget_available`, `trigger_allocation_budget_
blocked`)도 `entry_score` 경로에서는 함께 사라졌다 — 계산이 아예
실행되지 않으므로 append 자체가 일어나지 않는다.

**authoritative 게이트 쪽에서 무엇을 유지했는지**: `_assess_core_
risk_off_buy_guard()`(§13.1.6)가 자체적으로 계산하는 `allocation_
bonus_like`(`_CORE_RISK_OFF_ALLOCATION_BONUS_WEIGHT=0.10`,
`_CORE_RISK_OFF_ALLOCATION_NORMALIZER_PCT=10.0` 상수 사용)는 전혀
건드리지 않았다. 이 계산은 `_build_entry_score_allocation_
adjustment()`를 호출한 적이 없는 완전히 독립된 코드였으므로(§13.2.4
에서 이미 확인), 이번 제거로 게이트의 **코드**는 한 줄도 바뀌지
않았다. 다만 게이트의 판정식(`0.55*entry_score + 0.10*allocation_
bonus_like`)이 `entry_score`를 입력으로 받으므로, `entry_score`
자체가 낮아지면(또는 `max_new_capital_pct<=0`인 경우 높아지면) 게이트가
계산하는 점수도 **자연스럽게** 함께 이동한다 — 이는 게이트 로직을
바꾼 것이 아니라, 게이트가 참조하는 입력값 하나가 바뀐 결과다.

**"entry_score 값이 실제로 allocation 항만큼 내려가는지" 확인**:
확인됐다. 예를 들어 §13.2.3에서 쓴 대표 fixture(`max_new_capital_
pct=5.0`)는 `entry_score`가 `0.9513→0.9013`으로 정확히 `0.05`
(구 항의 값)만큼 낮아졌고, `max_new_capital_pct=2.5` fixture는
`0.025`만큼 낮아졌다 — 제거 대상 항의 크기와 정확히 일치한다.

**"authoritative 게이트 관련 테스트가 그대로 유지되는지" 확인(중요한
발견)**: **유지되지 않았다** — 다만 이는 게이트 **코드**가 아니라
게이트가 받는 **입력값**(`entry_score`)이 바뀐 결과다. `entry_score`
가 낮아지면서 게이트의 `0.55*entry_score + 0.10*allocation_bonus_
like` 점수도 함께 낮아져, `_CORE_RISK_OFF_RANKING_MIN_SCORE(0.28)`
경계에 걸려 있던 기존 fixture 2건(`test_trigger_engine_marks_risk_
off_exception_eligible_for_strong_core_setup`, `test_trigger_
engine_core_risk_off_ranking_boundary_shifts_by_coverage_score_
weight`)과 그 경계를 그대로 재확인하는 §13.1.6 회귀 테스트
(`test_trigger_engine_core_risk_off_authoritative_score_matches_
ranking_score_formula`)가 실패했다. 이 세 테스트는 게이트 코드가
아니라 **fixture의 경계값**을 재실측해 최소 범위로 보정했다(아래
"경계값 보정" 참고) — 게이트의 `0.28` threshold, 가중치, 계산식은
전혀 바꾸지 않았다.

**경계값 보정(최소 범위, 3건 + 관찰용 shadow 2건)**:

| 테스트 | 무엇이 바뀌었는지 | 보정 내용 |
|---|---|---|
| `test_trigger_engine_marks_risk_off_exception_eligible_for_strong_core_setup` | `entry_score` `0.4725→0.4475`로 게이트 점수가 `0.28` 밑으로 내려감 | fixture `overall` `0.28→0.45`로 상향(실측 재확인, "강한 core setup" 의도 유지) |
| `test_trigger_engine_core_risk_off_ranking_boundary_shifts_by_coverage_score_weight` | 좁은 경계(`overall 0.33/0.34`)가 새 `entry_score` 기준으로는 둘 다 차단 쪽으로 이동 | 경계를 다시 실측해 `overall 0.44(차단)/0.45(통과)`로 갱신 — "완화가 아닌 무변화 리팩터링" 검증 의도는 그대로 |
| `test_trigger_engine_core_risk_off_authoritative_score_matches_ranking_score_formula` | 위와 동일 경계·fixture 재사용 | 위 테스트와 동일하게 `overall 0.44/0.45`로 갱신 |
| `test_trigger_engine_marks_core_risk_off_shadow_floor_moderate_relax`(관찰용) | 관찰용 `ranking_score>=0.26` 절대값을 다시 못 넘김 | fixture `overall` `-0.05→0.00`로 소폭 상향 — 실제 BUY/eligibility 판정과 무관한 순수 관찰용 메타데이터 재조정 |
| `test_trigger_engine_instruments_event_overlay_shadow_lane_metadata`(관찰용) | 관찰용 `_EVENT_OVERLAY_SHADOW_MIN_SCORE=0.56`을 다시 못 넘김 | fixture `overall` `0.75→0.90`로 상향 — 실제 BUY/eligibility 판정과 무관한 순수 관찰용 메타데이터 재조정 |

이 5건 전부 게이트/threshold 상수(`0.28`, `0.26`, `0.56` 등)는 손대지
않고 **입력 fixture만** 재실측해 갱신했다 — "경계값 기대치가 바뀌면
최소 범위로만 보정"이라는 원칙을 지켰다.

**`ranking_score`/shadow/reporting 경로 중 이번 제거와 무관한 부분이
그대로인지 확인**: `_build_buy_ranking_score()` 본문, `_assess_core_
risk_off_buy_guard()` 본문, `_build_core_risk_off_shadow_experiment_
metadata()`, `_build_event_overlay_shadow_experiment_metadata()`
전부 코드 한 줄도 건드리지 않았다. `decision_json` 저장 구조, shadow
threshold(`0.02`/`0.26`류, `0.56`), authoritative threshold(`0.28`)
도 무변화다 — 이번 턴에서 바뀐 것은 오직 `_build_entry_score()`의
자본 보너스/패널티 계산이 사라졌다는 사실 하나뿐이며, 위 표의 값
변화는 전부 그 결과다.

**실행한 검증과 결과**(변경 파일 기준 좁은 범위, dev tree 직접 mount
— 이유는 이전 턴에 이미 문서화, 재논의하지 않음):
- `python3 -m pytest tests/services/test_deterministic_trigger_
  engine.py -v` → **25 passed**(위 표의 5건 경계값 보정 후 전부 통과)
- `python3 -m py_compile src/agent_trading/services/deterministic_
  trigger_engine.py tests/services/test_deterministic_trigger_
  engine.py` → 통과(exit 0)
- `python3 -m ruff check src/agent_trading/services/deterministic_
  trigger_engine.py tests/services/test_deterministic_trigger_
  engine.py` → All checks passed
- (표준 명령, 별도 production 체크아웃 기준이라 이번 턴 변경 미반영
  — 이전 턴에 이미 문서화한 사유, 재논의하지 않음) `bash scripts/
  harness/run.sh accept backend-file src/agent_trading/services/
  deterministic_trigger_engine.py` → PASS(`tests_run_count=3`,
  `test_failed_count=0`)
- full pytest·KIS 호출·DB write·`.env` 수정은 하지 않았다.

**기대 가능한 직접 영향**: `max_new_capital_pct>0`인 population에서
`entry_score`가 `min(0.10, pct/100.0)`만큼 낮아지고, `max_new_
capital_pct<=0`인 population에서는 `entry_score`가 `0.20`만큼
높아진다. §13.2.3 실측(C 집합=0건)에 따라 `buy_candidate_
threshold(0.65)` 판정 자체는 영향이 없을 것으로 예상되지만, 이번
턴은 코드 수정만 진행했고 운영 데이터로 다시 검증하지는 않았다.

**아직 미확인인 운영 영향**:
1. §13.2.3 실측은 `entry_score_allocation_adjustment`가 존재하던
   과거 코드 기준이다. 제거 이후의 실제 운영 데이터로 `entry_score`
   분포·`buy_candidate` 판정이 예상대로 무영향인지는 재실측하지
   않았다.
2. authoritative 게이트 쪽 판정(`risk_off_exception_eligible`)이
   `entry_score` 하락으로 실제 운영에서 얼마나 이동하는지는 이번
   턴에서 정량화하지 않았다 — `entry_score`가 게이트 점수의 입력
   중 하나이므로 이론적으로는 영향이 있을 수 있으나, §13.1.3/§13.2.3
   에서 확인한 실측 population(`max_new_capital_pct∈{2.5,3.0,4.0}`)
   기준 게이트 점수 이동폭은 최대 `0.55*0.04=0.022`로 작다는 점만
   대수적으로 확인했고, 실제 표본 재집계는 다음 턴 과제로 남긴다.
3. `max_new_capital_pct<=0`인 population(entry_score가 오히려
   높아지는 방향)에 대한 영향은 이번 턴에서 별도로 실측하지 않았다.

#### 13.2.6 R2 — `entry_score` 내부 regime/risk 보정항 정리 여부 판정(2026-08-02 KST, read-only 분석)

**목적**: allocation 항 제거(§13.2.5)가 끝난 지금, R2의 다음 후보인
`entry_score` 내부 regime/risk 보정항이 "제거/이관 후보로 확정
가능한지"를 좁힌다. 이번 턴은 코드 수정 없이 read-only 분석만
진행했다.

**전제(이미 닫힌 사실, 재검증하지 않음)**: R1 정리(§13.1.1~§13.1.6),
R2 allocation 4분류·실측·구조 분리·제거(§13.2.1~§13.2.5) — 전부
참조만 하고 다시 열지 않는다. `strategy`, `source-type`, `alpha`
항목은 이번 턴 범위 밖으로 유지한다. `activity` 항목은 §13.4(R4)
연계 축이므로 섞지 않는다.

**(1) `entry_score` 안의 regime/risk 보정항 — 정확한 코드 위치**

`_build_entry_score()`(`deterministic_trigger_engine.py` 1229~1238행)
안의 다음 블록이다.

```text
if market_regime is not None:
    if market_regime.regime_label == "bullish_trend":
        score += 0.10                      # trigger_bullish_regime
    if market_regime.risk_tone == "risk_on":
        score += 0.05                      # trigger_risk_on
    if market_regime.risk_tone == "risk_off":
        score -= 0.15                      # trigger_risk_off_penalty
```

이 블록은 **단일 항목이 아니라 서로 다른 발동 조건을 가진 3개의
하위 조건**이다 — 이 구분이 이번 절 판정의 핵심이다.

**(2) BUY 경로 내 중복 반영 경로 — 전수 매핑**

| 소비처 | 조건/역할 | 판정 성격 | `entry_score` regime/risk 블록과의 관계 |
|---|---|---|---|
| `entry_score`의 regime/risk 블록(현재 분석 대상) | `bullish_trend`+`0.10`, `risk_on`+`0.05`, `risk_off`-`0.15` | soft 가중치 | — |
| `_is_core_risk_off_regime()` → `core_risk_off_guard_active` | `risk_tone=="risk_off" and regime_label=="bearish_trend"`일 때만 `True` | hard 게이트 **활성화 조건** | `risk_off` 서브조건과 **정확히 같은 원신호**를 별도로 재확인 |
| `_assess_buy_eligibility()`의 risk_off 블록(449~497행) | `risk_tone=="risk_off" and regime_label=="bearish_trend"`이면 `risk_off_exception_eligible` 없이는 하드 차단 | hard 게이트 | 위 `_is_core_risk_off_regime()`와 **완전히 동일한 조건식을 별도 함수에서 다시 계산**(코드 레벨 재계산 중복) |
| AI context(`prompt_context_projection.py` regime_label/risk_tone 주입) | `regime_label`/`risk_tone` 원문을 프롬프트에 삽입 | reporting/컨텍스트 제공 | 원신호를 그대로 노출(AI가 참고, 하드 게이트 아님) |
| `decision_factory.py`의 `regime_label` 저장 | `trade_decisions.regime_label` 컬럼에 저장 | 순수 리포팅 | 판정에 되먹임되지 않음 |
| `expected_value_gate.py`(EV gate) | 참조 없음(코드 전수 검색 결과 0건) | 무관 | — |
| `regime_switch_v1` 게이트(`regime_switch_gate.py`, §21) | 별도 모니터링 신호(`regime_switch_v1_trigger_status`) 기반, `classify_market_regime()`이 만드는 이 `market_regime`과 **입력 자체가 다름** | 무관(다른 시스템) | 이름만 "regime"이 겹칠 뿐 서로 다른 개념 — 혼동 주의 |
| `_build_exit_ranking_score()`/`_build_exit_score()`의 regime 항 | `bearish_trend`+`0.6`(exit ranking 내부), `bearish_trend`+`risk_off` 가산(exit score) | SELL/EXIT 경로 전용 | BUY 경로 범위 밖(문서 §2 scope 그대로 유지, 재론 안 함) |

**(3) 정당한 분리 vs 과잉 중복 판정 — 서브조건별로 나뉜다**

regime/risk 블록은 하나의 항목처럼 보이지만, 실제로는 중복 성격이
서로 다른 두 그룹으로 나뉜다.

- **`risk_off` 서브조건(`-0.15`)**: `core_risk_off_guard_active`
  판정과 `_assess_buy_eligibility()`의 하드 차단이 **정확히 같은
  원신호(`risk_tone=="risk_off" and regime_label=="bearish_
  trend"`)를 이미 두 곳에서 하드 게이트로 쓰고 있다.** `entry_score`
  의 `-0.15`는 이 신호를 **세 번째로**, 그것도 이미 이분법적으로
  하드 게이트가 걸린 상황에 대해 soft 페널티를 추가하는 것이라
  **과잉 중복에 가깝다** — allocation 항이 authoritative 게이트의
  `allocation_bonus_like`와 같은 신호를 이중 반영했던 구조(§13.1.6/
  §13.2.3)와 매우 유사하다.
- **`bullish_trend`(`+0.10`)/`risk_on`(`+0.05`) 서브조건**: BUY
  경로에는 이에 대응하는 **하드 게이트가 없다**(하드 게이트는
  `bearish_trend`+`risk_off` 쪽에만 존재). AI 컨텍스트에 원문이
  노출되긴 하지만 그건 판정에 되먹임되지 않는 참고자료다. 즉 이
  두 서브조건은 alpha 보정과 유사하게 **정당한 역할(연속적이지는
  않지만 유일한 soft 가중치)로 볼 여지가 있다** — 다만 alpha처럼
  연속값이 아니라 이산 라벨이라는 점은 여전히 남는 특징이다.

**결론: regime/risk 블록 전체를 "제거해도 영향 미미"라고 단정할 수
없다** — `risk_off` 서브조건만 allocation과 유사한 과잉 중복
구조이고, `bullish_trend`/`risk_on` 서브조건은 하드 게이트 대응쌍이
없어 성격이 다르다. 하나의 판정으로 뭉뚱그리면 §13.2.3 같은 실측
없이 성급하게 제거 범위를 넓히는 위험이 있다.

**(4) 규모 참고(read-only DB 조회, 전면 실측 아님 — changed-scope
수준의 근거만 수집)**: `trading_db`에서 `side='buy'`, `entry_score`
가 존재하는 전체 이력 기준으로 `regime_label`×`risk_tone` 조합별
건수를 확인했다.

| `regime_label` | `risk_tone` | 건수 | `entry_score>=0.65` | `entry_score∈[0.50,0.65)` |
|---|---|---|---|---|
| `bearish_trend` | `risk_off` | 24,211 | 148 | 50 |
| `bullish_trend` | `risk_off` | 7,922 | 439 | 3,556 |
| `range_bound` | `risk_off` | 7,303 | 50 | 74 |
| (없음) | (없음) | 1,947 | 0 | 395 |
| `range_bound` | `neutral` | 231 | 0 | 78 |
| `event_driven_unstable` | `risk_off` | 64 | 0 | 0 |
| `bullish_trend` | `risk_on` | 42 | 42 | 0 |
| `event_driven_unstable` | `neutral` | 4 | 0 | 4 |

`risk_off` 서브조건(패널티 `-0.15`)이 적용되는 population은
`24,211+7,922+7,303+64=39,500`건으로 전체 buy-path 표본의 대다수를
차지한다. `risk_on` 서브조건(보너스 `+0.05`)이 적용되는 population은
`42`건뿐으로 극히 작다. 이 규모 차이 자체가 다음 턴 실측 설계의
우선순위(어느 서브조건부터 §13.2.3 방식으로 실측할지)를 정하는 데
직접적인 근거가 된다 — 다만 이 표는 규모 확인용이며, `entry_score
- regime_risk_adjustment < 0.65 <= entry_score`인 C 집합 계산은
이번 턴에서 수행하지 않았다.

**(5) 다음 코드 수정 단위 — A/B/C 중 어디까지 좁힐 수 있는가**

**B. read-only 실측 먼저**로 좁힌다. 근거:
1. `risk_off` 서브조건은 allocation과 유사한 과잉 중복 구조로
   보이지만, allocation과 달리 **적용 population이 39,500건으로
   훨씬 크고**, 이 서브조건이 활성화되는 상황은 정확히
   `core_risk_off_guard_active=true`인 상황과 겹친다 — §13.1.3/
   §13.2.3와 같은 방식으로 "이 항 덕분에만 `0.65`를 넘긴 표본"(C
   집합)을 먼저 실측하지 않고 구조 분리·제거로 바로 가면, allocation
   때보다 훨씬 큰 population에 대한 근거 없는 변경이 된다.
2. `bullish_trend`/`risk_on` 서브조건은 하드 게이트 대응쌍이 없어
   "제거 후보"로 판정하기엔 근거가 약하고, 오히려 §13.2.1의 "유지"
   판정에 더 가깝다 — 이 부분은 A(무변화 구조 분리)조차 아직 이르며,
   먼저 "정말 제거 후보가 맞는지" 자체를 다시 봐야 한다.
3. 결과적으로 규모가 유의미한 `risk_off` 서브조건 하나만 골라
   §13.2.3과 같은 방법론(C 집합 실측)을 먼저 적용하는 것이 다음
   턴의 1순위 권고안이다 — `bullish_trend`/`risk_on` 서브조건은
   이번 턴 결과대로 "유지" 판정을 유지한 채 별도로 다시 열지 않는다.

**아직 미확인 사항**:
1. `risk_off` 서브조건(entry_score의 `-0.15`)이 `buy_candidate_
   threshold(0.65)`에 실제로 얼마나 기여하는지(§13.2.3과 같은 C
   집합 실측)는 이번 턴에서 수행하지 않았다 — 다음 턴 과제.
2. `_is_core_risk_off_regime()`와 `_assess_buy_eligibility()`가
   같은 조건식을 각자 재계산하는 코드 레벨 중복(구현상 중복, 판정
   결과와는 무관)의 정리 필요성은 이번 턴에서 판단하지 않았다 —
   R2 범위인지 별도 정리 트랙인지도 다음 턴에 정할 사안이다.
3. `bullish_trend`+`risk_on`(`42`건)처럼 작은 population에 대한
   서브조건별 세부 실측은 규모상 우선순위가 낮다고 판단했으나,
   완전히 배제한 것은 아니다.

#### 13.2.7 R2 — `entry_score` 내부 `risk_off -0.15` 서브조건 기여도 실측(2026-08-03 KST, read-only)

**목적**: §13.2.6에서 판정한 "다음 코드 수정 단위 = B(read-only 실측
먼저)"에 따라, `entry_score`의 `risk_off -0.15` 서브조건 하나만을
대상으로 §13.2.3(allocation)과 같은 방법론으로 `buy_candidate_
threshold(0.65)` 기여도를 실측한다. `bullish_trend +0.10`/`risk_on
+0.05`는 이번 턴에서 다시 열지 않는다. 코드는 변경하지 않았다.

**전제(이미 닫힌 사실, 재검증하지 않음)**: R1 정리(§13.1.1~§13.1.6),
R2 allocation 4분류·실측·구조 분리·제거(§13.2.1~§13.2.5), regime/risk
서브조건 분해·매핑(§13.2.6, `risk_off` 서브조건만 과잉 중복 후보로
판정) — 전부 참조만 하고 다시 열지 않는다.

**조회 방법**: `trading_db`(PostgreSQL) 컨테이너에 read-only
`SELECT`로 직접 접속해 `trading.trade_decisions.decision_json`에서
`deterministic_trigger.entry_score`, `deterministic_trigger.buy_
candidate`, `deterministic_trigger.metadata.risk_tone`,
`deterministic_trigger.metadata.regime_label`, `candidate_vs_final.
final_intent`, `decision_type`을 추출했다. `side='buy'` 필터만
적용했고, DB write·KIS 호출·코드 수정은 하지 않았다.

**`risk_off -0.15` 적용 위치 재확인**: `_build_entry_score()`
1236~1238행 —

```text
if market_regime.risk_tone == "risk_off":
    score -= 0.15                      # trigger_risk_off_penalty
```

`regime_label`과 무관하게 `risk_tone=="risk_off"`이기만 하면 항상
적용된다(`bullish_trend`의 `+0.10`과 동시에 적용될 수 있음 — 실제로
아래 실측 population 대부분이 `regime_label="bullish_trend"`다).

**집합 정의**: B = `risk_tone=="risk_off"`가 적용된 전체 표본. A =
B 중 `entry_score>=0.65`(현재 통과). C = B 중 현재 `entry_score<0.65`
이지만 `entry_score+0.15>=0.65`(패널티 때문에만 차단, 즉 `entry_
score∈[0.50,0.65)`). D = A 중 `entry_score+0.15>=0.65`(패널티를
없애도 여전히 통과 — A와 필연적으로 동일하다, 아래 확인).

**새로 확인한 사실 1(집계 창별 비교표, row 기준)**:

| 집계 창 | B(전체) | A(현재 통과) | C(패널티 때문에만 차단) | D(패널티 없어도 통과) |
|---|---|---|---|---|
| 최근 3거래일(08-01~08-03, 08-01/08-02는 주말이라 실제 거래일은 07-30·07-31·08-03) | 2,586 | 155 | 472 | 155 |
| 최근 1개월(07-04~08-03) | 23,293 | 640 | 1,733 | 640 |
| 전체 이력(06-19~08-03) | 39,530 | 640 | 3,692 | 640 |

**D = A는 수학적으로 자명하다** — `risk_off -0.15`는 패널티이므로
이를 제거(즉 `+0.15`)하면 점수는 커지기만 하고 작아지지 않는다.
따라서 이미 `0.65`를 넘은 A 표본은 패널티를 없애도 반드시 그대로
통과한다(D=A=640건, 실측으로 확인). **allocation 항(§13.2.3)이
보너스였던 것과 반대로 `risk_off`는 패널티라, "덕분에만 통과"(C
집합, allocation 쪽 개념)가 아니라 "패널티 때문에만 차단"(C 집합,
이번 절 개념)이 실측 대상이라는 점이 방향상의 차이다.**

**새로 확인한 사실 2(핵심 결과, allocation과 다름)**: **C 집합이
0건이 아니다.** 전체 이력 `3,692`건, 최근 1개월 `1,733`건, 최근
3거래일 `472`건이 `risk_off -0.15` 패널티 때문에만 `0.65` 문턱
아래로 내려가 있다.

**새로 확인한 사실 3(distinct `symbol`+거래일 기준)**:

| 집계 창 | distinct symbol(C) | distinct symbol+거래일 조합(C) |
|---|---|---|
| 최근 3거래일 | 10 | 10 |
| 최근 1개월 | 14 | 31 |
| 전체 이력 | 27 | 89 |

row 기준 결론과 같은 방향이다 — 특정 하루 반복 호출에 몰린 소수
종목의 편중이 아니라, **27개 서로 다른 종목·89개 서로 다른 종목+
거래일 조합**에 걸쳐 나타나는 표본이라 "distinct 기준으로도 같은
결론이 유지된다."

**상위 10건**(distinct `symbol`+거래일, `entry_score` 내림차순 —
문턱에 가장 가까웠던 사례):

| symbol | 거래일(KST) | entry_score | entry_score_without_risk_off_penalty | regime_label | buy_candidate | final_intent | decision_type |
|---|---|---|---|---|---|---|---|
| 073240 | 2026-08-03 | 0.6434 | 0.7934 | bullish_trend | false | no_action | hold |
| 000810 | 2026-07-28 | 0.6200 | 0.7700 | bullish_trend | false | no_action | hold |
| 000810 | 2026-07-28 | 0.6200 | 0.7700 | bullish_trend | false | watch | watch |
| 000810 | 2026-07-27 | 0.6200 | 0.7700 | bullish_trend | false | no_action | hold |
| 000810 | 2026-07-27 | 0.6200 | 0.7700 | bullish_trend | false | watch | watch |
| 000660 | 2026-06-29 | 0.6086 | 0.7586 | bullish_trend | false | watch | watch |
| 000660 | 2026-06-29 | 0.6086 | 0.7586 | bullish_trend | false | no_action | hold |
| 000660 | 2026-06-25 | 0.6085 | 0.7585 | bullish_trend | false | no_action | hold |
| 000660 | 2026-06-25 | 0.6085 | 0.7585 | bullish_trend | false | watch | watch |
| 000660 | 2026-06-26 | 0.6065 | 0.7565 | bullish_trend | false | watch | watch |

상위 10건 전부 `regime_label="bullish_trend"`다 — `risk_off` 패널티
(`-0.15`)와 `bullish_trend` 보너스(`+0.10`)가 **동시에 적용돼 순
`-0.05`만큼만 순감소**했음에도 불구하고, `entry_score`가 원래
`0.65` 부근이었던 표본에서는 이 순감소만으로 문턱을 넘지 못했다.

**새로 확인한 사실 4(`decision_type=approve`/`order_requests`와의
관계, 실제 사례)**: A 집합(24건 `approve`, `order_requests` 도달
`0`건)과 달리, **C 집합에서 `approve`이자 실제 `order_requests`에
도달(체결)한 사례가 1건 있었다**:

- `symbol=011070`, `2026-06-19 11:03:51 KST`, `entry_score=0.5647`
  (패널티 제거 시 `0.7147`), `regime_label=bullish_trend`,
  `buy_candidate=false`(결정론적 게이트는 차단), `final_intent=buy`,
  `decision_type=approve`, `order_requests.status=filled`.

즉 **결정론적 `buy_candidate` 게이트는 `risk_off` 패널티 때문에
이 표본을 차단했지만, AI가 이를 override해 실제로 매수해 체결까지
갔다.** 이는 `risk_off` 패널티가 결정론적 게이트와 AI 최종 판단
사이에 실제 괴리를 만든 구체적 사례이며, allocation 실측(§13.2.3,
`order_requests` 도달 `0`건)에서는 나타나지 않았던 종류의 결과다.

**1순위 판정: C. 실제 BUY 경로에 유의미하다.**

근거:
1. C 집합이 세 집계 창 모두 **0건이 아니며**, 전체 이력 `3,692`건
   (해당 population의 약 `9.3%`)에 달한다 — allocation 항(§13.2.3,
   전 구간 `0`건)과 명확히 다른 결과다.
2. distinct `symbol`+거래일 기준으로도 `27`개 종목·`89`개 조합에
   걸쳐 나타나 특정 표본 편중이 아니다.
3. C 집합 안에 실제로 `decision_type=approve`이자 `order_requests`
   에서 체결까지 간 사례(`011070`, `2026-06-19`)가 존재한다 —
   결정론적 게이트와 AI 최종 판단이 이 패널티 하나 때문에 실제로
   어긋난 구체적 증거다.

**다음 턴 1순위 권고안**: allocation 때처럼 곧바로 "제거" 코드
수정으로 가지 않는다. C 집합 규모와 실제 override 사례(011070)가
보여주듯, `risk_off` 패널티는 최소한 일부 population에서 결정론적
게이트의 판정을 실질적으로 바꾸고 있어 "제거해도 영향 미미"라고
할 수 없다. 대신 **R1(§13.1.2)에서 썼던 A/B/C 설계 비교 패턴**을
다음 턴에 적용해, `risk_off` 패널티를 (A) 그대로 유지, (B) 계수만
줄이는 완화, (C) `entry_score`에서 제거하고 필요하면 eligibility의
기존 하드 게이트(`risk_off`+`bearish_trend` 차단)만 남기는 안 —
세 방향의 blast radius와 근거를 비교하는 **설계 검토**부터 시작할
것을 권고한다. 코드 수정은 그 설계 검토 이후로 미룬다.

**아직 미확인인 것**:
1. `risk_off` 패널티를 제거·완화했을 때 하류(EV gate, AI downgrade,
   최종 submit)에서 override 빈도가 실제로 줄어드는지는 이번 턴에서
   확인하지 않았다 — `011070` 1건은 override가 이미 일어나고 있다는
   사실만 보여준다.
2. `bullish_trend` 보너스(`+0.10`)와 `risk_off` 패널티(`-0.15`)가
   동시에 적용되는 population(상위 10건 전부 해당)에서 두 서브조건을
   함께 조정할 필요가 있는지는 §13.2.6에서 이미 "`bullish_trend`는
   유지"로 판정했으므로 이번 턴에서 재검토하지 않았다.
3. A/B/C 설계 비교 자체는 다음 턴 과제이며 이번 턴에서 수행하지
   않았다.

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

1. **R1**: [2026-08-01 KST 갱신] 판정 완료(C, 13.1.1) — [2026-08-02
   KST 갱신] 대체 contract 설계 비교(13.1.2)에 이어 착수 전 마지막
   실측(13.1.3)까지 마쳤다. 실측 결과 `threshold ÷ 0.55` 단순
   재정규화는 `ranking_score ∈ [0.28, 0.38]` 구간 표본을 전량 뒤집는다
   — [2026-08-02 KST 재갱신] 새 threshold 산정안 비교(13.1.4)에서
   **보조 조건 병행(기존 산식 인라인 재현) 안을 권고**한다. 근사가
   없어 과완화/과차단 위험이 없고, 다음 턴 바로 코드 수정 초안 작성
   가능한 수준으로 좁혀졌다. **[2026-08-02 KST 4차 갱신] C안 코드
   수정 초안까지 적용 완료(13.1.5)** — `_assess_core_risk_off_buy_
   guard()`가 `ranking_score` 대신 `entry_score`+`portfolio_
   allocation`을 받아 authoritative 게이트 전용 점수를 그 자리에서
   재계산하도록 바꿨고, 좁은 범위 검증(단위 테스트 24건, lint) 전부
   통과했다. `ranking_score` 필드·shadow·reporting 경로는 전부 무변화.
   **[2026-08-02 KST 5차 갱신] authoritative 게이트 명시식 2차 수정
   완료(13.1.6)** — `_build_buy_ranking_score()` 재호출을 제거하고,
   게이트 안에서 `entry_score`+`allocation_bonus_like`를 직접 계산하는
   명시식으로 바꿨다. 신규 회귀 테스트로 두 산식의 일치를 고정했고,
   dev tree를 직접 mount한 임시 컨테이너에서 25 passed 확인(로컬
   harness 표준 명령은 별도 production 체크아웃을 테스트하므로 병행
   실행)
2. **R2**: [2026-08-02 KST 갱신, 착수 준비] `entry_score` 내부 6개
   항목(alpha/regime·risk/allocation/strategy/source-type/activity)을
   전수 분해하고 BUY 경로 재사용을 매핑 완료(13.2.1). alpha·strategy·
   source-type은 유지, regime/risk·activity는 점수 밖 이관 검토,
   allocation은 **중복 제거 최우선 후보**로 판정했다. 다음 1순위 코드
   수정 단위로 "`entry_score`의 allocation 보정항을 지역 변수로
   명시적으로 분리하는 무변화 리팩터링"을 권고한다 — 다음 턴 바로
   코드 수정 초안 작성 가능한 수준. **[2026-08-02 KST 재갱신] R2 1차
   단위 적용 완료(13.2.2)** — `_build_entry_score()`의 allocation
   블록을 `entry_score_allocation_adjustment` 지역 변수로 분리했다
   (수치·threshold·shadow·reporting 전부 무변화). dev tree 직접 mount
   임시 컨테이너에서 25 passed 확인. 제거/이관 여부 판단은 운영 실측
   후 다음 턴으로 넘긴다. **[2026-08-02 KST 3차 갱신] 기여도 실측
   완료(13.2.3)** — `entry_score_allocation_adjustment` 덕분에만
   `buy_candidate_threshold(0.65)`를 넘긴 표본(C 집합)은 최근
   3거래일/1개월/전체 이력 모두 **0건**이었다. **판정 A(제거해도
   영향 미미)**를 권고하며, 다음 코드 수정 단위(제거 vs 하드 게이트
   전용 이관)는 다음 턴 과제로 남긴다. **[2026-08-02 KST 4차 갱신]
   자본 보너스 점수 구조 분리 완료(13.2.4)** — 인라인 블록을
   `_build_entry_score_allocation_adjustment()` helper로 추출해
   entry_score 본체와 함수 경계로 명확히 나눴다(동작 무변화, dev
   tree 직접 mount 검증 25 passed). 다음 턴은 이 helper를 대상으로
   제거 vs 하드 게이트 전용 이관을 결정한다. **[2026-08-02 KST 5차
   갱신] entry_score에서 자본 보너스 점수 제거 적용 완료(13.2.5)** —
   `_build_entry_score_allocation_adjustment()` 호출·helper 자체를
   제거했다. authoritative 게이트(§13.1.6)의 `allocation_bonus_like`
   코드는 무변화로 유지했으나, `entry_score`가 입력으로 들어가는
   구조상 게이트 관련 fixture 5건(authoritative 2건 + 관찰용 shadow
   2건 + §13.1.6 회귀 테스트 1건)의 경계값을 재실측해 최소 범위로
   보정했다. dev tree 직접 mount 검증 25 passed. **[2026-08-02 KST
   6차 갱신] regime/risk 보정항 정리 여부 판정(13.2.6, read-only)** —
   regime/risk 블록은 `bullish_trend`(+0.10)/`risk_on`(+0.05)/
   `risk_off`(-0.15) 3개 서브조건으로 나뉘며, **`risk_off` 서브조건만
   `core_risk_off_guard_active`·eligibility 하드 게이트와 같은
   원신호를 중복 반영**(과잉 중복에 가까움, population 39,500건)하고,
   `bullish_trend`/`risk_on` 서브조건은 대응하는 하드 게이트가 없어
   "유지" 판정에 가깝다. 다음 코드 수정 단위는 **B(read-only 실측
   먼저)**로 좁혔다 — `risk_off` 서브조건에 대해 §13.2.3과 같은
   방법론(C 집합 실측)을 다음 턴에 적용한다. **[2026-08-03 KST 7차
   갱신] `risk_off -0.15` 기여도 실측 완료(13.2.7)** — allocation과
   달리 **C 집합이 0건이 아니다**(전체 이력 3,692건/27종목/89
   symbol+거래일 조합, 최근 1개월 1,733건, 최근 3거래일 472건).
   C 집합 안에 `decision_type=approve`이자 `order_requests`
   체결까지 간 실제 사례(`011070`, `2026-06-19`)도 확인됐다. **판정
   C(실제 BUY 경로에 유의미)**로, 곧바로 제거하지 않고 A/B/C 설계
   비교(§13.1.2 패턴)부터 다음 턴에 진행할 것을 권고한다
3. **R3/R4**: allocation/activity를 점수 밖으로 내릴지 검토
4. **R5**: 상류 결정 이후 하류 연쇄 영향 확인

즉 현재는 "BUY 경로 전체 리팩터링"이라는 이름보다,
**R1(판정 완료)→R2→R3/R4→R5의 단계적 리팩터링**으로 보는 것이 정확하다.
