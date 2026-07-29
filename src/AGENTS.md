# src/AGENTS.md

## 적용 범위

이 지침은 `src/` 이하 백엔드 코드에 적용한다. 루트 `AGENTS.md`를 우선 따르고, 이 문서는 백엔드 런타임 변경 규칙을 보강한다.

## 백엔드 원칙

- 매매, 리스크, 주문 제출, 정합성, 스케줄러 경계는 명시적 근거와 테스트 없이 변경하지 않는다.
- 실패한 실제 경로를 먼저 고치고, 인증·재시도·브로커·DB 동작을 불필요하게 넓히지 않는다.
- REST-only 경로는 REST 인증만 사용한다.
- broker submit, post-submit sync, reconciliation, inspection 경계를 섞지 않는다.
- 운영 성공은 처리량, 스킵, 오류, 저장 레코드 같은 지표로 증명한다.
- 코드를 제외한 주석, 설명, 문서, 보고에는 한국어를 사용하고 중국어를 사용하지 않는다.
- 코드 수정이 없는 read-only 분석 턴이라도, 어떤 DB/로그/코드 경로를 확인했고 무엇이 아직 미확인인지 분리해서 보고한다.
- 토큰, 인증 정보, secret 후보가 포함될 수 있는 원격 URL, 명령 출력, 로그 조각은 그대로 보고하지 않는다.

## 주요 경로

- `agent_trading/services/`: 의사결정, 리스크, 주문, 정합성, 스케줄러 로직.
- `agent_trading/repositories/`: 저장소 계약과 구현.
- `agent_trading/brokers/`: 외부 브로커, KIS, 데이터 소스 경계.
- `agent_trading/api/`: Inspection API.
- `agent_trading/db/`: DB 연결, 트랜잭션, 마이그레이션 실행.
- `agent_trading/runtime/`: 런타임 조립과 의존성 wiring.

## 검증

- 가능한 경우 백엔드 검증은 `bash scripts/harness/run.sh <command>` 또는 대응하는 `make` target으로 실행한다.
- 단일 백엔드 파일의 정답 판정은 `bash scripts/harness/run.sh accept backend-file <file>` 또는 `make accept-backend-file FILE=<file>`을 사용한다.
- 직접 대응 테스트가 없는 백엔드 파일은 기본 실패로 판정한다. 테스트 추가가 불가능한 경우에만 `HARNESS_ALLOW_NO_TEST=1`로 명시 우회하고 이유를 보고한다.
- 백엔드 런타임 조립, API factory, 설정 import를 건드린 경우 `bash scripts/harness/run.sh accept backend-runtime` 또는 `make accept-backend-runtime`을 사용한다.
- DB schema, migration, repository contract, repository 구현, repository container wiring을 건드린 경우 `bash scripts/harness/run.sh accept db-structure` 또는 `make accept-db-structure`를 사용한다.
- backend 계층 import 경계를 건드린 경우 `bash scripts/harness/run.sh accept architecture` 또는 `make accept-architecture`를 사용한다.
- 백엔드 코드 스타일 baseline을 확인할 때 `bash scripts/harness/run.sh accept style` 또는 `make accept-style`을 사용한다.
- Python 명령은 `python3`를 사용한다.
- 셸 명령은 `bash`에서 실행한다.
- 단일 파일 문법 확인: `python3 -m py_compile <changed_file>`
- 대상 테스트: `bash scripts/harness/run.sh test-file <tests/path.py>`
- 단일 테스트: `bash scripts/harness/run.sh test-one <selector>`
- DB schema나 repository contract를 바꾸면 migration, repository test, API read path 영향을 함께 확인한다.

## 검증 부하 제한

- 이 Ubuntu 서버에서는 full test suite 실행을 기본 금지한다.
- 사용자 명시 승인 없이 `make test`, `python3 -m pytest`, `python3 -m pytest tests/`, `make docker-test`를 실행하지 않는다.
- smoke, slow, integration, broker, KIS, 외부 API 연동 테스트는 사용자 명시 승인 없이 실행하지 않는다.
- 네트워크, Docker, DB, KIS, 외부 API, 대량 데이터 파일을 사용하는 검증은 사용자 승인 없이 실행하지 않는다.
- 예외: 하네스가 제공하는 `accept backend-file`, `accept backend-runtime`, `py-compile`, `test-one`, `test-file`, `lint-path`는 승인 없이 실행할 수 있다.
- 위 예외는 이미 실행 중인 컨테이너에 대한 짧은 `docker exec`와 단일 테스트 selector에만 적용한다.
- 새 서비스 기동, 장시간 컨테이너 실행, 전체 테스트, 외부 API 호출, DB 쓰기/마이그레이션은 계속 명시 승인 대상이다.
- 전체 테스트가 필요하다고 판단되면 직접 실행하지 말고 예상 부하, 필요한 이유, 대체 검증안을 먼저 보고한다.

## 금지 사항

- 테스트 통과만을 위해 risk gate, sell guard, submit-lane gate, reconciliation lock을 우회하지 않는다.
- 실패한 broker, KIS, DB 작업을 조용히 성공으로 바꾸지 않는다.
- 관련 없는 리팩터링을 끼워 넣지 않는다.
- 브랜치 보호 규칙이 있는 저장소에서 로컬 커밋만으로 완료를 주장하지 않는다. 필요한 경우 PR/check 상태를 함께 보고한다.
