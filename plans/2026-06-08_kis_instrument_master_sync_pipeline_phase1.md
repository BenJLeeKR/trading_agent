# KIS Instrument Master Sync Pipeline Phase 1

## 목적
- KIS 종목정보파일 기반으로 `trading.instruments`를 갱신할 수 있는 첫 적재 경로를 만든다.
- 기존의 고정 seed/CSV 수동 주입 단계를 넘어, 운영자가 정규화된 KIS master CSV를 사용해 종목 master를 갱신할 수 있게 한다.

## 범위
- 입력: 정규화된 KIS master CSV
- 처리:
  - `symbol`, `name` 필수
  - `market_code`, `asset_class`, `currency`, `tick_size`, `lot_size`, `is_active` 선택
  - `name_kr`, `short_name`, `isin_code`, `standard_code`, `exchange_code`, `listing_date`, `delisting_date`, `source_updated_at`, `par_value`, `listing_shares`
    는 `metadata`로 보존
  - `metadata_*` prefix 컬럼도 `metadata`에 그대로 적재
- 결과:
  - `(symbol, market_code)` 기준 upsert
  - 선택적으로 누락 active 종목 비활성화

## 구현
- 신규 스크립트:
  - [scripts/sync_kis_instrument_master.py](/workspace/agent_trading/scripts/sync_kis_instrument_master.py)

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
