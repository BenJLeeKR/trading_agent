# KIS Instrument Master Sync Pipeline Phase 1

## 목적
- KIS 종목정보파일 기반으로 `trading.instruments`를 갱신할 수 있는 첫 적재 경로를 만든다.
- 기존의 고정 seed/CSV 수동 주입 단계를 넘어, 운영자가 정규화된 KIS master CSV를 사용해 종목 master를 갱신할 수 있게 한다.
- Universe Selection은 `instrument master`에 없는 종목을 `unknown_instrument`로 제외한다.
  따라서 KOSDAQ 종목을 실제 판단 대상에 포함시키려면 이 파이프라인으로
  `market_code=KOSDAQ` master를 먼저 적재하는 것이 선행 조건이다.

## 범위
- 입력: 정규화된 KIS master CSV
- 처리:
  - `symbol`, `name` 필수
  - `market_code`, `asset_class`, `currency`, `tick_size`, `lot_size`, `is_active` 선택
  - `name_kr`, `short_name`, `isin_code`, `standard_code`, `exchange_code`, `listing_date`, `delisting_date`, `source_updated_at`, `par_value`, `listing_shares`
    는 `metadata`로 보존
  - `metadata_*` prefix 컬럼도 `metadata`에 그대로 적재
  - `market_segment`, `segment`, `universe_segment`는 normalized CSV에서
    `metadata_market_segment`, `metadata_segment`, `metadata_universe_segment`로
    보존하며, 알려진 별칭은 `KOSPI100`, `KOSDAQ150`, `KOSPI_LARGE`,
    `KOSDAQ_GROWTH` 형태로 정규화한다.
  - 원본 CSV의 `is_kospi200`, `is_kosdaq150` 플래그는
    각각 `KOSPI200`, `KOSDAQ150` membership으로 승격해
    `metadata_index_memberships`에도 함께 기록한다.
  - 현재 원본 CSV에는 `KOSPI100`, `KOSDAQ50` 직접 플래그가 없으므로
    해당 membership은 별도 소스 없이는 자동 생성하지 않는다.
- 결과:
  - `(symbol, market_code)` 기준 upsert
  - 선택적으로 누락 active 종목 비활성화
  - KOSPI/KOSDAQ row를 `market_code` 그대로 보존

## 구현
- 신규 스크립트:
  - [scripts/build_kis_instrument_master_sync_csv.py](/workspace/agent_trading/scripts/build_kis_instrument_master_sync_csv.py)
  - [scripts/sync_kis_instrument_master.py](/workspace/agent_trading/scripts/sync_kis_instrument_master.py)

### 정규화 공급 경로
- 원본 CSV 여러 개를 입력받아 하나의 normalized CSV로 합친 뒤 sync에 넘긴다.
- 현재 기본 경로:
  - 입력: `data/instrument_master/source/kospi_master.csv`
  - 입력: `data/instrument_master/source/kosdaq_master.csv`
  - 출력: `data/instrument_master/normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv`
  - 원본 보관: `data/instrument_master/archive/<YYYY-MM-DD>/...`
- `ops-scheduler`는 거래일 `07:50 KST`에
  `build_kis_instrument_master_sync_csv.py -> sync_kis_instrument_master.py`
  순서로 1회 실행한다.

### 주요 옵션
- `--csv <path>`
- `--apply`
- `--deactivate-missing`
- `--deactivate-market-code KRX`
- `--source-tag kis_master_csv`

### 동작 원칙
- `KRX`는 기존 seed와 UUID shape를 맞추기 위해 `uuid5("krx/{symbol}")` 형태를 유지
- `metadata.sync_source = "kis_master_file"` 저장
- 비활성화 시 `metadata.deactivated_by_sync = true`와 timestamp 저장
- 시장별 authoritative source를 유지하기 위해 `symbol`만이 아니라 `(symbol, market_code)`를 기준으로 관리한다.
- KOSDAQ 확장은 decision loop override가 아니라 `instrument master sync` 완료 여부로 제어한다.
- 2026-06-19 기준 시범 KOSDAQ 종목은 `core universe`가 아니라
  `discovery seed`로만 먼저 편입되도록 코드 분리를 적용했다.
  즉, 명시적 `core_universe=true`가 없는 KOSDAQ 종목은
  `market overlay fallback seed`에는 포함될 수 있지만,
  기본 `compose()`의 주문 core에는 자동 승격되지 않는다.
- 2026-06-19 기준 `exchange_code`, `market_segment`, `segment`, `universe_segment`도
  instrument metadata의 authoritative source로 적재되도록
  normalized CSV 생성 경로를 확장했다.

## 검증
- `pytest -q tests/scripts/test_sync_kis_instrument_master.py tests/scripts/test_seed_instrument_master.py tests/repositories/test_instruments.py`
  - `52 passed`
- `python3 -m py_compile scripts/sync_kis_instrument_master.py tests/scripts/test_sync_kis_instrument_master.py`
  - 통과

## 남은 작업
- KIS raw 종목정보파일 포맷을 직접 정규화하는 parser 추가
- KIS 종목정보파일 다운로드/보관 경로 확정
- 주기 배치(새벽/장후) 연결
- `instrument master 갱신 정책` 정식화
  - [`plans/2026-06-08_kis_instrument_master_update_policy.md`](./2026-06-08_kis_instrument_master_update_policy.md)
- snapshot/event mapping과의 정합성 검증 확대
- KOSDAQ master sync 후 universe / signal feature / decision loop 경로 실측
  - 2026-06-19 기준 테스트 고정 완료:
    - `Universe Selection`의 KOSDAQ instrument 통과
    - `signal_feature_snapshot_input`의 `market=KOSDAQ` 유지
    - `run_decision_loop` DB fallback universe의 `market=KOSDAQ` 유지
    - preview API의 `market=KOSDAQ` 노출
    - coverage summary의 `market_counts` 노출
    - KOSDAQ discovery seed의 `core 미승격 + overlay seed 편입` 분리
