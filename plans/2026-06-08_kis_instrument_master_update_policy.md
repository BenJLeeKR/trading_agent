# KIS Instrument Master Update Policy

## 목적
- `trading.instruments`를 갱신하는 경로가 장중에 무분별하게 apply되지 않도록 운영 정책을 코드로 고정한다.
- `instrument master 갱신 정책`을 단순 문서가 아니라 실제 스크립트 가드로 반영한다.
- `instrument master`에 없는 종목은 Universe Selection 단계에서 `unknown_instrument`로 제외되므로,
  KOSDAQ 종목을 판단/주문 대상으로 편입하려면 먼저 KIS 종목정보파일 기반 sync로
  해당 종목의 master row를 적재해야 한다.

## 반영 내용
- 대상 스크립트:
  - [scripts/build_kis_instrument_master_sync_csv.py](/workspace/agent_trading/scripts/build_kis_instrument_master_sync_csv.py)
  - [scripts/sync_kis_instrument_master.py](/workspace/agent_trading/scripts/sync_kis_instrument_master.py)
  - [scripts/run_ops_scheduler.py](/workspace/agent_trading/scripts/run_ops_scheduler.py)
- 시장 확장 원칙:
  - `KOSDAQ` 편입은 `decision loop`의 예외 허용으로 해결하지 않는다.
  - 먼저 `trading.instruments`에 `market_code=KOSDAQ` 종목 master를 sync한다.
  - 그 다음 Universe Selection / signal feature batch가 해당 master를 authoritative source로 사용한다.
  - 즉, `master sync → universe 편입 → decision loop` 순서를 깨지 않는다.
  - 다만 초기 단계에서는 `탐색 대상`과 `주문 core`를 분리한다.
    명시적 `core_universe=true`가 없는 KOSDAQ 종목은 기본 주문 core로 바로 승격하지 않고,
    `market overlay fallback seed` 또는 event overlay 경로에서만 먼저 관측한다.
  - `exchange_code`, `market_segment`, `segment`, `universe_segment`는
    source CSV에서 normalized CSV를 거쳐 instrument metadata에 보존한다.
    이후 Universe Selection은 이 값을 allowlist 보조가 아니라
    segment authoritative source로 사용할 수 있어야 한다.
- `--apply` 실행 시 기본 정책:
  - 비거래일: 허용
  - 거래일 장전 (`08:00` 이전 KST): 허용
  - 거래일 장후 (`15:30:30` 이후 KST): 허용
  - 거래일 장중: 차단
- 예외:
  - `--allow-intraday-apply`
    - 거래일 장중 apply를 명시적으로 허용
  - `--ignore-update-policy`
    - 응급 수동 작업용 전체 우회
- `--now-kst`
  - 테스트/재현용 현재 시각 override
- `--default-market-code`
  - CSV에 `market_code`가 비어 있을 때 사용할 기본 시장 코드
  - `KRX`, `KOSPI`, `KOSDAQ` 같은 한국 주식 시장 코드를 명시적으로 사용할 수 있다.
- scheduler 반영
  - `ops-scheduler`는 거래일 `07:50 KST`에 `instrument master sync`를 1회 시도한다.
  - 실제 실행 순서는 `원본 CSV 정규화 -> instrument master sync`다.
  - 기본 CSV 경로는 `data/instrument_master/normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv`다.
  - 기본 원본 CSV 경로는 `data/instrument_master/source/kospi_master.csv`, `data/instrument_master/source/kosdaq_master.csv`다.
  - 원본 CSV는 `data/instrument_master/archive/<YYYY-MM-DD>/` 아래로 자동 보관한다.
  - CSV가 없거나 sync command가 실패하면 `done` 처리하지 않고 다음 tick에 재시도한다.

## 구현 포인트
- `create_session_provider()`를 사용해 거래일 여부를 먼저 판정한다.
- apply 정책은 `dry-run`에는 적용하지 않는다.
- 거래일 장중 차단 메시지에 현재 시각과 허용 window를 함께 남겨 operator가 바로 이해할 수 있게 했다.
- Universe Selection은 `unknown_instrument`를 hard exclude로 취급한다.
  따라서 KOSDAQ 확장은 universe 예외 규칙이 아니라 instrument master 적재 품질 문제로 관리한다.

## 검증
- `pytest -q tests/scripts/test_sync_kis_instrument_master.py tests/scripts/test_seed_instrument_master.py tests/repositories/test_instruments.py`
  - `56 passed`
- `python3 -m py_compile scripts/sync_kis_instrument_master.py tests/scripts/test_sync_kis_instrument_master.py`
  - 통과

## 남은 작업
- `snapshot/event mapping과의 정합성 확보`
- KIS raw 종목정보파일 직접 parser 및 다운로드/보관 경로
- KOSPI/KOSDAQ master sync 운영 절차와 실행 이력 UI 연결
