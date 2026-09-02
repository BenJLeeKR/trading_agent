# FDC actual dispatch — BUY/core lane 확장 설계 (2026-09-01)

> **상태**: 설계 문서 초안, 5차 보정(2026-09-01). 코드/설정/DB/운영 상태
> 변경 없음. 이 문서 자체가 이번 작업의 유일한 산출물이다.
>
> **선행 문서**: `docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_
> shared_13rpm_quota_design_2026-08-25.md`(이하 "원 설계 문서") — held_
> position REDUCE_CANDIDATE/SELL_CANDIDATE 실전 전환(PR #359)과 그 보정
> (PR #360, #361)의 근거 문서. 이 문서는 그 §15 "③ 전체 lane 전환" 단계를
> 구체화한다.

## 1. 목적, 범위, 비범위

### 목적

`FDC_ACTUAL_DISPATCH_ENABLED`(held_position REDUCE/SELL_CANDIDATE 전용)가
이미 운영 검증된 상태에서, 같은 공용 quota coordinator 인프라를 BUY/core
lane에도 안전하게 재사용할 수 있는 **구현 가능한** 설계를 확정한다. 직전
read-only 조사(별도 세션)에서 나온 권고안("일부 BUY 조건만 확장, 별도
quota_scope 파일럿")에 대해 리뷰에서 아래 두 결함이 지적됐고, 이 문서는
그 결함을 코드 근거로 재검토해 수정한다.

1. **quota_scope 분리안의 결함**: 별도 scope를 만들면 `try_reserve()`의
   60초 sliding window 판정이 **scope별로 완전히 독립**적으로 계산되므로
   (근거는 §4), held_position scope와 BUY scope가 각자 13 RPM까지 grant를
   허용하면 Gemini 실제 계정 한도(선언 15 RPM)를 합산 기준으로 초과할 수
   있다. 또한 새 scope는 `trading.fdc_quota_state`에 anchor 행이 없으면
   `try_reserve()`가 즉시 `CoordinatorError`로 fail-closed 종료한다(§4) —
   migration 없이는 아예 동작하지 않는다.
2. **flag/호출 경계 배선 누락**: 이전 PR 분할안은 `FDC_ACTUAL_DISPATCH_
   BUY_ENABLED`라는 새 flag와 `source_type` 파라미터화만 언급했을 뿐,
   실제로 이 flag가 동작하려면 `config/settings.py` 리졸버, `.env.example`
   기본값, `docker-compose.yml` 배선, `scripts/harness/contracts/
   runtime_env_wiring.json` 계약, `accept env` 검증까지 전부 갖춰야 한다는
   점이 PR Task Spec에서 누락돼 있었다(§7에서 기존 `FDC_ACTUAL_DISPATCH_
   ENABLED` 배선을 근거로 재구성한다).

**2026-09-01 2차 보정** — 위 1·2를 반영한 초판에 대한 리뷰에서 다음 HIGH
결함이 추가로 지적됐고, 이 문서는 그 결함도 함께 정정한다.

3. **provider 전체 13 RPM 계약의 불완전성**: 초판은 "held_position과
   BUY actual job이 같은 `gemini:shared-operational` quota_scope를
   공유하면 provider 전체 13 RPM이 보장된다"는 취지로 서술했으나, 이는
   불완전하다. BUY 후보 중 actual-dispatch **대상이 아닌** 것들(그리고
   held_position의 NO_ACTION/WATCH 등 비대상 상태 전부)은 여전히 기존
   `mode="full"` 단일 subprocess 경로를 타고, 그 안의 FDC 호출은 파일
   기반 `fdc_rate_limiter.py`의 **완전히 별도인** 10 RPM limiter를
   그대로 쓴다(§3에서 코드로 재확인). 이 legacy 경로의 실제 HTTP 호출은
   `trading.fdc_provider_attempts`에 전혀 기록되지 않으므로 actual-
   dispatch coordinator의 60초 window 계산에 **절대 포함되지 않는다** —
   즉 같은 quota_scope를 공유해도 legacy 호출량은 그 window에 잡히지
   않는다. 따라서 BUY actual-dispatch를 부분 도입하는 것만으로는
   provider 전체(legacy+actual 합산) HTTP 호출량이 13 RPM 이하로
   유지된다는 것을 증명할 수 없다. 이는 §4의 quota_scope 분리 문제와는
   **독립적인 별개의 결함**이며, §4의 결정(단일 scope 공유)만으로는
   해결되지 않는다. 이번 2차 보정은 §4에 이 한계를 명시하고, §8의 PR
   분할을 재구성해 provider 전체 quota 통합 설계(신규 PR D)가 완료·검증
   되기 전에는 BUY actual-dispatch를 활성화할 수 없도록 순서를 강제한다.

**2026-09-01 3차 보정** — 2차 보정판에 대한 리뷰에서 다음 flag 의미 충돌이
추가로 지적됐고, 이 문서는 그 결함도 함께 정정한다.

4. **shadow/actual flag 의미 충돌**: 2차 보정판은 단일 key `FDC_ACTUAL_
   DISPATCH_BUY_ENABLED`를 PR C(shadow 관측)에서는 "관측만 켜는" 용도로,
   PR E(실제 배선 연결)에서는 "actual-dispatch를 켜는" 용도로 **같은
   key가 PR 단계에 따라 의미를 바꾸도록** 서술했다. 이는 위험하다 —
   PR C 기간에 운영에서 `true`로 설정해 두고 잊었거나, 어떤 사전 점검
   실패로 `false`로 되돌리지 못한 채 값이 남아 있으면, PR E가 배포되는
   순간 **그 key의 의미가 바뀌면서** 아무도 명시적으로 활성화하지 않은
   actual-dispatch가 자동으로 시작된다. 이는 §11의 "코드 병합과 flag
   활성화는 별개 사건"이라는 계약 자체를 무력화한다. 이번 3차 보정은
   §7/§8/§9/§10/§11을 재구성해 shadow 전용 key(`FDC_ACTUAL_DISPATCH_
   BUY_SHADOW_ENABLED`)와 actual 전용 key(`FDC_ACTUAL_DISPATCH_BUY_
   ENABLED`)를 처음부터 별개로 분리하고, actual key는 PR E 이전까지
   **어떤 코드도 읽지 않도록** 못박는다.

**2026-09-01 4차 보정** — 3차 보정판에 대한 리뷰에서 다음 결함이 추가로
지적됐고, 이 문서는 그 결함도 함께 정정한다.

5. **shadow 측정값을 provider 전체 실제 경쟁의 예측치로 오독할 여지**:
   3차 보정판의 PR C 설계는 `register_shadow_job_and_judge()`가 계산하는
   `mode='shadow'` 가상 FIFO 판단(`SHADOW_WOULD_GRANT`/`SHADOW_QUEUED`)
   과, held_position의 실제 `mode='real'` reservation·legacy `fdc_rate_
   limiter.py` 경로의 실제 HTTP 호출을 한 문단에 섞어 서술했다(예:
   "만약 이 BUY 후보가 실제로 coordinator에 reservation을 요청했다면
   몇 초를 기다렸을지(시뮬레이션)"). 그러나 `repositories/postgres/
   fdc_quota.py`의 `register_shadow_job_and_judge()`를 직접 재확인한
   결과(§3), 그 window_count 조회는 `WHERE quota_scope = $1 AND mode =
   'shadow' AND status = 'SHADOW_WOULD_GRANT'`로 **`mode='shadow'` 행만
   계산**하며 `mode='real'`(held_position 실제 reservation)이나 legacy
   HTTP 호출은 전혀 입력으로 받지 않는다. 즉 shadow judge 결과는 실제
   held_position과의 경합(mode='real')이나 provider 전체 60초 호출량과는
   무관하다 — shadow 결과를 BUY의 실제 대기시간·거부율·held_position
   지연 증가·provider 전체 13 RPM 준수 여부의 예측치로 쓰면 안 된다.
   이번 4차 보정은 §8 PR C의 "변경 내용"을 다시 써서 (a) shadow 내부
   관측과 (b) read-only 실제 부하 관측을 명확히 분리하고, (c)
   counterfactual replay(실제 경쟁을 가정한 시뮬레이션)를 PR C 범위에서
   제거해 PR D 이후 별도 Task Spec 대상으로 명시한다(§8/§9/§10/§11).

**2026-09-01 5차 보정** — 4차 보정판에 대한 리뷰에서 다음 결함이 추가로
지적됐고, 이 문서는 그 결함도 함께 정정한다.

6. **"BUY shadow 내부 관측"이라는 명칭 자체가 구현 사실과 다름**: 4차
   보정판은 (a)를 "BUY shadow 내부 관측"이라 명명하고 "다른 BUY shadow
   후보들끼리의 가상 FIFO 판단"이라고 서술했다. 그러나
   `register_shadow_job_and_judge()`의 window_count SQL(§3, 위 인용)을
   다시 보면 **`source_type` 조건이 전혀 없다** — `quota_scope`,
   `mode='shadow'`, `status='SHADOW_WOULD_GRANT'`, `enqueue_sequence`,
   `fdc_ready_at`만으로 필터링된다. 즉 같은 `quota_scope`에 등록된
   held_position shadow 행과 BUY shadow 행은 **서로의**
   `SHADOW_WOULD_GRANT`/`SHADOW_QUEUED` 판정에 영향을 준다 — "BUY만의"
   가상 FIFO가 아니라 **동일 quota_scope를 쓰는 모든 lane이 공유하는
   shared-shadow FIFO**다. 더 나아가 `scripts/run_decision_loop.py:
   1916-1922`의 실제 호출부를 확인한 결과, 이 shadow replay 자체가
   이미 `source_type`을 가리지 않고 모든 lane의 `_fdc_ready_shadow_
   event`에 대해 호출되고 있다 — 즉 이 shared-shadow 동작은 BUY
   확장으로 새로 생기는 것이 아니라 **이미 존재하는 기존 동작**이다.
   이번 5차 보정은 §8 PR C, §9, §10, §11 전체에서 "BUY shadow 내부
   관측"이라는 명칭과 "BUY 후보들끼리"라는 서술을 "동일 quota_scope의
   공유 shadow FIFO 관측"으로 바로잡고, BUY 행 단독 집계(등록 수/상태/
   순서)와 shared-shadow 판정(다른 lane의 영향을 받는
   `SHADOW_WOULD_GRANT`/`SHADOW_QUEUED`)을 구분해서 서술한다.

### 범위

- BUY/core lane actual dispatch 파일럿의 **quota 정책**(신규 scope 없음),
  **대상 판정과 안전 계약**, **source_type 파라미터화의 호출 경계**,
  **runtime flag 배선 계약**을 확정하고, 구현 PR로 분할 가능한 수준까지
  구체화한다.

### 비범위

- 실제 코드 구현(이 문서는 설계 문건이며, 실제 함수 작성은 후속 PR).
- lane 우선순위 정책, quota_scope 분할, 정적 RPM 예약(예: 8+5) — 이번
  파일럿에서는 **의도적으로 도입하지 않는다**(§4의 결정 사항). 이는 파일럿
  관측 결과가 나온 뒤 별도 문서로 재설계한다.
- `run_decision_loop.py`의 일반(core/BUY) submit lane 자체의 **Pass 2**
  메커니즘(`defer_actionable_for_pass2`/`pending_candidates_sink`/
  `_run_general_lane_pass2()`, 2026-08-11 도입, D안)의 재설계 — 이 문서는
  그 기존 메커니즘과 FDC dispatch pending 메커니즘이 **동시에 존재할 때의
  상호작용**만 §6/§12에서 위험 요소로 명시하고, 통합 재설계는 하지 않는다.

## 2. 현재 held_position/BUY 경로 비교

| 항목 | held_position REDUCE/SELL_CANDIDATE(실전 전환됨) | BUY/core lane(현재, 미전환) |
|---|---|---|
| 대상 판정 | `_is_fdc_actual_dispatch_target()`(`decision_agent_runner.py:84-109`): `source_type=="held_position" AND has_position AND primary_candidate in (REDUCE_CANDIDATE, SELL_CANDIDATE)` | 판정 없음 — 항상 단일 `mode="full"` subprocess 경로(`run_agents_in_subprocess()` 1231-1247) |
| FDC 호출 방식 | pre_fdc pass(EI/AR/AC + skip 판정) → `FdcActualDispatchPendingError` 즉시 발생(1387-1390) → post-gather `complete_fdc_actual_dispatch()`(356-649)가 별도로 fdc_only 호출 | 단일 subprocess 안에서 EI→AR→AC→FDC 순차 실행, 대기 없이 즉시 완결 |
| quota/limiter | Postgres `FdcQuotaCoordinator`/`try_reserve()`(`fdc_quota_coordinator.py:114`), anchor 행 `FOR UPDATE`, target 13 RPM(`_resolve_fdc_provider_target_rpm()`, settings.py:702-709), quota_scope=`gemini:shared-operational`(`DEFAULT_QUOTA_SCOPE`) | **파일 기반** `fdc_rate_limiter.py`, `DEFAULT_MAX_CALLS_PER_WINDOW=10`/60s(163-164), `fcntl.flock`로 직렬화된 `/tmp/agent_trading_fdc_rate_limiter_state.json` 상태 — **Postgres `fdc_provider_attempts`에 전혀 기록되지 않으므로 actual-dispatch coordinator의 window_count 계산에 절대 포함되지 않는다**(§3 확정 사실). provider 429/5xx 재시도도 이 legacy limiter에서 별도 permit을 소비한다(`fdc_rate_limiter.py:606-618`, `allow_requeue=False`) — 즉 재시도 포함 모든 legacy HTTP 시도가 coordinator 밖에서 일어난다. |
| DB 영속화 | `fdc_queue_jobs`(pending)→`fdc_provider_attempts`(append-only)→second pass→`agent_runs`(4건)→`trade_decisions`(1건). PR #361 이후 read-only 실측(자연 cycle 3개, real job 31건)으로 `decision_context_id` 3자 완전 일치 확인됨(별도 세션 보고) | 현재 운영에서는 held_position 행만 실제로 존재하지만, **schema와 repository 계약 자체는 lane-agnostic이다**: `fdc_queue_jobs.source_type VARCHAR(32) NOT NULL`(migration `0068_add_fdc_quota_lifecycle_tables.sql:46`, CHECK 제약 없음)이고 `register_real_job(source_type=...)`도 임의 문자열을 그대로 받는다 — BUY 확장에 신규 테이블이나 schema 확장은 필요 없다. 다만 대상이 아닌 BUY 후보(legacy `mode="full"` 경로)는 여전히 `fdc_queue_jobs`에 기록되지 않는다(위 quota/limiter 행 참고). `agent_runs`/`trade_decisions`는 lane 무관하게 동일 구조로 기록됨 |
| 실행 파이프라인(둘 다 `ExecutionService.run_execution_pipeline()` 단일 함수, `execution_service.py`) | quote_resolution 생략(smoke-price, `HP_SELL_QUOTE_BYPASS`) → sizing → **sell_guard**(2339-2438, SELL만) → translation → compliance_validator → risk_validator → order_create → broker_submit | quote_resolution 실제 조회 → sizing → execution_liquidity(BUY 전용) → translation → probe_churn_guard → compliance_validator → risk_validator → **buy_duplicate_guard**(2665-2744, `_has_active_reconciliation_lock()`+`_has_recent_active_buy_order()`, BUY만) → order_create → **stale_snapshot_guard**(2848-3040) → broker_submit |
| submit 예산 | `general_submit_budget_bypassed`(submit_lane_gate.py) — cycle-level cap 미적용(레거시 상수 `HELD_POSITION_SELL_MAX_PER_CYCLE=2`는 더 이상 강제되지 않음) | `max_general_submits_this_cycle` 공유 pool, `submit_budget_consumed_count`는 **실제 제출 결과가 SUBMITTED/RECONCILE_REQUIRED일 때만** 증가(`run_decision_loop.py:3314-3315`) — pending 등록 시점이 아니라 최종 제출 시점에 소비됨 |
| flag 배선 | `FDC_ACTUAL_DISPATCH_ENABLED`(settings.py:682-699, 기본 false), `.env.example:139`, `docker-compose.yml:408`(`${FDC_ACTUAL_DISPATCH_ENABLED:-false}`), `runtime_env_wiring.json:59-64`(`required_in_compose: true`, services=["ops-scheduler"]) | 해당 없음 |

## 3. 확정 사실 / 해석 / NOT VERIFIED

### 확정 사실 (코드로 직접 재확인)

- `FdcQuotaCoordinator.try_reserve()`의 실제 Postgres 구현
  (`repositories/postgres/fdc_quota.py:94-121`)은 다음 두 조회를 모두
  **`quota_scope` 컬럼으로 필터링**한다.
  - anchor 행 잠금: `SELECT quota_scope FROM trading.fdc_quota_state WHERE quota_scope = $1 FOR UPDATE`(94-97)
  - 60초 window 카운트: `SELECT count(*) FROM trading.fdc_provider_attempts WHERE quota_scope = $1 AND mode = 'real' AND ... reserved_at > now() - make_interval(secs => $3)`(113-121)

  즉 **scope가 다르면 window_count도, FIFO(`earlier_queued`, 134-145)도
  완전히 독립적으로 계산된다** — 물리적으로 동일한 Gemini API 계정을
  공유하더라도, coordinator 레벨에서는 서로의 소비량을 전혀 모른다.
- anchor 행은 migration `0068_add_fdc_quota_lifecycle_tables.sql:26-33`이
  `gemini:shared-operational` **단 하나만** 시딩한다. 다른 quota_scope로
  `try_reserve()`를 호출하면 anchor 행이 없어 99-111행의 fail-closed
  분기(`CoordinatorError(COORDINATOR_TRANSACTION_ERROR, "anchor row missing
  for quota_scope=... — seed the anchor row before use")`)로 즉시
  실패한다 — **migration 없이는 새 scope가 원천적으로 동작하지 않는다.**
- `_resolve_fdc_actual_dispatch_enabled()`(settings.py:682-699)의 독스트링
  자체가 "BUY 후보, 일반 universe, 그 밖의 held_position 상태(NO_ACTION/
  WATCH)는 이 값과 무관하게 기존 10 RPM strict limiter 경로
  (`_FdcPermitAccumulator`)를 그대로 쓴다"(694-696)고 명시 — 현재 BUY/core는
  구조적으로 실전 quota coordinator를 전혀 거치지 않는다.
- **(2026-09-01 2차 보정) legacy `mode="full"` 경로는 coordinator를
  물리적으로 아예 호출하지 않는다**: `DecisionAgentRunner.run_agents_in_
  subprocess()`(decision_agent_runner.py:1224-1247)는 대상 판정이
  거짓이면(현재는 held_position 대상 여부만 판정) `_run_agents_in_
  subprocess_with_actual_dispatch()`/`complete_fdc_actual_dispatch()`
  둘 다 호출하지 않고, `_spawn_agent_subprocess()`(1239-1241)로 단일
  `mode="full"` subprocess를 곧바로 실행한다 — 이 경로에는 `try_
  reserve()` 호출이 전혀 없다. 그 subprocess 내부(`run_agent_subprocess.
  py`, 별도 프로세스)의 FDC 호출은 `fdc_rate_limiter.py`의 파일 기반
  10 RPM limiter(`DEFAULT_MAX_CALLS_PER_WINDOW=10`, 163-164)만 거치며,
  이 limiter의 상태는 `/tmp/agent_trading_fdc_rate_limiter_state.json`
  (`default_state_path()`, 235-242)에 저장될 뿐 `trading.fdc_provider_
  attempts`에는 절대 기록되지 않는다. 따라서 `try_reserve()`의 window_
  count SQL(§3 첫 bullet 인용, `WHERE quota_scope = $1 AND mode = 'real'`)
  은 legacy 호출을 구조적으로 볼 수 없다.
- **429/5xx 재시도도 legacy limiter 안에서 일어난다**: `provider_
  client.py`의 재시도 루프가 매 재시도마다 `fdc_rate_limiter.acquire(...,
  allow_requeue=False)`(fdc_rate_limiter.py:606-618, 707)를 다시 호출해
  permit을 소비한다 — 재시도 1회당 legacy limiter의 10 RPM 카운터가
  1씩 소비되지만, 이 소비 역시 Postgres coordinator에는 전혀 반영되지
  않는다.
- **결론(HIGH)**: held_position actual-dispatch와 BUY actual-dispatch가
  같은 `gemini:shared-operational` quota_scope를 공유해도, 그 scope의
  60초 window(§3 첫 bullet)는 **오직 `mode='real'`로 등록된 actual-
  dispatch job의 reservation만** 계산한다. 같은 시간대에 legacy
  `mode="full"` 경로로 나가는 HTTP 호출(비대상 BUY/core 전부, 비대상
  held_position 상태 전부, 그리고 그 재시도)은 파일 기반 10 RPM
  limiter가 **별도로** 허용한다. 즉 provider(Gemini)로 나가는 실제
  HTTP 총량은 이론상 "coordinator가 승인한 최대 13/60s" + "legacy
  limiter가 승인한 최대 10/60s" = 최대 23/60s까지 동시에 발생할 수
  있으며, 이는 Gemini 선언 한도(15 RPM)를 상회한다. **quota_scope를
  공유하는 것(§4의 결정)은 held_position actual job과 BUY actual job
  "사이의" 경합만 정확히 반영할 뿐, legacy 경로를 포함한 provider
  전체 호출량 상한을 증명하지 못한다** — 이는 §4의 scope 분리 문제와
  독립적인 별개의 결함이다.
- 기존 flag(`FDC_ACTUAL_DISPATCH_ENABLED`) 하나의 완전한 배선 사례:
  `settings.py:682-699`(리졸버) → `.env.example:139`(기본값 `false`) →
  `docker-compose.yml:408-409`(compose 배선, `${...:-false}` 기본값
  fallback 포함) → `runtime_env_wiring.json:59-64`(`required_in_compose:
  true`, `services: ["ops-scheduler"]`, 배선 누락 시 하드 실패 사유 명시) —
  4개 파일이 항상 함께 갱신돼야 하는 계약임을 이 존재 사례 자체가 증명한다.
  `scripts/harness/README.md:247-269`(`accept env` 절)가 이 계약을
  강제하는 하네스 명령이며, "새 런타임 env 키를 추가할 때는 계약 파일과
  `docker-compose.yml` 배선을 함께 갱신한다"(266행)고 명시한다.
- `complete_fdc_actual_dispatch()`(decision_agent_runner.py) 내부의
  held_position 하드코딩 3곳(원 조사에서 확인, 이번 세션에서도 grep으로
  재확인): `caller_id = "ops-scheduler:held_position_reduce_sell"`(421),
  `fdc_only_payload`의 `"source_type": "held_position"`(472, 고정 문자열),
  `register_real_job(source_type=request.source_type or "held_position", ...)`
  (1375, 방어적 기본값).
- `run_decision_loop.py`의 일반 lane(core/BUY) 자체 Pass 2 메커니즘
  (`defer_actionable_for_pass2`/`pending_candidates_sink`/
  `_run_general_lane_pass2()`, 1966-1967, 2411-2438, 3186)은 FDC dispatch
  pending 메커니즘(`pending_fdc_dispatch_sink`/`_run_fdc_actual_dispatch_
  phase()`)과 **이름은 유사하지만 완전히 별개의 코드 경로**다 — 하나는
  "AI 판단은 끝났고 제출만 다음 phase로 미루는" 메커니즘, 다른 하나는
  "FDC 호출 자체가 quota 대기로 미뤄지는" 메커니즘이다.
- `submit_budget_consumed_count`는 `_submit_general_lane_candidate()`의
  결과가 `SUBMITTED`/`RECONCILE_REQUIRED`일 때만 증가한다
  (`run_decision_loop.py:3313-3315`) — pending/등록 단계에서는 전혀
  증가하지 않음을 코드로 확인.
- **(2026-09-01 4차 보정) `register_shadow_job_and_judge()`의 가상
  FIFO 판단은 `mode='shadow'` 행만 집계한다**: `repositories/postgres/
  fdc_quota.py:285-365`(특히 347-358행)를 직접 재확인한 결과, window_
  count 조회 SQL은
  ```sql
  SELECT count(*) FROM trading.fdc_queue_jobs
  WHERE quota_scope = $1 AND mode = 'shadow'
    AND status = 'SHADOW_WOULD_GRANT'
    AND enqueue_sequence < $2
    AND fdc_ready_at > $3::timestamptz - make_interval(secs => $4)
    AND fdc_ready_at <= $3::timestamptz
  ```
  로, `mode = 'shadow'` 조건이 명시돼 있다 — `mode='real'`(held_position
  실제 reservation, `try_reserve()`가 쓰는 `fdc_provider_attempts`
  테이블 자체도 아예 조회하지 않음)이나 legacy `fdc_rate_limiter.py`
  경로의 실제 HTTP 호출은 이 계산에 **전혀 포함되지 않는다**. 또한 이
  판단은 `reserved_at`(실제 reservation 발급 시각)이 아니라 `fdc_ready_
  at`(FDC-ready로 확정된 시각) 기준 `(t-window, t]` 구간을 쓴다 —
  `try_reserve()`의 실시간 `reserved_at` 기준 window(§3 첫 bullet)와도
  다른 시간 기준이다. 따라서 `SHADOW_WOULD_GRANT`/`SHADOW_QUEUED`는
  held_position의 실제 경합(`mode='real'`)이나 provider 전체 60초
  호출량과는 구조적으로 무관하다.
- **(2026-09-01 5차 보정) 위 window_count SQL에는 `source_type` 조건이
  없다 — "BUY만의" 가상 FIFO가 아니라 동일 quota_scope를 쓰는 모든
  lane이 공유하는 shared-shadow FIFO다**: 위 SQL(240행 인용)을 다시
  확인하면 필터 조건은 `quota_scope`, `mode='shadow'`,
  `status='SHADOW_WOULD_GRANT'`, `enqueue_sequence`, `fdc_ready_at`
  뿐이며 `source_type`/lane 식별 조건이 전혀 없다. `source_type`은
  `register_shadow_job_and_judge()`의 파라미터로 받아 `fdc_queue_jobs`
  행에 저장되지만(325-338행, `INSERT ... source_type ...`), window_
  count 조회에는 전혀 쓰이지 않는다. 즉 **같은 quota_scope에 등록된
  held_position shadow 행과 BUY shadow 행은 서로의 `SHADOW_WOULD_
  GRANT`/`SHADOW_QUEUED` 판정에 영향을 준다** — BUY shadow job의
  등록 수/상태/`enqueue_sequence`는 BUY 행만 걸러 별도로 집계할 수
  있지만, 그 판정 자체(would_grant 여부)는 앞선 held_position shadow
  행을 포함한 동일 scope 전체의 shared-shadow 상태에 좌우된다. 게다가
  `scripts/run_decision_loop.py:1916-1922`(shadow replay 호출부)를
  확인한 결과, 이 함수는 `source_type`을 가리지 않고 모든 lane의
  `_fdc_ready_shadow_event`에 대해 이미 호출되고 있다 — 즉 이
  shared-shadow 동작은 BUY 확장으로 새로 생기는 것이 아니라 **이미
  존재하는 기존 동작**이며, BUY가 추가되면 그 기존 공유 FIFO에 새
  참여자가 하나 늘어나는 것뿐이다.

### 해석 (판단 개입)

- quota_scope를 분리하지 않고 공유하는 것이, "물리적으로 하나뿐인 Gemini
  계정 RPM 한도를 정확히 반영한다"는 점에서 **더 정확한 모델**이다. 분리는
  구현이 쉬워 보이지만 실제로는 이중 계정을 흉내 내는 것과 같아서 실질
  한도 위반 위험을 새로 만든다.
- held_position sell이 BUY에 순번을 밀릴 위험은 이론적으로 존재하지만,
  현재 실측 데이터(별도 세션, 최근 2시간 표본)상 held_position 실전
  dispatch job은 cycle당 9~12건 수준이고 이는 13 RPM 한도에 크게 못 미쳐
  대부분의 시간에 여유가 있었다 — 다만 이는 **BUY가 아직 quota를 전혀
  쓰지 않는 현재 상태**의 관측치이므로, BUY가 합류한 이후의 실제 경합
  수준은 파일럿을 통해서만 확인 가능하다(그래서 우선순위/분할 설계를
  이번 파일럿에서 보류하고 shadow 지표로 먼저 측정하는 것이 타당하다).

### NOT VERIFIED

- `decision_context_service.py`(`ensure_or_create()`의 실제 구현체) —
  이번 세션에서도 열람하지 않았다. BUY 경로에서 `decision_context_id`
  resolve 로직이 held_position과 100% 동일한 코드 경로를 타는지는
  구조적으로 개연성이 높으나(둘 다 `assemble()`을 거침) 파일 자체를
  직접 확인하지는 못했다.
- core lane BUY 후보의 정확한 `primary_candidate` 라벨(`BUY_CANDIDATE`
  추정)이 `deterministic_trigger_engine.py`에서 정확히 어떤 조건으로
  생성되는지는 이번 세션에서도 직접 열람하지 않았다 — §5의 BUY 판정
  함수 설계는 이 라벨이 존재한다는 전제 위에 있으며, 구현 착수 전
  최우선 확인 항목이다.
- 새 quota_scope를 실제로 만들었을 때 물리적으로 몇 RPM까지 초과하는지
  (예: 13+13=26까지 가능한지, 아니면 다른 안전장치가 있는지)는 이번
  문서에서 **코드 경로로만** 증명했고, 실제로 재현 실험을 하지는
  않았다(재현하려면 별도 scope+anchor 행 seed가 필요해 금지 사항인
  DB write/migration을 위반하므로 이번 세션에서는 불가능).
- **(2026-09-01 4차 보정) legacy 경로의 실제 provider HTTP 시작 시각을
  지속적으로 신뢰 가능하게 관측할 저장소/로그 근거가 확정돼 있지
  않다**: legacy `mode="full"` 경로의 HTTP 호출은 `trading.fdc_
  provider_attempts`에 전혀 기록되지 않으므로(§3), 그 실제 시각을 알
  수 있는 유일한 방법은 provider 클라이언트가 남기는 애플리케이션
  로그(`docker logs`류)의 grep뿐이다. 이 방법 자체는 초 단위 타임스탬프
  추출이 가능함을 별도 세션에서 실제로 확인한 바 있으나, 그것은
  일회성 조회였고 로그 rotation/보존 정책·다중 컨테이너 인스턴스·
  로그 포맷 변경 등에 대한 내구성이 검증되지 않았다. 따라서 §8 PR C의
  (B) read-only 실제 부하 관측과 §8 "PR C 범위 밖" counterfactual
  replay가 전제하는 "legacy 실제 시각을 안정적으로 확보할 수 있다"는
  가정은 이 문서에서 `NOT VERIFIED`로 남긴다 — 지속적인 운영 지표로
  쓰려면 별도 로그 파이프라인/저장 설계가 필요하다.

## 4. 최종 quota 결정과 기각한 대안

### 결정: 별도 quota_scope를 만들지 않는다

- held_position과 BUY 모두 기존 `gemini:shared-operational`(`fdc_quota_
  coordinator.py`의 `DEFAULT_QUOTA_SCOPE`) 단일 scope를 그대로 사용한다.
- 전체 실제 reservation(`mode='real'`)의 60초 sliding window 상한은
  계속 `FDC_PROVIDER_TARGET_RPM`(기본 13)이며, **held_position job과
  BUY job을 구분하지 않고 합산**해서 판정한다 — §3에서 확인했듯
  `try_reserve()`의 window 카운트 SQL이 `quota_scope` 하나로만 필터링
  되므로, 같은 scope를 쓰면 이 합산이 자동으로 이루어진다(추가 코드
  불필요).
- FIFO 기준은 기존 `fdc_ready_at`/`enqueue_sequence` 계약을 그대로
  유지한다(`fdc_quota_coordinator.py:134-145`의 `earlier_queued` 판정 —
  `quota_scope`+`mode='real'`+`status='QUEUED'`로만 필터링되고 `source_
  type`은 전혀 관여하지 않으므로, held_position/BUY 구분 없이 순수
  등록 순서(`enqueue_sequence`)로만 경쟁한다).
- lane 우선순위, scope 분할, 정적 RPM 예약(예: held_position 8 + BUY 5)은
  **이번 파일럿 범위에서 도입하지 않는다**. held_position이 BUY에 밀릴
  위험은 실제 shadow 관측 지표(§10 shadow 테스트 계획)로 측정하고,
  우선순위/분할이 필요하다고 판단되면 그 실측 데이터를 근거로 **별도
  후속 설계 문서**를 작성한다.

> **(2026-09-01 2차 보정) 이 결정의 적용 범위 한정**: 위 결정은 held_
> position actual-dispatch job과 BUY actual-dispatch job **사이의** 60초
> window 경합만 정확히 반영한다는 뜻이다. §3에서 확인했듯 legacy
> `mode="full"` 경로(비대상 BUY/core, 비대상 held_position, 그 재시도)는
> 어느 quota_scope 결정과도 무관하게 coordinator 밖에서 파일 기반 10 RPM
> limiter로 계속 실제 HTTP를 호출한다. **따라서 이 §4의 결정만으로는
> "provider 전체 60초 HTTP 호출량이 13 이하"라는 것을 증명하지 못한다.**
> 이 결함은 이번 문서의 범위를 넘어서는 별도 설계·구현이 필요하며, §8의
> 신규 PR D("provider 전체 quota 통합 설계 및 구현")가 병합·검증되기
> 전에는 `FDC_ACTUAL_DISPATCH_BUY_ENABLED`를 활성화하지 않는다(§8/§9/§11).
> PR D가 검토해야 할 설계 대안 3가지(이번 문서에서는 결정하지 않음):
>
> 1. legacy FDC HTTP 호출도 coordinator(`try_reserve()`)를 반드시 거치게
>    통합한다 — 즉 `mode="full"` 경로 자체를 없애거나, 그 안의 FDC 호출도
>    Postgres 기반 reservation을 거치도록 바꾼다.
> 2. legacy limiter(`fdc_rate_limiter.py`, 파일 기반)와 actual coordinator
>    (`FdcQuotaCoordinator`, Postgres 기반)가 **하나의 DB 기반 전역
>    window**를 공유하도록 legacy limiter 쪽을 Postgres-backed로 재작성한다.
> 3. provider 전체 호출량(legacy+actual 합산)을 원자적으로 합산·제한하는
>    **별도 global coordinator**(두 하위 메커니즘의 상위 계층)를 신설한다.
>
> "actual 13 + legacy 10"을 **단순 정적 분할**(예: "coordinator는 최대
> 8까지만 grant하고 legacy는 최대 5까지만 쓰도록 각자 알아서 낮춘다")로
> 허용하는 방안은 이번 문서에서 명시적으로 대안이 아니다 — 현재 held_
> position actual target 자체가 이미 13이므로(§2, `_resolve_fdc_provider_
> target_rpm()` 기본값), 정적 분할은 held_position의 기존 실전 운영
> target을 그대로 두는 한 legacy 쪽 여유가 사실상 없거나(13+0), target을
> 낮추면 held_position의 기존 실전 계약(no-bypass 원칙상 근거 없이 바꿀
> 수 없는 값)을 건드리게 되므로 안전한 해결책이 아니다.

### 기각한 대안과 기각 사유

| 대안 | 기각 사유 |
|---|---|
| 별도 `quota_scope`(예: `gemini:shared-operational-buy`) 신설 | §3에서 확인한 대로 window_count/FIFO가 scope별 독립 계산이라, 두 scope가 각자 13 RPM까지 허용하면 물리적으로 최대 26 RPM까지 실제 Gemini 호출이 나갈 수 있다(Gemini 선언 한도 15 RPM을 크게 초과) — 이는 API 계정 자체의 rate limit 위반이나 계정 정지 위험으로 이어질 수 있는 **운영 안전성 결함**이다. 또한 새 anchor 행 migration, scope별 target RPM 설정 계약, 전 scope 합산 60초 RPM 검증 로직이 전부 새로 필요해 파일럿 범위를 크게 벗어난다. |
| 정적 RPM 예약(예: held_position 8 + BUY 5) | 실측 데이터 없이 정적 배분을 먼저 확정하면, 실제 트래픽 패턴(예: 특정 시간대에 BUY 후보가 몰리는 경우)에 맞지 않아 한쪽이 상시 유휴이거나 상시 기아 상태가 될 위험이 있다. 파일럿에서 shadow 관측으로 실제 경합 패턴을 먼저 확인하는 것이 순서상 맞다. |
| FIFO에 lane 가중치 추가(held_position 우선) | `try_reserve()`의 FIFO 판정(§3 인용)을 수정하는 것은 held_position의 기존 동작(현재 실전 운영 중)에 손을 대는 것이므로 no-bypass 원칙(기존 게이트/정책을 근거 없이 바꾸지 않음)에 어긋난다. 게다가 이 변경 없이도(§3 해석) 현재 held_position 실측 물량은 13 RPM 한도에 여유가 있어, 우선순위 도입의 실익이 아직 데이터로 증명되지 않았다. |

### 향후 별도 scope가 필요해질 경우의 전제 조건(명시만, 이번 범위 아님)

1. provider 전체 합산 상한을 원자적으로 보장하는 **상위 global coordinator**
   (예: 모든 scope의 window_count를 하나의 트랜잭션에서 합산 조회하고
   합산 캡을 강제하는 별도 조회/락 계층)의 설계.
2. scope별 target RPM을 별도로 설정할 수 있는 명시적 계약
   (`FDC_PROVIDER_TARGET_RPM`을 scope-aware하게 확장하거나 scope별
   env 키 신설).
3. 새 anchor 행의 migration/배포 계약(현재처럼 `INSERT ... ON CONFLICT
   DO NOTHING`으로 최초 배포 시 1회 시딩, 운영 DB 마이그레이션 절차 포함).
4. 모든 scope 합산 60초 RPM을 검증하는 운영 read-only SQL(현재 §5
   안전/정합성 재확인 절차에 준하는 것)의 사전 마련.
5. priority 정책과 FIFO 계약의 명시적 재정의(어느 lane이 동률일 때
   우선하는지, `enqueue_sequence` 단일 정렬을 유지할지 별도 2차 키를
   둘지).

## 5. 상태 전이 및 context ID 계약

### BUY 대상 판정(신규 함수, 기존 함수는 무변경)

```
_is_fdc_actual_dispatch_target()          # 기존 — held_position 전용, 무변경
    source_type == "held_position"
    AND has_position
    AND primary_candidate in ("REDUCE_CANDIDATE", "SELL_CANDIDATE")

_is_fdc_actual_dispatch_buy_target()      # 신규 — 별도 함수로 추가
    source_type == "core"
    AND primary_candidate == "BUY_CANDIDATE"   # NOT VERIFIED: 실제 라벨명 확인 필요(§3)
    AND primary_candidate NOT IN ("NO_ACTION", "WATCH_CANDIDATE")   # 방어적 명시(위 조건과 사실상 중복이나 의도를 코드에 남김)
    AND risk_off 상태 아님                      # 판정 방법은 §5 하위 확인 항목
    AND 주문 가능 상태(eligibility 차단 아님)    # pre-AI short-circuit 등으로 이미 배제된 케이스와 정합
```

호출부는 기존 단일 `if` 대신 **명시적 3-way 분기**로 구성한다(의사코드,
구현 아님):

```python
if self._fdc_actual_dispatch_enabled and _is_fdc_actual_dispatch_target(assembled_context):
    return await self._run_agents_in_subprocess_with_actual_dispatch(
        request, assembled_context, lane="held_position",
    )
elif self._fdc_actual_dispatch_buy_enabled and _is_fdc_actual_dispatch_buy_target(assembled_context):
    return await self._run_agents_in_subprocess_with_actual_dispatch(
        request, assembled_context, lane="core",
    )
# 기존 mode="full" 단일 subprocess 경로 — 무변경
```

이 분기 순서 자체가 안전 계약이다: **held_position 분기가 먼저 평가되고,
그 조건은 한 글자도 바꾸지 않는다.** BUY 분기는 held_position이 아닐 때만
평가되므로 두 판정이 겹칠 수 없다(상호 배타적 조건이기도 하다 —
`source_type`이 다르다).

### pending 등록 → second pass 상태 전이(held_position과 동일 구조 재사용)

```
1차 pass: assemble() → _run_agents_in_subprocess_with_actual_dispatch()
    → mode="pre_fdc" subprocess (EI/AR/AC + requires_fdc_dispatch 판정)
    → register_real_job(source_type=<실제 lane>, ...)   # §6에서 파라미터화
    → FdcActualDispatchPendingError(decision_context_id=<resolved>)
    → _run_decision_pipeline() 핸들러 → SubmitResult(FDC_ACTUAL_DISPATCH_PENDING, decision_context_id=exc.decision_context_id)
    → pending_fdc_dispatch_sink.append({..., "decision_context_id": result.decision_context_id})

post-gather: _run_fdc_actual_dispatch_phase()
    → complete_fdc_actual_dispatch(job_id, pre_fdc_result, decision_context_id, ...)
        → try_reserve(quota_scope="gemini:shared-operational", ...)   # held_position/BUY 공유
        → (grant) mode="fdc_only" subprocess
        → 병합된 AgentExecutionBundle 반환
    → _run_one_cycle(precomputed_agent_bundle=bundle, decision_context_id_override=job["decision_context_id"], ...)
        → assemble()의 precomputed_agent_bundle 분기 → EV anchor 적용 → _rehydrate_subprocess_agent_runs()
        → _ensure_trade_decision() → agent_runs(4건)/trade_decisions(1건) 영속화
        → run_execution_pipeline()   # §6에서 재평가 계약 상세
```

### context ID/correlation ID 연속성 계약(불변, 그대로 재사용)

PR #361이 확립한 계약을 BUY에도 **동일하게** 적용한다 — 이 계약을 위한
코드(`FdcActualDispatchPendingError.decision_context_id`,
`_run_decision_pipeline()`의 `exc.decision_context_id` 우선 사용,
`pending_fdc_dispatch_sink`의 `result.decision_context_id` 사용)는 이미
lane-agnostic하므로 **추가 변경이 필요 없다**:

```
fdc_queue_job.decision_context_id == agent_run.decision_context_id == trade_decision.decision_context_id
```

이 동일성은 §10 종단 간 테스트에서 BUY job에 대해서도 동일하게
증명해야 한다(신규 계약이 아니라 기존 계약의 재확인).

## 6. 안전장치 호출 순서와 재평가 계약

### 호출 순서는 절대 변경하지 않는다

`ExecutionService.run_execution_pipeline()`(execution_service.py)의 게이트
호출 순서·함수·조건은 **BUY actual-dispatch 여부와 무관하게 100% 동일**해야
한다. `precomputed_agent_bundle`을 쓰는 second pass든 기존 in-process
경로든, 이 함수에 진입하는 시점부터는 완전히 동일한 코드를 탄다(held_
position이 이미 이렇게 동작 중임을 §2/§3에서 확인) — 즉 **이 부분은
"보장돼야 한다"가 아니라 "현재 구조상 자동으로 보장된다"**: second pass가
`_run_one_cycle()` → `assemble_and_submit()` → `run_execution_pipeline()`을
호출하는 경로는 애초에 lane을 구분하지 않는 단일 함수이기 때문이다.

명시적으로 재확인해야 할 것은 다음 3가지다(구현이 아니라 **이 문서가
못박는 계약**):

1. **quote freshness / stale_snapshot_guard**(execution_service.py:2848-3040):
   BUY는 held_position SELL과 달리 `quote_resolution`을 실제로 수행한다
   (§2 표). FDC dispatch가 여러 cycle에 걸쳐 지연된 뒤 second pass가
   실행되면, 그 시점에 **다시** quote를 조회하고 `stale_snapshot_guard`가
   그 시점 기준으로 재평가해야 한다 — first pass 시점의 시세를 second
   pass까지 들고 가서는 안 된다. `complete_fdc_actual_dispatch()`가
   `assembled_context`를 아예 받지 않고 durable(DB 저장 가능)한
   `pre_fdc_result`/`job_id`만 다루도록 설계된 것(원 설계 문서, decision_
   agent_runner.py 주석 372-378)이 바로 이 원칙을 위한 구조 — second
   pass의 `assemble()`이 **항상 새로 만든 fresh `ai_policy_context`**로
   EV anchor를 적용한다(decision_orchestrator.py:2977-2982 주석). BUY도
   동일하게 이 fresh-context 원칙을 따르므로 구조적으로는 안전하나,
   `stale_snapshot_guard`가 실제로 "몇 분 전 pre_fdc 시점"이 아니라
   "second pass 시점"의 snapshot 기준으로 판정하는지는 §10에 명시 테스트로
   증명해야 한다.
2. **buy_duplicate_guard + reconciliation lock**(execution_service.py:
   2665-2744): 이 게이트는 `run_execution_pipeline()` 안에서 매번 fresh
   하게 평가되므로(§2/§6 첫 문단) second pass에서도 그 시점의 최신 lock
   상태를 본다 — 구조적으로 안전하나, **durable resume**(프로세스가
   실제로 재시작된 뒤 `list_resumable_real_jobs()`로 재개하는 경우)
   시나리오에서 재개 시점에 이 게이트가 정말 최신 상태를 조회하는지는
   §10에 명시 테스트로 증명한다.
3. **submit-lane gate 예산 시점**(submit_lane_gate.py, run_decision_loop.py):
   §3에서 확인한 대로 `submit_budget_consumed_count`는 실제 제출 결과가
   확정된 시점에만 증가한다. **pending 등록(1차 pass)은 이 예산을
   전혀 건드리지 않으며, 오직 second pass의 기존 submit 경로(§2의
   `_submit_general_lane_candidate()`와 동일 경로)에서만 판단·소비한다**
   — 이는 이 문서가 정하는 명시적 계약이며, 별도 코드 변경 없이 기존
   구조를 그대로 따르면 자동으로 성립한다(BUY actual-dispatch가 이
   흐름을 우회하는 새 제출 경로를 만들지 않는 한).

### 실패/재시도/fallback

held_position과 완전히 동일한 계약을 재사용한다(§2 표의 "DB 영속화" 행)
— `AttemptHttpLifecycle` tri-state, 최대 3회 재시도, 소진 시
`FDC_FAILED_FINAL`. BUY 전용 예외 처리를 추가하지 않는다 — fail-closed
HOLD(또는 해당 lane에서 이미 쓰던 fallback 결과)로 귀결되는 원칙은 lane과
무관하게 동일해야 한다(no-bypass 원칙 — 실패를 성공으로 바꾸지 않는다).

## 7. runtime flag / Compose / Harness 배선 계약

### 신규 flag 2개 — 책임을 절대 겹치지 않게 분리(2026-09-01 3차 보정)

§1 항목 4에서 지적된 flag 의미 충돌을 없애기 위해, 단일 key를 재사용하지
않고 **역할이 명확히 분리된 별개의 key 2개**를 도입한다.

| key | 역할 | 기본값 | 실제 HTTP/reservation/order 영향 | 어느 PR에서 코드가 읽는가 |
|---|---|---:|---|---|
| `FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED` | BUY 후보를 동일 `quota_scope`의 **공유 shadow FIFO**(`mode='shadow'`, held_position 등 다른 lane과 동일 판정 로직을 공유 — §3 확정 사실)에 등록해 BUY 행의 등록량/순서와, 다른 lane의 영향을 받는 `SHADOW_WOULD_GRANT`/`SHADOW_QUEUED` 판정을 관측한다(원 설계 문서 §15 "① lifecycle 관측"과 동일 성격) — **held_position 실제 reservation이나 legacy HTTP 호출을 반영한 예측치가 아니며, "BUY만의" 격리된 판정도 아니다**(§3 확정 사실, §8 PR C) | `false` | **없음** — 이 key가 무슨 값이든 실제 HTTP/reservation/주문 경로는 절대 바뀌지 않는다 | PR C(그리고 그 이후 전부) |
| `FDC_ACTUAL_DISPATCH_BUY_ENABLED` | BUY actual-dispatch의 실제 `try_reserve()`/`fdc_only` 경로 선택 | `false` | **있음** — true면 BUY_CANDIDATE가 실제로 pending 경로에 진입 | **PR E 이전에는 어떤 runtime 분기도 이 값을 읽지 않는다.** PR B가 배선(settings/.env.example/compose/wiring 계약)만 하고, 실제로 이 값을 조회하는 코드는 PR E에서 처음 작성된다 |

두 key는 **완전히 독립적인 변수**이며, 어느 한쪽 값이 다른 쪽의 의미나
동작에 영향을 주지 않는다. 이 표가 이 문서의 유일한 flag 의미 정의이며,
아래에 다시 나열하는 문구·코드 블록·표는 전부 이 표와 일치해야 한다.

**필수 계약(코드 구현 시 반드시 지켜야 하는 제약, 이 문서가 못박는 것)**:

- PR C는 `FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED`만 읽는다 — `FDC_
  ACTUAL_DISPATCH_BUY_ENABLED`를 참조하거나 조건문에 사용하지 않는다.
- PR C 코드가 존재하는 상태에서 `FDC_ACTUAL_DISPATCH_BUY_ENABLED=true`
  여도(§8 PR B가 이미 배선했으므로 값 자체는 설정 가능) 실제 `try_
  reserve()` 호출, `fdc_only` subprocess 실행, 주문 경로 변경은 **절대
  발생하지 않는다** — PR C 시점에는 이 값을 읽는 코드가 아예 없기
  때문이다(우연이 아니라 설계).
- `FDC_ACTUAL_DISPATCH_BUY_ENABLED`는 PR B에서 4단계 배선(아래)이
  완료되지만, PR E 전까지는 어떤 runtime 분기도 이 값을 읽지 않는다.
- PR E의 **코드 병합**과 **actual flag 활성화(`true`로 변경)**는 별개
  사건이다 — PR E가 머지돼도 `FDC_ACTUAL_DISPATCH_BUY_ENABLED`는 여전히
  `false`로 유지되며, 운영 승인 이후에만 별도로 `true`로 바뀐다.
- PR E 배포 전 사전 점검에서 `FDC_ACTUAL_DISPATCH_BUY_ENABLED`의 실제
  container 환경값을 확인한다 — 이미 `true`라면(어떤 경로로든) 배포·
  재시작·활성화를 진행하지 않고, 그 값이 왜 `true`인지 원인을 밝히는
  별도 운영 승인 절차로 넘긴다(§11).

### 배선 절차 — 각 key마다 4개 파일을 모두 갱신

기존 `FDC_ACTUAL_DISPATCH_ENABLED`의 4단계 배선(§3에서 인용)과 동일한
패턴을 **두 key 각각에 대해 독립적으로** 반복한다. 아래 4개 파일 중
하나라도 누락되면 `accept env`가 실패해야 한다.

**`FDC_ACTUAL_DISPATCH_BUY_ENABLED`(actual flag, PR B에서 배선)**

1. **`src/agent_trading/config/settings.py`**: `_resolve_fdc_actual_dispatch_
   buy_enabled() -> bool` 신설(기존 `_resolve_fdc_actual_dispatch_enabled()`,
   682-699와 동일 패턴 — `os.getenv("FDC_ACTUAL_DISPATCH_BUY_ENABLED",
   "false").strip().lower() == "true"`), `AppSettings`에
   `fdc_actual_dispatch_buy_enabled: bool = field(default_factory=...)`
   추가(기존 1064-1067과 동일 패턴). 독스트링에 "이 값은 `FDC_ACTUAL_
   DISPATCH_ENABLED`(held_position)와도, `FDC_ACTUAL_DISPATCH_BUY_
   SHADOW_ENABLED`(shadow 관측)와도 완전히 독립이며, PR E 이전에는 어떤
   runtime 코드도 이 값을 읽지 않는다"는 문장을 명시한다.
2. **`.env.example`**: 기존 `FDC_ACTUAL_DISPATCH_ENABLED=false`(139행)
   바로 아래에 `FDC_ACTUAL_DISPATCH_BUY_ENABLED=false`를 추가하고, 관련
   주석에 "PR E 이전에는 이 값이 무엇이든 실제 동작에 영향 없음"을 명시.
3. **`docker-compose.yml`**: 기존 408-409행과 같은 `ops-scheduler`
   서비스 `environment:` 블록에 `FDC_ACTUAL_DISPATCH_BUY_ENABLED:
   "${FDC_ACTUAL_DISPATCH_BUY_ENABLED:-false}"` 추가.
4. **`scripts/harness/contracts/runtime_env_wiring.json`**: 59-64행과
   같은 형태의 신규 항목 추가 —
   ```json
   {
     "key": "FDC_ACTUAL_DISPATCH_BUY_ENABLED",
     "services": ["ops-scheduler"],
     "required_in_compose": true,
     "note": "core/BUY lane BUY_CANDIDATE에 한해 FDC 공용 quota coordinator(기존 gemini:shared-operational scope 공유, 신규 scope 아님)로 전환하는 실행 경로 선택 키. PR E 이전에는 어떤 코드도 이 값을 읽지 않는다 — PR B~D 기간에는 값이 true여도 실제 동작에 영향이 없다. FDC_ACTUAL_DISPATCH_ENABLED(held_position), FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED(shadow 관측)와 독립. 기본값 false는 기존 core/BUY mode=full 경로를 그대로 유지한다."
   }
   ```

**`FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED`(shadow flag, PR C에서 배선)**

1. **`src/agent_trading/config/settings.py`**: `_resolve_fdc_actual_
   dispatch_buy_shadow_enabled() -> bool` 신설(동일 패턴 —
   `os.getenv("FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED", "false").strip()
   .lower() == "true"`), `AppSettings`에 `fdc_actual_dispatch_buy_shadow_
   enabled: bool = field(default_factory=...)` 추가. 독스트링에 "이 값은
   실제 HTTP/reservation/주문 경로에 어떤 영향도 주지 않는다 — 관측
   전용이며, `FDC_ACTUAL_DISPATCH_BUY_ENABLED`(actual flag)와 이름이
   유사하지만 완전히 별개의 key다"를 명시한다.
2. **`.env.example`**: `FDC_ACTUAL_DISPATCH_BUY_ENABLED=false` 바로
   아래에 `FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED=false` 추가, 주석에
   "관측 전용, 실제 동작 영향 없음" 명시.
3. **`docker-compose.yml`**: 같은 `ops-scheduler` 서비스 `environment:`
   블록에 `FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED: "${FDC_ACTUAL_
   DISPATCH_BUY_SHADOW_ENABLED:-false}"` 추가.
4. **`scripts/harness/contracts/runtime_env_wiring.json`**: 신규 항목 —
   ```json
   {
     "key": "FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED",
     "services": ["ops-scheduler"],
     "required_in_compose": true,
     "note": "BUY_CANDIDATE 후보의 lifecycle/FIFO/quota 대기 예상치를 관측만 하는 shadow 전용 키(PR C). 실제 HTTP/reservation/주문 경로에 영향 없음 — FDC_ACTUAL_DISPATCH_BUY_ENABLED(actual flag)와 이름은 유사하지만 완전히 별개다. 기본값 false는 관측 자체를 끈다."
   }
   ```

### 검증 계약

- `bash scripts/harness/run.sh accept env` — `scripts/harness/run.sh`의
  `passed` 판정(해당 스크립트 내 `runtime_env_wiring_missing_count == 0
  and runtime_env_wiring_contract_parse_failed_count == 0` 조건 포함)을
  그대로 따른다. 위 8개 파일 항목(2개 key × 4개 파일) 중 하나라도
  누락되면 `runtime_env_wiring_missing_count`가 1 이상이 되어 `accept
  env`는 **실패**한다. `runtime_env_wiring.json` 계약 자체의 형식이
  잘못되면 `runtime_env_wiring_contract_parse_failed_count`가 1 이상이
  되어 마찬가지로 **실패**한다. **통과 조건은 두 카운트가 모두 정확히
  0인 것뿐이다** — `missing_count`가 1 이상인 상태로 통과하는 경우는
  없다.
- settings/배선 테스트: 기존 `FDC_ACTUAL_DISPATCH_ENABLED`를 검증하는
  테스트와 동일한 패턴으로, 두 신규 key 각각에 대해 env 미설정 시 기본
  `False`, `"true"` 설정 시 `True`가 되는지 단위 테스트로 검증. 두 값을
  독립적으로 조합(false/false, true/false, false/true, true/true)해도
  서로의 리졸버 결과에 영향이 없는지도 확인한다.
- `FDC_ACTUAL_DISPATCH_ENABLED=false`(기존 flag)와 `FDC_ACTUAL_DISPATCH_
  BUY_ENABLED=false`(신규 actual flag) 조합에서 core/BUY의 기존
  `mode="full"` 경로가 완전히 유지되는지가 최우선 회귀 테스트다(§9
  Acceptance Criteria) — `FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED`는 이
  회귀 테스트의 결과에 영향을 주지 않아야 한다(참여시켜 봐도 결과가
  같아야 한다).

## 8. PR 분할 Task Spec

### PR A — lane 하드코딩 제거(선행, 순수 파라미터화)

- **변경 대상 파일**: `src/agent_trading/services/decision_agent_runner.py`
  (`complete_fdc_actual_dispatch()`의 `caller_id`/`fdc_only_payload
  ["source_type"]` 파라미터화, `register_real_job()` 호출부의 `source_
  type` 기본값 처리 재검토), `scripts/run_decision_loop.py`(`_run_fdc_
  actual_dispatch_phase()`가 `complete_fdc_actual_dispatch()`를 호출할 때
  `job["source_type"]`을 새 파라미터로 전달하도록 배선 — 이 파일이
  포함돼야 하는 이유는 실제 호출자이기 때문).
- **변경 내용**: 421행/472행/1375행의 하드코딩 3곳을 호출부 파라미터로
  치환. 동작은 held_position에 한해 100% 동일해야 한다(현재 유일한
  호출자이므로 실질 산출값 불변).
- **금지되는 변경**: 새 lane 판정 로직(`_is_fdc_actual_dispatch_buy_
  target()`) 추가 금지 — 이 PR은 순수 파라미터화만. `FDC_ACTUAL_
  DISPATCH_ENABLED`/`FDC_PROVIDER_TARGET_RPM` 등 기존 flag/설정값
  변경 금지.
- **Acceptance Criteria**: 기존 `test_decision_agent_runner_actual_
  dispatch.py`, `test_run_decision_loop.py` 전량 **무수정** 통과. 새
  파라미터의 기본값이 기존 하드코딩 값과 동일해서, 파라미터를 생략한
  기존 호출 방식이 있다면 그 결과도 동일해야 함(단, 실제로는 유일한
  호출자인 `run_decision_loop.py`도 이 PR에서 함께 갱신하므로 생략 호출은
  없을 것).
- **단위/통합/운영 검증**: `accept backend-file decision_agent_runner.py`,
  `accept script-file run_decision_loop.py`, `test-file
  tests/services/test_decision_agent_runner_actual_dispatch.py`,
  `test-file tests/scripts/test_run_decision_loop.py`.
- **롤백 조건**: 기존 테스트 1건이라도 실패, 또는 held_position 운영
  로그의 `caller_id`/`source_type` 값이 이전과 달라지면 즉시 되돌림.

### PR B — BUY 대상 판정 함수 + actual flag 배선(동작 없음, 판정·배선만)

- **변경 대상 파일**: `decision_agent_runner.py`(`_is_fdc_actual_dispatch_
  buy_target()` 신설, §5 의사코드), `src/agent_trading/config/settings.py`,
  `.env.example`, `docker-compose.yml`, `scripts/harness/contracts/
  runtime_env_wiring.json`(§7의 `FDC_ACTUAL_DISPATCH_BUY_ENABLED` 4개
  파일 전부 — **actual flag만**, shadow flag는 PR C 범위).
- **변경 내용**: 새 판정 함수와 **actual flag(`FDC_ACTUAL_DISPATCH_BUY_
  ENABLED`)의 배선만** 추가, `run_agents_in_subprocess()`의 실제 분기
  에는 아직 연결하지 않음(dead code로 머지) — 판정 로직/배선과 실제
  동작 변경을 분리해 리스크를 낮춘다. **이 PR이 끝난 시점에도 actual
  flag를 읽는 코드는 존재하지 않는다** — settings 리졸버가 값을
  파싱할 수는 있지만, 그 결과를 조건문에 쓰는 코드는 PR E에서 처음
  작성된다(§7 필수 계약).
- **금지되는 변경**: `run_agents_in_subprocess()`의 분기 로직 연결 금지
  (PR E 범위). held_position 분기(`_is_fdc_actual_dispatch_target()`)
  변경 금지. shadow flag(`FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED`) 배선
  금지(PR C 범위).
- **Acceptance Criteria**: 신규 판정 함수의 대상/비대상 단위 테스트
  전량 통과, actual flag가 기본값 `false`로 해석됨을 settings 테스트로
  확인, **actual flag가 `true`여도 BUY가 기존 `mode="full"` 경로를
  그대로 유지**함을 테스트로 확인(§10 테스트 1), 기존 테스트 전량
  무영향.
- **단위/통합/운영 검증**: `accept backend-file decision_agent_runner.py`,
  `accept env`(§7 배선 계약 확인), `test-one`(신규 판정 함수 테스트),
  settings 단위 테스트.
- **롤백 조건**: `accept env` 실패, 또는 리뷰 미승인 시 머지 보류.

### PR C — BUY shadow 관측(신규 shadow flag, 실제 HTTP/reservation/주문 경로 변경 금지)

> **2026-09-01 3차 보정**: 이 PR은 실제 activation PR이 아니며, `FDC_
> ACTUAL_DISPATCH_BUY_ENABLED`(actual flag)와는 **완전히 별개인**
> `FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED`(shadow flag)만 사용한다(§7).
> §1/§3/§4에서 확인한 provider 전체 quota 결함이 해결되지 않은 상태
> 이므로, 이 단계에서는 **실제 HTTP 호출·실제 reservation 소비·주문
> 경로 변경을 전혀 발생시키지 않는 관측 전용** PR로 한정한다. held_
> position이 이미 거친 것과 동일한 단계(원 설계 문서 §15 "① lifecycle
> 관측", `mode='shadow'`/`register_shadow_job_and_judge()` 패턴 재사용)
> 를 BUY에도 반복한다.
- **변경 대상 파일**: `decision_agent_runner.py`(§5 판정 함수를 shadow
  전용 관측 경로에서만 호출 — `mode='shadow'` job 등록, 실제 dispatch
  분기(§5 3-way if/elif)에는 아직 연결하지 않음), `run_decision_loop.py`
  (관측 로그/집계만 추가), `src/agent_trading/config/settings.py`,
  `.env.example`, `docker-compose.yml`, `scripts/harness/contracts/
  runtime_env_wiring.json`(§7의 `FDC_ACTUAL_DISPATCH_BUY_SHADOW_
  ENABLED` 4개 파일 전부 — 이 PR에서 신규 배선).
- **변경 내용**: `FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED=true`일 때만
  **quota를 전혀 소비하지 않고**, 아래 두 종류의 관측을 **명확히
  분리해서** 수행한다(2026-09-01 4차 보정 — §1 항목 5의 shadow/실제
  혼동 결함 정정). 두 관측은 서로 다른 데이터 소스이며, 하나가 다른
  하나의 입력이나 결과가 아니다.

  **(A) 동일 quota_scope의 공유 shadow FIFO 관측**(`register_shadow_
  job_and_judge()` 재사용 — 2026-09-01 5차 보정으로 "BUY shadow 내부
  관측"에서 명칭 정정, §3 확정 사실: window_count SQL에 `source_type`
  조건이 없어 held_position 등 다른 lane의 shadow 행과 **판정을
  공유**한다):
  - **BUY 행 단독 집계**(BUY 행만 걸러서 셀 수 있는 것 — `source_type`
    이 저장은 되므로 사후 필터링 가능): shadow job 등록 수(BUY_
    CANDIDATE 발생량), BUY 행의 `enqueue_sequence` 기준 등록 순서.
  - **shared-shadow 판정**(다른 lane의 shadow 행 영향을 받는 것 —
    BUY 행만 따로 격리해 집계할 수 없음): BUY 행의 `SHADOW_WOULD_
    GRANT`/`SHADOW_QUEUED` 판정 수·비율, 동일 scope 전체(held_position
    shadow 행 포함)의 `fdc_ready_at` 기준 window 포화 빈도. 이 판정은
    "BUY만의 가상 포화"가 아니라 **같은 scope를 공유하는 모든 lane의
    shadow 행이 함께 만드는 상태**의 결과다.

  **(B) read-only 실제 부하 관측**(shadow judge와 완전히 별도의 read-only
  조회/로그 관측 — shadow judge의 입력도 출력도 아님을 명시):
  - held_position `mode='real'` reservation/`fdc_provider_attempts` 건수
  - legacy `mode="full"` 경로의 실제 provider HTTP 시작 시각 및 재시도
    (NOT VERIFIED — 아래 참고)
  - 위 실측을 이용한 provider 전체 60초 sliding window 관측값

  legacy 경로의 실제 HTTP 시작 시각은 현재 `trading.fdc_provider_
  attempts`에 전혀 기록되지 않으므로(§3), 이 관측은 `docker logs`류의
  provider 클라이언트 HTTP 요청 로그 grep으로만 가능하다 — 이는 초 단위
  타임스탬프의 임시 조회 방법일 뿐, 로그 rotation/보존 정책에 따라
  과거 데이터가 유실될 수 있는 **영속적이지 않은 근거**다. 지속적인
  운영 관측 지표로 자동화하려면 별도 로그 파이프라인/저장 설계가
  필요하며, 이 문서는 그 설계를 확정하지 않았으므로 **(B)의 legacy
  실제 HTTP 시각 관측 방법 자체는 `NOT VERIFIED`로 남긴다**(§3 NOT
  VERIFIED 목록에도 추가).

  **이 관측 코드는 `FDC_ACTUAL_DISPATCH_BUY_ENABLED`(actual flag)를
  참조하지 않는다** — 그 값이 무엇이든(PR B가 배선만 했으므로 운영에서
  실수로 `true`가 돼 있어도) 이 PR의 동작에는 아무 영향이 없다(§7 필수
  계약).
- **허용된 용도와 금지된 해석**(4차 보정 신설, 5차 보정으로 shared-
  shadow 구분 반영):
  - **허용**: BUY 후보량(등록 수)과 BUY 행의 shadow 결과(`SHADOW_
    WOULD_GRANT`/`SHADOW_QUEUED`)를, "동일 scope shared-shadow 환경
    에서 관측된 값"으로 기록한다.
  - **허용**: held_position shadow와 BUY shadow의 `source_type`별
    등록 수·상태 분포를 나란히 제시한다(예: 표나 그래프로 두 lane을
    비교 — 단, 서로를 예측치로 변환하지 않는다).
  - **금지**: BUY shadow 상태(`SHADOW_WOULD_GRANT`/`SHADOW_QUEUED`)를
    "BUY만의 대기·포화·거부율"로 해석하는 것 — 이 판정은 §3에서
    확인했듯 같은 scope의 held_position shadow 행을 포함한 shared-
    shadow 상태의 결과이지, BUY 후보끼리만의 격리된 판정이 아니다.
  - **금지**: shared-shadow 결과(A)를 held_position 실제 reservation
    (`mode='real'`), legacy HTTP 호출, provider 전체 13 RPM 준수
    여부의 예측치나 증빙으로 사용하는 것 — `register_shadow_job_and_
    judge()`가 `mode='shadow'` 행만 집계한다는 사실(§3)이 이 금지의
    근거다.
  - (B)는 실측이지만 (A)의 입력이나 출력이 아니며, (A)와 (B)를 하나의
    지표로 합산하거나 서로를 보정하는 계산도 이 PR에서는 수행하지
    않는다. **실제 경쟁을 가정한 counterfactual replay(예: "이 BUY
    후보가 실제로 reservation을 요청했다면 몇 초를 기다렸을지"
    시뮬레이션)는 이 PR에서 구현하지 않는다** — §8 "PR C 범위 밖" 참고.
  - **실제 provider-wide 경쟁 판정, 그리고 BUY만 격리된("BUY-only")
    shadow 판정이 필요하다면, 둘 다 이 PR의 범위 밖이며 별도 설계
    대상**이다 — 전자는 §8 PR D(provider 전체 quota 통합), 후자는
    아래 "PR C 범위 밖: BUY-only shadow 판정" 참고.
- **금지되는 변경**: 실제 HTTP 호출을 유발하는 경로 추가 금지, `try_
  reserve()`(실제 reservation 소비) 호출 금지, 주문 경로(`run_execution_
  pipeline()`) 변경 금지. held_position 분기, 기존 `mode="full"` 경로
  변경 금지. `FDC_ACTUAL_DISPATCH_BUY_ENABLED`(actual flag)를 조건문에
  사용하는 것 금지(§7). provider-wide counterfactual wait/rejection을
  산출하는 코드 추가 금지(아래 "PR C 범위 밖" 참고). (A) shadow 판정
  결과를 (B) 실측과 결합해 "실제 예상 대기시간/거부율"류의 파생 지표를
  산출하는 코드 추가 금지.
- **Acceptance Criteria**: shadow flag가 활성화돼도 실제 provider
  HTTP 호출량·held_position 실전 dispatch 동작·주문 제출 경로가 이전과
  100% 동일(회귀 없음) — 이 PR은 순수 관측이므로 "아무 것도 실제로
  바뀌지 않았음"이 곧 성공 조건이다. **actual flag가 `true`인 상태에서
  shadow flag가 false/true 어느 쪽이어도 actual-dispatch가 전혀 발생하지
  않음**(§10 테스트 3). (A) shared-shadow FIFO 관측과 (B) 실제 부하
  관측이 코드·산출물 양쪽에서 명확히 분리된 별도 필드/로그로 기록됨
  (하나의 파생 지표로 합쳐지지 않음). (A) 내부에서도 BUY 행 단독
  집계(등록 수/순서)와 shared-shadow 판정(`SHADOW_WOULD_GRANT`/
  `SHADOW_QUEUED`, 다른 lane 영향 받음)이 별도 필드로 구분 기록됨 —
  후자를 "BUY-only"라는 라벨로 기록하지 않음.
- **단위/통합/운영 검증**: `accept backend-file decision_agent_runner.py`,
  `accept script-file run_decision_loop.py`, `accept env`(shadow flag
  배선 확인), `test-file` 관련 스위트, `accept no-bypass`.
- **롤백 조건**: 관측 코드가 실제 HTTP 호출·reservation·주문 경로에
  조금이라도 영향을 준 것이 드러나면 즉시 되돌림(이 PR의 존재 이유
  자체가 무영향 관측이므로), (A)와 (B)를 결합한 파생 지표나
  counterfactual replay가 코드에 포함된 것이 드러나면 즉시 되돌림,
  또는 이 코드가 actual flag를 참조하는
  것이 발견되면 즉시 되돌림.

### PR C 범위 밖: counterfactual replay(2026-09-01 4차 보정 신설)

실제 경쟁을 가정한 counterfactual replay("이 BUY 후보가 실제로
provider 전체(legacy+held_position+BUY)와 경쟁했다면 얼마나 대기·거부
됐을지"를 사후 재현하는 기능)가 필요하다고 판단되면, 이는 **PR C의
기능이 아니라 PR D 이후 별도 설계·구현 대상**으로 분리한다. PR D
자체의 필수 범위(§8 PR D)에도 포함하지 않는다 — PR D는 provider 전체
quota의 **실시간 회계 통합**이 목적이고, counterfactual replay는 그와
독립적인 **사후 분석 도구**이기 때문이다. 이 문서는 그 도구를 설계하지
않지만, 향후 누군가 도입하려 할 때 반드시 확정해야 할 항목을 명시한다.

- 입력 데이터: (A) shadow 판정 기록, (B) held_position `mode='real'`
  reservation 기록, (C) legacy 실제 HTTP 시각 기록(§8 PR C에서 이미
  `NOT VERIFIED`로 남긴 신뢰 가능한 저장소 문제를 먼저 해결해야 함) —
  이 세 소스를 어떻게 정렬·병합할지.
- 60초 반열림 구간 `(t-60s, t]`의 적용 방식과 경계 처리(현재 `try_
  reserve()`가 쓰는 `reserved_at > now() - make_interval(...)` 방식과
  일치시킬지, 다른 방식을 쓸지).
- 동일 시각(밀리초 단위까지 같은) 이벤트의 tie-breaker 규칙.
- held_position/legacy의 재시도(429/5xx)를 replay에 포함하는 방식 —
  포함하지 않으면 실제보다 낙관적인 재현이 되고, 포함하면 §8 PR D의
  전역 회계와 동일한 재시도 규칙을 그대로 가져와야 정합성이 맞는다.
- 출력(재현된 대기시간/거부 여부)의 신뢰 한계를 얼마나 명시적으로
  표시할지 — 이 문서가 이미 지적한 대로, 입력 데이터 중 하나(legacy
  실제 시각)가 불완전할 수 있으므로 그 사실을 출력에도 반영해야 한다.
- read-only 보장 — replay 자체가 절대 실제 reservation이나 HTTP를
  유발하지 않는다는 것을 코드 경계로 증명하는 방법.
- 합성(synthetic) interleaving 테스트 — 실제 운영 데이터가 아니라 미리
  구성한 legacy/held_position/BUY 이벤트 시퀀스로 replay 로직 자체의
  정확성을 검증하는 테스트 계획.

**provider 전체 global quota accounting(PR D)이 확정되기 전에는, BUY
shadow 결과만으로 actual-dispatch 활성화 판단을 내리지 않는다** —
이는 §9 Acceptance Criteria에도 명시한다.

### PR C 범위 밖: BUY-only shadow 판정(2026-09-01 5차 보정 신설)

§8 PR C가 재사용하는 `register_shadow_job_and_judge()`는 §3에서
확인했듯 `source_type` 조건 없이 동일 `quota_scope`의 모든 shadow 행을
함께 판정하는 **shared-shadow** 함수다. 만약 향후 "다른 lane(특히
held_position)의 shadow 행과 완전히 격리된, BUY 후보끼리만의 가상
FIFO 판정"(BUY-only shadow)이 실제로 필요하다고 판단되면, 다음을
`NOT VERIFIED`이자 후속 설계 항목으로 남긴다.

- **현재 `register_shadow_job_and_judge()`를 그대로 재사용하는 것만으로는
  BUY-only shadow 판정을 만들 수 없다** — window_count SQL이
  `source_type`을 걸러내지 않는 구조적 한계이며, 이 함수를 호출하는
  쪽에서 사후에 BUY 행만 골라내도 판정값(`SHADOW_WOULD_GRANT`/
  `SHADOW_QUEUED`) 자체는 이미 다른 lane의 영향을 받은 뒤다.
- **BUY-only shadow가 필요하다면 `source_type`을 포함한 별도 저장/
  판정 계약이 필요하다** — 예를 들어 window_count SQL에 `AND source_
  type = $N` 조건을 추가하는 최소 변경안이든, 아예 별도 shadow 판정
  테이블/함수를 두는 격리 모델이든, 새로운 계약을 명시적으로 설계해야
  한다. 이번 문서는 어느 쪽이 맞는지 결정하지 않는다.
- **이 변경은 §4에서 다룬 actual quota_scope 분리나 §8 PR D의 provider
  전체 quota 해결책을 의미하지 않는다** — shadow(관측 전용, quota
  미소비)와 actual(quota 실제 소비)은 완전히 다른 층이며, BUY-only
  shadow를 도입해도 §4의 "actual 단일 scope 공유" 결정이나 PR D의
  provider 전체 통합 회계 필요성은 전혀 바뀌지 않는다.
- **별도 모델을 도입하기 전에는 현재 shared-shadow 관측 의미를
  유지한다** — 즉 §8 PR C의 (A)는 계속 "동일 quota_scope의 공유
  shadow FIFO 관측"으로 남으며, "BUY만의" 판정으로 재해석되지 않는다.

### PR D — provider 전체 quota 통합 설계 및 구현 (필수, PR E의 선행 조건)

> **이 PR이 병합·검증되기 전에는 `FDC_ACTUAL_DISPATCH_BUY_ENABLED`를
> 활성화하지 않는다.** §1/§3/§4에서 확인한 legacy(파일 기반 10 RPM)와
> actual coordinator(Postgres 기반, 현재 13 RPM target) 사이의 회계
> 불일치를 해소하는 것이 이 PR의 목적이다.
- **변경 대상 파일**: §4에서 제시한 3가지 설계 대안 중 하나(또는 그
  조합)에 따라 달라진다 — `fdc_rate_limiter.py`/`provider_client.py`
  (legacy를 coordinator로 통합하는 대안 1·2의 경우), `fdc_quota_
  coordinator.py`/`repositories/postgres/fdc_quota.py`(전역 global
  coordinator를 신설하는 대안 3의 경우). **이번 문서는 어느 대안을
  택할지 결정하지 않는다** — PR D 자체의 설계 검토에서 확정한다.
- **변경 내용**: provider(Gemini) 전체로 나가는 실제 HTTP 호출(legacy
  `mode="full"` 경로 포함, 429/5xx 재시도 포함)이 **하나의 회계 체계**로
  합산·제한되도록 만든다. held_position/BUY actual-dispatch의 기존
  동작(§2)은 이 PR 이후에도 그대로 유지돼야 한다.
- **금지되는 변경**: `FDC_ACTUAL_DISPATCH_BUY_ENABLED`를 이 PR 안에서
  true로 활성화하는 것 금지(활성화는 PR E). held_position의 기존
  실전 계약(§2, target 13 RPM 등)을 근거 없이 변경 금지.
- **Acceptance Criteria**(§9에 상세):
  - legacy full 경로와 held_position/BUY actual-dispatch 경로를 동시에
    실행해도 provider 전체 HTTP **시작 시각** 기준 sliding 60초 최대
    13 이하.
  - 429 재시도를 포함한 모든 provider HTTP 시도가 전역 quota 회계에
    반영됨(빠짐없이).
  - coordinator와 legacy limiter를 모두 우회하는 FDC HTTP 경로 0건.
- **단위/통합/운영 검증**: 선택한 대안에 따라 달라지나, 공통으로
  provider 전체 호출량을 실측하는 통합 테스트(§10) 및 `accept no-bypass`,
  `accept architecture`.
- **롤백 조건**: 선택한 대안이 held_position의 기존 13 RPM 실전 계약을
  변경하거나, provider 전체 60초 합산이 13을 초과하는 시나리오가 테스트
  에서 재현되면 병합 보류.

### PR E — BUY actual-dispatch 배선 연결(PR D 이후에만 검토 가능, flag=false 기본)

> **이 PR은 `FDC_ACTUAL_DISPATCH_BUY_ENABLED`(actual flag)를 처음으로
> runtime 분기에서 읽는 PR이다** — PR B는 이 값을 배선(파싱)만 했고,
> PR C/D는 이 값을 아예 참조하지 않았다(§7). 즉 이 PR이 머지되기 전까지는
> actual flag 값이 무엇이든 실제 동작에 영향이 없었고, 이 PR이 머지된
> **이후부터** 비로소 그 값이 의미를 갖기 시작한다 — 그래서 이 PR의
> **코드 병합 자체와 flag의 실제 활성화(false→true 변경)는 반드시
> 별개 사건으로 취급**해야 한다(아래 Acceptance Criteria/롤백 조건).
- **선행 조건**: PR D가 병합되고 §9의 provider 전체 quota Acceptance
  Criteria가 전부 통과해야 이 PR을 시작할 수 있다.
- **변경 대상 파일**: `decision_agent_runner.py`(§5 3-way 분기 실제
  연결), `run_decision_loop.py`(`_run_fdc_actual_dispatch_phase()`가
  BUY job도 처리 — lane-agnostic 인프라 재사용이라 최소 변경, §6의
  submit 예산 시점 계약 명시적 반영).
- **변경 내용**: `FDC_ACTUAL_DISPATCH_BUY_ENABLED=true`일 때만 BUY
  후보가 실제로 pending 경로에 진입. quota_scope는 §4 결정에 따라
  기존 `gemini:shared-operational` 그대로(신규 scope 코드 없음). PR D가
  구축한 provider 전체 통합 회계 위에서 동작해야 한다. `FDC_ACTUAL_
  DISPATCH_BUY_SHADOW_ENABLED`(shadow flag)는 이 PR의 실제 dispatch
  분기와 무관하다 — 참조하지 않는다.
- **금지되는 변경**: held_position 분기, risk gate/sizing/submit-lane/
  reconciliation lock/broker contract check(§6) 변경 금지, 기존
  `FDC_ACTUAL_DISPATCH_ENABLED`의 의미·기본값 변경 금지, 신규
  quota_scope 도입 금지(§4), PR D 없이 이 PR을 단독으로 활성화하는 것
  금지, shadow flag를 actual dispatch 분기 조건에 사용하는 것 금지.
- **Acceptance Criteria**: `FDC_ACTUAL_DISPATCH_ENABLED`(held_position)와
  `FDC_ACTUAL_DISPATCH_BUY_ENABLED`(actual flag) 모두 false에서 기존
  core/BUY 경로 byte-for-byte 동일(§9, shadow flag 값과 무관하게 동일해야
  함), actual flag가 true일 때만 BUY_CANDIDATE 대상만 actual-dispatch
  경로 진입, held_position 실전 경로는 완전히 무영향, provider 전체
  60초 합산이 PR D의 통합 회계 기준으로 13 이하 유지.
- **단위/통합/운영 검증**: `accept backend-file` ×2(`decision_agent_
  runner.py`, `decision_orchestrator.py` — 후자는 §5 second pass 경로가
  실제로 lane-agnostic임을 재확인하는 정도), `accept script-file
  run_decision_loop.py`, `test-file` 전체(§10 목록), `accept no-bypass`,
  `accept architecture`, `accept env`.
- **rollout preflight(배포 전 필수 확인)**: PR E를 배포하기 전, 컨테이너의
  실제 `FDC_ACTUAL_DISPATCH_BUY_ENABLED` 값을 조회해 `false`인지 확인
  한다. 이미 `true`라면(어떤 경로로든) 배포·재시작·활성화를 진행하지
  않고 원인 규명 후 별도 운영 승인으로 처리한다(§10 테스트 5, §11).
- **롤백 조건**: `FDC_ACTUAL_DISPATCH_BUY_ENABLED`를 false로 되돌리는
  것만으로 즉시 이전 동작이 복원돼야 한다(구조적 요구사항이자 acceptance
  criteria) — 이 조건이 성립하지 않으면(즉 flag=false인데도 동작이
  달라지면) 이 PR 자체가 결함으로 간주된다. `FDC_ACTUAL_DISPATCH_BUY_
  ENABLED=true` 활성화 자체도 §9/§11에 명시된 검증과 별도 운영 승인
  이후에만 수행한다(코드 병합과 flag 활성화는 별개 사건이다). `FDC_
  ACTUAL_DISPATCH_BUY_SHADOW_ENABLED`는 이 PR의 어떤 동작에도 관여하지
  않으므로, 그 값이 true인 채로 이 PR이 머지·배포돼도 actual-dispatch가
  자동으로 시작되지 않는다(§1 항목 4의 flag 의미 충돌 결함이 이 설계로
  해소됨).

## 9. Acceptance Criteria (전체 요약)

- `FDC_ACTUAL_DISPATCH_ENABLED=false AND FDC_ACTUAL_DISPATCH_BUY_ENABLED=false`:
  기존 core/BUY `mode="full"` 경로, held_position 기존 경로 모두 완전히
  동일(회귀 없음) — 최우선 조건. `FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED`
  값(false/true 어느 쪽이든)은 이 조건에 영향을 주지 않아야 한다.
- `FDC_ACTUAL_DISPATCH_ENABLED=true AND FDC_ACTUAL_DISPATCH_BUY_ENABLED=false`:
  현재 운영 상태와 완전히 동일(이번 확장 이전 상태 재현) — held_position만
  실전 dispatch, BUY는 기존 로컬 limiter 경로.
- `FDC_ACTUAL_DISPATCH_BUY_ENABLED=true`(**PR E 이후에만 의미를 가짐**,
  §7/§8): BUY_CANDIDATE만 actual-dispatch 진입, held_position과 같은
  quota_scope 공유, FIFO는 lane 구분 없이 `enqueue_sequence` 순.
- `FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED=true`(**PR C부터 의미를 가짐**,
  PR E 이후에도 계속 관측 전용): BUY 후보 lifecycle/FIFO/quota 대기
  예상치만 관측되고, 실제 HTTP/reservation/주문 경로에는 어떤 영향도
  없어야 한다 — `FDC_ACTUAL_DISPATCH_BUY_ENABLED`가 무엇이든 이 조건은
  성립해야 한다(§10 테스트 2).
- 두 flag는 완전히 독립적으로 동작해야 한다 — 어느 한쪽 값을 바꿔도
  다른 쪽의 리졸버 결과나 의미가 바뀌지 않는다(§7).
- 신규 quota_scope, 정적 RPM 분할, FIFO 우선순위 코드가 이번 범위에
  전혀 포함되지 않았음(§4).
- §7의 배선 파일(2개 key × 4개 파일)이 모두 갱신됐고 `accept env` 통과.
- §6의 3개 재평가 계약(quote freshness, buy_duplicate_guard/reconciliation
  lock, submit 예산 시점)이 테스트로 증명됨.
- `decision_context_id` 3자 일치 계약이 BUY job에도 성립.
- no-bypass 정책 위반 0건(`accept no-bypass`), 아키텍처 계층 위반 0건
  (`accept architecture`).

### PR D/E 전용 Acceptance Criteria (2026-09-01 2차 보정 추가)

- **legacy full 경로와 held_position/BUY actual-dispatch 경로를 동시에
  실행해도 provider 전체 HTTP 시작 시각 기준 sliding 60초 최대 13
  이하**여야 한다 — coordinator가 grant한 reservation 수만이 아니라,
  legacy `mode="full"` 경로의 실제 HTTP 호출까지 합산한 수치로 검증한다
  (§3 확정 사실의 "13+10=23" 위험을 직접 반증하는 지표).
- **429 재시도를 포함한 모든 provider HTTP 시도가 전역 quota 회계에
  반영**돼야 한다 — legacy limiter의 재시도(`fdc_rate_limiter.py:606-
  618`)든 coordinator의 재시도(`apply_retry_failure`)든, 어느 경로의
  재시도도 회계 밖에서 발생해서는 안 된다.
- **coordinator와 legacy limiter를 모두 우회하는 FDC HTTP 경로가 0건**
  이어야 한다(제3의 경로 신설 금지).
- **BUY actual 활성화(`FDC_ACTUAL_DISPATCH_BUY_ENABLED=true`) 전 shadow
  관측**(PR C)으로 BUY 대상 후보량과 동일 quota_scope 공유 shadow FIFO
  경향(§8 PR C (A))을 먼저 확인해야 한다. **PR C shadow 결과(`SHADOW_
  WOULD_GRANT`/`SHADOW_QUEUED`)만으로 provider 전체 호출량, held_
  position 실제 대기/거부율, 실제 FIFO 영향을 입증하지 않는다**
  (2026-09-01 4차·5차 보정 — §1 항목 5·6, §3 확정 사실, §8 PR C 근거)
  — 이 shadow 결과는 held_position 등 다른 lane의 shadow 행과 판정을
  공유하는 값일 뿐, "BUY만의" 격리된 값도, 실제 경합의 예측치도 아니다.
  그 실측은 §8 PR C (B)의 별도 read-only 관측과 PR D의 provider 전체
  통합 회계로만 입증한다.
- **`FDC_ACTUAL_DISPATCH_BUY_ENABLED=true` 활성화는 위 검증(PR D 병합+
  Acceptance Criteria 통과)과 별도로, 운영 승인 이후에만 가능**하다 —
  PR E의 코드 병합 자체가 활성화를 의미하지 않는다(§11 rollout 순서).
  이 활성화의 선행 조건에는 "PR C shadow 결과만으로 provider-wide
  경쟁을 입증하지 않는다"가 명시적으로 포함된다 — shadow 관측은 참고
  자료일 뿐, PR D의 provider 전체 quota 통합 회계와 그 Acceptance
  Criteria(위 3개 항목)가 실제 입증 근거다.

### shadow/actual flag 분리 Acceptance Criteria (2026-09-01 3차 보정 추가)

§10에 명시하는 아래 5개 테스트가 전부 통과해야 한다.

1. PR B: actual flag(`FDC_ACTUAL_DISPATCH_BUY_ENABLED`)가 false/true
   어느 값이어도 BUY가 기존 `mode="full"` 경로를 유지한다.
2. PR C: shadow flag(`FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED`)가 true여도
   실제 HTTP, reservation, `fdc_only`, broker submit이 호출되지 않는다.
3. PR C: actual flag가 true + shadow flag가 false/true 어느 조합이어도
   actual-dispatch가 발생하지 않는다(actual flag를 읽는 코드가 PR C
   시점에는 존재하지 않으므로 구조적으로 성립).
4. PR E: PR D 통과 후 actual flag가 true일 때만 BUY actual-dispatch에
   진입한다(shadow flag 값과 무관).
5. rollout preflight: PR E 배포 전 actual flag가 false가 아니면(즉 이미
   true이면) 배포를 중단하고 별도 운영 승인으로 처리한다.

## 10. 테스트 계획

### 단위 테스트

- `_is_fdc_actual_dispatch_buy_target()`: BUY_CANDIDATE+core+주문가능 →
  대상, NO_ACTION/WATCH_CANDIDATE/risk-off/비주문가능 → 비대상. 기존
  `_is_fdc_actual_dispatch_target()`은 무수정이므로 기존 테스트 재사용.
- 신규 flag 2개(`FDC_ACTUAL_DISPATCH_BUY_ENABLED`, `FDC_ACTUAL_DISPATCH_
  BUY_SHADOW_ENABLED`) 각각의 settings 리졸버 단위 테스트(기본값/true/
  false), 그리고 두 값을 4가지 조합(false/false, true/false, false/true,
  true/true)으로 섞어도 서로의 리졸버 결과가 영향받지 않는지.
- `complete_fdc_actual_dispatch()`의 `caller_id`/`source_type` 파라미터화
  — held_position 기존 값과 동일한지, BUY 값을 넘겼을 때 정확히 그
  값이 쓰이는지(하드코딩 제거 검증).

### shadow/actual flag 분리 테스트 (2026-09-01 3차 보정, §9와 동일 목록)

1. **PR B**: actual flag(`FDC_ACTUAL_DISPATCH_BUY_ENABLED`)가 false/true
   어느 값이어도 BUY가 기존 `mode="full"` 경로를 유지하는지 — 이 PR
   시점에는 이 값을 읽는 실행 분기 자체가 없으므로, 어떤 값을 넣어도
   `run_agents_in_subprocess()`의 산출물이 동일해야 한다.
2. **PR C**: shadow flag(`FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED=true`)
   여도 실제 HTTP, `try_reserve()`(reservation), `fdc_only` subprocess,
   broker submit이 전혀 호출되지 않음을 mock assertion으로 확인
   (`assert_not_called()`류).
3. **PR C**: actual flag(`FDC_ACTUAL_DISPATCH_BUY_ENABLED=true`) +
   shadow flag(false 또는 true) 조합에서도 actual-dispatch가 발생하지
   않음 — PR C 코드베이스에는 actual flag를 읽는 분기가 아예 없으므로
   구조적으로 성립해야 하며, 혹시라도 참조하는 코드가 있다면 이 테스트가
   실패해야 한다.
4. **PR E**: PR D 통과 후 actual flag(`true`)일 때만 BUY actual-dispatch
   진입 — shadow flag 값(false/true 어느 쪽)과 무관하게 이 판정이
   동일해야 한다.
5. **rollout preflight**: PR E 배포 전 actual flag의 실제 container 값을
   조회해 `false`가 아니면(이미 `true`면) 배포 스크립트/체크리스트가
   중단되는지 — 코드 테스트라기보다 §11의 배포 전 점검 절차 자체를
   문서로 검증하는 항목이다.

### PostgreSQL 통합 테스트

- `test_fdc_quota_coordinator.py`에 BUY job 케이스 추가 — 동일
  `quota_scope`에서 held_position job과 BUY job이 섞였을 때 60초 window
  합산이 올바른지(예: held_position 7건 + BUY 6건 = 13건에서 14번째는
  거부), FIFO(`enqueue_sequence`)가 lane 구분 없이 순수 등록 순서로
  동작하는지.
- §9 요약의 신규 scope 미도입을 실측으로도 확인 — `fdc_quota_state`
  테이블에 `gemini:shared-operational` 외 다른 행이 생기지 않았는지
  (read-only SELECT로 이 문서 작성 세션에서도 확인 가능한 항목이며,
  실제 배포 후 재확인 대상).

### 종단 간 테스트

- PR #361의 in-memory 종단 간 테스트 패턴(`TestFdcActualDispatchEndTo
  EndContextContinuity`, `tests/scripts/test_run_decision_loop.py`)을
  BUY 시나리오로 복제 — `fdc_queue_job.decision_context_id ==
  agent_run.decision_context_id == trade_decision.decision_context_id`가
  BUY job에도 성립하는지.
- durable resume: BUY job이 `list_resumable_real_jobs()`로 재개된 뒤
  `buy_duplicate_guard`/`_has_active_reconciliation_lock()`이 재개
  시점의 최신 상태를 조회하는지(§6 항목 2).
- stale snapshot: BUY job이 여러 cycle에 걸쳐 지연된 뒤 second pass가
  그 시점 기준 fresh quote로 `stale_snapshot_guard`를 재평가하는지(§6
  항목 1) — first pass 시점의 오래된 quote가 재사용되지 않음을 명시
  적으로 증명.
- submit 예산: pending 등록 시점에 `submit_budget_consumed_count`가
  증가하지 않고, second pass의 실제 제출 결과 확정 시점에만 증가하는지
  (§6 항목 3).
- 429 재시도와 최종 fail-closed HOLD, pre-HTTP 실패와 §9 회계 불변식
  (원 설계 문서 §9)이 BUY job에도 동일하게 성립하는지 — 기존 held_
  position 테스트를 BUY 파라미터로 복제.
- risk/sizing/submit-lane/reconciliation이 우회되지 않는지 — `run_
  execution_pipeline()`의 각 게이트 함수가 정확히 동일한 순서로 호출됨을
  mock assertion으로 확인(§6 첫 문단이 구조적으로 보장한다는 주장을
  실제 테스트로 뒷받침).
- flag=false 조합(§9)에서 기존 core/BUY 전체 테스트 스위트 무수정 통과.

### provider 전체 quota 통합 테스트 (PR D)

- 선택한 설계 대안(§4/§8 PR D의 3가지 대안 중 확정된 것)에 대해, legacy
  `mode="full"` 경로와 held_position/BUY actual-dispatch 경로를 **동시에**
  발생시켰을 때 provider 전체 HTTP 시작 시각 기준 sliding 60초 window가
  13을 넘지 않는지 직접 재현하는 통합 테스트 — 예: legacy 경로를
  시뮬레이션하는 fake HTTP 카운터와 coordinator의 실제 reservation을
  같은 시간대에 섞어 넣고 합산 검증.
- 429/5xx 재시도가 어느 경로에서 발생하든 전역 회계에 정확히 반영되는지
  (§9 PR D/E 전용 Acceptance Criteria의 재시도 회계 항목).
- coordinator/legacy 우회 경로가 없는지 — FDC HTTP를 유발할 수 있는
  모든 코드 경로(정적 분석 또는 grep 기반 감사)가 두 회계 체계 중
  하나를 반드시 거치는지 확인.

### 운영 shadow 테스트 (PR C, `FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED=true`, 실제 quota 미소비)

실제 activation(actual flag) 전, shadow flag만 켠 상태로 최소 1~2주간
관측한다. §8 PR C의 (A)/(B) 구분을 그대로 유지해 각각 별도로 기록·
보고한다 — 하나로 합치지 않는다(2026-09-01 4차 보정, 5차 보정으로
(A) 명칭·해석 정정).

**(A) 동일 quota_scope의 공유 shadow FIFO 관측**(`register_shadow_
job_and_judge()`, `mode='shadow'` 행만 — 5차 보정으로 "BUY shadow
내부 관측"에서 명칭 정정): BUY_CANDIDATE 발생 빈도(=BUY 행 단독 집계,
shadow job 등록 수), BUY 행의 `SHADOW_WOULD_GRANT`/`SHADOW_QUEUED`
판정 비율(이 판정은 held_position 등 동일 scope의 다른 lane shadow
행 영향을 받는 shared-shadow 결과 — "BUY만의" 값이 아니다, §3/§8 PR
C), BUY 행의 `enqueue_sequence` 기준 등록 순서. **이 지표만으로 실제
대기시간이나 거부율을 계산·보고하지 않으며, BUY만 격리된 값으로
서술하지 않는다.**

**(B) read-only 실제 부하 관측**(shadow judge와 무관한 별도 관측):
held_position job과의 동시 발생 빈도(같은 60초 창에 겹치는 실제
`mode='real'` reservation 건수), legacy `mode="full"` 경로의 실제
provider 호출량(§3에서 확인한 대로 이는 coordinator 밖에서 발생하므로
별도 관측이 필요 — 방법 자체는 §8 PR C에서 `NOT VERIFIED`로 남긴
로그 grep 한계를 그대로 적용받는다).

held_position shadow와 BUY shadow의 `source_type`별 등록 수·상태
(`SHADOW_WOULD_GRANT`/`SHADOW_QUEUED`) 분포를 나란히 제시하는 것은
허용한다 — 단 이 비교는 "두 lane이 같은 shared-shadow FIFO를 어떻게
나눠 쓰는지"를 보여주는 관측이며, 어느 한쪽을 다른 쪽의 예측치로
변환하는 계산은 아니다.

(A)와 (B)를 나란히 놓고 사람이 판단 자료로 쓰는 것은 허용하지만,
"만약 실제로 quota를 공유했다면 예상되는 거부율"류의 **파생 시뮬레이션
값을 코드가 산출하는 것은 이 PR의 범위가 아니다**(§8 "PR C 범위 밖:
counterfactual replay"). (A)+(B) 원자료 자체가 §4에서 보류한 우선순위/
분할 필요성 판단과 PR D의 설계 대안 선택 근거 자료가 된다.

## 11. rollout, rollback, 즉시 중단 기준

### rollout 순서

1. PR A→B 순서로 병합(둘 다 `FDC_ACTUAL_DISPATCH_BUY_ENABLED=false`
   기본이므로 운영 동작에 영향 없음 — PR B는 이 값을 배선만 할 뿐 읽지
   않는다, §7), 각 PR 사이에 최소 1 사이클 이상 운영 관측.
2. PR C(BUY shadow 관측, 실제 HTTP/reservation/주문 변경 없음) 병합 후,
   **shadow flag(`FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED`)만 `true`로
   전환**해 최소 1~2주 관측 데이터 축적 — actual flag(`FDC_ACTUAL_
   DISPATCH_BUY_ENABLED`)는 이 단계 내내 `false`로 유지한다(전환할
   필요도 없다 — PR C는 이 값을 읽지 않는다, §7). §8 PR C의 (A) 동일
   quota_scope 공유 shadow FIFO 관측과 (B) read-only 실제 부하 관측을
   **분리해서** 축적하고,
   §4에서 보류한 우선순위/분할 필요성과 PR D의 설계 대안 선택 근거로
   사용한다. **이 단계의 관측만으로 provider 전체(legacy+held_position+
   BUY) 실제 경쟁 수준을 확정하지 않는다** — 그 확정은 PR D의 통합
   회계와 그 실측 테스트(§9 PR D/E 전용 Acceptance Criteria)로만
   이루어진다(4차 보정).
3. **PR D(provider 전체 quota 통합 설계 및 구현)를 병합하고 §9의 PR D/E
   전용 Acceptance Criteria가 전부 통과할 때까지는 다음 단계로 진행하지
   않는다.** 이 단계가 2차 보정의 핵심 게이트다. actual flag는 계속
   `false`.
4. PR D 통과 후에만 PR E(BUY actual-dispatch 배선 연결)를 병합 — 병합
   시점에도 `FDC_ACTUAL_DISPATCH_BUY_ENABLED=false` 유지(코드 병합과
   flag 활성화는 별개 사건, §7/§8 PR E). **shadow flag가 그동안 `true`로
   켜져 있었더라도, PR E 병합만으로는 actual-dispatch가 자동으로
   시작되지 않는다** — actual flag를 명시적으로 `true`로 바꾸는 별도
   사건이 있어야만 시작된다(3차 보정으로 해소된 §1 항목 4의 결함).
5. PR E 배포 전 사전 점검에서 **두 flag의 실제 container 환경값을 모두
   조회해 기록**한다 — actual flag가 `false`가 아니면 배포를 중단하고
   원인 규명 후 별도 운영 승인으로 처리한다(§8 PR E rollout preflight,
   §10 테스트 5). shadow flag 값은 기록만 하고 배포 중단 사유는 아니다.
6. PR #361 검증에 사용했던 것과 동일한 절차 반복: 사전 점검(운영 코드
   SHA/두 flag 값 확인) → 제한 활성화 승인 트리거 확인(actual flag를
   `true`로 변경) → 자연 cycle 1~2개 read-only 관측 → 문제 없으면 자연
   cycle 3~5개 read-only 실측(context 연속성, 13 RPM, FIFO, 회계 불변식,
   held_position 기아 여부, **provider 전체(legacy+actual 합산) 60초
   호출량** 포함).

### rollback

- **PR C shadow 관측의 활성화·롤백은 shadow flag(`FDC_ACTUAL_DISPATCH_
  BUY_SHADOW_ENABLED`)만 사용**한다 — actual flag를 건드릴 필요가 없다
  (애초에 관여하지 않으므로).
- **actual flag(`FDC_ACTUAL_DISPATCH_BUY_ENABLED`)는 PR E 운영 승인
  전까지 계속 `false`여야 한다** — PR B~D 어느 단계에서도 이 값을
  `true`로 바꿀 이유가 없다(바꿔도 PR E 이전에는 아무 영향이 없지만,
  §8 PR E의 rollout preflight가 이 값을 확인하므로 불필요하게 켜두지
  않는다).
- `FDC_ACTUAL_DISPATCH_BUY_ENABLED=false`로 되돌리는 것만으로 즉시 이전
  동작 복원(PR E의 Acceptance Criteria) — 코드 롤백/재배포 불필요, env
  변경 + 컨테이너 recreate만으로 충분(§7 배선 계약이 성립한다는 전제).
- `FDC_ACTUAL_DISPATCH_ENABLED`(held_position)는 이 확장과 완전히
  독립이므로, BUY 쪽에 문제가 생겨도 held_position 실전 dispatch를
  건드릴 필요가 없다.
- PR D가 도입한 provider 전체 통합 회계 자체에 결함이 발견되면, PR D를
  롤백하기 전에 먼저 `FDC_ACTUAL_DISPATCH_BUY_ENABLED=false`(이미
  false였다면 유지)를 확인하고, held_position의 기존 실전 회계
  (coordinator, target 13 RPM)가 PR D 롤백으로 영향받지 않는지 별도
  확인한다.

### 즉시 중단 기준 (파일럿 운영 관측 중 하나라도 발견 시)

- held_position job의 60초 window 거부율이 BUY 도입 전 대비 유의미하게
  증가(기아 징후).
- **provider 전체(legacy `mode="full"` 경로 + held_position/BUY
  actual-dispatch 경로 합산) 60초 실제 HTTP 시작 건수가 13을 단 한
  번이라도 초과**(2026-09-01 2차 보정 — 기존에는 "coordinator grant
  수"만 기준으로 삼았으나, §3에서 확인했듯 이는 legacy 경로를 놓친다.
  반드시 실제 HTTP 로그/provider 응답 타임스탬프 기준으로 합산 판정).
- BUY job의 `decision_context_id`가 job/agent_run/trade_decision 사이에
  불일치.
- `fdc_quota_state`에 `gemini:shared-operational` 외의 행이 생성됨
  (설계 위반 — 코드가 의도치 않게 새 scope를 만들었다는 뜻).
- **legacy FDC 호출이 (PR D 이후에도) 전역 quota 회계 밖에서 계속
  발생**하는 것이 확인됨(PR D의 목적 자체가 무효화된 상태).
- **BUY 도입 이후 held_position의 provider 대기(60초 window 거부) 또는
  실패(FDC_FAILED_FINAL) 비율이 BUY 도입 전 기준선보다 증가**.
- coordinator/DB transaction/recovery 오류, 또는 risk gate/sizing/
  submit-lane/reconciliation lock/buy_duplicate_guard 우회 정황.
- BUY 실패를 성공으로 변환한 정황(no-bypass 위반).

이 중 하나라도 발견되면 즉시 `FDC_ACTUAL_DISPATCH_BUY_ENABLED=false`로
롤백하고, 원인 분석 전까지 재활성화하지 않는다.

## 12. 기존 FDC 설계 문서와의 관계

- 이 문서는 원 설계 문서 §15 "단계적 도입"의 "③ 전체 lane(core 포함)
  전환" 단계를 구체화한 후속 문서다. 원 설계 문서가 "새 아키텍처가
  필요하지 않다"(원 설계 문서 인용, 별도 세션 조사)고 예견한 것은
  **held_position/BUY actual-dispatch job 사이의 인프라**(`fdc_queue_
  jobs`/`fdc_provider_attempts`/`FdcQuotaCoordinator`/durable resume)에
  한해 여전히 유효하다 — 이 부분은 3곳의 lane 하드코딩(§3/§8 PR A)과
  대상 판정 함수 추가(§5/§8 PR B)만으로 재사용 가능하다. 다만 이번
  2차 보정에서 드러난 legacy `mode="full"` 경로와의 provider 전체 회계
  통합 문제(§3/§4/§8 PR D)는 원 설계 문서가 다루지 않았던 **새로운
  범위**이며, "새 아키텍처가 필요하지 않다"는 예견이 이 부분까지
  포함하지는 않는다 — 원 설계 문서는 held_position 단일 lane이
  legacy 경로와 공존하는 구조 자체를 처음부터 전제하고 있었고, 그
  공존이 BUY까지 확장될 때 생기는 회계 격차는 다루지 않았다.
- 원 설계 문서 §11(수동 provider 호출 정책)은 이 확장과 무관 —
  `caller_id`가 `"manual:"` 접두사가 아닌 한(BUY도 held_position처럼
  `"ops-scheduler:..."` 접두사를 쓸 것이므로) 그 정책의 영향을 받지
  않는다.
- 원 설계 문서 §9(회계 불변식)와 PR #360(그 정정)은 lane과 무관하게
  `fdc_queue_jobs`의 카운터 컬럼 전체에 적용되는 계약이므로, BUY job에도
  변경 없이 그대로 적용된다(§10에서 재확인 대상으로 명시).
- PR #361(`decision_context_id` 단절 보정)의 계약은 이 문서 §5가
  그대로 상속한다 — 그 PR이 고친 3개 파일(`decision_agent_runner.py`,
  `decision_orchestrator.py`, `run_decision_loop.py`)의 수정 내용은
  전부 lane-agnostic이었으므로, BUY 확장을 위해 그 부분을 다시 건드릴
  필요가 없다.
- 이번 문서가 새로 도입하는 정책적 결정은 §4(quota_scope 공유 결정)와,
  2차 보정으로 추가된 "provider 전체 quota 통합(PR D)이 BUY actual-
  dispatch 활성화(PR E)의 선행 조건"이라는 게이트다 — 둘 다 원 설계
  문서에는 없던 내용이다. 원 설계 문서는 held_position 단일 lane만
  다뤘으므로 scope 공유/분리 문제도, legacy 경로와의 provider 전체
  회계 통합 문제도 제기되지 않았다.
