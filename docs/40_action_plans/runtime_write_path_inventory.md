# Runtime Write Path 추적 파일 분류

## 목적

이 문서는 `logs/`, `tmp/`, `data/` 아래에 Git이 추적 중인 파일을 런타임 산출물 보호 관점에서 분류한다.

배포 작업에서 `git reset --hard origin/main`은 tracked 파일을 되돌릴 수 있으므로, 런타임 중 쓰이는 파일은 Git 추적 대상에서 제외해야 한다. 반대로 seed, fixture, canonical 입력 데이터는 무조건 제외하면 재현성이 깨질 수 있다.

## 현재 추적 파일 수

| 경로 | tracked 파일 수 | 1차 판정 | 권고 |
| --- | ---: | --- | --- |
| `logs/` | 2560 | 런타임·분석 산출물 | 전체 `git rm --cached -r logs` 후보 |
| `tmp/` | 55 | 임시 스크립트·검증 산출물 혼재 | 전체 추적 제외 후보, 보존 필요 파일은 정식 경로로 이동 |
| `data/` | 72 | seed/canonical 입력과 산출물 혼재 | 전체 제외 금지, 하위 경로별 분류 후 처리 |
| 합계 | 2687 | 혼재 | 단계적 정리 필요 |

## `logs/` 분류

| 분류 | 파일 수 | 근거 | 권고 |
| --- | ---: | --- | --- |
| 루트 로그·분석 산출물 | 2384 | `logs/*` depth 2 | Git 추적 제외 |
| bars cache | 176 | `logs/_bars_cache_core87_3y_2026-07-14/`, `logs/_bars_cache_core88_2026-07-14/` | Git 추적 제외. 재현성 필요 시 별도 fixture 또는 artifact 정책 필요 |
| nested non-cache | 0 | cache 외 depth 3 이상 없음 | 추가 조치 없음 |

확장자별 카운트:

| 확장자 | 파일 수 |
| --- | ---: |
| `.log` | 2195 |
| `.json` | 354 |
| `.sh` | 2 |
| `.jsonl` | 2 |
| `.bak` | 2 |
| `.txt` | 1 |
| `.sandbox_write_test` | 1 |
| `.py` | 1 |
| `.out` | 1 |
| `.md` | 1 |

Codex 추천안:

- `logs/`는 전체를 런타임·분석 산출물로 보고 Git 추적에서 제거한다.
- 추적 제거 전에 문서가 직접 참조하는 로그 파일이 있는지 검사하고, 재현성에 필요한 파일은 `tests/fixtures/` 또는 `docs/90_reference/`로 이동한다.
- 운영 서버 배포에서는 `logs/`를 삭제하지 않고 untracked/ignored runtime path로 유지한다.

## `tmp/` 분류

| 분류 | 파일 수 | 근거 | 권고 |
| --- | ---: | --- | --- |
| 임시 Python 스크립트 | 40 | `.py` | 기본 추적 제외. 계속 필요한 것은 `scripts/` 또는 `tests/`로 이동 |
| 결과·백업·패치 파일 | 15 | `.csv`, `.json`, `.log`, `.patch`, `.md` | 기본 추적 제외. 보고서 근거는 `docs/30_work_log/` 또는 `docs/90_reference/`로 이동 |

Codex 추천안:

- `tmp/`는 전체를 Git 추적에서 제거한다.
- `tmp/naver_daily_quota.json` 같은 운영 중 mutable 파일은 `tmp/` ignore에 포함되므로 별도 패턴을 유지하지 않는다.
- 단, 운영에서 반드시 필요한 mutable 파일은 컨테이너/서비스 시작 시 없을 때 생성되도록 코드 또는 운영 절차를 확인해야 한다.

## `data/` 분류

| 분류 | 파일 수 | 근거 | 권고 |
| --- | ---: | --- | --- |
| `data/instrument_master/` | 42 | 종목 마스터 source/archive/normalized | 바로 삭제 금지. seed/canonical 여부 분류 |
| `data/observations/` | 6 | 관측 결과 JSON | 산출물 후보. 필요 시 `docs/90_reference/`로 이동 |
| `data/` 루트 JSON | 24 | signal snapshot, trigger proxy attribution, AR FDC 자료 | 산출물·입력 혼재. 파일별 분류 필요 |
| `data/runtime/`, `data/cache/`, `data/local/` | 0 | 신규 mutable 하위 경로 | 앞으로 런타임 쓰기 위치로 사용 |

Codex 추천안:

- `data/` 전체를 `.gitignore`에 넣지 않는다.
- 신규 런타임 쓰기는 `data/runtime/`, `data/cache/`, `data/local/`로 모으고 이 하위 경로만 ignore한다.
- `data/instrument_master/source/*.example.*`처럼 재현성에 필요한 예제 파일은 계속 추적한다.
- 날짜별 archive와 분석 산출물은 운영 런타임에 필요한지 확인한 뒤, 필요 없으면 Git 추적에서 제거하거나 reference 문서 경로로 이동한다.

## 후속 정리 순서

1. `logs/`를 참조하는 문서·테스트·스크립트 목록을 산출한다.
2. `tmp/`의 `.py` 중 정식 스크립트 또는 테스트로 승격할 파일이 있는지 확인한다.
3. `data/instrument_master/`의 source, normalized, archive를 seed/canonical/runtime 산출물로 분류한다.
4. 사용자 승인 후 `git rm --cached` 또는 경로 이동 PR을 분리한다.
5. 정리 후 `runtime_tracked_file_count`를 실패 지표로 전환한다.

## 사용자 결정 필요 항목

Codex 추천안은 다음과 같다.

- `logs/`: 전체 추적 제외.
- `tmp/`: 전체 추적 제외.
- `data/`: 전체 추적 제외 금지. 하위 경로별 분류 후 `data/runtime/`, `data/cache/`, `data/local/`만 기본 ignore.

이유:

- `logs/`와 `tmp/`는 운영 중 변하는 산출물이므로 배포 작업 트리와 분리해야 한다.
- `data/`에는 종목 마스터, seed, example, snapshot 입력이 섞여 있어 전체 ignore 시 테스트·운영 재현성이 깨질 수 있다.
- tracked 파일 `2687`개를 한 번에 제거하면 PR이 커지고 오판 위험이 크므로, 경로별 PR로 나눠야 한다.
