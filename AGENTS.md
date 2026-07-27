# AGENTS.md

## 프로젝트 역할

이 저장소는 멀티 에이전트 트레이딩 시스템을 검증 가능한 형태로 운영하기 위한 Harness Engineering 프로젝트다.

에이전트는 이 코드베이스를 단순 애플리케이션이 아니라 실행 가능한 검증 하네스로 다뤄야 한다. 런타임 변경은 관측 가능한 계약, 결정론적 검증 경로, 그리고 실제로 기대한 매매·정합성·스케줄러·Inspection 동작이 수행됐다는 증거를 보존해야 한다.

## 언어 원칙

- 코드를 제외한 주석, 설명, 문서, 계획, 완료 보고, 분석 보고, 사용자 응답은 한국어로 작성한다.
- 코드 식별자, 명령어, 로그 원문, 에러 메시지, 외부 API 필드명, 설정 키, 파일 경로는 원문 그대로 유지할 수 있다.
- 기존 영어 코드 주석을 수정할 때도 의미를 바꾸지 않는 범위에서는 한국어로 전환한다.
- 외부 라이브러리나 표준 인터페이스와 직접 맞닿은 주석은 필요한 경우 영어를 유지할 수 있지만, 보고와 설명은 한국어로 정리한다.

## 핵심 작업 원칙

- 실제로 실패한 경로를 먼저 고친다. 인증, 재시도, 브로커, 스케줄러, DB 동작은 실패 경로가 요구하지 않는 한 넓히지 않는다.
- 표면적인 방어 코드보다 원인에 가까운 작은 수정을 우선한다.
- 매매 의미론, 리스크 정책, 주문 크기 산정, 주문 제출, 정합성 상태 전이는 명시적 근거와 검증 없이 바꾸지 않는다.
- 운영 커버리지가 중요한 작업에서는 exit code 0만으로 성공을 판단하지 않는다. 처리 건수, 스킵 건수, 오류 건수, 저장된 레코드 등 명시적 지표를 보고한다.
- 런타임 코드, 마이그레이션 동작, API 실행 모드, 문서 내용이 서로 어긋나지 않게 유지한다.
- `.env` 파일은 직접 수정하지 않는다. 환경변수 변경이 필요하면 `.env.example` 수정안 또는 사용자가 직접 적용할 변경 내용을 제시한다.
- `.env` 파일의 키값, 토큰, 비밀번호, 계좌 정보, API secret은 출력하거나 보고서에 노출하지 않는다.

## 저장소 구조

- `src/agent_trading/`: Python 애플리케이션 코드.
- `src/agent_trading/services/`: 의사결정, 리스크, 정합성, 브로커 연동, 스케줄러, 시그널 로직.
- `src/agent_trading/repositories/`: 저장소 계약과 구현.
- `src/agent_trading/api/`: FastAPI 기반 Inspection API.
- `scripts/`: 운영, 검증, 스모크 테스트 진입점.
- `tests/`: unit, integration, API, broker, repository, smoke 테스트.
- `db/migrations/`: PostgreSQL 스키마 마이그레이션.
- `docs/`: 아키텍처, 구현 계획, 런타임 분석, 인수인계 문서.
- `admin_ui/`: 운영 대시보드 UI.

## 검증 정책

변경한 동작을 증명할 수 있는 가장 좁은 검증을 우선 실행한다.

- 가능한 경우 검증 명령은 직접 조합하지 말고 `bash scripts/harness/run.sh <command>` 또는 대응하는 `make` target을 사용한다.
- 표준 실행기에 없는 새 검증 명령이 필요하면 임의 실행하지 말고 필요한 명령, 예상 부하, 대체 검증안을 먼저 보고한다.
- 문서 정합성의 정답 판정은 `bash scripts/harness/run.sh accept docs` 또는 `make accept-docs`를 사용한다.
- 운영 환경 재현성의 정답 판정은 `bash scripts/harness/run.sh accept env` 또는 `make accept-env`를 사용한다.
- 단일 백엔드 파일의 정답 판정은 `bash scripts/harness/run.sh accept backend-file <file>` 또는 `make accept-backend-file FILE=<file>`을 사용한다.
- Admin UI의 정답 판정은 `bash scripts/harness/run.sh accept frontend` 또는 `make accept-admin-ui`를 사용한다.
- 운영 리포트 `summary_json`의 정답 판정은 `bash scripts/harness/run.sh accept ops-report <summary_json>` 또는 `make accept-ops-report SUMMARY_JSON=<summary_json>`을 사용한다.
- 환경 재현성 확인은 `bash scripts/harness/run.sh env-check` 또는 `make env-check`를 사용한다.
- Ubuntu 서버 작업 영역에서는 `python` 명령을 사용하지 않는다. 검증과 실행은 `python3` 명령을 사용한다.
- 서버 환경 특성상 `sh`에서 실행하는 명령은 항상 실패하므로, 셸 명령은 `bash`에서 실행한다.
- Python 컴파일 확인: `python3 -m py_compile <changed_file>`
- 대상 테스트: `python3 -m pytest <specific_test_file> -v`
- Python 스타일 검증이 필요한 경우: `make lint`
- API in-memory 모드 확인: `make run-api-inmemory`
- API Postgres/Auth 모드 확인: `make run-api-postgres`
- Docker 마이그레이션 표준 경로: `docker compose run --rm migrate` 또는 `make docker-migrate`

API 컨테이너 시작이 DB 마이그레이션을 자동으로 수행한다고 가정하지 않는다.

## 검증 부하 제한

이 Ubuntu 서버에서는 full test suite 실행을 기본 금지한다. 이전 전체 테스트 실행에서 서버 네트워크 단절 수준의 부하가 발생했으므로, 에이전트는 사용자의 명시 승인 없이 전체 테스트, 장시간 테스트, 외부 연동 테스트를 실행하지 않는다.

- 사용자 명시 승인 없이 실행 금지:
  - `make test`
  - `python3 -m pytest`
  - `python3 -m pytest tests/`
  - `make docker-test`
  - `docker compose exec app python3 -m pytest tests/ -v`
  - `npm test`, `npm run test`, `npm run test:run`
  - 장시간 실행되는 smoke, slow, integration, broker, KIS, 외부 API 연동 테스트
- 기본 검증은 변경 파일에 직접 대응하는 가장 좁은 테스트로 제한한다.
- 전체 테스트가 필요하다고 판단되면 직접 실행하지 말고 예상 부하, 필요한 이유, 대체 검증안을 먼저 보고한다.
- 네트워크, Docker, DB, KIS, 외부 API, 대량 데이터 파일을 사용하는 검증은 사용자 승인 없이 실행하지 않는다.

## Harness Engineering 기대사항

런타임 또는 운영 변경에서는 다음 증거 경로를 보존하거나 추가한다.

- 가능한 경우 저장된 실행 레코드.
- 명시적인 처리·스킵·오류 카운트.
- decision ID, context ID, order ID, account ID, symbol 식별자.
- pre-submit 검증, submit, post-submit sync, reconciliation, inspection 경계의 분리.
- 테스트, 로그, 요약 파일, DB 상태 중 하나 이상으로 확인 가능한 실패 모드.

## 트레이딩 안전 불변식

- 테스트를 통과시키기 위해 risk gate, sell guard, submit-lane gate, reconciliation lock, broker contract check를 우회하지 않는다.
- 실패한 브로커, KIS, DB, 스케줄러 작업을 조용히 성공으로 변환하지 않는다.
- REST-only 경로는 REST 인증만 사용한다. 해당 경로가 요구하지 않는 한 WebSocket 또는 전체 브로커 인증을 추가하지 않는다.
- account lookup, held-position 처리, reconciliation, post-submit sync는 관측 가능하고 테스트 가능해야 한다.

## 문서화 규칙

- 문서 유지보수 작업에서는 저장소의 canonical 문서를 업데이트한다.
- 기존 분석 이력은 보존하되, 현재 결론이 바뀌면 날짜가 포함된 `최신 종합 결론` 섹션을 추가한다.
- 분석 문서에서는 측정 결과와 가설을 구분한다.
- 운영 보고에서는 단순히 “OK”라고 쓰지 말고 실제 처리량과 커버리지 지표를 포함한다.

## 프롬프트 및 계획 리뷰 규칙

설계안이나 구현 계획 리뷰를 요청받으면, 사용자가 구현을 명시하지 않는 한 기본 산출물은 재사용 가능한 프롬프트다.

- 하나의 승인 프롬프트로 정리한다.
- 다음 섹션을 포함한다.
  - `추가 보정사항`
  - `그 외 유지해야할 원칙`
  - `완료 후 보고에 대한 가이드`
- 구현 완료 보고가 주어지면 다음 추천 구현 프롬프트를 생성한다.
- 오래된 프로젝트 제목 접두사는 프롬프트에 붙이지 않는다.

## 코드 스타일

- 새 추상화를 도입하기 전에 기존 패턴을 우선 따른다.
- 축약어보다 명시적인 이름을 선호한다.
- 국소 버그를 고치기 위해 광범위한 프레임워크 변경을 추가하지 않는다.
- 비자명한 런타임 제약을 설명할 때만 주석을 추가한다.
- 관련 없는 파일을 수정하거나 별도 결함을 기회주의적으로 고치지 않는다.

## 완료 보고 규칙

작업 완료 보고에는 다음 내용을 포함한다.

- 변경한 파일.
- 실행한 검증 명령과 결과.
- 검증하지 못한 가정.
- 운영 작업인 경우, 기대한 작업이 실제로 수행됐는지 보여주는 구체적 지표.
