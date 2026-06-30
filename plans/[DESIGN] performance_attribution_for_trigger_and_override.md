# Trigger / Override Performance Attribution 설계

> 작성일: 2026-06-16
>
> 목적:
> deterministic trigger와 AI override가
> 실제 성과에 어떻게 기여했는지를
> `replay 가능`, `운영 관찰 가능`, `백엔드 deterministic 우선` 원칙 아래에서
> 단계적으로 측정하기 위한 설계를 정의한다.

## 1. 배경

현재까지 이미 확보된 기반은 다음과 같다.

- `signal_feature_snapshot` 계산/저장
- `market_regime / strategy_selection / portfolio_allocation`
- `deterministic_trigger`
- `candidate_vs_final`
- `candidate alignment diagnostics`
- `trigger execution attribution`

즉, 이제는 다음 질문을 다뤄야 한다.

1. 어떤 candidate가 실제 주문/체결로 이어졌는가
2. 어떤 override가 실행 전환율을 높이거나 낮췄는가
3. 어떤 override가 실제 기대수익률 개선에 기여했는가
4. 어떤 trigger bucket이 성과가 나쁜데도 계속 살아 있는가

다만 현재 데이터 모델에서는
`trigger → order → fill` 경로는 비교적 직접 추적 가능하지만,
`trigger → realized pnl`은 아직 완전하게 귀속하기 어렵다.

이유:

- 현재 `trade_decisions`는 decision truth다.
- `order_requests / broker_fill_snapshots / execution_attempts`는 execution truth다.
- 하지만 `포지션 청산 단위의 realized pnl attribution`은
  개별 trade decision 또는 candidate bucket에 완전히 귀속되도록
  아직 모델링되어 있지 않다.

따라서 V1은
`execution attribution`과 `performance attribution`을 분리해야 한다.

---

## 2. 설계 원칙

### 2.1 deterministic backend 우선

성과 attribution 계산은 LLM이 아니라 백엔드 집계 로직이 authoritative 해야 한다.

금지:

- LLM이 order/fill/PnL attribution을 계산하는 구조
- prompt 출력에서 성과 원인 분석을 truth source로 삼는 구조

허용:

- DB snapshot / order / fill / decision metadata를 이용한 deterministic 집계

### 2.2 live-safe 관점 유지

paper 환경이어도 live와 동일하게 취급한다.

따라서 attribution은
운영 안전성에 영향을 주지 않는 read-only 집계로 먼저 도입해야 한다.

### 2.3 execution attribution과 realized pnl attribution 분리

현재 바로 가능한 것:

- decision → order 생성 여부
- decision → filled 여부
- bucket별 execution conversion

현재 추가 설계가 필요한 것:

- decision / candidate / override 단위 realized pnl
- holding period 종료 후 attribution close-out
- partial fill / scale-out / multi-entry consolidation

### 2.4 source of truth 고정

V1에서 사용할 source는 아래로 고정한다.

- decision metadata truth:
  `trading.trade_decisions.decision_json.candidate_vs_final`
- order truth:
  `trading.order_requests`
- execution status truth:
  `trading.execution_attempts`
- fill truth:
  `trading.broker_fill_snapshots`
- account/position-level performance truth:
  기존 `performance_summary` / `performance_history` 계산 경로

---

## 3. Attribution 단계 정의

## 3.1 Stage A — Candidate Coverage

질문:

- 최근 decision 중 몇 %가 `candidate_vs_final`을 보유하는가
- 어떤 source_type에서 candidate 누락이 발생하는가

핵심 지표:

- `candidate_tracked_count`
- `candidate_coverage_rate`
- `source_type x candidate_missing_count`

현재 상태:

- 이미 일부 API로 확인 가능

## 3.2 Stage B — Execution Attribution

질문:

- 어떤 `candidate_intent`가 실제 주문으로 이어졌는가
- 어떤 `alignment_status`가 체결 전환율이 높은가

핵심 지표:

- `decision_to_order_rate`
- `decision_to_fill_rate`
- `alignment_status x order_conversion_rate`
- `candidate_intent x fill_conversion_rate`

현재 상태:

- `GET /performance-trigger-attribution`로 1차 확보됨

## 3.3 Stage C — Mark-to-Market Proxy Attribution

질문:

- 특정 bucket에서 생성된 decision이
  이후 일정 기간 동안 포지션/체결 성과와 어떤 방향 상관을 보이는가

V1 정의:

- 완전한 realized pnl이 아니라
  `post-decision performance proxy`를 먼저 도입한다.

예시:

- decision 후 `T+1`, `T+3`, `T+5` 기준 종가 수익률
- buy candidate의 후행 수익률
- sell / reduce candidate의 이후 하락 회피율

장점:

- 현재 포지션 close model이 완전하지 않아도 집계 가능
- trigger threshold 조정 실험에 바로 활용 가능

주의:

- 이는 `order execution performance`가 아니라
  `decision quality proxy`다

## 3.4 Stage D — Realized PnL Attribution

질문:

- 어떤 override가 실제 실현손익 개선에 기여했는가
- 어떤 candidate_intent bucket이 장기적으로 돈을 버는가

이 단계는 아래 선행조건이 필요하다.

1. entry/exit chain linkage 강화
2. partial fill / split exit 귀속 규칙 확정
3. realized pnl lot matching 정책 고정
4. closing trade가 어떤 opening decision cluster를 닫는지 정의

즉, D 단계는 지금 바로 구현 대상이 아니라
별도 설계/데이터 모델 정리가 선행되어야 한다.

---

## 4. V1에서 바로 구현할 범위

## 4.1 포함 범위

이번 단계 이후 바로 구현 가능한 범위는 아래다.

1. `candidate / override post-decision return proxy`
2. `alignment_status x T+N return proxy`
3. `candidate_intent x T+N return proxy`
4. `source_type x override_applied x T+N return proxy`

이때 기준 가격은
가능하면 `trade_decisions.created_at`에 가장 가까운
동일 일자 snapshot / 종가 기준으로 고정한다.

현행 구현에서는 위 범위를
`holding_profile / reverse_trade / probe_churn`
운영 리포트 관점으로 먼저 구체화했다.

- `GET /performance-holding-profile-attribution`
  - `holding_profile`별
    decision / order / fill 전환
  - 평균 `edge_after_cost_bps`
  - buy fill 이후 첫 sell fill을 close-out proxy로 본
    평균 보유시간 / 평균 수익률
  - `reverse_trade` / `probe_churn` /
    `holding_profile_guard` 차단 분포
  - 계좌 기준 `opposite fill churn` 빈도

즉, 완전한 realized pnl attribution 이전에
현재 데이터 모델에서 deterministic하게 계산 가능한
`closed-trade proxy attribution`
을 먼저 확보한 상태다.

## 4.2 제외 범위

이번 단계에서 제외한다.

1. realized pnl을 decision bucket에 직접 귀속하는 기능
2. lot-level cost basis 재계산
3. fill-level slippage attribution
4. broker fee/tax를 포함한 완전 execution alpha attribution

---

## 5. 제안 API 구조

## 5.1 `GET /performance-trigger-proxy-attribution`

목적:

- trigger / override가 후행 수익률 proxy에서 어떤 분포를 보이는지 조회

권장 파라미터:

- `account_id`
- `lookback_days`
- `horizon_days` (`1 | 3 | 5`)
- `source_type` optional

응답 핵심:

- `tracked_decision_count`
- `proxy_available_count`
- `alignment_items`
- `candidate_intent_items`
- `recent_negative_outlier_items`

bucket별 항목 예시:

- `decision_count`
- `avg_return_pct`
- `median_return_pct`
- `positive_rate`
- `negative_rate`

추가로 현재 운영 리포트용으로는
다음 endpoint가 먼저 구현되었다.

## 5.1a `GET /performance-holding-profile-attribution`

목적:

- `holding_profile`별 기대수익률 anchor와
  실제 close-out proxy 결과를 함께 본다.
- reverse/probe/holding-profile guard가
  churn을 얼마나 차단했는지 같은 창에서 확인한다.

핵심 응답:

- `holding_profile_items`
- `guardrail_items`
- `edge_outcome_items`
- `realized_opposite_fill_churn_count`

주의:

- 여기서의 보유기간/수익률은
  `buy fill -> 이후 첫 sell fill`
  기준의 deterministic proxy다.
- partial fill / multi-entry / scale-out을 완전히 귀속한
  realized pnl attribution은 아직 아니다.

## 5.2 추후 `GET /performance-trigger-realized-attribution`

이 API는 지금 바로 만들지 않는다.

선행 설계 완료 후 별도 추가한다.

---

## 6. 계산 기준

## 6.1 candidate_intent 분류

현재 저장된 `candidate_vs_final.candidate_intent`를 사용한다.

허용 값:

- `buy`
- `sell`
- `watch`
- `no_action`

## 6.2 alignment_status 분류

현재 저장된 값을 그대로 사용한다.

예:

- `matched`
- `downgraded`
- `upgraded`
- `suppressed`
- `promoted_from_no_action`
- `diverged`

## 6.3 후행 수익률 proxy 정의

buy 계열:

- decision 시점 기준 `T+N` 종가 수익률

sell / reduce 계열:

- `회피 성과` 관점으로 해석해야 한다
- 기본 식:
  `-(T+N return_pct)`

즉, 매도 후보 이후 가격이 하락할수록
sell proxy score는 좋아진다.

watch:

- 기본적으로 성과 계산 대상이 아니라
  관찰 bucket으로 분리한다
- V1에서는 수익률 집계는 하되
  점수화보다는 분포 관찰용으로만 사용한다

## 6.4 override 성과 해석

`override_applied=true`인 decision은
아래 두 관점으로 분리 본다.

1. execution 측면:
   - order/fill 전환율이 좋아졌는가
2. proxy return 측면:
   - 후행 수익률/회피 성과가 좋아졌는가

즉, override의 평가는
단일 지표가 아니라
`실행 전환 + 후행 성과`를 같이 봐야 한다.

---

## 7. 데이터 의존성

V1 proxy attribution이 성립하려면 아래가 필요하다.

1. `signal_feature_snapshots` 또는 일봉 시세 접근 경로
2. decision 시점과 가격 시계열을 연결하는 lookup
3. symbol/market 매핑 안정성

권장 source:

- KIS 일봉 기반으로 생성된 snapshot 입력 또는
  별도 저장된 price history cache

비권장:

- decision 시점마다 외부 API를 즉시 재호출하여 과거 수익률을 계산하는 방식

이유:

- replay 비결정성 증가
- 외부 rate limit 의존
- 운영/분석 일관성 저하

---

## 8. 권장 구현 순서

1. `performance-trigger-proxy-attribution` 설계/구현
2. signal feature snapshot 또는 price snapshot 기반 후행 수익률 lookup helper 추가
3. bucket별 `avg/median/positive_rate` 집계 추가
4. Admin/ops에서 최근 outlier decision 샘플 노출
5. 별도 문서:
   `realized_pnl_attribution_for_trigger_and_override`

---

## 9. 완료 기준

이번 설계 단계의 완료 기준:

1. execution attribution과 realized pnl attribution의 경계가 문서화되어 있다
2. 현재 구조에서 가능한 V1 proxy attribution 범위가 정의되어 있다
3. 다음 구현 API의 응답 shape가 합의되어 있다
4. `실현손익 귀속은 별도 단계`라는 점이 명확히 정리되어 있다

---

## 10. 최종 결론

현재 구조에서 바로 할 수 있는 최선은
`trigger/override가 실제 실행으로 얼마나 이어졌는가`
를 먼저 보고,
그 다음
`trigger/override가 이후 성과 proxy에서 어떤 결과를 냈는가`
를 deterministic하게 붙이는 것이다.

즉, 다음 단계는
곧바로 복잡한 realized pnl attribution으로 뛰어드는 것이 아니라,

- execution attribution
- post-decision return proxy attribution

의 2단 구조로 가는 것이 맞다.

이 방식이
현재 데이터 모델과 운영 안정성 제약을 지키면서도,
`기대수익률 최대화`를 위한 threshold 조정과 override 평가를
가장 빠르게 가능하게 하는 경로다.
