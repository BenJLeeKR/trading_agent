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
| `data/signal_feature_snapshot_input*.json` | 16 | 일부 있음 | 테스트·스케줄러 입력과 분석 산출물이 혼재 | 기본 입력 1개만 보존, 과거 snapshot 추적 제외 완료 |
| `data/trigger_proxy_attribution*.json` | 5 | 0 | 분석 산출물 후보 | Git 추적 제외 완료 |
| `data/ar_fdc_*.json` | 2 | 있음 | 스크립트 생성 산출물 | Markdown 링크 정리 완료, 추적 제외 전 생성 경로 감사 필요 |
| `data/observations/*.json` | 6 | 있음 | 문서 근거 산출물 | Git 추적 제외 완료 |

## Codex 추천안

1. `data/instrument_master/archive/` `33`개는 정확 참조가 `0`개이므로 Git 추적에서 제외했다.
2. `data/observations/`는 `logs/`와 같은 방식으로 Markdown 링크를 코드 텍스트로 전환한 뒤 Git 추적에서 제외했다.
3. `data/signal_feature_snapshot_input.json`은 스케줄러와 테스트 기본값이 직접 참조하므로 이번 범위에서 제거하지 않는다.
4. `data/instrument_master/source/`와 `data/instrument_master/normalized/`는 운영 재현성 입력으로 남기되, 추후 `data/canonical/` 또는 `data/fixtures/` 같은 명시 경로로 옮길지 별도 판단한다.
5. top-level root JSON `24`개 중 정확 참조가 없는 `21`개는 코드 wildcard 사용 여부 감사 결과 `0`건이므로 Git 추적에서 제외했다.
6. `data/ar_fdc_*.json` Markdown 링크 `3`개는 코드 텍스트로 전환했다.

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
- `data/signal_feature_snapshot_input.json`은 스케줄러와 테스트 기본 입력이라 제거하지 않는다.
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
