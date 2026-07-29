# Runtime Artifact 정책

## 목적

이 문서는 `logs/`, `tmp/`, `data/`처럼 운영 중 변하거나 분석 실행 중 생성되는 산출물을 Git 추적 대상과 문서 링크 대상으로 어떻게 다룰지 정의한다.

목표는 다음 두 가지를 동시에 만족하는 것이다.

- 배포 작업이 런타임 산출물을 `git reset --hard` 대상으로 만들지 않는다.
- 문서가 과거 산출물명을 근거로 삼더라도 깨진 링크나 재현 불가능한 입력을 무분별하게 늘리지 않는다.

## 기본 원칙

- `logs/`와 `tmp/`는 runtime write path로 취급하고 Git 추적 대상에서 제외한다.
- `data/` 전체를 runtime write path로 취급하지 않는다. seed, fixture, canonical 입력, runtime 산출물이 섞일 수 있으므로 하위 경로별로 분류한다.
- 운영 중 갱신되는 파일은 문서의 canonical 입력으로 직접 사용하지 않는다.
- 외부 API 호출, 실계좌·브로커·스케줄러 상태, `.env` 값에 의존하는 임시 측정 스크립트는 정식 `scripts/`로 승격하지 않는다.
- 과거 분석 문서에서 산출물명을 보존해야 할 때는 Markdown 링크가 아니라 코드 텍스트로 남긴다.

## `data/` canonical 입력 정책

`data/`에서 Git 추적을 허용하는 파일은 [`canonical_data_contract.md`](canonical_data_contract.md)의 허용 목록을 따른다.

허용 목록에 없는 신규 `data/` 파일은 runtime 산출물로 보고 Git 추적에서 제외한다. 예외가 필요하면 owner, 갱신 절차, 검증 명령, 참조 목적을 먼저 문서화한다.

## `logs/` 링크 정책

`logs/`는 기본적으로 Git 추적에서 제거한다. 다만 추적 제거 전에 문서 링크는 다음 기준으로 정리한다.

### 링크 유지 금지

다음 파일은 `logs/...` Markdown 링크를 유지하지 않는다.

- 운영 또는 분석 실행 중 재생성되는 `.log`, `.json`, `.jsonl`, `.out`, `.bak` 파일.
- 특정 날짜의 측정 결과를 설명하기 위한 일회성 산출물.
- 외부 API 상태, 장중 시점, 운영 DB 상태에 의존해 재생성이 어려운 파일.
- 문서 안에서 이미 핵심 수치가 요약되어 있고 원본 파일 클릭이 필수 검증 조건이 아닌 파일.

처리 방식:

- ``logs/...`` 링크를 `` `logs/...` `` 코드 텍스트로 전환한다.
- 문서에는 산출물 파일명이 역사적 근거라는 점만 남긴다.

### 보존 예외

다음 조건을 모두 만족할 때만 산출물을 별도 보존 경로로 이동할 수 있다.

- 테스트 fixture 또는 회귀 검증 입력으로 실제 사용된다.
- 파일 크기와 민감정보 노출 위험이 낮다.
- 외부 API key, 계좌, 주문 식별자, 개인정보, 운영 secret이 포함되지 않는다.
- 유지하지 않으면 현재 테스트 또는 하네스 계약이 깨진다.

보존 위치:

- 테스트 입력이면 `tests/fixtures/`.
- 장기 참고자료이면 `docs/90_reference/artifacts/`.
- 단순 작업 결과나 이력 설명이면 `docs/30_work_log/` 문서 본문에 요약하고 원본 파일은 Git 추적에서 제외한다.

## 추적 제거 순서

1. 정확 참조된 `logs/` tracked 파일 목록을 산출한다.
2. 참조 문서에서 Markdown 링크를 코드 텍스트로 전환한다.
3. 보존 예외 후보가 있는 경우 별도 경로 이동 PR로 분리한다.
4. `git rm --cached -r logs`는 링크 정리 PR 이후 별도 PR로 진행한다.
5. `accept docs`와 `accept ci`에서 `markdown_link_missing_count=0`, `destructive_deploy_clean_command_count=0`을 확인한다.

## 현재 기준 카운트

2026-07-29 기준 `logs/` 상태는 다음과 같다.

- `logs_tracked_count=2560`
- `logs_exact_referenced_file_count=166`
- `logs_exact_reference_line_count=413`
- `logs_exact_referenced_json_count=95`
- `logs_exact_referenced_log_count=68`
- `logs_exact_referenced_jsonl_count=2`
- `logs_exact_referenced_txt_count=1`

문서 트리별 정확 참조 라인은 다음과 같다.

| 경로 | 정확 참조 라인 수 |
| --- | ---: |
| `docs/10_signal_research_sppv` | 248 |
| `docs/03_execution_order` | 69 |
| `scripts` | 58 |
| `docs/99_meta_handover` | 23 |
| `docs/30_work_log` | 7 |
| `docs/04_broker_kis` | 2 |
| `docs/07_scheduler_ops` | 2 |
| `docs/06_data_sources_news` | 2 |
| `docs/05_reconciliation_snapshot` | 1 |
| `docs/00_foundational_design` | 1 |

## Codex 추천안

`logs/`는 대표 산출물 대량 보존보다 Markdown 링크를 코드 텍스트로 전환하는 방식을 우선한다.

이유:

- 정확 참조된 `logs/` 파일이 `166`개라 보존 이동 PR이 과도하게 커질 수 있다.
- 대부분 과거 분석의 근거 산출물이며, 현재 하네스나 테스트의 필수 입력으로 확인된 파일은 아니다.
- 링크 보존보다 문서 본문에 핵심 수치와 파일명을 남기는 편이 배포 안전성과 문서 유지보수성을 동시에 만족한다.
