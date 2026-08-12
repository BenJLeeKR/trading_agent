# 손실률 기반 Loss-cut 정책/설정 경로 도입 — 실행 계획

> **문서 성격**: 설계·실행 계획 문서다. 이 문서 자체는 어떤 코드도 변경하지 않는다. 구현 지시가 아니라 "무엇을, 왜, 어떤 순서로, 어떻게 검증할지"를 확정하는 계획이다.
> **상세 설계**: [`13_loss_cut_policy_specification_and_config_path_design.md`](../00_foundational_design/detailed_design/13_loss_cut_policy_specification_and_config_path_design.md)
> **선행 조사(설계 조사/현황 분석)**: [`loss_cut_policy_investigation.md`](../20_system_analysis/loss_cut_policy_investigation.md)
> **연관 선례**: `risk.max_single_position_pct`의 `config_versions` + Admin API/CLI 관리 경로(PR #216 계열, [`06_config_schema.md`](../00_foundational_design/detailed_design/06_config_schema.md) §9)

## 1. 문제 배경

현재 운영 코드에는 매수가(평균단가) 대비 손실률 기준의 정량 손절
(Loss-cut) 규칙이 없다. 보유 포지션 청산은 전부 신호 기반(AI
risk_opinion/risk_score, thesis invalidation, edge collapse,
downside shock, holding_profile 만료)이다. 이 사실은
`loss_cut_policy_investigation.md`(`docs/20_system_analysis/`)에서 소스 기준으로 확인했고,
이번 문서가 다루는 것은 그 다음 단계 — **정책 명세를 구현 직전
수준까지 구체화**하는 것이다. 아직 기존 held_position 청산 경로에
실제로 연결하는 구현(B단계)은 하지 않는다.

## 2. 왜 지금 필요한가

- `max_single_position_pct=10→5`를 실제로 config_versions 경로로
  적용한 직후, 같은 계열의 다음 정책값(loss-cut)에 대해서도 같은
  질문(어떤 규칙? 어떤 설정 경로?)이 제기됐다 — 하나의 선례가 있을
  때 다음 정책값을 설계하는 것이 가장 저렴하다(이미 검증된 API/CLI
  패턴을 그대로 재사용 가능).
- "손절이 필요해 보인다"는 정성적 판단만으로 구현에 들어가면, 이
  저장소가 반복적으로 지켜온 원칙(기대값 개선 여부를 사후 성과로
  검증한 뒤에만 정책화, `[PRIORITY_MAP]` 공통 판단 원칙)을 어기게
  된다. 이번 계획은 **구현 전 shadow 검증 단계를 필수 관문으로
  명시**해 그 원칙을 지킨다.

## 3. 단계별 계획

### 0단계 — 정책 조사(완료)

- 산출물: `loss_cut_policy_investigation.md`(`docs/20_system_analysis/`,
  설계 조사/현황 분석 문서) — 현재 코드에 손실률 기반 loss-cut 없음을
  확인, 정책안 3종(A/B/C) 1차 비교, 설정 경로가 `env`가 아니라
  `config_versions`여야 하는 1차 근거.
- 상태: **완료**(2026-08-11, PR #226).

### 1단계 — 정책 명세 + 설정 경로 설계 초안(이번 턴, 완료)

- 왜: 0단계의 비교표만으로는 구현 착수가 불가능하다 — 실제
  threshold 구조, source_type 차등 여부, 기존 로직과의 합성/우선순위
  규칙, 기준 가격, cooldown, config 스키마, API/CLI 계약까지
  구체화해야 B단계 착수가 가능하다.
- 산출물: `13_loss_cut_policy_specification_and_config_path_
  design.md`(`docs/00_foundational_design/detailed_design/`, 정책
  명세/설정 경로 설계 문서) — 2단계(soft/hard) 정책 구조 추천, guard 삽입 위치
  구체 지정(`_check_held_position_sell_override`와
  `_check_held_position_exit_hysteresis_gate` 사이), 기존
  hysteresis escape-hatch 키워드(`"stop_loss"`/`"drawdown"`) 재사용
  설계, `risk.loss_cut` config_json 스키마 초안, Admin API/CLI 계약
  초안(`reason` 필수화 등 기존 계약과의 명시적 차이 포함).
- **이번 단계에서 하지 않은 것**: 코드 구현, 마이그레이션, API 추가,
  런타임 변경 — 전부 문서/설계로만 진행했다.
- 검증 명령: `bash scripts/harness/run.sh accept docs`.
- 상태: **완료**(2026-08-11, 이번 PR).

### 2단계 — Shadow 계산기 구현(완료)

- 왜: 실제 거래 결정을 바꾸지 않고, "loss-cut이 있었다면 어떤
  성과였을까"를 먼저 관측해야 §5(정책 확정)로 넘어갈 근거가 생긴다.
- 산출물:
  - `src/agent_trading/services/loss_cut_shadow.py`(신규) — 순수
    계산 함수 `evaluate_loss_cut_shadow()`. DB 쓰기·주문 제출·
    decision_type 변경 없음, 어떤 guard 목록에도 속하지 않는다.
  - `decision_orchestrator.py`의 신규 private 메서드
    `_record_loss_cut_shadow_observation()` — `assemble()`에서
    `trade_decision_id`가 확정된 **직후**(모든 결정 mutating guard가
    끝난 뒤)에만 호출되며, 반환값도 없고 어떤 결정 필드도 mutate하지
    않는다.
  - 저장: 신규 테이블/마이그레이션 없이 기존
    `trade_decisions.decision_json`에 `loss_cut_shadow` key를
    additive JSONB patch(`jsonb_set`)로 추가 —
    `sync_execution_sizing()`과 완전히 동일한 패턴
    (`repositories/contracts.py`/`memory.py`/`postgres/trade_decisions.py`에
    `sync_loss_cut_shadow_observation()` 추가).
  - 관측 대상: `source_type == "held_position"`으로 제한하지 않고,
    `position_snapshot.quantity > 0`인 모든 결정 사이클에 공통
    적용(기존 guard 메서드들의 `has_position` 판정 관례와 동일) —
    "현재 코드 구조상 가장 작은 안전 범위"를 source_type 분기가
    아니라 이미 모든 사이클에 공통 계산되는 `position_snapshot`
    존재 여부로 잡은 것.
  - 설정 경로: `LOSS_CUT_SHADOW_ENABLED`/
    `LOSS_CUT_SHADOW_SOFT_THRESHOLD_PCT`/
    `LOSS_CUT_SHADOW_HARD_THRESHOLD_PCT`(`.env.example`,
    `config/settings.py`) — 관측 on/off·threshold만 env로 다루고,
    실주문 정책값은 여전히 env에 두지 않는다(§4 원칙 유지). 기본값
    `LOSS_CUT_SHADOW_ENABLED=false` — 계산 자체가 실행되지 않는
    상태가 기본.
  - read path: 신규 API 없음(`GET /trade-decisions`가
    `decision_json`을 이미 노출하므로 무료로 충족) +
    `scripts/dump_loss_cut_shadow_observations.py`(신규, read-only
    조회 편의 스크립트).
  - 실패 처리: 관측 저장 실패는 `logger.warning(exc_info=True)`로
    남기고 예외를 전파하지 않는다(`_sync_trade_decision_execution_
    sizing()`과 동일한 관례) — 실주문 판단 흐름과 완전히 분리.
- 검증: 단위 테스트(`tests/services/test_loss_cut_shadow.py`,
  `tests/services/test_decision_orchestrator.py::
  TestLossCutShadowObservation`) PASS, `accept db-structure`/
  `accept architecture`/`accept backend-runtime`/`accept no-bypass`/
  `accept docs`/`accept env` PASS. Postgres 통합 테스트
  (`tests/repositories/test_postgres_trade_decisions.py::
  test_sync_loss_cut_shadow_observation_is_additive_only`)는
  추가했으나, 검증 환경(`agent_trading-app-1` 컨테이너)의 기존
  asyncpg 이벤트 루프 스코프 버그(수정 전 baseline에서도 동일하게
  재현됨 — 이번 변경과 무관)로 이 컨테이너에서는 실행 확인이
  불가능했다. 코드는 이미 테스트로 검증된 `sync_execution_sizing()`과
  바이트 단위로 동일한 `jsonb_set` 패턴이라 리스크는 낮다고 판단.
- 상태: **완료**(2026-08-11, PR #228 — shadow 관측 구현).

### 2단계 후속 — Shadow 관측 inspection/read API 보강(완료)

- 왜: 2단계가 제공한 read path(`GET /trade-decisions` +
  `scripts/dump_loss_cut_shadow_observations.py`)만으로는 "몇 건
  발동했는지/soft-hard 비율/source_type별 차이/실제 결정과의
  엇갈림"을 운영자가 raw JSON을 뒤지지 않고 빠르게 확인하기
  어려웠다 — 3단계(누적 실측)에 필요한 최소 inspection 도구다.
  **정책 도입이 아니라 이미 기록된 데이터의 조회/집계 read path
  추가**다.
- 산출물:
  - `GET /trade-decisions/loss-cut-shadow/summary` — 계좌×기간 기준
    전체 표본 수/`triggered`·soft·hard 건수/`source_type`별
    분포/실제 `decision_type` 분포/`shadow_only` 카운트/
    `trigger_rate`.
  - `GET /trade-decisions/loss-cut-shadow/samples` — 개별 관측
    원시 행(`triggered`/`tier`/`source_type`/`symbol` 필터,
    `before`+`limit` cursor pagination).
  - `TradeDecisionRepository.list_loss_cut_shadow_observations()`
    (신규 repository read 메서드, Protocol/Postgres/InMemory 3종
    구현) — `decision_json ? 'loss_cut_shadow'`인 TD를
    `decision_contexts` JOIN으로 계좌 필터링해 조회. 계산은 전혀
    하지 않고, 집계(카운트)는 route에서 수행(`realized_pnl`
    summary와 동일한 "repository가 원시 행을 주고 route가 Python
    으로 합산" 관례 재사용).
  - 신규 테이블/마이그레이션 없음 — 기존 `decision_json`을 그대로
    읽는다.
- 검증: `py_compile`, `accept architecture`/`backend-runtime`/
  `db-structure`/`no-bypass`/`docs` PASS, 신규 API/repository 단위
  테스트(`tests/api/test_loss_cut_shadow_inspection.py`,
  `tests/repositories/test_memory_loss_cut_shadow_observations.py`)
  dev-validation container에서 PASS. Postgres 통합 테스트
  (`tests/repositories/test_postgres_trade_decisions.py::
  test_list_loss_cut_shadow_observations_filters_by_account_and_tier`)
  는 추가했으나 이 세션의 두 검증 환경 모두 DB 접근 문제로 실행
  확인은 못 했다(dev-validation container는 `network_mode=none`,
  `agent_trading-app-1`은 기존 asyncpg 루프 스코프 버그) — 2단계와
  동일한 환경 한계.
- 상태: **완료**(2026-08-11, PR #229).

### 2단계 후속 2 — Shadow 관측 일자별 breakdown API 추가(완료)

- 왜: `summary`는 기간 전체를 하나의 숫자로 합산하므로 "어느 날짜에
  trigger가 몰렸는지"/"soft·hard 비율이 날짜별로 어떻게 바뀌는지"를
  볼 수 없었다 — 3단계(누적 실측)의 시계열 추이 확인에 필요한
  최소 read path다. **정책 변경이 아니라 기존 read path의 일자별
  breakdown 확장**이다.
- 산출물:
  - `GET /trade-decisions/loss-cut-shadow/daily` — 계좌×기간 기준
    날짜별(`trade_date`, KST) `total_observation_count`/
    `triggered_count`/`soft_trigger_count`/`hard_trigger_count`/
    `shadow_only_count`/`trigger_rate`. `source_type`/`triggered`
    선택 필터.
  - 신규 repository/SQL 없음 — 기존
    `list_loss_cut_shadow_observations()`가 반환한 원시 행을
    `created_at`의 KST 날짜로 route에서 그룹핑만 한다(`summary`와
    동일한 "원시 행 재사용 + route 후처리" 패턴). `realized-pnl/
    daily-summary`처럼 활동이 없는 날짜는 응답에서 생략한다.
  - `source_type_counts`/`actual_decision_type_counts` 같은 날짜별
    세부 분포는 응답 크기 억제를 위해 이번 턴 범위에서 제외했다
    (필요하면 `summary`를 해당 날짜 하루로 좁혀 호출).
- 검증: `py_compile`, `accept architecture`/`backend-runtime`/
  `db-structure`/`no-bypass`/`docs` PASS, 신규 API 테스트 4건
  (날짜 분리, `triggered` 필터, 빈 결과, UTC→KST 날짜 경계) 전부
  dev-validation container에서 PASS. 신규 repository 코드가 없어
  DB 접근이 필요한 검증 항목 자체가 없다.
- 상태: **완료**(2026-08-11, PR #230).

### 2단계 후속 3 — Shadow × realized PnL 교차 inspection API 추가(완료)

- 왜: `summary`/`samples`/`daily`는 shadow 데이터만 보여줄 뿐, "이
  종목에서 shadow가 발동한 뒤 실제 realized PnL이 어땠는지"를 나란히
  볼 수 없었다 — 3단계 실측 착수 전 최소한의 대조 자료다. **새
  손익/판정 계산 엔진이 아니라, 이미 저장된 shadow 관측값과 이미
  저장된 realized PnL 값을 조회해 나란히 보여주는 read-only 교차
  조회**다. API는 두 값 사이의 인과관계를 단정하지 않는다.
- 판단(코드 기준):
  1. route 위치: `trade-decisions/loss-cut-shadow/*` 계열에 그대로
     둠 — query 계약(`account_id`+기간+`source_type`)이 형제
     endpoint와 동일하고, realized PnL 값은 참고 필드로만 붙는다.
     `performance` 계열이나 별도 route로 분리할 이유가 없었다.
  2. 교차 기준: `account_id + instrument_id`(전체 기간 realized PnL
     누계와의 조인) — `symbol`이 아니라 `instrument_id`를 쓴 이유는
     `realized_pnl_daily_aggregates`/`position_cost_basis_state`가
     전부 `instrument_id`로 keyed돼 있기 때문이다(`symbol`은 표시용
     으로만 사용).
  3. 1:1 매칭 아님 — 종목별 **누계**(all-time realized PnL, shadow
     조회 기간에 종속되지 않음)를 보여줄 뿐, 특정 shadow 관측 1건과
     특정 realized PnL 이벤트 1건을 인과적으로 짝짓지 않는다. 응답
     스키마 docstring에 "인과관계로 해석하지 않는다"를 명시했다.
  4. 이번 턴 최소 안전 범위 = **종목별 교차 요약**(방향 C) — 방향
     A(샘플별 nearest-event 매칭)는 표본 1건마다 "이후 가장 가까운
     realized event"를 찾는 추가 쿼리/근사 로직이 필요해 범위가 더
     크고, 방향 B(일자별 대조)는 이미 있는 `daily`와 개념이 겹친다.
     방향 C는 기존 `realized_pnl.py`의 `list_realized_pnl_positions()`
     가 이미 쓰는 조회 패턴(종목별 `realized_pnl_daily_aggregates`
     합산 + `position_cost_basis_state.recompute_required`)을
     그대로 재사용할 수 있어 **신규 repository 메서드가 0개**다.
  5. "loss-cut을 적용했으면 얼마를 아꼈는지" 계산은 범위 밖으로
     명시적으로 제외 — 그건 반사실적(counterfactual) 시뮬레이션이라
     "정답 계산기 금지" 원칙에 정면으로 위배된다.
  6. 해석 제한: 응답에 "이 손절이 유효했다" 류의 판정 필드를 두지
     않았다 — 카운트/누계 숫자만 나열하고, 해석은 사람의 몫으로
     남긴다.
- 산출물:
  - `GET /trade-decisions/loss-cut-shadow/by-instrument` — 계좌×기간
    기준 종목별 `shadow_triggered_count`/`soft_trigger_count`/
    `hard_trigger_count`/`latest_shadow_at`(shadow 쪽, 기간 내
    `triggered=true`만) + `realized_pnl_net_sum`/
    `realized_sell_event_count`(realized PnL 쪽, 전체 기간 누계) +
    `recompute_required`(`position_cost_basis_state`, 없으면
    `null`). `triggered=true` 이력이 있는 종목만 나타난다.
  - 신규 repository 메서드 0개 — 기존 `list_loss_cut_shadow_
    observations()`, `realized_pnl_daily_aggregates.list_by_
    account_and_instrument()`, `position_cost_basis_states.get()`
    3개를 조합만 했다.
  - 신규 테이블/마이그레이션/계산 엔진 없음.
- 검증: `py_compile`, `accept architecture`/`backend-runtime`/
  `db-structure`/`no-bypass`/`docs` PASS, 신규 API 테스트 3건
  (종목별 집계+join 정상 동작, cost-basis 없는 종목 null 처리, 미발동
  종목 제외) 전부 dev-validation container에서 PASS. 신규
  repository 코드가 없어 DB 접근이 필요한 검증 항목 자체가 없다.
- 상태: **완료**(2026-08-11, PR #231).

### 2단계 후속 4 — Shadow sample × 이후 realized event 타임라인 API 추가(완료)

- 왜: `by-instrument`는 종목 단위 누계만 보여줄 뿐, 개별 shadow
  sample 1건을 기준으로 "그 이후 실제 매도가 있었는지/언제/얼마에
  청산됐는지"를 시간순으로 확인할 수 없었다 — 3단계 실측 착수 전
  개별 사례를 깊게 들여다볼 최소 read path다. **새 손익 계산/새
  trigger 판정이 아니라, 이미 저장된 shadow sample과 이미 저장된
  realized event를 시간순으로 나열만 하는 read-only 타임라인**이다.
- 판단(코드 기준):
  1. route: `trade-decisions/loss-cut-shadow/samples/{trade_decision_
     id}/timeline` — 형제 endpoint(`samples`)의 하위 리소스로 배치.
     `performance` 계열로 옮길 이유 없음(주 리소스가 shadow sample).
  2. 연결 기준: `account_id + instrument_id + fill_timestamp >=
     sample.created_at`(오름차순). `trade_date` 단위가 아니라
     `fill_timestamp`(정밀 timestamp)를 쓴 이유는 하루 안에도 여러
     건의 sample/event가 있을 수 있어 날짜 단위로는 순서를 못
     가르기 때문이다.
  3. **후속 참고 타임라인이지 정확한 인과 매칭이 아니다** — 응답
     스키마 docstring에 명시. "이 event가 이 shadow 때문에
     발생했다"는 주장을 하지 않는다.
  4. 이번 턴 범위: 사용자가 우선 추천한 **방향 A(단일 sample 상세
     타임라인)**를 그대로 채택 — 방향 B(`samples` 목록 전체에
     `next_realized_event_at` 등을 붙이는 방식)보다 범위가 작고
     (기존 `samples` 계약을 넓히지 않음), 한 sample을 사람이 깊게
     읽기에 더 적합하다고 판단.
  5. "loss-cut을 적용했으면 얼마를 아꼈는지" 계산은 여전히 범위
     밖 — 반사실적 시뮬레이션이라 "정답 계산기 금지" 원칙 위배.
  6. 해석 제한: 응답에 판정 필드 없음. `seconds_after_shadow`만
     단순 시간차(뺄셈)로 제공 — 그 이상의 상관/인과 해석 없음.
- 산출물:
  - `GET /trade-decisions/loss-cut-shadow/samples/{trade_decision_id}/
    timeline` — sample 상세 + 그 이후 realized event 최대
    `event_limit`건(기본 5, 최대 50). `account_id` 쿼리로 소유
    검증(불일치 시 404 — 다른 계좌 존재 여부 비노출). sample이
    없거나 shadow 관측이 없으면 404.
  - **신규 repository 메서드 1개**(최소): `RealizedPnlEventRepository.
    list_by_account_and_instrument_since()` — 기존
    `list_by_account_and_instrument()`(최신순, `before` 커서)와
    정렬 방향이 반대(오름차순, `since` 이후)라 별도 메서드가
    필요했다. Protocol/Postgres/InMemory 3종 구현.
  - 신규 테이블/마이그레이션/계산 엔진 없음.
- 검증: `py_compile`, `accept architecture`/`backend-runtime`/
  `db-structure`/`no-bypass`/`docs` PASS, 신규 API 테스트 6건
  (이후 이벤트만 시간순 조회, event_limit 적용, 이벤트 없음, 존재하지
  않는 trade_decision 404, shadow 없는 TD 404, 계좌 불일치 404)
  전부 dev-validation container에서 PASS. 신규 postgres
  repository 메서드는 이 세션의 두 검증 환경(DB 없는
  dev-validation container, 기존 asyncpg 루프 버그의
  `agent_trading-app-1`) 모두에서 실행 확인이 안 되는 기존
  한계가 그대로 적용된다(PR #229/#231에서 이미 문서화됨).
- 상태: **완료**(2026-08-11, PR #232).

### 2단계 후속 5 — Shadow → 첫 realized event 지연 분포 API 추가(완료)

- 왜: `timeline`은 sample 1건씩만 볼 수 있어 "보통 몇 초/몇 분 뒤
  첫 realized event가 나타나는지", "hard가 soft보다 빨리
  청산되는지", "첫 event가 아예 없는 sample 비율" 같은 **집계
  질문**에 답하지 못했다 — 3단계 실측 착수 여부를 판단할 다음
  최소 신호다. **새 손익 계산/새 trigger 판정이 아니라, 이미
  저장된 shadow sample과 이미 저장된 realized event의 시간차를
  모아 분포 통계만 내는 read-only 집계**다.
- 판단(코드 기준):
  1. route: `trade-decisions/loss-cut-shadow/*` 계열에 그대로 둠 —
     query 계약이 형제 endpoint와 동일하고, `timeline`의 "가장
     먼저 발생한 event 조회"를 표본 전체에 반복 적용한 것뿐이라
     `performance` 계열로 옮길 이유가 없다.
  2. 모집단: `triggered=true` sample 고정(쿼리로 끄고 켤 수 없게
     내부에서 고정) — `triggered=false` sample에는 "이후 첫
     event"를 물을 이유가 없기 때문이다. `source_type`/`tier`는
     선택 필터로 열어뒀다.
  3. 연결 기준: `account_id + instrument_id + fill_timestamp >=
     sample.created_at`인 가장 오래된 event 1건(`timeline`이 이미
     쓰는 `list_by_account_and_instrument_since(limit=1)`과 완전히
     동일한 조회를 표본마다 반복). 신규 repository 메서드
     **0개** — PR #232가 이미 추가한 메서드를 그대로 재사용했다.
  4. 인과 매칭 아님 — `timeline`과 동일한 한계(같은 계좌×종목에서
     "가장 먼저" 발생한 event일 뿐, 그 event가 이 sample 때문에
     발생했다는 보장 없음)를 응답 스키마 docstring에 명시했다.
  5. 이번 턴 범위: 사용자가 우선 추천한 **분포 요약 endpoint
     1개**만 구현 — 개별 sample 사례 첨부는 하지 않았다(그건
     이미 `timeline`/`samples`가 제공).
  6. 이벤트 없음 카운트: `missing_first_event_count`와
     `missing_first_event_rate` **둘 다** 응답에 포함했다(요청된
     범위 그대로).
- 산출물:
  - `GET /trade-decisions/loss-cut-shadow/first-realized-event-latency`
    — 계좌×기간(+선택 `source_type`/`tier`) 기준
    `sample_count`/`matched_first_event_count`/
    `missing_first_event_count`/`missing_first_event_rate`/
    `latency_seconds_{min,max,avg,median,p90}` +
    참고 필드 `first_realized_event_pnl_net_{avg,median}`(첫
    event의 `realized_pnl_net` 평균/중앙값 — 추가 쿼리 없이 이미
    가져온 event에서 뽑을 수 있어 포함했다. "이 손실이 shadow
    때문"이라는 해석을 뒷받침하지 않는다는 caveat을 스키마에
    명시).
  - 신규 repository 메서드 0개.
  - 신규 테이블/마이그레이션/계산 엔진 없음.
- 검증: `py_compile`, `accept architecture`/`backend-runtime`/
  `db-structure`/`no-bypass`/`docs` PASS, 신규 API 테스트 4건
  (분포 통계 계산 정확성 — min/max/avg/median/첫 event PnL
  평균·중앙값, `tier` 필터, 빈 표본, 전부 event 없는 경우) 전부
  dev-validation container에서 PASS. 신규 repository 코드가 없어
  DB 접근이 필요한 검증 항목 자체가 없다.
- 상태: **완료**(2026-08-12, PR #233).

### 2단계 후속 6 — Shadow missing first event 원인 bucket 분류 API 추가(완료)

- 왜: `first-realized-event-latency`는 "missing" 건수/비율만 낼 뿐
  **왜 missing인지**(아직 보유 중인지, ledger가 recompute 대기
  상태인지, 데이터 정합성이 의심되는지)를 구분하지 못했다 — 3단계
  실측 착수 전 운영자가 missing 표본을 바로 분류해서 볼 수 있는
  최소 read path다. **새로운 매매 판단이나 causality 해석이
  아니라, 이미 저장된 값(shadow payload/`position_cost_basis_
  state`/realized event 존재 여부)만으로 코드상 재현 가능한 규칙
  으로 분류하는 원인 분류 inspection**이다.
- bucket 정의와 판정 기준(코드: `_classify_missing_first_event_
  cause()`, `src/agent_trading/api/routes/decisions.py`):

  | bucket | 판정 기준 |
  |---|---|
  | `missing_instrument_linkage` | shadow payload에 `instrument_id`가 없음(구형 관측 등) |
  | `recompute_required` | `position_cost_basis_state.recompute_required is True` |
  | `missing_position_state` | 계좌×종목 `position_cost_basis_state`가 아예 없음 |
  | `still_holding_position` | `position_cost_basis_state.quantity > 0`(ledger 기준 아직 보유 중) |
  | `position_closed_but_no_realized_event` | `quantity <= 0`(ledger 기준 이미 청산)인데 realized event가 안 보임 — ledger/recompute 누락 의심 |
  | `other_unclassified` | 위 어느 것도 명확히 해당하지 않음(현재 코드 경로상 도달 가능성은 낮음) |

  **precedence(위에서부터 먼저 만족하는 것으로 확정)**:
  `missing_instrument_linkage` → `recompute_required` →
  `missing_position_state` → `still_holding_position` →
  `position_closed_but_no_realized_event` → `other_unclassified`.
  `recompute_required`가 `still_holding_position`보다 먼저인
  이유: `recompute_required=true`면 ledger의 `quantity` 자체가
  신뢰 불가 상태이므로, 그 값을 근거로 "보유 중이다"라고 먼저
  단정하면 잘못된 결론이 될 수 있다 — 정합성 경고를 항상 먼저
  드러낸다.
- 산출물:
  - `GET /trade-decisions/loss-cut-shadow/missing-first-event-causes`
    — 계좌×기간(+선택 `source_type`/`tier`) 기준 `sample_count`/
    `missing_first_event_count`/`missing_first_event_rate`/
    `cause_breakdown[]`(bucket별 count+비율, 분모는 missing 표본
    전체) + `by_source_type[]`/`by_tier[]`/`by_decision_type[]`
    (그룹별 `sample_count`/`missing_first_event_count`/그룹 **안**
    에서의 missing 비율 — 특정 그룹에서 missing이 쏠리는지 비교
    하는 용도).
  - 신규 repository 메서드 0개 — 기존 `list_loss_cut_shadow_
    observations()`/`realized_pnl_events.list_by_account_and_
    instrument_since()`/`position_cost_basis_states.get()` 3개
    조합만 했다.
  - 신규 테이블/마이그레이션/계산 엔진 없음.
- 한계(응답 스키마에도 명시): **원인 분류 inspection이지 인과
  확정 도구가 아니다.** "이 shadow가 유효했다"/"이 종목은 손절이
  정답이었다" 같은 결론을 내리지 않는다.
- 검증: `py_compile`, `accept architecture`/`backend-runtime`/
  `db-structure`/`no-bypass`/`docs` PASS, 신규 API 테스트 4건
  (6개 bucket 전체 분류 + source_type/tier/decision_type breakdown,
  recompute_required가 still_holding보다 우선하는 precedence 확인,
  빈 표본, `tier` 필터) 전부 dev-validation container에서 PASS.
  신규 repository 코드가 없어 DB 접근이 필요한 검증 항목 자체가
  없다.
- 상태: **완료**(2026-08-12, PR #234).

### 2단계 후속 7 — Shadow missing first event 원인별 sample drilldown API 추가(완료)

- 왜: `missing-first-event-causes`는 bucket별 **집계**만 보여줄 뿐,
  "그 bucket에 속한 실제 sample이 무엇인지"를 바로 조회할 수
  없었다 — 운영자가 집계에서 이상 신호(예: `recompute_required`가
  많음)를 확인한 뒤 실제 케이스로 즉시 drilldown할 최소 read
  path다. **새로운 매매 판단이나 causality 해석이 아니라, 이미
  분류된 원인 bucket을 원시 sample 행 단위로 나열하는 개별 사례
  inspection**이다.
- **cause 판정 규칙 재사용(가장 중요)**: `missing-first-event-
  causes`가 쓰던 `_classify_missing_first_event_cause()`를 그대로
  공유한다 — 중복 구현 없음. 이 함수의 반환형을
  `_MissingCauseClassification`(`cause` + `cost_basis_state`)
  dataclass로 바꿔, drilldown endpoint가 같은 조회를 다시 하지
  않고도 `recompute_required`/`position_quantity`를 얻을 수 있게
  했다(causes endpoint의 카운팅 로직은 `.cause`만 쓰도록 호출부만
  갱신 — 판정 로직 자체는 한 글자도 바뀌지 않았다). 두 endpoint
  가 같은 표본에 대해 항상 같은 cause를 내는지 교차 테스트로
  직접 확인했다(`test_missing_first_event_samples_filters_by_
  cause_matches_causes_endpoint`).
- 산출물:
  - `GET /trade-decisions/loss-cut-shadow/missing-first-event-samples`
    — 계좌×기간(+선택 `source_type`/`tier`/`cause`/`before`/
    `limit`) 기준 missing sample 원시 행 목록. 각 행:
    `trade_decision_id`/`created_at`/`symbol`/`instrument_id`/
    `source_type`/`actual_decision_type`/`tier`/`triggered`/
    `loss_pct`/`shadow_only`/`cause`/`recompute_required`/
    `position_quantity`/`has_first_realized_event`(항상 `false` —
    이 endpoint 자체가 missing 표본만 다루므로 명시적으로 고정).
  - 정렬/페이지네이션: 기존 `samples` endpoint와 동일하게
    `created_at` 내림차순(최신순) + `before`/`limit` cursor.
    `before`는 `list_loss_cut_shadow_observations()` 자체의 커서
    파라미터를 그대로 전달하고, `limit`은 missing/cause 조건을
    만족하는 행 개수 기준으로 적용한다(원시 조회 행 개수 기준이
    아님 — missing이 아닌 행은 세지 않음).
  - 신규 repository 메서드 0개 — 기존 3개(`list_loss_cut_shadow_
    observations()`/`realized_pnl_events.list_by_account_and_
    instrument_since()`/`position_cost_basis_states.get()`)만
    조합했다.
  - 신규 테이블/마이그레이션/계산 엔진 없음.
- 한계(응답 스키마에도 명시): **개별 사례 drilldown이지 인과
  확정 도구가 아니다** — `missing-first-event-causes`와 동일한
  한계를 그대로 물려받는다.
- 검증: `py_compile`, `accept architecture`/`backend-runtime`/
  `db-structure`/`no-bypass`/`docs` PASS, 신규 API 테스트 4건
  (missing 행 + cause/position 정보 정상 조회, causes endpoint와
  cause count 교차 일치 확인, `limit`/`before` cursor 동작,
  잘못된 `cause` 값 400) 전부 dev-validation container에서
  PASS(`test-file`로 직접 실행 — `accept backend-file`의
  import-graph 매칭은 이 신규 테스트 파일을 자동으로 잡지 못해
  별도로 확인함). 신규 repository 코드가 없어 DB 접근이 필요한
  검증 항목 자체가 없다.
- 상태: **완료**(2026-08-12, 이번 PR).

### 3단계 — Shadow 누적 실측(미착수)

- 왜: 표본이 쌓여야 "발동 표본 vs 미발동 표본" 사후 성과 비교가
  가능하다.
- 산출물(예정): 누적 이력(JSONL 또는 유사 구조, 기존
  `regime_conditional_signal_shadow_history.jsonl`류 관례 재사용),
  주기적 실측 보고. read path는 이번에 추가한
  summary/samples/daily/by-instrument/timeline/first-realized-
  event-latency/missing-first-event-causes/missing-first-event-
  samples API를 그대로 재사용할 수 있다 — 별도 조회 도구를 새로
  만들 필요는 없다.
- 상태: **미착수**.

### 4단계 — 정책 확정(미착수)

- 왜: 설계 문서 §3.1의 soft/hard 임계치, §3.5의 cooldown 시간 등
  구체 숫자는 실측 없이 정할 수 없다(이 저장소의 "빈도가 아니라
  기대값 개선으로 판단" 원칙).
- 산출물(예정): 확정된 임계치/cooldown 값, 사용자 최종 승인.
- 상태: **미착수**.

### 5단계 — Admin API/CLI 구현(미착수)

- 왜: 정책이 확정된 뒤에야 그 정책을 발행할 관리 경로가 의미를
  갖는다 — 값이 정해지지 않은 상태에서 API부터 만들면 스키마
  재작업 위험이 있다.
- 산출물(예정): `services/config_version_admin.py`에
  `publish_loss_cut_policy()` 추가(설계 문서 §4.4 계약),
  `POST /config-versions/risk/loss-cut-policy`,
  `scripts/publish_loss_cut_policy.py`, 대응 테스트(기존
  `max_single_position_pct` PR들과 동일한 검증 절차: `py-compile`,
  `accept style`, `accept no-bypass`, `accept architecture`,
  컨테이너 대체 pytest).
- 상태: **미착수**.

### 6단계 — `decision_orchestrator.py` 연결(미착수)

- 왜: 이 단계에서 비로소 실제 거래 결정에 영향을 준다 — 가장 신중해야
  하는 단계.
- 산출물(예정): 설계 문서 §3.3의 `_check_loss_cut_override` guard
  삽입, `_check_held_position_sell_override` 시그니처에
  `position_snapshot` 전달 추가, `SymbolTradeStateEntity.metadata_
  json`에 cooldown 필드 추가(마이그레이션 불필요 — 기존 자유 형식
  필드 재사용).
- 안전 원칙: `src/AGENTS.md`의 "매매 의미론, 리스크 정책, 주문
  크기 산정, 주문 제출, 정합성 상태 전이는 명시적 근거와 검증 없이
  바꾸지 않는다" 원칙에 따라, 회귀 테스트 없이 이 단계를 진행하지
  않는다.
- 상태: **미착수**.

### 7단계 — 운영 전환(미착수)

- 왜: 실제로 `risk.loss_cut.enabled=true`를 발행하는 단계 —
  장중 배포 금지 원칙을 그대로 적용한다(이 저장소의 반복 관례,
  submit budget 2단계 분리 작업 등에서 이미 확립됨).
- 상태: **미착수**.

## 4. 검증 기준

### 1단계(문서, 완료)

- `bash scripts/harness/run.sh accept docs` — PASS 필요.
- 코드/스키마 변경이 없으므로 `accept architecture`/`accept style`/
  `accept no-bypass`는 이번 단계에서 필수로 요구하지 않는다(실행
  시 이유를 완료 보고에 남긴다).

### 2단계(shadow 구현, 완료)

- `py_compile`(변경/신규 파일 전체), `accept db-structure`,
  `accept architecture`, `accept backend-runtime`, `accept no-bypass`,
  `accept docs`, `accept env` — 전부 PASS.
- `tests/services/test_loss_cut_shadow.py`(순수 함수 9 tests),
  `tests/services/test_decision_orchestrator.py::
  TestLossCutShadowObservation`(5 tests, 관측이 decision_type/side를
  바꾸지 않음을 직접 assert) — dev-validation container
  (`bash scripts/harness/run.sh test-file <path>`)에서 전부 PASS.
- Postgres 통합 테스트 1건은 작성했으나 `agent_trading-app-1`
  컨테이너의 기존 asyncpg 이벤트 루프 스코프 버그(수정 전 baseline
  재현 확인 완료 — 이번 변경과 무관한 환경 문제)로 이 환경에서는
  실행 결과를 확인하지 못했다. 완료 보고에 별도 명시.

## 5. 남은 리스크 / 후속 확인 필요 사항

`13_loss_cut_policy_specification_and_config_path_design.md` §6과
동일 — 이 문서에서 중복 나열하지 않는다. 핵심만 재인용:

- soft/hard 임계치 구체 숫자 미확정(shadow 실측 필요 — 이번 2단계
  구현으로 실측 자체는 이제 가능해졌으나, 실제 표본 축적/분석은
  아직 하지 않았다).
- loss-cut과 기존 hysteresis gate의 우선순위 설계(부분적 우선,
  완전 우회 아님)에 대한 사용자 명시 확인 필요.
- held_position에 대한 더 타이트한 override 여부는 데이터 없이
  판단 불가.
- `agent_trading-app-1` 컨테이너의 asyncpg 이벤트 루프 스코프 버그
  자체는 이번 작업 범위 밖이지만, DB 관련 통합 테스트 검증을
  막고 있어 별도 조사가 필요하다.

## 6. `[PRIORITY_MAP]` / `[BACKLOG]` 반영

- `[PRIORITY_MAP] remaining_work_priority_map.md`: 이번 2단계(shadow
  관측 구현) 완료를 append. 다음 주력 작업이 `SPPV-3`임은
  2026-08-11 이전 항목에서 이미 명시했고, 이번 항목은 그 우선순위를
  바꾸지 않는다 — 3단계(shadow 누적 실측)는 여전히 "표본 축적 대기"
  상태다.
- `[BACKLOG] backlog.md`: 이번 설계 초안으로 답한 질문(정책 구조,
  합성 규칙, 설정 경로)과 여전히 열려 있는 질문(임계치 숫자,
  우선순위 최종 확인, held_position 차등 여부)을 구분해 갱신한다.
  신규: `agent_trading-app-1` asyncpg 이벤트 루프 스코프 버그 조사
  항목을 추가한다.
