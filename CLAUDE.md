# CLAUDE.md

## 목적

Claude Code는 이 저장소에서 작업을 시작하기 전에, 현재 작업 경로에 적용되는 지침 문서를 먼저 읽고 따라야 한다.

## 필수 읽기 순서

1. `AGENTS.md`
   - 저장소 전역 Harness Engineering 규칙
   - 언어 원칙
   - 검증 정책
   - 보고 원칙

2. 작업 대상 경로별 추가 지침
   - `src/AGENTS.md`
   - `admin_ui/AGENTS.md`

3. `scripts/harness/README.md`
   - 하네스 표준 명령
   - 승인 플래그
   - 출력 지표 기준

4. `docs/80_harness_engineering/`
   - `definition_of_done.md`
   - `no_bypass_policy.md`
   - `ai_friendly_error_message_contract.md`
   - 배포/CI 관련 canonical 문서

## 언어 원칙

- 코드를 제외한 주석, 설명, 보고, 문서, 사용자 응답은 한국어로 작성한다.
- 사용자 보고, 문서, 설명, 완료 보고에서는 `diff`를 단독 용어로 쓰지 않고 `변경분`, `변경 차이`, `전후 차이`, `수정 내역` 같은 한국어 용어를 사용한다.
- `git diff` 같은 명령명이나 patch/diff 포맷 자체를 가리킬 때만 `diff`를 backtick으로 유지하고, 가능하면 같은 문장에 한국어 설명을 붙인다.
- 중국어 사용 금지 및 일본어 사용 금지 원칙은 `AGENTS.md`를 따른다.

## 필수 작업 원칙

- 세부 규칙은 이 파일에 중복 작성하지 않는다.
- 세부 명령 목록과 출력 지표 기준은 `scripts/harness/README.md`를 따른다.
- 검증 명령은 직접 조합하지 말고, 가능한 경우 `bash scripts/harness/run.sh ...` 또는 `make` alias를 우선 사용한다.
- Ubuntu 서버 작업에서는 `python` 대신 `python3`, `sh` 대신 `bash`를 사용한다.
- `.env` 파일은 직접 수정하지 않는다.
- 완료 주장 전에는 `docs/80_harness_engineering/definition_of_done.md` 기준을 확인한다.

## 우선순위

- 사용자 직접 지시
- 더 구체적인 하위 `AGENTS.md`
- 루트 `AGENTS.md`
- `scripts/harness/README.md`
- `docs/80_harness_engineering/` 문서
- 이 파일
