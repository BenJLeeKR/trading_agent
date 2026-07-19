# Instrument Mapping Summary + Snapshot Sync Error Link

## 목적
- `instrument master` 매핑 누락이 실제 snapshot sync에서 어떤 오류로 나타나는지
  운영자가 한 번에 볼 수 있게 연결한다.
- 기존 `external_events`, `broker_fill_snapshots` 기준 unmapped symbol summary에
  최근 `snapshot_sync_runs`의 `Instrument not found for pdno=...` 오류를 함께 포함한다.

## 구현
- `build_sync_run_entity()`가 이제 `batch.errors`를 `summary_json["errors"]`에 보존한다.
- `GET /instruments/mapping-consistency/summary`가 최근 `snapshot_sync_runs.summary_json.errors`
  에서 `Instrument not found for pdno=...` 패턴을 집계한다.

### 변경 파일
- [src/agent_trading/services/kis_snapshot_sync.py](/workspace/agent_trading/src/agent_trading/services/kis_snapshot_sync.py)
- [src/agent_trading/api/routes/instruments.py](/workspace/agent_trading/src/agent_trading/api/routes/instruments.py)
- [src/agent_trading/api/schemas.py](/workspace/agent_trading/src/agent_trading/api/schemas.py)

## 추가 응답 필드
- `total_unmapped_snapshot_position_symbols`
- `unmapped_snapshot_position_symbols`

각 row는 다음을 포함한다.
- `symbol`
- `occurrence_count`
- `latest_observed_at`

## 의도
- 이제 운영자는 한 API에서
  - 이벤트 쪽 매핑 누락
  - 체결 스냅샷 쪽 매핑 누락
  - snapshot sync 시점 unknown-instrument 오류
  를 함께 볼 수 있다.

## 검증
- `pytest -q tests/api/test_inspection.py -k 'instrument_mapping_consistency_summary or get_instrument_'`
- `pytest -q tests/services/test_kis_snapshot_sync.py -k 'summary_json_embeds_errors_and_positions_skipped or TestBuildSyncRunEntity'`
- `python3 -m py_compile src/agent_trading/api/routes/instruments.py src/agent_trading/api/schemas.py src/agent_trading/services/kis_snapshot_sync.py tests/api/test_inspection.py tests/services/test_kis_snapshot_sync.py`

## 남은 작업
- unmapped symbol auto-seed / placeholder instrument 생성 정책 검토
- 필요 시 Admin UI 정합성 점검 화면에서 이 summary를 직접 소비
