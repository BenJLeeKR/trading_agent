# Definition of Done

## 문서 목적

이 문서는 AI 에이전트가 이 저장소에서 작업을 “완료”했다고 주장할 수 있는 최소 조건을 정의한다.

DoD는 완벽한 품질 보증이 아니라 완료 주장에 필요한 증거 기준이다. 에이전트는 아래 조건을 만족하지 못한 경우 완료라고 단정하지 않고, 미충족 조건과 다음 조치를 보고해야 한다.

## 공통 완료 조건

모든 작업은 다음 조건을 만족해야 한다.

- 요청 범위와 실제 변경 파일이 일치한다.
- 관련 없는 파일, 산출물, 캐시, 로그, 데이터 파일을 함께 수정하거나 커밋하지 않는다.
- Git 상태를 확인하고, 현재 기준 브랜치, `HEAD`, 원격 추적 브랜치와의 동기화 여부를 혼동 없이 보고한다.
- 브랜치 보호 규칙이나 PR 필수 규칙이 있는 저장소에서는 로컬 커밋만으로 완료를 주장하지 않고, 브랜치/PR/check/merge 상태를 함께 보고한다.
- 변경한 동작을 증명할 수 있는 가장 좁은 하네스 명령을 실행한다.
- 실행하지 못한 검증은 `검증하지 못한 가정`으로 분리하고, 미실행 사유를 카운트나 조건으로 보고한다.
- `.env` 파일을 직접 수정하지 않고, `.env` 값과 secret 후보를 출력하지 않는다.
- 사용자 승인 없이 full test 또는 `full_test` 계층, heavy 검증, DB 쓰기, 마이그레이션, 외부 API 호출, 운영 덤프를 실행하지 않는다.
- 완료 보고에는 변경 파일 수, 검증 명령, 실패·스킵·미실행 카운트, 남은 위험을 포함한다.
- 이번 작업과 무관한 미추적 파일이 있으면 삭제·커밋하지 않고, 존재 사실과 작업 무관 여부만 분리해서 보고한다.

## 작업 유형별 완료 조건

### 문서 변경

- 상대 링크가 깨지지 않는다.
- canonical 문서를 직접 갱신한다.
- 문서가 안내하는 `make` target 또는 하네스 명령이 실제로 존재한다.
- `bash scripts/harness/run.sh accept docs`를 실행하거나, 실행하지 못한 사유를 보고한다.

### 하네스와 CI 변경

- 사람, AI, CI가 같은 `bash scripts/harness/run.sh ...` 진입점을 사용한다.
- CI workflow가 `pytest`, `ruff`, `npm test`, `tsc`, `vitest` 같은 정답 판정기를 직접 중복 정의하지 않는다.
- `Safe harness contracts` required check와 `Require Harness on main` ruleset 계약이 문서와 하네스 검사에 반영된다.
- `bash scripts/harness/run.sh accept ci`를 실행하거나, 실행하지 못한 사유를 보고한다.

### 백엔드 코드 변경

- 변경 파일에 대해 `bash scripts/harness/run.sh accept backend-file <file>`을 우선 실행한다.
- 직접 대응 테스트가 없으면 완료로 단정하지 않고, 테스트 추가 또는 `HARNESS_ALLOW_NO_TEST=1` 명시 우회 사유를 보고한다.
- 런타임 계약을 바꾼 경우 `bash scripts/harness/run.sh accept backend-runtime` 결과를 보고한다.
- 매매 의미론, 리스크 정책, 주문 제출, 정합성 전이는 명시적 검증 없이 바꾸지 않는다.

### Admin UI 변경

- `bash scripts/harness/run.sh accept frontend`를 실행하거나, 실행하지 못한 사유를 보고한다.
- 전체 빌드나 전체 테스트는 사용자 승인 없이 실행하지 않는다.
- loading, empty, error, stale 상태 표시가 깨지지 않았는지 변경 범위 안에서 확인한다.

### 운영 리포트와 스케줄러 변경

- exit code만으로 완료를 주장하지 않는다.
- 처리 건수, 스킵 건수, 실패 건수, timeout 건수, 저장 레코드 수를 보고한다.
- `summary_json`을 변경하거나 검증할 때는 `bash scripts/harness/run.sh accept ops-report <summary_json>`를 사용한다.
- DB 덤프가 필요하면 `HARNESS_ALLOW_OPS_DUMP=1` 승인 조건을 명시한다.

### read-only 분석 / 검증 턴

- 코드나 문서를 수정하지 않았더라도, 조회한 데이터 범위와 사용한 read-only 명령을 보고한다.
- 변경 파일이 0개인 경우에도 완료를 주장할 수 있지만, 이때는 "무엇을 확인했고 무엇은 아직 확인하지 못했는지"를 분리해서 적는다.
- 조회 결과로 기존 문서나 보고의 정정이 필요하다고 판단되면, 이번 턴에 수정하지 않은 이유 또는 다음 턴 조치를 함께 남긴다.

## 완료라고 말할 수 없는 경우

다음 경우에는 작업을 완료로 단정하지 않는다.

- 실패한 검증이 남아 있다.
- 검증 명령을 실행하지 않았는데 미실행 사유를 보고하지 않았다.
- 테스트 통과를 위해 risk gate, sell guard, submit-lane gate, reconciliation lock, broker contract check를 우회했다.
- `.env` 값, token, 계좌 정보, API secret을 출력했다.
- 사용자 승인 없이 full test, 외부 API, DB 쓰기, 마이그레이션, 운영 덤프를 실행했다.
- 작업 범위 밖 파일을 함께 커밋하거나 PR에 포함했다.
- `docs/80_harness_engineering/no_bypass_policy.md`의 `Hard Fail`에 해당하는 우회 행동이 남아 있다.

## 완료 보고 형식

완료 보고는 다음 항목을 포함한다.

1. 변경한 파일 목록.
2. 실제 카운트.
3. 테스트 결과.
4. 검증하지 못한 가정.
5. 검증에 대한 해석(이해하기 쉽게)
6. 현재 기준 브랜치와 커밋 상태(`HEAD`, `origin/<branch>` 또는 PR/check 상태).
7. 다음 우선순위 작업 또는 닫기 가능 여부.

“OK”, “정상 동작 확인” 같은 표현만으로 완료를 설명하지 않는다. 가능한 경우 하네스 출력의 `*_count`, `*_run`, `failed_step_count`, `route_count`, `test_file_count` 원문 지표를 함께 제시한다.
