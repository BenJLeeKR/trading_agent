# KIS_PAPER_REST_RPS 전수 조사 보고서 (Inventory)

> **작성일**: 2026-05-25  
> **목적**: repo 전역에서 `KIS_PAPER_REST_RPS` / `paper_rest_rps` / `global_rest_capacity` 사용처 전수 조사  
> **canonical 값(기준)**: **1** (paper 환경 KIS API 초당 호출 제한)

---

## 목차

1. [설정값 분포](#a-설정값-분포)
2. [사용처 분류](#b-사용처-분류)
3. [Canonical 값(1)과의 차이](#c-canonical-값1과의-차이)
4. [`global_rest_capacity` 계산 로직 분석](#d-global_rest_capacity-계산-로직-분석)
5. [RPS=1일 때의 예상 제약 분석](#e-rps1일-때의-예상-제약-분석)
6. [발견된 버그/불일치](#f-발견된-버그불일치)

---

## A. 설정값 분포

### A.1. 설정 선언 위치

#### (1) `src/agent_trading/config/settings.py`

| 위치 | 내용 | 값 |
|------|------|-----|
| [`settings.py:141-147`](../src/agent_trading/config/settings.py:141) | `_resolve_kis_paper_rest_rps()` resolver 함수 | `os.getenv("KIS_PAPER_REST_RPS", "10")` → `max(1, int(raw))` |
| [`settings.py:329`](../src/agent_trading/config/settings.py:329) | 주석: `KIS_PAPER_REST_RPS (default 1)` | **default 1** (주석) |
| [`settings.py:335`](../src/agent_trading/config/settings.py:335) | `AppSettings.kis_paper_rest_rps` dataclass 필드 | `field(default_factory=_resolve_kis_paper_rest_rps)` |

**중요**: `_resolve_kis_paper_rest_rps()`의 docstring에는 `default 10`이라고 명시되어 있으나, [`settings.py:329`](../src/agent_trading/config/settings.py:329) 주석에는 `default 1`이라고 되어 있어 **코드와 주석이 불일치**한다. resolver 함수의 `os.getenv("KIS_PAPER_REST_RPS", "10")`는 default가 `"10"`이다.

#### (2) `docker-compose.yml`

| Service | 라인 | 설정값 | 유형 |
|---------|------|--------|------|
| **app** | [`docker-compose.yml:65`](../docker-compose.yml:65) | `KIS_PAPER_REST_RPS: "${KIS_PAPER_REST_RPS:-10}"` | env var 참조, 기본 10 |
| **api** | [`docker-compose.yml:138`](../docker-compose.yml:138) | `KIS_PAPER_REST_RPS: "${KIS_PAPER_REST_RPS:-1}"` | env var 참조, 기본 1 |
| **snapshot-sync** | [`docker-compose.yml:218`](../docker-compose.yml:218) | `KIS_PAPER_REST_RPS: "2"` | **hardcoded 2** |
| **ops-scheduler** | [`docker-compose.yml:285`](../docker-compose.yml:285) | `KIS_PAPER_REST_RPS: "${KIS_PAPER_REST_RPS:-2}"` | env var 참조, 기본 2 |
| **reconciliation-worker** | [`docker-compose.yml:392`](../docker-compose.yml:392) | `KIS_PAPER_REST_RPS: "${KIS_PAPER_REST_RPS:-2}"` | env var 참조, 기본 2 |

#### (3) `.env` / 환경 파일

| 파일 | 라인 | 값 |
|------|------|-----|
| [`.env`](../.env:27) | 27 | `KIS_PAPER_REST_RPS=1` |
| [`.env.example`](../.env.example:27) | 27 | `KIS_PAPER_REST_RPS=1` |
| [`.env.example_bak`](../.env.example_bak:36) | 36 | `KIS_PAPER_REST_RPS=1` |
| [`.env.org`](../.env.org:36) | 36 | `KIS_PAPER_REST_RPS=1` |

### A.2. 설정값 요약표

| 출처 | 선언 값 | 유효 값 (runtime) | Canonical(1)과 차이 |
|------|---------|-------------------|---------------------|
| `settings.py` resolver | default `"10"` | 10 (env unset 시) | **+9** |
| `docker-compose.yml` app | `:-10` | 10 (env unset 시) | **+9** |
| `docker-compose.yml` api | `:-1` | 1 (env unset 시) | 0 ✅ |
| `docker-compose.yml` snapshot-sync | `"2"` | 2 (hardcoded) | **+1** |
| `docker-compose.yml` ops-scheduler | `:-2` | 2 (env unset 시) | **+1** |
| `docker-compose.yml` reconciliation-worker | `:-2` | 2 (env unset 시) | **+1** |
| `.env` | `=1` | 1 | 0 ✅ |
| `build_kis_budget_manager()` default param | `paper_rest_rps=10` | 10 | **+9** |

---

## B. 사용처 분류

### B.1. 설정 선언 위치 (7곳)

| # | 파일 | 라인 | 종류 |
|---|------|------|------|
| 1 | [`settings.py:141-147`](../src/agent_trading/config/settings.py:141) | resolver 함수 정의 | Python |
| 2 | [`settings.py:335`](../src/agent_trading/config/settings.py:335) | `AppSettings` dataclass 필드 | Python |
| 3 | [`docker-compose.yml:65`](../docker-compose.yml:65) | app service env | YAML |
| 4 | [`docker-compose.yml:138`](../docker-compose.yml:138) | api service env | YAML |
| 5 | [`docker-compose.yml:218`](../docker-compose.yml:218) | snapshot-sync service env | YAML |
| 6 | [`docker-compose.yml:285`](../docker-compose.yml:285) | ops-scheduler service env | YAML |
| 7 | [`docker-compose.yml:392`](../docker-compose.yml:392) | reconciliation-worker service env | YAML |

### B.2. 읽는 위치 (consumer) — runtime 코드 (6곳)

| # | 파일 | 라인 | 용도 |
|---|------|------|------|
| 1 | [`rate_limit.py:501`](../src/agent_trading/brokers/rate_limit.py:501) | `build_kis_budget_manager()` 함수 시그니처: `paper_rest_rps: int = 10` |
| 2 | [`rate_limit.py:532`](../src/agent_trading/brokers/rate_limit.py:532) | docstring: `paper_rest_rps : int` 문서화 |
| 3 | [`rate_limit.py:574`](../src/agent_trading/brokers/rate_limit.py:574) | paper env budget 계산: `total = max(1, paper_rest_rps)` |
| 4 | [`bootstrap.py:51`](../src/agent_trading/runtime/bootstrap.py:51) | `_build_kis_adapter()` → `build_kis_budget_manager(paper_rest_rps=settings.kis_paper_rest_rps)` |
| 5 | [`snapshot_factory.py:120`](../src/agent_trading/brokers/snapshot_factory.py:120) | snapshot sync용 budget manager: `paper_rest_rps=settings.kis_paper_rest_rps` |
| 6 | [`rate_limit.py:593`](../src/agent_trading/brokers/rate_limit.py:593) | paper env `global_rest_capacity=total` 설정 |

### B.3. 읽는 위치 — standalone 스크립트 (2곳)

| # | 파일 | 라인 | 용도 |
|---|------|------|------|
| 1 | [`scripts/sync_kis_snapshots.py:432`](../scripts/sync_kis_snapshots.py:432) | standalone snapshot sync: `paper_rest_rps=settings.kis_paper_rest_rps` |
| 2 | [`scripts/run_post_submit_sync_loop.py:221`](../scripts/run_post_submit_sync_loop.py:221) | post-submit sync loop: `paper_rest_rps=settings.kis_paper_rest_rps` |

### B.4. 테스트 파일 (5곳)

| # | 파일 | 라인 | 내용 |
|---|------|------|------|
| 1 | [`test_settings.py:400-404`](../tests/services/ai_agents/test_settings.py:400) | `test_paper_rest_rps_default`: delenv → `assert == 1` |
| 2 | [`test_settings.py:529-533`](../tests/services/ai_agents/test_settings.py:529) | `test_paper_rest_rps_custom`: setenv 3 → `assert == 3` |
| 3 | [`test_settings.py:551-557`](../tests/services/ai_agents/test_settings.py:551) | `test_rest_rps_clamp_positive`: setenv -5 → `assert == 1` |
| 4 | [`test_rate_limit.py:65-77`](../tests/brokers/test_rate_limit.py:65) | `test_custom_paper_rps_scales_buckets`: `paper_rest_rps=3` |
| 5 | [`test_kis_adapter_validation.py:250`](../tests/brokers/test_kis_adapter_validation.py:250) | `monkeypatch.delenv("KIS_PAPER_REST_RPS")` + adapter build |

### B.5. 문서 파일 (20+곳)

`KIS_PAPER_REST_RPS` / `paper_rest_rps`가 언급된 문서:

| 파일 | 주요 내용 |
|------|-----------|
| [`plan_docs/10_broker_rate_limit_and_capacity_policy.md`](../plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md) | 설계 문서: RPS 기본값 1, resolver 함수 위치 |
| [`plans/57_kis_rest_rps_config.md`](../plans/57_kis_rest_rps_config.md) | 초기 RPS 설정 설계 |
| [`plans/kis_rest_strict_global_cap.md`](../plans/kis_rest_strict_global_cap.md) | global cap 설계 |
| [`plans/kis_paper_1rps_pacing_design.md`](../plans/kis_paper_1rps_pacing_design.md) | 1RPS pacing 설계 |
| [`plans/kis_paper_1rps_scheduler_serialization_2026-05-18.md`](../plans/kis_paper_1rps_scheduler_serialization_2026-05-18.md) | 1RPS scheduler serialization |
| [`plans/mode_boundary_paper_live.md`](../plans/mode_boundary_paper_live.md) | mode boundary 문서 |
| [`plans/kis_paper_order_phase1_execution.md`](../plans/kis_paper_order_phase1_execution.md) | Phase 1 실행 문서 |
| [`plans/kis_paper_order_readiness.md`](../plans/kis_paper_order_readiness.md) | readiness 확인 |
| [`plans/broker_agnostic_snapshot_factory.md`](../plans/broker_agnostic_snapshot_factory.md) | snapshot factory 설계 |
| [`plans/cash_sync_failure_and_stale_snapshot_guardrail_diagnosis_2026-05-18.md`](../plans/cash_sync_failure_and_stale_snapshot_guardrail_diagnosis_2026-05-18.md) | cash sync 장애 진단 |
| [`plans/verify_real_snapshot_based_order_sizing_and_holiday_submit_reject_path_2026-05-25.md`](../plans/verify_real_snapshot_based_order_sizing_and_holiday_submit_reject_path_2026-05-25.md) | 실전 snapshot 기반 order sizing 검증 |
| [`plans/force_actionable_decision_on_holiday_and_verify_submit_rejected_path_2026-05-25.md`](../plans/force_actionable_decision_on_holiday_and_verify_submit_rejected_path_2026-05-25.md) | global_rest_capacity 변경 건 |
| [`plans/reconciliation_worker_architecture_2026-05-16.md`](../plans/reconciliation_worker_architecture_2026-05-16.md) | reconciliation worker 설계 |
| [`plans/cash_sync_failure_and_stale_snapshot_guardrail_diagnosis_2026-05-18.md`](../plans/cash_sync_failure_and_stale_snapshot_guardrail_diagnosis_2026-05-18.md) | cash sync 실패 진단 |
| [`plans/positions_amounts_intraday_resync_validation_2026-05-17.md`](../plans/positions_amounts_intraday_resync_validation_2026-05-17.md) | positions amounts resync |
| 다수의 일일 ops 보고서 (paper_daily_ops_report_*.md) | 운영 확인 |

---

## C. Canonical 값(1)과의 차이

### C.1. 코드 기본값 불일치

가장 중요한 발견: **`_resolve_kis_paper_rest_rps()`의 default가 `"10"`** 이지만, `AppSettings` 필드 주석과 test suite는 `1`을 기대한다.

| 위치 | 기대값(주석/테스트) | 실제 코드값 | 불일치 |
|------|---------------------|-------------|--------|
| [`settings.py:146`](../src/agent_trading/config/settings.py:146) | 1 (주석 line 329) | `"10"` (os.getenv default) | **🔴 심각** |
| [`rate_limit.py:501`](../src/agent_trading/brokers/rate_limit.py:501) | 1 (설계 baseline) | `paper_rest_rps: int = 10` | **🔴 심각** |
| [`test_settings.py:404`](../tests/services/ai_agents/test_settings.py:404) | `assert == 1` | resolver가 실제로 10 반환 | **🔴 테스트 깨짐 가능** |

### C.2. docker-compose service별 차이

| Service | 값 | Canonical(1) 대비 | 영향 |
|---------|-----|-------------------|------|
| app | 10 (기본) | **+9** | env override가 없으면 10배 여유 |
| api | 1 (기본) | 0 ✅ | canonical 유지 |
| snapshot-sync | 2 (hardcoded) | +1 | snapshot sync 전용 RPS 상향 |
| ops-scheduler | 2 (기본) | +1 | scheduler 전용 RPS 상향 |
| reconciliation-worker | 2 (기본) | +1 | reconciliation 전용 RPS 상향 |

### C.3. `.env` 파일

모든 `.env` 파일은 `KIS_PAPER_REST_RPS=1`로 설정되어 있어 canonical과 일치한다. 그러나 `app` service의 default가 10이므로, `.env`가 로드되지 않는 환경에서는 **RPS가 10으로 설정**된다.

---

## D. `global_rest_capacity` 계산 로직 분석

### D.1. 데이터 흐름

```
KIS_PAPER_REST_RPS env var
        │
        ▼
┌─────────────────────────────┐
│ _resolve_kis_paper_rest_rps() │  settings.py:141
│ os.getenv("KIS_PAPER_REST_RPS", "10") │
│ return max(1, int(raw))             │
└───────────┬─────────────────┘
            │
            ▼
┌─────────────────────────────┐
│ AppSettings.kis_paper_rest_rps │  settings.py:335
└───────────┬─────────────────┘
            │
            ├──────────────────────────────────────┐
            ▼                                      ▼
┌─────────────────────────┐    ┌──────────────────────────────┐
│ bootstrap.py:51        │    │ snapshot_factory.py:120      │
│ _build_kis_adapter()   │    │ _build_snapshot_components()│
│ build_kis_budget_manager│   │ build_kis_budget_manager()   │
│   paper_rest_rps=...   │    │   paper_rest_rps=...         │
└───────────┬─────────────┘    └──────────────┬───────────────┘
            │                                  │
            └──────────────┬───────────────────┘
                           ▼
┌──────────────────────────────────────────────┐
│ build_kis_budget_manager(env, paper_rest_rps) │  rate_limit.py:498
│                                               │
│ if env == "paper":                            │
│     total = max(1, paper_rest_rps)           │  ← line 574
│     global_rest_capacity = total              │  ← line 593
│     global_rest_refill_rate = 1.0 * total     │  ← line 594
│                                               │
│ if env == "live":                             │
│     total = max(1, real_rest_rps)            │
│     global_rest_capacity = total              │  ← line 624
│     global_rest_refill_rate = 1.0 * total     │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ RateLimitBudgetManager.__init__()            │
│   if global_rest_capacity > 0:               │  ← line 239
│       self.global_rest = OperationBucket(    │  ← line 240
│           capacity=global_rest_capacity,     │
│           refill_rate=global_rest_refill_rate)│
│   else:                                      │
│       self.global_rest = None (disabled)     │
└──────────────────────┬───────────────────────┘
                       ▼
              (운영 중 사용)
     ┌─────────────────────────────┐
     │ consume_or_raise()          │  rate_limit.py:302
     │  Tier 1: global_rest check  │  ← line 345-354
     │  Tier 2: per-bucket check   │  ← line 370-379
     └─────────────────────────────┘
```

### D.2. Paper 환경 bucket 상세

RPS=1 (total=1) 기준 paper 환경 budget:

| Bucket | Capacity | Refill rate | 계산식 |
|--------|----------|-------------|--------|
| **global_rest** (Tier 1) | **1** | **1.0/s** | `total` / `1.0 * total` |
| AUTH | 1 | 0.017/s | `max(1, total*1)` / `0.017 * total` |
| ORDER | 3 | 0.1/s | `max(3, total*3)` / `0.1 * total` |
| INQUIRY | 1 | 0.5/s | `max(1, total*1)` / `0.5 * total` |
| MARKET_DATA | 1 | 0.5/s | `max(1, total*1)` / `0.5 * total` |
| RECONCILIATION | 10 | 1.0/s | `max(1, 10*total)` / `1.0 * total` |

### D.3. 2-Tier Enforcement

`consume_or_raise()`는 다음 순서로 budget을 체크한다:

1. **Tier 1 — Global REST bucket**: `global_rest.try_consume(tokens)` — 실패 시 `BudgetExhaustedError(bucket="global")`
2. **Tier 2 — Per-operation bucket**: 해당 bucket에서 try_consume — 실패 시 `BudgetExhaustedError(bucket=해당타입)`

모든 REST API 호출은 두 단계를 모두 통과해야 한다.

### D.4. FileBackedGlobalBucket

[`rate_limit.py:598-605`](../src/agent_trading/brokers/rate_limit.py:598):  
paper 환경에서 `shared_budget_file` 파라미터가 제공되면 in-process `OperationBucket` 대신 파일 기반 `FileBackedGlobalBucket`을 사용한다. 이는 **프로세스 간 global REST cap 공유**를 가능하게 한다.

---

## E. RPS=1일 때의 예상 제약 분석

### E.1. 한 Cycle의 REST API 호출

하나의 decision→submit cycle에서 발생하는 REST API 호출:

| 단계 | API Endpoint | Bucket Type | Token 소비 |
|------|-------------|-------------|-----------|
| 1. quote_resolution | `inquire_psbl_order` | **INQUIRY** + **global** | 1 (global) |
| 2. submit_order | `order_cash` | **ORDER** + **global** | 1 (global) |
| 3. snapshot sync (후속) | `inquire_balance` + positions | **INQUIRY** × N + **global** × N | N (global) |

### E.2. budget 소모 시나리오 (RPS=1)

```
시간축 (초 단위)
0.0s:  [quote_resolution]  → global token = 0 (1 소모)
       INQUIRY bucket: 1→0, ORDER bucket: 3→3 (소모 없음)
       
~0.1s: [submit_order]      → global token = 0, BudgetExhaustedError!
       → global bucket이 1초 후에나 refill
       
1.0s:  global bucket refill → 1 token 추가 (1.0 refill_rate)
       
1.0s:  [submit_order] 재시도 성공 → global token = 0
       ORDER bucket: 3→2
       
2.0s:  global bucket refill → 1 token 추가
       
2.0s:  [snapshot sync: get_positions]  → global token = 0
       INQUIRY bucket: 0→- (이미 0)
       
3.0s:  global bucket refill → 1 token 추가
       INQUIRY bucket refill: 0.5/s → 1 token 추가 (2초 경과)
       
3.0s:  [snapshot sync: get_cash_balance] → global token = 0
       INQUIRY bucket: 1→0
```

### E.3. Budget Exhaustion 발생 조건

| 조건 | 설명 | 발생 확률 |
|------|------|-----------|
| **연속 REST 호출** | 1초 내 2회 이상 API 호출 | **항상 발생** (cycle당 최소 2회 호출) |
| quote + submit 동시 | global bucket=1로 둘 중 하나만 가능 | **항상** (❗️치명적) |
| quote_resolution 1회 후 INQUIRY 고갈 | INQUIRY capacity=1 → 추가 INQUIRY 불가 | 1회 후 고갈 |
| snapshot sync + decision 동기화 | 동시 실행 시 INQUIRY/global 경쟁 | 스케줄링에 따라 다름 |

### E.4. 하위 bucket 고갈 분석 (RPS=1)

#### INQUIRY bucket
- Capacity: 1, Refill: 0.5/s (2초에 1 token)
- `quote_resolution` 1회 호출 후 즉시 고갈
- 다음 INQUIRY 가능까지 약 **2초** 대기 필요
- snapshot sync의 `get_positions()` + `get_cash_balance()`는 각각 INQUIRY 1 token 소모

#### ORDER bucket
- Capacity: 3, Refill: 0.1/s (10초에 1 token)
- 연속 3회 submit 후 ORDER bucket 고갈
- 그 다음 submit은 10초 대기 후 가능

#### global_rest bucket (❗️주요 병목)
- Capacity: 1, Refill: 1.0/s
- **모든 REST API 호출이 1 token씩 소모**
- 1초에 1회만 가능
- cycle 내 quote_resolution(1) + submit(1)을 처리하려면 **2초** 필요

### E.5. Cycle 완료에 필요한 최소 시간

RPS=1일 때 하나의 decision→submit cycle의 최소 시간:

```
quote_resolution (1 global token 소모)
    │ 1초 대기 (global bucket refill)
    ▼
submit_order (1 global token 소모)
    │ 1초 대기 (global bucket refill)
    ▼
snapshot sync - get_positions (1 global + 1 INQUIRY token 소모)
    │ 1초 대기 (global bucket refill)
    ▼
snapshot sync - get_cash_balance (1 global + 1 INQUIRY token 소모)
    │ 1초 대기 (global bucket refill)
    ▼
(추가 INQUIRY 필요시) ...
```

**최소 3~4초** 소요 (INQUIRY bucket refill rate 0.5/s도 고려 시 더 소요 가능)

### E.6. RPS 조정 시 영향

| RPS | global_capacity | INQUIRY capacity | ORDER capacity | Cycle 완료 시간 |
|-----|----------------|-------------------|----------------|-----------------|
| 1 | 1 | 1 | 3 | ~3~4초 |
| 2 | 2 | 2 | 6 | ~1~2초 |
| 10 | 10 | 10 | 30 | ~0.1~0.5초 |

---

## F. 발견된 버그/불일치

### 🔴 F.1. `_resolve_kis_paper_rest_rps()` default 불일치 (심각)

[`settings.py:146`](../src/agent_trading/config/settings.py:146): `os.getenv("KIS_PAPER_REST_RPS", "10")`  
[`test_settings.py:404`](../tests/services/ai_agents/test_settings.py:404): `assert settings.kis_paper_rest_rps == 1`

resolver 함수의 os.getenv default가 `"10"`이지만, 테스트는 env unset 시 값이 `1`이라고 단언한다. `.env` 파일이 로드된 환경에서는 override되므로 눈에 띄지 않을 수 있으나, **`.env` 없이 실행하면 default=10이 적용**되어 테스트가 실패할 가능성이 높다.

**권장 수정**: resolver의 default를 `"1"`로 변경하거나, 테스트를 `== 10`으로 수정.

### 🟡 F.2. `build_kis_budget_manager()` 기본 파라미터 불일치

[`rate_limit.py:501`](../src/agent_trading/brokers/rate_limit.py:501): `paper_rest_rps: int = 10`  
docstring (line 533): `paper_rest_rps : int / Aggregate REST RPS baseline for the paper environment (default 1).`

코드 default는 `10`이나 docstring은 `default 1`이라고 명시. 불일치.

### 🟡 F.3. `docker-compose.yml` api service RPS 불일치

[`docker-compose.yml:138`](../docker-compose.yml:138): `KIS_PAPER_REST_RPS: "${KIS_PAPER_REST_RPS:-1}"`  
다른 service(app=10, ops-scheduler=2, snapshot-sync=2)와 값이 다름.

[`plans/verify_real_snapshot_based_order_sizing...md`](../plans/verify_real_snapshot_based_order_sizing_and_holiday_submit_reject_path_2026-05-25.md:264): api service RPS를 10으로 통일하자는 권고가 있음.

### 🟢 F.4. settings.py 주석 불일치 (경미)

[`settings.py:329`](../src/agent_trading/config/settings.py:329): `KIS_PAPER_REST_RPS (default 1)`  
resolver docstring (line 142): `default 10`

코드와 주석 사이에 minor 불일치.

---

## 부록: 검색 명령어 로그

```bash
# KIS_PAPER_REST_RPS 검색 (대소문자 무관)
grep -r -n -i "KIS_PAPER_REST_RPS" /workspace/agent_trading \
  --include='*.py' --include='*.yml' --include='*.yaml' \
  --include='*.md' --include='*.txt' --include='*.json'

# paper_rest_rps 검색
grep -r -n "paper_rest_rps" /workspace/agent_trading \
  --include='*.py' --include='*.yml' --include='*.yaml' \
  --include='*.md' --include='*.txt'

# global_rest_capacity 검색
grep -r -n "global_rest_capacity" /workspace/agent_trading \
  --include='*.py' --include='*.yml' --include='*.yaml' \
  --include='*.md' --include='*.txt'
```

---

*본 보고서는 2026-05-25 기준으로 작성되었으며, 모든 사용처를 전수 조사하였습니다.*
