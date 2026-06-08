# Instrument Mapping Consistency Audit

## 목적
- `instrument master`와 실제 운영 데이터(`external_events`, `broker_fill_snapshots`) 사이에
  symbol 매핑 누락이 있는지 빠르게 확인하는 read-only 점검 도구를 추가한다.
- `snapshot/event mapping과의 정합성 확보`를 감이 아니라 구조화된 목록으로 확인할 수 있게 만든다.

## 구현
- 신규 스크립트:
  - [scripts/evaluate_instrument_mapping_consistency.py](/workspace/agent_trading/scripts/evaluate_instrument_mapping_consistency.py)

## 점검 범위
- 최근 `external_events` 중 `trading.instruments`에 없는 symbol
- 최근 `broker_fill_snapshots` 중 `trading.instruments`에 없는 symbol
- `active_instrument_count` 기본 지표

## CLI 예시
```bash
python3 scripts/evaluate_instrument_mapping_consistency.py --lookback-days 7 --output text
python3 scripts/evaluate_instrument_mapping_consistency.py --lookback-days 30 --output json
```

## 의도
- 당장 auto-fix를 넣기보다, 운영자가
  - 어떤 symbol이 unmapped인지
  - 이벤트 쪽 문제인지
  - 체결 스냅샷 쪽 문제인지
를 빠르게 분리할 수 있게 한다.

## 검증
- `pytest -q tests/scripts/test_evaluate_instrument_mapping_consistency.py`
- `python3 -m py_compile scripts/evaluate_instrument_mapping_consistency.py tests/scripts/test_evaluate_instrument_mapping_consistency.py`

## 남은 작업
- unmapped symbol auto-seed / placeholder instrument 생성 여부 검토
- snapshot sync 에러(`Instrument not found for pdno=...`)와 이 audit 결과를 한 화면/한 보고서로 합치기
