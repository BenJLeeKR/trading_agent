# instrument market_code canonical model 결정

## 목적

- `trading.instruments`의 canonical 저장 모델을
  계속 `market_code='KRX'`로 유지할지,
  아니면 `market_code='KOSPI'|'KOSDAQ'`로 재정의할지
  현재 코드 기준으로 판단한다.

## 현재 상태 요약

- 현재 국내주식 canonical row는
  `market_code='KRX'`로 저장한다.
- `KOSPI/KOSDAQ` 구분은
  `exchange_code='KRX'` + `market_segment='KOSPI'|'KOSDAQ'`
  및 `metadata.source_market_code`로 보존한다.
- `KOSPI100`, `KOSPI200`, `KOSDAQ50`, `KOSDAQ150`는
  `instrument_index_memberships`와
  `metadata.index_memberships` fallback으로 관리한다.

## 코드 영향 범위

현재 코드베이스에서 `market_code='KRX'` canonical 가정이 이미 넓게 퍼져 있다.

### 저장/조회

- `PostgresInstrumentRepository.get_by_symbol_any_market()`
  는 `exchange_code='KRX' and market_code='KRX'`를 최우선 canonical row로 간주한다.
- `sync_kis_instrument_master.py`
  는 국내주식 입력이 `KOSPI`/`KOSDAQ`여도
  `_canonicalize_storage_market()`에서 `KRX`로 수렴시킨다.

### 상위 서비스

- `UniverseSelectionService`
  는 `KRX`, `KOSPI`, `KOSDAQ`를 모두 읽되
  실질적으로는 canonical `KRX` row와
  `market_segment`/membership를 조합해 사용한다.
- `DecisionOrchestratorService`,
  `ExecutionService`,
  `kis_snapshot_sync`,
  `sell_guard`
  는 canonical instrument lookup 이후
  `instrument.market_code`를 계속 사용한다.

### DB/테스트

- `trade_decisions`, `signal_feature_snapshots`, `position_snapshots`,
  `order_requests`, `universe_freeze_run_items` 등
  여러 FK 경로가 canonical instrument row를 참조한다.
- 테스트 fixture와 smoke/integration 코드 다수가
  국내주식 기본값을 `market_code='KRX'`로 가정한다.

## 판단

### 결론

- 현재 단계에서는
  `market_code='KRX'` canonical 저장 모델을 **유지**한다.

### 이유

1. 현재 구조에서 `market_segment`와 `instrument_index_memberships`가
   이미 `KOSPI/KOSDAQ/지수편입` 의미를 충분히 분리하고 있다.
2. `market_code`를 `KOSPI|KOSDAQ`로 바꾸면
   저장 모델은 직관적일 수 있으나,
   실제 운영 이득 대비
   FK 치환, replay, snapshot, order history,
   테스트 fixture 전면 수정 비용이 크다.
3. Universe selection, sell guard, snapshot sync의
   실질 판단 기준은 이미 `exchange_code + market_segment + membership`
   로 이동 중이다.
4. 지금 우선순위는
   저장 모델 미학보다
   authoritative membership source 확보와
   운영 정합성 강화 쪽이 더 높다.

## 운영 원칙

- `market_code`
  - canonical 저장 키로서 `KRX` 유지
- `exchange_code`
  - 거래소 구분값으로 `KRX` 유지
- `market_segment`
  - `KOSPI` / `KOSDAQ` 구분의 1차 authoritative field
- `instrument_index_memberships`
  - `KOSPI100`, `KOSPI200`, `KOSDAQ50`, `KOSDAQ150`의
    1차 authoritative source
- `metadata.source_market_code`
  - 원본 CSV가 제공한 시장 구분의 provenance 저장

## 재검토 조건

아래 조건이 모두 만족될 때만
`market_code='KOSPI'|'KOSDAQ'` 모델로의 재정의를 다시 검토한다.

1. 외부 membership authoritative source가 안정화되어
   `instrument_index_memberships` 운영 절차가 정착할 것
2. `UniverseSelectionService`, `sell_guard`, `kis_snapshot_sync`,
   `Decision/Execution` read path가
   `market_segment + membership` 기준으로 충분히 안정화될 것
3. 기존 FK 참조 테이블 치환/backfill 계획,
   replay 영향도, 운영 다운타임 전략이 문서화될 것
4. 운영 가독성 개선 이득이
   migration 비용보다 크다는 근거가 확보될 것

## 결정

- 현재 우선순위 기준 결정:
  `market_code='KRX'` canonical 저장 모델 유지
- 후속 과제:
  저장 모델 변경이 아니라
  authoritative membership source 실반영과
  운영 검증 절차 완결에 집중한다.
