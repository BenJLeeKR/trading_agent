# Agent Workspace Guide

## 문서 목적

이 문서는 `/workspace/agent_trading/` 프로젝트에서 AI 코딩 에이전트가 작업할 때 참고하는 작업 방식 안내서다.

실제 강제 규칙은 루트 [`AGENTS.md`](../../AGENTS.md)를 기준으로 한다. 이 문서는 README에서 분리한 작업 원칙, 문서 배치 기준, Harness Engineering 관점을 장기 인수인계용으로 정리한다.

## 지침 우선순위

1. 시스템/사용자 직접 지시
2. 루트 [`AGENTS.md`](../../AGENTS.md)
3. 루트 [`CLAUDE.md`](../../CLAUDE.md)
4. 프로젝트 [`README.md`](../../README.md)
5. 이 문서

## 기본 경로

- 프로젝트 기본 경로는 `/workspace/agent_trading/`다.
- 상대 경로는 별도 지시가 없으면 프로젝트 루트를 기준으로 해석한다.
- 프로젝트 외부의 `/workspace` 상위 경로는 백업, 데이터베이스 볼륨, 인프라 보조 디렉터리를 포함할 수 있으므로 프로젝트 문서 경로로 간주하지 않는다.

## 문서 역할 분리

- [`README.md`](../../README.md): 설치, 실행, Docker, API, 환경변수, Make 명령 등 프로젝트 사용 안내.
- [`AGENTS.md`](../../AGENTS.md): Codex 및 공통 에이전트가 반드시 따라야 하는 작업 규칙.
- [`CLAUDE.md`](../../CLAUDE.md): Claude Code가 `AGENTS.md`를 읽도록 안내하는 얇은 라우터.
- `docs/00_foundational_design/`: 시스템 원형 설계와 에이전트 책임 경계.
- `docs/01_architecture_milestones/`: 구현 마일스톤과 후속 수정 계획.
- `docs/02_agent_pipeline/`: AI agent, decision pipeline, prompt/provider 흐름.
- `docs/03_execution_order/`: 주문 실행과 broker boundary.
- `docs/05_reconciliation_snapshot/`: reconciliation과 snapshot sync.
- `docs/07_scheduler_ops/`: 스케줄러와 운영 자동화.
- `docs/08_admin_ui_dashboard/`: Admin UI와 운영 대시보드.
- `docs/09_paper_trading_validation/`: paper trading 검증.
- `docs/10_signal_research_sppv/`: 시그널 리서치와 분석 문서.
- `docs/99_meta_handover/`: 인수인계, 백로그, 문서 운영 원칙.

## Harness Engineering 목적

이 프로젝트의 Harness Engineering 목적은 매매 시스템을 “실행 가능한 검증 하네스”로 유지하는 것이다.

핵심은 다음 세 가지다.

1. 입력, 상태 전이, 출력, 실패 조건이 관측 가능해야 한다.
2. 매매·리스크·주문·정합성 경계가 테스트와 로그로 검증 가능해야 한다.
3. 운영 성공은 exit code가 아니라 처리량, 저장 레코드, 상태 변화, 오류 카운트 같은 증거로 보고해야 한다.

## 기본 작업 규칙

- 작업 전 루트 지침 파일을 확인한다.
- 코드 변경은 최소 범위로 수행한다.
- 검증 가능한 변경을 선호한다.
- 사용자가 요청하지 않은 커밋, 브랜치 생성, 배포는 하지 않는다.
- 비밀값, 토큰, `.env` 내용은 출력하지 않는다.
- `.env` 파일은 직접 수정하지 않는다. 환경변수 변경이 필요하면 `.env.example` 수정안 또는 사용자가 직접 적용할 변경 내용을 제시한다.
- `.env` 파일의 키값, 토큰, 비밀번호, 계좌 정보, API secret은 출력하거나 보고서에 노출하지 않는다.

## 언어 원칙

- 코드 자체를 제외한 주석, 설명, 문서, 계획, 완료 보고, 분석 보고, 사용자 응답은 한국어로 작성한다.
- 코드 식별자, 명령어, 로그 원문, 에러 메시지, 외부 API 필드명, 설정 키, 파일 경로는 원문 그대로 유지할 수 있다.

## 실행 원칙

- Ubuntu 서버 작업 영역에서는 `python` 대신 `python3`를 사용한다.
- 서버 환경 특성상 `sh` 실행은 실패하므로 셸 명령은 `bash`에서 실행한다.
- 환경 재현성 확인은 `bash scripts/harness/run.sh env-check` 또는 `make env-check`를 사용한다.
- 문서 정합성의 정답 판정은 `bash scripts/harness/run.sh accept docs` 또는 `make accept-docs`를 사용한다.
- 운영 환경 재현성의 정답 판정은 `bash scripts/harness/run.sh accept env` 또는 `make accept-env`를 사용한다.
- 단일 백엔드 파일의 정답 판정은 `bash scripts/harness/run.sh accept backend-file <file>` 또는 `make accept-backend-file FILE=<file>`을 사용한다.
- Admin UI의 정답 판정은 `bash scripts/harness/run.sh accept frontend` 또는 `make accept-admin-ui`를 사용한다.
- 운영 리포트 `summary_json`의 정답 판정은 `bash scripts/harness/run.sh accept ops-report <summary_json>` 또는 `make accept-ops-report SUMMARY_JSON=<summary_json>`을 사용한다.
- Python, Node.js, npm, PostgreSQL 기준 버전은 각각 `.python-version`, `admin_ui/.nvmrc`, `admin_ui/.npm-version`, `.postgres-version`에 고정한다.
- Python 패키지는 `requirements.lock`, Admin UI 패키지는 `package-lock.json`과 `npm ci`를 기준으로 재현한다.

## 테스트 데이터 원칙

- 테스트 입력 데이터는 `tests/fixtures/` 아래에 고정한다.
- mutable한 `data/`, `logs/`, `tmp/`의 현재 파일을 테스트 기대값으로 직접 사용하지 않는다.
- DB 테스트는 migration, deterministic seed, cleanup 순서를 명시적으로 가져야 한다.

## README 유지 원칙

README에는 프로젝트 실행에 필요한 최신 정보만 남긴다.

- 남길 내용: 요구사항, 빠른 시작, Docker, Inspection API, 프로젝트 구조 요약, 환경변수, Make 명령, 핵심 설계 문서 링크.
- 분리할 내용: 에이전트 작업 규칙, 장기 작업 방식, 계획 리뷰 규칙, 오래된 다음 단계, 세부 설계 본문.
- 오래된 상세 설명은 삭제하지 않고 적절한 `docs/` 하위 문서로 이동하거나 링크로 대체한다.

## 완료 보고 원칙

작업 완료 보고에는 다음을 포함한다.

- 변경한 파일.
- 실행한 검증 명령과 결과.
- 검증하지 못한 가정.
- 운영 작업인 경우 기대한 작업이 실제로 수행됐는지 보여주는 구체적 지표.
