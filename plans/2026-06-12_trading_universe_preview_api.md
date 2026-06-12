# Trading Universe Preview Inspection API

## 목적
- `Universe Selection Agent 분해` 항목의 운영 가시성을 보강한다.
- 운영자가 현재 계정 기준 `trading universe`가 어떻게 조합되는지
  API에서 바로 확인할 수 있게 한다.
- 단순 symbol 목록이 아니라, 각 종목의
  - `source_type`
  - `inclusion_reason`
  - priority
  와 전체 분포 요약까지 함께 노출한다.

## 추가한 것
- 신규 endpoint:
  - [src/agent_trading/api/routes/instruments.py](/workspace/agent_trading/src/agent_trading/api/routes/instruments.py)
  - `GET /instruments/trading-universe/preview`
- 신규 response schema:
  - [src/agent_trading/api/schemas.py](/workspace/agent_trading/src/agent_trading/api/schemas.py)
  - `TradingUniversePreviewResponse`
  - `TradingUniversePreviewItem`

## 요청 파라미터
- `account_id` (필수)
- `lookback_hours` (기본 `24`)
- `max_cap` (기본 `30`)
- `exclude_held_from_cap` (기본 `true`)
- `market_overlay_cap` (기본 `5`)
- `pre_pool_size` (기본 `50`)

## 동작 방식
- API 내부에서 `UniverseSelectionService.compose()`를 직접 호출한다.
- 즉, decision loop가 쓰는 deterministic universe selection 경로를 그대로 재사용한다.
- KIS client가 없으면 `market_overlay`는 자동으로 비활성 경로로 남고,
  KIS client가 있으면 현재 설정된 env(`paper`/`real`) 정보도 함께 반환한다.

## 응답 핵심 필드
- `total_count`
- `source_type_counts`
- `inclusion_reason_counts`
- `items[]`
  - `symbol`
  - `market`
  - `source_type`
  - `inclusion_reason`
  - `priority`

## 기대 효과
- “왜 이 종목이 오늘 판단 대상인가?”를 운영자가 바로 설명할 수 있다.
- `held_position`, `event_overlay`, `market_overlay`, `core` 분포를
  UI/운영 리포트에서 쉽게 재사용할 수 있다.
- backlog 28번의 `reason/source_type 기록`과 `운영 설명 가능성`을
  inspection 레이어까지 연결한다.

## 검증
- `pytest -q tests/api/test_inspection.py -k 'trading_universe_preview or instrument_mapping_consistency_summary'`
- `python3 -m py_compile src/agent_trading/api/routes/instruments.py src/agent_trading/api/schemas.py tests/api/test_inspection.py`
