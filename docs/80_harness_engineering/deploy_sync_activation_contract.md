# Deploy Sync/Activation 계약

## 목적

이 문서는 장중 배포 정책을 `소스 동기화(sync)`와 `활성화(activate)`로 분리할지 검토할 때 기준이 되는 canonical 정책 초안을 정의한다.

현재 배포는 서버 작업트리 갱신, migration, 컨테이너 재기동, proxy reload를 하나의 deploy job으로 묶어 실행한다. 따라서 장중 무승인 상태에서는 소스 반영과 재기동이 함께 차단된다.

이 문서의 목적은 다음 두 가지를 동시에 만족하는 방향을 정리하는 것이다.

- 장중에는 backend/frontend 런타임에 영향을 주는 활성화는 계속 차단한다.
- 재기동과 무관한 변경은 서버 작업트리 동기화만 허용할 수 있도록 경계를 분리한다.

## 용어 정의

### sync

서버 작업트리에 최신 `origin/main` 커밋을 fetch/reset 하여 소스 파일만 반영하는 단계다.

- 포함: `git fetch origin main`, `git reset --hard <sha>`
- 제외: migration, `docker compose up -d`, proxy reload

### activate

sync 이후 실제 런타임에 변경을 반영하는 단계다.

- 포함: `docker compose run --rm migrate`, `docker compose up -d --build --remove-orphans`, `docker exec nginx-proxy nginx -s reload`

## 현재 정책 요약

2026-07-29 기준 `.github/workflows/harness.yml`은 다음 구조다.

- `changes` job이 deploy-relevant 변경 여부를 계산한다.
- `market_hours_guard`가 `Asia/Seoul` 기준 평일 `09:00-15:30` 장중 여부를 계산한다.
- `deploy` job은 `allow_deploy == 1`일 때만 실행된다.
- `deploy` job 안에서 source reset, migration, restart, proxy reload가 함께 실행된다.

즉 장중 무승인 상태에서는 다음 카운트가 모두 `0`이다.

- source sync 실행 수
- migration 실행 수
- 컨테이너 재기동 수

## 2026-07-30 1차 반영 상태

이번 1차 작업에서는 실제 deploy job 분리까지는 하지 않고, CI change detector 계약만 먼저 세분화했다.

- `changes` job이 `activate_required`를 출력한다.
- `changes` job이 `sync_only_candidate_count`, `sync_only_allowlist_count`, `sync_only_blocked_count`를 출력한다.
- 장중 sync-only 허용 대상으로 `docs/` 전체와 `7`개 read-only `scripts/` allowlist, runtime-affecting 경로 denylist를 workflow 정적 규칙으로 선언했다.
- `accept ci`가 위 출력과 정적 규칙 존재 여부를 검사한다.

아직 남아 있는 범위는 다음과 같다.

- `deploy` job을 `sync_source` / `activate_runtime`으로 실제 분리
- 장중에는 `activate`만 차단하고, allowlist 조건을 만족하는 `sync`만 허용
- 신규 실행 지표 `deploy_sync_run_count`, `deploy_activate_run_count` 등 추가

## 2026-07-30 2차 반영 상태

이번 2차 작업에서는 workflow를 실제로 `sync_source` / `activate_runtime` `2`개 job으로 분리했다.

- `sync_source`는 장 종료 후 일반 배포에서 실행된다.
- 장중에도 `activate_required=0`, `sync_only_allowlist_count>0`, `sync_only_blocked_count=0`이면 `sync_source`만 실행할 수 있다. 이 경로에는 `docs/` 변경과 제한된 read-only `scripts/` 변경이 포함된다.
- `activate_runtime`은 `sync_source` 성공 이후, `allow_deploy=1`일 때만 실행된다.
- `activate_runtime`은 `push main`에서는 `activate_required=1`일 때만 실행하고, 수동 `workflow_dispatch + deploy_main=true`는 항상 activate를 허용한다.
- 실행 지표 `deploy_sync_run_count`, `deploy_sync_only_run_count`, `deploy_activate_run_count`, `deploy_activate_skipped_by_market_hours_count`를 추가했다.
- `accept ci`가 `sync_source`, `activate_runtime`, activate guard, 신규 지표 존재 여부를 정적으로 검사한다.

## 2026-07-30 실제 run 검증 결과

GitHub Actions 실제 run으로 다음 `2`개 결과를 확인했다.

- PR `#47`의 `pull_request` run `30503199183`는 `Safe harness contracts=success`, `Deployment change detector=success`, `Heavy harness contracts=skipped`로 끝났다.
- 머지 직후 `push main` run `30503269269`는 같은 `concurrency` 그룹의 수동 dispatch run이 시작되면서 `cancelled` `1`건으로 종료됐다.
- 사용자 승인 하에 실행한 `workflow_dispatch` run `30503269894`는 `conclusion=success`였다.
- 이 dispatch run에서 `Market-hours deploy guard=success`, `Sync source after safe harness=success`, `Activate runtime after source sync=success`를 확인했다.
- 이번 검증은 `deploy_main=true`, `allow_market_hours_deploy=true` override 경로 검증이다. 따라서 장중 sync-only 자동 경로 자체는 아직 별도 샘플 변경으로 검증하지 않았다.
- allowlist 파일만 수정한 PR `#49` 머지 후 `push main` run `30503894901`에서 `Market-hours deploy guard=success`, `Sync source after safe harness=success`, `Activate runtime after source sync=skipped`를 확인했다.
- 즉 장중 자동 경로에서 `sync_source`만 실행되고 `activate_runtime`은 건너뛰는 현재 계약이 실제로 동작했다.
- runtime-affecting 최소 변경 PR `#62` 머지 후 장외 `push main` run `30535699795`에서 `Market-hours deploy guard=success`, `Sync source after safe harness=success`, `Activate runtime after source sync=success`를 확인했다.
- 이 run은 `workflow_dispatch` override 없이 자연 경로로 실행됐고, 남아 있던 장외 activate 실검증 `1`건을 충족했다.

## 남은 실검증 — 장종료 activate 자연 경로

2026-07-30 기준 남은 핵심 실검증은 `1`건이다.

- 장중 override dispatch 경로: 확인 완료
- 장중 sync-only 자동 경로: 확인 완료
- 장종료 activate 자연 경로: 미확인

장종료 activate 자연 경로는 다음 조건을 모두 만족하는 `push main` run `1`건으로 확인한다.

1. KST 기준 평일 `15:30` 이후 또는 장 외 시간대
2. `src/`, `admin_ui/`, `db/`, `docker-compose.yml`, `.github/workflows/` 같은 runtime-affecting 경로 변경 포함
3. 수동 `workflow_dispatch` override 사용 없음

기대 결과:

- `Deployment change detector=success`
- `Safe harness contracts=success`
- `Market-hours deploy guard=success`
- `Sync source after safe harness=success`
- `Activate runtime after source sync=success`
- run `conclusion=success`

실패로 보는 조합:

- 장 외 시간인데 `Activate runtime after source sync=skipped`
- runtime-affecting 변경인데 `Sync source`만 실행되고 `activate_runtime`이 건너뛰어짐
- `workflow_dispatch`가 아닌데 override 지표에 의존한 결과만 남음

권장 최소 샘플 변경:

- backend/runtime 영향이 분명하지만 동작 의미를 바꾸지 않는 문구·주석 수준 변경 `1`건
- 예: `src/` 또는 `admin_ui/src/`의 설명 문자열/주석 보강

권장 기록 항목:

- run id
- KST 실행 시각
- `activate_required`
- `deploy_sync_run_count`
- `deploy_activate_run_count`
- `deploy_market_hours_override_count`

## 권장 목표 상태

장중 정책은 다음처럼 바꾸는 것을 권장한다.

1. `sync`와 `activate`를 별도 job으로 분리한다.
2. 장중 무승인 상태에서는 `activate`만 차단한다.
3. 단, `sync`는 아무 `scripts/` 변경이나 허용하지 않고 allowlist/denylist 기준으로만 허용한다.

핵심 원칙은 다음과 같다.

- `src/`, `admin_ui/`, `db/`, 컨테이너 설정, dependency lockfile은 장중 sync-only 예외 대상이 아니다.
- `scripts/`는 디렉터리 전체 허용이 아니라, 재기동과 무관하고 운영 side effect가 없는 파일만 명시 allowlist로 허용한다.
- read-only 분석/진단 스크립트라도 live broker, 외부 API, 운영 DB write, 스케줄러 기본 경로와 연결되면 기본 허용 대상에서 제외한다.

## 장중 sync-only 허용 판정 기준

다음 조건을 모두 만족해야 장중 sync-only 허용 후보로 본다.

1. running backend/frontend 컨테이너의 import 경로에 직접 영향이 없다.
2. migration, 배포, service bootstrap, scheduler loop, reconciliation worker와 연결되지 않는다.
3. 기본 동작이 order submit, broker call, DB write, external side effect를 수행하지 않는다.
4. 변경이 반영되어도 장중 자동 실행 경로에서 즉시 사용되지 않는다.
5. 사람이 수동 실행하더라도 read-only 분석/진단 성격이 강하다.

위 조건 중 하나라도 불명확하면 장중 sync-only 허용이 아니라 review 또는 차단 대상으로 둔다.

## `/workspace/agent_trading/scripts/` 분류

2026-07-29 기준 top-level `scripts/` 파일 `122`개를 보수적으로 분류하면 다음과 같다.

### A. 장중 sync-only 기본 허용 후보

이 그룹은 read-only 문서 또는 분석/진단 성격이 명확하고, 런타임 활성화와 거리가 있다.

- count=`docs/` 전체 + `7`
- 기준=`docs/**` 전체, `analyze_`, `check_`, `diagnose_`, `observe_`

허용 후보 목록:

- `docs/**`
- `scripts/analyze_trigger_proxy_attribution.py`
- `scripts/check_index_membership_staleness.py`
- `scripts/check_t3_db_status.py`
- `scripts/diagnose_activity_filter_half_period_divergence.py`
- `scripts/diagnose_blocked_reason_distribution.py`
- `scripts/diagnose_market_overlay_shadow.py`
- `scripts/observe_seeded_news_comparison.py`

정책:

- `docs/`는 서버 기준 문서 작업트리 동기화가 필요한 경우를 위해 sync-only 기본 허용 대상으로 둔다.
- 단, `docs/` 변경만으로 runtime activate를 허용하지 않는다.
- 장중 sync-only allowlist 1차 후보로 둘 수 있다.
- 다만 실제 실행 허용과 동일시하지 않는다. 배포 허용과 운영 실행 허용은 별도 정책이다.

### B. 장중 sync-only review 대상

이 그룹은 batch/research 성격이 강하지만, live broker·smoke·운영 검증·출력 생성 가능성이 섞여 있어 디렉터리 단위 허용이 위험하다.

- count=`70`
- 기준 prefix=`evaluate_`, `validate_`, `verify_`, `shadow_`, `replay_`, `ei_`

대표 예시:

- `scripts/evaluate_intraday_operational_validation.py`
- `scripts/evaluate_kis_live_combined_submit_smoke.py`
- `scripts/evaluate_kis_live_readonly_smoke.py`
- `scripts/evaluate_kis_live_submit_preflight.py`
- `scripts/validate_seeded_news_pipeline.py`
- `scripts/verify_order_truth.py`

정책:

- 기본 허용하지 않는다.
- 개별 파일 검토 후 read-only 성격이 명확한 항목만 별도 allowlist로 승격한다.
- `live`, `smoke`, `preflight`, `operational`, `store`, `truth` 같은 키워드가 있으면 우선 차단한다.

### C. 장중 sync-only 기본 차단

이 그룹은 재기동 여부와 별개로 운영 side effect 또는 scheduler 기본 경로에 연결될 가능성이 높다.

- count=`45`

세부 구성:

| 그룹 | count | 예시 | 기본 판정 |
| --- | ---: | --- | --- |
| `run_*` | 12 | `run_decision_loop.py`, `run_ops_scheduler.py` | 차단 |
| `sync_*` | 3 | `sync_kis_snapshots.py` | 차단 |
| `backfill_*` | 8 | `backfill_reconcile_required_orders.py` | 차단 |
| `seed_/import_/cleanup_/retry_/deploy_/start_/inject_/reconcile_/monitor_/operations_` | 13 | `deploy_broker_truth_sync.sh`, `start_with_prod_creds.sh`, `operations_day_run_evaluation_store.py` | 차단 |
| `build_/generate_/export_/ar_fdc_*` | 8 | `generate_signal_feature_snapshot_input.py`, `build_signal_feature_snapshots.py` | 차단 |
| 기타 | 1 | `tmp_active_core_risk_off_distribution.py` | 차단 |

차단 이유:

- scheduler/worker/bootstrap 경로와 연결될 수 있다.
- DB write, canonical 입력 재생성, external side effect, 운영 계정 실행 경로를 포함할 수 있다.
- 장중 source sync만 허용해도 다음 batch 실행 시 즉시 운영 동작이 바뀔 수 있다.

## 권장 allowlist 형태

장중 sync-only 허용은 원칙적으로 파일 allowlist로 유지하되, `docs/`는 runtime activate와 분리된 문서 작업트리 동기화 목적에 한해 디렉터리 예외로 허용한다.

1차 권장 allowlist:

- `scripts/analyze_trigger_proxy_attribution.py`
- `scripts/check_index_membership_staleness.py`
- `scripts/check_t3_db_status.py`
- `scripts/diagnose_activity_filter_half_period_divergence.py`
- `scripts/diagnose_blocked_reason_distribution.py`
- `scripts/diagnose_market_overlay_shadow.py`
- `scripts/observe_seeded_news_comparison.py`

추가 allowlist는 다음 검토를 통과해야 한다.

- live broker 호출 없음
- DB write 없음
- scheduler 기본 경로와 무관
- canonical 입력 자동 재생성 없음
- `start_`, `deploy_`, `run_`, `sync_`, `backfill_` 계열 아님

## `harness.yml` 개편안

### 1. `changes` job 출력 분리

기존 `deploy_required` 외에 다음 출력을 권장한다.

- `activate_required`
- `sync_only_candidate_count`
- `sync_only_allowlist_count`
- `sync_only_blocked_count`

개념:

- `activate_required=1`: runtime-affecting 경로 변경이 하나라도 있음
- `sync_only_allowlist_count>0`: 장중 sync-only 허용 후보 파일 변경이 있음 (`docs/` 또는 제한된 read-only `scripts/`)
- `sync_only_blocked_count>0`: `scripts/` 변경이지만 allowlist 밖이라 장중 sync-only로 허용하면 안 됨

### 2. runtime-affecting 경로 denylist

다음 경로는 장중 sync-only 예외 대상이 아니다.

- `src/**`
- `admin_ui/**`
- `db/**`
- `docker-compose.yml`
- `Dockerfile`
- `admin_ui/Dockerfile`
- `admin_ui/nginx.frontend.conf`
- `pyproject.toml`
- `requirements.lock`
- `admin_ui/package-lock.json`
- `.github/workflows/**`

### 3. sync job 분리

권장 job 이름:

- `sync_source`
- `activate_runtime`

권장 흐름:

1. `safe` 성공
2. `changes`가 `activate_required`와 allowlist 카운트 계산
3. `sync_source`는 아래 조건에서 실행
   - 장 종료 후 일반 deploy
   - 또는 장중이지만 `activate_required=0` 이고 `sync_only_blocked_count=0` 이며 `sync_only_allowlist_count>0`
4. `activate_runtime`는 아래 조건에서만 실행
   - `activate_required=1`
   - `market_hours_guard.allow_deploy == 1`

### 4. 장중 동작 원칙

장중 무승인일 때:

- `sync_only_allowlist_count>0` 이고 `activate_required=0` 이면 `sync_source` 실행 가능
- `activate_runtime`는 실행하지 않음
- `deploy_activate_skipped_by_market_hours_count=1` 출력

장중 승인일 때:

- `workflow_dispatch + deploy_main=true + allow_market_hours_deploy=true`
- `sync_source`, `activate_runtime` 둘 다 실행 가능

### 5. 권장 지표

신규 지표 권장값:

- `deploy_sync_run_count`
- `deploy_activate_run_count`
- `deploy_sync_only_allowlist_count`
- `deploy_sync_only_blocked_count`
- `deploy_activate_skipped_by_market_hours_count`
- `deploy_sync_only_run_count`

## `accept ci` 후속 확장안

정책을 구현하면 `accept ci`에 다음 정적 검사를 추가하는 것을 권장한다.

- `deploy_sync_job_present_count`
- `deploy_activate_job_present_count`
- `deploy_sync_only_allowlist_defined_count`
- `deploy_runtime_affecting_path_rule_count`
- `deploy_activate_guard_present_count`

실패 조건 예시:

- runtime-affecting 경로 변경인데 activate guard 없이 장중 실행 가능
- `scripts/` 전체 허용처럼 broad allow가 설정됨
- sync-only allowlist 밖의 `scripts/` 변경이 장중 자동 sync 대상이 됨

## 결론

권장 방향은 다음과 같다.

- 장중 정책을 “배포 전체 차단”에서 “activate 차단, 제한된 sync-only 허용”으로 세분화한다.
- 단, `scripts/`는 폴더 단위 예외가 아니라 파일 allowlist로만 허용한다.
- 현재 `/workspace/agent_trading/scripts/`에서는 위 `7`개 read-only 분석/진단 파일만 1차 sync-only 허용 후보로 보는 것이 가장 보수적이다.

## 관련 문서

- [`no_bypass_policy.md`](no_bypass_policy.md)
- [`runtime_artifact_policy.md`](runtime_artifact_policy.md)
- [`canonical_data_contract.md`](canonical_data_contract.md)
- [`../40_action_plans/harness_post_recommendation_action_plan.md`](../40_action_plans/harness_post_recommendation_action_plan.md)
