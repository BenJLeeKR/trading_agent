# Canonical Data 계약

## 목적

이 문서는 `data/` 아래에 Git 추적 대상으로 남길 수 있는 파일의 허용 기준, owner, 갱신 절차를 정의한다.

`data/`는 runtime write path와 canonical 입력이 섞이기 쉬운 경로다. 따라서 `logs/`, `tmp/`처럼 전체 제외하지 않고, 운영 재현성에 필요한 입력만 허용 목록으로 관리한다.

## 기본 원칙

- `data/`의 신규 runtime 산출물은 기본적으로 Git 추적 대상이 아니다.
- Git 추적을 허용하려면 owner, 갱신 절차, 검증 명령, 참조 목적이 문서화되어야 한다.
- 운영 중 자동 갱신되는 파일을 Git에 남길 때는 배포가 해당 파일을 파괴적으로 되돌리지 않는지 확인해야 한다.
- 일회성 분석 산출물은 `data/`에 남기지 않고 Git 추적에서 제외한다.
- `.env` 값, API key, 계좌 정보, 외부 provider 응답 원문 중 민감정보 가능성이 있는 내용은 canonical data로 승격하지 않는다.

## 현재 허용 목록

2026-07-30 기준 `data/` Git 추적 허용 목록은 `9`개다.

| 경로 | 유형 | owner | 갱신 절차 | 유지 근거 |
| --- | --- | --- | --- | --- |
| `data/instrument_master/source/index_membership_source_manifest.json` | 운영 source manifest | 운영 데이터 관리자 | 사용자 승인 원천 CSV 묶음 반영 후 source package pipeline 실행 | index membership seed 생성 기본 입력 |
| `data/instrument_master/source/index_membership_seed.csv` | 운영 seed | 운영 데이터 관리자 | source manifest와 구성 CSV를 기준으로 재생성 후 검증 | index membership import 기본 입력 |
| `data/instrument_master/source/index_membership_source_manifest.example.json` | 예시 manifest | Harness 문서 관리자 | 실제 값 대신 예시 값만 유지 | 사용자 환경별 source package 작성 기준 |
| `data/instrument_master/source/index_membership_seed.example.csv` | 예시 seed | Harness 문서 관리자 | 실제 값 대신 예시 값만 유지 | 사용자 환경별 seed 작성 기준 |
| `data/instrument_master/source/kospi100_constituents.csv` | 운영 source CSV | 운영 데이터 관리자 | manifest의 `csv_path`와 함께 갱신 | KOSPI100 membership source package 구성 |
| `data/instrument_master/source/kospi200_constituents.csv` | 운영 source CSV | 운영 데이터 관리자 | manifest의 `csv_path`와 함께 갱신 | KOSPI200 membership source package 구성 |
| `data/instrument_master/source/kosdaq150_constituents.csv` | 운영 source CSV | 운영 데이터 관리자 | manifest의 `csv_path`와 함께 갱신 | KOSDAQ150 membership source package 구성 |
| `data/instrument_master/source/kospi_master_instrument.csv` | 운영 raw source CSV | 스케줄러 운영자 | 승인된 원천 업로드 파일을 반영한 뒤 `kospi_master.csv` 생성 절차 실행 | instrument master sync 상류 원천 입력 |
| `data/instrument_master/source/kosdaq_master.csv` | 운영 source CSV | 스케줄러 운영자 | KIS master 원천 갱신 후 normalize 단계 실행 | instrument master sync 기본 입력 |
| `data/instrument_master/normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv` | 운영 normalized 입력 | 스케줄러 운영자 | source CSV 기준으로 normalize 후 sync 단계 실행 | instrument master sync 기본 입력 |

## 현재 카운트

2026-07-30 감사 결과는 다음과 같다.

| 항목 | 파일 수 |
| --- | ---: |
| `data/` tracked 파일 | 10 |
| CSV 파일 | 8 |
| JSON 파일 | 2 |
| `data/instrument_master/source/` 파일 | 8 |
| `data/instrument_master/normalized/` 파일 | 1 |
| `data/` runtime 산출물 tracked 파일 | 0 |

## 갱신 절차

### 공통 절차

1. owner가 변경 목적과 원천을 확인한다.
2. 변경 파일이 위 허용 목록에 포함되는지 확인한다.
3. 허용 목록 밖의 `data/` 파일은 기본적으로 `.gitignore` 또는 `git rm --cached` 대상으로 분류한다.
4. 변경 후 `bash scripts/harness/run.sh accept docs`와 `bash scripts/harness/run.sh accept ci`를 실행한다.
5. 변경 보고에는 변경 파일 수, `data_tracked_count`, `runtime_tracked_file_count`, 민감정보 검토 여부를 카운트로 남긴다.

### index membership source package

- manifest와 구성 CSV는 같은 PR에서 갱신한다.
- manifest의 `entries[].csv_path`가 실제 같은 디렉터리의 CSV 파일을 가리키는지 확인한다.
- seed CSV는 source package pipeline 결과로만 갱신한다.
- 예시 파일은 실제 운영 값이 아니라 형식 안내용 값만 포함한다.

### instrument master sync 입력

- `source/kospi_master_instrument.csv`는 승인된 운영 원천 업로드를 보존하는 상류 입력이다.
- `source/kospi_master.csv`와 `source/kosdaq_master.csv`는 스케줄러가 읽는 기본 source CSV다.
- `source/kosdaq_master.csv`와 `normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv`는 스케줄러 기본 경로와 연결되어 있다.
- normalized 파일은 source 파일을 기준으로 재생성 가능한 상태여야 한다.
- archive 산출물은 Git 추적 대상이 아니며 `data/instrument_master/archive/` 아래에만 남긴다.

### signal feature snapshot 입력

- `data/signal_feature_snapshot_input.json`은 일일 배치가 재생성하고 DB 갱신 입력으로 사용하는 운영 산출물이다.
- 따라서 이 파일은 canonical 입력 허용 목록에 두지 않고 Git 추적에서 제외한다.
- 스케줄러와 테스트의 기본 경로 문자열은 당장 유지할 수 있지만, 샘플 입력이 필요하면 별도 fixture 또는 `.example` 파일로 분리한다.
- 날짜별 snapshot과 분석 산출물도 모두 Git 추적 대상이 아니다.

## 금지 사항

- `data/` 전체를 한 번에 Git 추적 제외하거나 복원하지 않는다.
- 운영 source CSV와 generated normalized CSV를 같은 의미의 파일로 취급하지 않는다.
- 검증 없이 운영 입력 파일을 일회성 분석 산출물로 덮어쓰지 않는다.
- 민감정보 가능성이 있는 provider 응답, 계좌 정보, API 응답 원문을 canonical data로 추가하지 않는다.

## 관련 문서

- [`runtime_artifact_policy.md`](runtime_artifact_policy.md)
- [`data_runtime_canonical_split_review.md`](../30_work_log/data_runtime_canonical_split_review.md)
- [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)
