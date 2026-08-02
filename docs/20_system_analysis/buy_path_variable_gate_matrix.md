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
