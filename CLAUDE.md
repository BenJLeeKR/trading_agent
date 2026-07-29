# CLAUDE.md

## 프로젝트 지침

Claude Code는 이 저장소에서 코드, 문서, 스크립트, 테스트를 변경하기 전에 적용 가능한 `AGENTS.md` 파일을 읽고 따라야 한다.

## 지침 파일

다음 순서로 읽는다.

1. `AGENTS.md`
   - 저장소 전역 Harness Engineering 규칙, 언어 원칙, 중국어 사용 금지, 보고 원칙

2. `src/AGENTS.md`
   - `src/` 이하 백엔드 전용 규칙

3. `admin_ui/AGENTS.md`
   - `admin_ui/` 이하 프론트엔드 전용 규칙

4. `scripts/harness/README.md`
   - 하네스 명령, 출력 지표, 승인 플래그 기준

5. `docs/20_harness_engineering/definition_of_done.md`
   - 완료 주장 최소 조건

6. `docs/20_harness_engineering/no_bypass_policy.md`
   - 우회 행동의 실패 조건과 검토 대상

7. `docs/20_harness_engineering/ai_friendly_error_message_contract.md`
   - 오류 메시지와 운영 로그 계약

## 운영 원칙

- 이 파일에는 세부 규칙을 중복 작성하지 않는다.
- 지침이 충돌하면 사용자 직접 지시가 없는 한 더 구체적인 하위 `AGENTS.md`를 따른다.
- `README.md`는 프로젝트 설치와 실행 안내로 사용하고, 에이전트 작업 규칙은 `AGENTS.md` 계열 파일을 기준으로 한다.

## 하네스 진입점

세부 명령 목록과 출력 지표는 `scripts/harness/README.md`를 따른다. 이 파일에는 개별 명령 목록을 중복 작성하지 않는다. Claude Code는 검증 명령을 직접 조합하지 말고, 적용 가능한 경우 `bash scripts/harness/run.sh ...` 또는 `Makefile` alias를 우선 사용한다.

완료 주장, 우회 행동, 오류 메시지, 배포/CI 계약은 `docs/20_harness_engineering/` 아래 문서를 기준으로 판정한다.
