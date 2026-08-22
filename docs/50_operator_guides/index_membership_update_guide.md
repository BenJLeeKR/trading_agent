# 지수 편입 데이터 수동 갱신 가이드

## 목적과 적용 범위

이 문서는 거래소에서 받은 지수 구성종목 데이터를
`trading.instrument_index_memberships`에 안전하게 반영하는 운영 절차다.

- 대상 지수 코드: `KOSPI100`, `KOSPI200`, `KOSDAQ50`, `KOSDAQ150`
- 원천: 거래소에서 내려받아 운영자가 준비한 구성종목 CSV
  - 데이터는 KRX 정보데이터시스템(`https://data.krx.co.kr/`)에서 확인·다운로드할 수 있다.
- 반영 방식: 원천 패키지 → 검증 → DB 반영 → 유니버스 확인
- 영향 범위: 다음 유니버스 freeze 생성부터 지수 편입 기반 후보 판정에 사용한다.
- 비대상: 주문 제출, BUY 차단, 보유 종목 처리, 기존 freeze 기록의 소급 변경

운영 대시보드의 "지수 편입(index membership) 데이터가 오래되었습니다" 경고는
활성 membership의 가장 최신 `as_of_date`를 기준으로 계산한다. 기본 정책은
**달력 기준 6개월을 초과한 다음 날부터 오래됨**이다(2026-08-22 변경). 예를
들어 `as_of_date`가 `2026-01-31`이면 `2026-07-31`까지는 정상이고
`2026-08-01`부터 오래됨으로 판정한다. 데이터가 전혀 없으면 기존과 동일하게
무조건 오래됨으로 본다. 경고 자체는 관측 전용이며 주문 경로를 차단하지 않는다.
다만 오래된 구성종목 목록이 이후 유니버스 선정에 계속 사용될 수 있으므로,
원천 기준일이 갱신되면 이 절차로 반영한다.

변경 근거: KRX 지수 구성종목 정기 변경은 상반기·하반기 주기가 기본이다.
과거 21일 고정 임계값은 이 정상적인 반기 운영 주기에도 과도한 경고를
만들었다. 달력 기준 6개월은 월말·윤년 경계를 예측 가능하게 처리한다
(예: `2026-08-31` 기준이면 평년 2월의 말일 clamp로 `2027-02-28`까지 정상).

**KOSPI200 정기변경 일정(확인된 공개 자료 기준)**:

- 연 2회 정기변경 — 매년 5월·11월에 KRX가 결과를 확정·발표하고,
  KOSPI200 선물시장 6월·12월 결제월 최종거래일의 다음 매매거래일부터
  시행한다.
- 심사기준일은 심사연도 4월(또는 10월)의 최종 매매거래일이며,
  심사대상기간은 그 기준일로부터 소급한 최근 6개월이다.
- 2019-12-12 공지(한국금융연구원 자료)로 정기변경 주기가 연 1회(6월)에서
  연 2회(6월·12월)로 단축됐고, 구성종목 선정의 산정기간·최소 상장기간
  요건도 1년에서 6개월로 함께 단축됐다.
- 참고: [alchemine.github.io — KOSPI 200 리밸런싱 정리](https://alchemine.github.io/2020/04/03/kospi200.html),
  [한국금융연구원 — (보도자료) 코스피 200 및 코스닥 150 지수산출방법론 개선](https://vwserver.kif.re.kr/html/KM/132206130996610455_191212_%28%EB%B3%B4%EB%8F%84%EC%9E%90%EB%A3%8C%29%2B%EC%BD%94%EC%8A%A4%ED%94%BC%2B200%2B%EB%B0%8F%2B%EC%BD%94%EC%8A%A4%EB%8B%A5%2B150%2B%EC%A7%80%EC%88%98%EC%82%B0%EC%B6%9C%EB%B0%A9%EB%B2%95%EB%A1%A0%2B%EA%B0%9C%EC%84%A0.hwp.files/Sections1.html)

KOSDAQ150도 위 개선안 대상 지수로 함께 언급돼 있으나, 두 자료 모두
KOSDAQ150 자체의 발표월·시행월을 KOSPI200만큼 구체적으로 명시하지는
않는다 — 이 문서에서는 KOSPI200과 동일한 상·하반기 주기를 따른다고
**추정**하되, KOSDAQ150 고유의 정확한 심사기준일·발표일은 **미확인**으로
남긴다. 두 지수 모두 "반기 주기가 기본"이라는 점은 6개월 임계값의
근거로 충분하며, 이 문서의 staleness 정책은 지수별 세부 일정 차이와
무관하게 동일한 6개월 기준을 공통 적용한다.

`GET /instruments/index-membership/staleness`의 `threshold_days` query
parameter는 기본 정책이 아니라 운영 진단용 명시적 override다. 지정하면
고정 일수 기준으로 판정하고, 지정하지 않으면 기본 정책(달력 기준 6개월)을
사용한다.

관련 원본 런북은
[`docs/10_signal_research_sppv/[RUNBOOK] index_membership_source_package_apply.md`](../10_signal_research_sppv/[RUNBOOK]%20index_membership_source_package_apply.md)다.
이 문서는 해당 런북을 실제 운영자가 순서대로 실행할 수 있도록 보완한다.

## 반영 전 원칙

1. 거래소 구성종목의 실제 기준일을 확인한다. 이 값이 `as_of_date`다.
   다운로드한 날이나 DB 반영일로 임의 대체하지 않는다.
2. 전체 구성종목 목록을 받은 경우, 편입 종목 추가뿐 아니라 편출 종목 종료까지
   반영해야 한다. 이때 `--replace-membership-code-snapshot`을 사용한다.
3. 장중에는 실제 반영을 하지 않는다. 비거래일 또는 거래일 장전 08:50 KST 이전,
   장후 15:30:30 KST 이후에 실행한다.
4. `--apply` 없이 먼저 검증 전용으로 실행한다. 검증 결과가 기준을 만족할 때만
   실제 반영 명령을 실행한다.
5. 운영 DB를 쓰는 마지막 단계는 명시적 `--apply`가 있는 명령뿐이다.

## 입력 파일 구조

모든 파일은 프로젝트 루트의 `data/instrument_master/source/` 아래에 둔다.

```text
data/instrument_master/source/
├── index_membership_source_manifest.json
├── kospi100_constituents.csv
├── kospi200_constituents.csv
├── kosdaq50_constituents.csv          # 받은 경우에만 manifest에 포함
└── kosdaq150_constituents.csv
```

### 1. 지수별 구성종목 CSV

각 CSV에는 최소한 `symbol` 열이 있어야 한다. 종목 코드는 6자리 문자열로 유지한다.
`membership_code` 열을 함께 두어도 되지만, 실제 지수 코드는 manifest의 entry가
결정하므로 필수는 아니다.

예시: `kospi200_constituents.csv`

```csv
symbol
005930
000660
035420
```

다음 항목을 파일 작성 전에 확인한다.

- 종목 코드 앞자리 `0`이 빠지지 않았는지
- ETF, ETN, 우선주 등을 포함할지 거래소 원천 정의와 일치하는지
- 같은 파일 안에 중복 `symbol`이 없는지
- 지수별 파일이 같은 기준일의 구성종목인지

### 2. source package manifest

`index_membership_source_manifest.json`은 구성종목 파일과 원천 근거를 묶는다.
`csv_path`는 manifest 파일이 있는 디렉터리를 기준으로 해석한다.

```json
{
  "source_name": "krx_manual",
  "source_ref": "KRX 구성종목 다운로드 식별값",
  "as_of_date": "2026-08-21",
  "entries": [
    {
      "membership_code": "KOSPI100",
      "csv_path": "kospi100_constituents.csv",
      "note": "거래소 원천 전체 구성종목"
    },
    {
      "membership_code": "KOSPI200",
      "csv_path": "kospi200_constituents.csv",
      "note": "거래소 원천 전체 구성종목"
    },
    {
      "membership_code": "KOSDAQ150",
      "csv_path": "kosdaq150_constituents.csv",
      "note": "거래소 원천 전체 구성종목"
    }
  ]
}
```

작성 기준은 다음과 같다.

| 필드 | 의미 | 작성 기준 |
| --- | --- | --- |
| `source_name` | 원천 종류 | 수동 거래소 다운로드면 `krx_manual` 사용 |
| `source_ref` | 원천 추적 정보 | 다운로드 기준, 공시 식별값, 내부 작업 식별값 중 하나를 기록 |
| `as_of_date` | 구성종목 실제 기준일 | 대시보드 신선도 경고의 기준이 되므로 실제 기준일을 사용 |
| `membership_code` | 지수 코드 | 지원값 네 가지 중 하나만 사용 |
| `csv_path` | 지수별 구성종목 CSV | manifest 기준 상대 경로 또는 절대 경로 |
| `note` | entry별 보조 설명 | 선택 항목 |

`KOSDAQ50` 원천을 받지 않았다면 entry를 추가하지 않는다. 빈 파일을 만들어
전체 스냅샷으로 반영하면 기존 `KOSDAQ50` 편입 데이터를 의도치 않게 모두 종료할 수 있다.

## 실행 환경

명령은 프로젝트 루트에서 실행한다. 운영 DB 접근에는 외부 환경변수를 함께 로드해야 하므로,
실행 중인 `app` 컨테이너가 있다면 아래 형식을 사용한다.

```bash
bash scripts/harness/docker_compose_env.sh exec app \
  python3 scripts/run_index_membership_source_package_pipeline.py [옵션]
```

아래 절차의 명령은 위 공통 접두어 뒤에 붙이는 인자다. 이미 올바른 운영 환경에서
직접 실행하는 경우에는 `python3 scripts/...` 형식으로 바꾸어 실행할 수 있다.

## 단계별 절차

### 1단계: 원천 파일과 manifest 배치

1. 거래소에서 만든 지수별 CSV를 `data/instrument_master/source/`에 둔다.
2. manifest의 `as_of_date`를 실제 구성종목 기준일로 갱신한다.
3. manifest의 각 `csv_path`가 실제 파일명과 일치하는지 확인한다.
4. 이번에 받은 전체 지수만 `entries`에 넣는다.

이 단계에서는 DB가 변경되지 않는다.

### 2단계: 검증 전용 파이프라인 실행

전체 구성종목 스냅샷을 반영하는 표준 검증 명령이다.

```bash
bash scripts/harness/docker_compose_env.sh exec app \
  python3 scripts/run_index_membership_source_package_pipeline.py \
    --manifest data/instrument_master/source/index_membership_source_manifest.json \
    --seed-csv data/instrument_master/source/index_membership_seed.csv \
    --catalog logs/kis_index_category_catalog.json \
    --replace-listed-symbols \
    --replace-membership-code-snapshot
```

이 명령은 아래 네 단계를 순서대로 실행하며, 하나라도 실패하면 이후 단계로 진행하지 않는다.

| 순서 | 실행 내용 | 확인 목적 |
| --- | --- | --- |
| 1 | source package에서 `index_membership_seed.csv` 생성 | 지수별 원천 CSV를 표준 형식으로 정규화 |
| 2 | KIS 카탈로그 alias 검증 | 지수 코드 표기가 유효한지 확인 |
| 3 | instrument master 해상도 검증 | 종목이 DB master에 존재하고 placeholder가 아닌지 확인 |
| 4 | import dry-run | 실제 DB 반영 없이 추가·종료 대상이 계산되는지 확인 |

여기서 생성되는 `index_membership_seed.csv`는 수동 편집 대상이 아니라,
원천 패키지에서 재생성되는 중간 산출물이다.

### 3단계: 검증 결과 판정

다음 조건을 모두 만족해야 실제 반영으로 넘어간다.

- `validate_catalog_alias`가 성공한다.
- `validate_resolution`이 성공한다.
- `unresolved_symbol_count = 0`
- `placeholder_symbol_count = 0`
- dry-run의 `skipped_symbol_count = 0`

실패별 대응은 다음과 같다.

| 실패 | 의미 | 대응 |
| --- | --- | --- |
| catalog alias 실패 | 지수 코드 표기 또는 KIS 카탈로그가 맞지 않음 | `membership_code`와 catalog 파일을 확인 |
| unresolved 종목 | instrument master에 종목이 없음 | instrument master sync를 먼저 수행 |
| placeholder 종목 | 임시 master row에만 연결됨 | 실제 master row 정리 후 재검증 |
| skipped 종목 | import 시 DB 종목을 찾지 못함 | unresolved 원인을 해결한 뒤 재실행 |
| source CSV 형식 실패 | `symbol` 열 누락 또는 파일 경로 오류 | CSV 헤더와 manifest의 `csv_path` 확인 |

### 4단계: 실제 DB 반영

검증을 통과했고 허용 시간대라면, 같은 명령에 `--apply`를 추가한다.

```bash
bash scripts/harness/docker_compose_env.sh exec app \
  python3 scripts/run_index_membership_source_package_pipeline.py \
    --manifest data/instrument_master/source/index_membership_source_manifest.json \
    --seed-csv data/instrument_master/source/index_membership_seed.csv \
    --catalog logs/kis_index_category_catalog.json \
    --replace-listed-symbols \
    --replace-membership-code-snapshot \
    --apply
```

옵션의 의미를 구분해야 한다.

| 옵션 | 동작 | 전체 구성종목 반영 시 사용 여부 |
| --- | --- | --- |
| `--replace-listed-symbols` | CSV에 나온 종목의 active membership 집합을 파일 값으로 교체 | 사용 |
| `--replace-membership-code-snapshot` | CSV에 없는 기존 active 종목도 해당 지수에서 종료 | 사용 |
| `--apply` | 트랜잭션을 실제 커밋 | 실제 반영 시에만 사용 |

전체 목록을 반영할 때 `--replace-listed-symbols`만 사용하면, 이번 CSV에서 빠진
편출 종목이 기존 active membership으로 남는다. 따라서 거래소의 전체 구성종목을
받은 경우에는 두 replace 옵션을 함께 사용한다.

반대로 일부 종목만 추가하는 임시 보강 작업이라면 `--replace-membership-code-snapshot`을
사용하지 않는다. 이 경우 기존 편입 종목 전체가 원천 파일에 포함되지 않았기 때문이다.

### 5단계: 사후 확인

반영 직후 아래를 확인한다.

1. 명령 출력에서 `apply: True`와 `updated_symbol_count`를 확인한다.
2. `deactivated_membership_symbol_count`가 편출 종목 수와 대체로 맞는지 확인한다.
3. 운영 대시보드를 새로고침한다.
   - `as_of_date`가 최신 기준일이면 6개월 초과 경고가 사라져야 한다.
   - 경고의 날짜는 DB의 활성 행 metadata `as_of_date`를 우선 사용한다.
4. 다음 유니버스 freeze 생성 이후, 새 지수 편입 정보가 후보 판정에 반영되는지 확인한다.
5. 문제가 발견되면 즉시 원천 CSV와 manifest를 보존하고, 임의 DB 수정 대신
   정정된 전체 source package로 같은 절차를 다시 실행한다.

## 유니버스 선정과의 관계

지수 편입 데이터는 유니버스 선정의 후보 판정에 다음처럼 쓰인다.

| 편입 코드 | 주 사용처 |
| --- | --- |
| `KOSPI100`, `KOSPI200` | KOSPI 종목의 `core` seed 판정 |
| `KOSDAQ50`, `KOSDAQ150` | KOSDAQ discovery seed 판정 |

이 데이터만으로 모든 선정 규칙이 바뀌지는 않는다. 명시적 `core_universe` metadata와
정적 allowlist는 별도 경로로 계속 적용되며, 유동성·활동성·리스크 등 BUY 경로의
뒤단 판단도 별개로 작동한다.

## 운영 기록 권장 항목

반영 완료 보고에는 최소한 다음을 남긴다.

- 반영 일시와 실행 환경
- `source_name`, `source_ref`, `as_of_date`
- 포함한 지수 코드와 지수별 입력 종목 수
- 검증 결과: unresolved, placeholder, skipped 수
- 반영 결과: updated, deactivated 수
- 대시보드 경고 해소 여부
- 미확인 사항 또는 다음 freeze 확인 필요 여부

## 참고 구현 경로

- 통합 실행기: `scripts/run_index_membership_source_package_pipeline.py`
- 원천 package 정규화: `scripts/build_index_membership_seed_from_source_package.py`
- instrument master 해상도 검증: `scripts/validate_index_membership_seed_resolution.py`
- DB import: `scripts/import_instrument_index_membership_seed.py`
- 대시보드 경고 판단: `src/agent_trading/services/index_membership_staleness.py`
- 유니버스에서의 지수 편입 사용: `src/agent_trading/services/universe_selection.py`
