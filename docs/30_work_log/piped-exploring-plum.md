# scripts/harness/run.sh 적정성 검증 보고 및 수정 승인 프롬프트

## Context

`CLAUDE.md`와 `AGENTS.md` 계열 파일은 이 저장소를 "실행 가능한 검증 하네스"로 규정하고, 7개의 정답 판정 진입점(`accept docs/env/backend-file/backend-runtime/frontend/ops-report`, `env-check`)을 `scripts/harness/run.sh`에 위임한다. 최근 3개 커밋(`bd4f57a3`, `c258f4bd`, `93d8c2da`)에서 이 스크립트가 291줄 → 1470줄로 확장됐다.

이 문서는 (1) run.sh가 그 규칙에 맞게 만들어졌는지에 대한 실측 검증 결과와, (2) `AGENTS.md` §프롬프트 및 계획 리뷰 규칙에 따른 재사용 가능한 수정 승인 프롬프트다. **코드는 변경하지 않는다.**

검증 방식: 규칙 파일 전문 대조 + run.sh 전문 리뷰 + 실제 실행(`accept docs`, `accept ops-report` 6종 페이로드, `accept backend-file` 6개 파일, `lint-path`, `make lint`). Docker 컨테이너를 새로 띄우는 `accept env` / `accept backend-runtime` / `accept frontend`는 `AGENTS.md:76` 부하 제한 때문에 실행하지 않고 정적 리뷰만 했다.

---

## 1. 검증 결론

**골격은 규칙에 잘 부합한다. 다만 가장 자주 쓰일 단일 게이트인 `accept backend-file`이 트레이딩 안전 핵심 모듈에서 거짓 PASS를 내고, `make lint`는 아예 동작하지 않는다.** "정답 판정"이라는 지위에 비해 이 두 건은 치명적이다.

### 1.1 규칙에 잘 부합하는 부분 (유지)

| 항목 | 확인 내용 |
| --- | --- |
| 진입점 배선 | `AGENTS.md:44-50`, `CLAUDE.md:38-43`이 선언한 7개 진입점이 모두 `main()` case에 존재하고 Makefile 타깃과 1:1로 연결됨. `accept docs` 실행 → PASS, exit 0 확인 |
| 부하 제한의 코드 강제 | `require_heavy_allowed()`가 `HARNESS_ALLOW_HEAVY=1`을 요구하고, `require_safe_test_selector()`가 `tests/smoke|integration|brokers`를 차단. `make test`조차 차단됨. `AGENTS.md:66-73` 금지 목록이 문서가 아니라 실행 가능한 게이트가 된 점이 이 프로젝트의 핵심 취지에 정확히 부합 |
| 지표 기반 판정 | 모든 accept가 exit 0이 아니라 `*_count=0` 카운터 집합으로 판정하고 `DETAIL` 섹션을 출력 → `AGENTS.md:21`, `AGENTS.md:100` 충족 |
| 비밀 보호 | `accept env`는 `env_values=redacted` + `git ls-files .env` 추적 검사, `accept ops-report`는 재귀 secret key 스캔, `backend-runtime` probe는 `KIS_*` 제거 후 `API_RUNTIME_MODE=in_memory` 강제 → `AGENTS.md:24` 충족 |
| ops-report 스키마 정확성 | `accept ops-report`가 요구하는 키가 실제 생산자 `scripts/run_ops_scheduler.py`의 `_build_operations_day_summary_json()`(L1334~) 및 `_parse_decision_loop_summary()`와 정확히 일치. API 응답의 `operations_day_summary_json` wrapper 언랩까지 반영. 커버리지 정합성(`processed<=universe`, held-position) 검사 포함 |
| 인자 주입 방어 | `resolve_in_repo()`가 `-`로 시작하는 인자와 repo 밖 경로를 거부 |

### 1.2 실질 결함

#### P1. `accept backend-file`의 테스트 탐색이 파일명 stem 기반이라 거짓 PASS를 낸다 — 최우선

`accept_backend_file()`의 후보 탐색(run.sh L595-618)은 `tests/**/test_<stem>.py` / `tests/**/<stem>_test.py`를 **파일명만으로** 매칭한다. 모듈 경로도, import 관계도 보지 않는다.

**(a) 안전 핵심 모듈이 테스트 0건으로 PASS** — 실측:

```
accept backend-file src/agent_trading/services/submit_lane_gate.py
  → ACCEPT backend-file: PASS  (exit 0)
     safe_test_candidate_count=0 / tests_run_count=0
     ADVISORY no_safe_test_candidate_found=1

accept backend-file src/agent_trading/services/order_manager.py
  → 동일하게 PASS, tests_run_count=0
```

즉 `AGENTS.md:90`이 이름을 지목해 보호하는 submit-lane gate와, 주문 제출 경로의 중심인 order_manager가 **py_compile만 통과하면 "정답"** 이 된다. 실제 커버리지는 존재한다 — `tests/scripts/test_run_decision_loop.py`가 `agent_trading.services.submit_lane_gate`를, `tests/services/test_order_idempotency.py`·`test_order_state_transition.py`·`test_order_state_event_integration.py`·`test_unknown_state_reconciliation_boundary.py`·`test_decision_orchestrator.py`가 `agent_trading.services.order_manager`를 import한다. 탐색 방식이 못 찾을 뿐이다.

**(b) 무관한 테스트를 실행하고 PASS 처리** — 실측:

```
accept backend-file src/agent_trading/repositories/base.py
  → PASS, tests_run_count=1
     실행된 테스트: tests/services/ai_agents/test_base.py
     (이 파일은 agent_trading.services.ai_agents.base만 import — repositories/base.py와 무관)

accept backend-file src/agent_trading/api/schemas.py
  → PASS, tests_run_count=1
     실행된 테스트: tests/services/ai_agents/test_schemas.py
     (실제로 api.schemas를 쓰는 tests/api/test_inspection.py,
      tests/scripts/test_run_ops_scheduler.py는 미실행)
```

`tests_run_count=1, test_failed_count=0`이라는 지표가 거짓 근거가 된다. `AGENTS.md:74`("변경 파일에 직접 대응하는 가장 좁은 테스트")와 `AGENTS.md:21`("exit code 0만으로 성공을 판단하지 않는다")의 취지를 형식만 충족하고 실질은 배반한다.

**(c) 부수 결함**: 광역 glob + `max_safe_test_files=3` 하드 캡(L620) 조합은 stem이 흔한 모듈에서 `too_many_safe_test_candidates` 오탐을 낼 수 있다. 현재 트리에서는 실측상 해당 파일이 0건이라 잠복 상태다.

**대안 검증 완료**: import 그래프 기반 탐색(`grep -rl 'agent_trading\.<dotted.module>' tests/`)은 위 4개 모듈 모두에서 올바른 테스트를 찾아낸다. `repositories/base.py`는 import하는 테스트가 실제로 0건이므로 정확히 "무테스트"로 분류된다.

#### P2. `make lint` / `lint-path`가 동작하지 않는다

실측:

```
make lint            → No module named ruff, exit 2
lint-path <file>     → No module named ruff, exit 1
```

호스트와 `agent_trading-app-1` 컨테이너 모두 ruff가 없고, `requirements.lock`·`pyproject.toml` 어디에도 핀이 없다(`.gitignore`에 `.ruff_cache/`만 남아 있음). 그런데 `AGENTS.md:55`와 `README.md:247,257`은 이 경로를 공식 스타일 검증 수단으로 선언한다. `AGENTS.md:22`("런타임 코드 ... 문서 내용이 서로 어긋나지 않게 유지한다") 위반이며, "환경 재현성 정답 판정"을 자처하는 `accept env` / `accept backend-runtime`이 이 결손을 잡지 못한다는 점이 더 문제다.

#### P3. `accept ops-report`의 판정 공백

- **실패 카운트를 통과시킨다** — 실측: `failed_count=6`, `timed_out_count=5`인 페이로드가 `decision_loop.last_ok=true`이기만 하면 PASS. `AGENTS.md:91`("실패한 작업을 조용히 성공으로 변환하지 않는다") 취지와 어긋난다.
- **secret 스캔이 key 이름만 본다** — 실측: `"note": "appkey=PSxxxxLIVEKEY1234"`가 PASS. 값 패턴 스캔이 없다.
- **경로 오류 메시지가 오해를 부른다** — 실측: 존재하지 않는 경로나 repo 밖 경로를 주면 `json_parse_error ... source=<inline-json> line=1 column=1`이 나온다. `resolve_input()`(L1156-1162)이 파일 해석 실패를 조용히 inline JSON으로 강등하기 때문이다.
- **휴장일 무조건 FAIL** — `command_health.decision_loop`가 필수 경로인데, `_command_family_stats()`는 해당 커맨드가 없으면 `None`을 반환하고 상위에서 키가 제거된다. decision loop가 돌지 않은 날의 정상 스케줄러 런은 구조적으로 FAIL한다.
- **게이트에 도달할 경로가 없다** — summary_json은 `trading.operations_day_runs.summary_json`(DB)과 Inspection API에만 존재하고 파일 산출물이 없다. 이를 꺼내오는 하네스 명령이 없어서, 이 정답 판정을 쓰려면 승인 없이 DB/API를 직접 조회해야 한다(`AGENTS.md:76`과 충돌).

#### P4. 부하 게이트 정책과 문서 문구의 불일치 — 문서 쪽을 고치는 게 맞다

- `accept env` / `accept backend-runtime` / `accept frontend`, 그리고 `run_python_with_timeout()`을 타는 `py-compile`·`test-one`·`test-file`·`lint-path`는 컨테이너가 떠 있으면 `docker exec`을, node 검증에서는 `docker run --rm node:20-slim`을 **무조건** 사용한다. `AGENTS.md:76`·`src/AGENTS.md:41`의 "Docker를 사용하는 검증은 사용자 승인 없이 실행하지 않는다"와 문자 그대로 충돌한다.
- `admin-test-one`은 `npm run test:run -- '<selector>'`를 게이트 없이 실행하는데, `admin_ui/AGENTS.md:35`는 `npm run test:run`을 무조건 금지 목록에 올려두었다.

두 경우 모두 실제 의도(무거운 신규 컨테이너/전체 스위트 vs. 이미 떠 있는 컨테이너 exec·단일 파일 테스트)는 합리적이다. run.sh가 아니라 규칙 문구에 예외를 명시하는 편이 옳다.

#### P5. 구조·유지보수 부채

- 1470줄 단일 파일에 `ROOT_DIR="/workspace/agent_trading"`이 8곳 하드코딩(bash 1 + Python heredoc 7).
- docker 감지 / `run_command` / `python_command` 로직이 4~5회 중복되고 시그니처도 다름(`accept_backend_file`은 list 반환, `accept_backend_runtime`은 `(command, source)` tuple).
- `docs-check`가 `accept docs`의 부분집합인데 검사 파일 목록이 다르다(`tests/fixtures/README.md` 누락) → 두 판정이 갈릴 수 있다.
- `env_check()`(bash)와 `accept_env()`(python)가 같은 버전 검사를 이중 구현.
- timeout 비일관: `accept_env`(L333)·`accept_frontend`(L976)는 30초 하드코딩이라 `HARNESS_SAFE_TIMEOUT_SECONDS`를 무시.
- `py-compile`·`lint-path`는 검증을 마친 resolved 경로가 아니라 원본 인자를 그대로 실행에 넘긴다.
- Makefile: `smoke-all`은 항상 `exit 1`이고 대응 서브커맨드도 `HARNESS_ALLOW_HEAVY` 우회로도 없다(다른 heavy 명령과 패턴 불일치). `.PHONY` 목록에 누락된 타깃 다수. `check-file`→`py-compile`, `accept-admin-ui`→`accept frontend` 이름 불일치.
- `scripts/harness/`에 `run.sh` 단 하나. 공용 라이브러리도 README도 없다.
- `accept docs`가 항상 `full_test_run=0` 류의 상수를 출력하는 것처럼, 몇몇 지표는 조건과 무관한 고정값이라 실제 증거로서의 값이 없다.

#### P6. 문서 정합성 자체의 미검출

- `README.md:64-69`가 퀵스타트에서 `make test`(현재 차단됨)를 안내하고 "예상 결과: 53 passed"를 명시한다. 실제 테스트 파일은 206개다. `accept docs`는 링크·필수 파일·고정 문자열만 보므로 이 드리프트를 못 잡는다.
- `pytest.ini`(`function`)와 `pyproject.toml`(`module`)의 `asyncio_default_fixture_loop_scope`가 충돌한다. "환경 재현성" 판정 범위 밖이다.

---

## 2. 수정 승인 프롬프트

> 아래 블록을 그대로 실행 에이전트에 전달하면 된다.

```
scripts/harness/run.sh의 검증 결과 확인된 결함을 수정한다. 우선순위 순서대로 작업하고,
각 단계마다 해당 진입점을 실제로 실행해 판정 변화를 지표로 증명한다.

### 1순위 — accept backend-file의 테스트 탐색을 import 그래프 기반으로 교체

- src 대상 파일의 dotted module 경로(예: agent_trading.services.submit_lane_gate)를 계산하고,
  tests/ 이하에서 그 모듈을 import하는 테스트 파일을 후보로 삼는다.
  파일명 stem 매칭은 후보가 0건일 때의 fallback으로만 남긴다.
- tests/smoke, tests/integration, tests/brokers 제외 규칙은 그대로 유지한다.
- 후보가 0건이면 ADVISORY가 아니라 FAIL로 판정한다.
  명시 우회는 HARNESS_ALLOW_NO_TEST=1 환경변수로만 허용하고, 우회 시 출력에
  no_test_override=1을 남긴다.
- 지표에 test_discovery_mode=(import_graph|stem_fallback)와
  matched_by_import_count를 추가해, 어떤 근거로 테스트가 선택됐는지 출력에서 보이게 한다.
- max_safe_test_files 캡(기본 3)은 유지하되, 초과 시 즉시 FAIL이 아니라
  import 그래프 매칭 강도 순으로 상위 N개를 실행하고 dropped_test_candidate_count를
  명시 출력한다. 조용한 절삭은 금지한다.

검증(반드시 실행하고 결과를 보고):
  bash scripts/harness/run.sh accept backend-file src/agent_trading/services/submit_lane_gate.py
    → 수정 전 PASS(tests_run_count=0) → 수정 후 tests/scripts/test_run_decision_loop.py 실행
  bash scripts/harness/run.sh accept backend-file src/agent_trading/services/order_manager.py
    → tests/services/test_order_idempotency.py 등이 후보에 포함되는지
  bash scripts/harness/run.sh accept backend-file src/agent_trading/repositories/base.py
    → 수정 전 tests/services/ai_agents/test_base.py 오매칭 PASS → 수정 후 FAIL(무테스트)
  bash scripts/harness/run.sh accept backend-file src/agent_trading/api/schemas.py
    → tests/api/test_inspection.py 계열로 교체되는지

### 2순위 — make lint / lint-path 복구

- ruff를 requirements.lock과 pyproject.toml의 dev/test extra에 버전 고정으로 추가한다.
- ruff 설정 섹션이 없으므로 최소 규칙 세트를 pyproject.toml에 명시한다.
  기존 코드에 대량 위반이 나오지 않는 보수적 기본값으로 시작한다.
- accept env와 accept backend-runtime의 static_checks에
  "lint 도구가 lock에 고정되어 있고 실행 가능한가" 항목을 추가한다.
  문서가 선언한 검증 수단이 실제로 동작하지 않는 상태를 하네스가 잡아내야 한다.
- ruff를 도입하지 않기로 결정한다면, 그 경우에는 AGENTS.md:55와 README.md:247,257에서
  ruff 경로를 제거하고 lint-path/make lint 타깃도 함께 삭제한다.
  둘 중 하나를 반드시 선택하고, 문서와 런타임이 어긋난 상태로 두지 않는다.

검증: make lint 실행 결과(exit code와 위반 건수)를 그대로 보고한다.

### 3순위 — accept ops-report 판정 보강

- resolve_input()이 파일 경로 해석에 실패하면 inline JSON으로 강등하지 말고
  input_resolution_error로 구분해 FAIL시킨다. 인자가 { 또는 [로 시작할 때만 inline으로 본다.
- failed_count와 timed_out_count를 판정에 포함한다. 기본은 failed_count>0이면 FAIL로 하되,
  운영상 허용 범위가 있다면 HARNESS_OPS_ALLOWED_FAILED_COUNT로 임계를 노출한다.
  어떤 커맨드가 실패했는지는 DETAIL로 반드시 나열한다.
- secret 스캔에 값 패턴 검사를 추가한다(appkey=, Bearer , PS로 시작하는 장문 토큰 등).
  현재는 키 이름만 검사해 값에 박힌 자격증명을 통과시킨다.
- decision loop가 실행되지 않은 세션(휴장일 등)을 구조적 FAIL로 만들지 않는다.
  session_reason이나 command_results의 구성으로 분기하고,
  분기 결과를 session_profile= 지표로 출력한다.
- summary_json 조회 진입점을 추가한다.
  bash scripts/harness/run.sh dump ops-report [YYYY-MM-DD] 형태로
  Inspection API 또는 DB에서 해당 일자 summary_json을 파일로 떨군 뒤
  accept ops-report에 넘길 수 있게 한다.
  이 명령은 DB/API를 건드리므로 HARNESS_ALLOW_HEAVY 또는 별도 승인 플래그 뒤에 둔다.
- 조건과 무관하게 고정 출력되는 full_test_run=0, external_network_run=0 류는
  실제 실행 여부를 반영하도록 바꾸거나 제거한다. 고정 상수는 증거가 아니다.

### 4순위 — 부하 제한 규칙 문구 정합화 (run.sh가 아니라 문서를 고친다)

- AGENTS.md 검증 부하 제한 절에 예외를 명시한다.
  "이미 기동 중인 컨테이너에 대한 docker exec 기반 단일 파일 검증과, 하네스가 제공하는
   accept 진입점은 승인 없이 실행할 수 있다. 새 컨테이너 기동, 전체 스위트, 외부 API
   호출은 계속 승인 대상이다."
- admin_ui/AGENTS.md:35의 npm run test:run 금지 문구에
  "단일 selector를 지정한 run.sh admin-test-one은 예외"를 명시한다.
- src/AGENTS.md:41도 같은 기준으로 맞춘다.

### 5순위 — 구조 정리

- ROOT_DIR을 스크립트 위치에서 1회 산출하고(예:
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)")
  Python heredoc에는 환경변수로 전달한다. 하드코딩 8곳을 제거한다.
- docker 감지와 subprocess 실행 로직을 scripts/harness/lib.py 하나로 모으고
  각 accept 함수가 이를 import하게 한다. 시그니처를 하나로 통일한다.
- docs-check를 제거하고 accept docs로 일원화하거나,
  최소한 검사 파일 목록을 공유해 두 판정이 갈리지 않게 한다.
- env_check(bash)와 accept_env(python)의 버전 검사 로직을 하나로 합친다.
- accept_env와 accept_frontend의 하드코딩 30초 timeout을
  HARNESS_SAFE_TIMEOUT_SECONDS에 연결한다.
- py-compile과 lint-path가 resolved 경로를 실행에 사용하도록 고친다.
- Makefile: smoke-all을 제거하거나 다른 heavy 명령과 같은
  HARNESS_ALLOW_HEAVY 패턴으로 통일하고, .PHONY 목록에 누락된 타깃을 채운다.
- scripts/harness/README.md를 추가해 각 진입점의 판정 기준과 지표 의미를 정리한다.

### 6순위 — 문서 정합성

- README.md 퀵스타트 5절의 make test 안내와 "53 passed" 기대값을 현재 상태에 맞게 고친다.
  차단된 명령을 퀵스타트로 안내하지 않는다.
- pytest.ini와 pyproject.toml의 asyncio_default_fixture_loop_scope 충돌을 해소하고,
  설정 소스를 하나로 정한다.
- accept docs에 "문서가 안내하는 make 타깃이 실제로 존재하고 차단 여부가 문서와 일치하는가"
  검사를 추가하는 것을 검토한다. 지금은 링크와 고정 문자열만 본다.
```

### 추가 보정사항

- 1순위 수정은 **기존에 PASS하던 파일 일부를 FAIL로 바꾼다**. 이는 의도된 결과다. FAIL로 전환되는 파일 목록을 수정 직후 한 번 산출해 보고하고, 각각에 대해 (a) 테스트를 추가할지 (b) `HARNESS_ALLOW_NO_TEST=1`로 명시 우회할지를 사용자가 판단할 수 있게 한다. 우회를 기본값으로 만들지 않는다.
- 새로 추가하는 게이트가 기존 판정을 완화하는 방향이면 안 된다. 판정은 좁고 엄격해지는 방향으로만 바꾼다.
- `dump ops-report`처럼 DB/API를 건드리는 신규 명령은 반드시 승인 플래그 뒤에 두고, 기본 경로를 오염시키지 않는다.
- 3순위의 secret 값 패턴 검사는 오탐이 나면 운영 리포트 전체가 막히므로, 도입 시 실제 운영 summary_json 최소 1건으로 오탐 여부를 확인한 뒤 확정한다.
- 4순위는 코드가 아니라 규칙 문구 변경이다. 규칙을 느슨하게 만드는 방향이므로 문구를 임의로 넓히지 말고, 위에 제시한 범위(기동 중 컨테이너 exec / 단일 selector)로만 한정한다.

### 그 외 유지해야할 원칙

- `require_heavy_allowed()` 게이트와 `require_safe_test_selector()`의 `tests/smoke|integration|brokers` 차단은 그대로 둔다. 이 하네스에서 가장 잘 만들어진 부분이다.
- 모든 accept 진입점의 "카운터 지표 + DETAIL 나열 + exit code" 출력 형식을 유지한다. 새 검사를 추가할 때도 같은 형식을 따른다.
- 비밀 취급 원칙을 유지한다. `env_values=redacted`, `git ls-files .env` 검사, probe의 `KIS_*` 제거, `API_RUNTIME_MODE=in_memory` 강제는 건드리지 않는다.
- `resolve_in_repo()`의 `-` 접두 인자 거부와 repo 밖 경로 거부는 유지한다.
- `accept ops-report`의 스키마 키는 `scripts/run_ops_scheduler.py`의 `_build_operations_day_summary_json()`이 정답이다. 하네스 쪽 키를 임의로 바꾸지 말고, 생산자가 바뀌면 그쪽에 맞춘다.
- `AGENTS.md` 언어 원칙에 따라 주석·출력 메시지·보고는 한국어로 작성한다. 지표 키 이름은 영문 snake_case를 유지한다.
- 이번 작업 범위 밖의 리팩터링을 끼워 넣지 않는다. 특히 `src/` 런타임 코드의 매매 의미론은 건드리지 않는다.

### 완료 후 보고에 대한 가이드

보고에는 다음을 포함한다.

1. 변경한 파일 목록.
2. 우선순위별로 실행한 검증 명령과 **출력 지표 원문**. 특히 1순위는 `submit_lane_gate.py`, `order_manager.py`, `repositories/base.py`, `api/schemas.py` 4개 파일의 수정 전/후 판정과 `tests_run_count`, `test_discovery_mode`를 나란히 제시한다.
3. `make lint`의 exit code와 위반 건수. ruff를 도입하지 않기로 했다면 그 결정과 문서에서 제거한 위치.
4. 1순위 수정으로 **PASS → FAIL로 전환된 src 파일의 전체 목록**과, 각각에 대한 권고(테스트 추가 / 명시 우회).
5. 검증하지 못한 가정. 특히 Docker 컨테이너를 새로 띄우는 `accept env` / `accept backend-runtime` / `accept frontend`를 실행했는지 여부와, 실행하지 않았다면 그 이유.
6. "OK"나 "정상 동작 확인" 같은 표현 대신 실제 카운트로 서술한다.
```

---

## 3. 이번 작업에서 변경할 파일

없음. 이 문서가 산출물이다. 위 승인 프롬프트를 실행할지 여부는 사용자가 결정한다.

## 4. 검증 방법 (이 보고의 재현)

```bash
bash scripts/harness/run.sh accept docs
bash scripts/harness/run.sh accept backend-file src/agent_trading/services/submit_lane_gate.py
bash scripts/harness/run.sh accept backend-file src/agent_trading/repositories/base.py
make lint
```

`accept ops-report`의 실패 카운트 통과와 secret 값 미검출은 인라인 JSON 페이로드로 재현할 수 있다(본문 §1.2 P3 참조).
