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
- 현재 운영 원본 CSV가 `is_kospi200`, `is_kosdaq150` 플래그를 제공하면
  정규화 단계에서 이를 각각 `KOSPI200`, `KOSDAQ150`으로 변환해
  `metadata_segment`, `metadata_universe_segment`, `metadata_index_memberships`에 반영한다.
- 현재 원본 CSV에는 `is_kospi100`, `is_kosdaq50` 플래그가 없으므로
  `KOSPI100`, `KOSDAQ50`은 별도 원천 데이터나 승인 리스트 없이 자동 생성하지 않는다.
  또한 현재 `kosdaq_master.csv`는 `is_kosdaq150=False`만 제공하므로,
  실제 `KOSDAQ150` 구성종목 authoritative source로는 불충분하다.
  이를 보완하기 위해 운영 CSV
  `data/instrument_master/source/index_membership_seed.csv`
  또는 동일 포맷의 seed 파일을 별도 import 경로로 허용한다.
  예시 템플릿은
  `data/instrument_master/source/index_membership_seed.example.csv`를 사용한다.
  이후 Universe Selection은 이 값을 allowlist 보조가 아니라
  segment authoritative source로 사용할 수 있어야 한다.
  - `index_memberships`는
    `trading.instrument_index_memberships`에 authoritative history로 적재하고,
    `metadata.index_memberships`는 backward-compatible fallback으로 함께 유지한다.
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
- 국내주식 canonical field 방향:
  - `KRX`는 삭제하지 않고 `exchange_code` 의미로 유지한다.
  - `KOSPI`, `KOSDAQ`는 `market_segment`로 분리 적재한다.
  - `KOSPI100`, `KOSPI200`, `KOSDAQ50`, `KOSDAQ150`은
    정규화된 `index_memberships` authoritative source로 관리한다.
  - 초기에는 `metadata.index_memberships` 배열 허용,
    후속으로 시계열 membership table 승격을 검토한다.
- scheduler 반영
  - `ops-scheduler`는 거래일 `07:50 KST`에 `instrument master sync`를 1회 시도한다.
  - 실제 실행 순서는 `원본 CSV 정규화 -> instrument master sync`다.
  - 기본 CSV 경로는 `data/instrument_master/normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv`다.
  - 기본 원본 CSV 경로는 `data/instrument_master/source/kospi_master.csv`, `data/instrument_master/source/kosdaq_master.csv`다.
  - 원본 CSV는 `data/instrument_master/archive/<YYYY-MM-DD>/` 아래로 자동 보관한다.
  - CSV가 없거나 sync command가 실패하면 `done` 처리하지 않고 다음 tick에 재시도한다.
  - 별도 membership seed CSV는
    필요 시 운영자가 수동으로 import 하며,
    기본 동작은 기존 membership과 `merge`다.
    명시적 `replace`가 필요한 경우에만 listed symbol 기준 authoritative overwrite를 사용한다.

## 구현 포인트
- `create_session_provider()`를 사용해 거래일 여부를 먼저 판정한다.
- apply 정책은 `dry-run`에는 적용하지 않는다.
- 거래일 장중 차단 메시지에 현재 시각과 허용 window를 함께 남겨 operator가 바로 이해할 수 있게 했다.
- Universe Selection은 `unknown_instrument`를 hard exclude로 취급한다.
  따라서 KOSDAQ 확장은 universe 예외 규칙이 아니라 instrument master 적재 품질 문제로 관리한다.
- sync pipeline은 같은 `symbol`에 대해
  `exchange_code='KRX'`, `market_segment='KOSPI|KOSDAQ'`,
  `index_memberships`를 일관되게 적재해야 하며,
  기존 `market_code='KRX'` legacy row와 신규 세그먼트 row를
  중복 생성하는 방식은 피해야 한다.
- 현재 canonical 저장 규칙은 다음과 같다.
    - 국내주식 master sync 입력이 `KOSPI` 또는 `KOSDAQ`여도
      저장 row의 `market_code`는 `KRX`로 수렴시킨다.
    - `KOSPI/KOSDAQ` 구분은 `market_segment` 정식 컬럼과
      `metadata.source_market_code`로 보존한다.
    - 즉 `(symbol, market_code)` unique key 기준으로는
      국내주식 1종목당 canonical row 1개를 유지한다.
    - index membership 변경 이력은
      `instrument_index_memberships.effective_from/effective_to`로 시계열 관리한다.
- 후속 리팩토링 검토:
    - 운영 가독성 측면에서
      `market_code='KOSPI'|'KOSDAQ'`, `exchange_code='KRX'` 모델이 더 직관적인지
      별도 migration 항목으로 재검토한다.
    - `KOSPI100`, `KOSDAQ50`, 실제 `KOSDAQ150`은
      KIS 기본종목정보 CSV 외 별도 지수 구성종목 원천으로 보강한다.

## 검증
- `pytest -q tests/scripts/test_sync_kis_instrument_master.py tests/scripts/test_seed_instrument_master.py tests/repositories/test_instruments.py`
  - `56 passed`
- `python3 -m py_compile scripts/sync_kis_instrument_master.py tests/scripts/test_sync_kis_instrument_master.py`
  - 통과

## 남은 작업
- `snapshot/event mapping과의 정합성 확보`
- KIS raw 종목정보파일 직접 parser 및 다운로드/보관 경로
- KOSPI/KOSDAQ master sync 운영 절차와 실행 이력 UI 연결
- UniverseSelectionService의 membership read를
  `instrument_index_memberships` 우선, `metadata.index_memberships` fallback으로
  전환하는 후속 read-path 정리
- 현재는 UniverseSelectionService가 위 read-path 전환을 사용 중이며,
  sell_guard는 이미 canonical symbol lookup을 사용한다.
  snapshot sync도 `get_by_symbol_any_market()` 기반 canonical lookup으로 전환되었다.
  다만 membership table 직접 참조는 아직 UniverseSelection 한정이며,
  sell_guard / snapshot sync는 symbol → canonical instrument lookup 계층을 유지한다.
- UniverseSelectionService의 allowlist 우선 경로를
  canonical instrument metadata 우선 경로로 점진 전환
