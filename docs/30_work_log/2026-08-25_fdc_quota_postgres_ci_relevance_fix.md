# FDC quota PostgreSQL 전용 CI relevance detector 보정(PR #351)

## 1. 기존 `HEAD^` 판정의 누락 시나리오

`fdc_quota_postgres_relevant` job의 1차 구현은 `git diff --name-only
HEAD^ HEAD`로 **마지막 커밋 1개**만 봤다. 다음 순서로 PR을 만들면
누락된다.

1. `src/agent_trading/repositories/postgres/fdc_quota.py`(또는 migration)
   를 수정하는 커밋을 push한다.
2. 이어서 문서만 고치는 커밋을 추가 push한다(또는 그런 상태로 PR을 연다).
3. `HEAD^..HEAD`는 마지막 문서 커밋만 비교하므로 `matched_file_count=0`
   → `relevant=0`으로 잘못 판정한다.
4. 실제로는 PR 전체에 FDC quota SQL 변경이 있는데도 PostgreSQL 통합
   job이 실행되지 않는다.

`scripts/harness/test_detect_fdc_quota_postgres_relevance.sh`의 "대조
확인" 블록으로 이 결함이 실재했음을 직접 재현해 증명했다(HEAD^ 기준
비교 시 `matched_file_count=0`이 실제로 나옴).

## 2. 이벤트별 base ref/SHA와 비교 범위

| 이벤트 | base ref | 비교 범위 |
|---|---|---|
| `pull_request` | `github.event.pull_request.base.sha` | `base_sha..HEAD` |
| `push` | `github.event.before` | `before..HEAD` |
| `workflow_dispatch` | 해당 없음 | 항상 `relevant=1` |

판정 로직 자체는 `scripts/harness/detect_fdc_quota_postgres_relevance.sh`
(GitHub Actions 컨텍스트에 의존하지 않는 순수 bash)로 분리했다 —
workflow 스텝은 위 표의 base ref만 계산해 이 스크립트에 넘긴다.
`actions/checkout`은 `fetch-depth: 0`으로 바꿨다(가장 단순하고 안전한
방식 — PR base SHA가 얕은 checkout 때문에 로컬에 없어 비교 자체가
불가능해지는 사고를 막는다).

## 3. base SHA 부재 시 fail-closed/보수적 fallback 정책과 근거

**보수적 fallback(`relevant=1`)을 선택했다** — base ref가 빈 문자열이거나
(`push` 이벤트의 all-zero SHA 등) 로컬 저장소에 존재하지 않으면(예상치
못한 fetch-depth 부족) 판정을 포기하고 PostgreSQL 전용 job을 실행한다.

근거: 이 job은 `tests/services/test_fdc_quota_coordinator.py` 한 파일만
검증하는 매우 가벼운 job(관련도 판정 ~5초 + 통합 테스트 ~1분, 실측
기준)이라, 판정 불가 상황에서 불필요하게 한 번 더 실행하는 비용은
무시할 만하다. 반대로 fail-closed(관련 없음으로 간주해 `relevant=0`)를
선택하면, base ref 계산이 실패하는 예외적 상황(강제 push, rebase 후
force-push, GitHub Actions의 `before`가 `0000...0`인 브랜치 최초 push
등)에서 실제 FDC quota 변경이 있어도 조용히 검증을 건너뛰는 최악의
결과가 된다 — "검증을 놓치는 것보다 한 번 더 도는 것이 낫다"는 원칙에
따라 보수적 fallback을 선택했다. CI 실패로 막는 방안(명확한 실패)도
검토했으나, base ref 계산 실패는 사용자 코드 변경과 무관한 환경적
요인(강제 push 등)으로도 발생할 수 있어 매번 사람이 개입해야 하는
CI 실패보다는 자동으로 안전한 쪽(더 자주 검증)으로 넘어가는 fallback이
운영 부담이 적다고 판단했다.

## 4. 4개 판정 시나리오 검증 결과

`bash scripts/harness/test_detect_fdc_quota_postgres_relevance.sh`가
임시 git 저장소(fixture repo)를 만들어 아래를 포함한 10개 케이스를
검증했다(전부 PASS).

1. PR 전체 범위에 `fdc_quota.py` 변경 + 마지막 커밋은 문서만 →
   `relevant=1`(대조로 `HEAD^` 기준이면 `matched_file_count=0`이 되어
   결함이 실재했음도 같이 증명).
2. PR 전체 범위에 migration sql 변경 + 마지막 커밋은 무관한 파일 변경 →
   `relevant=1`.
3. PR 전체 범위에 관련 파일이 전혀 없음 → `relevant=0`.
4. `workflow_dispatch` → 관련 파일 여부와 무관하게 `relevant=1`.
5. (추가) `base_ref`가 빈 문자열(예: `push` 최초 커밋) → 보수적
   fallback `relevant=1`(fail-open으로 `relevant=0`이 아님을 확인).
6. (추가) `base_ref`가 로컬에 없는 SHA(all-zero 포함) → 보수적 fallback
   `relevant=1`.
7. (추가) 로그 출력에 필수 필드(`event_name`/`base_ref`/`head_ref`/
   `compare_range`/`changed_file_count`/`matched_file_count`/`relevant`)
   전부 존재 + URL/비밀값으로 의심되는 문자열 없음.

실행 방식: 워크플로 YAML 안에서만 가능한 방식이 아니라, 판정 로직
자체를 별도 스크립트로 분리해 fixture git 저장소로 로컬에서 직접
재현·검증했다(`test_docker_compose_env_git_sha.sh`와 동일한 관례).

## 변경 파일

- `.github/workflows/harness.yml`(`fdc_quota_postgres_relevant` job을
  이벤트별 base ref 계산 + 분리된 스크립트 호출로 교체, checkout
  `fetch-depth: 0`)
- `scripts/harness/detect_fdc_quota_postgres_relevance.sh`(신규,
  판정 로직 순수 bash 분리)
- `scripts/harness/test_detect_fdc_quota_postgres_relevance.sh`(신규,
  fixture git 저장소 기반 단위 테스트)
- `scripts/harness/README.md`(신규 스크립트/보정 배경 설명 추가)
- `docs/99_meta_handover/[BACKLOG] backlog.md`
- 본 문서(신규)

## 실행한 검증 명령과 결과

| 명령 | 결과 |
|---|---|
| `bash scripts/harness/test_detect_fdc_quota_postgres_relevance.sh` | PASS(`pass=10 fail=0`) |
| `accept ci` | PASS |
| `accept style` | PASS |
| `accept docs` | PASS |
| `accept no-bypass` | PASS(`hard_bypass_count=0`) |

실제 GitHub Actions 재실행 결과(relevance detector PASS, PostgreSQL
통합 테스트 실제 실행/pass-skip 수, Safe/Heavy 영향 여부)는 완료
보고에 별도 기재한다.

## 미검증 가정

- fork에서 열린 PR(`pull_request` 이벤트의 base가 다른 저장소 브랜치인
  경우)에서 `fetch-depth: 0`이 base SHA를 항상 로컬에 가져오는지는
  이번 턴에서 실제로 fork PR을 만들어 검증하지 않았다 — 코드 검토
  기준으로는 `actions/checkout`이 `pull_request` 이벤트에서 기본적으로
  merge ref를 체크아웃하고 `fetch-depth: 0`이면 그 저장소의 전체 이력을
  가져오므로 base SHA도 포함될 것으로 예상하나, 실측 확인은 fork PR이
  생겨야 가능하다. 그 경우에도 base ref를 찾지 못하면 보수적 fallback
  (`relevant=1`)이 적용되므로 최악의 경우도 "검증을 더 자주 돈다"이지
  "검증을 놓친다"가 아니다.
