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
- 이미 어떤 market에서든 instrument row가 존재하면 skip
- 없는 symbol만 inactive placeholder를 upsert

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
