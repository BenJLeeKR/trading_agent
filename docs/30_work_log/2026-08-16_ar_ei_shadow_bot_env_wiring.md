# AR/EI Shadow Bot Docker Compose Env Wiring 보강

## 문제

PR #278에서 `AR_SHADOW_BOT_ENABLED`/`EI_SHADOW_BOT_ENABLED`
설정(`src/agent_trading/config/settings.py`)과 shadow bot 계산/저장
로직(`services/shadow_bots.py`, `decision_orchestrator.py`)을 추가했다.
그러나 `docker-compose.yml`의 `ops-scheduler.environment`에 이 두 key가
**선언돼 있지 않으면**, `/etc/agent_trading/runtime.env`나
`local.override.env`에 값을 넣어도 실제 컨테이너 프로세스는 그 값을
전혀 받지 못한다.

이는 새로 생긴 문제가 아니라 이 저장소에서 반복적으로 발생해 온
패턴이다 — `ENTRY_SCORE_R3B_ALPHA_ENABLED`(§62/SPPV-2.73),
`EV_GATE_NEAR_MISS_OVERRIDE_ENABLED`(SPPV-2.87/2.88),
`LOSS_CUT_SHADOW_ENABLED`, `KIS_FILL_INCREMENTAL_APPEND_ENABLED` 모두
동일한 이유로 이미 `docker-compose.yml`의 `ops-scheduler.environment`
화이트리스트에 명시적으로 선언돼 있다. 이번 작업은 AR/EI shadow bot
env를 같은 화이트리스트에 추가해 동일한 배선 누락을 미리 막는 것이다.

## 변경 요약

- `docker-compose.yml`의 `ops-scheduler.environment`에 아래 두 줄을
  추가했다(`LOSS_CUT_SHADOW_*` 블록 바로 뒤):
  ```yaml
  AR_SHADOW_BOT_ENABLED: "${AR_SHADOW_BOT_ENABLED:-false}"
  EI_SHADOW_BOT_ENABLED: "${EI_SHADOW_BOT_ENABLED:-false}"
  ```
  주석에 (1) 이 화이트리스트에 없으면 `/etc/agent_trading/runtime.env`
  값이 전달되지 않는다는 것, (2) 관측 전용 스위치로 decision_type/주문/
  guard·override에 개입하지 않는다는 것, (3) 기본값 `false`는 기존
  운영 동작을 유지한다는 것을 명시했다.
- `.env.example`은 PR #278에서 이미 두 key와 충분한 설명이 추가돼
  있어 이번에는 수정하지 않았다(위치/설명 확인만 수행).
- `app.environment`/`api.environment`에는 추가하지 않았다(§서비스별
  판단 참고).

## 서비스별 추가/비추가 판단

| 서비스 | 결정 | 근거 |
|---|---|---|
| `ops-scheduler` | **추가** | `run_decision_loop.py`를 실행하는 유일한 서비스이며, `LOSS_CUT_SHADOW_ENABLED`/`EV_GATE_NEAR_MISS_OVERRIDE_ENABLED`/`ENTRY_SCORE_R3B_ALPHA_ENABLED` 등 동일 성격의 관측/실험 스위치가 모두 이미 여기에만 선언돼 있음 |
| `app` | **비추가** | `command: ["tail", "-f", "/dev/null"]`로 유지되는 수동 dev shell 컨테이너다. 확인 결과 `LOSS_CUT_SHADOW_ENABLED`를 포함한 기존 shadow/실험 스위치 중 어느 것도 `app.environment`에 선언돼 있지 않다 — 이 컨테이너에서 `AppSettings()`를 검증하는 기존 관례 자체가 없다. AR/EI만 예외적으로 추가하면 오히려 일관성이 깨지므로, 필요 시 `docker compose exec app env AR_SHADOW_BOT_ENABLED=true python3 -c "..."`처럼 exec 시점에 값을 주입해 검증하는 기존 대안을 그대로 쓴다 |
| `api` | **비추가** | `command`가 `uvicorn agent_trading.api.app:create_app_from_env --factory`로 Inspection API만 구동하며 decision loop를 실행하지 않는다. 기존 shadow/실험 스위치도 여기 없다 |
| `reconciliation-worker`/`realized-pnl-recompute-worker` | **비추가** | 각각 `run_reconciliation_worker.py`/`run_realized_pnl_recompute_worker.py`만 실행하며 decision loop와 무관하다 |

## compose/env 전달 경로

1. `scripts/harness/load_external_env.sh`(source 전용) — `/etc/agent_trading/{runtime.env,ai.env,kis.env}`(필수)와 `local.override.env`(선택)를 현재 쉘에 `set -a`로 auto-export하며 source한다. 파일이 없으면(dir 자체가 없으면) 조용히 스킵하고, 필수 파일이 없거나 읽을 수 없으면 에러로 중단한다. 로드된 파일 경로 목록을 `AGENT_TRADING_EXTERNAL_ENV_FILE_PATHS`(콜론 구분)에 담는다.
2. `scripts/harness/docker_compose_env.sh` — 위 스크립트를 source한 뒤, `AGENT_TRADING_EXTERNAL_ENV_FILE_PATHS`의 각 경로를 `docker compose --env-file <path> ...` 인자로 변환해 실제 `docker compose` 명령을 실행한다.
3. **핵심**: `--env-file`/쉘 export된 값은 `docker-compose.yml`의 `${VAR:-default}` **interpolation에만** 쓰인다. `docker-compose.yml`의 `environment:` 블록에 `VAR` 자체가 선언돼 있지 않으면, 아무리 `runtime.env`에 값이 있어도 컨테이너 프로세스의 실제 환경변수로는 절대 들어가지 않는다 — docker compose는 env-file의 모든 변수를 컨테이너에 자동으로 주입하지 않고, YAML에 명시된 키만 골라서 주입한다. 이번 작업 전 `AR_SHADOW_BOT_ENABLED`/`EI_SHADOW_BOT_ENABLED`가 정확히 이 상태였다.

## 중요 관측 사항 (운영 판단 필요)

read-only 확인(`bash scripts/harness/docker_compose_env.sh config` 결과를
해당 두 key만 grep, 다른 값은 출력하지 않음) 결과, **`/etc/agent_trading/
runtime.env`에 `AR_SHADOW_BOT_ENABLED`와 `EI_SHADOW_BOT_ENABLED`가 이미
`true`로 설정돼 있음을 확인했다.** 누가/언제 이 값을 넣었는지는 이번
턴에서 확인하지 못했다.

이는 이번 PR의 리스크 프로파일에 중요한 영향을 준다 — **이 PR이 머지된
뒤 ops-scheduler 컨테이너가 재생성되는 순간, shadow bot 관측이 즉시
켜진다.** "값을 설정하고 + 재생성한다"의 2단계가 아니라 **"재생성한다"
1단계만 남아 있다.** 컨테이너 재생성은 이번 세션에서 수행하지 않았고,
반드시 별도 승인을 받아야 한다.

## 실제 운영 동작 영향 여부

- **이 PR을 머지해도 즉시 운영 동작은 바뀌지 않는다** — 현재 실행 중인
  `ops-scheduler` 컨테이너는 이미 기동된 프로세스이므로, `docker-
  compose.yml` 파일 수정만으로는 실행 중인 프로세스의 환경변수가
  바뀌지 않는다. 다음 컨테이너 재생성(`docker compose up -d
  ops-scheduler` 등) 시점부터 반영된다.
- 단, 위 "중요 관측 사항"과 결합하면, **다음 재생성 시점에는 실제로
  shadow bot이 켜진다**(runtime.env에 이미 true가 있으므로). 이는
  "flag 기본값 false라 안전하다"는 일반론과 별개로, 이 특정 운영
  환경에서는 재생성이 곧 활성화를 의미한다는 점을 분리해서 보고해야
  한다.
- shadow bot 자체는 `decision_type`/주문 생성/수량/guard·override에
  개입하지 않으므로(PR #278에서 검증 완료), 켜지더라도 매매 판단
  로직에는 영향이 없다. 다만 매 결정 사이클마다 추가 계산과
  `decision_json` 쓰기가 한 번씩 더 발생한다.

## 실행한 검증 명령과 결과

| 명령 | 결과 |
|---|---|
| `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"` | 문법 오류 없음 |
| `grep -n "AR_SHADOW_BOT_ENABLED\|EI_SHADOW_BOT_ENABLED" docker-compose.yml` | 정확히 2줄, 중복 없음 |
| `bash scripts/harness/docker_compose_env.sh config \| grep -E "^      (AR_SHADOW_BOT_ENABLED\|EI_SHADOW_BOT_ENABLED):"` | 두 key 모두 compose interpolation에 정상 반영됨(현재 값 `true` — 위 "중요 관측 사항" 참고). secret 값은 출력하지 않음 |
| `bash scripts/harness/run.sh accept env` | PASS(`env_values=redacted`, `runtime_external_env_dir_status=ready`, secret 미노출) |
| `bash scripts/harness/run.sh accept docs` | PASS |
| `bash scripts/harness/run.sh accept ci` | PASS |

**명시**: 이번 턴에서 컨테이너를 재기동/재생성하지 않았다(`docker compose up`/`restart`/`run` 미실행). `.env`/`/etc/agent_trading/*.env` 파일을 직접 읽거나 수정하지 않았다(`docker_compose_env.sh`가 내부적으로 source하는 것은 하네스 스크립트의 기존 동작이며, 이번 턴에서 그 파일 내용을 직접 열람하거나 값을 출력하지 않았다 — 위 grep도 boolean 플래그 두 줄만 확인했다).

## 미검증 사항

- `/etc/agent_trading/runtime.env`에 `AR_SHADOW_BOT_ENABLED=true`/`EI_SHADOW_BOT_ENABLED=true`가 언제, 누구에 의해 설정됐는지는 확인하지 못했다.
- 실제 ops-scheduler 재생성 이후 shadow bot이 정상적으로 `decision_json.shadow_risk_bot`/`shadow_event_bot`을 적재하는지는 이번 턴에서 검증하지 않았다(컨테이너 재기동 금지 범위 밖 작업).
- `app` 컨테이너에서 `docker compose exec app env AR_SHADOW_BOT_ENABLED=true python3 -c "..."` 방식의 수동 검증이 실제로 동작하는지는 실행해보지 않았다(컨테이너 exec은 재기동이 아니지만 이번 턴 범위에서는 수행하지 않음).

## 운영 적용 절차 (참고, 이번 턴에서 수행하지 않음)

1. (이미 완료된 것으로 관측됨) `/etc/agent_trading/runtime.env`에 `AR_SHADOW_BOT_ENABLED=true`/`EI_SHADOW_BOT_ENABLED=true` 설정.
2. 이 PR 머지.
3. **사용자 명시 승인 하에** `ops-scheduler` 컨테이너 재생성(`docker compose up -d ops-scheduler` 등, `docker_compose_env.sh` 래퍼 경유).
4. 다음 거래일 이후 `trade_decisions.decision_json.shadow_risk_bot`/`shadow_event_bot` 적재 및 `opinion_agreement`/`bias_agreement` 등 분포 확인.

## 후속 작업

- 사용자에게 `/etc/agent_trading/runtime.env`의 기존 `true` 설정이 의도된 것인지 확인받는다.
- ops-scheduler 재생성 시점/승인 여부를 별도로 결정한다.
- 재생성 이후 배포 후 실측(PR #278 문서에 이미 정리된 항목)을 진행한다.
