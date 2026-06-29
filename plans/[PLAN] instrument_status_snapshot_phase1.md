# Instrument Status Snapshot Phase 1

## 목적

`trading.instruments`를 기준 종목 마스터로 유지하면서,
`CTPF1002R` 및 관련 시세 응답이 제공하는
`거래정지`, `관리종목`, `투자유의`, `NXT 거래정지` 같은
상태성 정보를 별도 snapshot 계층으로 분리한다.

핵심 원칙은 아래와 같다.

- `instrument master`와 `instrument status`를 같은 테이블에 섞지 않는다.
- 오전 `instrument master sync`는 계속 CSV 기반 canonical source로 유지한다.
- 종목 상태 판단은 별도 snapshot row를 authoritative fact로 사용한다.
- Universe Selection과 submit 직전 compliance validator가
  동일한 status fact를 읽도록 만든다.
- 신규 BUY와 held-position SELL의 차단 정책은 동일하지 않게 설계한다.

## 현재 코드 기준 문제

### 1. `restricted symbol` 경로의 authoritative 입력이 비어 있다

- 현재 [src/agent_trading/services/compliance_validator.py](/workspace/agent_trading/src/agent_trading/services/compliance_validator.py)
  의 `compliance_restricted_symbol`은
  `blocked_reason_codes`가 하나라도 있으면 차단하는 구조다.
- 하지만 [src/agent_trading/brokers/koreainvestment/snapshot.py](/workspace/agent_trading/src/agent_trading/brokers/koreainvestment/snapshot.py)
  에서 생성하는 `RiskLimitSnapshotEntity`는
  대부분 `nav` 중심이며 `blocked_reason_codes`를
  종목 상태 fact로 채우지 않는다.
- 따라서 현재 `restricted symbol`은
  구조는 있으나 실제 `관리종목` / `거래정지` 차단의
  authoritative source로는 부족하다.

### 2. 상태 필터가 universe 쪽에만 부분적으로 흩어져 있다

- [src/agent_trading/services/universe_selection.py](/workspace/agent_trading/src/agent_trading/services/universe_selection.py)
  는 `inquire-price` 응답의 `iscd_stat_cls_code`를 이용해
  `관리종목/투자위험/투자경고/투자주의/거래정지`를
  overlay 필터에 반영한다.
- 그러나 이 값은
  - `market_overlay` 전용 필터 성격이 강하고
  - submit 직전 hard compliance block과는 아직 연결되지 않는다.

### 3. `CTPF1002R`는 유용하지만 instrument master 대체 source는 아니다

- KIS `CTPF1002R` (`주식기본조회`)는
  `tr_stop_yn`, `admn_item_yn`, `mket_id_cd`, `scty_grp_id_cd`,
  `kospi200_item_yn`, `nxt_tr_stop_yn` 등
  규정/상태성 판단에 유용한 필드를 제공한다.
- 하지만 종목별 REST 조회이므로,
  KOSPI/KOSDAQ 전체 master 적재 source로 쓰기에는
  rate limit / 호출량 / 장애 복구 측면에서 부적합하다.

## 설계 결론

### 역할 분리

#### 1. `trading.instruments`

- 기준 종목 마스터
- source:
  - KIS 종목정보파일 CSV
  - 승인된 membership seed
- 성격:
  - 느리게 바뀌는 기준 데이터
  - symbol / market / name / 식별코드 / segment / membership

#### 2. `trading.instrument_status_snapshots`

- 종목 상태 snapshot fact
- source:
  - 1차: `CTPF1002R`
  - 2차 보조: `inquire-price` 응답
- 성격:
  - 거래 가능 여부와 규정성 상태를 담는 빠른 스냅샷
  - universe / compliance / inspection 공통 입력

## Phase 1 범위

### 저장 대상 필드

`CTPF1002R` 또는 보조 시세 응답에서 아래 필드를 우선 저장한다.

- `tr_stop_yn`
- `admn_item_yn`
- `mket_id_cd`
- `scty_grp_id_cd`
- `excg_dvsn_cd`
- `nxt_tr_stop_yn`
- `kospi200_item_yn`
- `prdt_type_cd`
- `iscd_stat_cls_code`
- `temp_stop_yn`
- `status_reason_codes`
- `raw_payload_json`

### Phase 1 저장 단위

- key:
  - `instrument_status_snapshot_id`
  - `instrument_id`
  - `snapshot_at`
  - `source_type`
- source_type 예시:
  - `kis_stock_basic_info`
  - `kis_inquire_price`
  - `composed_status`

### authoritative 판정

Phase 1에서는 아래 우선순위를 사용한다.

1. 같은 거래일 최신 `CTPF1002R` snapshot
2. 같은 거래일 최신 `inquire-price` snapshot
3. 없으면 `unknown_status`

`unknown_status`일 때의 정책:

- 신규 BUY:
  - fail-closed가 맞다.
  - 장전 상태 배치가 실패했거나 freshness가 기준 미달이면
    `status_snapshot_unavailable_for_new_buy`로 차단한다.
- held-position SELL (`REDUCE` / `EXIT`):
  - 기본은 fail-open으로 둔다.
  - 이유는 과보유/리스크 축소 경로를
    status snapshot 누락만으로 막지 않기 위해서다.
  - 다만 시장 세션 자체가 닫혀 있거나
    브로커가 명시적으로 거래정지 reject를 반환하면
    그 지점에서 authoritative하게 중단한다.

## 권장 DB 스키마

### 신규 테이블

`trading.instrument_status_snapshots`

권장 컬럼:

- `instrument_status_snapshot_id UUID PRIMARY KEY`
- `instrument_id UUID NOT NULL`
- `snapshot_at TIMESTAMPTZ NOT NULL`
- `source_type TEXT NOT NULL`
- `status_scope TEXT NOT NULL`
- `tr_stop_yn TEXT`
- `admn_item_yn TEXT`
- `nxt_tr_stop_yn TEXT`
- `temp_stop_yn TEXT`
- `iscd_stat_cls_code TEXT`
- `mket_id_cd TEXT`
- `scty_grp_id_cd TEXT`
- `excg_dvsn_cd TEXT`
- `prdt_type_cd TEXT`
- `status_reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb`
- `raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

권장 인덱스:

- `(instrument_id, snapshot_at DESC)`
- `(snapshot_at DESC)`
- `(source_type, snapshot_at DESC)`

권장 제약:

- `status_scope IN ('instrument', 'market_overlay_probe', 'submit_preflight')`
- `source_type IN ('kis_stock_basic_info', 'kis_inquire_price', 'composed_status')`

## 도메인 / 저장소 추가안

### 1. domain entity

[src/agent_trading/domain/entities.py](/workspace/agent_trading/src/agent_trading/domain/entities.py)
에 아래 entity 추가:

- `InstrumentStatusSnapshotEntity`

권장 필드:

- `instrument_status_snapshot_id`
- `instrument_id`
- `snapshot_at`
- `source_type`
- `status_scope`
- `tr_stop_yn`
- `admn_item_yn`
- `nxt_tr_stop_yn`
- `temp_stop_yn`
- `iscd_stat_cls_code`
- `mket_id_cd`
- `scty_grp_id_cd`
- `excg_dvsn_cd`
- `prdt_type_cd`
- `status_reason_codes`
- `raw_payload_json`
- `created_at`

### 2. repository contract

신규 contract:

- `InstrumentStatusSnapshotRepository`

최소 메서드:

- `add(snapshot)`
- `get_latest_by_instrument(instrument_id)`
- `get_latest_by_instrument_before(instrument_id, as_of)`
- `list_latest_by_instrument_ids(instrument_ids)`

### 3. postgres repository

신규 파일:

- `src/agent_trading/repositories/postgres/instrument_status_snapshots.py`

## 배치 설계

### 1. 실행 위치

`ops-scheduler` 장전 구간에
`instrument master sync` 다음 단계로 붙인다.

권장 순서:

1. `build_kis_instrument_master_sync_csv.py`
2. `sync_kis_instrument_master.py`
3. `build_instrument_status_snapshots.py`
4. `decision_loop_intraday freeze`

### 2. 실행 시각

현재 장전 `instrument master sync`가 `04:50 KST`이므로,
status snapshot 배치는 같은 장전 구간 후속 작업으로 붙이는 것이 맞다.

권장 기본 시각:

- `05:05 KST` 1차 실행

이유:

- master sync가 끝난 뒤 canonical `instrument_id`를 기준으로
  status snapshot을 적재할 수 있다.
- 장 시작 전에 충분한 retry 여유를 남긴다.

### 3. 대상 종목 범위

전체 KRX 전종목 일괄 조회는 Phase 1 범위에서 과하다.

권장 대상:

1. `approved core universe`
2. active `instrument_index_memberships` 편입 종목
3. 최근 `held_position` 종목
4. 최근 `reconciliation_overlay` / open order 관련 종목
5. 당일 `intraday freeze` 후보 seed

즉, “오늘 판단/관리 대상에 실제로 들어올 가능성이 있는 종목” 위주로 제한한다.

### 4. 호출 전략

- `CTPF1002R`는 종목별 상세조회이므로
  강한 pacing이 필요하다.
- Phase 1 기본 전략:
  - 동시성 1
  - 1 request 후 1초 sleep
  - 실패 시 exponential backoff
  - 전체 실패가 아니라 종목별 partial commit 허용

### 5. 산출물

- DB:
  - `instrument_status_snapshots`
- 로그:
  - 성공/실패 건수
  - skipped 이유
  - freshness 기준
- 후속 단계 입력:
  - universe / compliance 공통 조회

## 코드 연결 지점

### 1. KIS client

신규 메서드 추가:

- [src/agent_trading/brokers/koreainvestment/rest_client.py](/workspace/agent_trading/src/agent_trading/brokers/koreainvestment/rest_client.py)
  - `get_stock_basic_info(symbol, prdt_type_cd='300')`

반환 최소 필드:

- `tr_stop_yn`
- `admn_item_yn`
- `mket_id_cd`
- `scty_grp_id_cd`
- `excg_dvsn_cd`
- `nxt_tr_stop_yn`
- `kospi200_item_yn`
- `prdt_type_cd`
- 원본 payload

### 2. batch script

신규 스크립트:

- `scripts/build_instrument_status_snapshots.py`

입력:

- 대상 instrument set
- source priority
- snapshot time

출력:

- `instrument_status_snapshots` upsert 또는 append

### 3. ops-scheduler

[scripts/run_ops_scheduler.py](/workspace/agent_trading/scripts/run_ops_scheduler.py)
에 신규 phase 추가:

- `instrument_status_snapshot`

필요 사항:

- command result 기록
- missed window 기록
- partial success 요약

## Universe Selection 연결안

### 연결 위치

[src/agent_trading/services/universe_selection.py](/workspace/agent_trading/src/agent_trading/services/universe_selection.py)

### 적용 방식

- 현재 `iscd_stat_cls_code` 중심의 market overlay 전용 필터를
  `instrument_status_snapshot` 우선 조회로 승격한다.
- 공통 eligibility에서 아래를 hard exclude로 쓴다.
  - `tr_stop_yn='Y'`
  - `admn_item_yn='Y'`
  - `nxt_tr_stop_yn='Y'`
  - `iscd_stat_cls_code`가 차단 코드 집합에 포함

### fallback

- snapshot이 없으면
  - core / event / manual / market 공통으로 `unknown_status`를 붙인다.
  - 다만 Phase 1에서는 즉시 전부 제외하지 않고,
    신규 BUY 계열 source에 한해 exclude,
    held/reconciliation 관리 source는 유지하는 방식이 맞다.

## Compliance Validator 연결안

### 입력 구조 확장

[src/agent_trading/services/compliance_validator.py](/workspace/agent_trading/src/agent_trading/services/compliance_validator.py)
의 `ComplianceValidationInput`에 아래 필드 추가:

- `status_reason_codes`
- `status_snapshot_at`
- `status_source_type`
- `allow_unknown_status_for_sell`

### 신규 rule

- `compliance_instrument_status_blocked`
- `compliance_status_snapshot_unavailable`

### 차단 기준

- 신규 BUY:
  - `tr_stop_yn='Y'`
  - `admn_item_yn='Y'`
  - `iscd_stat_cls_code` 차단 코드
  - status snapshot freshness 초과
- SELL:
  - 위 사유가 있어도 무조건 동일 정책 적용하지 않는다.
  - held-position `REDUCE/EXIT`는 별도 정책으로 열어 둔다.

## Inspection / Admin 노출안

### inspection API

후속 API 후보:

- `GET /instruments/{instrument_id}/status`
- `GET /instruments/status/latest?symbol=...`

반환 예시:

- latest snapshot 시각
- `tr_stop_yn`
- `admn_item_yn`
- `iscd_stat_cls_code`
- `status_reason_codes`
- source_type

### 운영 가치

- “왜 universe에서 제외됐는가”
- “왜 submit 직전 compliance가 막았는가”
- “관리종목/거래정지 판단의 근거가 무엇인가”

를 DB 기반으로 바로 설명할 수 있다.

## 구현 순서

### Step 1

DB / entity / repository 추가

### Step 2

`CTPF1002R` client method 추가

### Step 3

장전 batch script 추가

### Step 4

`UniverseSelectionService` read-path 연결

### Step 5

`compliance_validator_v1` read-path 연결

### Step 6

inspection / runbook / 운영 계측 추가

## 완료 기준

아래가 만족되면 Phase 1 완료로 본다.

- `instrument master`와 `status snapshot` 역할이 문서와 코드에서 분리된다.
- 장전 배치가 대상 universe 후보에 대해 status snapshot을 저장한다.
- universe exclusion과 submit 직전 compliance 차단이
  동일한 status fact를 읽는다.
- `관리종목` / `거래정지` 차단 근거를
  DB row와 API 응답으로 설명할 수 있다.
