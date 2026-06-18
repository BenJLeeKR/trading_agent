# KIS Instrument Master Update Policy

## 목적
- `trading.instruments`를 갱신하는 경로가 장중에 무분별하게 apply되지 않도록 운영 정책을 코드로 고정한다.
- `instrument master 갱신 정책`을 단순 문서가 아니라 실제 스크립트 가드로 반영한다.
- `instrument master`에 없는 종목은 Universe Selection 단계에서 `unknown_instrument`로 제외되므로,
  KOSDAQ 종목을 판단/주문 대상으로 편입하려면 먼저 KIS 종목정보파일 기반 sync로
  해당 종목의 master row를 적재해야 한다.

## 반영 내용
- 대상 스크립트:
  - [scripts/sync_kis_instrument_master.py](/workspace/agent_trading/scripts/sync_kis_instrument_master.py)
- 시장 확장 원칙:
  - `KOSDAQ` 편입은 `decision loop`의 예외 허용으로 해결하지 않는다.
  - 먼저 `trading.instruments`에 `market_code=KOSDAQ` 종목 master를 sync한다.
  - 그 다음 Universe Selection / signal feature batch가 해당 master를 authoritative source로 사용한다.
  - 즉, `master sync → universe 편입 → decision loop` 순서를 깨지 않는다.
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
