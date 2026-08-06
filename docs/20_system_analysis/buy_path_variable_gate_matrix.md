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

#### 13.2.8 R2 — `risk_off -0.15` 처리 방식 A/B/C 설계 비교(2026-08-03 KST, read-only 설계 검토)

**목적**: §13.2.7에서 확인한 대로 `risk_off -0.15`는 allocation 항과
달리 C 집합이 0건이 아니고(전체 이력 3,692건, 실제 체결 사례
`011070` 포함) 실제 BUY 경로에 유의미했다. 이번 절은 그 전제를 바탕
으로 곧바로 제거하지 않고, R1(§13.1.2)에서 썼던 것과 같은 A/B/C
설계 비교로 다음 코드 수정 단위를 좁힌다. 코드는 변경하지 않았다.

**전제(이미 닫힌 사실, 재검증하지 않음)**: R1 정리(§13.1.1~§13.1.6),
R2 allocation 4분류·실측·구조 분리·제거(§13.2.1~§13.2.5), regime/risk
서브조건 분해·매핑(§13.2.6), `risk_off -0.15` 기여도 실측(§13.2.7,
판정 C) — 전부 참조만 하고 다시 열지 않는다. `bullish_trend +0.10`/
`risk_on +0.05`는 이번 턴에서도 다루지 않는다.

**전제 재확인(코드 read-only)**: `_build_entry_score()`
1236~1238행의 `if market_regime.risk_tone == "risk_off": score -=
0.15`는 `regime_label`과 **무관하게** 적용된다. 반면 하드 게이트
쪽(`_is_core_risk_off_regime()`, `_assess_buy_eligibility()`의
risk_off 블록)은 둘 다 `risk_tone=="risk_off" AND regime_label==
"bearish_trend"`라는 **더 좁은 조합**에서만 발동한다. 이 범위
차이가 이번 설계 비교의 핵심이다.

**새로 확인한 사실(이번 턴, §13.2.7 C 집합의 `regime_label` 분해)**:
§13.2.7의 C 집합(전체 이력 3,692건)을 `regime_label`별로 나누면 —

| `regime_label` | C 집합 내 건수 | 하드 게이트 커버 여부 |
|---|---|---|
| `bullish_trend` | 3,616 (97.9%) | **커버 안 됨**(하드 게이트는 `bearish_trend`에서만 발동) |
| `range_bound` | 74 (2.0%) | 커버 안 됨 |
| `bearish_trend` | 50 (1.4%) | 커버됨(단, 이 경우도 `risk_off_exception_eligible` 여부에 따라 최종 판정은 별도) |

**즉 C 집합의 98.6%(3,666/3,692건)는 하드 게이트가 전혀 손대지 않는
population이다** — 이 population에서 `entry_score`의 `risk_off
-0.15`는 "이미 하드 게이트가 막고 있는 것을 soft하게 한 번 더
막는 중복"이 아니라, **하드 게이트가 아예 존재하지 않는 곳에서
유일하게 작동하는 restraint**다. `011070`(2026-06-19 KST 체결
사례, `regime_label=bullish_trend`)이 바로 이 98.6% population에
속한다.

**(1) A/B/C 각 안의 의미상 차이**

- **A안(유지)**: `risk_off -0.15`를 손대지 않는다. `risk_tone==
  "risk_off"`라는 신호가 `regime_label`과 무관하게 항상 entry_score
  를 `0.15`만큼 낮춘다는 현재 동작을 그대로 둔다.
- **B안(계수 완화)**: 같은 신호를 계속 반영하되 가중치만 낮춘다
  (후보값 `-0.10` 또는 `-0.05`, 정확한 수치는 이번 턴에서 확정하지
  않고 후보로만 다룬다). "risk_off 상황에서는 진입을 다소 보수적으로
  본다"는 의도는 유지하되, 그 보수성의 크기를 줄인다.
- **C안(entry_score에서 제거, 하드 게이트만 유지)**: `entry_score`
  에서 이 신호를 완전히 빼고, 남는 restraint는 `bearish_trend`+
  `risk_off` 조합에서만 발동하는 기존 하드 게이트뿐이다.

**(2) A/B/C가 BUY 경로 각 단계에 주는 영향**

| 단계 | A안(유지) | B안(계수 완화) | C안(제거) |
|---|---|---|---|
| `buy_candidate_threshold(0.65)` | 무변화 — C 집합(3,692건) 계속 차단 | 계수에 비례해 일부만 완화(정확한 규모는 계수 확정 후 재실측 필요) | C 집합 전체(3,692건)가 통과 가능해짐 |
| `ranking_score`(`0.55*entry_score+...`) | 무변화 | `entry_score` 변화폭의 `0.55`배만큼 함께 이동 | 동일하게 `0.55`배만큼 이동(가장 큰 폭) |
| core risk-off guard(authoritative, §13.1.6) | 무변화 — 게이트 자체는 `entry_score`를 입력으로만 받고 `regime_label`/`risk_tone`을 직접 재확인하지 않음 | `entry_score`가 입력이라 게이트 점수도 비례 이동, 다만 게이트 **코드**는 무변화 | 게이트 점수가 가장 크게 이동(코드는 여전히 무변화) |
| `risk_off_exception_eligible` | 무변화 — 이 값은 `_is_core_risk_off_regime()`/`_assess_buy_eligibility()`가 `regime_label`/`risk_tone`을 직접 보고 판정하므로 `entry_score`와 **무관** | 무변화(같은 이유) | 무변화(같은 이유) |
| AI context(`prompt_context_projection.py`) | 무변화 — `regime_label`/`risk_tone` 원문 노출은 `entry_score`와 별개 경로 | 무변화 | 무변화 |
| EV gate | 무변화(애초에 이 신호를 참조하지 않음, §13.2.6에서 확인) | 무변화 | 무변화 |

`risk_off_exception_eligible`이 A/B/C 어느 안에서도 무변화라는 점은
중요하다 — 이 값은 `entry_score`가 아니라 `market_regime`을 직접
보고 정해지므로, `entry_score` 쪽 조정은 `bearish_trend`+`risk_off`
population의 **최종 예외 판정 자체를 바꾸지 않는다.** A/B/C의 실제
차이는 전부 `buy_candidate_threshold(0.65)`와 그로부터 파생되는
`ranking_score`/게이트 점수 쪽에서만 나타난다.

**(3) 변경 범위와 부작용 범위**

| 축 | A안 | B안 | C안 |
|---|---|---|---|
| 코드 변경 범위 | 없음 | `_build_entry_score()` 안 상수 1개(`-0.15 → 후보값`) | `_build_entry_score()`의 블록 삭제(§13.2.5에서 이미 적용한 allocation 블록 제거와 같은 패턴) |
| diff 난이도 | 없음 | 매우 낮음(상수 1개) | 낮음(블록 삭제, 호출부 변경 없음) |
| 부작용 범위(핵심) | 없음(현상 유지) — 다만 `011070`류 override 마찰은 계속 발생 | C 집합의 일부만 완화 — 계수가 작을수록 완화 폭이 커지지만, 정확한 규모는 이번 턴에서 실측하지 않음 | **C 집합의 98.6%(3,666건)에 대해 restraint가 완전히 사라짐** — 하드 게이트가 이 population을 전혀 커버하지 않기 때문 |
| 하드 게이트/shadow/reporting 영향 | 없음 | 없음(하드 게이트는 `entry_score`를 참조하지 않음) | 없음(같은 이유) |
| 근거 확실성 | 높음(§13.2.7 실측 그대로 유지) | **낮음**(계수 선택 근거가 아직 없음) | 높음(§13.2.7 + 이번 절의 regime_label 분해로 부작용 범위가 정량적으로 확인됨) |

**(4) 왜 이번에는 곧바로 제거하면 안 되는가 — allocation 항 제거와의
차이**

allocation 항(§13.2.3~§13.2.5)을 제거할 수 있었던 근거는 두 가지
였다 — (a) C 집합이 **0건**이었고, (b) authoritative 게이트가 같은
신호(`allocation_bonus_like`)를 이미 수학적으로 동일하게 반영하고
있어 entry_score 쪽 항을 빼도 **판정에 실질적 공백이 생기지
않았다.** 이번 `risk_off -0.15`는 이 두 조건을 **모두** 충족하지
못한다 — (a) C 집합이 3,692건으로 유의미하고, (b) 하드 게이트의
커버리지(`bearish_trend`+`risk_off`)가 soft penalty의 커버리지
(모든 `regime_label`+`risk_off`)보다 훨씬 좁아 **C안으로 제거하면
98.6% population에서 안전망 없는 완화**가 된다. 즉 allocation은
"완전한 중복 제거"였지만, `risk_off -0.15`의 C안은 "중복 제거"가
아니라 "실질적 완화(relaxation)"에 해당한다.

**(5) 다음 코드 수정 단위 — A/B/C 중 어디까지 좁힐 수 있는가**

**B. 추가 실측 1건 필요**로 좁힌다. 근거:
1. A/B/C의 구조적 차이와 핵심 트레이드오프(하드 게이트 커버리지
   격차, 98.6% 대 1.4%)는 이번 턴에 정량적으로 확인됐다 — "아직
   설계 부족"(C 판정)은 아니다.
2. 다만 B안(계수 완화)을 실제로 채택하려면 **후보 계수(예: `-0.10`,
   `-0.05`)별로 C 집합이 얼마나 줄어드는지**를 §13.2.7과 같은
   방법론으로 재실측해야 한다 — 계수 선택 근거가 아직 없어 "바로
   초안 가능"(A 판정)이라 하기엔 이르다.
3. C안은 이번 턴 실측으로 이미 "권고하지 않음" 판정이 섰으므로,
   다음 실측은 B안의 계수 확정에 집중하면 된다.

**현재 가장 보수적인 안 / 가장 효과 큰 안 / 1순위 권고안**:
- 가장 보수적인 안: **A안(유지)** — 변경도 위험도 없지만 기존
  마찰(011070류 override)을 그대로 남긴다.
- 가장 효과(완화 폭) 큰 안: **C안(제거)** — 다만 §13.2.7/이번 절
  실측에 따르면 그 효과의 98.6%가 안전망 없는 완화라 위험도도
  가장 크다.
- **1순위 권고안: B안(계수 완화)** — `risk_off`라는 신호 자체의
  restraint 필요성(특히 하드 게이트가 커버하지 못하는 population)은
  유지하되, 패널티 강도를 낮춰 `011070`류 override 마찰을 부분적으로
  줄이는 절충안이다. 정확한 계수는 다음 턴 추가 실측 이후 확정한다.

**아직 미확인인 것**:
1. B안의 후보 계수(`-0.10`/`-0.05` 등)별로 C 집합이 정확히 얼마나
   줄어드는지는 이번 턴에서 실측하지 않았다 — 다음 턴 과제.
2. `bearish_trend`+`risk_off`인 C 집합 50건이 실제로
   `risk_off_exception_eligible`을 통해 어떻게 처리되는지(하드
   게이트를 통과하는지 여부)는 이번 턴 범위 밖이다.
3. B안 적용 시 `011070`류 override 빈도가 실제로 줄어드는지는 코드
   수정 이후에나 확인 가능하며, 이번 턴은 설계 비교로 범위를
   한정했다.

#### 13.2.9 R2 — `risk_off` 패널티 B안 후보 계수별 영향 실측(2026-08-03 KST, read-only)

**목적**: §13.2.8에서 1순위로 권고한 B안(계수 완화)의 후보 계수를
좁히기 위해, `-0.15 → -0.10 / -0.05 / 0.00` 후보별로 C 집합이 얼마나
줄거나 이동하는지 read-only로 실측한다. `0.00`은 제거안에 가까운
**참고용 상한 비교**이며 B안 권고 후보와 같은 무게로 다루지 않는다.
코드는 변경하지 않았다.

**전제(이미 닫힌 사실, 재검증하지 않음)**: R1 정리(§13.1.1~§13.1.6),
R2 allocation 4분류·실측·구조 분리·제거(§13.2.1~§13.2.5), regime/risk
서브조건 분해(§13.2.6), `risk_off -0.15` 기여도 실측·판정 C(§13.2.7),
A/B/C 설계 비교·1순위 B안 권고(§13.2.8) — 전부 참조만 하고 다시 열지
않는다. `bullish_trend +0.10`/`risk_on +0.05`는 이번 턴에서도 다루지
않는다.

**`risk_off -0.15` 적용 위치 재확인**: `_build_entry_score()`
1236~1238행, `regime_label`과 무관하게 `risk_tone=="risk_off"`이면
항상 적용됨을 재확인했다(§13.2.7/§13.2.8과 동일).

**조회 방법**: `trading_db`에 read-only `SELECT`로 직접 접속해
`entry_score`, `risk_tone`, `regime_label`, `decision_type`을
추출했다. 후보 계수 `k`에 대한 가상 점수는 `entry_score_candidate(k)
= entry_score + (0.15 - k)`로 계산했다(§13.2.7에서 확정한
`entry_score_without_penalty = entry_score + 0.15`와 같은 방식).
`side='buy'`, `risk_tone='risk_off'` 필터만 적용했고, DB write·KIS
호출·코드 수정은 하지 않았다.

**집합 정의**: A = 현행(`k=0.15`) 기준 `entry_score>=0.65`. C(B1) =
현행은 `<0.65`이지만 `k=0.10`이면 `>=0.65`. C(B2) = 현행은 `<0.65`
이지만 `k=0.05`이면 `>=0.65`. C(B3) = 현행은 `<0.65`이지만 `k=0.00`
이면 `>=0.65`(§13.2.7의 C 집합과 동일 정의). 세 집합은 서로소가
아니라 **누적(nested) 관계**다 — `k`가 작아질수록 통과 조건이 완화
되므로 `C(B1) ⊆ C(B2) ⊆ C(B3)`이다.

**새로 확인한 사실 1(후보안별 통과 건수, row 기준)**:

| 후보 | 정의 | 최근 3거래일(07-30~08-03) 통과 | 최근 1개월(07-04~08-03) 통과 | 전체 이력(06-19~08-03) 통과 |
|---|---|---|---|---|
| 현행(`-0.15`) | 무변화 | 174 | 659 | 659 |
| B1(`-0.10`) | 완화 | 200 | 793 | 956 |
| B2(`-0.05`) | 완화 | 310 | 1,321 | 2,706 |
| B3(`0.00`, 참고용) | 제거에 가까움 | 722 | 2,468 | 4,427 |

전체 이력 통과 건수(`659`)는 §13.2.7 측정 시점(`640`) 이후
2026-08-03 장중 거래가 이어지며 늘어난 자연 증가분이다 — 방법론은
동일하다.

**새로 확인한 사실 2(현행 대비 신규 통과 표본, row 기준)**:

| 후보 | 최근 3거래일 신규 통과 | 최근 1개월 신규 통과 | 전체 이력 신규 통과 |
|---|---|---|---|
| C(B1) | 26 | 134 | 297 |
| C(B2) | 136 | 662 | 2,047 |
| C(B3, 참고용) | 548 | 1,809 | 3,768 |

**순증(marginal) 표본**(누적이 아니라 구간별 증분, 전체 이력 기준):
`B1→B2` 구간에서 `1,750`건이 추가로 통과하고, `B2→B3` 구간에서
`1,721`건이 추가로 통과한다. 즉 `0.00`(참고용)까지 가면 `B2` 대비
추가로 `1,721`건이 더 통과하게 되는데, 이 폭이 바로 아래 (3)에서
확인하듯 `bearish_trend`/`range_bound`까지 전부 끌어들이는 구간이다.

**새로 확인한 사실 3(distinct `symbol`+거래일 기준)**:

| 후보 | distinct symbol(3td) | 조합(3td) | distinct symbol(1개월) | 조합(1개월) | distinct symbol(전체) | 조합(전체) |
|---|---|---|---|---|---|---|
| C(B1) | 1 | 1 | 2 | 3 | 3 | 6 |
| C(B2) | 4 | 4 | 5 | 13 | 18 | 53 |
| C(B3, 참고용) | 10 | 10 | 14 | 31 | 27 | 89 |

row 기준과 같은 방향이다 — `B1`은 매우 소수(전체 이력 3종목/6조합)
에만 영향을 주고, `B2`는 그보다 넓지만(18종목/53조합) `B3`(27종목/
89조합, §13.2.7의 C 집합과 동일)보다는 뚜렷이 좁다.

**새로 확인한 사실 4(regime 분포, 전체 이력 신규 통과 표본 기준,
6번 질문과 직결)**:

| 후보 | `bullish_trend` | `range_bound` | `bearish_trend` |
|---|---|---|---|
| C(B1) | 297(100%) | 0 | 0 |
| C(B2) | 2,047(100%) | 0 | 0 |
| C(B3, 참고용) | 3,644(96.7%) | 74(2.0%) | 50(1.3%) |

**`B1`과 `B2`의 신규 통과 표본은 전부 `bullish_trend`뿐이다 —
`range_bound`/`bearish_trend`는 단 한 건도 포함되지 않는다.**
`bearish_trend`(하드 게이트가 실제로 커버하는 population, §13.2.8)
와 `range_bound`가 새로 풀리기 시작하는 것은 `B3`(참고용 상한)
부터다. 즉 계수를 `-0.10`이나 `-0.05`로만 완화하면, §13.2.8에서
확인한 하드 게이트 커버리지 문제(98.6% 비커버)를 넘어서는 범위
(즉 하드 게이트가 어느 정도 관여하는 `bearish_trend` population)
까지는 건드리지 않는다는 뜻이다 — **완화 폭이 지나치게 큰 후보는
`B3`뿐이고, `B1`/`B2`는 §13.2.8이 지적한 "안전망 없는 population"
안에서만 움직인다.**

**새로 확인한 사실 5(`decision_type=approve`/`order_requests`와의
관계, 5번 질문)**:

| 후보 | `approve` 겹침 | `order_requests` 겹침 |
|---|---|---|
| C(B1) | 0건 | 0건 |
| C(B2) | **1건** | **1건** |
| C(B3, 참고용) | 1건 | 1건 |

§13.2.7에서 확인한 실제 체결 사례(`011070`, 2026-06-19 KST,
`entry_score=0.5647`)는 `entry_score+0.05=0.6147`(`B1`로는 `0.65`
미달)이지만 `entry_score+0.10=0.6647`(`B2`로는 `0.65` 이상)이다.
**즉 `B1(-0.10)`은 이번 실측의 동기가 된 실제 override 사례를
전혀 해소하지 못하고, `B2(-0.05)`부터 그 사례를 해소한다.**

**1(질문 6에 대한 답, 요약)**: 완화 폭이 지나치게 큰 후보는
`B3(0.00)`이다 — `bearish_trend`/`range_bound`까지 끌어들이고
(하드 게이트 커버리지가 있는 population까지 건드림), 신규 통과
규모도 전체 이력 `3,768`건으로 현행 통과 건수(`659`)의 5배가
넘는다. `B1`/`B2`는 규모·regime 분포 모두 `bullish_trend` 안에서만
움직여 완화 폭이 통제 가능한 범위다.

**현재 가장 보수적인 후보 / 가장 완화 폭이 큰 후보 / 1순위 권고
후보**:
- 가장 보수적: **B1(`-0.10`)** — 전체 이력 신규 통과 `297`건, 3종목
  /6조합뿐이나, 실제 동기가 된 `011070` 사례를 해소하지 못한다.
- 가장 완화 폭이 큰 후보(참고용, 권고 아님): **B3(`0.00`)** —
  `bearish_trend`/`range_bound`까지 끌어들여 §13.2.8의 우려(안전망
  없는 완화)가 그대로 나타난다.
- **1순위 권고 후보: B2(`-0.05`)** — 전체 이력 신규 통과 `2,047`건
  /18종목/53조합으로 `B3`보다 뚜렷이 좁고, `bearish_trend`/`range_
  bound`는 전혀 포함하지 않으며(§13.2.8의 하드 게이트 커버리지
  범위를 벗어나지 않음), 실제 동기가 된 override 사례(`011070`)를
  유일하게 해소하는 최소 완화 폭이다.

**다음 코드 수정 단위 판정**: 이번 턴 실측으로 계수 후보가
`B2(-0.05)`로 좁혀졌으므로, **다음 턴은 코드 초안 턴**으로 진행할
수 있다 — `_build_entry_score()`의 `score -= 0.15`를 `score -=
0.05`로 바꾸는 상수 1개 수정과, §13.2.5(allocation 제거)에서 이미
썼던 것과 같은 방식으로 관련 fixture의 경계값을 재실측·보정하는
작업이 될 것으로 예상된다.

**아직 미확인인 것**:
1. `B2(-0.05)` 적용 후 실제 운영에서 `011070`류 override 빈도가
   실제로 줄어드는지는 코드 수정·재실측 이후에나 확인 가능하다.
2. `bearish_trend`+`risk_off`인 population(§13.2.8의 50건)이
   `B1`/`B2`/`B3` 어느 후보에서도 신규 통과에 전혀 포함되지 않는
   이유(원래 entry_score가 낮아 `0.15` 전액을 복원해야만 겨우
   넘는 구조인지)는 이번 턴에서 세부 분석하지 않았다.
3. `B2` 적용 시 `ranking_score`/authoritative 게이트 점수가 구체적
   으로 얼마나 이동하는지(§13.1.6 명시식 기준 재계산)는 코드 초안
   작성 시점에 함께 확인해야 한다.

#### 13.2.10 R2 — `risk_off` soft penalty B2(-0.05) 코드 적용(2026-08-03 KST)

**목적**: §13.2.9에서 1순위로 좁힌 B2(-0.05) 권고 후보를 실제
코드로 반영한다. 이번 턴은 `risk_off` soft penalty 계수 완화만
수행하며, 하드 게이트 구조(`bearish_trend`+`risk_off` 조합에서만
발동)는 그대로 유지한다 — "`risk_off` 하드 게이트 단일 권위화"는
인지하되 이번 턴 범위 밖으로 남긴다.

**전제(이미 닫힌 사실, 재검증하지 않음)**: R1 정리(§13.1.1~§13.1.6),
R2 allocation 4분류·실측·구조 분리·제거(§13.2.1~§13.2.5), regime/risk
서브조건 분해(§13.2.6), `risk_off -0.15` 기여도 실측·판정 C(§13.2.7),
A/B/C 설계 비교·1순위 B안 권고(§13.2.8), B안 후보 계수별 영향 실측·
1순위 B2 권고(§13.2.9) — 전부 참조만 하고 다시 열지 않는다.

**어떤 상수를 어떻게 바꿨는지**: `_build_entry_score()` 1236~1239행의
`if market_regime.risk_tone == "risk_off": score -= 0.15`를
`score -= 0.05`로 바꿨다. 조건식(`risk_tone=="risk_off"`, `regime_
label`과 무관하게 적용)과 `reason_codes.append("trigger_risk_off_
penalty")`는 그대로 유지했다 — 계수 값 하나만 바꾼 최소 수정이다.

**건드리지 않은 범위**:
- `bullish_trend +0.10`, `risk_on +0.05` — 코드 한 줄도 건드리지
  않았다.
- 하드 게이트(`_is_core_risk_off_regime()`, `_assess_buy_eligibility()`
  의 `risk_off`+`bearish_trend` 블록) — `entry_score`를 참조하지
  않는 독립 코드라 전혀 영향받지 않는다. 조건식 자체도 무변화다.
- authoritative 게이트(`_assess_core_risk_off_buy_guard()`, §13.1.6)
  — `allocation_bonus_like` 계산과 `0.28` threshold 코드는 무변화다.
  다만 `entry_score`가 입력이므로 게이트가 계산하는 점수 값 자체는
  `risk_off` 표본에서 `0.55*0.10=0.055`만큼 높아진다(코드 변경이
  아니라 입력값 변화에 따른 자연스러운 결과).
- `_build_buy_ranking_score()`(`ranking_score` 공식) — 코드 무변화,
  다만 같은 이유로 `risk_off` 표본에서 값 자체는 `0.055`만큼 높아진다.
- shadow(`_build_core_risk_off_shadow_experiment_metadata()`,
  `_build_event_overlay_shadow_experiment_metadata()`) — 코드
  무변화. 다만 이 함수들이 받는 `entry_score`/`ranking_score` 값이
  `risk_off` 표본에서 함께 이동하므로, 그 값을 사용하는 shadow
  bucket 판정 결과가 fixture 차원에서 달라질 수 있다(아래 확인).
- reporting(`decision_factory.py`, `trigger_proxy_attribution.py`) —
  코드 무변화, 저장 구조도 무변화.
- EV gate — 이 신호를 참조하지 않으므로 무관(§13.2.6에서 이미 확인,
  재검증 안 함).

**실행한 검증과 결과**(변경 파일 기준 좁은 범위, dev tree 직접 mount
— 이유는 이전 턴에 이미 문서화, 재논의하지 않음):
- `python3 -m pytest tests/services/test_deterministic_trigger_
  engine.py -v` → **25 passed**(경계값 보정 2건 반영 후 전부 통과,
  아래 참고)
- `python3 -m py_compile src/agent_trading/services/deterministic_
  trigger_engine.py tests/services/test_deterministic_trigger_
  engine.py` → 통과(exit 0)
- `python3 -m ruff check src/agent_trading/services/deterministic_
  trigger_engine.py tests/services/test_deterministic_trigger_
  engine.py` → All checks passed
- (표준 명령) `bash scripts/harness/run.sh accept backend-file
  src/agent_trading/services/deterministic_trigger_engine.py` →
  PASS(`tests_run_count=3`, `test_failed_count=0`)
- full pytest·KIS 호출·DB write·`.env` 수정은 하지 않았다.

**fixture 보정이 필요했던 이유(최소 범위 2건)**: 계수를 `-0.15→
-0.05`로 완화하면 `risk_off` 표본의 `entry_score`가 일률적으로
`0.10`만큼 높아진다. `test_trigger_engine_core_risk_off_ranking_
boundary_shifts_by_coverage_score_weight`(§13.2.5에서 이미 `overall
0.33/0.34→0.44/0.45`로 한 차례 재조정된 좁은 경계 테스트)와
`test_trigger_engine_core_risk_off_authoritative_score_matches_
ranking_score_formula`(§13.1.6 회귀 테스트, 같은 fixture 재사용)는
authoritative 게이트의 `0.28` threshold를 정확히 걸치도록 설계된
좁은 경계 테스트라, `entry_score`가 `0.10` 높아지면서 두 fixture
(`overall=0.44`/`0.45`)가 모두 통과 쪽으로 넘어갔다. 실측으로 새
경계를 다시 찾아 `overall 0.44/0.45 → 0.00/0.02`로 최소 범위만
갱신했다 — **게이트 코드·threshold(`0.28`)는 이번에도 무변화**이며,
바뀐 것은 좁은 경계를 만드는 fixture 입력값뿐이다. 다른 23건은
계수 완화의 영향권 밖이거나(risk_off 무관 fixture) 영향권 안이라도
`0.65`/`0.28` 경계에서 충분히 떨어져 있어 보정이 필요 없었다.

**확인 항목별 결과**:
1. `entry_score`만 계수 완화되고 하드 게이트 조건식 자체는 그대로인지
   — 그대로다. `_is_core_risk_off_regime()`/`_assess_buy_eligibility()`
   코드에 `entry_score`를 참조하는 부분이 없음을 재확인했다.
2. `buy_candidate_threshold(0.65)` 경계 fixture가 바뀌면 최소 범위로만
   조정했는지 — 이번 계수 변경으로 `0.65` 경계 자체에 걸린 기존
   fixture는 없었다(§13.2.9 실측에서 `B2`의 신규 통과분은 기존에
   경계 테스트로 쓰이지 않던 population). 조정이 필요했던 것은
   `0.28`(authoritative) 경계 fixture 2건뿐이었다.
3. authoritative 게이트 관련 fixture도 `entry_score` 입력 변화 때문에
   영향받으면 최소 보정했는지 — 위 2건이 정확히 이 경우였고, `overall`
   입력값만 재실측해 최소 보정했다.
4. shadow/reporting 값은 로직 변경 없이 유지됐는지 — 로직(함수 코드)은
   전부 무변화이며, 나머지 23건 통과 결과가 이를 뒷받침한다(shadow
   관련 테스트 6건 모두 fixture 변경 없이 그대로 통과).

**아직 남은 운영 실측 필요 사항**:
1. `B2(-0.05)` 적용 후 실제 운영 데이터에서 `011070`류 override
   빈도가 실제로 줄어드는지는 이번 턴에서 확인하지 않았다 — 코드
   병합·운영 반영 이후 별도 실측이 필요하다.
2. `bearish_trend`+`risk_off` population(§13.2.8의 50건)에 대한
   `risk_off_exception_eligible` 최종 처리 경로는 여전히 미확인
   (§13.2.7/§13.2.8과 동일 범위 제한).
3. `risk_off` 하드 게이트 단일 권위화(entry_score 쪽 soft penalty를
   완전히 없애고 하드 게이트만 남기는 구조 재편)는 이번 턴에서
   인지만 했을 뿐 설계·구현하지 않았다 — §13.2.8에서 이미 "권고하지
   않음"으로 판정한 C안과 연결되는 논의이며, 다음 턴 이후 과제로
   남긴다.

#### 13.2.11 R2 — `risk_off` soft penalty B2(-0.05) 운영 반영 초기 실측(2026-08-03 KST, read-only)

**목적**: §13.2.10에서 적용한 `risk_off -0.05` 코드가 실제 운영
서버(사용자 승인에 따른 장중 예외 배포)에 반영된 뒤, 재기동 이후
첫 intraday cycle들에서 실제로 반영됐는지와 초기 영향을 read-only로
확인한다. 코드는 변경하지 않았다.

**전제(이미 닫힌 사실, 재검증하지 않음)**: R1 정리(§13.1.1~§13.1.6),
R2 allocation 트랙(§13.2.1~§13.2.5), regime/risk 서브조건 분해
(§13.2.6), `risk_off -0.15` 기여도 실측(§13.2.7), A/B/C 설계 비교
(§13.2.8), B안 후보 계수별 영향 실측(§13.2.9), B2(-0.05) 코드 적용
(§13.2.10) — 전부 참조만 하고 다시 열지 않는다.

**새로 확인한 사실 1(런타임 반영 확인 방법과 결과)**: `docker exec
agent_trading-app-1`로 컨테이너 내부 `/app/src/agent_trading/
services/deterministic_trigger_engine.py`를 직접 확인한 결과,
`risk_off` 블록이 `score -= 0.05`(§13.2.9 실측 근거 주석 포함)로
반영돼 있음을 확인했다. 같은 컨테이너 안에서 `_build_entry_score()`
를 직접 호출해(`market_regime.risk_tone="risk_off"`,
`regime_label="bullish_trend"`) `trigger_risk_off_penalty`
reason code와 함께 `-0.05`가 적용된 점수가 나오는 것도 확인했다.

**새로 확인한 사실 2(실제 배포 반영 시점 — 컨테이너 재기동 시각이
아니다, 중요)**: 컨테이너는 `2026-08-03 11:56:23 KST`에 재기동됐지만
(`docker inspect .State.StartedAt`), 소스 파일 자체는 `sync_source`
단계(`git reset --hard`)가 그보다 먼저 끝나 `2026-08-03 11:55:32
KST`에 이미 갱신돼 있었다(파일 mtime으로 확인). 이 시스템의 매매
루프(`ops-scheduler`)는 cycle마다 `python3` 서브프로세스를 새로
띄우는 구조라(`decision_submit_gate`, `post_submit_sync` 등 로그에서
확인), **컨테이너 재기동을 기다리지 않고 `sync_source`가 끝난 시점
(11:55:32 KST) 이후 첫 cycle부터 이미 새 코드로 동작했다.** 즉 이번
실측의 진짜 경계는 `11:56:23`(컨테이너 재기동)이 아니라 `11:55:32`
(소스 동기화 완료)다.

**실측 시점(경계 재확인 반영)**: 진짜 이전(old, `-0.15`) 기준 cycle은
`11:55:32` 이전에 완료된 `11:45`, `11:50` cycle이고, 이후(new,
`-0.05`) cycle은 `11:56`, `11:58`, `12:03`, `12:09` 4개 cycle이다
(`decision_submit_gate` 로그의 `CADENCE_TRACE` 완료 기록과 `trade_
decisions` 타임스탬프 클러스터로 교차 확인, cycle당 12건씩 정확히
일치).

**새로 확인한 사실 3(cycle별 집계표, `risk_tone=="risk_off"` 표본
기준)**:

| 집계 창 | 표본 수(전체) | `risk_off` 표본 | `entry_score>=0.65` | `buy_candidate=true` | `risk_off_exception_eligible=true` | `decision_type=approve` |
|---|---|---|---|---|---|---|
| 이전(`-0.15`, 11:45/11:50 cycle) | 24 | 20 | 2 | 2 | 0 | 0 |
| 이후(`-0.05`, 11:56/58/12:03/09 cycle) | 48 | 40 | 8 | 8 | 0 | 0 |

`order_requests` 생성 건수는 `11:55:00 KST` 이후 전체 심볼 기준으로도
**0건**이었다.

**새로 확인한 사실 4(대표 종목 전/후 비교, 직전 cycle(`11:50`, old) 대
직후 cycle(`11:56`, new) 동일 종목 10개 전수)**:

| symbol | `entry_score` 전 | `entry_score` 후 | Δ | `ranking_score` 전 | `ranking_score` 후 | Δ | `buy_candidate` 전→후 | `regime_label` |
|---|---|---|---|---|---|---|---|---|
| 000810 | 0.4336 | 0.5336 | **+0.1000** | 0.2685 | 0.3235 | +0.0550 | false→false | bullish_trend |
| 001450 | 0.7564 | 0.8564 | **+0.1000** | 0.4460 | 0.5010 | +0.0550 | true→true | bullish_trend |
| 051900 | 0.4161 | 0.5161 | **+0.1000** | 0.2588 | 0.3138 | +0.0550 | false→false | event_driven_unstable |
| **073240** | **0.6134** | **0.7134** | **+0.1000** | 0.3674 | 0.4224 | +0.0550 | **false→true** | bullish_trend |
| 078930 | 0.5368 | 0.6368 | **+0.1000** | 0.3253 | 0.3803 | +0.0550 | false→false | bullish_trend |
| 081660 | 0.4133 | 0.5133 | **+0.1000** | 0.2573 | 0.3123 | +0.0550 | false→false | bullish_trend |
| 111770 | 0.3609 | 0.4609 | **+0.1000** | 0.2285 | 0.2835 | +0.0550 | false→false | range_bound |
| 138040 | 0.5219 | 0.6219 | **+0.1000** | 0.3170 | 0.3720 | +0.0550 | false→false | bullish_trend |
| 316140 | 0.3705 | 0.4705 | **+0.1000** | 0.2338 | 0.2888 | +0.0550 | false→false | range_bound |
| 383220 | 0.5068 | 0.6068 | **+0.1000** | 0.3088 | 0.3638 | +0.0550 | false→false | bullish_trend |

**10개 종목 전부 `entry_score`가 정확히 `+0.1000`, `ranking_score`가
정확히 `+0.0550`(`=0.55*0.10`) 이동했다** — §13.2.9/§13.2.10에서
예상한 수식(`+0.10` 직접, `0.55*entry_score` 경로로 `+0.055`)과
소수점 4자리까지 정확히 일치한다. `073240`은 이 이동으로 `entry_
score`가 `0.6134→0.7134`로 `buy_candidate_threshold(0.65)`를
새로 넘어 `buy_candidate`가 `false→true`로 뒤집혔다 — §13.2.9가
예측한 정확한 메커니즘(entry_score 상승으로 인한 신규 통과)이 실제
운영 데이터에서 관측된 첫 사례다.

**직전 기준 대비 확인(4번 질문에 대한 답)**: `entry_score`는 예상대로
`+0.10` 이동한 사례가 **표본 전량(10/10)**에서 확인됐고,
authoritative 게이트 쪽 경로(`ranking_score = 0.55*entry_score +
0.10*allocation_bonus_like`)도 `+0.055`로 정확히 해석되는 것을
확인했다 — `allocation_bonus_like`가 동일 종목 전/후로 변하지
않았으므로 이동폭 전부가 `0.55*0.10` 항에서만 나왔다는 뜻이다.

**초기 판정: B. 초기 방향성 확인됨.**

근거:
1. 런타임 반영은 코드·실행 결과 양쪽에서 확실히 확인됐다(A 수준은
   이미 충족).
2. `entry_score`/`ranking_score` 이동폭이 표본 전량에서 설계 그대로
   (`+0.10`/`+0.055`) 재현돼, "우연이 아니라 의도한 메커니즘이 그대로
   작동한다"는 방향성이 확인됐다.
3. 실제 `buy_candidate` 플립 사례(`073240`)가 1건 관측됐다 — 이는
   단순 반영 확인을 넘어 **실제 판정 결과가 바뀐 사례**다.
4. 다만 `risk_off_exception_eligible`/`decision_type=approve`/
   `order_requests` 생성은 이 실측 창(4 cycle, 40건)에서 전부 0건
   이라, §13.2.9의 동기가 된 override 마찰(`011070`류)이 실제로
   줄어드는지는 **아직 확인할 수 없다** — 표본이 너무 적고
   (`bearish_trend`+`risk_off` 조합 자체가 이 창에 아예 없었다),
   그 결론까지 내리기엔 이르다. 그래서 "C. 효과까지 확인"은 아니다.

**아직 미확인인 것**:
1. `risk_off_exception_eligible=true`/`decision_type=approve` 사례가
   더 많은 cycle이 누적되면 실제로 나타나는지, 그리고 §13.2.9가 겨냥한
   override 마찰이 줄어드는지는 이번 턴 표본으로는 판단할 수 없다 —
   더 많은 intraday cycle 누적 후 재실측이 필요하다.
2. `bearish_trend`+`risk_off` population(§13.2.8의 50건)이 이번
   실측 창에는 전혀 나타나지 않았다 — 관측 가능한 시점에 재확인이
   필요하다.
3. 이번 실측은 오늘(2026-08-03 KST) 장중 4개 cycle(40건)에 한정된다
   — 장 마감 후 또는 여러 거래일 누적 기준 재집계는 다음 턴 과제다.

#### 13.2.12 R2 — `risk_off` 하드 게이트 단일 권위화 B안 설계·적용(2026-08-03 KST)

**설계 비교(read-only, 코드 변경 없는 턴에서 진행)**: `risk_off`가
BUY 경로에서 soft penalty(`entry_score -0.05`)/hard gate(`_assess_
buy_eligibility()`의 `bearish_trend+risk_off` 인라인 조건)/authoritative
exception gate(`_assess_core_risk_off_buy_guard()`) 3곳에 걸쳐 있음을
전수 확인하고, A안(현행 유지)/B안(soft penalty 유지, hard gate만 단일
권위화)/C안(soft penalty 제거)을 비교했다. C안은 `bullish_trend+
risk_off`처럼 하드 게이트가 전혀 발동하지 않는(이력 다수) population
에 안전망 없이 완화가 번지는 위험이 커 §13.2.8과 같은 논리로 기각
했고, **B안(가장 보수적, 판정 무변화)**을 권고했다. `expected_value_
gate.py`(risk_off_exception_eligible 소비), AI-context, downstream
reporting은 범위 밖으로 유지했다. `decision_orchestrator.py`의 pre-AI
short circuit(risk_off_exception_eligible과 eligibility_risk_off_
block을 재확인하는 코드)에서 R3의 `allocation_budget_ok`와 유사한
무해한 재확인 후보를 하나 더 발견했으나, 이번 설계와 독립적인 소규모
정리 후보로만 기록하고 건드리지 않았다.

**B안 구현 적용**: `source_type` 분기를 `_assess_buy_eligibility()`
바깥 wrapper 성격으로 유지하기로 확정했다(authoritative 게이트인
`_assess_core_risk_off_buy_guard()`에 흡수하면 그 함수가 몰라도 되는
eligibility 전용 reason-code 컨벤션·source_type 구분까지 알아야 해서
결합도가 늘어나므로, 흡수보다 보수적). 구체적으로:
1. `market_regime.risk_tone=="risk_off" and regime_label=="bearish_
   trend"` 조건을 `_is_bearish_trend_risk_off_regime()` 헬퍼 하나로
   추출해, `_is_core_risk_off_regime()`과 `_assess_buy_eligibility()`
   양쪽이 각자 인라인으로 복제하던 것을 이 하나로 통일했다.
2. `_assess_buy_eligibility()` 내부의 `if source_type=="core": if/else
   ... elif/else ...`(4-leaf 분기, pass/block 판단이 core/비-core에서
   각각 따로 쓰여 있었음)를 `if risk_off_exception_eligible: ... else:
   ...`(2-leaf 분기, source_type은 reason_code 구성에만 관여)로
   정리했다 — pass/block을 결정하는 권위가 `risk_off_exception_
   eligible`(authoritative 게이트가 계산) 하나로 좁혀졌다.
3. `entry_score`의 `risk_off -0.05`, `_assess_core_risk_off_buy_
   guard()`의 내부 계수·threshold(`0.28`), reason_code 값·순서는
   전혀 건드리지 않았다.

**판정 결과 무변화인 근거**: 4개 (source_type, risk_off_exception_
eligible) 조합을 전수 대조한 결과 새 코드와 기존 코드의 분기 결과가
byte 단위로 동일함을 코드 추적으로 확인했고, 기존 테스트 25건이
fixture 변경 없이 그대로 통과했다(신규 헬퍼 직접 검증용 1건만 추가,
총 26건). `expected_value_gate.py`/`test_core_risk_off_topk_
projection.py` 관련 테스트 7건도 무변화로 통과했다.

**검증**: `bash scripts/harness/run.sh accept backend-file src/
agent_trading/services/deterministic_trigger_engine.py` PASS.
dev tree 직접 mount 임시 컨테이너에서 `test_deterministic_trigger_
engine.py` 26 passed, `test_expected_value_gate.py`+`test_core_
risk_off_topk_projection.py` 7 passed, `ruff check` 통과. 전체
테스트는 수행하지 않았다.

**범위 밖**: C안(soft penalty 제거), `decision_orchestrator.py`의
pre-AI short circuit 재확인 코드 정리, 운영 실측(구조 정리라 판정
결과가 바뀌지 않으므로 이번 턴은 불필요로 판단 — 필요 시 다음 턴에
재확인).

#### 13.2.13 R2 — §13.2.3 "C=0/영향 미미" 판정 재검증 및 정정(2026-08-06 KST, read-only)

**목적**: 2026-08-05(수) 운영 실측에서 "allocation 제거 후
`buy_candidate` 뒤집힘"이 관측됐다는 보고가 들어와, §13.2.3의 원래
측정 정의를 그대로 복원해 오늘 데이터에 동일 방법론을 재적용했다.
코드 변경 없음, DB write/`.env`/컨테이너 재기동/외부 API 호출 없음.

**§13.2.3 원래 정의 복원**: 모집단 = `side='buy'` 필터만 적용한
`trade_decisions`(당시 06-20~07-31, 6주). Set A = `entry_score>=
0.65`(구 공식, allocation 보정항 포함 — 필터는 이것뿐, `eligibility_
passed`나 `buy_candidate` 자체를 조건으로 넣지 않았다). Set B =
`entry_score - entry_score_allocation_adjustment < 0.65`. Set C =
A∩B. 즉 §13.2.3은 **"진짜 `buy_candidate`가 될 수 있었는가"가 아니라
"`entry_score` 하나의 threshold(0.65)만 놓고 봤을 때 보정항이 결정적
이었는가"**를 물었다 — `eligibility_low_relative_activity` 같은 다른
하드 게이트로 이미 차단되는 표본도 Set A/C에 포함될 수 있는 정의다.

**같은 정의를 2026-08-05(수) 전체 표본에 재적용**: `max_new_capital_
pct>0`(오늘 관측값 `{3,4}`, `side='BUY'`, 그 외 필터 없음) 기준으로
Set A/C를 다시 계산한 결과 **Set A = 378행(7종목), Set C = 216행
(4종목: `008930`/`051900`/`073240`/`078930`)** — §13.2.3과 정확히
같은 방법론인데도 **C가 0이 아니다.**

**참고**: `buy_candidate`(실제 `eligibility_passed`/`allocation_
budget_ok` 하드 게이트까지 통과해야 하는 진짜 최종 플래그) 기준으로
좁히면 `073240`은 `eligibility_low_relative_activity`(activity 게이트,
allocation과 무관)로 이미 차단되는 표본이라 제외되고, 나머지 3종목
(`008930`/`051900`/`078930`)만 "allocation 제거만으로 `buy_candidate`
자체가 뒤집힌" 진짜 사례다(162행). 어제 보고된 "270건"은 C 집합이
아니라 **구 공식 기준 `buy_candidate=true` 총합**(`eligibility_
passed`+`allocation_budget_ok`까지 재적용한 값, 108+162)이었다 —
"새로 차단된 건수"로 잘못 라벨링됐던 것으로 보인다. 두 숫자(162/216)
모두 §13.2.3 원래 정의로는 **0이 아니라는 결론은 동일**하다.

**원인 규명(핵심)**: 이 4개 종목은 §13.2.3 측정 기간(06-20~07-31)
동안 **`trade_decisions`에 단 한 건도 등장하지 않는다**(read-only
확인, `symbol IN (...) AND created_at BETWEEN '2026-06-20' AND
'2026-08-01'` → 0 rows). 즉 §13.2.3의 "C=0"은 **측정 오류가 아니라,
당시 거래 유니버스에 이 4개 종목이 아예 없었기 때문에 처음부터
관측 대상이 아니었던 것**이다. §13.2.3 스스로도 "이 실측은 `max_new_
capital_pct`가 3개 값만 관측된 기간에 한정된다 — 다른 국면에서도
C가 계속 0인지는 별도 실측이 필요하다"(미확인 사항 2번)고 명시했었다
— 실제로 깨진 지점은 새로운 `pct` 값이 아니라 **새로운 유니버스
구성원**이었다.

**§13.2.3 vs 2026-08-05 비교표**:

| 항목 | §13.2.3(2026-08-02 KST 측정) | 2026-08-05(수) 재적용 |
|---|---|---|
| 모집단 기간 | 06-20~07-31(6주) | 단일 거래일(08-05) |
| 필터 | `side='buy'`만 | `side='BUY'`만(동일 의도) |
| 관측된 `max_new_capital_pct` | `{2.5, 3.0, 4.0}` | `{3, 4}`(`2.5` 없음) |
| Set A(entry_score>=0.65, 구공식) | 675행 / 6종목 | 378행 / 7종목 |
| Set C(A∩B) | **0행** | **216행 / 4종목** |
| Set A margin(entry_score_without_bonus - 0.65) | 최소 `+0.0038`, 평균 `+0.0850` | 최소 `-0.0158`, 평균 `+0.0195` |
| 4개 신규 종목이 §13.2.3 기간에 존재했는가 | — | **아니다(0건, 완전히 새 유니버스 구성원)** |
| `buy_candidate`(진짜 최종 플래그) 기준 flip | (Set C가 0이라 해당 없음) | 162행 / 3종목(`073240`은 activity 게이트로 별도 차단) |
| 같은 질문인가 | — | **예 — 방법론은 동일, 모집단(유니버스 구성원·시점)이 다름** |
| 결론이 직접 비교 가능한가 | — | **가능. 같은 방법론 재적용 결과이므로 직접 비교 가능하며, 결과가 다르다** |

**판정**: **B. 기존 결론 일부 정정 필요.** §13.2.3의 측정 자체(그
표본에서 C=0)는 정확했고 방법론도 문제 없다. 다만 "1순위 판정: A.
제거해도 영향 미미"라는 문장이 **그 표본·그 시점에 한정된 관찰**임을
명시하지 않고 서술돼 있어, 유니버스가 회전한 이후에도 항상 성립하는
것처럼 오독될 위험이 있었다. 오늘 재적용으로 그 오독이 실제로
발생했다(다른 세션이 이를 "새로 차단된 270건"으로 잘못 해석해
보고한 사례). "완전히 폐기(C)"할 근거는 없다 — 측정이 틀린 게 아니라
전제(모집단 고정)가 시간이 지나며 깨진 것이다.

**정정 문구 초안**(§13.2.3 "1순위 판정" 문단에 추가 권고):

> **[2026-08-06 KST 정정]** 위 "C=0, 영향 미미" 판정은 **2026-08-02
> KST 측정 시점의 표본(06-20~07-31, 당시 유니버스 구성원)에 한정된
> 관찰**이며, 유니버스가 회전해 다른 종목이 편입되면 재현되지 않을
> 수 있다. 실제로 2026-08-05(수) 재적용에서 당시 표본에 없던 신규
> 종목 3~4개가 C>0(재현 가능한 boundary-dependent 사례)를 보였다
> (`buy_path_variable_gate_matrix.md` §13.2.13). "제거해도 영향
> 미미"는 **당시 표본 기준의 결론**으로 좁혀 읽어야 하며, 매 유니버스
> 회전마다 재검증이 필요한 결론으로 재분류한다.

**미확인 사항**: (1) 오늘 4개 종목의 `entry_score`가 왜 하필 0.65
경계에 이렇게 몰려 있는지(우연한 분포인지, R2 이후 다른 리팩터링
(`risk_off -0.15→-0.05` 등)이 이 종목들의 점수 구성에 계통적 영향을
줬는지)는 이번 턴에서 규명하지 않았다. (2) 유니버스 회전 주기·기준
(core 선정 로직)과 이런 boundary-dependent 종목이 편입되는 빈도의
상관관계는 별도 조사가 필요하다.

#### 13.2.14 R2 — `008930`/`051900`/`073240`/`078930` counterfactual downstream 개연성 분석(2026-08-06 KST, read-only)

**목적**: §13.2.13에서 확인한 4종목의 "allocation 제거가 없었으면
deterministic 기준 `BUY_CANDIDATE`가 됐을 것"이라는 판단을 한 단계
더 진행해, 실제로 `buy`/`approve`/`order_request`까지 갔을 개연성이
있었는지를 counterfactual로 분석했다. 새 AI 호출 없음, 코드 변경
없음, DB write 없음.

**저장 경로 재확인(2026-08-06 재검증)**: `risk_opinion`은
`decision_factory.py:217`에서 `ai_inputs.risk_opinion`(AI Risk
Agent 출력의 top-level `risk_opinion`)을 그대로 받아
`decision_json.risk_opinion`(top-level)에 저장한다. `evidence_
strength`는 `decision_factory.py:203`에서 `ai_inputs.evidence_
strength`(Event Interpretation Agent 출력의 `aggregate_view.
evidence_strength`)를 받아 `decision_json.evidence_strength`
(top-level)에 저장한다 — 원본은 nested지만 저장 시점에 top-level로
평탄화된다. `jsonb_path_query_array(decision_json, '$.**.risk_
opinion')`/`'$.**.evidence_strength'`로 오늘 표본(`035420`)의
decision_json 전체를 재귀 탐색한 결과 각각 **정확히 1개 경로만
존재**했다(`["allow"]`/`["none"]` 형태) — 중복되거나 경쟁하는 다른
저장 위치는 없다. 즉 이전 절에서 쓴 `decision_json->>'risk_opinion'`/
`decision_json->>'evidence_strength'`(top-level 추출)는 저장 경로
자체는 정확했다.

**비교군**: 2026-08-05(수) 오늘 실제 `buy_candidate=true`였던 factual
표본은 `035420`(`entry_score=0.6503`, core, 54사이클)과 `181710`
(`entry_score=0.6872`, core, 54사이클) 2종목뿐이다. `event_overlay`
비교군은 오늘 확보되지 않아 근사로만 사용한다(미확인 사항).

**비교군 downstream 분해**: 두 종목 모두 `eligibility_passed`/
`buy_candidate`는 전 사이클 `true`였으나, `candidate_vs_final.
alignment_status`가 `035420` 53/54·`181710` 54/54(100%)에서
`downgraded`였다. `decision_type`은 `035420`이 `buy` 1건(1.9%)/
`watch` 46건/`hold` 7건, `181710`은 `buy` 0건/`watch` 47건/`hold`
7건이었다(전부 factual 관측치). `035420`의 유일한 `buy` 행도
`expected_value_gate.passed=false`(`edge_after_cost_bps=-12.97bps`)
로 `order_request`가 생성되지 않았다 — **오늘 전체 864행 중 `order_
request`는 0건**이다(factual).

**`risk_opinion`/`evidence_strength`의 판별력 재검토(2026-08-06,
정정)**: 앞선 서술은 "`risk_opinion=review`+`evidence_strength=
weak·moderate` 조합이 downgrade를 지배한다"고 썼으나, `alignment_
status`별로 다시 교차 집계한 결과 이 해석은 **근거가 약해 철회한다**.
`035420`의 유일한 `matched`(`buy`, downgrade 안 됨) 행이 `risk_
opinion=review`/`evidence_strength=moderate`로, **downgrade된 44개
`watch` 행과 완전히 같은 조합**이다 — 즉 이 두 필드는 오늘 표본에서
override 여부를 구분해주지 못한다(같은 조합이 양쪽 결과 모두에
나타남). 저장 경로는 정확했지만, 그 값으로 "개연성이 높다/낮다"를
판단하는 것은 표본이 약해 근거가 되지 못한다. 이하 판정은 이
필드들에 의존하지 않고 **factual 도달률(빈도)만**으로 다시 쓴다.

**4종목 실제(factual) 상태**(가정 `entry_score`는 §13.2.13의 역산
값을 그대로 사용, factual row와 혼동하지 않도록 별도 표기):

| symbol | 현재(factual) `entry_score` | 가정(counterfactual) `entry_score` | `eligibility_passed` | `source_type` | 지배 신호 조합(비중) |
|---|---|---|---|---|---|
| `008930` | 0.6342 | 0.6642(가정) | true | core | `review`/`moderate` 85% |
| `051900` | 0.6387 | 0.6687(가정) | true | event_overlay | `review`/`moderate` 85% |
| `073240` | 0.6347 | 0.6647(가정) | **false**(`low_relative_activity`) | event_overlay | `review`/`moderate` 85% |
| `078930` | 0.6417 | 0.6717(가정) | true | core | `review`/`weak` 83% |

**`073240`**: `eligibility_passed=false`가 allocation과 무관한 별도
하드 게이트(activity)이므로, allocation 제거 여부와 상관없이
`buy_candidate`가 될 수 없다(확정) — counterfactual 전제 자체가
성립하지 않아 A/B/C 판정 대상이 아니다.

**`008930`/`051900`/`078930`(공통)**: deterministic `BUY_CANDIDATE`
전환 개연성은 높다(가정 `entry_score`가 `0.65` 초과, `eligibility_
passed=true`) — 이는 §13.2.13에서 이미 확인한 factual 재구성이다.
`buy`/`approve`까지의 factual 도달률은 비교군 기준 0~1.9%(`035420`
1/54, `181710` 0/54)로 낮고, `order_request` 도달률은 비교군·전체
표본 모두 0%다. **판정: A(`BUY_CANDIDATE`까지만 가능성 높음, 주문
까지는 낮음)** — 다만 이 판정은 "빈도가 낮다"는 factual 관측이며,
"차단이 정당했다/과하지 않았다"는 규범적 판단까지 자동으로 포함하지
않는다(아래 D 참고).

**allocation 관련 결론과 downstream 차단 결론의 분리(A/B/C/D)**:

- **A. allocation 항목 자체**: §13.2.3(06-20~07-31 표본)에서는
  allocation 제거 영향이 미미했다(C=0). 이 결론은 그 표본·시점에
  한정된 관찰이다(§13.2.13에서 이미 정정).
- **B. 유니버스 회전 후 재관측**: 2026-08-05 신규 유니버스 종목
  4개 중 3개(`008930`/`051900`/`078930`)에서 allocation 제거가
  `BUY_CANDIDATE` 경계에 실제로 영향을 준 사례가 관측됐다(§13.2.13,
  216행/4종목 또는 162행/3종목).
- **C. 그 사실이 주문까지 이어졌어야 한다는 뜻은 아님**: 같은 날
  실제 `BUY_CANDIDATE`(비교군)의 `order_request` 도달률도 0%였다 —
  "`BUY_CANDIDATE`가 됐을 것"이라는 사실만으로 "주문까지 갔어야
  했다"고 단정할 근거는 없다.
- **D. 그러나 그 반대(현재 downstream 차단이 과하지 않다)도 강하게
  말할 수 없다**: 비교군 표본이 2종목·54사이클로 작고, `risk_
  opinion`/`evidence_strength`는 위에서 확인했듯 override 여부를
  구분해주지 못해 "차단이 근거 있게 이뤄졌다"는 설명을 뒷받침하지
  못한다. "오늘 `order_request`가 0건이었다"는 사실은 (i) 차단이
  정당했다는 근거로도, (ii) 시스템이 전반적으로 과도하게 보수적
  이었다는 근거로도 **동시에 해석 가능**하며, 현재 증거만으로는 둘
  중 하나를 확정할 수 없다.

**3종목 공통 결론(강도 조정)**: allocation 제거가 없었더라도
`008930`/`051900`/`078930`이 오늘 실제 매수(`order_request`)까지
**갔어야 했다고 단정할 수는 없다**(C). 동시에, 현재 downstream
차단 장치가 **과하지 않다고 단정할 수도 없다**(D) — 두 결론 모두
비교군 표본이 작고(2종목), 유일한 구분 근거로 썼던 `risk_opinion`/
`evidence_strength`가 실제로는 판별력이 없다는 것이 확인됐기 때문
이다. 이번 턴에서 새로 확정된 것은 "allocation 제거의 경계 영향이
재현 가능하다"(B)는 사실뿐이며, 그 이후 단계(주문 도달 여부, 차단의
적정성)는 여전히 **미확인**으로 남긴다.

**미확인 사항**: (1) `event_overlay` 계열(`051900`)의 실제 비교군이
오늘 없어 `core` 비교군 패턴을 근사 적용했다. (2) AI는 프롬프트에
`primary_candidate`를 입력받으므로, 실제로 `BUY_CANDIDATE`로 AI에
전달됐다면 평가 자체가 달라졌을 가능성은 배제할 수 없다(새 AI 호출
없이는 검증 불가). (3) `035420`의 유일한 `buy` 행이 다른 44개
`watch` 행과 완전히 같은 `risk_opinion`/`evidence_strength` 조합
임에도 override를 피한 이유는 규명하지 않았다 — 다른 필드(`opposing_
evidence`, LLM 비결정성 등)의 영향일 수 있으나 확인하지 않았다.
(4) downstream 차단군(`watch`/`hold`로 내려간 표본) vs 통과군(`buy`/
`approve`까지 간 표본)의 사후 수익률(counterfactual PnL 포함) 비교는
이번 턴에서 수행하지 않았다 — 후속 검증 과제로 남긴다.

**후속 검증 로드맵**: 이 축(③, downstream 하향)의 다음 작업 순서는
`[PRIORITY_MAP] remaining_work_priority_map.md`의 "다음 검증
로드맵"(B항)에 정리했다 — qualitative 필드 재사용 금지, guard/EV/
risk/compliance 단계별 구조적 재분해로 전환한다.

### 13.3 R3 — `portfolio_allocation`의 역할 분리

- 범위:
  - `max_new_capital_pct`, `allocation_budget_ok`,
    `recommended_max_order_value`를
    점수/하드게이트/실행 feasibility로 분리
- 핵심 질문:
  - sizing 정보가 후보 점수에 들어가는 것이 맞는지
  - execution feasibility 전용으로 내리는 것이 맞는지
- 우선순위: **3순위**

#### 13.3.1 `portfolio_allocation` BUY 경로 전수 매핑 및 역할 분리 판정(2026-08-03 KST, read-only 분석)

**목적**: R2(§13.2.1~§13.2.11)를 일단 정리된 것으로 두고, `portfolio_
allocation`이 BUY 경로의 점수/하드 게이트/실행 가능성/하류 컨텍스트에
각각 어떤 역할로 들어가 있는지 전수 매핑하고, 정당한 역할 분리인지
과잉 중복인지 판정한다. 이번 턴은 코드 수정 없이 read-only 분석만
진행했다.

**전제(이미 닫힌 사실, 재검증하지 않음)**: R1 정리(§13.1.1~§13.1.6),
R2 allocation 트랙(§13.2.1~§13.2.5, `entry_score`에서는 allocation
항이 이미 제거됨), R2 regime/risk 트랙(§13.2.6~§13.2.11) — 전부
참조만 하고 다시 열지 않는다. R4(activity)와 R5(하류 contract)는
이번 절에서 경계만 표시하고 본론으로 확장하지 않는다(아래 (6) 참고).

**(1) `portfolio_allocation` 필드/소비처 전수표**

| 필드 | 소비 위치 | 역할 | 비고 |
|---|---|---|---|
| `max_new_capital_pct`(1) | `allocation_budget_ok = max_new_capital_pct > 0`(197~200행) | **risk/하드 게이트**(이진) | `_assess_buy_eligibility()` 하드 차단(474행)과 `buy_candidate` 최종식(283행) 양쪽에서 참조 |
| `max_new_capital_pct`(2) | authoritative core-risk-off guard의 `allocation_bonus_like`(628~633행, §13.1.6) | **risk/score**(연속값, `0~1` 정규화) | `_CORE_RISK_OFF_ALLOCATION_BONUS_WEIGHT=0.10` 가중치로 `authoritative_entry_gate_score`에 반영 |
| `max_new_capital_pct`(3) | `_build_buy_ranking_score()`의 `allocation_quality`(1155~1161행) | **risk/score**(관찰용, §13.1.5 C안으로 잔존) | (2)와 **수식·가중치가 완전히 동일**(§13.1.6에서 이미 확인) — R1에서 "관찰용으로 의도적으로 남긴 중복"으로 이미 판정 |
| `recommended_max_order_value`(1) | eligibility 참여율 하드 게이트 1(560~570행, 회전율 대비 `>5%` 차단) | **execution feasibility/하드 게이트** | `estimated_average_turnover` 대비 |
| `recommended_max_order_value`(2) | eligibility 참여율 하드 게이트 2(572~583행, 일평균거래량 대비 `>3%` 차단) | **execution feasibility/하드 게이트** | `avg_daily_volume`·`liquidity_reference_price` 대비, (1)과 다른 관점(회전율 vs 물량) |
| `portfolio_allocation`(객체 존재 여부만) | `_build_feature_coverage_score()`(444행) | **completeness(원본 5분류 밖의 별도 역할)** | 값이 아니라 "객체가 있는지"만 확인 — `coverage_score`를 통해 간접적으로 하드 게이트(`<0.50` 차단)에 연결 |
| `recommended_max_order_value`, `max_new_capital_pct` 등 전 필드 | AI 프롬프트 컨텍스트(`prompt_context_projection.py` 210~271행) | **reporting/context** | `target_weight_pct`/`current_weight_pct`/`allocation_bias`/`available_allocation_cash`/`max_single_position_pct`/`remaining_concentration_pct`/`remaining_gross_budget_pct`까지 포함해 객체 전체를 원문 그대로 노출 |
| 전 필드 | `decision_json.portfolio_allocation`(`decision_factory.py` 251~305행) | **reporting/저장** | 판정에 되먹임되지 않는 순수 저장 경로 |
| `current_weight_pct`, `max_single_position_pct` | `_build_exit_ranking_score()`/`_build_exit_score()`의 `concentration_pressure` | **SELL/EXIT 경로** | BUY 경로 범위 밖(문서 §2 scope 그대로 유지, 재론 안 함) |
| — | `expected_value_gate.py` | **무관** | 코드 전수 검색 결과 참조 0건 |
| — | `translation.py`(submit translation) | **무관(간접적)** | `intent.request.quantity`만 참조 — `portfolio_allocation` 필드를 직접 읽어 주문 수량을 계산하지 않음. AI가 컨텍스트로 참고해 결정한 수량이 이미 `request.quantity`에 반영돼 있을 뿐 |

**(2) 역할 분류 요약(alpha/risk/sizing/execution feasibility/reporting-context)**

- **alpha**: 해당 없음 — `entry_score`에서 allocation 항은 §13.2.5에서
  이미 제거됐고, 남은 소비처 중 alpha(순수 신호 대표값) 역할을 하는
  곳은 없다.
- **risk(하드 게이트 + score)**: `allocation_budget_ok`(이진),
  authoritative guard의 `allocation_bonus_like`(연속), `ranking_
  score`의 `allocation_quality`(연속, 관찰용 잔존) — `max_new_
  capital_pct` 하나의 원신호가 이 3곳에 반영된다.
- **sizing(=risk의 하위 개념으로 흡수됨)**: `max_new_capital_pct`
  자체가 "신규 자본을 얼마나 배정할 수 있는가"라는 sizing 정보이며,
  위 risk 역할과 사실상 같은 축이다 — 별도로 분리된 "순수 sizing
  전용" 소비처는 없다.
- **execution feasibility**: `recommended_max_order_value` 기반
  참여율 하드 게이트 2건(회전율 기준, 일평균거래량 기준) — sizing
  정보와는 다른 필드(주문 규모 자체가 아니라 "그 규모가 시장에서
  집행 가능한가")를 본다.
- **reporting/context**: AI 프롬프트 컨텍스트, `decision_json`
  저장 — 객체 전체가 원문으로 노출되며 판정에 되먹임되지 않는다.
- **completeness(추가로 확인된 다섯 번째 역할)**: `coverage_score`
  계산의 존재 여부 체크 — 5분류에 정확히 들어맞지 않는 별도 역할로,
  값이 아니라 "정보가 채워져 있는가"만 본다.

**(3) 같은 원신호의 score/gate/feasibility 중복 반영 여부**

`max_new_capital_pct`는 **하드 게이트(이진) 1곳 + score(연속) 2곳**
에 반영된다. score 2곳(authoritative guard의 `allocation_bonus_
like`, `ranking_score`의 `allocation_quality`)은 §13.1.6에서 이미
확인한 대로 **수식이 완전히 동일**하다 — 다만 이는 §13.1.2/§13.1.5의
C안 결정(authoritative만 명시식으로 교체하고 관찰용 `ranking_score`
계산은 그대로 잔존)에 따라 **의도적으로 남긴 중복**이며, 이번 R3
분석에서 새로 발견한 문제가 아니다. R1 결정을 재검토하지 않는다.

`recommended_max_order_value`는 하드 게이트 2곳에 쓰이지만, 두
게이트는 **서로 다른 관점**(회전율 대비 비중 vs 일평균거래량 대비
비중)이라 같은 신호의 단순 반복이 아니라 서로 다른 시장충격
리스크를 보는 것으로 판단했다 — 아래 (4)에서 "정당한 분리"로
분류한다.

**(4) 정당한 역할 분리 vs 과잉 중복 판정**

| 항목 | 판정 | 근거 |
|---|---|---|
| `allocation_budget_ok`(하드 게이트, 이진) | **유지** | "신규 자본이 아예 없는가"라는 필요조건 체크로, 아래 score 역할과 성격이 다르다(이진 vs 연속) |
| authoritative guard `allocation_bonus_like` vs `ranking_score`의 `allocation_quality` | **의도된 중복(재론 안 함)** | §13.1.2/§13.1.5에서 이미 C안으로 확정된 "관찰용 잔존" 구조 — 새 문제 아님 |
| `recommended_max_order_value` 참여율 하드 게이트 2건(회전율/거래량) | **정당한 분리** | 같은 필드를 쓰지만 서로 다른 시장충격 리스크(회전율 집중도 vs 물량 집중도)를 각각 체크 — 중복이 아니라 두 렌즈 |
| `allocation_budget_ok`의 **코드 레벨** 재확인(474행 eligibility 내부 vs 283행 `buy_candidate` 최종식) | **과잉 중복 후보(작음)** | `eligibility_passed`가 이미 `allocation_budget_ok` 하드 차단을 통과한 결과이므로, 283행에서 `and allocation_budget_ok`를 다시 보는 것은 **판정 결과에 영향 없는 코드 레벨 재확인**이다 — §13.2.6에서 확인한 `_is_core_risk_off_regime()`/`_assess_buy_eligibility()`의 조건식 중복 재계산과 같은 성격 |
| `coverage_score`의 객체 존재 여부 체크 | **유지** | 다른 6개 체크(신호/국면/전략)와 같은 패턴의 completeness 체크이며, 이 하나만 떼어낼 이유가 없다 |
| AI 컨텍스트/`decision_json` 저장 | **유지** | reporting 역할은 판정에 되먹임되지 않아 정당한 분리 |

**결론: `portfolio_allocation`의 현재 역할 분포는 대체로 정당한
역할 분리다.** 유일하게 확인된 "과잉 중복 후보"는 `allocation_
budget_ok`를 `_assess_buy_eligibility()` 내부와 `buy_candidate`
최종식에서 두 번 확인하는 **코드 레벨 재확인**(판정 결과에는 영향
없음, R2에서 이미 닫힌 `_is_core_risk_off_regime`/`_assess_buy_
eligibility` 중복 재계산과 같은 종류)뿐이다. `max_new_capital_pct`의
score 중복(authoritative guard vs `ranking_score`)은 이미 R1에서
의도적으로 결정된 사안이라 재론하지 않는다.

**(5) 다음 코드 수정 단위 — A/B/C 중 어디까지 좁힐 수 있는가**

**A. 무변화 구조 분리(작고 선택적)**로 좁힌다. 근거:
1. R2(allocation, risk_off)와 달리 이번 R3 분석에서는 "제거해도
   되는지" 실측이 필요한 새로운 중복 신호를 찾지 못했다 —
   `recommended_max_order_value`의 두 참여율 게이트는 정당한 분리로
   판정됐고, `max_new_capital_pct`의 score 중복은 이미 R1에서 닫힌
   사안이다.
2. 유일한 정리 후보(`allocation_budget_ok` 코드 레벨 재확인)는
   판정 결과에 영향이 전혀 없는 **순수 가독성 정리**라, read-only
   실측(B)이 필요 없다 — `eligibility_passed`가 이미 `allocation_
   budget_ok`를 내포한다는 것은 코드 구조 자체로 증명 가능하다.
3. 다만 이 항목은 우선순위가 낮고 선택적이다 — R3 트랙의 핵심
   질문(sizing이 후보 점수에 들어가는 것이 맞는지)에 대한 답은
   이미 "그렇다, 단 의도된 것"으로 R1에서 닫혔으므로, 이 작은 정리
   외에는 R3에서 바로 착수할 코드 수정 단위가 없다.

**(6) R4/R5 경계(본론으로 확장하지 않음, §13.4/§13.5 그대로 유지)**:
- R4(activity, `relative_activity_score`/`volume_surge_ratio`/
  `turnover_surge_ratio`)는 이번 절에서 다루지 않았다 — `recommended_
  max_order_value` 참여율 게이트가 `average_volume_20d`/`average_
  turnover_20d`(activity 계열과 인접한 필드)를 함께 참조하지만, 이
  필드들 자체의 soft/hard 중복 정리는 R4의 범위다.
- R5(하류 contract, `candidate_vs_final`/EV gate/submit translation)
  도 이번 절에서 다루지 않았다 — (1)에서 확인한 대로 EV gate·submit
  translation 모두 `portfolio_allocation`을 직접 참조하지 않는다는
  사실만 이번 절의 경계 확인용으로 기록한다.

**(7) 코드 수정 없이 확인한 범위 / 아직 미확인 사항**:
1. 코드 read-only 확인: `deterministic_trigger_engine.py` 전수
   grep, `prompt_context_projection.py`, `decision_factory.py`,
   `expected_value_gate.py`, `translation.py`, `decision_
   orchestrator.py`에서 `portfolio_allocation` 참조 전수 확인.
2. PostgreSQL read-only 조회는 이번 절에서 수행하지 않았다 — 이번
   턴은 코드 구조 매핑과 정성 판정만으로 결론이 좁혀져 실측이 필요
   없었다(§13.2 트랙과 달리 "얼마나 자주 영향을 주는지"를 물을
   신규 후보가 없었음).
3. `assess_portfolio_allocation()`(값 생성 로직 자체)의 내부 구현은
   이번 절의 범위 밖이다 — BUY 경로 소비처 매핑에 집중했다.

#### 13.3.2 `allocation_budget_ok` 이중 확인 소규모 정리 적용(2026-08-03 KST, 동작 무변화)

**(1) 기존 이중 확인 위치**:
- 계산: `_build_deterministic_trigger_assessment()` 내부(약 197-200행)
  ```python
  allocation_budget_ok = (
      portfolio_allocation is None
      or portfolio_allocation.max_new_capital_pct > 0
  )
  ```
- 1차 확인: `_assess_buy_eligibility()` 내부(약 474-477행) — `not
  allocation_budget_ok`이면 즉시 `eligibility_passed=False`,
  `"eligibility_allocation_blocked"` reason과 함께 반환한다.
- 2차 확인(제거 대상): `buy_candidate` 최종 조건식(약 280-288행)에서
  `eligibility_passed`와 별개로 `and allocation_budget_ok`를 다시 확인.

**(2) 중복 검증**: `_assess_buy_eligibility()`의 제어 흐름상
`allocation_budget_ok=False`일 때 함수가 그 즉시 `False, (...)`를
반환하는 return문이 유일한 분기이며, 그 뒤에 `allocation_budget_ok`를
다시 뒤집는 코드 경로는 없다. 즉 `eligibility_passed=True`는 항상
`allocation_budget_ok=True`를 함의한다 — 최종식의 `and
allocation_budget_ok`는 이미 참으로 확정된 조건을 다시 확인하는
무변화 재확인이다.

**(3) 적용한 정리**: `buy_candidate` 최종 조건식에서 `and
allocation_budget_ok` 절만 제거했다. `allocation_budget_ok` 변수 자체는
`_assess_buy_eligibility()` 인자 전달과 `metadata["allocation_budget_
ok"]` 기록에 계속 쓰이므로 그대로 유지했다.

**(4) 최소 검증**:
- `bash scripts/harness/run.sh accept backend-file
  src/agent_trading/services/deterministic_trigger_engine.py` → PASS
  (선택된 테스트 3건 전부 통과, 신규 실패 0건)
- 개발 트리 대상 ephemeral 컨테이너에서
  `tests/services/test_deterministic_trigger_engine.py` 25건 전부
  통과(fixture 변경 없음 — 판정 무변화라는 사실 자체를 증명) — 특히
  `max_new_capital_pct=0.0`으로 할당 예산을 막는 기존 케이스(약
  214-220행, `eligibility_allocation_blocked` 확인)가 수정 없이 그대로
  통과했다.
- `py_compile`, `ruff check` 모두 통과.

**(5) 범위 밖으로 유지한 항목**: `max_new_capital_pct`의 다른 소비처
(authoritative guard의 `allocation_bonus_like`, `ranking_score`의
`allocation_quality`, 참여율/실행 가능성 게이트, AI 컨텍스트/
`decision_json` 저장)는 이번 정리에서 전혀 건드리지 않았다.
`risk_off` 하드 게이트 단일 권위화도 이번 턴 범위 밖이다.

### 13.4 R4 — activity 계열의 soft/hard 중복 정리

- 범위:
  - `relative_activity_score`
  - `volume_surge_ratio`, `turnover_surge_ratio`
  - `average_volume_20d`, `average_turnover_20d`
- 핵심 질문:
  - bonus와 hard gate를 동시에 유지할 이유가 남아 있는지
  - risk-off guard와 일반 eligibility의 activity 중복을 줄여야 하는지
- 우선순위: **4순위**

#### 13.4.1 `relative_activity` BUY 경로 전수 매핑 및 역할 분리 판정(2026-08-03 KST, read-only 분석)

**(1) 전수 매핑**: `volume_surge_ratio`/`turnover_surge_ratio`가
`_build_entry_score()`의 `relative_activity_bonus`(soft, `[1.0,3.0]→
[0,1]` 정규화, 최대 `+0.10`), `_assess_buy_eligibility()`의 `eligibility_
low_relative_activity`(hard, `max(...)<1.10`, 전체 BUY 공통), `_assess_
core_risk_off_buy_guard()`의 `eligibility_core_risk_off_activity_
blocked`(hard, `max(...)<1.20`, topk override 시 `1.10`, `core`+
`bearish_trend`+`risk_off` 서브셋 전용), 2개 shadow 함수(`>=1.10`/
`>=1.15`, reporting only), `market_regime.py`의 regime 분류 입력
(`volume_surge_ratio>=1.5`, `event_driven_unstable` 판정)에 각각
반영됨을 확인했다. `average_volume_20d`/`average_turnover_20d`·참여율
게이트는 R3에서 이미 execution feasibility로 분류된 **별개 개념**
(절대 유동성 규모)이라 이번 절 범위에서 제외했다.

**(2) 중복 판정**: entry_score soft bonus vs eligibility 1.10 hard
gate는 R2의 `risk_off` 패턴과 같은 논리로 **정당한 역할 분리**다 —
이력 6,345건 차단 중 309건(2종목)은 `entry_score≥0.65`였던 실제
결정적 사례라 살아있는 게이트임을 확인했다. **주의**: 여기서 "살아
있는 게이트"는 "구조적으로 실제 차단이 발생하는 코드"라는 뜻이며,
"사후 성과 기준으로 이 차단이 적정하다"는 뜻은 **아니다** — 후자는
§13.4.4에서 별도로 실측했고 그 결론은 "미확정"이다. 두 질문을
혼동하지 않는다. 반면 **eligibility
1.10 hard gate와 authoritative gate 1.20 hard gate는 과잉 중복에
가깝다** — 같은 원신호를 서로 다른 threshold로 두 번 하드 게이팅
하는데, authoritative gate 쪽은 이력 13,312건 전체에서 이 사유로
차단된 적이 **0건**이다(ranking `0.28`/signal 체크가 항상 먼저
걸러냄). topk override(activity_min을 1.10으로 완화)도 이력상
`apply_ready=true`가 **0건**이라 한 번도 선택되지 않았다. 다만 두
게이트의 적용 population이 다르므로(eligibility는 전체 BUY,
authoritative는 서브셋) "관측된 범위 내에서 dead"라는 조건부
판정이다.

**(3) 설계안**: A안(현행 유지) / **B안(authoritative gate의 activity
하드 플로어 제거, eligibility 판정에 위임)** / C안(두 hard gate
threshold를 하나로 통합)을 비교했다. C안은 R2 C안과 같은 패턴으로
threshold 재산정이 필요해 무변화 리팩터링이 성립하지 않아 기각한다.
B안 방향이 유력하나, "dead"라는 근거가 topk override 미관측 조건부
사실이라 **다음 턴은 코드 수정이 아니라 topk override 케이스를
포함한 추가 실측**(별도 C-set 확인)을 먼저 권고한다.

**(4) 범위 밖**: `market_regime.py`의 regime 분류 입력 채널,
2개 shadow 함수, `trigger_proxy_attribution.py`(오프라인 분석
스크립트)는 각자 목적이 다른 정당한 분리로 판정해 재설계 대상에서
제외했다.

#### 13.4.2 R4 — authoritative gate activity floor 추가 실측(2026-08-03 KST, read-only)

**(1) topk override 경로 실측표**: `core_risk_off_guard_active=true`
population(전체 이력 13,312건) 기준.

| 구간 | 건수 | `apply_ready=true` | `eligibility_core_risk_off_topk_override_pass` reason | `eligibility_core_risk_off_shadow_rank_promoted` reason |
|---|---|---|---|---|
| 최근 3거래일(2026-07-30~08-03) | 592 | 0 | 0 | 0 |
| 최근 1개월(2026-07-04~) | 10,849 | 0 | 0 | 0 |
| 전체 이력 | 13,312 | 0 | 0 | 0 |

topk override 경로(activity 완화 `1.20→1.10`)는 3개 시간창 전부에서
**단 한 번도 선택된 적이 없다.**

**(2) authoritative gate 하위 조건 분해표**: 동일 population을
`core_risk_off_guard_reasons` 조합별로 분해.

| ranking | signal | activity | strategy | guard_pass | 전체 이력 | 최근 1개월 | 최근 3거래일 |
|---|---|---|---|---|---|---|---|
| blocked | — | — | — | — | 13,188(99.07%) | 10,725 | 518 |
| pass | blocked | — | — | — | 124(0.93%) | 124 | 74 |
| pass | pass | blocked/pass | any | any | **0** | 0 | 0 |

두 패턴의 합(13,188+124=13,312)이 전체 population과 **정확히 일치**
한다 — `activity_blocked`/`strategy_blocked`/`guard_pass`로 끝나는
행이 전체 이력에 단 하나도 없다. `signal_feature_snapshot is None`
경로(activity 체크 이전 단계의 데이터 결측 차단)도 0건이라, "데이터
결측 때문에 activity gate가 사실상 비활성"인 것도 아니다 — 애초에
이 지점까지 도달하는 행 자체가 없다.

**(3) 구조적 dead vs 관측 범위 내 dead 판정**: 대수적으로 반례를
구성해봤다 — `authoritative_entry_gate_score = 0.55*entry_score +
0.10*allocation_bonus_like >= 0.28`를 만족하면서 동시에 `overall>=0.0
and slow>=-0.05`(signal 플로어 통과)도 만족하는 조합이 이론상
존재한다(예: `fast` 성분이 강하고 activity/strategy/allocation
보너스가 겹치면 `entry_score≈0.35` 수준에서 `overall=0`, `slow=
-0.05`처럼 신호 플로어 경계값에 걸쳐 있어도 두 조건을 동시에
만족할 수 있다). 즉 **수학적으로 100% 불가능하다고 증명되지는
않는다.** 다만 전체 이력 13,312건, 3개 시간창(3거래일/1개월/전체)
전부에서 예외 없이 이 조합이 단 한 번도 관측되지 않았다는 것은
매우 강한 경험적 증거다. **판정: "관측 범위 내 dead"** — 구조적
불가능 증명에는 못 미치지만, 실측 가능한 전체 이력을 통틀어 activity
gate에 도달한 표본이 0건이라는 사실은 변하지 않는다.

**(4) null 처리 방식의 비대칭(신규 확인 사항)**: 일반 eligibility의
`eligibility_low_relative_activity`는 `volume_surge_ratio is not None
and turnover_surge_ratio is not None and max(...)<1.10`으로, **둘 중
하나라도 결측이면 게이트 자체를 건너뛴다**(통과 처리). 반면
authoritative gate는 `max(volume_surge_ratio or 0.0, turnover_surge_
ratio or 0.0) < required_activity_min`으로, **결측을 0.0으로 취급해
오히려 차단 쪽으로 해석한다.** 이 비대칭은 이번 실측에서 activity_
blocked가 0건이라 지금까지는 드러난 적이 없지만, B안(authoritative
게이트의 activity 하드 플로어를 제거하고 eligibility 판정에 위임)을
실제로 구현할 때는 이 null 처리 차이까지 감안해야 한다는 점을
다음 턴을 위해 기록해 둔다.

**(5) 일반 eligibility gate가 살아있다는 근거(한 줄 정리)**:
`eligibility_low_relative_activity`(1.10)는 전체 BUY population
(bearish_trend+risk_off에 국한되지 않음)에서 이력 6,345건을 차단했고
그중 309건(2종목)은 `entry_score>=0.65`였던 실제 결정적 사례라
authoritative gate와 무관하게 독립적으로 살아 있다 — 따라서
authoritative gate의 activity 하드 플로어를 제거해도 일반 BUY 경로의
활동성 최저 기준 자체는 이 게이트가 그대로 지킨다.

**(6) B안 착수 가능 여부**: 위 (1)~(5)로 이번 턴이 요구한 추가
실측 2건(topk override 경로, 구조적 dead 여부)을 모두 닫았다.
**바로 코드 초안 착수가 가능한 수준으로 좁혀졌다** — 다만 (4)의
null 처리 비대칭은 구현 시 명시적으로 다뤄야 할 설계 포인트로
남긴다.

#### 13.4.3 R4 — authoritative gate 내부 구조적 dead branch 정리 적용(2026-08-03 KST, 동작 무변화)

**(1) B안(activity 하드 플로어 전체 제거) 실행 중 재확인한 사실**:
착수 전 기존 테스트를 재확인한 결과, `test_trigger_engine_topk_
override_does_not_bypass_low_relative_activity`가 `max(volume_
surge_ratio, turnover_surge_ratio)<required_activity_min` 수치
비교 분기를 의도적으로 exercise하고 있음을 확인했다 — topk override가
선택돼도 활동성이 낮으면(1.06<1.10) `risk_off_exception_eligible`이
여전히 `False`가 돼야 함을 검증하는 테스트다. 이 분기를 통째로
제거하면(B안 원안대로) 이 시나리오에서 `risk_off_exception_eligible`
값이 `False→True`로 바뀐다 — `eligibility_passed`는 일반 eligibility의
`eligibility_low_relative_activity`(1.10)가 별도로 잡아 결과적으로
동일하게 `False`가 되지만, `risk_off_exception_eligible` 자체는
metadata/decision_json/`expected_value_gate.py` 소비 여부와 무관하게
값이 바뀌므로 **엄밀히는 "완화"에 해당**한다. 이 수치 비교 분기는
"관측 범위 내 dead"였을 뿐 "구조적으로 dead"는 아니었으므로, 원안대로
제거하지 않았다.

**(2) 대신 발견한 진짜 구조적 dead branch**: `if signal_feature_
snapshot is None: activity_blocked; return` 분기는 다르다. 이 함수의
유일한 호출부(`_build_deterministic_trigger_assessment()`, 141-149행)
에서 `overall`/`slow`는 `signal_feature_snapshot`이 `None`일 때만
`None`이 되도록 항상 함께 파생된다. 이 함수 안에서 이 지점(활동성
체크)에 도달하려면 이미 앞의 signal 체크(`overall is None or
overall<0.0` / `slow is None or slow<-0.05`)를 통과해야 하므로,
`overall`/`slow`가 not-None임이 이미 확정돼 있고 — 따라서
`signal_feature_snapshot`도 이 지점에서 항상 not-None임이 **수학적으로
보장**된다. 이 널 체크는 관측 데이터상으로만이 아니라 **코드 흐름상
절대 참이 될 수 없는 조건**이라, 유일하게 완전히 안전한 제거 대상
이었다.

**(3) 적용한 정리**: `_assess_core_risk_off_buy_guard()`에서
`if signal_feature_snapshot is None: activity_blocked; return` 3줄만
제거했다. `max(...)<required_activity_min` 수치 비교, `required_
activity_min`(topk override 시 1.10, 아니면 1.20) 계산, `ranking_
blocked`/`signal_blocked` 판정 경로, threshold 값 전부 무변화다.

**(4) null 처리 비대칭(명시적으로 남김)**: 제거한 것은 "snapshot
객체 자체의 None 여부"에 대한 방어였을 뿐, "개별 surge ratio 값이
None일 때 0.0으로 취급해 사실상 차단 쪽으로 해석"하는 처리(`or
0.0` fallback)는 그대로 남아 있다. 일반 eligibility의 `eligibility_
low_relative_activity`는 두 ratio 중 하나라도 결측이면 게이트 자체를
건너뛰는(통과) permissive 처리라, authoritative gate와의 null 처리
방식 비대칭은 이번 턴에도 해소되지 않았다 — 코드 주석(위 (2))과 이
문서에 명시적으로 남기고, 완화하지 않았다.

**(5) 검증**: `bash scripts/harness/run.sh accept backend-file
src/agent_trading/services/deterministic_trigger_engine.py` PASS.
dev tree 직접 mount 임시 컨테이너에서 `test_deterministic_trigger_
engine.py` 26 passed(기존 fixture 변경 없음, topk override 활동성
테스트 포함 전부 통과), `test_core_risk_off_topk_projection.py`+
`test_expected_value_gate.py` 7 passed, `ruff check` 통과.

**(6) 범위 밖으로 남긴 것**: `max(...)<required_activity_min` 수치
비교 자체의 제거(B안 원안, "완화"에 해당해 보류), null 처리 비대칭
해소, `decision_orchestrator.py`의 `eligibility_core_risk_off_
activity_blocked` reason 참조(이제 authoritative gate에서는 이
reason이 나올 확률이 이론상 더 낮아졌을 뿐 여전히 발생 가능해 그대로
둠).

#### 13.4.4 `eligibility_low_relative_activity` 최근 구간(2026-08-03 이후) 사후 성과 1차 실측(2026-08-06 KST, read-only)

**목적**: 최근 운영 구간(유니버스 선정 반영 시점인 2026-08-03 08:50
KST 이후)에서 이 게이트의 차단 비중이 과거(8.5~11%) 대비 급증
(53~54%)한 것을 확인한 뒤, 차단군/통과군의 **사후 가격 성과**까지
포함해 적정성을 재검증했다. read-only, 코드/문서 외 수정 없음.

**가격 데이터 소스**: `trading.instrument_status_snapshots`
(`source_type='kis_stock_basic_info'`)의 `raw_payload_json.thdt_
clpr`(종가)를 `raw_payload_json.clpr_chng_dt`(종가 기준일)로 색인한
일봉 시계열. `instrument_id`로 `trading.instruments`와 조인(해당
테이블에 `symbol` 컬럼이 없어 직접 조인 필수). 이 시계열로 확인
가능한 종가 기준일은 **07-31/08-03/08-04/08-05 4개뿐**이다(08-06은
장이 아직 끝나지 않아 데이터 없음) — T+5/T+20은 **원천적으로 계산
불가**로 명시한다.

**모집단 확정**: `(instrument_id, decision_date, source_type)` 단위
62행. 같은 날 여러 사이클 내에서 차단 여부가 갈리는 경우는 **0건**
(재확인). `entry_score` 구간별 원시 표본·T+1 계산 가능 건수:

| 구간 | 통과군 표본 | 통과군 중 T+1 계산 가능 | 차단군 표본 | 차단군 중 T+1 계산 가능 |
|---|---|---|---|---|
| `entry_score<0.60` | 12 | 9 | 29 | 14 |
| `[0.60,0.65)` | 8 | 2 | 4 | 1 |
| `entry_score>=0.65` | 7 | 2 | 2 | 1 |

`entry_score>=0.65` 9건 중 6건은 08-05/08-06 진입이라 T+1 종가가
아직 나오지 않았다.

**[2026-08-06 KST 정정]** `009420`/`181710`을 "가격 데이터 전무"로
쓴 것은 부정확했다 — 두 종목을 분리해 재확인한다.

- **`009420`**: `instrument_status_snapshots`에 07-01~08-05 구간의
  종가가 **풍부하게 존재한다**(39,000→43,400→45,950→52,000→53,100,
  07-30~08-05). 이 종목은 `trade_decisions`에 **08-06이 유일한
  등장일**이라(read-only 확인, 이전 날짜 등장 0건 — 최근 유니버스
  편입 종목), T+1 계산에 필요한 08-06 자체의 종가가 아직 나오지
  않은 것뿐이다 — **"전무"가 아니라 "미도착"**이다. 참고로 이
  종목은 직전 4거래일(07-30→08-05)간 **+36.2%**의 급등을 이미
  거쳤고, 08-06 차단 시점의 `volume_surge_ratio=0.63`/`turnover_
  surge_ratio=0.67`로 활동성 게이트 threshold(1.10)에 못 미친다 —
  즉 **큰 가격 변동이 상대적 활동성 서지로는 나타나지 않은 사례**다.
- **`181710`**: 선택한 소스(`instrument_status_snapshots`)에는
  전체 이력 통틀어 이 `instrument_id`의 행이 **0건**(read-only
  확인, 이 소스 자체의 공백은 사실). 다만 **다른 내부 read-only
  시세 관련 테이블에는 값이 있다** — `signal_feature_snapshots`의
  `sma_20 * (1 + price_vs_sma_20_pct/100)`으로 종가를 역산할 수
  있다(`009420`으로 역산값이 원본 종가와 소수점까지 정확히 일치함을
  먼저 검증). 이 방법으로 `181710`의 07-31~08-05 종가를 복원하면
  37,100→37,150→43,700→42,800이다 — **08-04에 이미 +17.7%가
  선행**됐고 08-05는 -2.1%였다. 다만 이 대체 소스로도 08-06 종가는
  **아직 없다**(전체 시스템에서 08-06 종가 자체가 어디에도 없음,
  시장이 아직 열려 있기 때문) — 따라서 08-05 결정에 대한 T+1은
  소스를 바꿔도 여전히 계산 불가하다. **결론: `181710`은 선택
  소스의 공백은 실재하지만, 이번 T+1 계산 불가는 그 공백 때문이
  아니라 `009420`과 동일한 "호라이즌 미도착" 때문이다.**

**계산 가능한 표본의 T+1/T+2 평균(참고용, 표본이 매우 작음)**:
전체 population 기준 통과군 T+1 평균 +2.35%(n=13)/차단군 +0.96%
(n=16), `entry_score>=0.60`로 좁히면 통과군 +1.45%(n=4)/차단군
+3.74%(n=2) — 방향이 뒤집힌다. T+2는 `[0.60,0.65)`·`>=0.65` 차단군
모두 **계산 가능 표본이 0건**이라 비교 자체가 불가능하다.

**판정(2026-08-06 KST 재정리, 층위 분리)**:

1. **전체 population 기준**: 통과군이 차단군보다 평균 수익률이
   높다는 방향은 유지되며, 이 층위에서는 게이트가 "고장났다"고 볼
   근거가 없다.
2. **경계 고득점 구간(`entry_score>=0.60`, 특히 `>=0.65`)**: 계산
   가능 표본이 n=1~2에 불과해 통계적 결론은 낼 수 없지만, `009420`
   (직전 4거래일 +36.2%, 활동성 서지는 낮음, chronic 차단)처럼
   **가격은 이미 강하게 움직였는데 활동성 서지 기준만 못 미쳐
   차단되는 사례가 실제로 존재**한다는 점에서 **과잉 차단 의심이
   커졌다**. 이는 실측이 아니라 사례 기반 관측이며, 사후 T+1/T+2
   수익률로 직접 뒷받침되지는 않았다(해당 horizon 자체가 없음).
3. **최종 판정: 미확정.** 두 층위의 결론이 다르고, 운영상 더 중요한
   것은 경계 구간(실제 `buy_candidate`가 될 수 있었던 표본)이지만
   이 구간은 사후 수익률로 뒷받침할 표본이 아직 없다 — "과잉
   차단"이라고 단정할 근거도, "정상 작동"이라고 안심할 근거도
   부족하다.

**장중(실시간) 관측은 별개 층위로 분리한다**: 2026-08-06 장중
`009420`/`181710`의 강세가 사용자에 의해 보고됐으나, 이 문서의
백테스트는 **종가 기준 시계열**(위 두 소스 모두 최신값이 08-05
종가에서 멈춰 있음)만 사용했고, DB에는 장중 실시간 시세를 저장하는
테이블이 없다(`market_data_snapshots` 전체 이력 0행, read-only
확인). 따라서 장중 관측은 이번 백테스트 수치에 반영되지 않은
**별도의, 아직 검증하지 않은 추가 의심 신호**로만 기록한다 — 종가가
확정되기 전까지 이 값으로 어떤 결론도 내리지 않는다.

**미확인 사항**: (1) `009420`/`181710`의 08-06 확정 종가(장 종료
이후에나 관측 가능)와 그에 따른 실제 T+1. (2) `009420`의 급등이
활동성 서지로 나타나지 않은 것이 이 종목만의 특성인지, 최근 편입
종목군 전반의 패턴인지는 규명하지 않았다. (3) T+5/T+20은 최소
5~20 거래일치 데이터가 더 쌓여야 계산 가능하다.

**후속 검증 로드맵**: 이 축(②)의 다음 작업 순서·판정 기준은
`[PRIORITY_MAP] remaining_work_priority_map.md`의 "다음 검증
로드맵"에 정리했다(A항). ①allocation/③downstream/④주문요청
미생성과 분리해서 계속 관리한다 — 이 문서에는 상세 실측만 남기고
로드맵은 복붙하지 않는다.

### 13.5 R5 — 하류 contract 정리

- 범위:
  - `candidate_vs_final`
  - `expected_value_gate`
  - `submit translation`
- 핵심 질문:
  - 상류에서 제거된 변수 의미가 하류에서 다시 암묵적으로 주입되는지
  - 상류 리팩터링 뒤 하류 contract를 같이 손봐야 하는지
- 우선순위: **5순위**

#### 13.5.1 R5-a — `translation.py` `WATCH` 이중 분기 정리 적용(2026-08-03 KST, 동작 무변화)

R5 전수 매핑(하류 6개 파일: decision_orchestrator/expected_value_gate/
decision_factory/prompt_context_projection/execution_service/
translation) 결과, `build_submit_order_request_from_decision()`가
`actionable_types`에 `"WATCH"`를 넣어놓고 바로 다음 줄에서 다시
`WATCH`면 `return None`하던 무해한 이중 분기(R5-a)를 정리했다 —
`"WATCH"`를 `actionable_types`에서 제외하고 별도 분기를 제거했다.
두 분기 결과가 항상 동일함을 신규 회귀 테스트로 고정했고(전/후 코드
모두 통과 확인), 기존 pytest 24건도 fixture 변경 없이 통과했다.
`expected_value_gate_passed`/`quantity>0`/`held_position` 분기,
다른 decision_type 처리는 전부 무변화다. 상세는 R5 원본 매핑
분석(대화 이력)을 참고 — R5-b(`expected_value_gate.py`의 metadata
fallback), R5-f(`decision_orchestrator.py`의 `evaluate_action_envelope`
재확인)는 이번 턴 범위 밖으로 남긴다.

#### 13.5.2 R5-b — `expected_value_gate.py` metadata fallback 정리 적용(2026-08-04, 동작 무변화)

`_is_risk_off_exception_path()`는 `deterministic_trigger.risk_off_
exception_eligible` 속성을 확인한 뒤, 실패하면 `deterministic_
trigger.metadata["risk_off_exception_eligible"]`까지 재확인하는
fallback을 갖고 있었다. `evaluate_expected_value_gate()`의 실제
호출부 3곳(`decision_agent_runner.py` 2곳, `decision_orchestrator.py`
1곳)을 전수 확인한 결과, 전부 `AssembledContext`/`AIPolicyContextView`
의 정적 타입 필드(`deterministic_trigger: DeterministicTriggerAssessment
| None`)를 통해서만 전달되며 dict/duck-typed 객체가 실제로 흘러드는
경로는 없었다. 또한 `DeterministicTriggerAssessment`의 유일한 생성
지점(`deterministic_trigger_engine.py`)에서 `risk_off_exception_
eligible` 속성과 `metadata["risk_off_exception_eligible"]`는 항상
동일한 계산식으로 함께 채워진다 — 값이 어긋날 수 없음을 코드로
확정했다.

안전이 확정돼 metadata fallback을 제거했다. 신규 회귀 테스트
(`test_expected_value_gate_ignores_metadata_only_risk_off_flag`)를
추가해 duck-typed 시나리오(metadata에만 플래그가 있고 top-level
속성은 없는 경우)에서 이제 `risk_off_exception_eligible`로 취급하지
않음을 고정했다 — 수정 전 코드로는 이 테스트가 실패함을 확인해
회귀 재현을 검증했다. 기존 테스트 4건은 fixture 변경 없이 통과했다.
R5-f(`decision_orchestrator.py`의 `evaluate_action_envelope` 재확인)는
이번 턴 범위 밖으로 남긴다.

#### 13.5.3 R5-f — `_check_ai_buy_override_gate()` 내부 `evaluate_action_envelope` 재확인 제거(2026-08-04, 동작 무변화)

`_check_ai_buy_override_gate()`는 호출자(`assemble()`)에서 항상
`_check_source_policy_upgrade_guard()`가 먼저 실행된 뒤에만 호출된다.
그 가드가 `evaluate_action_envelope(source_type, has_position)`로
`allow_new_buy=False`를 확인하면 `decision_type`을 이미 `HOLD`/`WATCH`
로 낮추고, `_check_ai_buy_override_gate()`는 자신의 `decision_type`
체크(`APPROVE`/`BUY` 아니면 `return None`)에서 먼저 빠진다.

`source_type`/`has_position`은 두 호출 사이에 바뀌지 않고(같은
`position_snapshot`/`derivation.source_type`을 그대로 재사용),
`evaluate_action_envelope()`는 이 두 값에만 의존하는 순수 함수다(
`held_position`은 무조건 차단, `reconciliation_overlay`는 `has_
position`이 거짓일 때만 차단, 그 외 `core`/`market_overlay`/
`event_overlay`는 항상 허용 — 5개 `source_type` 전수 검토 결과
반례 없음). 따라서 이 지점에 `decision_type`이 `APPROVE`/`BUY`로
남아 있다는 것 자체가 이미 그 가드의 동일한 envelope 평가가
`allow_new_buy=True`였음을 뜻하며, 여기서 다시 확인해도 절대 다른
결과가 나올 수 없다 — "관측 범위 내 dead"가 아니라 5개 `source_
type` 전수 검토로 **구조적으로 100% 도달 불가능**함을 확정했다.

`_check_ai_buy_override_gate()` 내부의 `envelope = evaluate_action_
envelope(...)` 계산과 `if not envelope.allow_new_buy: ... return
(...)` 재확인 분기만 제거했다. `normalized_source_type` 변수는 이후
rationale 로그 문자열에서 계속 쓰이므로 그대로 유지했다. `source_
policy_upgrade_guard`/`watch_candidate_upgrade_guard`/`buy_
eligibility_upgrade_guard`의 판정 순서·정책·downgrade 의미는 전혀
건드리지 않았다.

기존 테스트를 직접 호출하는 방식이 아니라 전체 `assemble()` 경로를
통해서만 이 가드를 검증하는 기존 관례를 그대로 따랐다 — 이 재확인
분기를 단독으로 호출해 exercise하는 테스트는 원래 없었고(전수
grep 확인), `reconciliation_overlay` flat-buy·`held_position` 관련
기존 시나리오를 포함해 관련 테스트 111건이 fixture 변경 없이 그대로
통과했다.

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
   비교(§13.1.2 패턴)부터 다음 턴에 진행할 것을 권고한다. **[2026-
   08-03 KST 8차 갱신] A/B/C 설계 비교 완료(13.2.8)** — C 집합
   3,692건 중 `bullish_trend`가 3,616건(97.9%)으로, 하드 게이트
   (`bearish_trend`+`risk_off`에서만 발동)가 이 population의
   **98.6%를 전혀 커버하지 못함**을 확인했다. C안(제거)은 이 98.6%
   에 안전망 없는 완화가 되므로 권고하지 않는다. **1순위 권고안은
   B안(계수 완화, 후보 `-0.10`/`-0.05`)**이며, 다음 코드 수정 단위는
   **B(추가 실측 1건 필요)** — 후보 계수별 C 집합 축소 규모를 다음
   턴에 실측한 뒤 계수를 확정한다. **[2026-08-03 KST 9차 갱신] B안
   후보 계수별 영향 실측 완료(13.2.9)** — `B1(-0.10)`/`B2(-0.05)`의
   신규 통과 표본은 전체 이력 기준 각각 297건/2,047건이며 **전부
   `bullish_trend`**(`bearish_trend`/`range_bound` 0건)뿐이다.
   실제 override 사례(`011070`)는 `B1`로는 해소되지 않고 `B2`부터
   해소된다. **1순위 권고 후보는 B2(-0.05)**이며, 참고용 상한
   비교인 `B3(0.00)`은 `bearish_trend`/`range_bound`까지 끌어들여
   권고하지 않는다. 다음 코드 수정 단위는 **A(바로 초안 가능)**로
   좁혔다. **[2026-08-03 KST 10차 갱신] B2(-0.05) 코드 적용 완료
   (13.2.10)** — `_build_entry_score()`의 `risk_off` 패널티를
   `-0.15→-0.05`로 완화했다. 하드 게이트·authoritative 게이트 코드·
   shadow·reporting은 전부 무변화이며, `0.28` 경계에 걸린 fixture
   2건만 최소 재실측·보정했다(dev tree 직접 mount 검증 25 passed).
   `risk_off` 하드 게이트 단일 권위화는 인지만 하고 이번 턴 범위
   밖으로 남긴다. **[2026-08-03 KST 11차 갱신] 운영 반영 초기 실측
   완료(13.2.11)** — 사용자 승인에 따른 장중 예외 배포 이후 실제
   운영 데이터 10개 종목 전량에서 `entry_score +0.10`/`ranking_score
   +0.055` 이동을 확인했고, `073240` 종목이 `buy_candidate`
   `false→true`로 실제 뒤집힌 사례도 관측했다. **판정 B(초기 방향성
   확인)** — `risk_off_exception_eligible`/`approve`/`order_
   requests`는 이번 창(4 cycle)에 전부 0건이라 효과 확인은 아직
   이르다. 소스 동기화(`sync_source`)가 컨테이너 재기동보다 먼저
   끝나 그 시점부터 이미 새 코드가 적용됐다는 것도 이번에 새로
   확인했다. **[2026-08-03 KST 12차 갱신] 하드 게이트 단일 권위화
   B안 설계·적용 완료(13.2.12)** — soft penalty/hard gate/
   authoritative gate 3자 분리를 전수 확인하고 B안(soft penalty
   유지, hard gate만 단일 권위화)을 권고·적용했다. `_is_bearish_
   trend_risk_off_regime()` 헬퍼로 레짐 조건을 단일화하고,
   `_assess_buy_eligibility()`의 4-leaf 분기를 `risk_off_exception_
   eligible` 하나로 판단하는 2-leaf 분기로 정리했다(계수·threshold·
   reason_code 값 전부 무변화, 테스트 26건 fixture 변경 없이 통과).
   C안(soft penalty 제거)은 이번 턴에서도 범위 밖으로 유지했다
3. **R3**: [2026-08-03 KST 갱신] `portfolio_allocation` BUY 경로
   전수 매핑·역할 분리 판정 완료(13.3.1) — 대체로 **정당한 역할
   분리**로 판정했다. `max_new_capital_pct`의 score 중복(guard vs
   `ranking_score`)은 R1에서 이미 의도적으로 결정된 사안이라 재론
   하지 않았고, `recommended_max_order_value`의 참여율 하드 게이트
   2건은 서로 다른 시장충격 관점이라 정당한 분리로 판정했다. 유일한
   정리 후보는 `allocation_budget_ok`의 코드 레벨 재확인(판정 결과
   무영향)뿐이다. 다음 코드 수정 단위는 **A(무변화 구조 분리, 작고
   선택적)**로 좁혔다. **[2026-08-03 KST 갱신] A 적용 완료(13.3.2)**
   — `buy_candidate` 최종식의 `allocation_budget_ok` 재확인을
   제거했다. `eligibility_passed`가 이미 이 조건을 내포한다는 것을
   코드 구조로 증명했고, 관련 테스트 25건 전부 fixture 변경 없이
   통과해 판정 무변화임을 확인했다. `portfolio_allocation`의 다른
   소비처는 전부 범위 밖으로 유지했다 — R3 트랙은 이것으로 닫는다
4. **R4**: [2026-08-03 KST 갱신] `relative_activity` BUY 경로 전수
   매핑·역할 분리 판정 완료(13.4.1) — entry_score soft bonus vs
   eligibility 1.10 hard gate는 정당한 분리(이력상 309건이 실제
   결정적)로 판정했다. eligibility 1.10과 authoritative gate 1.20의
   중복은 **과잉 중복에 가깝다**고 판정했다 — authoritative gate 쪽은
   이력 13,312건 전체에서 이 사유로 차단된 적이 0건이다(topk
   override도 0건 선택). A/B/C 설계안 비교 결과 **B안(authoritative
   gate의 activity 하드 플로어 제거, eligibility 판정에 위임)**을
   권고하나, "dead"라는 근거가 topk override 미관측 조건부 사실이라
   **다음 턴은 코드 수정이 아니라 추가 실측**을 먼저 진행한다.
   **[2026-08-03 KST 갱신] 추가 실측 2건 완료(13.4.2)** — topk
   override는 3개 시간창(3거래일/1개월/전체 이력) 전부에서 0건
   선택됐고, authoritative gate 하위 조건은 전체 이력 13,312건이
   `ranking_blocked`(13,188)/`signal_blocked`(124) 단 두 패턴으로
   100% 소진돼 `activity_blocked`가 도달할 표본 자체가 없음을
   확인했다. 대수적 반례 검토 결과 수학적으로 100% 불가능하다고
   증명되지는 않아 **"관측 범위 내 dead"**로 판정을 좁혔다. 다음
   턴은 **바로 코드 초안 착수 가능**하다 — 단 eligibility/
   authoritative 게이트의 null 처리 방식 비대칭(결측 시 통과 vs
   차단)은 구현 시 명시적으로 다뤄야 한다. **[2026-08-03 KST 갱신]
   구조적 dead branch 정리 적용 완료(13.4.3)** — B안(activity 하드
   플로어 전체 제거) 착수 중, `max(...)<required_activity_min` 수치
   비교는 기존 테스트가 실제로 exercise하는 "관측 범위 내 dead"일
   뿐이라 제거하지 않았다. 대신 `if signal_feature_snapshot is None:
   activity_blocked` 분기가 signal 체크(overall/slow 파생 관계)로
   인해 **구조적으로 100% 도달 불가능**함을 확인해 이 부분만
   제거했다(동작 무변화, 테스트 26건 fixture 변경 없이 통과). null
   처리 비대칭은 해소하지 않고 코드 주석·문서로 명시만 했다
5. **R5**: 상류 결정 이후 하류 연쇄 영향 확인

즉 현재는 "BUY 경로 전체 리팩터링"이라는 이름보다,
**R1(판정 완료)→R2→R3/R4→R5의 단계적 리팩터링**으로 보는 것이 정확하다.

## 14. execution path 별건 — `stale_snapshot_guard` zero-position false-stale 수정

R1~R5(위 §13)는 `deterministic_trigger_engine.py`의 BUY 경로 점수/게이트
리팩터링 트랙이고, 이 절은 그와 무관한 **별도 인시던트**(`execution_
service.py`의 KIS 제출 직전 게이트) 수정을 기록한다.

**(1) 인시던트 요약(2026-08-03 KST)**: `001450`의 `order_request`가
`validated` 상태에서 멈춰 KIS 제출 전 `stale_snapshot_guard`에 매번
차단됐다. read-only 조사 결과 원인은 계좌가 전량 매도로 quantity=0이
된 이후, `position_snapshots.list_latest_by_account()`가 그 quantity=0
행을 계속 "최신 행"으로 반환해 `_check_account_snapshot_freshness()`의
"zero-position account policy"(목록이 비어 있으면 cash만 fresh해도
통과)가 실제로는 발동하지 못한 것으로 확정됐다. 전체 이력 기준
`stale_snapshot_guard` 차단 134건 중 76건이 `is_position_stale=true`,
그중 63건이 이 zero-qty-latest 패턴이었다(오늘 4건은 cash도 fresh한
순수 격리 사례로 가설을 확정).

**(2) 설계 비교**: A안(함수 내부에서 `quantity>0` 필터 후 freshness
계산) / B안(전용 repository 계약 추가) / C안(`list_latest_by_account()`
의미 자체 변경) / D안(계좌별 "최종 확인 시각" 하트비트 신설)을 비교한
결과, `list_latest_by_account()` 호출부 15곳 중 14곳이 quantity=0 행을
정확히 필요로 함(PnL 계산, UI 표시, zero-out dedup 등)을 확인해 C안을
기각했고, 이번 문제의 소비처가 `execution_service.py` 1곳뿐이라 리포
지토리 계약 확장(B)도 시기상조로 판단, **A안(가장 보수적이면서
근본 해결)**을 권고했다.

**(3) 코드 적용 완료**: `_check_account_snapshot_freshness()` 내부에서
`list_latest_by_account()` 결과를 `quantity is not None and quantity >
0`인 행만으로 좁힌 뒤(`quantity is None`도 보수적으로 미보유 취급)
`max(snapshot_at)`·staleness를 계산하도록 수정했다. `list_latest_by_
account()` 자체의 반환 계약·저장 로직은 무변화이며, `is_cash_stale`
판정, run-level fallback(`health.is_stale`), `held_position` sell
bypass 등 다른 stale 정책도 전부 무변화다.

**(4) 검증**: `bash scripts/harness/run.sh accept backend-file
src/agent_trading/services/execution_service.py` — 선택된 3개 테스트
파일 중 2개(`test_decision_orchestrator.py`, `test_decision_replay.py`)
에서 총 8건이 실패했으나, 수정 전 `main`에서 `git stash`로 동일하게
재현되는 **선재·무관 실패**임을 확인했다(우리 수정과 무관). 신규
회귀 테스트 2건(`test_account_snapshot_freshness_ignores_stale_zero_
quantity_position`, `test_account_snapshot_freshness_still_blocks_
real_stale_position`)을 `test_decision_orchestrator.py`에 추가해
`ExecutionService._check_account_snapshot_freshness()`를 직접
호출하는 좁은 단위 테스트로 검증했다 — 수정 전 코드로는 첫 번째
테스트가 실패하고(회귀 재현 확인), 수정 후에는 둘 다 통과한다.
`test_decision_submit_pipeline.py`의 기존 stale 관련 테스트 3건은
fixture 변경 없이 그대로 통과했다(신규 케이스만 추가, 기존 케이스는
보정 불필요로 판단).

**(5) 범위 밖**: `cash_stale`/run-level stale/`held_position` sell
bypass 등 다른 stale 정책, B/C/D안, 5-6월의 "cash도 함께 stale"이던
72건 구간의 별도 원인 규명, `memory.py`의 `list_latest_by_account()`
가 `DISTINCT ON` 의미를 지키지 않는 것으로 보이는 별건 불일치, 운영
재기동 이후 실측(이번 턴은 코드 적용까지만, 실측은 다음 턴 과제).

## 15. 하루 단위 `BUY` 퍼널 실측 — `order_request` 병목 위치 확인(2026-08-06 KST, read-only)

`[PRIORITY_MAP] remaining_work_priority_map.md`의 "다음 검증 로드맵"
1순위(④주문요청 미생성 + 종합 퍼널)를 실제로 집계했다. 코드 변경
없음, DB write 없음, 새 AI/API 호출 없음.

### 15.1 저장 경로 확인(추정 없이 재확인)

- 전체 판단 대상: `trading.trade_decisions`(`created_at`).
- 기본 적격성: `decision_json.deterministic_trigger.eligibility_passed`
  (boolean), 사유는 `decision_json.deterministic_trigger.eligibility_
  reasons`(배열, `eligibility_low_relative_activity` 포함 여부로 활동성
  사유를 분리).
- 매수 후보: `decision_json.deterministic_trigger.buy_candidate`
  (boolean).
- downstream 정합 상태: `decision_json.candidate_vs_final.alignment_
  status`(`matched`/`upgraded`/`downgraded`/`suppressed`).
- 최종 판정: `trade_decisions.decision_type`(`buy`/`approve`/`watch`/
  `hold` 등).
- EV 게이트: `decision_json.expected_value_gate.passed`(boolean).
- AI 자체 risk/compliance 의견: `trade_decisions.risk_check_passed`/
  `compliance_check_passed`(boolean 컬럼, decision_json이 아니라
  테이블 top-level 컬럼) — **주의**: 이는 execution 단계의 하드
  가드(`compliance_validator_v1`, `VaR`)와는 다른, AI Risk/Compliance
  에이전트의 자체 의견 플래그다. 실제 execution 단계 하드 가드는
  `trading.execution_attempts.stop_phase`/`stop_reason`에서 확인한다.
- 주문 요청 생성: `trading.order_requests`(`trade_decision_id`로
  `trade_decisions`와 조인, 행이 존재하면 "생성됨").
- **실제 브로커 제출**: `trading.order_requests.submitted_at`(NULL이
  아니면 실제 제출). "생성"과 "제출"은 다른 사건이다 — 아래에서
  분리해서 집계한다.

### 15.2 날짜별 퍼널(2026-08-03 08:50 KST ~ 2026-08-06 13:xx KST, `BUY` 경로 전체)

| 날짜 | 전체 대상 | 적격성 탈락(활동성) | 적격성 탈락(기타) | 매수 후보 | downstream 하향(downgraded) | suppressed | 최종 `buy`/`approve` | EV 게이트 차단 | AI risk/compliance 의견 불일치 | `order_request` 생성 | 실제 제출(`submitted_at`) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 08-03 | 863 | 143 | 0 | 107 | 101 | 434 | 6 | 1 | 0 | **4** | **0** |
| 08-04 | 918 | 756 | 54 | 0 | 0 | 133 | 0 | 0 | 0 | 0 | 0 |
| 08-05 | 864 | 432 | 54 | 108 | 107 | 102 | 1 | 1 | 0 | 0 | 0 |
| 08-06(진행 중) | 969 | 627 | 57 | 114 | 84 | 59 | 30 | 30 | 0 | 0 | 0 |
| **합계** | **3,614** | **1,958** | **165** | **329** | **292** | **728** | **37** | **32** | **0** | **4** | **0** |

집계는 `trade_decisions`/`order_requests`에 대한 read-only `SELECT`
(CTE로 필드 추출 후 `date_trunc`/`GROUP BY`)로 수행했다 — 상세 쿼리는
완료 보고에 남긴다.

### 15.3 `order_request=0`건인 날의 단계별 원인(factual)

- **08-04**: `buy_candidate` 자체가 **0건**이다. 적격성 탈락 918건 중
  756건(82.4%)이 활동성 부족 — 이 날은 매수 후보 단계 이전에 이미
  대부분 소진됐다.
- **08-05**: `buy_candidate` 108건 중 107건이 downstream에서
  `downgraded`됐다. 유일하게 남은 `buy` 1건(`035420`)도
  `expected_value_gate.passed=false`(`edge_after_cost_bps=-12.97`)로
  막혀 `order_request`가 생성되지 않았다.
- **08-06(진행 중)**: `buy`/`approve` 30건 **전부**가 두 종목
  (`051900`, `008930`)의 반복 평가이며, `expected_value_gate.
  passed=false`가 **30/30**(`edge_after_cost_bps`가 각각
  약 `-20.35`/`-14.54`~`-6.54`로 지속적 음수)로 100% 막혔다.
  AI risk/compliance 의견 불일치는 이 기간 전체에서 **0건**으로
  전혀 병목이 아니었다.

### 15.4 `order_request`가 "생성"됐지만 "제출"은 0건인 사례(08-03, 중요)

08-03의 `order_request` 4건(`001450`)은 모두 `status='validated'`,
`submitted_at IS NULL`이다 — **row는 생성됐지만 실제 KIS 제출까지는
가지 못했다.** `execution_attempts`로 원인을 확인한 결과, 4건 모두
§14에서 이미 기록한 `stale_snapshot_guard`/`stale_snapshot` 인시던트
(PR #119, 08-03 16:57 KST 병합, 이 4건은 그 **이전** 발생분)와 정확히
일치한다 — 새로운 원인이 아니라 기존에 문서화된 인시던트의 재확인이다.
같은 종목의 5번째 `approve`(14:57)는 `ev_passed=true`/`risk_check_
passed=true`/`compliance_check_passed=true`였음에도 `buy_duplicate_
guard`/`recent_active_buy_order`로 `order_request` 자체가 생성되지
않았다 — 이미 활성 주문이 있어 중복 생성을 막은 **정상 동작**이다
(오류가 아님).

### 15.5 질문별 답변

1. **`order_request=0`건인 날의 병목**: 08-04는 활동성 게이트(②),
   08-05는 downstream 하향(③) + EV 게이트(④), 08-06은 EV 게이트(④)
   단독. 날짜마다 지배적 병목이 다르다 — 하나로 뭉쳐 말할 수 없다.
2. **매수 후보가 있었는데 주문요청이 0건인 날**: **있다.** 08-05
   (매수 후보 108건 → `order_request` 0건), 08-06(매수 후보 114건 →
   `order_request` 0건). 08-03은 "생성"은 4건 있었으나 "제출"은
   0건이었다.
3. **가장 지배적인 병목 단계**: 전체 판단 대상 기준으로는 활동성
   부족(②)이 물량이 가장 크다(적격성 탈락의 92.2%). 다만 **매수
   후보(329건)까지 좁히면**, downstream 하향(③, 292건 중 상당수)과
   EV 게이트(④, 최종 `buy`/`approve` 37건 중 32건, 86.5%)가 실제
   기회비용이 발생하는 지점이다. 4일 통틀어 **실제 브로커 제출은
   0건**이다.
4. **1-B순위(활동성)/2순위(downstream)에 주는 영향**: 08-04의 극단적
   활동성 차단(82.4%)이 §13.4.4 활동성 표본에 새 관측치를 더한다.
   08-05의 downstream 하향 107건은 §13.2.14 재분해 작업의 표본을
   늘려준다. 08-06의 EV 게이트 100% 차단(2종목, 30건, 지속적 음수
   `edge_after_cost_bps`)은 **④(EV 게이트) 자체도 별도 사후 성과
   검증이 필요하다**는 새 시사점이다 — 이 두 종목의 알파가 실제로
   비용을 못 넘는 것인지, EV 게이트 파라미터(왕복비용/슬리피지
   버퍼)가 과도하게 보수적인지는 아직 미확인이다.

### 15.6 해석(사실과 분리)

- **factual**: 4일간 3,614건의 판단 중 `buy`/`approve`까지 간 것은
  37건(1.0%), `order_request` 생성은 4건(0.11%), 실제 제출은
  0건(0%)이다.
- **해석**: 이 수치만으로 "차단이 과하다"고 단정하지 않는다 — 4일이라는
  짧은 기간, 소수 종목(대부분 2~3종목이 반복 평가되는 구조)이라는
  표본 한계가 있고, EV 게이트가 지속적으로 음수 `edge_after_cost_bps`
  를 계산했다는 것은 실제로 비용을 못 넘는 신호였을 가능성도 배제할
  수 없다. 반대로 "0건이 정상"이라고도 단정하지 않는다 — `[PRIORITY_
  MAP]`의 공통 판단 원칙대로, 주문 0건 수렴은 기회비용 증가 가능성
  으로 먼저 의심하고 사후 성과로 확인해야 한다.
- **미확정**: `051900`/`008930`의 지속적 음수 edge가 실제로 타당한
  신호(비용 대비 기대수익 부족)인지, EV 게이트 파라미터의 문제인지는
  이번 턴에서 판별하지 않았다.

### 15.7 후속 검증에 대한 연결

- 이 퍼널은 `[PRIORITY_MAP]`의 4축(①allocation/②활동성/③downstream/
  ④주문요청 미생성) 분리 관리 원칙을 실제 수치로 뒷받침한다 — ④가
  이번 구간에서 가장 직접적인 최종 병목(37건 중 32건, 86.5%)임을
  처음 정량화했다.
- **신규 후속 과제(④)**: `051900`/`008930`의 지속적 음수 `edge_
  after_cost_bps`에 대한 사후 성과(백테스트) 검증 — 이 두 종목이
  실제로 사후 손실을 피했는지, 기회비용만 발생시켰는지 확인이
  필요하다. 표본이 2종목뿐이라 결론을 낼 단계는 아니다.
- 08-03의 `stale_snapshot_guard` 4건은 §14에서 이미 코드 수정이
  완료된 인시던트의 재확인이라 새 후속 과제가 아니다.

## 16. 종목(symbol) 단위 `BUY` 퍼널 분해(2026-08-06 KST, read-only)

§15의 하루 단위 퍼널을 종목 단위로 더 잘게 분해했다. "얼마나 많이
막혔는가"가 아니라 **실제 매수 후보가 될 수 있었던 종목이 어느
단계에서 막혔는가**에 초점을 둔다. 코드 변경 없음, 새 실측 방법론은
§15와 동일(저장 경로 재확인 포함).

### 16.1 저장 경로(§15와 동일, 표본으로 재확인)

`decision_json.deterministic_trigger.buy_candidate`/`eligibility_
passed`/`eligibility_reasons`, `decision_json.candidate_vs_final.
alignment_status`, `decision_json.expected_value_gate.passed`,
`trading.order_requests.trade_decision_id`/`submitted_at`. 오늘
표본 3건으로 경로를 재확인했다(`buy_candidate_path`/`eligibility_
passed_path`/`alignment_status_path`가 모두 예상한 값으로 나옴).

### 16.2 기간 누적 종목별 퍼널(2026-08-03~08-06, `buy_candidate` 수 내림차순)

| symbol | 전체 판단 | 적격성 탈락(활동성) | 적격성 탈락(기타) | 매수 후보 | 매수 후보 중 downstream 하향 | 최종 buy/approve | EV 게이트 차단 | order_request 생성 | 실제 제출 | 등장 일수 |
|---|---|---|---|---|---|---|---|---|---|---|
| `001450` | 126 | 54 | 0 | **69** | 63 | 6 | 1 | **4** | **0** | 2 |
| `008930` | 165 | 54 | 0 | **57** | 34 | 23 | **23** | 0 | 0 | 3 |
| `051900` | 237 | 0 | 0 | **57** | 50 | 7 | 7 | 0 | 0 | 4 |
| `035420` | 111 | 57 | 0 | 54 | 53 | 1 | 1 | 0 | 0 | 2 |
| `181710` | 111 | 0 | 0 | 54 | **54(100%)** | 0 | 0 | 0 | 0 | 2 |
| `073240` | 237 | 165 | 0 | 38 | 38(100%) | 0 | 0 | 0 | 0 | 4 |
| `081660` | 180 | **180(100%)** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| `138040` | 237 | 165 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| `316140`/`009240`/`068270` | 183 | 111 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| `078930` | 237 | 111 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| `003490` | 108 | 54 | **54** | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| 그 외 17개 종목 | — | — | — | 0 | 0 | 0 | 0 | 0 | 0 | 1~2 |

(전체 30개 종목 원표는 read-only SQL 결과 그대로 — 완료 보고에 전체
표 첨부. `buy_candidate=0`인 나머지 종목은 이 표에서 압축했다.)

### 16.3 일자 × 종목(매수 후보가 1건이라도 있었던 종목만 압축 표시)

| 날짜 | symbol | 전체 | 적격성 탈락(활동성) | 매수 후보 | downstream 하향 | 최종 buy/approve | EV 게이트 차단 | order_request 생성/제출 |
|---|---|---|---|---|---|---|---|---|
| 08-03 | `001450` | 72 | 0 | 69 | 63 | 6 | 1 | 4 / 0 |
| 08-03 | `073240` | 72 | 0 | 38 | 38 | 0 | 0 | 0 / 0 |
| 08-05 | `035420` | 54 | 0 | 54 | 53 | 1 | 1 | 0 / 0 |
| 08-05 | `181710` | 54 | 0 | 54 | 54 | 0 | 0 | 0 / 0 |
| 08-06(진행중) | `008930` | 57 | 0 | 57 | 34 | 23 | 23 | 0 / 0 |
| 08-06(진행중) | `051900` | 57 | 0 | 57 | 50 | 7 | 7 | 0 / 0 |

같은 두 종목(`008930`/`051900`)이 08-04에는 활동성 부족(54건 모두
차단)으로 매수 후보가 0건이었다가, 08-06에는 반대로 100% 매수 후보가
됐다 — **같은 종목이 날짜에 따라 완전히 다른 단계에서 막힌다**는
것을 보여주는 직접 사례다.

### 16.4 보조 랭킹

- **활동성 부족 반복 최다**: `081660`(180건, 3일 내내 100% 차단),
  `073240`(165건), `138040`(165건).
- **매수 후보였다가 downstream에서 가장 많이 내려간 종목**:
  `001450`(63건), `181710`(54건, **등장한 모든 사이클이 100%
  downgrade**), `035420`(53건).
- **최종 buy/approve까지 갔지만 EV 게이트에서 반복 차단된 종목**:
  `008930`(23건), `051900`(7건) — 둘 다 2026-08-06 하루에 집중.
- **`order_request` 생성은 있었으나 실제 제출은 0건인 종목**:
  `001450`뿐이다(4건 생성, 전부 `status='validated'`,
  `submitted_at IS NULL` — §14/§15에서 이미 규명한 `stale_snapshot_
  guard` 인시던트의 재확인).

### 16.5 질문별 답변

1. **활동성 부족 최다 반복 종목**: `081660`(core, 3거래일 관측 전량
   100% 차단).
2. **매수 후보까지 갔지만 downstream에서 가장 많이 내려간 종목**:
   `001450`(63건)과 `181710`(54건, 100% downgrade율) — 둘 다
   "매수 후보였다면 좋은 기회였을 수 있는" 표본이라는 점에서
   운영상 중요도가 높다.
3. **최종 buy/approve까지 갔지만 EV 게이트에서 반복 차단된 종목**:
   `008930`(23건)과 `051900`(7건) — §15.7의 신규 후속 과제(지속적
   음수 edge의 타당성 검증) 대상과 동일하다.
4. **`order_request` 생성은 있었으나 제출 0건인 종목**: `001450`
   하나뿐이며, 새로운 발견이 아니라 기존 인시던트(§14)의 재확인이다.

### 16.6 해석(사실과 분리, 과장 없이)

- **factual**: 이번 4일간 `buy_candidate=true`가 1건이라도 있었던
  종목은 6개(`001450`/`008930`/`051900`/`035420`/`181710`/
  `073240`)뿐이다. 나머지 24개 종목은 이 기간 내내 매수 후보가
  된 적이 한 번도 없다.
- **해석**: "많이 막혔다"는 사실 자체(예: `081660`의 100% 활동성
  차단)는 그 종목이 원래 매수 후보가 될 가능성이 낮았다는 뜻일 수
  있어 운영상 비용이 크지 않다. 반면 `181710`(100% downgrade)과
  `008930`/`051900`(EV 게이트 100% 차단)은 **실제로 매수 후보
  문턱까지 도달했던 표본**이라 운영상 더 무겁게 봐야 한다 — 다만
  이 역시 사후 성과 없이는 "차단이 틀렸다"고 단정하지 않는다.
- **미확정**: `181710`의 downstream 하향이 타당했는지, `008930`/
  `051900`의 EV 게이트 차단이 타당했는지는 사후 성과(백테스트) 확인
  이 아직 없어 판단할 수 없다 — §13.2.14/§15.7의 후속 과제와 동일한
  선상에 있다.

### 16.7 후속 검증 연결

이 종목 단위 분해는 `[PRIORITY_MAP]`의 1-B순위(활동성, `081660`/
`073240`/`138040` 등 신규 chronic 종목 추가)와 2순위(downstream,
`001450`/`181710`을 우선 표본으로) 작업의 구체적 대상 목록을
좁혀준다. ④(EV 게이트) 후속 과제의 대상도 `008930`/`051900`으로
그대로 유지된다 — 이번 턴에서 새로 추가된 대상은 없다.

## 17. `2026-08-06` EV 게이트 차단 30건 — 입력값 구조 분해(2026-08-06 KST, read-only)

§16이 확정한 ④(EV 게이트) 후속 과제(`008930`/`051900`의 지속적
음수 `edge_after_cost_bps`가 알파 부족인지, 비용 가정 문제인지,
임계값 문제인지)를 30건 전부에 대해 입력값 단위로 분해했다. "EV
게이트가 막았다"에서 멈추지 않고 **무엇이 음수를 만들었는지**를
확인하는 것이 목적이다 — 이번 턴에서 EV 게이트의 과잉/정상 여부는
판정하지 않는다. 코드 변경 없음.

### 17.1 저장 경로 확인(추정 없이 재확인)

샘플 row로 재확인한 결과 모든 필드가 `decision_json.expected_
value_gate`의 **top-level**에 있다(추가 nesting 없음): `passed`,
`edge_after_cost_bps`, `expected_return_bps`, `expected_downside_
bps`, `net_expected_value_bps`, `minimum_required_edge_bps`,
`estimated_round_trip_cost_bps`, `slippage_buffer_bps`, `ev_gate_
near_miss_deficit_bps`/`ev_gate_near_miss_threshold_bps`/`ev_gate_
near_miss_override_applied`. 계산식도 값으로 직접 재확인했다 —
`net_expected_value_bps = expected_return_bps - expected_downside_
bps`, `edge_after_cost_bps = net_expected_value_bps - estimated_
round_trip_cost_bps - slippage_buffer_bps`(예: `65.46-52.00=13.46`,
`13.46-8.00-20.00=-14.54`, 정확히 일치). 관련 상위 필드는
`decision_json.deterministic_trigger.entry_score`, `decision_json.
strategy_selection.preferred_strategy`, `decision_json.portfolio_
allocation.max_new_capital_pct`, `decision_json.candidate_vs_final.
alignment_status`, `decision_json.risk_flags`(top-level), `trading.
trade_decisions.risk_check_passed`(테이블 컬럼)다.

### 17.2 30건 행 단위 표(고유 패턴 기준으로 압축, 전체 원본은 조회 명령 참고)

| symbol | decision_type | 건수 | `edge_after_cost_bps` | `expected_return_bps` | `expected_downside_bps` | `net_expected_value_bps` | 왕복비용 | 슬리피지 버퍼 | 최소 요구 edge | `risk_check_passed` |
|---|---|---|---|---|---|---|---|---|---|---|
| `008930` | approve(14)+buy(1) | 15 | -14.54 | 65.46 | 52.00 | 13.46 | 8.00 | 20.00 | 10.00 | false |
| `008930` | approve | 7 | -6.54 | 65.46 | 44.00 | 21.46 | 8.00 | 20.00 | 10.00 | true |
| `051900` | approve(1)+buy(6) | 7 | -20.35 | 65.65 | 56.00 | 9.65 | 8.00 | 22.00 | 10.00 | false |

`ev_gate_near_miss_deficit_bps`/`threshold_bps`는 30건 전부 `null`,
`ev_gate_near_miss_override_applied`는 30건 전부 `false`다 — near-miss
완화 경로가 발동할 만큼 근소한 차이가 아니라는 뜻이다(가장 근접한
경우도 최소 요구치 대비 `16.54bps` 부족, §17.4 참고).

### 17.3 종목별 요약

| symbol | 건수 | `edge` 평균/최소/최대 | `expected_return_bps` 평균 | `expected_downside_bps` 평균 | 왕복비용 평균 | 슬리피지 버퍼 평균 | 고유 `edge` 값 수 |
|---|---|---|---|---|---|---|---|
| `008930` | 23 | -12.11 / -14.54 / -6.54 | 65.46(불변) | 49.57 | 8.00(불변) | 20.00(불변) | 2 |
| `051900` | 7 | -20.35 / -20.35 / -20.35 | 65.65(불변) | 56.00(불변) | 8.00(불변) | 22.00(불변) | **1(완전 불변)** |

- `entry_score`(`008930`=0.6546, `051900`=0.6565), `preferred_
  strategy`(둘 다 `event_continuation`), `max_new_capital_pct`
  (둘 다 `3.0`)는 30건 전부 완전히 동일하다.
- `alignment_status`는 **30건 전부 `matched`** — downstream(③)에서
  이미 하향된 것이 아니라, EV 게이트(④)에서 처음 막혔다는 뜻이다.
  ③과 ④가 이 30건에서는 서로 섞이지 않고 분리돼 있다.
- `risk_flags`는 태그 표현(예: `risk_off`/`risk_off_tone`,
  `event_overlay`/`event_overlay_positive`)이 사이클마다 조금씩
  달라지지만, `high_volatility`/`risk_off`(계열)/`event_overlay`
  (계열)는 30건 모두 공통이다.

### 17.4 패턴 분류

| 패턴 | 대상 | 설명 |
|---|---|---|
| A. 반복 동일 입력(완전 불변) | `051900` 7건 | `edge_after_cost_bps`를 포함한 모든 수치가 7건 동일 — 두 시간 넘게 입력값이 전혀 변하지 않았다. |
| B. 이산적 2-상태 반복 | `008930` 23건 | `expected_downside_bps`(44.00/52.00)와 `risk_check_passed`(true/false)가 함께 두 상태로만 오간다 — 나머지는 전부 불변. |
| C. 최소 요구치 대비 소폭 미달 여부 | 둘 다 아님 | `008930` 최선의 경우도 `10bps` 요구치에 `16.54bps` 부족, `051900`은 `30bps` 부족 — "임계값에 근소하게 못 미친 것"으로 볼 수 없는 큰 격차다. |
| D. 기대수익 자체는 낮지 않음, 하방/비용이 그것을 삼킴 | 둘 다 | `expected_return_bps`(65.46/65.65)는 낮지 않다. `expected_downside_bps`가 그 70~85%를 이미 소진하고, 남은 얇은 마진(9.65~21.46bps)을 왕복비용+슬리피지(28~30bps)가 넘어선다. |

### 17.5 질문별 답변

1. **30건은 몇 개의 고유 패턴인가**: 실질적으로 **3개**다 — `008930`의
   두 상태(다운사이드 44/52)와 `051900`의 한 상태.
2. **`edge_after_cost_bps` 음수의 직접 원인**: **기대수익 부족이
   아니라, 하방추정치가 기대수익의 대부분을 소진한 뒤 남은 얇은
   마진을 비용(왕복비용+슬리피지)이 넘어서는 조합**이다. 최소 요구
   임계(10bps) 자체는 변경한 적이 없으니 "임계값이 높아서"라고
   단정할 근거는 이번 턴 데이터만으로는 약하다 — 다만 비용
   가정(20~22bps 슬리피지 버퍼)이 상당히 크다는 점은 사실로
   확인된다.
3. **`051900`과 `008930`은 같은 이유로 막히는가**: **유사하지만
   완전히 같지는 않다.** 둘 다 "높은 기대수익 - 큰 하방 - 두꺼운
   비용" 구조는 같지만, `051900`은 `net_expected_value_bps`
   자체가 비용 차감 **이전에도 이미 최소 요구치(10bps)에 못
   미친다**(9.65<10.00)는 점에서 `008930`(13.46/21.46, 비용
   차감 전에는 요건을 충족)보다 더 근본적으로 얇은 마진이다. 또한
   슬리피지 버퍼가 `051900`이 `2bps` 더 크다.
4. **`buy`/`approve` 차이가 EV 입력값 패턴과 관련 있는가**: **없다.**
   같은 `edge_after_cost_bps` 값 안에 `buy`와 `approve`가 함께
   섞여 있다(예: `008930` -14.54 그룹에 `approve` 14건 + `buy`
   1건). `decision_type`(buy/approve) 구분은 EV 게이트 계산과
   무관한 다른 필드에서 결정되는 것으로 보인다 — 이번 턴에서는
   그 필드를 특정하지 않았다(미확정).
5. **"알파 부족"/"비용 가정"/"임계값 문제" 중 현재 데이터로 어디까지
   말할 수 있는가**: "알파 부족"이라고 부르기는 어렵다(기대수익
   자체는 65bps대로 낮지 않다). "비용 가정 영향"과 "하방추정 크기"의
   **조합**이 직접 원인이라는 것까지는 factual하게 말할 수 있다.
   "임계값 문제"(10bps가 너무 높다)는 이번 데이터만으로 판단할
   근거가 부족하다 — 두 종목 모두 격차가 16.5~30bps로 커서, 임계값을
   소폭 낮추는 것만으로는 통과하지 못한다.

### 17.6 사실 / 해석 / 미확정

- **factual**: 30건 모두 `alignment_status=matched`(downstream
  개입 없음), `entry_score`/`preferred_strategy`/`max_new_capital_
  pct`가 완전 불변, `051900`은 전 항목 완전 불변, `008930`은
  `expected_downside_bps`/`risk_check_passed`만 두 상태로 변동.
  두 종목 모두 최소 요구치 대비 16.5bps 이상 부족.
- **해석(조심스럽게 구분)**: 기대수익(`expected_return_bps`)
  자체는 두 종목 모두 60bps대로 특별히 낮지 않다 — "알파 신호가
  아예 없다"는 근거는 약하다. 반면 하방추정치가 기대수익의
  70~85%를 소진하는 비중이 크고, 비용/슬리피지 가정(28~30bps)도
  남은 마진을 넘어설 만큼 크다 — 이 두 요소의 조합이 직접 원인일
  가능성이 데이터로 뒷받침된다. 다만 표본이 2종목뿐이라 **일반화하지
  않는다**.
- **미확정**: (1) `expected_downside_bps`의 계산 구성요소
  (`risk_score`/ATR 등)가 실제로 어떻게 산출되는지는 이번 턴에서
  코드 추적하지 않았다. (2) `decision_type`(buy/approve)을 가르는
  필드는 특정하지 않았다. (3) 슬리피지 버퍼(20~22bps)/왕복비용
  (8bps) 가정이 실제 시장 상황 대비 과도한지 적정한지는 이번
  데이터만으로 판단할 수 없다 — 사후 성과(§15.7/§16.7에서 이미
  제기한 후속 과제)와 별개로, 비용 가정 자체의 근거 문서화 여부도
  확인이 필요하다.

### 17.7 후속 검증 연결

- 이 분해는 `[PRIORITY_MAP]`의 ④(EV 게이트) 후속 과제를 "왜
  음수인가"까지 한 단계 더 좁혔다. 다음 단계로 제안하는 것은
  코드 변경이 아니라 **읽기 전용 확인**이다: (a) `expected_
  downside_bps` 계산식의 실제 구성요소를 코드로 추적, (b) `slippage_
  buffer_bps`/`estimated_round_trip_cost_bps` 값이 어디서 오는
  상수/파라미터인지 확인, (c) 이 값들이 실제 시장 데이터(체결
  slippage 이력 등)와 비교 가능한지 탐색.
- 표본이 2종목·30건(대부분 같은 두 종목의 반복)뿐이라 이번 턴
  결론은 이 2종목에 한정된다 — 다른 EV 게이트 차단 사례가 쌓이면
  재검증이 필요하다.

## 18. EV 게이트가 churn-control 설계 의도를 침식하는가(2026-08-06 KST, read-only)

`[DESIGN] expected_return_holding_horizon_and_churn_control_refactor.md` §6의
`Expected Value Gate`가 원래 "좋은 신규 진입은 통과시키고 낮은 기대값만
`WATCH`/`HOLD`로 강등"하려던 설계 의도를 실제로 지키고 있는지,
아니면 신규 진입 자체를 광범위하게 억제하는 방향으로 작동하는지를
§17의 미확정 항목 (a)(b)(c)를 코드 추적으로 해소하면서 검증했다.
`002930`/`051900`을 특정해 정정할 오류는 없었고, 이번 절은 §17이
남긴 "왜 하방/비용 가정이 이런 값이 되는가"라는 구조적 질문에 답한다.

### 18.1 A. 설계 의도 재확인

§6 원문은 "제출 게이트는 사후비용 실질 edge(edge_after_cost_bps)가
`minimum_required_edge_bps` 이상일 때만 통과"하고, 낮은 기대값은
차단이 아니라 `WATCH`/`HOLD`로의 강등이라고 명시한다. 코드
(`expected_value_gate.py`)에서 게이트 통과 실패 시 즉시 `reason_
codes`에 `expected_value_edge_below_minimum_required`만 추가하고
`gate_passed=False`를 반환할 뿐, 이 자체가 "신규 진입을 광범위하게
막으라"는 지시로 읽히지는 않는다 — 설계 문서 어디에도 "가능한 많이
차단하라"는 표현은 없다. 즉 **원래 의도는 사후비용 edge가 실제로
양(+)인 진입만 통과시키는 개별 종목 단위 필터**였다.

### 18.2 B. 현재 입력값이 산출되는 구조(코드 추적, §17 미확정 (a)(b)(c) 해소)

`expected_value_gate.py`를 라인 단위로 추적한 결과, 세 값 모두
**하드코딩된 고정 페널티가 아니라 종목별 실측 지표(ATR·거래량·회전율)
기반 공식**으로 산출된다.

- `expected_return_bps = score_anchor * 100`(§`_resolve_score_
  anchor`) — 대체로 `entry_score`/`ranking` 계열 앵커에서 나온다.
- `expected_downside_bps = risk_anchor * 40 + min(atr_14_pct * 10,
  30)` — ATR 페널티는 **10 곱, 30 상한**.
- `estimated_round_trip_cost_bps = 8.0(entry 기준) + turnover_20d
  구간 가산(<10억 +3, <50억 +1.5, 그 외 +0) + ranking_percentile<
  0.35 시 +2.0`.
- `slippage_buffer_bps = 3.0(entry 기준) + min(atr_14_pct * 4, 15)
  + average_volume_20d 구간 가산(<10만 +4, <30만 +2, 그 외 +0)`.
- `minimum_required_edge_bps = 10.00`(entry 기준, `risk_off_
  exception_path`이면 `+7.50` 추가).

`trading.signal_feature_snapshots`에서 세 종목의 08-03~08-05
실측값을 조회해 이 공식에 그대로 대입한 결과, §17이 보고한 실제
`decision_json` 값(`051900` 슬리피지 22.00, `008930` 슬리피지
20.00, `001450` 슬리피지 18.00)과 **정확히 일치**했다.

| 종목 | ATR 14 | 평균 거래량(20일) | ATR 페널티(하방/슬리피지 상한 도달?) | 거래량 가산 |
|---|---|---|---|---|
| `001450` | 6.7~6.8% | 47.6만~51.9만 | 도달(30/15 상한 모두) | 슬리피지 +0(≥30만) |
| `008930` | 5.6~5.9% | 22.3만~24.2만 | 도달(30/15 상한 모두) | 슬리피지 +2(10만~30만) |
| `051900` | 5.2~5.3% | 8.5만~8.9만 | 도달(30/15 상한 모두) | 슬리피지 +4(<10만) |

**factual**: 세 종목 모두 ATR이 4%를 넉넉히 넘어(5.2~6.8%)
하방·슬리피지의 ATR 성분이 이미 상한(각각 30bps/15bps)에
포화돼 있다 — 즉 이 세 종목에서 ATR 자체는 더 이상 차별 요인이
아니다. 세 종목을 가르는 실질 요인은 **(1) `expected_return_bps`를
결정하는 `score_anchor`(001450=0.8564 vs 008930/051900≈0.65) —
신호 강도 차이, (2) 거래량 구간에 따른 슬리피지 가산(001450=+0,
008930=+2, 051900=+4) — 유동성 차이**다. 즉 하방/비용 가정이
"임의로 부풀려진 고정값"이라는 근거는 이번 코드 추적으로
**배제된다** — 종목별 실측 유동성·변동성에 연동된 공식이다.

### 18.3 구조적 함의 — 두 임계값 사이의 괴리(신규 발견)

위 공식을 정리하면, 진입이 게이트를 통과하려면

```
score_anchor * 100 >= (risk_anchor*40 + 30) + cost + slippage + 10
```

이어야 한다. `008930`(cost=8, slippage=20)의 경우 `risk_anchor`가
0.35~0.55 두 상태를 오가며(§17에서 확인된 `expected_downside_bps`
44.00/52.00과 정확히 일치 — `44=0.35*40+30`, `52=0.55*40+30`),
필요 `score_anchor`는 **0.82~0.90**에 달한다. `051900`(cost=8,
slippage=22)도 유사하게 **0.85 안팎**이 필요하다. 반면 두 종목의
실제 `score_anchor`는 **약 0.65**로, 시스템 상류 단계(①allocation/
②activity 필터)가 candidate로 인정하는 기준선과 큰 차이가 없다.

**이것이 이번 턴에서 새로 확인된 핵심 구조다**: 상류 candidate
필터(entry_score/eligibility 기준 약 0.65 내외)와, EV 게이트가
"사후비용으로 실제 통과"하려면 요구하는 실질 `score_anchor`
(변동성이 큰 종목 기준 0.8~0.9대)가 **서로 다른 기준선에서
독립적으로 설계돼 있고, 두 기준선 사이에 뚜렷한 간극이 있다.**
설계 문서 §6은 이 간극을 명시적으로 다룬 적이 없다 — "낮은
기대값이면 강등"이라는 서술은 있지만, 상류 후보 기준과 하류
게이트 기준이 정합적으로 맞춰져 있다는 서술은 없다. `001450`
(score_anchor=0.8564)처럼 상류 기준을 크게 상회하는 신호만 이
간극을 넘는다.

### 18.4 C. 사후 성과 관점 — 가능 범위와 한계

2026-08-06 16:44 KST 기준, `008930`/`051900`의 08-06 종가는
`instrument_status_snapshots`(다음날 05:05 KST 배치)와 `signal_
feature_snapshots`(당일 20:10 KST 배치) 양쪽 모두에 **아직
반영되지 않았다** — 두 소스 모두 최신 종가가 `2026-08-05`에
머물러 있다. 이는 "가격 데이터 전무"가 아니라 **"장 마감 후
반영 horizon이 아직 도착하지 않은 것"**이다(20:10 KST 배치
시각 이전).

따라서 `008930`/`051900` 자체의 사후 실현수익률 비교는 **이번
턴 시점에서 불가능**하다. 유일하게 확보 가능한 비교군은 08-03
`001450`(EV 게이트를 통과해 `buy`/`approve`로 진행된 유일한
사례, 전체 08-03+ 구간 37건 중)이며, 이마저 **표본 1건**이라
"통과군의 사후 성과가 실제로 더 좋았다"는 인과적 결론을 낼 수
없다. `001450`이 게이트를 통과한 것이 (i) 신호가 실제로 더
우수했기 때문인지, (ii) 유동성이 좋아 비용 가정이 낮게 잡혔기
때문인지, (iii) 두 요인의 결합인지는 §18.2/18.3의 공식 분해로
**구조적으로는** 설명되지만, 그 판단이 사후 수익률로 실제
검증된 것은 아니다.

**미확정으로 남기는 것**: (1) `minimum_required_edge_bps=10`,
ATR 상한(30/15), 거래량 구간 임계(10만/30만) 등 개별 파라미터가
실제 체결 slippage·리스크 이력과 비교해 적정한지, (2) 상류
candidate 기준(entry_score≈0.65)과 하류 게이트 실질 기준
(score_anchor 0.8~0.9대, 변동성 큰 종목 기준)의 간극이 **의도된
이중 안전장치**인지 **조정되지 않은 우연한 부산물**인지, (3)
이 간극을 넘지 못해 차단된 진입들이 실제로 진행됐다면 평균
기대값이 양(+)이었을지 음(-)이었을지.

### 18.5 D. 판정 — 4축 분리

- **A) 설계 의도**: §6은 "사후비용 실질 edge가 있는 진입만 통과"를
  의도했고, "신규 진입을 광범위하게 억제하라"는 지시는 없다.
- **B) 현재 입력 구조**: 하방/비용/슬리피지 값은 임의 고정값이
  아니라 종목별 실측 ATR·거래량·회전율에 연동된 공식이며, 이번
  세 종목에서는 ATR 성분이 상한에 포화돼 사실상 **거래량(유동성)
  구간**이 종목 간 차이를 지배한다 — 이 자체는 설계 의도에서
  크게 벗어나지 않는다.
- **C) 사후 성과 가능 범위**: `008930`/`051900`은 horizon 미도착으로
  검증 불가. `001450` n=1 비교만 가능하며 인과 추론에는 부족하다.
- **D) 설계 목적 침식 여부**: §18.3에서 확인한 **상류 candidate
  기준(≈0.65)과 하류 EV 게이트 실질 통과 기준(변동성 종목
  기준 0.8~0.9대) 사이의 구조적 간극**은, "낮은 기대값만
  강등한다"는 §6 원문의 서술보다 훨씬 좁은 통과 구간을 만든다.
  이는 "EV 게이트가 나쁜 진입만 걸러낸다"는 낙관적 해석보다
  "두 기준선이 서로 맞춰지지 않아 사실상 상류 candidate 대부분이
  하류에서 걸러진다"는 해석에 더 가까운 **구조적 증거**다.

**판정은 두 층으로 분리해서 말해야 한다 — 하나의 확신 수준에
뭉뚱그리지 않는다.**

- **개별 파라미터(비용/하방 공식의 계수·상한, `minimum_required_
  edge_bps=10` 등)의 사후 성과 기준 적정성: "아직 미확정"을
  유지한다.** 이 간극이 "과도한 억제"인지 "의도된 이중 필터"
  인지, 이 간극을 넘지 못한 진입들의 실제 사후 기대값이 음(-)
  이었는지 양(+)이었는지는 사후 성과 데이터 없이는 최종
  판정할 수 없다는 양방향 불확실성이 남아 있다.
- **시스템 목적 차원(churn-control 설계의 본래 우선순위와 현재
  운영이 부합하는가)의 괴리: "운영상 괴리 가능성 큼"으로
  올린다.** `[DESIGN] expected_return_holding_horizon_and_
  churn_control_refactor.md`가 명시하는 이 설계의 핵심 목적은
  **신규 진입 통제가 아니라 보유 후 빈번한 매도/재매수(churn)
  통제**다(§2, §15). 그런데 이 설계 자신의 진입 측 컴포넌트인
  EV 게이트(§6)가 상류 병목(②③)과 결합해 신규 진입 자체를
  4일 연속·37건 중 32건(86.5%) 차단하고 있고, 그 결과 보유
  측 churn-control 계층(§7~§10)은 발동 기회조차 얻지 못했다.
  이것은 표본 부족에서 오는 일시적 관측이 아니라 §18.3에서
  산술적으로 재현 가능한 구조(상류/하류 기준선 간극)로 반복
  확인된 패턴이며, **"신규 진입 억제가 보유 후 churn 억제보다
  앞서 작동하는 운영상 불균형"**이 원래 설계가 상정한 우선순위
  (좋은 진입은 통과 → 그 이후만 통제)와 반대 방향으로 작동하고
  있다는 뜻이다. 개별 수식이 종목별 실측 지표에 근거해 계산
  단위에서는 정확하다는 사실(§18.2)은 이 목적 차원의 괴리를
  반박하지 않는다 — 구현이 각 수식 단위로는 맞아도 결합 결과가
  설계 문서의 목적과 다른 방향으로 흐를 수 있기 때문이다.
- **정책 판단(범위 밖)**: 위 두 판정 모두 EV 게이트의 코드·
  임계값을 지금 바꿔야 한다는 정책 결론으로 이어지지 않는다.
  "목적 침식 징후가 강하다"는 진단과 "그래서 무엇을 바꿔야
  하는가"는 분리된 질문이며, 후자는 개별 파라미터 적정성이
  사후 성과로 확인된 뒤에 다룬다.

### 18.6 factual / 목적 괴리 해석 / 미확정 — 3층 분리 요약

- **factual**: (1) 하방/비용/슬리피지 공식은 종목별 실측 지표
  기반이며 임의 고정값이 아니다(코드로 확인). (2) 세 종목 모두
  ATR 상한에 포화돼 있어 실질 차별 요인은 거래량 구간과
  `score_anchor` 크기다. (3) 08-03+ 구간 37건 중 EV 게이트를
  통과한 것은 `001450` 1건(6회 중 5회)뿐이며, 그 `score_anchor`
  (0.8564)는 `008930`/`051900`(≈0.65)보다 뚜렷이 높다. (4)
  상류 candidate 기준(≈0.65)과 이 세 종목 기준 하류 게이트 실질
  통과선(0.8~0.9대) 사이에 산술적으로 확인 가능한 간극이 있다.
  (5) `008930`/`051900`의 08-06 사후 실현수익률은 이번 턴
  시점(16:44 KST)에 데이터 미도착으로 계산 불가. (6) 설계
  문서(§2, §15)는 이 churn-control 설계의 본래 목적을 "신규
  진입 억제"가 아니라 "보유 후 빈번한 매도/재매수(churn) 억제"로
  명시한다. (7) 이 결과로 4일 연속(2026-08-03~) `order_request`
  실제 제출은 0건이고, 보유 측 churn-control 계층(§7~§10)은
  발동 기회 자체가 없었다.
- **목적 차원 괴리 해석("운영상 괴리 가능성 큼")**: 위 factual
  (4)(6)(7)을 종합하면, EV 게이트(§6, 이 설계 자신의 진입 측
  컴포넌트)가 상류 병목과 결합해 **"좋은 가설은 진입시키고
  이후 churn만 억제한다"는 원래 우선순위를 뒤집어, 신규 진입
  억제가 보유 후 churn 억제보다 앞서 작동하는 운영상 불균형을
  만들고 있다.** 이 판단은 개별 파라미터가 코드상 정확히
  계산된다는 사실(factual (1)(2))과 배치되지 않는다 — 계산
  단위의 정확성과 결합 결과가 설계 목적에 부합하는지는 별개의
  질문이기 때문이다. 이 괴리는 표본이 작아 생긴 일시적 관측이
  아니라 §18.3에서 산술적으로 재현 가능한 구조(상류/하류
  기준선 간극)에서 비롯되므로, 확신 수준을 "의심이 커짐"보다
  한 단계 높은 **"운영상 괴리 가능성 큼"**으로 판정한다.
- **미확정(정책 판단과 무관하게 유지)**: (1) 상류/하류 기준선
  간극이 설계상 의도된 이중 필터인지 우연한 미조정인지. (2)
  개별 파라미터(ATR 상한, 거래량 구간 임계, `minimum_required_
  edge_bps=10`)의 **사후 성과 기준 적정성** — 이것은 위 목적
  차원 판정과 다른 층이며, 이번 정정으로도 확정되지 않는다. (3)
  차단된 진입들의 실제 사후 기대값 방향(양/음) — 표본 부족(n=1
  비교군)과 horizon 미도착으로 판단 불가. (4) 이 진단으로부터
  임계값·공식을 실제로 바꿔야 하는지의 정책 판단 — 이번 턴의
  범위 밖이며 개별 파라미터 적정성이 사후 성과로 확인된 뒤에
  다룬다.

### 18.7 후속 검증 연결

- 다음 단계로 제안하는 것은 코드/정책 변경이 아니라, (a) `008930`/
  `051900` 08-06 종가가 도착하는 대로(내일 05:05 KST 이후)
  당일 사후 수익률을 재계산해 이번 절의 구조적 추론을 실측으로
  보강하는 것, (b) EV 게이트 통과/차단 사례가 더 누적된 뒤
  `score_anchor` 대 `edge_after_cost_bps` 산포를 종목 유동성별로
  나눠 상류/하류 기준선 간극이 이 세 종목에 특유한 것인지 구조적
  경향인지 확인하는 것이다.
- 이번 절의 결론은 여전히 3개 종목(001450/008930/051900) 표본에
  한정된다.

## 19. EV 게이트 개별 파라미터 적정성 — 사후 성과 관점 검증(2026-08-06 KST, read-only)

§18은 **목적 차원의 괴리**를 다뤘다("운영상 괴리 가능성 큼"으로
판정). 이번 절은 그와 별개로, §18.5에서 미확정으로 남긴 **개별
파라미터(`expected_downside_bps`/`estimated_round_trip_cost_bps`/
`slippage_buffer_bps`/`minimum_required_edge_bps`)가 사후 성과
기준으로 정당한지**를 좁힌다. **이 두 판정은 서로 다른 층이며,
같은 강도로 섞지 않는다.**

### 19.1 후행 성과 — 가능한 범위와 명확한 한계

2026-08-06 17:20 KST 기준 가격 소스 재확인: `instrument_status_
snapshots`는 `20260805`까지, `signal_feature_snapshots`는
`2026-08-05 20:00:00+09`까지만 반영돼 있다(둘 다 08-06 종가
미도착 — 다음날 05:05 KST/당일 20:10 KST 배치가 아직 도착하지
않음). 종가 기준만 사용했고 장중 관측은 섞지 않았다.

- **`008930`/`051900`(08-06 결정)**: 결정이 발생한 날(08-06)
  자체의 종가조차 아직 없으므로 **T+0/T+1 어느 시점도 계산할
  근거가 없다.** 이번 턴에서도 이 두 종목의 사후 성과는
  **"불가"로 명확히 남긴다.**
- **`001450`(08-03 결정, 유일한 EV 게이트 통과 사례)**: 08-03/
  08-04/08-05 종가가 모두 있어 **T+1/T+2가 계산 가능하다.**
  진입 근사가(마지막 `approve` 시각 15:03:44는 08-03 장 마감
  15:30 직전이므로, 08-03 종가를 진입가 근사로 사용):

  | 기준일 | 종가 | 진입가 대비 |
  |---|---|---|
  | 08-03(진입 근사) | 37,300 | 0bps |
  | 08-04(T+1) | 36,800 | **-134.0bps** |
  | 08-05(T+2) | 36,700 | **-160.9bps** |

  실제로 이 4건의 `order_request`(13:59/14:19/14:44/15:03,
  전부 `status=validated`)는 **`submitted_at`이 전부 비어 있어
  실제 체결로 이어지지 않았다** — 즉 이것은 "체결됐다면 어땠을
  것인가"의 근사치이지 실현된 손익이 아니다.

- **중대한 한계(horizon 불일치, 억지 결론 방지를 위해 명시)**:
  `holding_profile_policy.py`를 코드로 확인한 결과, `001450`
  (`source_type=core`)의 설계상 의도된 보유 프로파일은
  `core_swing`(최소 보유 2시간)이고, `008930`/`051900`
  (`source_type=event_overlay`, `time_horizon=short`)은
  `event_probe`(최소 보유 **15분**)다. 즉 이 설계가 실제로
  평가하고자 하는 "사후 성과"는 **당일 장중 15분~2시간 수준의
  단기 구간**이지, 다음날/다음다음날 종가가 아니다. 위 T+1/T+2
  수치(24~48시간 뒤)는 **의도된 horizon보다 훨씬 긴 구간의
  근사치**이며, 이 구간 안에는 설계가 평가하려던 움직임과
  무관한 다른 하루치 가격 변동이 섞여 있다. 장중 tick 단위
  가격 데이터가 이번 조회 범위의 소스(`instrument_status_
  snapshots`/`signal_feature_snapshots`, 둘 다 일별 종가 기준)에
  없어 **의도된 horizon에 정확히 맞춘 사후 성과는 이번 턴에서도
  계산 불가능하다.** 아래 해석은 이 한계를 전제로 한다.

### 19.2 파라미터 기여도 분해

세 종목의 `edge_after_cost_bps = expected_return_bps -
expected_downside_bps - estimated_round_trip_cost_bps -
slippage_buffer_bps`를 구성 요소별로 분해했다(단위: bps).

| 종목 | 상태 | `expected_return` | `-expected_downside` | `net_ev` | `-cost` | `-slippage` | `edge` | `min_edge` | 통과에 필요한 추가 개선분 |
|---|---|---|---|---|---|---|---|---|---|
| `001450` | 최선(1건) | 85.64 | -42.00 | 43.64 | -8.00 | -18.00 | **17.64** | 10.00 | 통과(여유 +7.64) |
| `001450` | 중간(2건) | 85.64 | -44.00 | 41.64 | -8.00 | -18.00 | **15.64** | 10.00 | 통과(여유 +5.64) |
| `001450` | 근소 실패(1건) | 85.64 | -52.00 | 33.64 | -8.00 | -18.00 | **7.64** | 10.00 | **2.36bps 부족** |
| `008930` | 낮은 하방(7건) | 65.46 | -44.00 | 21.46 | -8.00 | -20.00 | **-6.54** | 10.00 | **16.54bps 부족** |
| `008930` | 높은 하방(16건) | 65.46 | -52.00 | 13.46 | -8.00 | -20.00 | **-14.54** | 10.00 | **24.54bps 부족** |
| `051900` | 전체(7건) | 65.65 | -56.00 | 9.65 | -8.00 | -22.00 | **-20.35** | 10.00 | **30.35bps 부족** |

**기여도로 본 1차 결론**: `051900`은 `min_edge`와 비교하기도
전에 이미 `net_expected_value_bps`(9.65)가 `minimum_required_
edge_bps`(10.00)에 못 미친다 — **비용/슬리피지를 아예 0으로
가정해도 통과하지 못한다.** 즉 `051900`의 차단 원인은 비용/
슬리피지가 아니라 **`expected_downside_bps`(56.00, 세 종목 중
가장 큼) 그 자체**다. `008930`은 두 상태 모두 `net_ev`는
`min_edge`를 넘지만(13.46/21.46 > 10.00) **비용+슬리피지 합
(28.00)이 그 마진을 전부 삼킨다** — 즉 `008930`의 차단 원인은
**비용/슬리피지 쪽 기여가 더 크다.** `001450`의 유일한 실패
사례는 `downside`가 일시적으로 52.00까지 오른 상태에서 발생한
**근소한(2.36bps) 부족**이다.

### 19.3 민감도 시뮬레이션(정책 제안이 아닌 민감도 확인용)

아래는 "이 항목만 완화됐다면 통과했을까"를 개별적으로 살펴본
것이다. **이것은 파라미터를 바꿔야 한다는 제안이 아니라, 어느
항목의 변화가 결과에 얼마나 민감한지 확인하는 용도로만 쓴다.**

| 시나리오 | `008930`(하방44) | `008930`(하방52) | `051900` | `001450`(근소실패) |
|---|---|---|---|---|
| 현재 상태 | -6.54(부족 16.54) | -14.54(부족 24.54) | -20.35(부족 30.35) | 7.64(부족 2.36) |
| 슬리피지 -5bps | -1.54(부족 11.54) | -9.54(부족 19.54) | -15.35(부족 25.35) | **통과(12.64)** |
| `min_edge`→5.00 | -6.54(부족 11.54) | -14.54(부족 19.54) | -20.35(부족 25.35) | **통과(edge 7.64≥5)** |
| downside -10bps | 3.46(부족 6.54) | -4.54(부족 14.54) | -10.35(부족 20.35) | **통과(17.64)** |
| 위 세 가지 동시 완화 | 8.46(부족 4.54) | 0.46(부족 4.54) | -5.35(부족 10.35) | **통과(여유 +17.64)** |

**시뮬레이션이 보여주는 것**: `001450`의 근소 실패 사례는 **어느
항목을 하나만 완화해도 통과선을 넘는다** — 이는 이 사례가
"임계값에 근소하게 못 미친" 전형적인 near-miss라는 뜻이다. 반면
`008930`(두 상태 모두)과 `051900`은 **세 항목을 슬리피지 -5bps,
`min_edge` 반토막(10→5), 하방 -10bps로 동시에, 상당히 크게
완화해도 여전히 4.54~10.35bps가 부족해 통과하지 못한다** — 즉
이 두 사례의 차단은 "개별 파라미터 하나가 살짝 과했다"로
설명되지 않는, **구조적으로 더 큰 격차**다. 이 시뮬레이션은
파라미터 각각의 "적정 값"을 말해주지 않는다 — 다만 "작은
조정만으로 뒤집힐 사례"와 "여러 항목을 크게 완화해도 여전히
뒤집히지 않는 사례"를 구분해준다.

### 19.4 factual / 해석 / 미확정 — 3층 분리

- **factual**: (1) `051900`은 비용/슬리피지 차감 이전에 이미
  `net_expected_value_bps`가 `minimum_required_edge_bps`에
  못 미친다 — 차단 원인은 `expected_downside_bps` 자체다. (2)
  `008930`은 `net_ev`는 임계치를 넘지만 비용(8)+슬리피지(20)
  합이 마진을 전부 삼킨다 — 차단 원인은 비용/슬리피지 쪽 기여가
  더 크다. (3) `001450`의 유일한 실패 사례는 2.36bps 근소
  부족이며, 개별 항목 하나만 완화해도 통과선을 넘는다(민감도
  시뮬레이션으로 확인). (4) `001450`(EV 게이트 유일 통과,
  체결은 되지 않음)의 종가 기준 T+1/T+2 수익률은 각각
  -134.0bps/-160.9bps로 **음(-)이었다.** (5) `001450`/
  `008930`·`051900` 모두 설계상 의도된 보유 horizon은
  15분~2시간이며, 위 (4)의 T+1/T+2는 그보다 12~192배 긴
  구간이다. (6) `008930`/`051900` 자체의 사후 성과는 08-06
  종가 미도착으로 계산 불가.
- **해석(조심스럽게 구분)**: `001450` 사례 하나만 놓고 보면,
  실현된 하락(-134~-161bps)이 EV 게이트가 가정한 하방(42~52bps)
  보다 훨씬 컸다 — **이 방향의 증거는 "하방 가정이 과도했다"는
  가설과 반대되며, 오히려 하방 가정이 (horizon이 맞지 않는 훨씬
  긴 구간 기준으로도) 작았을 가능성을 보여준다.** 다만 이는
  horizon이 설계 의도(15분~2시간)보다 훨씬 긴 구간(24~48시간)의
  근사치이고 표본이 1건뿐이라, "하방 가정이 적정하다"거나
  "과보수적이지 않다"고 일반화할 근거는 아니다. `008930`/
  `051900`의 차단이 실제로 좋은 진입을 놓친 것인지는 이번 턴
  에서도 **판단할 근거가 없다** — 이 두 종목은 사후 성과 자체가
  계산 불가능하기 때문이다.
- **미확정**: (1) `008930`/`051900`이 실제로 "막아야 할 나쁜
  진입"이었는지 "놓쳤을 가능성이 있는 진입"이었는지 — 08-06
  종가 미도착으로 이번 턴에서도 판단 불가. (2) `expected_
  downside_bps`/`estimated_round_trip_cost_bps`/`slippage_
  buffer_bps`/`minimum_required_edge_bps`의 계수 자체가 설계
  의도 horizon(15분~2시간) 기준으로 정확한지 — 그 horizon에
  맞는 장중 가격 데이터가 없어 이번 턴에서도 검증 불가. (3)
  `001450` 1건의 결과를 다른 종목/다른 날짜로 일반화할 수
  있는지.

### 19.5 개별 파라미터 적정성 — 확신 수준(목적 차원 판정과 분리)

**§18의 "목적 차원 괴리"는 "운영상 괴리 가능성 큼"으로 이미
높게 판정돼 있고, 이번 절은 그 판정을 바꾸지 않는다.** 이번
절이 다루는 **개별 파라미터의 사후 성과 적정성**은 별도로
판정한다:

- **"아직 미확정"을 유지한다.** 근거: (a) 차단된 대표 사례
  (`008930`/`051900`)의 사후 성과 자체가 계산 불가능하고, (b)
  유일하게 계산 가능한 사례(`001450`)는 표본 1건이며 설계
  의도보다 훨씬 긴 horizon의 근사치라 일반화할 수 없고, (c)
  그 1건이 보여주는 방향(실현 하락이 가정 하방보다 큼)은 만약
  일반화된다면 "과보수적이었다"는 가설과 **반대** 방향이다.
  이 세 가지를 종합하면 "의심이 커짐"이나 "과보수성 의심
  큼"으로 올릴 근거가 없고, 오히려 현재 있는 유일한 실증 조각은
  과보수성 가설을 뒷받침하지 않는다.
- 다만 §19.2/§19.3의 기여도 분해는 파라미터 적정성과 무관하게
  유효한 **구조적 사실**이다: `051900`은 하방 추정 자체가 원인,
  `008930`은 비용/슬리피지 합이 원인, `001450`은 근소 차이다 —
  이 구분은 다음 후속 검증에서 "어느 항목을 먼저 검증할지"
  우선순위를 정하는 데 쓸 수 있다.

### 19.6 후속 검증 연결

- (a) `008930`/`051900` 08-06 종가 도착 후(내일 05:05 KST
  이후) 동일한 T+1/T+2 근사 계산을 반복해 이번 절의 "계산
  불가" 상태를 해소.
- (b) 설계 의도 horizon(15분~2시간)에 맞는 장중 가격 데이터
  소스가 존재하는지 별도로 확인 — 있다면 이번 절의 "horizon
  불일치" 한계를 해소할 수 있는 유일한 경로다.
- (c) EV 게이트 통과/차단 사례가 누적되면 `001450`류(비용/
  하방 마진 충분)와 `008930`/`051900`류(마진 자체가 얇거나
  없음)의 구분이 다른 종목에서도 반복되는지 확인.
- 이번 절의 결론도 여전히 3개 종목·8개 EV 입력 상태(001450 3개,
  008930 2개, 051900 1개) 표본에 한정된다.

## 20. A/B/C/D 4축 구조 정리와 다음 착수 순서(2026-08-06 KST, 재정리 — 새 실측 없음)

**이번 절의 목적**: §13~§19에 흩어진 실측 결과를 "활동성 게이트
(A)/downstream 하향(B)/EV 게이트(C)/churn-control 목적-구조
불합치(D)" 4축으로 재정렬해, 다음 착수자가 어디부터 시작할지
바로 판단할 수 있게 한다. **08-07 KST 종가 도착 후 §19 재계산은
이번 절에서 보류하고, 그 이후 이어질 구조적 검토의 우선순위만
정리한다.** 새로운 DB 조회·코드 추적은 이번 절에서 하지 않았다 —
전부 §9/§13.4/§17~§19/`[PRIORITY_MAP]`에 이미 있는 내용의 재배치다.

### 20.1 공통 판단틀(반복 적용)

이 시스템의 목표는 손실 0이 아니라 **감내 가능한 손실 제약 아래
최고의 기대수익률**이다(`AGENTS.md`). 따라서 4축 모두에서 다음
3층을 분리해서 본다 — 이 구분을 섞으면 "차단이 많다"와 "차단이
틀렸다"를 혼동하게 된다.

1. **구조적으로 실제 발동하는가**(코드/이력으로 확인 가능)
2. **어떤 표본을 주로 막는가**(전체 population vs 경계 고득점 구간)
3. **그 차단이 실제 기대수익률 개선에 기여하는가**(사후 성과) —
   **이것만이 차단 장치의 적정성을 결정한다.** 1·2가 참이어도
   3이 미확정이면 "적정하다"고도 "과도하다"고도 말할 수 없다.

### 20.2 A축 — 활동성 부족 게이트(`eligibility_low_relative_activity`)

- **factual**: 최근 구간(08-03~) 차단 비중이 과거 대비 급증
  (8.5~11%→53~54%, §13.4.4). `009420`처럼 직전 4거래일 +36.2%
  급등했지만 활동성 서지 기준(1.10)에 못 미쳐 차단된 사례가
  실제로 존재한다(§13.4.4). eligibility(1.10)와 authoritative
  gate(1.20, risk-off 서브셋)의 이중 하드게이팅은 전체 이력
  13,312건에서 후자 쪽 실제 차단 0건으로 "관측 범위 내 dead"
  판정을 받았다(§13.4.2).
- **해석**: 전체 population 기준으로는 통과군 수익률이 차단군보다
  높은 방향이 유지돼 "고장났다"는 근거는 없다. 다만 운영상
  더 중요한 **경계 고득점 구간**(`entry_score>=0.60`, 특히
  `>=0.65`)에서는 계산 가능 표본이 n=1~2뿐이라 통계적 결론을
  낼 수 없음에도, `009420` 같은 사례가 "과잉 차단 의심"을
  키운다.
- **미확정**: 경계 구간의 사후 성과(표본 n>=10 필요), 이중
  하드게이팅 중 authoritative gate activity 하드 플로어를
  제거해도 안전한지(코드 변경 여부는 이번 문서 범위 밖).
- **사후 성과 검증이 반드시 필요한 것**: 경계 구간 표본이
  두 자릿수로 쌓일 때까지 T+1/T+2, 이후 T+5까지 확장 계산.
- **설계 목적 차원 우선순위**: 중간 — activity gate 자체는
  churn-control 설계(§6~§10)의 일부가 아니라 별도 eligibility
  계층이므로, D축의 "churn-control 목적 침식" 논의와는 직접
  연결되지 않는다. 다만 A축도 신규 진입을 막는 상류 게이트라는
  점에서 C축(EV 게이트)과 같은 "신규 진입 억제 총량"에 기여한다.

### 20.3 B축 — downstream 하향(`candidate_vs_final.alignment_status`)

- **factual**: `alignment_status`가 `downgraded`/`suppressed`인
  사례가 존재하고(§13.2.14), `risk_opinion`/`evidence_strength`
  같은 qualitative 필드는 판별력이 부족함이 재검증으로 확인됐다.
  §17에서 확인한 EV 게이트 30건은 전부 `alignment_status=matched`
  라 이 30건에서는 B축과 C축이 섞이지 않는다(§17.6).
- **해석**: 08-05는 B축(downstream 하향)과 C축(EV 게이트)이 함께
  작동한 날로 식별됐다(§15.2 요약, `[PRIORITY_MAP]` 1순위 항목).
  즉 B축은 날짜에 따라 C축과 결합해 작동할 수 있다 — 항상 분리
  돼 있는 것은 아니다.
- **미확정**: 어느 guard/EV/risk/compliance 단계가 실제로
  하향시켰는지의 구조적 재분해(`override_applied`/`reason_codes`
  조합, `[PRIORITY_MAP]` 2순위 항목)가 아직 없다. `downgraded`/
  `suppressed` 표본의 "가상 진입가" 방법론(§34.5, `[PRIORITY_MAP]`)
  도 미확정이라 사후 성과 연결 자체가 아직 시작되지 않았다.
- **사후 성과 검증이 반드시 필요한 것**: 가상 진입가 방법론 확정
  → `downgraded`/`suppressed` 표본의 forward return 계산 → "이
  downstream 차단이 기대값을 실제로 개선했는가"에 답하는 것.
  이 방법론이 없으면 B축은 A축/C축과 달리 사후 성과 검증을
  **시작조차 못 한 상태**다.
- **설계 목적 차원 우선순위**: 높음(방법론 부재로 착수 지연) —
  B축이 C축과 결합해 작동하는 날이 관측된 이상(08-05), D축의
  "신규 진입이 상류 병목들의 결합으로 과도하게 막힌다"는 진단에
  B축도 기여자로 포함해야 한다.

### 20.4 C축 — Expected Value Gate(§6)

- **factual**(§17~§19에서 이미 확정): 08-03+ 구간 `buy`/`approve`
  37건 중 32건(86.5%)을 이 게이트가 차단. 하방/비용/슬리피지
  공식은 종목별 실측 ATR·거래량 기반이며 임의 고정값이 아니다
  (§18.2). `051900`은 하방 추정 자체가, `008930`은 비용+슬리피지
  합이 주된 차단 원인이다(§19.2). 유일한 통과 사례(`001450`)의
  사후 실현 수익률은 T+1/T+2 모두 음(-)이었다(§19.1) — 다만
  horizon 불일치(설계 의도 15분~2시간 vs 관측 24~48시간)와
  n=1이라 일반화 불가.
- **해석**: 상류 candidate 기준선(≈0.65)과 이 세 종목 기준 EV
  게이트 실질 통과선(0.8~0.9대) 사이에 산술적으로 확인되는
  간극이 있다(§18.3). `008930`/`051900`은 세 파라미터를 동시에
  크게 완화해도 여전히 부족해(§19.3) "임계값에 근소 미달"로
  설명되지 않는 구조적 격차다.
- **미확정**: 개별 파라미터(ATR 상한, 거래량 구간 임계,
  `minimum_required_edge_bps=10`)의 사후 성과 기준 적정성
  (§19.5) — "아직 미확정"으로 유지 중.
- **사후 성과 검증이 반드시 필요한 것**: `008930`/`051900`의
  08-06 종가 도착 후(08-07 05:05 KST 이후) T+1/T+2 재계산 —
  **이번 턴에서는 보류**하고 다음 착수자에게 넘긴다. 설계 의도
  horizon(15분~2시간)에 맞는 장중 가격 데이터 소스가 있는지
  확인하는 것이 horizon 불일치 한계를 해소하는 유일한 경로다.
- **설계 목적 차원 우선순위**: **가장 높음** — C축은 churn-control
  설계(§6~§10) 자신의 진입 측 컴포넌트이면서 동시에 D축 괴리의
  직접적 원인이다.

### 20.5 D축 — churn-control 목적(보유 후 churn 억제) vs 현재 구조(신규 진입 억제)

- **factual**: 설계 문서 §2("보유기간이 짧은가 긴가 자체가 아니라
  거래비용을 감안한 뒤에도 밀어붙일 수 있는가")·§15("현재의 단기
  churn을 줄이면서도 기대값이 높은 종목은 더 오래 보유하게 만드는")
  는 **신규 진입 억제를 목적으로 명시한 적이 없다.** §6.1(EV 게이트
  도입 배경)도 "일부 필드가 비어 있어 기대값 최적화 여부가
  불명확해진다"는 **측정 공백 해소**가 원래 동기였고, §6.3의
  강제 규칙은 REDUCE/EXIT 쪽에 더 엄격한 조건(`edge collapse`/
  `downside risk increase`/`thesis invalidation`/`holding_
  profile risk breach` 중 하나 필요)을 두어 **매도를 어렵게
  만드는 것**이 비대칭의 핵심이었다 — BUY 쪽 `edge_after_cost_
  bps < minimum_required_edge_bps → WATCH/HOLD`는 예시 수준의
  단일 조건이다. 실측상 C축(EV 게이트)이 A/B축과 결합해 신규
  진입 자체를 4일 연속·37건 중 32건 차단했고(`order_request`
  제출 0건), 보유 측 계층(§7~§10)은 발동 기회 자체가 없었다
  (§18.5, §18.6).
- **목적 차원 해석("운영상 괴리 가능성 큼", §18에서 이미 확정,
  이번 절에서 낮추지 않음)**: "좋은 가설은 진입시키고 그 이후만
  통제한다"는 원래 우선순위가 운영상 뒤집혀, **신규 진입 억제가
  보유 후 churn 억제보다 앞서 작동하는 불균형**이 반복 확인됐다.
  A축(활동성)·B축(downstream)·C축(EV 게이트)이 서로 다른
  변수·다른 코드 지점에서 각자 "정당한 이유"로 신규 진입을
  걸러내지만, **그 결과가 누적되면 같은 방향(신규 진입 총량 억제)
  으로 겹친다** — 이것이 "비슷한 변수를 여러 층에서 중복 통제하는
  구조는 과도 통제 가능성으로 의심한다"는 판단 원칙이 이번
  구조에도 적용되는 지점이다. 단, 이 중복은 §7.2(A축 activity
  bonus/hard gate)처럼 "정당한 역할 분리"로 판정된 사례도 있어,
  **모든 중복이 과도 통제인 것은 아니다** — 축별로 분리해서
  판단해야 한다(§20.1의 3층 원칙).
- **미확정(설계 변경 필요성 그 자체)**: "설계와 구현이 일치한다"
  (§18.1~18.2에서 확인)는 사실이 "이 설계가 목적에 부합한다"는
  뜻은 아니다 — 이 둘을 같은 말로 쓰지 않는다. 그러나 **"그래서
  설계를 바꿔야 하는가"는 이번 턴까지도 판단할 수 없다.** 근거:
  (1) C축 개별 파라미터의 사후 성과 적정성이 미확정이고, (2) A축
  경계 구간, (3) B축은 사후 성과 방법론 자체가 없다. 이 세 축의
  사후 성과가 모두 갖춰지기 전에 설계(임계값·공식)를 변경하면,
  "차단을 줄이는 것 자체가 목적"이 되어 이 시스템의 진짜 목표
  (기대수익률 개선)와 다시 어긋날 위험이 있다.
- **설계 목적 차원에서 우선순위가 높은 것**: D축 자체의 "설계
  변경 필요성" 판단은, A/B/C축의 사후 성과가 쌓일 때까지는
  **판단을 유보하되 우선순위 1위로 계속 추적**해야 하는 항목이다
  — 목적 차원 괴리가 이미 강하게 확인된 만큼, 세 축의 사후 성과가
  갖춰지는 즉시 "설계를 바꿀지"를 다시 여는 것이 다음 국면의
  핵심 질문이 돼야 한다.

### 20.6 다음 착수 순서(문서 재정리 기준, 새 우선순위 아님 — 기존 로드맵의 재확인)

`[PRIORITY_MAP]`의 기존 순서(1순위 ④+종합 퍼널 → 1-B순위 ② 활동성
표본 축적 → 2순위 ③ downstream 재분해)를 이번 4축 정리로 재확인
했다 — 변경하지 않는다. 이번 절에서 추가하는 것은 **각 순위 항목이
D축 판단과 어떻게 연결되는지**뿐이다.

1. **C축(EV 게이트) 08-07 재계산** — 08-07 05:05 KST 이후
   `008930`/`051900` 종가 도착 시 §19와 동일한 방법으로 T+1/T+2
   재계산. **이번 턴에서는 착수하지 않고 다음 턴으로 명시 이월**.
2. **A축(활동성) 경계 구간 표본 축적** — `009420`/`180640`/
   `073240`/`078930`/`035420`/`051900`/`008930` 추적 지속, 표본
   n>=10 도달 시 재판정.
3. **B축(downstream) 구조적 재분해 + 가상 진입가 방법론 확정** —
   현재 사후 성과 검증을 시작조차 못 한 유일한 축이라, 방법론
   확정이 선행 조건이다.
4. **D축(설계 변경 필요성) 재검토** — 1~3의 사후 성과가 누적되는
   대로, "churn-control 목적과 신규 진입 억제 구조 사이의 괴리를
   해소하려면 설계(임계값/공식/게이트 배치)를 실제로 바꿔야
   하는가"를 다시 연다. 지금은 이 질문에 답할 근거가 부족하다.

### 20.7 다음 작업자를 위한 후속 프롬프트 재료(그대로 지시문으로 쓸 수 있는 형태)

- **C축용**: "`008930`/`051900`의 2026-08-06 종가가
  `trading.instrument_status_snapshots`/`trading.signal_feature_
  snapshots`에 도착했는지 먼저 확인하고, 도착했다면 §19.1과 동일한
  방법(종가 기준, 장중 관측 배제)으로 T+1(08-07)/가능하면 T+2 수익률을
  계산해 §19의 '계산 불가' 상태를 해소하라. `001450`과 같은 3층
  분리(factual/해석/미확정) 원칙을 유지하고, 이번에도 표본이 2종목
  뿐이면 일반화하지 마라."
- **A축용**: "`[PRIORITY_MAP]`의 추적 대상 종목군(`009420`/`180640`/
  `073240`/`078930`/`035420`/`051900`/`008930`, chronic 차단
  상위 `081660`/`073240`/`138040` 포함)의 T+1/T+2/(가능시 T+5)
  사후 수익률을 갱신하고, 경계 구간(`entry_score>=0.60`, 특히
  `>=0.65`) 표본이 n>=10에 도달했는지 확인하라. 도달하지 않았으면
  '미확정' 판정을 유지하고 그 사실만 기록하라."
- **B축용**: "`downgraded`/`suppressed` 표본에 대해 어느 guard/EV/
  risk/compliance 단계가 실제로 하향시켰는지 `decision_json`의
  `override_applied`/`reason_codes`/`expected_value_gate.passed`/
  `risk_check_passed` 조합으로 재분해하는 표를 만들고, 이 표본들의
  '가상 진입가' 방법론(§34.5 미해결 과제)을 먼저 확정하라 — 방법론
  확정 전에는 forward return을 계산하지 마라."
- **D축용**: "A/B/C축의 사후 성과가 모두 최소 판정 가능한 수준
  (표본 n>=10 또는 방법론 확정)에 도달하면, 'churn-control 설계
  (§6~§10)의 임계값·공식·게이트 배치를 실제로 바꿔야 하는가'를
  다시 열어라. 그 전까지는 목적 차원 괴리('운영상 괴리 가능성
  큼')를 유지하되 설계 변경 여부는 미확정으로 남겨라."

### 20.8 이번 절에서 문서화하지 않은 것(의도적 보류)

- **08-07 종가 재계산 결과** — 아직 데이터가 없어 이번 절에서는
  다루지 않는다(§20.6 항목 1로 명시 이월).
- **설계(코드/임계값) 변경 여부에 대한 결론** — §20.5에서 명시한
  대로 세 축의 사후 성과 없이는 이 질문에 답하지 않는다. "설계와
  구현이 일치한다"는 사실만으로 "그래서 바꿀 필요가 없다"고
  쓰지 않았다.
- **A/B축의 새로운 실측** — 이번 절은 기존 §13.4/§13.2.14 결과의
  재배치이며, 새 SQL 조회를 수행하지 않았다.

## 21. B축(downstream 하향) 가상 진입가 방법론 재구성 및 표준안(2026-08-06 KST, read-only)

**목적**: §20에서 "4축 중 유일하게 사후 성과 검증을 시작조차
못 한 축"으로 남긴 B축의 진행을 위해, 과거에 이미 이 문제를
다룬 문서를 먼저 찾고, 그 방법론이 현재 데이터에 재활용 가능한지
판단한다. 코드 수정 없음, DB write 없음, read-only 조회만 수행.

### 21.1 과거 문서 탐색 결과

`rg`로 `가상 진입가`/`candidate_vs_final`/`alignment_status`/
`forward return` 등을 전체 `docs/`에서 검색한 결과, 이 문제를
실제로 다룬 원본은 **`[DESIGN] signal_predictive_power_
validation.md` §34("`SPPV-3` 축 3 착수 분석", 2026-08-04)**다.
`buy_path_variable_gate_matrix.md`(§17.7)와 `[BACKLOG]`
(5587행 근처)의 "§34.5, 아직 미확정" 표기는 모두 이 원본을
가리키는 참조였고, §34 자체에 방법론 확정 내용은 없었다 —
"다음 착수 턴 과제로 남긴다"(§34.5)로 끝나 있었다. 즉 **가상
진입가를 실제로 정의·계산한 적은 이번 턴 이전까지 한 번도
없었다.**

### 21.2 과거(§34) 방법론 요약

- **검증 질문**(§34.1): AI/EV/submit 레이어의 override·downgrade·
  suppress 개입이 없었다면 deterministic 레이어 단독 판단이 실제
  최종 결정보다 더 나았을지(또는 최소 열등하지 않았을지)를 본다.
- **비교군 설계**(§34.4, 2안 비교): A안(`buy_candidate`/`eligibility_
  passed` 통과 vs 미통과, 축 1의 quintile/IC 방법론 재사용)과
  B안(`candidate_vs_final.alignment_status`로 `suppressed`/
  `downgraded`/`upgraded`/`promoted_from_no_action`을 분리해
  forward return 비교, 이미 존재하는 필드라 즉시 조회 가능) —
  **B안을 1순위로 권고**했다(§34.4 권고).
- **모집단**(§34.5): 전체 이력 기준 `suppressed` 3,775 / `downgraded`
  427건, R5(하류 contract 정리) 마감 이후로 좁히면 `suppressed`
  55 / `downgraded` 24건.
- **가격 소스/한계**(§34.5): "deterministic이 원했던 시점의 가상
  진입가"를 어떤 기준(당일 종가/다음날 시가 등)으로 잡을지
  **방법론 자체가 정해지지 않았다** — 이것이 유일하게 막혀 있던
  지점이다. 통계 방법론으로는 축 1(§9~§33)에서 쓴 **Newey-West
  표준오차 보정 + quintile spread**를 그대로 재사용할 것을
  제안했다(§34.6).

### 21.3 현재(B축, 2026-08-03+) 데이터로 재활용 가능성 판단

**재활용 가능 부분**: `candidate_vs_final.alignment_status` 필드
구조와 `decision_json` 저장 방식은 §34 작성 시점(2026-08-04)과
지금(2026-08-06) 사이에 변경되지 않았다(read-only 확인) — B안의
population 정의는 **그대로 재사용 가능**하다. 2026-08-03 이후로
좁혀 재확인한 결과(`(symbol, decision_date)` 단위, §17/§13.4.4와
동일한 population 정의 방식):

| `alignment_status` | distinct `(symbol, date)` | 비고 |
|---|---|---|
| `downgraded` | 6 | `001450`(08-03)·`073240`(08-03)·`035420`(08-05)·`181710`(08-05)·`008930`(08-06)·`051900`(08-06) |
| `suppressed` | 40 | 08-03~08-06에 걸쳐 20개 이상 종목 |

이 표본 크기(46개 단위)는 §34.5가 언급한 R5 마감 이후 전체 이력
표본(24~55건대)과 비슷한 규모이며, **이미 통계적 유의성을 낼
만큼 크지 않다** — 이 점은 과거와 지금이 같다.

**재활용이 어려운 부분(방법론 자체를 바꿔야 하는 이유)**: §34.6이
제안한 **Newey-West/quintile spread**는 축 1(SPPV, 88종목·수천
행 cross-sectional 표본)처럼 표본이 넓고 독립적인 시점이 많을 때
의미가 있는 방법론이다. 현재 B축 population(46개 단위, 대부분
같은 종목이 여러 날 반복)에 이 방법론을 적용하면 **표본 부족으로
추정치 자체가 불안정해질 위험이 크다** — 이는 실제로 A축(§13.4.4)
과 C축(§19)에서 이미 검증된 패턴과 일치한다: 두 축 모두 §34.6이
제안한 무거운 통계 방법론을 쓰지 않고, **종가 기준 단순 T+1/T+2
근사 + "표본이 작다"는 명시적 caveat**만으로 진행했다. 즉 **과거에
설계된 방법론(A안이든 B안이든 통계 계층)과 실제로 채택된 실행
방법론(A/C축) 사이에 이미 간극이 있었다** — 이번 턴은 B축도
이 실행 방법론(가벼운 근사)에 맞추는 것이 A/C축과 **비교 가능한
형태**를 유지하는 유일한 방법이라고 판단한다.

### 21.4 B축 가상 진입가 표준안(제안, §19/§13.4.4와 동일 규약 재사용)

- **가상 진입가**: 하향/차단이 발생한 **결정일(decision_date) 종가**
  를 근사로 사용한다(§19.1에서 `001450`에 이미 적용한 규약과
  동일). 이유: 장중 tick 가격 소스가 시스템에 없어(§18.4, §19.1
  재확인) 결정 시각에 정확히 맞춘 가격을 만들 수 없고, 종가는
  두 소스(`instrument_status_snapshots`/`signal_feature_
  snapshots`)에서 이미 검증된 방식으로 조회 가능하다.
- **명시할 한계(look-ahead 방향)**: 결정이 그날 이른 시각(예:
  08:50 KST)에 발생했다면 "결정일 종가"에는 결정 **이후** 하루치
  가격 변동이 전부 포함돼 약한 look-ahead 성격을 갖는다 — 결정이
  장 마감 직전(예: 14:57 KST)이었던 경우보다 이 왜곡이 크다.
  이번 표준안은 이 왜곡을 제거하지 못하고, **명시적으로 남긴다**
  (제거하려면 장중 tick 데이터가 필요하고, 현재 시스템에는 없다).
- **forward return**: T+1(다음 거래일 종가), 계산 가능하면 T+2 —
  T+5/T+20은 거래일이 더 쌓여야 한다(§13.4.4와 동일 원칙).
- **horizon 불일치 caveat 유지**: `holding_profile_policy.py`
  기준 설계 의도 보유 horizon(15분~2시간, §19.1)이 여전히 이
  근사(24~48시간)보다 훨씬 짧다 — 이 한계는 B축에도 동일하게
  적용된다.
- **비교군**: `matched`(개입 없이 그대로 진행된) 표본, 가능하면
  **같은 날·같은 종목**에서 `alignment_status`가 갈린 사이클
  (예: `073240` 08-03에 `downgraded`·`suppressed`가 같은 날
  섞여 있음, `008930`/`051900` 08-06에 `downgraded`·`matched`
  가 같은 날 섞여 있음)을 우선 짝지어 비교한다 — 같은 종목·같은
  날이면 그날의 시장 전체 움직임(베타)이 통제되기 때문이다.
- **A/C축과 비교 가능한 축**: T+1/T+2(공통 horizon), 전체
  population vs 경계 고득점 구간(`entry_score>=0.60`, A축과 동일
  경계), `downgraded`/`suppressed` vs `matched`(B축), chronic
  반복 종목군(`073240`/`051900`/`008930`/`081660`/`138040` —
  A/B/C축에 모두 등장하는 교차 종목).

### 21.5 시범 적용 재검증(2026-08-06 KST 2차) — `suppressed` 08-03 수치 보정 + `matched` 비교군 추가

**보정 사유**: 최초 시범 표(2026-08-06 1차)의 `suppressed` 08-03
집계에서 `001450`의 `suppressed` 상태 사이클(같은 날 3건,
`entry_score=0.6036`)을 그룹핑에서 누락해 종목 수를 11로 잘못
셌다. `001450`은 08-03 하루 동안 `matched`(6건)·`downgraded`
(63건)·`suppressed`(3건) 세 상태를 모두 오갔는데, 재집계 시
`suppressed` 상태의 3건만 빠졌다 — 새로 SQL을 다시 실행해
`(symbol, date, alignment_status)` 조합을 전수 재확인했다(아래
21.5.1). 이번 절이 §21.5의 표를 대체한다.

08-03/08-04 결정일(T+1/T+2 종가가 이미 존재)에 대해 `matched`/
`downgraded`/`suppressed` **세 상태를 모두** 같은 방법(결정일
종가=가상 진입가, 다음 거래일 종가=T+1)으로 재계산했다.
`trading.instrument_status_snapshots` 종가 사용, 장중 관측 배제.

#### 21.5.1 전체 population(경계 구간 분리 전)

| `alignment_status` | 결정일 | 종목 수(symbol×date) | T+1 평균 | T+2 평균 |
|---|---|---|---|---|
| `matched` | 08-03 | 11 | +2.32% | +2.70% |
| `downgraded` | 08-03 | 2(`001450`,`073240`) | +1.73%(혼조: -1.34%/+4.81%) | +4.60%(혼조: -1.61%/+10.81%) |
| `suppressed` | 08-03 | **12**(보정: 11→12, `001450` 추가) | **+2.53%**(보정: +2.88%→+2.53%) | **+3.37%**(보정: +3.83%→+3.37%) |
| `matched` | 08-04 | 17 | +0.91% | 계산 불가(08-06 미도착) |
| `suppressed` | 08-04 | 12 | +0.71% | 계산 불가(08-06 미도착) |
| `downgraded` | 08-04 | 0 | — | — |

#### 21.5.2 경계 고득점 구간(`entry_score>=0.60`, A축과 동일 기준)

같은 population을 그날 도달한 최고 `entry_score`(`max_es`)가
`0.60` 이상인 종목만으로 좁혔다.

| `alignment_status` | 결정일 | 종목 수 | T+1 평균 | T+2 평균 |
|---|---|---|---|---|
| `matched` | 08-03 | 5(`001450`/`068270`/`078930`/`138040`/`383220`) | +3.39% | +4.08% |
| `downgraded` | 08-03 | 2(`001450`/`073240`, 전체와 동일) | +1.73% | +4.60% |
| `suppressed` | 08-03 | 6(`001450`/`068270`/`073240`/`078930`/`138040`/`383220`) | +3.62% | +5.20% |
| `matched` | 08-04 | 3(`051900`/`073240`/`180640`) | +2.61% | 계산 불가 |
| `suppressed` | 08-04 | 3(`051900`/`073240`/`180640`, **matched와 완전 동일 종목**) | +2.61% | 계산 불가 |

#### 21.5.3 결정적 한계 — population 중복(가장 중요한 factual 발견)

이번 재검증에서 드러난 가장 중요한 사실은 평균값 자체가 아니라
**population이 서로 크게 겹친다**는 점이다. `alignment_status`는
사이클(수 분 단위) 단위로 갈리지만 forward return은 `(symbol,
date)` 단위(일봉)로만 계산 가능하므로, 하루에 여러 상태를 오간
종목은 **같은 날의 같은 가격 변동이 여러 버킷에 동시에 집계된다.**

- **08-03**: 그날 등장한 distinct 종목 12개 전부가 최소 2개
  이상의 `alignment_status`에 동시에 속한다(100% 중복).
  `001450`은 `matched`·`downgraded`·`suppressed` 세 버킷
  **모두**에 같은 T+1(-1.34%)/T+2(-1.61%)를 제공한다. `073240`
  은 그날 `matched` 상태가 **한 번도 없어**(`downgraded`/
  `suppressed`만 존재), `073240`을 기준으로 "하향되지 않았다면
  어땠을지"를 비교할 `matched` 대응짝 자체가 없다.
- **08-04 경계 구간**: `matched`(3종목)과 `suppressed`(3종목)가
  **정확히 같은 3개 종목**(`051900`/`073240`/`180640`)이다 —
  같은 날 같은 종목이 어떤 사이클에서는 `matched`, 다른 사이클
  에서는 `suppressed`로 갈렸을 뿐이라, 이 구간에서는 두 버킷의
  평균이 같을 수밖에 없는 **퇴화된(degenerate) 비교**다.
- **함의**: 위 21.5.1/21.5.2의 버킷 간 평균 차이는 "하향된 판단이
  실제로 더 나빴다/좋았다"를 뜻하지 않는다 — 대부분 **같은
  종목·같은 날의 가격 변동이 여러 버킷에 중복 집계된 결과**다.
  08-03~08-04 구간 자체가 관측된 종목 대다수에서 가격이 상승한
  국면(예: `078930` +14.5%, `073240` +10.8%, `383220` +5.2%)
  이었다는 점이 세 버킷 모두 양(+)으로 나온 더 그럴듯한 설명이다
  — **시장 국면(베타) 효과와 게이트 판단의 효과를 이 population
  으로는 분리할 수 없다.**

**이 표에서 말할 수 있는 것(factual)**: (1) `suppressed` 08-03
수치는 11종목/+2.88%·+3.83%가 아니라 **12종목/+2.53%·+3.37%가
맞다**(보정). (2) `matched`/`downgraded`/`suppressed` 세 버킷
모두 08-03/08-04 계산 가능 구간에서 평균이 양(+)이었다. (3)
`073240`(08-03)처럼 `matched` 대응짝이 없는 종목이 존재하고,
08-04 경계 구간은 `matched`=`suppressed` population이 완전히
동일하다.

**이 표에서 말할 수 없는 것(과잉해석 방지, 이전보다 강화)**:
(1) 표본이 여전히 종목 2~17개, 통계적 결론 불가. (2) **버킷 간
population 중복이 100%에 가까워, 이 비교로는 "하향이 기대수익률
을 개선했는지/훼손했는지"를 판단할 수 없다** — 이것은 표본 크기
문제를 넘어선 **방법론 자체의 구조적 한계**다. (3) look-ahead
caveat(§21.4)와 horizon 불일치(15분~2시간 vs 24~48시간)는
그대로 유지된다. **"하향 게이트가 좋은 진입을 놓쳤다"도 "하향
게이트가 나쁜 진입을 잘 막았다"도 이번 데이터로는 말할 수
없다.**

### 21.6 factual / 해석 / 미확정

- **factual**: (1) 가상 진입가 방법론은 §34(2026-08-04)에서
  설계만 되고 실제로 정의된 적이 없었다. (2) B안(`alignment_
  status` 기반)의 population 정의는 지금도 유효하며 2026-08-03+
  구간에서 `downgraded` 6/`suppressed` 40개 단위(symbol×date)를
  확인했다. (3) §34.6이 제안한 Newey-West/quintile 방법론은 A/C
  축에서 실제로 쓰인 적이 없다. (4) 최초 시범 표의 `suppressed`
  08-03 수치는 표본 1개(001450) 누락으로 부정확했다 — §21.5.1로
  보정했다(11종목/+2.88%·+3.83% → 12종목/+2.53%·+3.37%). (5)
  `matched`/`downgraded`/`suppressed` 세 버킷 모두 계산 가능
  구간에서 평균이 양(+)이었다. (6) 08-03 distinct 종목 12개 전부,
  08-04 경계 구간 3종목 전부가 하루 동안 2개 이상의 `alignment_
  status`를 오갔다 — population이 버킷 간에 크게 중복된다.
- **해석**: 세 버킷 모두 양(+)이라는 사실은 "하향/차단이 실제로
  좋은 진입을 놓쳤다"는 근거로 읽을 수도 있지만, §21.5.3의 population
  중복 때문에 **그 방향의 해석도, 반대 방향(차단이 정당했다) 해석도
  이번 데이터로는 뒷받침되지 않는다** — 관측된 양(+) 평균은 이
  2일 구간의 전반적 상승 국면(베타)을 반영할 가능성이 더 크다.
  "차단=나쁜 진입"이라는 가정도, "차단이 기대수익률을 개선했다"는
  가정도 둘 다 이 population으로는 검증되지 않는다.
- **미확정**: (1) 버킷 간 population 중복을 통제한(예: 같은 종목의
  여러 날 반복 관측을 독립적으로 취급하지 않는) 비교 방법 — 이번
  턴에서 해소하지 못했다. (2) look-ahead 왜곡의 실제 크기. (3)
  08-05/08-06 결정일의 사후 성과(종가 미도착). (4) chronic 교차
  종목(`073240`/`051900`/`008930`)의 A/B/C축 결과가 서로
  일관되는지.

### 21.7 후속 검증 연결(다음 착수 턴 1순위 갱신)

1. **population 중복 문제를 우선 해소한다** — §21.5.3에서 확인한
   대로, 현재 방식(symbol×date 단위 평균)은 버킷 간 중복이 커서
   비교 자체가 성립하지 않는다. 다음 착수 턴은 (a) 종목별 "그날의
   지배적 상태"(예: 사이클 수 가중 최빈값)로 1종목=1버킷만
   부여하는 방식, 또는 (b) `073240`처럼 `matched` 대응짝이 없는
   종목을 제외하고 순수 대응짝이 있는 종목만 비교하는 방식 중
   하나를 확정해야 한다 — 이번 턴에서 새로 발명하지 않고 다음
   턴 과제로 남긴다.
2. 같은 종목·같은 날에 `alignment_status`가 갈린 사이클을 우선
   짝지어 베타 통제 비교를 시도한다(위 1과 같은 문제의식).
3. 08-05/08-06 결정일은 08-06/08-07 종가 도착 후(§20.6 항목 1과
   함께) 재계산한다.
4. 이 결과를 §20의 D축(설계 변경 필요성) 판단에 연결한다 — B축
   사후 성과가 갖춰지는 것이 D축 재검토의 전제 조건 중 하나였다.

## 22. B축 population 중복 해소 방법론 확정 및 시범 재집계(2026-08-06 KST, read-only)

**목적**: §21.7이 다음 턴 1순위로 남긴 population 중복 문제를
해소한다. §21.5.3에서 확인한 근본 원인은 `alignment_status`가
**사이클(수 분 단위) 단위**로 갈리는데 forward return은
**종가(일 단위) 단위**로만 계산 가능하다는 것이었다 — 이번
절은 "하루=1개 라벨"로 강제 압축하는 방법을 확정한다.

### 22.1 현재 집계 단위 재확인

`decision_json.candidate_vs_final.alignment_status`는 매 사이클
(약 5~7분 간격, 하루 약 50~70사이클)마다 새로 판정된다. 같은
`(symbol, date, source_type)` 안에서 이 값이 하루 동안 여러
상태(`matched`/`downgraded`/`suppressed`/`promoted_from_no_
action`)를 오가는 것이 오히려 **일반적인 패턴**이다(§21.5.3
재확인, 아래 22.2에서 전수 재검증). forward return의 유일한
가격 소스(`instrument_status_snapshots`/`signal_feature_
snapshots`)는 일봉 종가만 제공해 사이클 단위로 쪼갤 수 없다 —
이 비대칭이 중복의 유일한 원인이며, 코드나 데이터 구조를 바꾸지
않고는(이번 턴 범위 밖) 근본적으로 제거할 수 없다.

### 22.2 후보 방법론 3안 비교

`(symbol, date)` 단위로 그날 발생한 모든 사이클의 `alignment_
status` 분포를 전수 집계해(2026-08-03/08-04, read-only) 세 방법을
동일 데이터에 적용해봤다.

| 방법 | 정의 | factual 재현성 | 구현 가능성(현재 저장 구조) | look-ahead/selection bias | A/C축과 비교 가능성 | 목적(기대수익률 검증) 부합성 |
|---|---|---|---|---|---|---|
| **1안: 우선순위 규칙**(`downgraded > suppressed > matched`) | 하루 중 단 한 사이클이라도 `downgraded`/`suppressed`가 있으면 그날 전체를 그 라벨로 강제 | 재현 가능(단순 규칙) | 가능 | **낮음(방향 편향 위험 큼)** — 하루의 20%만 개입이 있어도 그날 전체를 "개입일"로 분류해, 실제로는 대부분 `matched`였던 날을 `suppressed` 버킷에 넣는다(§22.3에서 실증). 이 편향은 항상 "개입 있음" 쪽으로만 작동해 방향성이 고정돼 있다 | 낮음 — A/C축은 이런 강제 우선순위를 쓴 적이 없다 | **부적합** — "그날이 실제로 얼마나 개입됐는지"가 아니라 "개입이 한 번이라도 있었는지"만 반영해, 기대수익률 비교의 노출(exposure) 단위를 왜곡한다 |
| **2안: 지배적 상태(사이클 수 다수결)** | 그날 사이클 수가 가장 많은 `alignment_status`를 대표 라벨로 채택, 오염도(비-지배 사이클 비율)를 함께 기록 | 재현 가능(사이클 카운트만 필요, 이미 조회한 데이터) | 가능 — 코드 변경 없이 기존 `decision_json` 집계로 즉시 계산 | **중간, 명시적으로 관리됨** — 오염도를 같이 보고하고 임계치(예: 40%) 이상이면 "혼합 사례"로 별도 표기해 숨기지 않는다 | 높음 — A축(§13.4.4)이 이미 쓴 "단순 근사 + 명시적 caveat" 철학과 동일선상 | **가장 부합** — 그날의 실제 노출 비중을 반영해 "그날 시스템이 실제로 어느 상태로 대부분 운영됐는가"에 가장 가깝다 |
| **3안: 마지막 사이클(장마감 직전) 대표** | 그날의 마지막 사이클 상태만 채택(§19.1의 "결정일 종가=진입가" 관례와 대칭) | 재현 가능 | 가능 | 낮음 — 하루 대부분이 차단이었어도 마감 직전 한 번 통과하면 그날 전체가 `matched`로 분류돼 **반대 방향의 편향**이 생길 수 있다 | 낮음 — 대칭성만 있고 실측 선례 없음 | 부적합 — 그날의 누적 노출이 아니라 마감 시점 상태만 보므로 기대수익률 비교의 취지(그날 무엇이 실제로 얼마나 일어났는가)와 어긋난다 |

### 22.3 추천 표준안: 2안(지배적 상태 + 오염도 명시, 임계치 초과 시 "혼합 사례"로 분리)

**추천 이유**: 1안·3안은 모두 "그날 어느 한 시점의 상태"만으로
전체를 대표시켜 **한 방향으로 고정된 편향**을 만든다(1안은
"개입 있음" 과다표집, 3안은 "마감 시점 상태" 과다표집). 반대로
2안은 그날 실제로 일어난 사이클 분포 전체를 반영하고, 애매한
날(예: 거의 50/50)은 라벨을 강제하지 않고 오염도로 명시해
**"단순함"과 "왜곡 축소"를 동시에 만족**한다 — 이는 이번 턴의
판단 원칙("단순해야 하지만 단순하다는 이유로 왜곡이 큰 방식을
채택하지 않는다")과 정확히 일치한다.

**남는 한계(정직하게 명시)**: 2안도 하루=1라벨 강제는 피할 수
없다 — 사이클 단위의 "그 순간에 진입했다면 어땠을지"는 장중
tick 데이터가 없는 한 어떤 방법으로도 재현 불가능하다(§21.4
already 확인). 또한 대부분의 비교가 **다른 날·다른 종목** 간
비교라 그날의 시장 전체 움직임(베타)이 완전히 통제되지는 않는다
— `signal_predictive_power_validation.md`의 SPPV-2.6이 이미
KODEX 200 벤치마크로 시장 대비 초과수익을 통제한 선례가 있어,
B축에도 같은 시장 조정(market-adjusted return)을 적용하는 것이
다음 단계의 자연스러운 개선 방향이다 — **이번 턴에서는 착수하지
않는다.**

### 22.4 2안 적용 — 시범 재집계(2026-08-03/08-04, read-only)

`(symbol, date)` 단위로 전체 사이클 수 대비 각 `alignment_status`
비율을 계산해 지배 상태를 배정했다. `promoted_from_no_action`이
지배적인 3개 단위(`003490`/`008930`/`090430`, 08-04, 승격 방향
이라 B축(하향) 대상이 아님)는 제외했다. 오염도 40% 이상은
"혼합"으로 별도 표기했다.

| 결정일 | 지배 라벨 | 종목 수 | 종목(오염도) | T+1 평균 | T+2 평균 |
|---|---|---|---|---|---|
| 08-03 | `matched` | 4 | `051900`(29.2%)·`081660`(29.2%)·`111770`(29.2%)·`316140`(29.2%) | +1.19% | +0.91% |
| 08-03 | `suppressed` | 6 | `009240`(23.6%)·`068270`(23.6%)·`078930`(23.6%)·`138040`(23.6%)·`383220`(23.6%)·**혼합**`000810`(46.5%) | +3.68% | +4.61% |
| 08-03 | `downgraded` | 2 | `001450`(12.5%)·**혼합**`073240`(47.2%, `downgraded`/`suppressed`가 52.8/47.2로 거의 동률이나 `matched`는 0%) | +1.73% | +4.60% |
| 08-04 | `matched` | 13 | 전부 오염도 22.2% 이하(`001450`/`004370`/`051900`/`055550`/`068270`/`073240`/`078930`/`081660`/`111770`/`138040`/`180640`/`268280`(0%)/`001800`(0%)) | +0.74% | 계산 불가(08-06 미도착) |
| 08-04 | `suppressed`/`downgraded` | **0** | — 08-04에 지배적으로 하향/차단된 종목이 **없다**(전부 `matched`가 다수) | — | — |

**가장 중요한 재발견**: §21.5.2가 "퇴화(degenerate)"로 보고한
08-04 경계 구간(`matched`=`suppressed`가 완전히 같은 3종목
`051900`/`073240`/`180640`)은, 2안(사이클 다수결)을 적용하면
**셋 다 `matched`가 지배적**(77.8~79.6%)이었다 — 그날 이
종목들은 대부분(약 4/5) `matched`로 운영됐고 `suppressed`는
소수 사이클(약 1/5)에 그쳤다. 즉 §21.5.2의 "퇴화" 현상은 population
중복 문제의 극단적 사례였을 뿐, 2안으로 재분류하면 08-04에는
지배적 `suppressed`/`downgraded` 표본이 **아예 존재하지 않는다.**

### 22.5 factual / 해석 / 미확정

- **factual**: (1) 2안(사이클 수 다수결) 적용 결과 08-04에는
  지배적으로 `suppressed`/`downgraded`인 `(symbol, date)`가
  0건이다 — 이날 모든 종목이 사이클의 다수(≥77.8%)에서
  `matched`였다. (2) 08-03은 `matched` 4/`suppressed` 6/
  `downgraded` 2로 분리되며, 오염도 40% 이상인 혼합 사례(`000810`
  46.5%, `073240` 47.2%)를 별도 표기했다. (3) 08-03 세 버킷의
  T+1/T+2 평균은 모두 여전히 양(+)이었다(`matched` +1.19%/
  +0.91%, `suppressed` +3.68%/+4.61%, `downgraded` +1.73%/
  +4.60%).
- **해석**: 2안으로 중복을 해소해도 세 버킷 모두 양(+)이라는
  방향은 바뀌지 않았다 — 이는 §21.5.3에서 추정한 "이 2일 구간
  전반의 상승 국면(베타)"이 여전히 지배적 설명일 가능성을
  뒷받침한다. `suppressed`(+3.68%/+4.61%)가 `matched`(+1.19%/
  +0.91%)보다 산술적으로는 더 높지만, n=4~6에 시장 조정(market-
  adjusted) 없이 나온 차이라 **"하향이 기대수익률을 개선했다/
  훼손했다" 어느 쪽으로도 결론 내리지 않는다.** 08-04에 지배적
  `suppressed`/`downgraded` 표본이 아예 없다는 사실은, 이날
  "하향 개입이 있었다"는 이전 서술 자체가 사이클 다수결 기준으로는
  과장이었음을 보여준다.
- **미확정**: (1) 시장 조정(KODEX 200 등 벤치마크 차감) 전/후
  방향이 유지되는지. (2) 08-05/08-06 결정일(종가 미도착)의 동일
  재집계. (3) 오염도 40% 이상 혼합 사례(`000810`/`073240`)를
  아예 제외했을 때 결론이 달라지는지. (4) n=4~6 수준을 넘어서는
  표본 확대 후에도 방향이 유지되는지.

### 22.6 후속 검증 연결

1. **시장 조정 도입**(SPPV-2.6 선례 재사용) — B축 T+1/T+2에
   같은 날 KODEX 200(또는 동등 벤치마크) 수익률을 차감해 베타를
   통제한 뒤 재비교한다. 이번 턴에서는 벤치마크 데이터 조회를
   추가하지 않았다.
2. 08-05/08-06 결정일은 종가 도착 후 2안으로 동일하게 재집계한다.
3. 표본이 누적되는 대로(다른 거래일 추가) 오염도 임계치(40%)
   자체의 적정성도 재검토한다 — 이번 턴은 예시값으로 사용했다.
4. 이 결과를 §20 D축(설계 변경 필요성) 판단에 계속 연결한다.

### 22.7 시장 조정(KODEX 200) 도입(2026-08-06 KST 후속, read-only)

**벤치마크 가격 소스 확인**: `069500`(KODEX 200)은 `trading.
instruments`에 존재하지만 `trading.instrument_status_snapshots`
(1차 종가 소스)에는 **전체 이력 0행**이다(read-only 확인) — 이
벤치마크는 이 소스가 커버하는 개별 종목 유니버스에 포함되지
않는다. 대신 `trading.signal_feature_snapshots`에 15행이 있고,
§13.4.4에서 `009420`으로 이미 정확성을 검증한 파생 공식
(`sma_20 * (1 + price_vs_sma_20_pct/100)`)으로 종가를 복원했다
— `009420` 사례와 동일한 방식이므로 이번에도 신규 방법론이
아니다. 복원된 종가: `08-03=99105.0`/`08-04=100330.0`/
`08-05=104300.0`(내부 단위, 비율 계산에만 사용).

**벤치마크 수익률**: 08-03 기준 T+1(→08-04) **+1.24%**, T+2
(→08-05) **+5.24%**. 08-04 기준 T+1(→08-05) **+3.96%**. 즉 이
2일 구간은 시장 전체가 강하게 상승한 국면이었다 — §21.5.3/§22.5
에서 "베타 효과일 가능성"으로 추정했던 부분이 이번 절에서
**실측으로 확인**됐다.

**초과수익률(excess = raw − benchmark) 재계산**(§22.4의 지배적
상태 population, 40% 오염도 임계치, 혼합 사례 포함):

| 결정일 | 지배 라벨 | n | raw T+1 | raw T+2 | excess T+1 | excess T+2 |
|---|---|---|---|---|---|---|
| 08-03 | `matched` | 4 | +1.19% | +0.91% | **-0.05%** | **-4.34%** |
| 08-03 | `suppressed` | 6 | +3.68% | +4.61% | **+2.45%** | **-0.63%** |
| 08-03 | `downgraded` | 2 | +1.73% | +4.60% | **+0.50%** | **-0.64%** |
| 08-04 | `matched` | 13 | +0.74% | 계산 불가 | **-3.22%** | 계산 불가 |
| 08-04 | `suppressed`/`downgraded` | 0 | — | — | — | — |

### 22.8 오염도 임계치 민감도(30%/40%/50% 비교)

08-03/08-04 각 단위의 오염도(§22.4에서 이미 계산)를 30%/40%/50%
세 임계치로 나눠 "혼합" 판정 여부가 바뀌는지 확인했다.

| 임계치 | 08-03 혼합 판정 | 08-04 혼합 판정 |
|---|---|---|
| 30% | `000810`(46.5%)·`073240`(47.2%) — 2건 | 0건(최대 오염도 22.2%) |
| 40%(현재 문서안) | `000810`·`073240` — **동일 2건** | 0건 |
| 50% | **0건**(최대 오염도가 47.2%로 50% 미달) | 0건 |

**30%와 40%는 이번 표본에서 완전히 동일한 결과를 낸다** — 두
혼합 사례(46.5%/47.2%) 다음으로 높은 오염도가 29.2%(4건)라
30~40% 구간 안에 걸리는 단위가 없기 때문이다. **50%는 위험하다**
— `073240`(52.8% `downgraded` vs 47.2% `suppressed`, 거의
동전 던지기 수준의 근소 다수결)을 "깨끗한 `downgraded`"로
받아들이게 되는데, 이는 오염도 임계치의 취지(애매한 날을
숨기지 않고 명시)와 어긋난다.

**"혼합 사례 포함" vs "제외" 민감도**(30/40% 임계치에서만
차이가 남, 50%는 원래 표와 동일):

| 라벨 | 정책 | n | raw T+1 | raw T+2 | excess T+1 | excess T+2 |
|---|---|---|---|---|---|---|
| `suppressed`(08-03) | 포함(현재 문서안) | 6 | +3.68% | +4.61% | +2.45% | -0.63% |
| `suppressed`(08-03) | 30/40%에서 혼합 제외(`000810` 제거) | 5 | +4.29% | +4.85% | +3.05% | -0.39% |
| `downgraded`(08-03) | 포함(현재 문서안) | 2 | +1.73% | +4.60% | +0.50% | -0.64% |
| `downgraded`(08-03) | 30/40%에서 혼합 제외(`073240` 제거) | **1**(`001450`만) | -1.34% | -1.61% | -2.58% | -6.85% |

**중요한 발견**: `downgraded`에서 혼합 사례(`073240`)를 제외하면
표본이 **n=1**로 줄어 §19.1에서 이미 다룬 "`001450` 단일 사례"
문제로 되돌아간다 — 제외 정책은 표본을 오히려 더 취약하게
만든다. 이 때문에 **"오염도로 혼합 사례를 표시하되, 기본 평균
에서는 제외하지 않고 포함한 채 별도 표기만 한다"(§22.4의 기존
정책)를 유지하는 것이 타당**하다 — 제외는 n이 이미 작은 이
표본에서 통계적 안정성을 오히려 해친다.

### 22.9 factual / 해석 / 미확정(§22.7~§22.8 반영)

- **factual**: (1) `069500`(KODEX 200)은 1차 종가 소스에 없고,
  `009420`으로 이미 검증된 파생 공식으로 `signal_feature_
  snapshots`에서 복원했다. (2) 벤치마크 수익률은 08-03 기준
  T+1 +1.24%/T+2 +5.24%, 08-04 기준 T+1 +3.96%로, 이 구간
  전체가 강한 상승장이었다. (3) 시장 조정 후 `matched`(08-03/
  08-04 모두)의 초과수익률은 **음(-)**(-0.05%~-4.34%,08-04
  matched -3.22%)이다. (4) `suppressed`/`downgraded`(08-03)의
  초과수익률은 T+1에는 양(+)(+2.45%/+0.50%), T+2에는 음(-)
  (-0.63%/-0.64%)으로 **horizon에 따라 방향이 달라진다.** (5)
  오염도 임계치 30%와 40%는 이번 표본에서 결과가 동일하고, 50%는
  근소 다수결(52.8/47.2) 사례를 "깨끗함"으로 오분류한다. (6)
  혼합 사례를 제외하면 `downgraded` 표본이 n=1로 줄어든다.
- **해석**: 원수익률의 양(+)은 이 구간의 강한 상승장(베타)을
  크게 반영한 것으로 보인다 — `matched`(개입 없이 통과한
  표본)조차 시장 조정 후에는 음(-)이라는 사실이 이를 뒷받침한다.
  `suppressed`/`downgraded`가 시장 조정 후에도 T+1에는 `matched`
  보다 높은 초과수익률을 보인 것은 사실이나, T+2에는 세 버킷
  모두 비슷하게 음(-)으로 수렴해 **방향이 horizon에 따라
  바뀐다** — 표본(n=2~6)과 관측 기간(2일)이 너무 작아 "하향이
  기대수익률을 개선했다" 또는 "훼손했다" 어느 쪽으로도 안정적인
  결론을 내릴 수 없다. 오염도 임계치는 30%나 40% 모두 이번
  데이터에서는 동등하게 타당하고, 50%는 부적절하다는 것은
  비교적 명확하다.
- **미확정**: (1) 표본이 더 쌓인 뒤에도 T+1/T+2 방향 역전 패턴이
  반복되는지. (2) `matched` 자체가 시장 조정 후에도 음(-)인
  이유(전체 유니버스 성과 대비 이 4~17개 종목이 특별히 나빴는지,
  혹은 우연인지)는 이번 턴에서 규명하지 않았다. (3) 08-05/08-06
  결정일의 동일 재집계 — 아래 §22.10에서 새로 확인한 데이터
  가용성 변화를 반영해 다음 턴 과제로 넘긴다.

### 22.10 후속 검증 연결(갱신) 및 신규 데이터 가용성 확인

이번 턴 조회 중 `trading.signal_feature_snapshots`의 전체 최신
`snapshot_at`이 **`2026-08-06 20:00:00+09`까지 갱신**돼 있음을
확인했다(read-only, 이전 턴들에서는 `2026-08-05 20:00:00+09`가
최신이었다) — 오늘(08-06) 20:10 KST 배치가 실행되며 `008930`/
`051900`을 포함한 08-06 종가가 이 파생 소스로는 **이제 계산
가능**해졌다(`instrument_status_snapshots` 1차 소스는 여전히
08-05까지만 반영돼 있어, 08-06 종가는 파생 소스로만 확인
가능하다). **이번 턴은 시장 조정/오염도 임계치 검증에 범위를
한정했으므로 이 신규 가용 데이터로 §19/§20의 08-06 재계산을
시도하지 않는다** — 다음 착수 턴에 명시적으로 넘긴다.

1. **다음 턴 1순위(갱신)**: 위에서 확인한 08-06 파생 종가 가용성을
   이용해 (a) §19의 `008930`/`051900` C축 T+1 재계산, (b) §22의
   B축 08-05 결정일 T+1 재계산(08-04 결정일의 T+2도 이제
   계산 가능)을 함께 진행한다 — `009420` 검증 공식을 그대로
   재사용하고 1차 소스(`instrument_status_snapshots`)와의 정합성
   재확인을 선행한다.
2. 표본이 누적되는 대로(다른 거래일 추가) `matched` 자체의
   시장 조정 후 성과가 왜 음(-)인지, T+1/T+2 방향 역전이
   반복되는지를 재확인한다.
3. 오염도 임계치는 **40%(또는 동등한 30%)를 유지**하고 50%는
   채택하지 않는다 — 이번 절에서 사실상 확정했다.
4. 이 결과를 §20 D축(설계 변경 필요성) 판단에 계속 연결한다.

### 22.11 시장 벤치마크 비교 폐기 및 08-05/08-06 재집계 방침(2026-08-06 KST 후속, read-only)

**시장 벤치마크 비교 폐기**: §22.7의 KODEX 200 시장 조정 접근을
이번 턴부터 기본 경로에서 제외한다 — 현재 한국 시장 지수는
삼성전자/SK하이닉스 영향이 지나치게 커서 개별 종목 `BUY` 경로
검증의 기준점으로 쓰기에는 왜곡 가능성이 크다는 문제의식을
반영했다. 이후 B축 검증은 **절대수익률 + 대표 라벨 비교**를
기본으로 하고, "상승장/하락장 국면 영향을 배제할 수 없다"는
한계를 매번 명시한다. §22.7~§22.9의 초과수익률 수치 자체는
factual 기록으로 남기되, 앞으로의 판단 근거로는 재사용하지
않는다.

**가격 소스 우선순위 재확인**: 1차 소스(`instrument_status_
snapshots`, `source_type='kis_stock_basic_info'`)의 전체 최신
종가일은 **`2026-08-05`**다(SQL 재확인). 핵심 종목별로도 `008930`/
`051900`/`035420`/`073240`은 08-05까지 반영돼 있으나, **`181710`
은 이 소스에 전체 이력 0행**(§13.4.4에서 이미 확인된 구조적 공백,
재확인해도 변함없음). 보완 소스(`signal_feature_snapshots`,
`timeframe='1d'`)는 이번 턴 조회 시점(22:04 KST) 기준 **`2026-
08-06 20:00 KST`까지 갱신**돼 있고, `sma_20*(1+price_vs_sma_20_
pct/100)` 파생 공식으로 08-05 종가를 복원하면 1차 소스 값과
**소수점까지 정확히 일치**한다(`008930` 40350/`051900` 292500/
`073240` 7380, 재검증). **사용 기준**: 1차 소스가 있는 날짜·
종목은 1차 소스를 쓰고, 1차 소스가 없는 경우(① 날짜가 08-06
이후라 아직 반영 전, ② `181710`처럼 종목 자체가 이 소스에 없음)
에만 파생 소스로 보완한다 — 이번 재집계에서 실제로 파생 소스를
쓴 경우는 (a) 모든 08-06 종가(1차 소스 미도착), (b) `181710`의
08-05 종가(1차 소스 자체 결측)뿐이다.

**두 소스 혼용의 왜곡 가능성(명시)**: 같은 종목의 T+1을 계산할
때 진입일(08-05)은 1차 소스, 도착일(08-06)은 파생 소스를 쓰는
**소스 혼용**이 대부분의 08-05 T+1 계산에서 발생한다. 두 소스가
`009420`/`008930`/`051900`/`073240`으로 이미 검증된 대로 겹치는
구간에서는 정확히 일치하지만, 이 검증은 **과거 날짜(07-31~08-05)
에서만** 이뤄졌다 — 08-06처럼 처음 등장하는 날짜에 대해 두
소스가 계속 일치하는지는 08-07 05:05 KST 배치로 1차 소스가
08-06을 반영한 뒤에야 최종 확인 가능하다. 이번 재집계의 T+1
(08-05→08-06) 수치는 **이 미확인 전제 위에 있다**는 것을
명시한다.

### 22.12 08-05/08-06 대표 라벨 재집계(지배적 상태+오염도, §22.2~22.4 방식 재사용)

`(symbol, date)` 단위로 사이클 분포를 전수 재확인해 지배 라벨과
오염도를 산출했다(방법은 §22.2/§22.4와 동일, 새로 발명하지
않음).

#### 22.12.1 08-05 결정일

| 지배 라벨 | 종목 수 | 오염도 범위 | 종목(오염도) |
|---|---|---|---|
| `matched` | 14 | 11.1~16.7% | `003490`(0%)·`004370`(16.7%)·`006040`(14.8%)·`008930`(14.8%)·`009240`(14.8%)·`018260`(11.1%)·`021240`(13.0%)·`051900`(13.0%)·`073240`(13.0%)·`078930`(14.8%)·`081660`(14.8%)·`111770`(16.7%)·`138040`(14.8%)·`483650`(16.7%) |
| `downgraded` | 2 | 0~1.9% | `035420`(1.9%)·`181710`(0%, 1차 소스 결측이라 종가는 파생 소스 사용) |
| `suppressed` | **0** | — | 이날 지배적으로 `suppressed`인 종목이 없다 |

40% 임계치 기준 **혼합 사례 0건** — 08-05는 08-03보다 훨씬
깨끗하게 분리된다(오염도 최고값이 16.7%로, 08-03의 46.5%/47.2%
와 대비된다).

**T+1(08-05→08-06, 1차+파생 혼용) 절대수익률**:

| 지배 라벨 | n | T+1 평균 | 비고 |
|---|---|---|---|
| `matched` | 14 | **+5.16%** | `051900`(+10.77%)·`008930`(+8.55%)처럼 큰 양(+) 이동이 다수 |
| `downgraded` | 2 | **-0.31%**(`035420` -1.31%, `181710` +0.70%) | `matched`보다 낮음 — 08-03의 방향(하향이 더 높음)과 **반대** |
| `suppressed` | — | 계산 대상 없음 | |

경계 고득점 구간(`entry_score>=0.60`): `matched` 7종목
(`003490`/`006040`/`008930`/`018260`/`051900`/`073240`/`078930`)
T+1 평균 **+5.17%**(전체와 거의 동일), `downgraded` 2종목 그대로
**-0.31%**(전체 population과 동일 — 이날 `downgraded`는 원래
2종목뿐이라 경계로 좁혀도 바뀌지 않는다).

T+2(08-05→08-07)는 **08-07이 아직 도래하지 않은 미래 날짜라
계산 불가**(horizon 미도착, 데이터 공백이 아니다).

#### 22.12.2 08-06 결정일

| 지배 라벨 | 종목 수 | 오염도 범위 | 종목(오염도) |
|---|---|---|---|
| `matched` | 14 | 0~1.8% | `009240`·`018260`·`035420`·`055550`·`068270`·`069540`·`073240`·`078930`·`138040`·`181710`·`196170`·`316140`(전부 0%)·`009420`(1.8%)·`175330`(1.8%) |
| `downgraded` | 2 | 12.3~**40.4%** | `051900`(12.3%)·**`008930`(40.4%, 40% 임계치 경계에 걸리는 혼합 경계 사례 — `downgraded` 34사이클/`matched` 23사이클, 59.6/40.4)** |
| `suppressed` | 1 | 0% | `001800` |

T+1(08-06→08-07)/T+2(08-06→08-08) 모두 **계산 불가** — 08-07/
08-08은 아직 도래하지 않은 미래 날짜다(horizon 미도착, 소스
공백이 아니다). 이번 절에서는 population과 오염도 분포만
확정하고, 수익률은 다음 거래일 종가가 실제로 쌓인 뒤(08-07
05:05 KST 이후 1차 소스 반영 시점) 재계산한다.

### 22.13 factual / 해석 / 미확정

- **factual**: (1) 08-05는 `matched` 14종목/`downgraded` 2종목
  (`035420`/`181710`)으로 분리되고 `suppressed` 지배 사례는
  0건이다. (2) 08-06은 `matched` 14/`downgraded` 2(`008930`
  오염도 40.4%로 경계)/`suppressed` 1(`001800`)로 분리된다.
  (3) 08-05 T+1(파생 소스로 보완한 08-06 종가 기준) 절대수익률은
  `matched` +5.16%, `downgraded` -0.31%로 — **08-03(하향이
  더 높음)과 정반대 방향**이다. (4) 08-06 결정일의 T+1/T+2는
  08-07/08-08이 미래라 전부 계산 불가다. (5) 08-05/08-06 모두
  오염도가 08-03보다 훨씬 낮다(최고 16.7%/40.4% vs 08-03의
  46.5%/47.2%) — 이 2일은 대표 라벨이 실제 사이클 분포를 더
  안정적으로 반영한다.
- **해석**: 08-03에서는 `suppressed`/`downgraded`가 `matched`
  보다 산술적으로 높았고, 08-05에서는 반대로 `matched`가
  `downgraded`보다 훨씬 높다 — **날짜에 따라 방향이 뒤집힌다.**
  이는 하나의 날짜만으로 "하향이 기대수익률을 개선/훼손한다"는
  일반화를 내릴 수 없다는 것을 다시 보여준다. 시장 벤치마크
  비교를 폐기했으므로, 이 방향 전환이 종목 고유의 판단 품질
  차이인지 그날그날의 시장 국면(상승/하락) 차이인지는 **이번
  절만으로 분리할 수 없다** — 이는 벤치마크 폐기가 받아들인
  명시적 대가다.
- **미확정**: (1) 08-06 결정일의 실제 사후 성과(08-07 종가 도래
  후 재계산 필요). (2) `008930`(08-06, 오염도 40.4%)이 40%
  임계치 기준 정확히 어느 쪽으로 분류돼야 하는지 — 경계값에
  걸려 있어 임계치를 40.0%로 엄격히 적용하면 "혼합"이지만
  40.5%로 완화하면 "깨끗한 downgraded"가 된다. (3) 두 소스
  혼용(1차+파생)이 08-06처럼 처음 등장하는 날짜에서도 계속
  정확히 일치하는지 — 08-07 1차 소스 반영 후 사후 검증 필요.
  (4) 날짜 간 방향 전환(08-03 vs 08-05)이 표본이 더 쌓여도
  반복되는 패턴인지, 이 2건의 우연인지.

### 22.14 후속 검증 연결

1. **08-06 결정일 사후 성과**: 08-07 05:05 KST 이후 1차 소스가
   08-06 종가를 반영하면 즉시 T+1을 계산하고, 같은 시점에 08-06
   종가가 1차 소스와 파생 소스에서 일치하는지(§22.11의 미확인
   전제) 함께 검증한다.
2. **`008930`(08-06) 경계 오염도** 재확인 — 다음 거래일 사이클이
   추가되면 이 경계값이 어느 쪽으로 안정되는지 관찰한다.
3. 날짜 간 방향 전환(08-03 vs 08-05)의 반복 여부를 표본이
   쌓이는 대로 계속 추적한다 — 시장 벤치마크 비교를 폐기한
   이후에는 이 방향 전환을 "종목 판단 품질"과 "시장 국면" 중
   무엇으로 설명할지 별도 근거(예: 동일 시점 KOSPI 상승/하락
   여부를 참고 정보로만 기록하되 차감 계산에는 쓰지 않는 방식)
   가 필요할 수 있다 — 이번 턴에서 새로 설계하지 않는다.
4. 이 결과를 §20 D축(설계 변경 필요성) 판단에 계속 연결한다.

### 22.15 §22.11 미확인 전제 해소(2026-08-07 KST, read-only)

2026-08-07 05:05 KST 배치 이후 1차 소스(`instrument_status_
snapshots`)에 `2026-08-06` 종가가 반영됐다(전체 350행 신규).
§22.11이 "미확인 전제"로 남긴 질문(파생 소스와 1차 소스가 처음
등장하는 날짜에서도 일치하는지)을 재확인한 결과, 겹치는 5개
종목(`001800`/`008930`/`035420`/`051900`/`073240`) 전부
**소수점까지 정확히 일치**했다 — 미확인 전제가 해소됐다. 상세
재계산과 4일 누적 설명력 재평가는 §23에서 다룬다.

## 23. `2026-08-07` 05:10 KST 이후 실측 갱신 — B/C축 4거래일 누적 설명력 재평가(read-only)

**중요한 정정**: 이번 턴의 원래 목표는 "`2026-08-06` 결정분의
실제 T+1"이었으나, 실측 결과 **이는 이번 턴에서도 충족되지
않는다** — T+1은 `2026-08-06` 결정에 대해 `2026-08-07` 종가가
필요한데, 조회 시각(07:34 KST) 기준 `2026-08-07`은 아직 장이
열리지도 않은 날이라 어느 소스에도 종가가 없다(진짜 미래 날짜,
데이터 공백이 아니다). 대신 실제로 새로 풀린 것은: (a) `2026-
08-06` 종가가 1차 소스에 반영돼 **`2026-08-05` 결정분의 T+1이
1차 소스로 확정**됐고, (b) **`2026-08-04` 결정분의 T+2도 이제
계산 가능**해졌다. 이 정정을 먼저 명시하고 그 위에서 4거래일
누적을 재평가한다.

**"최근 7일" 표현에 대한 추가 정정**: 이번 턴 지시의 "최근 7일
누적"도 현재 데이터로는 충족되지 않는다 — 이 유니버스의 관측
가능 구간은 `2026-08-03`부터로 이번 턴 시점까지 **거래일 4일**
(08-03/04/05/06)뿐이다. 아래 평가는 4거래일 기준이며, "7일"로
과장하지 않는다.

### 23.1 C축(EV gate) 4거래일 누적 재평가

**factual**: `2026-08-03~08-06` 전체에서 `decision_type IN
('buy','approve')`로 실제 EV 게이트를 통과한 `(symbol, date)`는
**단 4개뿐**이다.

| 결정일 | 종목 | EV 통과 사이클 | EV 차단 사이클 | T+1 | T+2 |
|---|---|---|---|---|---|
| 08-03 | `001450` | 5(edge 15.64~17.64) | 1(근소 실패, edge 7.64) | **-1.34%** | **-1.61%** |
| 08-05 | `035420` | 0 | 1(edge -12.97, 구조적 실패) | **-1.31%** | 계산 불가(08-07 필요) |
| 08-06 | `008930` | 0 | 23(edge -14.54/-6.54) | 계산 불가(08-07 필요) | 계산 불가 |
| 08-06 | `051900` | 0 | 7(edge -20.35) | 계산 불가(08-07 필요) | 계산 불가 |

`001450`의 통과 사이클과 근소 실패 사이클은 **같은 날 같은
종목**이라 forward return이 동일하다(§21.5.3의 population 중복
문제와 동일한 구조) — 즉 이번 턴에도 진짜로 독립적인 "통과군
vs 차단군" 비교가 가능한 조합은 `001450`(통과, T+1 -1.34%)과
`035420`(차단, T+1 -1.31%) **단 한 쌍**뿐이다.

**해석**: 이 유일한 비교 쌍에서 통과군(-1.34%)과 차단군(-1.31%)
의 T+1 성과가 **거의 동일**하다 — EV 게이트가 실제로 "더 나은
진입을 통과시켰다"는 근거가 이번 데이터에서는 **나타나지
않는다.** 다만 n=1 대 n=1이라는 극단적으로 작은 표본이므로,
이것이 "게이트가 무의미하다"는 증거는 아니다 — "게이트가 설명력
을 갖는다는 근거가 아직 확인되지 않았다"는 수준으로만 말할 수
있다. 경계 고득점 구간(`entry_score>=0.60`) 분리는 이번
population 자체가 이미 전부 `entry_score>=0.65`(`001450`=
0.8564, `035420`=0.6503)라 추가 분리의 의미가 없다.

**질문별 답변**:
1. 반복적으로 설명력이 있는가 — **없다(또는 아직 확인되지
   않았다)**. 4거래일 동안 독립적으로 비교 가능한 쌍이 1개뿐이고,
   그 쌍의 성과가 거의 동일하다.
2. 방향이 자주 뒤집히는가 — 표본이 너무 작아 "방향"이라고 부를
   만한 반복 패턴 자체가 없다.
3. 통과군이 반복적으로 더 좋은가, 차단군이 더 좋은가 — **둘 다
   아니다, 거의 동일했다.**
4. 유지보다 완화가 합리적인가 — **완화 후보로 명시할 근거는
   있으나, 표본(n=1 대 n=1)이 정책 판단을 내리기에는 지나치게
   작다.** 이번 턴은 판정 갱신까지만 하고 정책 변경은 하지
   않는다.

### 23.2 B축(downstream 하향) 4거래일 누적 재평가

**08-04/08-06 갱신**: §22.4/§22.12 기준 08-04는 지배적 `suppressed`
/`downgraded`가 0건이라 비교 자체가 성립하지 않는다(변동 없음).
08-04 `matched`(13종목) T+2(08-04→08-06, 신규 계산 가능)는
**+5.85%**다(전 종목 양(+), +1.96%~+13.75%). 08-06은 지배 라벨
(`matched` 14/`downgraded` 2/`suppressed` 1)만 확정되고 T+1/T+2
는 여전히 계산 불가(08-07 필요) — §22.12.2와 변동 없음.

**4거래일 누적 비교표**(대표 라벨 기준, 비교 가능한 날만):

| 결정일 | `matched` T+1/T+2 | `downgraded`/`suppressed` T+1/T+2 | 비교 가능? |
|---|---|---|---|
| 08-03 | +1.19%/+0.91% | `suppressed`+3.68%/+4.61%, `downgraded`+1.73%/+4.60% | 가능 — **하향 쪽이 더 높음** |
| 08-04 | +0.74%/**+5.85%(신규)** | 표본 없음 | 불가(비교 대상 없음) |
| 08-05 | +5.16%/계산불가 | `downgraded`-0.31%/계산불가 | 가능 — **matched가 훨씬 높음** |
| 08-06 | 계산불가 | 계산불가 | 불가(horizon 미도착) |

**해석**: 4거래일 중 실제로 `matched` vs `downgraded`/`suppressed`
비교가 가능한 날은 **08-03과 08-05 2일뿐**이고, 이 2일의 방향이
**정반대**다(08-03은 하향 쪽 우위, 08-05는 매칭 쪽 우위, 격차도
훨씬 큼). 사용자 판단 원칙("방향이 날짜별로 자주 뒤집히면 안정적
설명력 없음으로 해석")을 그대로 적용하면, **이번 4거래일
표본에서 B축은 안정적 설명력을 보이지 않는다.** 다만 비교
가능일이 2일뿐이라 "자주 뒤집힌다"고 부르기엔 관측치 자체가
적다는 것도 함께 밝힌다.

**질문별 답변**:
1. 반복적으로 설명력이 있는가 — 비교 가능한 2일의 방향이
   정반대라 **안정적 설명력이 확인되지 않는다.**
2. 방향이 자주 뒤집히는가 — 비교 가능한 표본(2일) 기준으로는
   **뒤집혔다**고 말할 수 있으나, 표본이 2건뿐이라 "자주"라고
   일반화하지는 않는다.
3. 통과군(`matched`)이 반복적으로 더 좋은가, 차단군이 더 좋은가
   — **날짜마다 다르다.**
4. 유지보다 완화가 합리적인가 — **완화 후보로 명시할 근거가
   있다** — C축과 마찬가지로 판정 갱신 수준이며, 정책 변경은
   하지 않는다.

### 23.3 B축 vs C축 — 어느 쪽이 더 설명력이 약한가

- **C축(EV 게이트)**: 4거래일 동안 실제로 평가된(=`buy`/`approve`
  에 도달한) 표본 자체가 극히 드물다(4개 symbol×date, 그중
  독립 비교 쌍은 1개). "설명력이 없다"기보다 **"설명력을 판단할
  표본 자체가 거의 없다"**는 것이 더 정확한 진단이다.
- **B축(downstream 하향)**: 표본은 C축보다 많지만(46개 이상
  symbol×date 단위, §21.3), 비교 가능한 날이 2일뿐이고 그 2일의
  **방향이 정반대**다. "표본이 있는데도 방향이 불안정하다"는
  점에서 C축과는 성격이 다른 약점이다.
- **종합**: 두 축 모두 "완화 후보"로 명시할 근거가 있지만, 근거의
  성격이 다르다 — C축은 **판단할 데이터 자체의 부재**, B축은
  **있는 데이터의 방향 불안정**이다. 어느 쪽이 "더" 약한지는
  이 차이 때문에 단순 서열화가 부적절하다 — 둘 다 완화 후보로만
  남기고, 실제 완화(정책/코드 변경) 여부는 표본이 더 쌓인 뒤
  판단한다.

### 23.4 factual / 해석 / 미확정

- **factual**: (1) `2026-08-06` 결정분의 T+1은 `2026-08-07`
  종가가 없어 이번 턴에도 계산 불가하다(진짜 미래 날짜). (2)
  `2026-08-05` 결정분 T+1은 1차 소스로 확정됐고 파생 소스와
  완전히 일치했다(§22.15). (3) `2026-08-04` 결정분 T+2(전
  13종목 양(+), 평균 +5.85%)가 신규로 계산됐다. (4) C축은
  4거래일 동안 독립 비교 가능한 쌍이 1개(`001450` vs `035420`)
  뿐이고 두 성과가 거의 동일(-1.34%/-1.31%)했다. (5) B축은
  비교 가능한 날이 2일(08-03/08-05)뿐이고 방향이 정반대다.
- **해석**: 두 축 모두 이번 4거래일 표본으로는 "차단이 기대값을
  개선했다"는 근거도 "훼손했다"는 근거도 안정적으로 제시하지
  못한다. 사용자 판단 원칙에 따라 둘 다 **완화 후보**로 명시
  한다 — 다만 그 근거의 성격이 다르다(§23.3). 이 판정은 표본이
  극히 작다는 것을 전제로 한 "지금까지 유지 근거가 확인되지
  않았다"는 수준이며, "지금 당장 완화해야 한다"는 정책 결론이
  아니다.
- **미확정**: (1) `008930`/`051900`/`001800`(08-06)의 실제
  사후 성과 — `2026-08-08` 05:05 KST 이후 재계산 필요. (2)
  표본이 5거래일·6거래일로 계속 쌓였을 때도 이 불안정성/데이터
  부재가 반복되는지. (3) `008930`(08-06) 오염도 40.4% 경계
  사례의 최종 분류.

### 23.5 후속 검증 연결

1. `2026-08-08` 05:05 KST 이후 1차 소스가 `2026-08-07` 종가를
   반영하면 `008930`/`051900`/`001800`(08-06 결정분)의 T+1을
   계산하고, 같은 시점에 `035420`(08-05)의 T+2도 계산한다.
2. B축/C축 모두 "완화 후보" 판정을 유지한 채 코드/정책 변경은
   하지 않는다 — 표본이 최소 10일 이상(사용자·문서가 반복적으로
   요구한 최소 판정 기준, §13.4.4/§20 참고) 쌓인 뒤 정책 논의를
   시작하는 것이 타당하다.
3. 이 결과를 §20 D축(설계 변경 필요성) 판단에 계속 연결한다 —
   D축 자체의 "설계를 바꿔야 하는가" 판단은 여전히 미확정이며,
   이번 절의 "완화 후보" 표시가 D축 판정을 앞당기는 근거로
   쓰이지 않는다(표본 부족이 공통 한계).
