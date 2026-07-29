# AGENTS.md

## 프로젝트 역할

이 저장소는 멀티 에이전트 트레이딩 시스템을 검증 가능한 형태로 운영하기 위한 Harness Engineering 프로젝트다. 에이전트는 이 코드베이스를 단순 애플리케이션이 아니라 실행 가능한 검증 하네스로 다뤄야 한다.

상세 작업 방식은 다음 문서로 분리한다.

- [`docs/99_meta_handover/agent_workspace_guide.md`](docs/99_meta_handover/agent_workspace_guide.md): 작업 원칙, 문서 역할, 테스트 데이터, 계획 리뷰 규칙.
- [`docs/20_harness_engineering/definition_of_done.md`](docs/20_harness_engineering/definition_of_done.md): AI가 완료를 주장할 수 있는 최소 조건.
- [`scripts/harness/README.md`](scripts/harness/README.md): `scripts/harness/run.sh` 진입점, 승인 플래그, 출력 지표.
- [`src/AGENTS.md`](src/AGENTS.md): 백엔드 런타임 전용 규칙.
- [`admin_ui/AGENTS.md`](admin_ui/AGENTS.md): Admin UI 전용 규칙.

## 언어 원칙

- 코드를 제외한 주석, 설명, 문서, 계획, 완료 보고, 분석 보고, 사용자 응답은 한국어로 작성한다.
- 문서, 보고, 설명, 사용자 응답에는 중국어를 사용하지 않는다.
- 코드 식별자, 명령어, 로그 원문, 에러 메시지, 외부 API 필드명, 설정 키, 파일 경로는 원문 그대로 유지할 수 있다.
- 기존 영어 코드 주석을 수정할 때도 의미를 바꾸지 않는 범위에서는 한국어로 전환한다.

## 핵심 작업 원칙

- 실제로 실패한 경로를 먼저 고치고, 실패 경로가 요구하지 않는 인증·재시도·브로커·DB 동작을 넓히지 않는다.
- 표면적인 방어 코드보다 원인에 가까운 작은 수정을 우선한다.
- 매매 의미론, 리스크 정책, 주문 크기 산정, 주문 제출, 정합성 상태 전이는 명시적 근거와 검증 없이 바꾸지 않는다.
- 런타임 코드, 마이그레이션 동작, API 실행 모드, 문서 내용이 서로 어긋나지 않게 유지한다.
- 코드나 문서를 수정하지 않는 read-only 분석 턴이라도, 조회 범위·사용한 명령·미확인 사항을 분리해서 보고한다.
- `.env` 파일은 직접 수정하지 않는다. 환경변수 변경이 필요하면 `.env.example` 수정안 또는 사용자가 직접 적용할 변경 내용을 제시한다.
- `.env` 파일의 키값, 토큰, 비밀번호, 계좌 정보, API secret은 출력하거나 보고서에 노출하지 않는다.
- 토큰, 인증 정보, secret 후보가 포함될 수 있는 원격 URL, 명령 출력, 로그 조각은 그대로 보고하지 않는다.

## 검증 정책

변경한 동작을 증명할 수 있는 가장 좁은 검증을 우선 실행한다. 가능한 경우 명령은 직접 조합하지 말고 `bash scripts/harness/run.sh <command>` 또는 대응하는 `make` target을 사용한다.

- 검증 계층과 출력 지표 기준은 [`scripts/harness/README.md`](scripts/harness/README.md)를 따른다.
- CI도 사람·AI와 같은 `bash scripts/harness/run.sh ...` 진입점을 사용하며, GitHub Actions 기준은 `.github/workflows/harness.yml`에 둔다.
- 커밋 전 빠른 스냅샷: `bash scripts/harness/run.sh check quick` 또는 `make check-quick`.
- CI safe 등가 로컬 스냅샷: `bash scripts/harness/run.sh check full` 또는 `make check-full`.
- 변경 백엔드 파일 스냅샷: `bash scripts/harness/run.sh check changed` 또는 `make check-changed`.
- 타입 검사 스냅샷: `bash scripts/harness/run.sh type-check backend`, `bash scripts/harness/run.sh type-check frontend`, `make type-check-backend`, `make type-check-frontend`.
- read-only 보안 스냅샷: `bash scripts/harness/run.sh security scan` 또는 `make security-scan`.
- 문서 정합성: `bash scripts/harness/run.sh accept docs` 또는 `make accept-docs`.
- CI 정합성: `bash scripts/harness/run.sh accept ci` 또는 `make accept-ci`.
- 운영 환경 재현성: `bash scripts/harness/run.sh accept env` 또는 `make accept-env`. `env-check`는 호환 alias다.
- DB 저장소 구조: `bash scripts/harness/run.sh accept db-structure` 또는 `make accept-db-structure`.
- 아키텍처 계층 구조: `bash scripts/harness/run.sh accept architecture` 또는 `make accept-architecture`.
- 코드 스타일 baseline: `bash scripts/harness/run.sh accept style` 또는 `make accept-style`.
- 우회 행동 검사: `bash scripts/harness/run.sh accept no-bypass` 또는 `make accept-no-bypass`.
- 단일 백엔드 파일: `bash scripts/harness/run.sh accept backend-file <file>` 또는 `make accept-backend-file FILE=<file>`.
- 백엔드 런타임 계약: `bash scripts/harness/run.sh accept backend-runtime` 또는 `make accept-backend-runtime`.
- Admin UI 계약: `bash scripts/harness/run.sh accept frontend` 또는 `make accept-admin-ui`.
- 운영 리포트 JSON: `bash scripts/harness/run.sh accept ops-report <summary_json>` 또는 `make accept-ops-report SUMMARY_JSON=<summary_json>`.
- API 실행: `bash scripts/harness/run.sh run api-inmemory`, `bash scripts/harness/run.sh run api-postgres`, `make run-api-inmemory`, `make run-api-postgres`.

`accept backend-file`에서 직접 대응 테스트가 없으면 실패로 본다. 불가피한 경우에만 `HARNESS_ALLOW_NO_TEST=1`로 명시 우회하고 보고서에 이유를 남긴다.

운영 리포트 덤프는 DB를 조회하므로 `HARNESS_ALLOW_OPS_DUMP=1 bash scripts/harness/run.sh dump ops-report [YYYY-MM-DD]` 또는 `HARNESS_ALLOW_OPS_DUMP=1 make dump-ops-report DATE=<YYYY-MM-DD>`로만 실행한다.

Ubuntu 서버 작업 영역에서는 `python` 명령을 사용하지 않고 `python3`를 사용한다. 서버 환경 특성상 `sh` 실행은 실패하므로 셸 명령은 `bash`에서 실행한다.

## 검증 부하 제한

이 Ubuntu 서버에서는 full test suite 실행을 기본 금지한다. 이전 전체 테스트 실행에서 서버 네트워크 단절 수준의 부하가 발생했으므로, 사용자 명시 승인 없이 전체 테스트, 장시간 테스트, 외부 연동 테스트를 실행하지 않는다.

- 사용자 명시 승인 없이 금지: `make test`, `python3 -m pytest`, `python3 -m pytest tests/`, `make docker-test`, `docker compose exec app python3 -m pytest tests/ -v`, `npm test`, `npm run test`, `npm run test:run`, smoke/slow/integration/broker/KIS/외부 API 연동 테스트.
- L4/L5 무거운 계층의 상세 분류와 보고 카운트는 `scripts/harness/README.md`의 기준을 따른다.
- 예외: 하네스가 제공하는 `accept`, `env-check`, `py-compile`, `test-one`, `test-file`, `lint-path`, `admin-test-one` 진입점은 승인 없이 실행할 수 있다.
- 위 예외는 이미 실행 중인 컨테이너에 대한 짧은 `docker exec`, 버전 확인용 `docker run --rm node:20-slim`, 단일 테스트 selector 실행에만 적용한다.
- 새 서비스 기동, 장시간 컨테이너 실행, 전체 테스트/전체 빌드, 외부 API 호출, DB 쓰기/마이그레이션, 운영 덤프는 계속 명시 승인 대상이다.

## 트레이딩 안전 불변식

- 테스트를 통과시키기 위해 risk gate, sell guard, submit-lane gate, reconciliation lock, broker contract check를 우회하지 않는다.
- 우회 행동 금지 기준은 `docs/20_harness_engineering/no_bypass_policy.md`를 따른다. 명확한 안전 위반은 실패로 보고, 맥락 판단이 필요한 항목은 검토 대상으로 카운트한다.
- 실패한 브로커, KIS, DB, 스케줄러 작업을 조용히 성공으로 변환하지 않는다.
- REST-only 경로는 REST 인증만 사용한다. 해당 경로가 요구하지 않는 한 WebSocket 또는 전체 브로커 인증을 추가하지 않는다.
- account lookup, held-position 처리, reconciliation, post-submit sync는 관측 가능하고 테스트 가능해야 한다.

## 보고 원칙

- 운영 커버리지가 중요한 작업에서는 exit code 0만으로 성공을 판단하지 않는다.
- AI가 완료를 주장할 수 있는 조건은 `docs/20_harness_engineering/definition_of_done.md`를 따른다.
- 오류 메시지, API 오류 응답, 운영 로그를 보강할 때는 `docs/20_harness_engineering/ai_friendly_error_message_contract.md`를 따른다.
- 완료 보고에는 변경한 파일, 실행한 검증 명령, 검증하지 못한 가정, 실제 처리·스킵·오류·테스트 카운트를 포함한다.
- 브랜치 보호 규칙이 있는 저장소에서는 완료 보고에 현재 브랜치, `HEAD`, 원격 추적 브랜치 상태, PR/check 상태를 포함한다.
- 운영 보고에서는 단순히 “OK”라고 쓰지 말고 실제 처리량과 커버리지 지표를 포함한다.
