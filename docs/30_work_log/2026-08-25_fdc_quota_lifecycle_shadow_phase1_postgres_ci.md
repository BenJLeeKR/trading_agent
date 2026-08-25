# FDC cycle-scoped batch queue Phase 1(lifecycle shadow) — PostgreSQL 전용 좁은 CI 경로 추가(PR #351)

## 배경

Phase 1 shadow FIFO 보정(1차·2차)의 PostgreSQL 통합 테스트
(`TestPostgresAtomicReservation`, `TestPostgresShadowFifoQueue`)는 로컬
샌드박스(`DATABASE_HOST` 없음)와 자동 CI(`Safe harness contracts`는
전체 pytest를 실행하지 않음) 양쪽에서 계속 skip 상태였다. 수동
`workflow_dispatch(run_heavy=true)`도 시도했으나, `full-test`가 전체
`pytest tests/ -v`를 돌리다 `HEAVY_TIMEOUT_SECONDS=900`에 걸려 알파벳순
약 19%(`tests/brokers/...`)에서 타임아웃돼 대상 테스트에 도달하지
못했다. 이 문서는 전체 heavy suite를 건드리지 않고, 이번 PR이 새로
추가한 PostgreSQL SQL(migration/anchor 행 잠금/shadow FIFO)만 실제
PostgreSQL에서 검증하는 좁은 CI 경로를 추가한 내역을 기록한다.

## 1. 기존 CI/harness 관례 조사 결과

1. **pinned PostgreSQL을 쓰는 기존 job**: `.github/workflows/harness.yml`
   의 `safe` job이 `docker run --detach --name trading_db ...
   postgres:$(cat .postgres-version)`로 컨테이너를 띄운다. 그러나 포트를
   publish하지 않고(`-p` 옵션 없음), 이후 어떤 단계도 `DATABASE_HOST`를
   설정하지 않는다 — 이 컨테이너는 `docker exec`로 버전만 확인하는
   용도(`accept env`)일 뿐, 실제 pytest가 이 DB에 연결한 적이 없다.
   `heavy` job은 PostgreSQL 컨테이너 자체가 없다.
2. **단일 파일을 PostgreSQL 환경에서 실행하는 기존 harness 명령**:
   `scripts/harness/run.sh test-file <file>`이 이미 존재하고, `WORKSPACE_
   ROLE=ci`(즉 `HARNESS_CI=1`)일 때 `run_python_with_timeout()`이
   `agent_trading-app-1` 컨테이너가 없으면(CI 러너에는 없음) **host
   python3로 직접 `python3 -m pytest <file> -v`를 실행**한다(코드 확인:
   `scripts/harness/run.sh:156-176`). 즉 CI job의 step `env:`에 `DATABASE_
   HOST` 등을 설정하기만 하면 `test-file`이 그 값을 그대로 상속해
   pytest에 전달한다 — **harness 명령 자체를 바꿀 필요가 전혀 없다.**
3. **migration runner의 기존 CI 관례**: 별도의 "migration 적용" harness
   명령은 없다. 대신 `tests/services/test_fdc_quota_coordinator.py`의
   `db_ready` fixture(`tests/repositories/test_postgres_blocking_locks.py`
   와 동일 패턴)가 `create_pool()` + `run_all_migrations()`를 테스트
   실행 시점에 직접 호출해 전체 migration(0068 포함)을 적용한다 — 이
   fixture가 이미 "CI 전용 DB에 migration 적용"을 담당하므로 워크플로
   레벨에서 별도 migration 스텝을 추가할 필요가 없다.
4. **PR 파일 변경 감지 규칙**: 기존 `changes` job이 `deploy_required`/
   `activate_required` 등을 판정하지만, 그 출력을 재사용하면 배포 게이트
   로직에 새 의존을 얹는 위험이 있다. 이번 좁은 job은 완전히 독립된
   `fdc_quota_postgres_relevant` job(자체 git diff 판정)을 신설해
   `changes` job의 계약을 전혀 건드리지 않았다.

## 2. 선택한 구현 방식(B)과 이유

**B(harness 명령 유지 + workflow에 전용 job 추가)**를 선택했다.
`test-file`이 CI 환경에서 이미 host python3로 직접 실행되고 job의
`env:`로 주입한 `DATABASE_*`를 그대로 상속하므로, A안(harness에 새
`test-file-postgres` 명령 추가)이 하려는 일(연결 확인·migration 적용·
대상 파일 실행)을 harness 코드 변경 없이도 workflow job 구성만으로
전부 만족한다. `require_safe_test_selector()`도 `tests/services/*`를
이미 허용하므로 harness 쪽 승인 로직도 변경이 필요 없었다. 이는
"기존 `scripts/harness/run.sh` 진입점을 우선 재사용하라"는 지시와 가장
직접적으로 일치하며, harness 스크립트 자체의 변경 범위를 0으로 유지해
회귀 위험을 최소화한다.

## 3. PostgreSQL 전용 job의 정확한 실행 대상 및 DB 격리 방식

- 실행 대상: `bash scripts/harness/run.sh test-file tests/services/
  test_fdc_quota_coordinator.py` — 이 한 파일만, 다른 어떤 테스트 파일도
  실행하지 않는다.
- DB 격리: `docker run --detach --name trading_db_fdc_quota_ci --publish
  127.0.0.1:5432:5432 ...postgres:$(cat .postgres-version)`로 이 job
  전용 ephemeral 컨테이너를 새로 띄운다 — `safe` job의 `trading_db`
  컨테이너와 이름이 다르고, 서로 다른 job(=서로 다른 GitHub Actions
  러너 VM)에서 실행되므로 물리적으로도 격리된다. `DATABASE_HOST=127.0.0.1`
  로 이 컨테이너만 가리키며, 운영 DB·운영 컨테이너·`.env`는 이 job
  어디에서도 참조하지 않는다. job 마지막 단계(`if: always()`)에서
  `docker rm -f trading_db_fdc_quota_ci`로 컨테이너 자체를 폐기한다.

## 4. skip을 실패 처리하는 방법

`test-file` 명령의 exit code(0)만으로는 skip 여부를 알 수 없으므로
(pytest는 skip이 있어도 실패 아니면 exit 0), 출력을 `tee`로 파일에
저장한 뒤 pytest 최종 요약 줄에서 `"N skipped"` 패턴을 `grep`으로
직접 파싱한다. `N != 0`이면 `::error::`로 원인(`DATABASE_HOST` 미전달
가능성)을 명시하고 `exit 1`로 job 자체를 실패시킨다 — exit code만
보고 통과시키지 않는다는 요구사항을 그대로 구현했다.

## 5. migration 적용 범위가 CI 전용 DB임을 증명하는 근거

- `db_ready` fixture는 `agent_trading.db.connection.create_pool()`을
  호출하며, 이 함수는 `DATABASE_HOST` 등 환경변수로만 접속 대상을
  결정한다(`src/agent_trading/db/connection.py:38-66`, 하드코딩된 호스트
  없음). job의 `env:`가 `DATABASE_HOST=127.0.0.1`(방금 띄운 `trading_db_
  fdc_quota_ci`)로 고정돼 있으므로, `run_all_migrations()`가 적용하는
  대상은 오직 이 컨테이너다.
- 운영 DB 접속 정보(`DATABASE_HOST`가 운영 호스트를 가리키는 값)는 이
  job의 `env:`/`secrets` 어디에도 등장하지 않는다 — 이 job은 `.env`나
  운영 secret을 전혀 참조하지 않는 완전히 독립된 hardcoded 로컬 값
  (`trading`/`trading`/`trading`)만 쓴다.
- job 종료 시 컨테이너 자체를 삭제하므로, migration이 적용된 상태가
  다음 실행에 남지 않는다(매 실행마다 빈 DB에서 새로 시작).

## 6. anchor 행 fail-open 결함 보정(부수 발견, 이번 PR 범위 포함)

PostgreSQL 전용 검증 경로를 준비하면서 `try_reserve()`/`register_
shadow_job_and_judge()`의 `SELECT ... FOR UPDATE` 결과를 재검토한 결과,
anchor 행이 없을 때(migration/seed 불완전) 두 메서드 모두 `fetchrow()`의
`None` 반환을 확인하지 않고 그대로 다음 쿼리로 진행하는 결함을
발견했다 — `FOR UPDATE`는 대상 행이 없으면 아무것도 잠그지 못하고
조용히 통과하므로, 이 상태에서는 직렬화(새치기 방지) 보장 없이 quota
판단/소비가 fail-open으로 진행될 수 있었다.

**보정**: 두 메서드 모두 anchor 행 조회 직후 `None` 체크를 추가해,
없으면 즉시 롤백 후 `CoordinatorError(COORDINATOR_TRANSACTION_ERROR, ...)`
를 반환하도록 했다(기존 3-분류 enum 재사용, 새 enum 값 추가 없음 —
Protocol/contracts 표면적 변경 없이 구현 파일 내부 로직만 보정). 신규
테스트 `TestPostgresAnchorRowFailClosed`(2건)로 seed되지 않은
quota_scope에 대해 real/shadow 양쪽 경로 모두 `CoordinatorError`를
반환하고 어떤 행도 삽입되지 않음을 확인한다.

## 6.5 실제 CI 1차 실행에서 발견한 loop_scope 결함(부수 발견 2)

신규 job을 push한 뒤 실제 GitHub Actions에서 처음 실행했을 때, 13개
PostgreSQL 통합 테스트가 skip 없이 실제로 실행됐지만 전부
`RuntimeError: ... attached to a different loop` /
`asyncpg.exceptions._base.InterfaceError: cannot perform operation:
another operation is in progress`로 실패했다. 원인은 `pyproject.toml`의
`asyncio_default_fixture_loop_scope = "module"`과 테스트 자체의 기본
loop scope("function")가 불일치해, `quota_scope`/`db_ready`
fixture(둘 다 평범한 `@pytest.fixture`)가 만든 asyncpg pool이 테스트
함수의 이벤트 루프와 다른 루프에 묶였기 때문이다 — 이 테스트들이
`DATABASE_HOST` 없이는 한 번도 실제로 실행된 적이 없어서 지금까지
발견되지 못했던 결함이다.

**보정**: 이 두 fixture만 `@pytest_asyncio.fixture(loop_scope="function")`
로 명시해 테스트와 같은 이벤트 루프를 쓰도록 고쳤다 — 프로젝트 전역
`asyncio_default_fixture_loop_scope` 설정은 바꾸지 않았다(다른 테스트
파일에 미치는 영향을 예측할 수 없어 이번 PR 범위 밖으로 남김).
`tests/conftest.py`의 `postgres_repos`/`seeded_postgres_data`도 동일한
평범한 `@pytest.fixture` 패턴이라 같은 결함 가능성이 있으나, 그 fixture는
이 job이 쓰는 파일에서 쓰이지 않고 확인 범위 밖이라 별도 백그라운드
점검 작업으로 분리했다(수정하지 않음).

## 완료 보고 형식에 따른 나머지 항목

### 7. 변경 파일 목록

- `.github/workflows/harness.yml`(`fdc_quota_postgres_relevant`/`fdc_
  quota_postgres_integration` job 신설)
- `scripts/harness/README.md`(신규 job 설명 추가)
- `src/agent_trading/repositories/postgres/fdc_quota.py`(anchor 행
  fail-closed 보정, 2곳)
- `tests/services/test_fdc_quota_coordinator.py`(신규 테스트 5건:
  `test_14th_queued_state_unaffected_by_interleaved_real_reservation`,
  `test_real_reservations_do_not_affect_shadow_13_judgement`,
  `TestPostgresAnchorRowFailClosed` 2건 — 정렬 재생 검증은 이전 턴에서
  이미 추가한 `test_sequential_replay_in_true_fdc_ready_order_grants_
  by_that_order`가 담당)
- 본 문서(신규)

### 8. 실행한 harness와 결과

| 명령 | 결과 |
|---|---|
| `test-file tests/services/test_fdc_quota_coordinator.py`(로컬, DATABASE_HOST 없음) | 15 passed, 13 skipped(신규 5건 포함 전부 정상 skip) |
| `accept backend-file src/agent_trading/repositories/postgres/fdc_quota.py` | PASS |
| `accept ci` | PASS(`ci_contract_failed_count=0`) |
| `accept db-structure` | PASS |
| `accept architecture` | PASS |
| `accept no-bypass` | PASS(`hard_bypass_count=0`) |
| `accept style` | PASS |
| `accept docs` | PASS |

실제 GitHub Actions 실행 결과(6번 항목 상세)는 최종 완료 보고에 별도
기재한다 — PR #351에 push 후 `fdc_quota_postgres_relevant`/`fdc_quota_
postgres_integration` job의 실제 실행/skip 카운트를 확인한다.

### 9. 미검증 가정

- 새 job의 anchor-fail-closed 테스트는 host 환경에 프로젝트 의존성
  (asyncpg 등)이 없어 로컬에서 실제 PostgreSQL로 사전 검증하지 못했다
  — 이 fix가 실제 PostgreSQL에서 최초로 실행되는 시점은 이번 PR
  push 후의 CI 실행이다.
- 두 신규 job이 PR마다 추가로 소비하는 GitHub Actions 러너 시간(컨테이너
  기동 ~수 초 + 24개 테스트 실행)은 실측하지 않았다 — `safe`/`heavy`
  대비 훨씬 가벼울 것으로 예상하나 확인 필요.
