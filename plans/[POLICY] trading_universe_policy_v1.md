# Trading Universe Policy v1.1

작성일: 2026-05-14

## 1. 목적

이 문서는 `instrument master`와 `trading universe`를 분리하여 정의하고, 실제 운영에서 어떤 비즈니스 기준과 절차로 오늘의 판단 대상 종목을 선정할지 고정한다.

핵심 원칙은 다음과 같다.

1. `instruments`는 전체 종목 기준 데이터다.
2. `universe`는 오늘 판단 대상으로 올릴 실행 집합이다.
3. Universe 선정은 에이전트의 임의 판단이 아니라, 운영 정책과 결정적 규칙으로 우선 수행한다.
4. 에이전트는 선정된 universe 안에서 해석, 우선순위화, 매매 판단을 수행한다.

## 2. 용어 정의

### 2.1 Instrument Master

`trading.instruments`는 전체 거래 가능 종목의 기준 정보 저장소다.

포함 예시:

- `symbol`
- `market_code`
- `asset_class`
- `currency`
- `name`
- `is_active`
- 추가 metadata

역할:

- 종목 식별의 단일 기준
- snapshot sync, external event mapping, UI 표시에 공통 사용
- universe 선정을 위한 모수 풀 제공

추가 원칙:

- `instrument master`에 없는 종목은 Universe Selection 단계에서 `미등록 종목`으로 제외한다.
- 따라서 KOSDAQ 종목을 판단/주문 대상에 넣으려면, 먼저 KIS 종목정보파일 기반 sync로
  해당 종목의 master row를 `trading.instruments`에 적재해야 한다.
- `decision loop`나 AI 계층에서 이 예외를 우회하지 않는다.

국내주식 canonical model 원칙:

- `market_code` 단일 값에
  `거래소(exchange)`와 `시장세그먼트(segment)` 의미를 동시에 싣지 않는다.
- 국내주식은 장기적으로 아래 역할 분리를 목표로 한다.
  - `exchange_code = 'KRX'`
  - `market_segment = 'KOSPI' | 'KOSDAQ'`
  - `index_memberships = ['KOSPI100', 'KOSPI200', 'KOSDAQ50', 'KOSDAQ150', ...]`
- `KRX`는 즉시 제거 대상이 아니다.
  기존 `position/order/snapshot/replay` FK와 운영 데이터 정합성을 위해
  이행 기간 동안 backward-compatible하게 유지한다.
- Universe Selection과 execution 계층은
  최종적으로 `market_code` legacy 해석보다
  `exchange_code + market_segment + index_memberships`
  기준을 우선 사용해야 한다.

권장 저장 방식:

- `exchange_code`, `market_segment`
  - `trading.instruments` 정식 컬럼 권장
- `index_memberships`
  - 1차: `metadata.index_memberships` 배열 허용
  - 2차: 시계열 관리가 필요해지면
    `instrument_index_memberships` 별도 테이블로 승격
  - 현재 KIS 원본 CSV에 `is_kospi200`, `is_kosdaq150`가 있으면
    이를 각각 `KOSPI200`, `KOSDAQ150` membership으로 정규화해 적재한다.
  - 현재 원본 CSV에 `KOSPI100`, `KOSDAQ50` 직접 플래그가 없으면
    별도 승인 리스트나 외부 원천 없이 임의 추론해 적재하지 않는다.
  - 중첩 membership은 제거하지 않고 원본 의미를 그대로 보존한다.
    예: `KOSPI100` 종목은 `KOSPI200` membership도 함께 가질 수 있다.
  - 다만 판단 계층에서는 평면 리스트를 그대로 해석하지 않고,
    `primary_index_membership` 파생 규칙을 추가한다.
    현재 우선순위는
    `KOSPI100 > KOSDAQ50 > KOSPI200 > KOSDAQ150 > 기타`
    로 본다.

### 2.2 Trading Universe

`trading universe`는 특정 시점에 decision loop가 실제로 순회하는 종목 집합이다.

역할:

- 오늘 판단할 종목 후보군 제한
- 운영 예산(KIS 호출량, LLM 비용, 판단 시간) 통제
- 설명 가능성과 재현성 보장

## 3. 운영 원칙

### 3.1 Universe 선정 책임

Universe 선정은 기본적으로 시스템 정책 책임이다.

권장 역할 분리:

- 시스템/정책 계층:
  - 후보군 생성
  - 제외 조건 적용
  - 오늘의 universe 확정
- 에이전트 계층:
  - universe 내 종목의 중요도/우선순위 보조
  - EI/Risk/FDC 판단 수행

금지:

- 에이전트가 전체 시장을 임의로 훑어 오늘의 universe를 독자적으로 생성
- 운영 정책 없이 LLM이 종목 선정부터 매매 판단까지 전부 수행

### 3.1-a Trading Universe Freeze

`trading universe`는 운영 배치나 판단 loop가 필요할 때마다
매번 즉석 recomposition 하는 개념으로만 두지 않는다.

운영 기준의 authoritative snapshot은
별도 PostgreSQL 테이블에 `freeze` 형태로 남겨야 한다.

핵심 원칙:

- 동일 실행 목적 안에서는 같은 freeze 결과를 재사용한다.
- 재시도, replay, reconciliation은 freeze 당시의 대상 집합을 바꾸지 않는다.
- feature batch, decision loop, 운영 진단은
  가능하면 같은 freeze run id를 참조해야 한다.
  - 현재 구현은 장후 `signal_feature` batch가 먼저 사용 중이다.
  - 다음 확장 단계에서는 장중 `decision loop`도
    `decision_loop_intraday` freeze를 우선 조회하도록 맞춰야 한다.
    그렇지 않으면 장중 판단 대상과
    장후 feature/audit 대상의 universe 기준이 분리된다.
- `왜 이 종목이 그날 대상이었는가`를
  DB row 단위로 사후 설명 가능해야 한다.

권장 저장 단위:

- `trading.universe_freeze_runs`
  - 한 번의 freeze 실행 메타데이터
- `trading.universe_freeze_run_items`
  - 해당 freeze에 포함된 종목 목록

`universe_freeze_runs` 필수 컬럼 권장안:

- `id`
- `business_date`
- `freeze_purpose`
  - 예: `signal_feature_after_market`, `decision_loop_intraday`
- `freeze_sequence`
  - 같은 영업일/목적 내 재생성 순번
- `frozen_at`
- `selection_version`
- `selection_params_json`
- `target_count`
- `status`
  - 예: `created`, `materialized`, `consumed`, `failed`
- `created_at`
- `updated_at`

`universe_freeze_run_items` 필수 컬럼 권장안:

- `id`
- `freeze_run_id`
- `instrument_id`
- `symbol`
- `market_code`
- `source_type`
- `inclusion_reason`
- `priority_score`
- `rank`
- `cap_bucket`
  - 예: `core`, `market_overlay`, `held_position`, `reconciliation_overlay`
- `metadata_json`
- `created_at`

unique / index 원칙:

- `universe_freeze_runs`
  - `(business_date, freeze_purpose, freeze_sequence)` unique
- `universe_freeze_run_items`
  - `(freeze_run_id, instrument_id)` unique
- 조회 인덱스
  - `(freeze_purpose, business_date desc)`
  - `(freeze_run_id, rank asc)`
  - `(symbol, business_date desc)` 또는 동등 조회 경로

연결 원칙:

- 장후 feature batch는
`signal_feature_batch_runs.universe_freeze_run_id` FK로 freeze를 참조한다.
현재 구현에서는 `signal_feature_batch_runs` / `signal_feature_batch_run_items`
테이블이 위 연결을 사용해 장후 배치 실행 메타데이터와 종목별 처리 결과를 저장한다.
- 이후 decision loop에도 동일 개념을 확장할 수 있지만,
  우선 장후 feature batch를 1차 authoritative consumer로 둔다.
  다음 우선 확장 범위는 아래와 같다.
  1. scheduler가 장중 첫 cycle 직전
     `decision_loop_intraday` freeze를 1회 materialize
  2. `run_decision_loop`는
     env override 다음으로 latest intraday freeze를 조회
  3. intraday freeze가 없을 때만 compose fallback
  4. decision cycle summary / audit metadata에
     `universe_freeze_run_id`, `freeze_purpose`, `freeze_reused`
     를 남긴다.

운영 원칙:

- 동일 freeze run에 대해 fetch 실패가 발생해도
  대상 universe 자체는 변경하지 않는다.
- 실패 종목 재시도는 `freeze_run_id` 기준 subset 재실행으로 처리한다.
- 수동 재실행도 기본은 기존 freeze 재사용이며,
  대상 집합 변경이 필요할 때만 `freeze_sequence + 1` 새 run을 만든다.
- `signal_feature_snapshots`는
  `(instrument_id, timeframe, snapshot_at, feature_set_version)` natural key 기준으로
  idempotent upsert를 수행한다.
  동일 장후 배치를 다시 실행해도 snapshot row는 중복 생성되지 않고
  기존 row payload만 최신 계산값으로 갱신한다.

### 3.1-b Signal Feature Batch Authoritative Source

장후 `signal feature` 배치는
`freeze -> fetch -> persist -> tail-retry`의 각 단계마다
파일과 DB를 모두 남길 수 있지만,
운영상 authoritative source는 아래처럼 고정한다.

1. 대상 universe authoritative source
   - `trading.universe_freeze_runs`
   - `trading.universe_freeze_run_items`
2. 배치 실행 메타데이터 authoritative source
   - `trading.signal_feature_batch_runs`
   - `trading.signal_feature_batch_run_items`
3. 최종 feature row authoritative source
   - `trading.signal_feature_snapshots`
4. JSON 중간 산출물
   - authoritative source가 아니라
     배치 간 전달, tail-retry, 수동 재실행, 장애 분석용 artifact다.

운영 해석 원칙:

- 오늘 어떤 종목을 대상으로 삼았는지는
  입력 JSON이 아니라 `universe_freeze_run_items`를 기준으로 판단한다.
- 장후 배치가 몇 건을 성공/실패했고
  어떤 종목이 누락됐는지는
  `signal_feature_batch_runs`와
  `signal_feature_batch_run_items`를 기준으로 판단한다.
- 최종적으로 판단 계층이 참조해야 할 feature snapshot은
  파일이 아니라 `signal_feature_snapshots` row다.
- 입력 JSON이 유실돼도
  DB의 freeze/run-state/snapshot이 남아 있으면
  audit, 설명, 사후 검증은 계속 가능해야 한다.

재실행 원칙:

- 기본 재실행은 기존 `freeze_run_id`를 재사용한다.
- 파일 기반 `--retry-from-input` 경로는 허용하되,
  이 경로도 authoritative run-state를 대체하지 않는다.
- 장기적으로는 file artifact 없이도
  `freeze_run_id + batch_run_id`만으로
  subset 재실행이 가능하도록 orchestration 계층을 수렴시킨다.

### 3.2 설명 가능성

각 종목이 universe에 포함된 이유는 운영자가 사후 설명 가능해야 한다.

예시 reason:

- `core_universe`
- `held_position`
- `high_importance_event`
- `market_overlay`
- `manual_watchlist`
- `recent_order_context`

## 4. Universe 선정 계층

Universe는 아래 5단계로 구성한다.

### 4.1 Layer 1 — Base Market Pool

가장 바깥 풀이다. 시스템이 원천적으로 다룰 시장 범위를 결정한다.

v1 권장 기준:

- `exchange_code = 'KRX'` 또는 legacy `market_code='KRX'`
- `market_segment IN ('KOSPI', 'KOSDAQ')`
- `asset_class = 'kr_stock'`
- `is_active = true`

운영 초기 권장 모수:

- `KOSPI100` 또는 이에 준하는 대형주 풀
- KOSDAQ은 초기에는 `core`보다
  `discovery / overlay / event` 계층에서 단계 편입

core seed authoritative source 우선순위:

1. `index_memberships` 기반
   - 예: `KOSPI100`, `KOSPI200`, `KOSDAQ150`
2. 명시적 metadata flag
   - 예: `core_universe=true`
3. 임시 코드 allowlist
   - 후속 제거 대상

시장 확장 원칙:

- KOSDAQ/중소형 탐색 확대는 허용하되, universe 편입 전제는 항상
  `instrument master sync 완료`다.
- 즉, `master sync → operational eligibility → strategy relevance / overlay`
  순서를 유지한다.

비즈니스 이유:

- 유동성이 충분하다
- 공시/이벤트 반응성이 상대적으로 높다
- near-real 운영에서 슬리피지, 호가 공백, 비정상 종목 노이즈를 줄일 수 있다

### 4.2 Layer 2 — Operational Eligibility Filter

거래 가능한 종목 중에서도 실제 자동매매 운영에 적합한 종목만 남긴다.

예시 기준:

- 거래정지 종목 제외
- 관리/감리/투자경고 등 운영 제외 리스트 반영
- 종목 정보 미완성 종목 제외
- 브로커 주문 지원 범위 밖 종목 제외
- 내부적으로 비활성 처리된 종목 제외
- instrument master 미등록 종목 제외

비즈니스 이유:

- 자동매매 오류 가능성을 낮춤
- 브로커/시장 예외케이스에 의한 운영 사고를 방지

### 4.3 Layer 3 — Strategy Relevance Filter

운영 가능 종목 중에서도 전략적으로 볼 가치가 있는 종목을 추린다.

예시 기준:

- 최근 중요 OpenDART 이벤트가 존재
- 최근 1~3영업일 내 공시 발생
- 최근 판단/주문 이력이 있어 추적 가치가 높음
- 현재 보유 종목

비즈니스 이유:

- 이벤트 없는 종목을 무의미하게 반복 판단하지 않음
- 판단 자원을 실제 신호가 있을 가능성이 높은 종목에 집중

### 4.4 Layer 4 — Market-Driven (Flow/Volatility) Overlay

뉴스나 공시가 없어도, 장중 수급과 변동성 자체가 alpha 신호가 될 수 있다. 따라서 event-driven 후보군과 별도로 `market-driven overlay`를 운영한다.

정의:

- 한국투자증권(KIS) 순위 분석 API 또는 동급의 실시간 랭킹 데이터에서 추출한 수급/모멘텀 상위 종목

대표 편입 후보 신호:

- 거래량 급증 상위
- 체결강도 상위
- 신고가 근접 또는 신고가 갱신 후보
- 가격/거래대금 동반 급증 종목
- 상대 거래량 급증 종목
- 상대 거래대금 급증 종목

역할:

- OpenDART/뉴스가 없는 종목 중에서도 장중 강한 흐름이 발생한 종목을 universe에 편입
- KOSDAQ/중소형주 포함 하이알파 후보를 탐지
- event-driven 전략이 놓치는 intraday momentum 종목을 보강

핵심 원칙:

- `market-driven overlay`는 core universe를 대체하지 않는다
- 별도의 동적 오버레이로 작동한다
- 편입 직전 반드시 유동성/체결 안정성 필터를 통과해야 한다
- 절대 거래대금 순위만으로 후보를 고정하지 않고,
  `상대 거래량/거래대금 급증률`을 함께 사용해
  새로 강해지는 종목을 조기 포착한다
- 탐색 풀과 주문 가능 풀은 동일하지 않을 수 있으며,
  탐색 풀은 더 넓게 보되 주문 가능 풀은 execution 안전성 기준을 유지한다

#### 4.4.1 Liquidity Filter

`market-driven overlay`는 변동성이 큰 종목을 다루므로, universe 편입 전에 1차 유동성 필터를 강하게 적용한다.

필수 필터 예시:

- 틱 사이즈 대비 호가창이 지나치게 얇은 종목 제외
- 직전 N분 누적 거래대금이 너무 낮은 종목 제외
- 내부 기준 시가총액 하한 미만 종목 제외
- micro-cap 또는 초저유동성 종목 제외
- 단일호가/급격한 갭/이상체결로 해석되는 종목 제외

추가 원칙:

- 상대 거래량/거래대금 급증률이 낮은 종목은
  단순 절대 거래대금이 높더라도 신규 진입 후보에서 후순위 처리하거나 제외할 수 있다
- 유동성 필터는 “많이 거래되는 대형주만 남기기”가 목적이 아니라,
  `기대수익률 대비 execution risk`가 과도한 종목을 제거하는 것이 목적이다

비즈니스 이유:

- 하이알파 후보를 편입하되 execution risk가 과도한 종목은 초기에 배제
- 에이전트가 신호를 높게 보더라도 실제 체결 가능성이 낮거나 슬리피지가 과도한 종목은 universe 단계에서 차단

#### 4.4.2 포함 reason

`market-driven overlay` 편입 종목은 reason을 명시적으로 남긴다.

예시:

- `flow_volume_surge`
- `flow_trade_strength`
- `flow_near_high_breakout`
- `flow_price_value_breakout`
- `flow_relative_volume_surge`
- `flow_relative_turnover_surge`

### 4.5 Layer 5 — Daily Execution Cap

최종적으로 오늘 loop가 실제 순회할 종목 수를 제한한다.

예시 기준:

- 최대 20~30종목
- 중요도/우선순위 순으로 cut
- 보유 종목은 cap과 무관하게 강제 포함

추가 원칙:

- cap을 무조건 크게 늘리는 대신,
  먼저 `상대 활동성 feature 기반 ranking`으로 상위 후보 품질을 높인다
- 시장 과열 구간에서도 단순 종목 수 확대보다
  `top-k 후보 품질`과 `체결 가능성`을 우선한다

비즈니스 이유:

- 5분 주기 내 판단 완료 가능성 확보
- LLM 비용 통제
- 운영자가 결과를 검토할 수 있는 범위 유지

## 5. 오늘의 Universe 구성 절차

실무 절차는 다음 순서를 따른다.

### Step 1. Core Universe 준비

정적 또는 반정적 중심 종목군을 유지한다.

예시:

- KOSPI100
- 내부 승인된 KRX 대형주 리스트

이 풀은 자주 바뀌지 않으며, 운영의 기본 모수 역할을 한다.

### Step 2. 강제 포함 종목 추가

다음 종목은 일반 우선순위와 무관하게 우선 포함한다.

1. 현재 보유 종목
2. 오늘 미체결/정합성 확인이 필요한 주문 관련 종목
3. 당일 중요 이벤트가 발생한 종목

이유:

- 이미 익스포저가 있는 종목은 반드시 관리 대상이어야 한다
- 정합성 점검 대상 종목은 universe 밖으로 밀리면 안 된다

### Step 3. Event-Driven Overlay 추가

다음 종목을 동적 overlay로 추가한다.

- 당일 중요 OpenDART 이벤트 발생 종목
- 최근 1~3영업일 내 의미 있는 공시 발생 종목
- 내부 이벤트 정책상 우선 관찰 대상 종목

### Step 4. Market-Driven Overlay 추가

다음 종목을 장중 동적 overlay로 추가한다.

- KIS 순위 분석 API에서 거래량 급증 상위 종목
- 체결강도 상위 종목
- 신고가 근접 또는 강한 돌파 후보 종목
- 가격/거래대금이 동시에 급증하는 종목

이 단계에서는 편입 전에 반드시 `Liquidity Filter`를 적용한다.

기본 정책:

- market-driven 후보는 장중 alpha 포착용이다
- core universe에 없더라도 편입 가능하다
- 단, execution risk가 높으면 편입하지 않는다

### Step 5. 제외 규칙 적용

다음은 최종 universe에서 제외한다.

- 비활성 종목
- 운영 금지 리스트
- 브로커 미지원 범위
- 이벤트/가격/스냅샷 데이터가 명백히 불완전한 종목
- 유동성 필터 미통과 종목

### Step 6. 우선순위 정렬

정렬 기준 예시:

1. 보유 종목
2. 중요 OpenDART 이벤트 발생 종목
3. 정합성/미체결 관리 대상 종목
4. `market-driven overlay` 편입 종목
5. Core Universe 일반 종목

동률일 경우:

- 최근 이벤트 시각
- 최근 수급 강도
- 유동성
- 시가총액
- 운영자 수동 우선순위

### Step 7. Daily Cap 적용

정렬 결과에 따라 최종 종목 수를 제한한다.

v1 권장:

- 기본 cap: 20
- 상한 cap: 30

## 6. v1 운영 정책

### 6.1 기본 정책

v1에서는 다음 정책을 권장한다.

1. `Base Pool = KRX active kr_stock`
2. `Core Universe = KOSPI100 또는 내부 승인 대형주 리스트`
3. `Overlay = 중요 공시 종목 + market-driven 수급/변동성 종목`
4. `강제 포함 = 보유 종목 + 정합성 점검 대상 종목`
5. `Daily Cap = 20~30`

### 6.2 초기 운영 형태

초기 1개월 near-real 운영에서는 아래 순서를 권장한다.

1. 보유 종목 관리 우선
2. 중요 공시 종목 우선
3. 장중 수급/변동성 강한 종목을 제한적으로 추가
4. 신규 발굴은 Liquidity Filter 통과 종목으로 제한

즉, “시장 전체 탐색”보다 “관리 가능한 범위 내의 고확신 종목 운영”이 우선이다.

## 7. Agent 역할 범위

### 7.1 Agent가 하지 말아야 할 것

- 전체 시장에서 임의로 오늘의 universe를 생성
- 운영 정책을 우회해 종목을 독자적으로 추가/삭제

### 7.2 Agent가 해도 되는 것

- 선정된 universe 내부에서 우선순위 보조
- 이벤트 강도 해석
- 종목별 actionability 판단
- HOLD/WATCH/APPROVE 결정

### 7.3 결론

Universe 생성은 deterministic system policy가 authoritative source여야 한다.

에이전트는 `selection authority`가 아니라 `decision intelligence` 역할을 맡는다.

## 8. 개발 반영 원칙

### 8.1 필수 분리

개발 구조는 아래 3개를 분리해야 한다.

1. `Instrument Master`
2. `Universe Selection Policy`
3. `Decision Loop`

현재처럼 decision loop가 직접 fallback 심볼 하나를 잡아 돌기만 하면, instrument master가 확장돼도 비즈니스 의미가 없다.

### 8.2 최소 구현 순서

#### P0

- `TRADING_UNIVERSE_SYMBOLS` 또는 DB 기반 universe source 확보
- 단일 `005930` fallback 제거 또는 fallback 전용으로 축소
- 다종목 loop 동작 확보

#### P1

- 별도 universe selection layer 도입
- `core universe`, `held positions`, `event-driven overlay`, `market-driven overlay`를 합성하는 deterministic selector 구현
- 종목별 inclusion reason 기록
- `market-driven overlay` 종목은 Fast Layer에서 우선 스코어링
- Liquidity Filter를 deterministic pre-gate로 구현

권장 selector 합성식:

```text
Final Universe
  = Core Universe
  + Held Positions
  + Event-Driven Overlay
  + Market-Driven Overlay
  - Exclusion Rules
  -> Priority Ranking
  -> Daily Cap
```

Fast Layer 정책:

- `market-driven overlay`에서 편입된 종목은 초/분 단위 Fast Layer scoring 후보로 우선 배정
- Event/공시 중심 Slow Layer보다 높은 refresh cadence를 허용할 수 있다
- 단, 실제 submit gate는 계좌 예산, snapshot freshness, compliance/risk guard를 그대로 통과해야 한다
- Fast Layer 후보 우선순위는 절대 거래대금뿐 아니라
  `relative volume`, `relative turnover`, `trade strength`를 함께 반영한다

#### P2

- universe ranking 보조용 AI 또는 hybrid scoring 도입
- adaptive scheduling과 결합

## 9. 권장 데이터 모델

v1 이후에는 별도 universe 소스를 분리하는 것이 바람직하다.

예시:

- `universe_watchlists`
- `universe_watchlist_items`
- `universe_daily_runs`

최소 필드 예시:

- `symbol`
- `market_code`
- `enabled`
- `priority`
- `reason`
- `source_type` (`core`, `held_position`, `event_overlay`, `market_overlay`, `manual`)
- `effective_date`

## 10. 운영 예외 처리

### 10.1 보유 종목

보유 종목은 universe 일반 cap보다 우선한다.

정책:

- 보유 종목은 항상 포함
- 보유 종목이 많아져도 일반 후보군을 줄여서 수용

### 10.2 정합성 대상 종목

`reconcile_required`, 미체결 관리, lineage 점검 대상 종목은 universe에서 빠지면 안 된다.

정책:

- execution/reconciliation 관련 종목은 항상 포함

### 10.3 이벤트 발생 종목 급증

같은 날 중요 이벤트 종목이 급증하면, 모두 신규 진입 대상으로 삼지 않는다.

정책:

- 중요 이벤트 종목은 포함하되
- 실제 submit 후보는 추가 cap 또는 ranking으로 제한

### 10.4 Market-Driven 후보 급증

장중 변동성이 커질 때 `market-driven overlay` 후보가 급증할 수 있다.

정책:

- Fast Layer 우선순위는 높게 두되 무제한 편입하지 않는다
- Liquidity Filter 통과 후에도 별도 overlay cap을 둘 수 있다
- 시장 과열 구간에서는 core/held/event 종목을 침범하지 않는 범위에서만 편입한다

## 11. KPI

Universe 정책의 품질은 아래로 평가한다.

1. 오늘 universe 종목 수
2. 보유 종목 포함 누락률
3. 중요 이벤트 종목 포함률
4. market-driven 편입 종목의 actionability 비율
5. 판단 loop 평균 소요시간
6. submit candidate 대비 실제 submit 전환율
7. 이벤트 없는 종목 반복 판단 비율

## 12. 최종 권고

현재 단계의 최적 운영 원칙은 다음과 같다.

1. Universe는 시스템 정책으로 선정한다.
2. 에이전트는 universe 안에서만 판단한다.
3. 보유 종목, 중요 이벤트 종목, 정합성 대상 종목은 강제 포함한다.
4. market-driven alpha 후보는 별도 overlay로 편입하되, Liquidity Filter를 반드시 통과시킨다.
5. 최종 종목 수는 운영 예산과 주기 제약으로 제한한다.
6. Universe 선정 이유를 종목별로 기록 가능하게 만든다.

이 문서는 향후 `Universe Selection Agent` 또는 `Universe Selection Service` 구현의 비즈니스 기준 문서로 사용한다.
