# `data/` runtime/canonical 분리 검토

## 목적

`logs/`와 `tmp/` 추적 제외 이후 남은 runtime tracked 파일 `72`개를 즉시 제거하지 않고, 운영 입력으로 보존할 파일과 런타임 산출물로 제외할 파일을 분리한다.

## 2026-07-29 현재 집계

| 항목 | 파일 수 |
| --- | ---: |
| `data/` tracked 전체 | 72 |
| `data/instrument_master/` | 42 |
| `data/` 루트 JSON | 24 |
| `data/observations/` | 6 |
| 정확 참조된 tracked `data/` 파일 | 15 |
| 정확 참조 라인 | 107 |
| 정확 참조 없는 tracked `data/` 파일 | 57 |

## 경로별 판정

| 경로 | 파일 수 | 정확 참조 | 판정 | 다음 조치 |
| --- | ---: | ---: | --- | --- |
| `data/instrument_master/source/` | 8 | 있음 | canonical 입력 후보 | 유지하되 owner와 갱신 절차 문서화 |
| `data/instrument_master/normalized/` | 1 | 있음 | 생성물이지만 스케줄러 기본 입력 | 기본 경로 변경 전까지 유지 |
| `data/instrument_master/archive/` | 33 | 0 | runtime/cache 후보 | Git 추적 제외 완료 |
| `data/signal_feature_snapshot_input*.json` | 16 | 일부 있음 | 테스트·스케줄러 입력과 분석 산출물이 혼재 | 과거 snapshot 추적 제외 완료, 기본 입력도 운영 산출물로 재분류 |
| `data/trigger_proxy_attribution*.json` | 5 | 0 | 분석 산출물 후보 | Git 추적 제외 완료 |
| `data/ar_fdc_*.json` | 2 | 있음 | 스크립트 생성 산출물 | Git 추적 제외 완료 |
| `data/observations/*.json` | 6 | 있음 | 문서 근거 산출물 | Git 추적 제외 완료 |

## 현재 canonical 입력 허용 목록

2026-07-30 기준 남은 `data/` tracked 파일 `9`개는 [`canonical_data_contract.md`](../80_harness_engineering/canonical_data_contract.md)의 허용 목록으로 관리한다.

| 분류 | 파일 수 | 판정 |
| --- | ---: | --- |
| `data/instrument_master/source/` 운영·예시 입력 | 7 | owner와 갱신 절차 문서화 후 유지 |
| `data/instrument_master/normalized/` 스케줄러 입력 | 1 | 기본 경로 변경 전까지 유지 |
| runtime 산출물 | 0 | 허용 목록 밖 신규 `data/` 파일은 추적 제외 |

## Codex 추천안

1. `data/instrument_master/archive/` `33`개는 정확 참조가 `0`개이므로 Git 추적에서 제외했다.
2. `data/observations/`는 `logs/`와 같은 방식으로 Markdown 링크를 코드 텍스트로 전환한 뒤 Git 추적에서 제외했다.
3. `data/signal_feature_snapshot_input.json`은 일일 배치가 재생성하고 DB 갱신 입력으로 쓰는 운영 산출물이므로 Git 추적에서 제외한다.
4. `data/instrument_master/source/`와 `data/instrument_master/normalized/`는 운영 재현성 입력으로 남기되, 추후 `data/canonical/` 또는 `data/fixtures/` 같은 명시 경로로 옮길지 별도 판단한다.
5. top-level root JSON `24`개 중 정확 참조가 없는 `21`개는 코드 wildcard 사용 여부 감사 결과 `0`건이므로 Git 추적에서 제외했다.
6. `data/ar_fdc_*.json` Markdown 링크 `3`개는 코드 텍스트로 전환했다.
7. `data/ar_fdc_*.json`은 스크립트가 생성·갱신하는 산출물이므로 Git 추적에서 제외했다.
8. 남은 `data/` tracked 파일 `9`개는 canonical 입력 허용 목록으로 문서화했다.

## 금지 사항

- `data/` 전체를 한 번에 `git rm --cached -r data`로 제거하지 않는다.
- 스케줄러 기본 입력 경로를 바꾸면서 테스트 fixture와 운영 입력 경로를 같은 PR에 섞지 않는다.
- 문서 Markdown 링크가 남아 있는 산출물을 추적 제외하지 않는다.

## 다음 작업 후보

- P0 11차: `data/instrument_master/archive/` 정확 참조 `0`개를 재확인하고 추적 제외했다.
- P0 12차: `data/observations/` Markdown 링크 보존 정책을 결정했다.
- P0 13차: `data/observations/` tracked 파일 `6`개 추적 제외를 완료했다.
- P0 14차: root JSON 중 기본 입력 파일과 과거 분석 산출물을 분리했다.
- P0 15차: 정확 참조가 없는 root JSON `21`개에 대한 wildcard 사용 여부를 감사했다.
- P0 16차: 정확 참조와 wildcard 사용이 없는 root JSON `21`개를 추적 제외했다.
- P0 17차: `data/ar_fdc_*.json` Markdown 링크 `3`개를 코드 텍스트로 전환했다.
- P0 18차: `data/ar_fdc_*.json` 생성 경로를 감사하고 tracked 파일 `2`개를 추적 제외했다.
- P0 19차: 남은 `data/` tracked 파일 `10`개의 owner와 갱신 절차를 canonical 허용 목록으로 문서화했다.

## 완료 기록

### 2026-07-29 — `data/instrument_master/archive/` 추적 제외

- 추적 제외 전 `data/instrument_master/archive/` tracked 파일은 `33`개였다.
- 정확 참조된 archive 파일은 `0`개였다.
- `git rm --cached -r data/instrument_master/archive`로 Git 추적에서만 제거했다.
- 작업트리의 archive 실제 파일은 `34`개로 보존됐다.
- `.gitignore`에 `data/instrument_master/archive/`를 추가해 재추적을 막았다.
- `runtime_tracked_file_count`는 `72`에서 `39`로 감소했다.

### 2026-07-29 — `data/observations/` Markdown 링크 전환

- `data/observations/` tracked 파일은 `6`개다.
- 정확 참조된 `data/observations/` tracked 파일은 `6`개, 정확 참조 라인은 `13`개였다.
- `data/observations/` Markdown 링크는 `13`개였다.
- 전환 대상 문서는 `7`개였다.
- Markdown 링크 `13`개를 모두 코드 텍스트로 전환했다.
- 전환 후 `data/observations/` Markdown 링크는 `0`개다.
- 다음 작업은 `data/observations/` tracked 파일 `6`개를 별도 PR에서 추적 제외하는 것이다.

### 2026-07-29 — `data/observations/` 추적 제외

- 추적 제외 전 `data/observations/` tracked 파일은 `6`개였다.
- 작업트리의 `data/observations/` 실제 파일은 `6`개로 보존됐다.
- 전체 문서의 `data/observations/` Markdown 링크는 `0`개였다.
- `git rm --cached -r data/observations`로 Git 추적에서만 제거했다.
- `.gitignore`에 `data/observations/`를 추가해 재추적을 막았다.
- `runtime_tracked_file_count`는 `39`에서 `33`으로 감소했다.

### 2026-07-29 — root JSON 기본 입력·분석 산출물 분리

- top-level root JSON tracked 파일은 `24`개다.
- 정확 참조된 top-level root JSON 파일은 `3`개, 정확 참조 라인은 `46`개다.
- 정확 참조 없는 top-level root JSON 파일은 `21`개다.
- 분류 결과는 `signal_feature_default=1`, `signal_feature_historical=16`, `trigger_proxy_artifact=5`, `ar_fdc_artifact=2`다.
- `data/signal_feature_snapshot_input.json`은 당시 스케줄러와 테스트 기본 입력이라 임시 유지 대상으로 분류했다.
- `data/ar_fdc_*.json`은 문서 Markdown 링크 `3`개와 스크립트 생성 경로 참조가 있어 링크 정리 후 별도 처리한다.
- `signal_feature_historical`와 `trigger_proxy_artifact` `21`개는 정확 참조가 `0`개지만 wildcard 사용 여부를 추가 감사한 뒤 추적 제외한다.

### 2026-07-29 — root JSON wildcard 사용 감사

- 정확 참조가 없는 top-level root JSON 후보는 `21`개다.
- 후보 구성은 `signal_feature_historical=16`, `trigger_proxy_artifact=5`다.
- 코드·테스트·스크립트·CI에서 `data/*.json`, `Path("data").glob("*.json")`, `glob("data/*.json")`, `signal_feature_snapshot_input_*`, `trigger_proxy_attribution_*` 패턴을 감사했다.
- 후보 파일 basename 부분 참조는 `0`건이었다.
- 후보를 실제로 읽을 수 있는 코드 wildcard 패턴은 `0`건이었다.
- 문서 예시와 과거 산출물명 참조는 runtime artifact 보존 근거로 보지 않는다.
- 다음 작업은 후보 `21`개를 별도 PR에서 Git 추적 제외하는 것이다.

### 2026-07-29 — root JSON 후보 추적 제외

- 추적 제외 후보 root JSON 파일은 `21`개였다.
- 후보 구성은 `signal_feature_historical=16`, `trigger_proxy_artifact=5`였다.
- `git rm --cached`로 후보 `21`개를 Git 추적에서만 제거했다.
- 작업트리의 후보 실제 파일은 `21`개로 보존됐다.
- `.gitignore`에 `data/signal_feature_snapshot_input_*.json`과 `data/trigger_proxy_attribution_*.json`를 추가했다.
- 남은 top-level root JSON tracked 파일은 `3`개다.
- `runtime_tracked_file_count`는 `33`에서 `12`로 감소했다.

### 2026-07-29 — `data/ar_fdc_*.json` Markdown 링크 전환

- `data/ar_fdc_*.json` tracked 파일은 `2`개다.
- 전환 전 전체 문서의 `data/ar_fdc_*.json` Markdown 링크는 `3`개였다.
- 전환 대상 문서는 `2`개였다.
- Markdown 링크 `3`개를 모두 코드 텍스트로 전환했다.
- 전환 후 전체 문서의 `data/ar_fdc_*.json` Markdown 링크는 `0`개다.
- 정확 참조된 `data/ar_fdc_*.json` tracked 파일은 `2`개, 정확 참조 라인은 `19`개다.
- 다음 작업은 `data/ar_fdc_*.json` 생성 경로를 감사한 뒤 Git 추적 제외 가능 여부를 판단하는 것이다.

### 2026-07-29 — `data/ar_fdc_*.json` 추적 제외

- 추적 제외 전 `data/ar_fdc_*.json` tracked 파일은 `2`개였다.
- `scripts/ar_fdc_output_measurement.py`는 `data/ar_fdc_prompts_{symbol}.json`을 생성한다.
- `scripts/ar_fdc_provider_validation.py`는 `data/ar_fdc_prompts_030200.json`을 입력으로 읽고 `data/ar_fdc_provider_validation_030200.json`을 생성한다.
- `data/ar_fdc_*.json` Markdown 링크는 `0`개였다.
- `git rm --cached`로 후보 `2`개를 Git 추적에서만 제거했다.
- `.gitignore`에 `data/ar_fdc_*.json`을 추가했다.
- 남은 `data/` tracked 파일은 `10`개다.
- `runtime_tracked_file_count`는 `12`에서 `10`으로 감소했다.

### 2026-07-29 — 남은 `data/` canonical 입력 허용 목록 문서화

- 남은 `data/` tracked 파일은 `10`개다.
- 확장자 분포는 `csv=7`, `json=3`이다.
- 경로 분포는 `data/instrument_master/source=7`, `data/instrument_master/normalized=1`, `data/signal_feature_snapshot_input.json=1`이다.
- 허용 목록 작성 전 full path 정확 참조가 `0`개였던 constituent CSV `3`개는 manifest의 `csv_path`와 문서 basename 참조가 각각 `3`개 있어 source package 구성 파일로 유지한다.
- owner 분류는 `운영 데이터 관리자=5`, `스케줄러 운영자=3`, `Harness 문서 관리자=2`로 기록했다.
- 허용 목록과 갱신 절차는 [`canonical_data_contract.md`](../80_harness_engineering/canonical_data_contract.md)에 기록했다.

### 2026-07-30 — `data/signal_feature_snapshot_input.json` 운영 산출물 재분류

- `data/signal_feature_snapshot_input.json` tracked 파일 `1`개를 Git 추적에서 제거했다.
- 작업트리의 실제 파일 `1`개는 보존했다.
- `.gitignore`에 `data/signal_feature_snapshot_input.json`을 추가해 재추적을 막았다.
- 남은 `data/` tracked 파일은 `10`에서 `9`로 감소했다.
- canonical 허용 목록의 JSON 파일 수는 `3`에서 `2`로 감소했다.
- 스케줄러와 테스트의 기본 경로 문자열은 유지하되, 샘플 입력이 필요하면 fixture 또는 `.example` 파일로 분리하기로 기록했다.
