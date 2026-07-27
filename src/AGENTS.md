# src/AGENTS.md

## 적용 범위

이 지침은 `src/` 이하 백엔드 코드에 적용한다. 루트 `AGENTS.md`를 우선 따르고, 이 문서는 백엔드 런타임 변경 규칙을 보강한다.

## 백엔드 원칙

- 매매, 리스크, 주문 제출, 정합성, 스케줄러 경계는 명시적 근거와 테스트 없이 변경하지 않는다.
- 실패한 실제 경로를 먼저 고치고, 인증·재시도·브로커·DB 동작을 불필요하게 넓히지 않는다.
- REST-only 경로는 REST 인증만 사용한다.
- broker submit, post-submit sync, reconciliation, inspection 경계를 섞지 않는다.
- 운영 성공은 처리량, 스킵, 오류, 저장 레코드 같은 지표로 증명한다.

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
- 백엔드 런타임 조립, API factory, 설정 import를 건드린 경우 `bash scripts/harness/run.sh accept backend-runtime` 또는 `make accept-backend-runtime`을 사용한다.
- Python 명령은 `python3`를 사용한다.
- 셸 명령은 `bash`에서 실행한다.
- 단일 파일 문법 확인: `python3 -m py_compile <changed_file>`
- 대상 테스트: `python3 -m pytest <specific_test_file> -v`
- 단일 테스트: `python3 -m pytest <specific_test_file>::<test_name> -v`
- DB schema나 repository contract를 바꾸면 migration, repository test, API read path 영향을 함께 확인한다.

## 검증 부하 제한

- 이 Ubuntu 서버에서는 full test suite 실행을 기본 금지한다.
- 사용자 명시 승인 없이 `make test`, `python3 -m pytest`, `python3 -m pytest tests/`, `make docker-test`를 실행하지 않는다.
- smoke, slow, integration, broker, KIS, 외부 API 연동 테스트는 사용자 명시 승인 없이 실행하지 않는다.
- 네트워크, Docker, DB, KIS, 외부 API, 대량 데이터 파일을 사용하는 검증은 사용자 승인 없이 실행하지 않는다.
- 전체 테스트가 필요하다고 판단되면 직접 실행하지 말고 예상 부하, 필요한 이유, 대체 검증안을 먼저 보고한다.

## 금지 사항

- 테스트 통과만을 위해 risk gate, sell guard, submit-lane gate, reconciliation lock을 우회하지 않는다.
- 실패한 broker, KIS, DB 작업을 조용히 성공으로 바꾸지 않는다.
- 관련 없는 리팩터링을 끼워 넣지 않는다.
