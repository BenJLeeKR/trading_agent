# index membership 외부 원천 패키지 적용 절차

## 목적

- `KOSPI100`, `KOSDAQ50`, `KOSDAQ150` 같은 membership 외부 원천 파일을
  운영 DB에 반영할 때
  손편집/즉시 import로 인한 오염을 막고
  `source package -> 검증 -> import` 절차를 고정한다.

## 입력물

- source package manifest
  - `data/instrument_master/source/index_membership_source_manifest.json`
- membership별 구성종목 CSV
  - manifest의 `entries[].csv_path`
- KIS 카탈로그 dump
  - `logs/kis_index_category_catalog.json`
  - 필요 시 `scripts/export_kis_index_category_catalog.py`로 재생성

## 절차

### 0. 통합 파이프라인 실행기 사용 가능

```bash
python3 scripts/run_index_membership_source_package_pipeline.py \
  --manifest data/instrument_master/source/index_membership_source_manifest.json \
  --seed-csv data/instrument_master/source/index_membership_seed.csv \
  --catalog logs/kis_index_category_catalog.json \
  --replace-listed-symbols
```

실반영 시:

```bash
python3 scripts/run_index_membership_source_package_pipeline.py \
  --manifest data/instrument_master/source/index_membership_source_manifest.json \
  --seed-csv data/instrument_master/source/index_membership_seed.csv \
  --catalog logs/kis_index_category_catalog.json \
  --replace-listed-symbols \
  --apply
```

의미:
- 위 실행기는 아래 1~4단계를 같은 순서로 호출한다.
- 중간 단계 하나라도 실패하면 즉시 중단한다.

### 1. source package -> seed CSV 생성

```bash
python3 scripts/build_index_membership_seed_from_source_package.py \
  --manifest data/instrument_master/source/index_membership_source_manifest.json \
  --output data/instrument_master/source/index_membership_seed.csv
```

확인 포인트:
- `source_name`, `source_ref`, `as_of_date`가 manifest에 모두 들어있는지
- 각 entry의 `membership_code`가 허용 집합인지
- 각 source CSV에 `symbol` 컬럼이 존재하는지

### 2. KIS 카탈로그 기준 alias 검증

```bash
python3 scripts/validate_kis_index_membership_catalog.py \
  --catalog logs/kis_index_category_catalog.json \
  --seed-csv data/instrument_master/source/index_membership_seed.csv \
  --fail-on-missing
```

목적:
- `KOSPI100`, `KOSPI200`, `KOSDAQ50`, `KOSDAQ150` code가
  KIS 카탈로그 alias와 전혀 매칭되지 않는 오기입인지 확인

주의:
- 이 검증은 구성종목 authoritative source 검증이 아니라
  membership code label 검증이다.

### 3. instrument master 해상도 검증

```bash
python3 scripts/validate_index_membership_seed_resolution.py \
  --csv data/instrument_master/source/index_membership_seed.csv \
  --fail-on-unresolved \
  --fail-on-placeholder
```

목적:
- seed CSV의 symbol이 현재 `trading.instruments`에 실제로 존재하는지
- placeholder row에만 해상되는 종목이 남아 있는지 확인

판정:
- `unresolved_symbol_count > 0`
  - 먼저 instrument master sync 또는 placeholder 정리가 필요
- `placeholder_symbol_count > 0`
  - 실제 master row 승격 전에는 import를 보류하는 것이 원칙

### 4. membership seed import

```bash
python3 scripts/import_instrument_index_membership_seed.py \
  --csv data/instrument_master/source/index_membership_seed.csv \
  --replace-listed-symbols \
  --apply
```

원칙:
- 외부 authoritative source package를 반영할 때는
  manifest에 나온 symbol에 대해 `--replace-listed-symbols`를 기본값으로 본다.
- 단, 일부 membership만 보강하는 임시 merge 작업이면
  `--replace-listed-symbols` 없이 merge 적용 가능하다.

### 5. 사후 확인

확인 항목:
- `instrument_index_memberships` active row가 기대 membership으로 바뀌었는지
- Universe preview에서 membership 기반 seed 판정이 달라졌는지
- placeholder symbol이 import 대상에 남지 않았는지

## 실패 시 대응

- manifest 오류:
  - source package 메타데이터 수정 후 1단계부터 재실행
- catalog alias 미매칭:
  - membership code 오기입 여부 우선 점검
- unresolved / placeholder:
  - instrument master sync 또는 placeholder 승격 선행
- import contract 실패:
  - 같은 symbol의 provenance 불일치 여부 확인

## 비고

- 이 runbook은 외부 원천 파일을 확보한 뒤
  운영자가 최초 반영할 때의 안전 절차다.
- 실제 authoritative source 자체의 신뢰성 평가는
  별도 운영 승인 프로세스를 따른다.
