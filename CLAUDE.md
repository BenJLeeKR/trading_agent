# CLAUDE.md

## 프로젝트 지침

Claude Code는 이 저장소에서 코드, 문서, 스크립트, 테스트를 변경하기 전에 적용 가능한 `AGENTS.md` 파일을 읽고 따라야 한다.

## 지침 파일

다음 순서로 읽는다.

1. `AGENTS.md`
   - 저장소 전역 Harness Engineering 규칙
   - 언어 원칙
   - 검증 정책과 검증 부하 제한
   - 트레이딩 안전 불변식
   - 문서화와 완료 보고 규칙

2. `src/AGENTS.md`
   - `src/` 이하 백엔드 코드를 변경할 때 적용
   - 런타임, 트레이딩 안전, 브로커, DB, 정합성, API 규칙
   - 백엔드 검증 부하 제한

3. `admin_ui/AGENTS.md`
   - `admin_ui/` 이하 프론트엔드 코드를 변경할 때 적용
   - 운영 UI, API contract, 상태 표시, 프론트엔드 검증 규칙
   - 프론트엔드 검증 부하 제한

## 운영 원칙

- 이 파일에는 세부 규칙을 중복 작성하지 않는다.
- 지침이 충돌하면 사용자 직접 지시가 없는 한 더 구체적인 하위 `AGENTS.md`를 따른다.
- `README.md`는 프로젝트 설치와 실행 안내로 사용하고, 에이전트 작업 규칙은 `AGENTS.md` 계열 파일을 기준으로 한다.

## 하네스 진입점

세부 판정 기준은 `AGENTS.md`와 `scripts/harness/run.sh`를 따른다. Claude Code는 검증 명령을 직접 조합하기보다 아래 진입점을 우선 사용한다.

- 문서 정합성: `bash scripts/harness/run.sh accept docs` 또는 `make accept-docs`
- 환경 재현성: `bash scripts/harness/run.sh accept env` 또는 `make accept-env`
- 단일 백엔드 파일: `bash scripts/harness/run.sh accept backend-file <file>` 또는 `make accept-backend-file FILE=<file>`
- 백엔드 런타임 계약: `bash scripts/harness/run.sh accept backend-runtime` 또는 `make accept-backend-runtime`
- Admin UI: `bash scripts/harness/run.sh accept frontend` 또는 `make accept-admin-ui`
- 운영 리포트: `bash scripts/harness/run.sh accept ops-report <summary_json>` 또는 `make accept-ops-report SUMMARY_JSON=<summary_json>`
