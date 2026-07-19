# Placeholder Instrument Policy From Mapping Gaps

## 목적
- `instrument master`에 없는 symbol이 `external_events`, `broker_fill_snapshots`,
  `snapshot_sync_runs` 오류에서 반복 관측될 때, 운영자가 안전하게
  placeholder instrument를 생성할 수 있는 정책/도구를 추가한다.

## 정책
- placeholder는 기본적으로 **inactive** (`is_active=false`) 로 생성한다.
- canonical KIS master 데이터가 아니므로, 이름은 `[PLACEHOLDER] {symbol}` 형식으로 표시한다.
- metadata에 아래를 남긴다.
  - `placeholder=true`
  - `placeholder_source=mapping_gap_auto_seed`
  - `sources`
  - `occurrence_count`
  - `latest_observed_at`
  - `canonical_master_pending=true`
- 적용 시점 정책은 instrument master sync와 동일하게 유지한다.
  - 비거래일
  - 거래일 장전 `08:00` 이전
  - 거래일 장후 `15:30:30` 이후
  - 필요 시 `--allow-intraday-apply`, `--ignore-update-policy` override

## 구현
- 신규 스크립트:
  - [scripts/seed_placeholder_instruments_from_mapping_gaps.py](/workspace/agent_trading/scripts/seed_placeholder_instruments_from_mapping_gaps.py)

## 동작
- 최근 `lookback_days` 범위의 아래 3개 소스에서 unmapped symbol을 모은다.
  - `external_events`
  - `broker_fill_snapshots`
  - `snapshot_sync_runs.summary_json.errors` 중 `Instrument not found for pdno=...`
- 추가로 최근 `trade_decisions.instrument_id IS NULL` 누적 종목도
  canonical placeholder seed 대상에 포함해
  의사결정 저장 경로의 FK 단절을 후행 정리할 수 있어야 한다.
- 이미 어떤 market에서든 instrument row가 존재하면 skip
- 없는 symbol만 inactive placeholder를 upsert
- `index_membership_seed.csv`가 존재하면
  `exchange_code`, `market_segment`, `metadata.index_memberships`까지 함께 보강한다.

## placeholder 치환 정책
- placeholder canonical row는 별도 삭제/재생성 대상이 아니라,
  이후 `sync_kis_instrument_master.py`가 같은
  `symbol + market_code='KRX'` row를 authoritative master 데이터로
  **승격(promote)** 하는 방식으로 치환한다.
- 이때 `instrument_id`는 유지되어
  기존 `trade_decisions`, `signal_feature_snapshots`,
  `order_requests` 등 FK 참조를 깨지 않는다.
- 승격 시 기존 placeholder metadata
  (`placeholder`, `placeholder_source`, `canonical_master_pending`)는
  KIS master metadata로 교체된다.
- `metadata.index_memberships`와
  `instrument_index_memberships` active row도
  같은 sync cycle에서 함께 authoritative 값으로 동기화한다.

## 예시
```bash
python3 scripts/seed_placeholder_instruments_from_mapping_gaps.py
python3 scripts/seed_placeholder_instruments_from_mapping_gaps.py --apply
```

## 검증
- `pytest -q tests/scripts/test_seed_placeholder_instruments_from_mapping_gaps.py tests/scripts/test_sync_kis_instrument_master.py tests/repositories/test_instruments.py`
- `python3 -m py_compile scripts/seed_placeholder_instruments_from_mapping_gaps.py tests/scripts/test_seed_placeholder_instruments_from_mapping_gaps.py`

## 의미
- 이제 9번 항목의 마지막 남은 과제였던
  `unmapped symbol auto-seed / placeholder instrument 생성 정책`
  이 코드와 운영 정책 수준에서 닫혔다.
