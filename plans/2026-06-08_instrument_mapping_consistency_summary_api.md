# Instrument Mapping Consistency Summary API

## 목적
- `instrument master`와 실제 운영 데이터(`external_events`, `broker_fill_snapshots`) 사이의
  symbol 매핑 누락을 운영자가 스크립트 없이 바로 조회할 수 있게 한다.
- 앞서 추가한 audit CLI를 inspection API로 노출해서,
  `snapshot/event mapping과의 정합성 확보` 작업을 운영 점검 경로와 연결한다.

## 구현
- 신규 endpoint:
  - `GET /instruments/mapping-consistency/summary?lookback_days=7`
- 구현 파일:
  - [src/agent_trading/api/routes/instruments.py](/workspace/agent_trading/src/agent_trading/api/routes/instruments.py)
  - [src/agent_trading/api/schemas.py](/workspace/agent_trading/src/agent_trading/api/schemas.py)

## 응답 구조
- `lookback_days`
- `active_instrument_count`
- `has_gap`
- `total_unmapped_external_event_symbols`
- `total_unmapped_broker_fill_symbols`
- `unmapped_external_event_symbols`
- `unmapped_broker_fill_symbols`

각 gap item은 아래를 포함한다.
- `symbol`
- `occurrence_count`
- `latest_observed_at`

## 조회 기준
- 최근 `lookback_days` 이내 `external_events.symbol` 중 `trading.instruments`에 없는 symbol
- 최근 `lookback_days` 이내 `broker_fill_snapshots.symbol` 중 `trading.instruments`에 없는 symbol
- 현재 `is_active=true` instrument 개수

## 의도
- 운영자가 스크립트를 직접 실행하지 않아도 inspection API에서 바로
  - 이벤트 쪽 매핑 누락
  - 체결 스냅샷 쪽 매핑 누락
  를 구분할 수 있게 한다.

## 검증
- `pytest -q tests/api/test_inspection.py -k 'instrument_mapping_consistency_summary or get_instrument_'`
- `python3 -m py_compile src/agent_trading/api/routes/instruments.py src/agent_trading/api/schemas.py tests/api/test_inspection.py`

## 남은 작업
- unmapped symbol auto-seed / placeholder instrument 생성 정책 검토
- snapshot sync 에러(`Instrument not found for pdno=...`)와 이 summary를 한 화면/한 리포트로 통합
