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
- `.claude/worktrees/` 아래 경로는 Claude Code의 그림자 작업 사본일 수 있으므로 canonical 프로젝트 경로로 간주하지 않는다.
- 코드 검색, 변경 파일 산출, 문서 정합성 점검에서는 별도 지시가 없으면 `.claude/` 경로를 제외한다.

## 문서 역할 분리

- [`README.md`](../../README.md): 설치, 실행, Docker, API, 환경변수, Make 명령 등 프로젝트 사용 안내.
- [`AGENTS.md`](../../AGENTS.md): Codex 및 공통 에이전트가 반드시 따라야 하는 작업 규칙.
- [`CLAUDE.md`](../../CLAUDE.md): Claude Code가 `AGENTS.md`를 읽도록 안내하는 얇은 라우터.
- [`scripts/harness/README.md`](../../scripts/harness/README.md): 하네스 실행기, 승인 플래그, accept 출력 지표 안내.
- [`docs/80_harness_engineering/`](../80_harness_engineering/): Harness Engineering 규칙, DoD, 우회 금지, 오류 메시지 계약.
- [`definition_of_done.md`](../80_harness_engineering/definition_of_done.md): AI가 완료를 주장할 수 있는 최소 조건.
- [`ai_friendly_error_message_contract.md`](../80_harness_engineering/ai_friendly_error_message_contract.md): AI가 진단 가능한 오류 메시지, API 오류 응답, 운영 로그 계약.
- `docs/00_foundational_design/`: 시스템 원형 설계와 에이전트 책임 경계.
- `docs/01_architecture_milestones/`: 구현 마일스톤과 후속 수정 계획.
- `docs/02_agent_pipeline/`: AI agent, decision pipeline, prompt/provider 흐름.
- `docs/03_execution_order/`: 주문 실행과 broker boundary.
- `docs/05_reconciliation_snapshot/`: reconciliation과 snapshot sync.
- `docs/07_scheduler_ops/`: 스케줄러와 운영 자동화.
- `docs/08_frontend_design/`: Admin UI와 운영 대시보드.
- `docs/09_paper_trading_validation/`: paper trading 검증.
- `docs/10_signal_research_sppv/`: 시그널 리서치와 분석 문서.
- `docs/99_meta_handover/`: 인수인계, 백로그, 문서 운영 원칙.

## Harness Engineering 목적

이 프로젝트의 Harness Engineering 목적은 매매 시스템을 “실행 가능한 검증 하네스”로 유지하는 것이다.

핵심은 다음 세 가지다.

1. 입력, 상태 전이, 출력, 실패 조건이 관측 가능해야 한다.
2. 매매·리스크·주문·정합성 경계가 테스트와 로그로 검증 가능해야 한다.
3. 운영 성공은 exit code가 아니라 처리량, 저장 레코드, 상태 변화, 오류 카운트 같은 증거로 보고해야 한다.

런타임 또는 운영 변경에서는 다음 증거 경로를 보존하거나 추가한다.

- 가능한 경우 저장된 실행 레코드.
- 명시적인 처리·스킵·오류 카운트.
- decision ID, context ID, order ID, account ID, symbol 식별자.
- pre-submit 검증, submit, post-submit sync, reconciliation, inspection 경계의 분리.
- 테스트, 로그, 요약 파일, DB 상태 중 하나 이상으로 확인 가능한 실패 모드.

## 시스템 목표와 차단 장치 판단 기준

이 시스템의 목표는 **손실을 0으로 만드는 것이 아니라, 감내 가능한 손실 제약 아래에서 최고의 기대수익률을 추구하는 것**이다(2026-07-14 사용자 확정 — "손실 0이 목적이 아니라, 손실을 최소화하며 리스크를 감내한 뒤 기대수익을 추구한다"; 상세 배경은 `docs/10_signal_research_sppv/[PRIORITY_MAP] remaining_work_priority_map.md`의 공통 판단 원칙 참고).

이 목표가 중요한 이유는 다음과 같다.

- 손실 0을 목표로 삼으면 모든 차단 장치를 "더 엄격하게" 만드는 쪽으로 판단이 기울기 쉽다. 하지만 매매 시스템에서 손실 0은 대개 거래 0을 뜻한다 — 아무것도 사지 않으면 손실도 없지만, 원래 목표였던 기대수익도 함께 사라진다.
- 그래서 이 시스템은 **감내 가능한 손실을 전제로, 그 안에서 기대값을 최대화**하는 것을 목표로 둔다. "손실을 허용한다"는 뜻이 아니라 "리스크를 무제한 감내한다"는 뜻도 아니다 — VaR, 유동성, 컴플라이언스 같은 하드 리스크 한도는 그대로 authoritative하게 유지되며, 이 목표는 그 한도 **안에서** 무엇을 우선할지를 정하는 기준이다.
- 차단 장치(eligibility gate, downstream override, expected value gate 등)의 적정성을 판단할 때는 "차단이 얼마나 자주 발생했는가"가 아니라 **그 차단이 기대값을 실제로 개선했는가**를 본다. 차단률이 늘었다는 사실만으로 "과잉 차단"이라 단정하지 않고, 통과군 평균 수익률이 높다는 사실만으로 "차단이 적정하다"고 단정하지도 않는다 — 두 경우 모두 사후 성과(백테스트) 비교로 뒷받침해야 결론이 된다.
- 주문 요청이 0건에 수렴하는 상태는 "안전하게 잘 막았다"가 아니라 **기회비용이 쌓이고 있고 시스템이 원래 목표(기대수익 추구)를 달성하지 못하고 있을 가능성**으로 먼저 의심한다. 다만 이것이 "무조건 더 자주 사야 한다"는 뜻은 아니다 — 그 0건이 실제로 기대값 개선의 결과인지, 과잉 방어의 결과인지는 항상 사후 성과로 확인이 필요하다.

이 기준은 루트 [`AGENTS.md`](../../AGENTS.md)의 "트레이딩 안전 불변식"을 대체하지 않는다. 안전 불변식은 그대로 지키고, 그 한도 안에서 "무엇을 더 우선할지"를 판단할 때만 이 기준을 쓴다.

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
- 문서, 보고, 설명, 사용자 응답에는 중국어를 사용하지 않는다.
- 코드 식별자, 명령어, 로그 원문, 에러 메시지, 외부 API 필드명, 설정 키, 파일 경로는 원문 그대로 유지할 수 있다.

## 실행 원칙

- Ubuntu 서버 작업 영역에서는 `python` 대신 `python3`를 사용한다.
- 서버 환경 특성상 `sh` 실행은 실패하므로 셸 명령은 `bash`에서 실행한다.
- 검증 계층은 `scripts/harness/README.md`의 L0~L6 정의를 따른다.
- L4/L5 무거운 계층의 상세 분류와 보고 카운트는 `scripts/harness/README.md`를 기준으로 한다.
- 커밋 전 빠른 스냅샷은 `bash scripts/harness/run.sh check quick` 또는 `make check-quick`을 사용한다.
- 변경 백엔드 파일 스냅샷은 `bash scripts/harness/run.sh check changed` 또는 `make check-changed`를 사용한다.
- 타입 검사 스냅샷은 `bash scripts/harness/run.sh type-check backend`, `bash scripts/harness/run.sh type-check frontend`, `make type-check-backend`, `make type-check-frontend`를 사용한다.
- read-only 보안 스냅샷은 `bash scripts/harness/run.sh security scan` 또는 `make security-scan`을 사용한다.
- 문서 정합성의 정답 판정은 `bash scripts/harness/run.sh accept docs` 또는 `make accept-docs`를 사용한다.
- 운영 환경 재현성의 정답 판정은 `bash scripts/harness/run.sh accept env` 또는 `make accept-env`를 사용한다.
- 단일 백엔드 파일의 정답 판정은 `bash scripts/harness/run.sh accept backend-file <file>` 또는 `make accept-backend-file FILE=<file>`을 사용한다.
- 백엔드 런타임 계약의 정답 판정은 `bash scripts/harness/run.sh accept backend-runtime` 또는 `make accept-backend-runtime`을 사용한다.
- Admin UI의 정답 판정은 `bash scripts/harness/run.sh accept frontend` 또는 `make accept-admin-ui`를 사용한다.
- 운영 리포트 `summary_json`의 정답 판정은 `bash scripts/harness/run.sh accept ops-report <summary_json>` 또는 `make accept-ops-report SUMMARY_JSON=<summary_json>`을 사용한다.
- 운영 리포트 덤프는 DB를 조회하므로 `HARNESS_ALLOW_OPS_DUMP=1 bash scripts/harness/run.sh dump ops-report [YYYY-MM-DD]` 또는 `HARNESS_ALLOW_OPS_DUMP=1 make dump-ops-report DATE=<YYYY-MM-DD>`로만 실행한다.
- API in-memory 모드 실행은 `bash scripts/harness/run.sh run api-inmemory` 또는 `make run-api-inmemory`를 사용한다.
- API Postgres/Auth 모드 실행은 `bash scripts/harness/run.sh run api-postgres` 또는 `make run-api-postgres`를 사용한다.
- Python, Node.js, npm, PostgreSQL 기준 버전은 각각 `.python-version`, `admin_ui/.nvmrc`, `admin_ui/.npm-version`, `.postgres-version`에 고정한다.
- Python 패키지는 `requirements.lock`, Admin UI 패키지는 `package-lock.json`과 `npm ci`를 기준으로 재현한다.
- `.claude/worktrees/` 아래에는 Claude Code가 만든 그림자 작업트리나 사본이 남을 수 있으므로, canonical 변경 경로로 취급하지 않는다.
- 코드 검색, 참조 집계, 문서 링크 감사, 대량 치환 시에는 `.claude/` 경로를 제외하고 현재 작업트리 기준으로만 판정한다.

## 테스트 데이터 원칙

- 테스트 입력 데이터는 `tests/fixtures/` 아래에 고정한다.
- mutable한 `data/`, `logs/`, `tmp/`의 현재 파일을 테스트 기대값으로 직접 사용하지 않는다.
- DB 테스트는 migration, deterministic seed, cleanup 순서를 명시적으로 가져야 한다.

## 검증 부하 예외

- 하네스가 제공하는 `accept`, `env-check`, `py-compile`, `test-one`, `test-file`, `lint-path`, `admin-test-one` 진입점은 승인 없이 실행할 수 있다.
- 이 예외는 이미 실행 중인 컨테이너의 짧은 `docker exec`, 버전 확인용 `docker run --rm node:20-slim`, 단일 테스트 selector에만 적용한다.
- 새 서비스 기동, 장시간 컨테이너 실행, 전체 테스트/전체 빌드, 외부 API 호출, DB 쓰기/마이그레이션, 운영 덤프(`HARNESS_ALLOW_OPS_DUMP=1`)는 계속 명시 승인 대상이다.

## README 유지 원칙

README에는 프로젝트 실행에 필요한 최신 정보만 남긴다.

- 남길 내용: 요구사항, 빠른 시작, Docker, Inspection API, 프로젝트 구조 요약, 환경변수, Make 명령, 핵심 설계 문서 링크.
- 분리할 내용: 에이전트 작업 규칙, 장기 작업 방식, 계획 리뷰 규칙, 오래된 다음 단계, 세부 설계 본문.
- 오래된 상세 설명은 삭제하지 않고 적절한 `docs/` 하위 문서로 이동하거나 링크로 대체한다.

## 완료 보고 원칙

완료를 주장하기 전 최소 조건은 [`definition_of_done.md`](../80_harness_engineering/definition_of_done.md)를 따른다.

작업 완료 보고에는 다음을 포함한다.

- 변경한 파일.
- 실행한 검증 명령과 결과.
- 검증하지 못한 가정.
- 운영 작업인 경우 기대한 작업이 실제로 수행됐는지 보여주는 구체적 지표.

## 프롬프트 및 계획 리뷰 규칙

설계안이나 구현 계획 리뷰를 요청받으면, 사용자가 구현을 명시하지 않는 한 기본 산출물은 재사용 가능한 프롬프트다.

- 하나의 승인 프롬프트로 정리한다.
- `추가 보정사항`, `그 외 유지해야할 원칙`, `완료 후 보고에 대한 가이드`를 포함한다.
- 구현 완료 보고가 주어지면 다음 추천 구현 프롬프트를 생성한다.
- 오래된 프로젝트 제목 접두사는 프롬프트에 붙이지 않는다.

## 코드 스타일

- 새 추상화를 도입하기 전에 기존 패턴을 우선 따른다.
- 축약어보다 명시적인 이름을 선호한다.
- 국소 버그를 고치기 위해 광범위한 프레임워크 변경을 추가하지 않는다.
- 비자명한 런타임 제약을 설명할 때만 주석을 추가한다.
- 관련 없는 파일을 수정하거나 별도 결함을 기회주의적으로 고치지 않는다.
