# WATCH Diagnostics API And EI Metadata Persistence

## 목적
- `WATCH decision 부재 원인 분석 및 정책 보완` 작업을 코드 레벨에서 시작한다.
- 사후 진단에 필요한 EI 메타데이터를 `trade_decisions.decision_json`에 남기고,
  운영자가 최근 `WATCH/HOLD` 분포를 바로 확인할 수 있는 inspection API를 추가한다.

## 변경 사항

### 1. EI 메타데이터 persistence 보강
- [src/agent_trading/services/common_types.py](/workspace/agent_trading/src/agent_trading/services/common_types.py)
  - `AIDecisionInputs`에 아래 필드 추가
    - `evidence_strength`
    - `no_material_events`
    - `detected_event_count`
    - `interpreted_event_count`
- [src/agent_trading/services/decision_agent_runner.py](/workspace/agent_trading/src/agent_trading/services/decision_agent_runner.py)
- [src/agent_trading/services/subprocess_helpers.py](/workspace/agent_trading/src/agent_trading/services/subprocess_helpers.py)
  - EI output에서 위 필드를 `AIDecisionInputs`로 전달
- [src/agent_trading/services/decision_factory.py](/workspace/agent_trading/src/agent_trading/services/decision_factory.py)
  - `trade_decisions.decision_json`에 위 메타데이터를 저장

### 2. WATCH diagnostics inspection API 추가
- [src/agent_trading/api/routes/decisions.py](/workspace/agent_trading/src/agent_trading/api/routes/decisions.py)
  - `GET /trade-decisions/watch-diagnostics`
- [src/agent_trading/api/schemas.py](/workspace/agent_trading/src/agent_trading/api/schemas.py)
  - `WatchDiagnosticsResponse`
  - `WatchDiagnosticsSourceTypeItem`
  - `WatchDiagnosticsEvidenceStrengthItem`
  - `WatchDiagnosticsReasonCodeItem`
  - `WatchDiagnosticsSampleItem`

## API 응답 핵심
- 최근 N일 전체 decision 수
- `HOLD` / `WATCH` 수와 `watch_rate`
- `no_material_events=true` 조건의 `WATCH/HOLD` 수
- `source_type`별 WATCH/HOLD 분포
- `evidence_strength`별 WATCH/HOLD 분포
- 최근 WATCH decision의 상위 `event_reason_codes`
- 최근 WATCH/HOLD 샘플

## 의미
- 이제 11번(`WATCH 부재 분석`)과 12번(`core + no_event HOLD 완화`)을
  운영 DB 기준으로 바로 측정할 수 있다.
- 기존 문서 분석이 정적 보고서였다면, 이제는 운영 API로 현재 상태를 재확인할 수 있다.

## 검증
- `pytest -q tests/api/test_inspection.py -k 'watch_diagnostics or list_trade_decisions_includes_decision_json'`
- `pytest -q tests/services/test_decision_orchestrator.py -k 'ai_backend_inputs_direct_defaults or ai_backend_inputs_schema_versions_immutable'`
- `python3 -m py_compile src/agent_trading/api/routes/decisions.py src/agent_trading/api/schemas.py src/agent_trading/services/common_types.py src/agent_trading/services/decision_factory.py src/agent_trading/services/decision_agent_runner.py src/agent_trading/services/subprocess_helpers.py tests/api/test_inspection.py`
