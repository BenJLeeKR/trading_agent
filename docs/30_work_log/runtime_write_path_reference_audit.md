# Runtime Write Path 참조 감사

## 목적

이 문서는 `logs/`, `tmp/`, `data/` 추적 제거 전에 코드·문서·테스트가 해당 파일을 직접 참조하는지 확인한 결과를 기록한다.

`git rm --cached` 자체는 로컬 파일을 삭제하지 않지만, Git 추적에서 제거된 파일을 문서가 Markdown 링크로 직접 참조하면 `accept docs`의 링크 검증 또는 사람이 문서를 읽는 과정에서 깨진 참조가 생길 수 있다.

## 감사 범위

검색 대상:

- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `docs/`
- `scripts/`
- `src/`
- `tests/`
- `admin_ui/`
- `.github/`
- `Makefile`

제외 대상:

- `docs/90_reference/**`
- `logs/**`
- `tmp/**`
- `data/**`

## 경로 문자열 참조 카운트

| 경로 문자열 | 참조 라인 수 | 판정 |
| --- | ---: | --- |
| `logs/` | 864 | 문서·분석 보고서 참조가 많음 |
| `tmp/` | 103 | 대부분 작업/임시 경로 설명 |
| `data/` | 307 | 코드 기본값, 테스트 기대값, 문서 링크가 혼재 |

## tracked 파일 정확 참조 카운트

| 경로 | 정확 참조된 tracked 파일 수 | 정확 참조 라인 수 | 판정 |
| --- | ---: | ---: | --- |
| `logs/` | 166 | 406 | 추적 제거 전 문서 링크 정리 필요 |
| `tmp/` | 1 | 3 | 정리 난이도 낮음 |
| `data/` | 15 | 98 | seed/canonical 입력과 산출물 분리 필요 |
| 합계 | 182 | 507 | 즉시 전체 추적 제거 금지 |

## 정확 참조 상위 파일

| 참조 라인 수 | 파일 |
| ---: | --- |
| 23 | `data/signal_feature_snapshot_input.json` |
| 15 | `data/instrument_master/source/index_membership_seed.csv` |
| 11 | `data/instrument_master/normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv` |
| 10 | `data/ar_fdc_prompts_030200.json` |
| 10 | `logs/regime_conditional_signal_shadow_history.jsonl` |
| 10 | `logs/signal_ic_alpha_layer_r3_reproducibility_2026-07-16.json` |
| 9 | `logs/near_real_scheduler_2026-05-15.log` |
| 9 | `logs/regime_switch_v1_gate_monitor_2026-07-14.json` |
| 8 | `logs/r3b_pytest_run_2026-07-18.log` |
| 7 | `data/ar_fdc_provider_validation_030200.json` |
| 7 | `data/instrument_master/source/index_membership_source_manifest.json` |
| 7 | `data/instrument_master/source/kosdaq_master.csv` |
| 7 | `logs/signal_ic_sppv2_7_extended_period_2026-07-14.json` |
| 7 | `logs/signal_ic_sppv2_expanded_2026-07-14.json` |

## 판정

현재 상태에서 `logs/`, `tmp/`, `data/`를 한 번에 `git rm --cached -r`로 제거하는 것은 적절하지 않다.

이유:

- 정확 참조된 tracked 파일이 `182`개 있다.
- 특히 `logs/`는 분석 문서가 실제 산출물 파일명을 근거로 많이 참조한다.
- `data/`는 테스트와 스크립트 기본 경로가 참조하는 seed/canonical 후보가 포함되어 있다.
- 한 번에 제거하면 링크 정리, fixture 이동, 운영 입력 분리 작업이 섞여 PR 검토 난이도가 커진다.

## Codex 추천안

### 1단계 — `tmp/` 정리

- 정확 참조 파일 수가 `1`개라 오판 위험이 가장 낮다.
- 필요한 `.py`는 `scripts/` 또는 `tests/`로 승격하고, 나머지는 `git rm --cached -r tmp` 후보로 둔다.

### 2단계 — `logs/` 링크 정책 결정

- 분석 문서의 과거 산출물 링크를 계속 클릭 가능하게 유지할지 결정한다.
- 유지한다면 대표 산출물만 `docs/90_reference/artifacts/` 같은 보존 경로로 이동한다.
- 유지하지 않는다면 문서 링크를 “역사적 산출물명” 텍스트로 바꾸고 `logs/` 전체를 추적 제외한다.
- 현재 정책은 [`runtime_artifact_policy.md`](../20_harness_engineering/runtime_artifact_policy.md)를 따른다.

### 3단계 — `data/` canonical 분리

- `data/instrument_master/source/*.example.*`와 테스트가 직접 쓰는 seed 파일은 보존 후보로 둔다.
- 날짜별 snapshot, observation, 분석 산출물은 runtime/cache/reference 중 하나로 재분류한다.
- 신규 런타임 쓰기는 `data/runtime/`, `data/cache/`, `data/local/`로만 보낸다.

## 사용자 결정 필요 항목

Codex 추천은 다음과 같다.

- 다음 PR은 `tmp/` 정리부터 진행한다.
- `logs/`는 전체 제거 전에 문서 링크 정책을 먼저 결정한다.
- `data/`는 전체 제거하지 않고 seed/canonical 분리 문서와 함께 진행한다.

이유:

- `tmp/`는 정확 참조가 `1`개라 작은 PR로 닫을 수 있다.
- `logs/`는 정확 참조가 `166`개라 즉시 제거 시 문서 신뢰도가 떨어질 수 있다.
- `data/`는 정확 참조가 `15`개지만 테스트와 스크립트 기본값이 포함되어 있어 운영 재현성에 직접 영향을 줄 수 있다.

## 후속 처리 기록

### 2026-07-29 — `tmp/` 정확 참조 해소

- 정확 참조 파일 `1`개: `tmp/measure_dschat_latency.py`.
- 정확 참조 라인 `3`개를 Markdown 링크에서 역사적 파일명 코드 텍스트로 전환했다.
- 전환 후 `tmp/` tracked 파일을 Git 추적에서 제거해도 문서 링크 검증이 깨지지 않는다.

### 2026-07-29 — `logs/` 링크 정책 결정

- `logs/` tracked 파일은 `2560`개다.
- 정확 참조된 `logs/` tracked 파일은 `166`개, 정확 참조 라인은 `413`개다.
- 정확 참조 파일 확장자 분포는 `.json=95`, `.log=68`, `.jsonl=2`, `.txt=1`이다.
- 대표 산출물 대량 보존보다 Markdown 링크를 코드 텍스트로 전환하는 정책을 우선한다.
- 정책 기준은 [`runtime_artifact_policy.md`](../20_harness_engineering/runtime_artifact_policy.md)에 기록했다.

### 2026-07-29 — `docs/03_execution_order` `logs/` Markdown 링크 전환

- `docs/30_work_log`와 `docs/99_meta_handover`에는 `logs/` Markdown 링크가 `0`개였다.
- 두 디렉터리의 정확 참조된 `logs/` tracked 파일은 `23`개, 정확 참조 라인은 `30`개였으나 이미 코드 텍스트 형태라 전환하지 않았다.
- 전체 문서의 `logs/` Markdown 링크는 `28`개였다.
- `docs/03_execution_order`의 `logs/` Markdown 링크 `19`개와 정책 문서 예시 링크 `1`개를 코드 텍스트로 전환했다.
- 전환 후 남은 `logs/` Markdown 링크는 `8`개다.
