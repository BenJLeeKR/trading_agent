# AC(ai_compliance) subprocess 직렬화 버그 수정

## 배경

PR #277/#281/#282(EI/AR/AC deterministic bot 전환) 완료 후 진행한
전체 경로 read-only 검토 턴에서, `scripts/run_agent_subprocess.py::
_write_output()`이 stdout JSON에 `compliance_output` 키를 쓰지 않는
것을 재확인했다. 이는 이번 3개 PR이 만든 문제가 아니라
`docs/20_system_analysis/ai_agent_vs_deterministic_bot_replacement_
analysis.md`(§4.1, 137행)에서 이미 근본 원인으로 지목된, 최초 커밋부터
있던 사전 존재 버그다(`git show 81f2a40f:scripts/run_agent_subprocess.py`
로 확인).

## 실제 영향 경로

운영 기본 경로는 subprocess 격리(`AGENT_SUBPROCESS_ISOLATION` 기본값
`"1"`)다. 이 경로에서:

1. `run_agent_subprocess.py`의 `main()`이 AC bot(`DeterministicAIComplianceAgent`)
   을 실제로 실행하고 `AgentSubprocessOutput(compliance_output=
   dataclass_to_dict(compliance_output))`까지는 올바르게 채운다.
2. 그런데 `_write_output()`이 stdout JSON으로 쓰는 키는
   `success/event_output/risk_output/composer_output/error/
   duration_seconds/ei_error_metadata`뿐이었다 — `compliance_output`
   키가 빠져 있었다.
3. 부모 프로세스의 `subprocess_helpers.py::deserialize_agent_output()`
   은 `data.get("compliance_output") or data.get("ac_output", {})`로
   읽는데 둘 다 없으므로 항상 `{}` → `AIComplianceOutput()`(전부
   default: `compliance_opinion="allow"`, `reason_codes=()`)로
   복원됐다.
4. 이 손상된 `compliance_output`이 `decision_orchestrator.py::
   _rehydrate_subprocess_agent_runs()`를 통해 `agent_runs.
   ai_compliance.structured_output_json`에, `deserialize_agent_output()`
   내부의 `AIDecisionInputs` 조립을 통해 `decision_json.compliance_*`
   /`compliance_check_passed`에 각각 잘못 반영됐다.

**FDC 프롬프트 입력은 영향받지 않는다** — subprocess **내부**에서
FDC에 전달되는 `compliance_output`은 JSON 왕복 이전의 실제 로컬
변수를 그대로 쓰기 때문이다. 손상은 부모 프로세스가 stdout JSON을
역직렬화하는 지점(저장/관측 경로)에서만 발생한다.

## 수정 내용

`scripts/run_agent_subprocess.py::_write_output()`의 JSON payload에
`"compliance_output": output.compliance_output` 키를 추가했다.
`subprocess_helpers.py::deserialize_agent_output()`은 이미 이 키를
올바르게 읽도록 작성돼 있었으므로(`data.get("compliance_output") or
data.get("ac_output", {})`) 수정이 필요 없었다.

이 수정은 **순수 직렬화 배관 수정**이다 — AC/AR/EI/FDC의 판단 로직,
`translation.py`/`execution_service.py`의 주문 gate, EV gate는 전혀
건드리지 않았다.

## wiring 변경

없음. `bootstrap.py`/`decision_orchestrator.py`/`decision_agent_runner.py`
는 미수정.

## policy 영향 여부

없음. AC/AR/EI/FDC의 판단 규칙 자체는 변경하지 않았다. 다만 이 수정이
재배포되면, subprocess 경로에서 `agent_runs`/`decision_json`에 기록되는
**AC의 관측값**이 지금까지의 "항상 allow 기본값"에서 "AC deterministic
bot의 실제 계산 결과"로 바뀐다 — 이는 관측/감사 데이터의 정확도 개선이며,
`compliance_check_passed`는 여전히 어떤 주문 gate에도 연결되지 않는다
(authoritative 차단은 이미 submit-time deterministic validator가 담당).

## 검증 명령과 결과

| 명령 | 결과 |
|---|---|
| `test-file tests/services/ai_agents/test_agent_subprocess.py` | 21 passed(신규 `TestWriteOutputIncludesComplianceOutput` 1건 포함) |
| `test-file tests/services/ai_agents/test_ai_compliance_deterministic.py` | 10 passed |
| `test-file tests/services/test_decision_orchestrator.py` | 81 passed |
| `accept backend-runtime` | PASS |
| `accept architecture` | PASS |
| `accept no-bypass` | PASS(hard_bypass_count=0) |
| `accept style` | PASS |
| `accept docs` | PASS |
| `accept script-file scripts/run_agent_subprocess.py`(선택) | FAIL — `tests/scripts/test_fdc_skip.py`가 `/workspace` read-only 인프라 이슈로 실패. PR #277/#281/#282와 동일한 사전 존재 인프라 이슈(무관) |

**회귀 테스트 설계**: `scripts.run_agent_subprocess`는 모듈 최상단에서
`_os.makedirs("/workspace/agent_trading/logs", exist_ok=True)`를
무조건 실행하므로, 이 harness의 dev-validation 컨테이너(`/workspace`
read-only)에서 이 모듈을 직접 import하거나 실제 subprocess로 스폰하는
어떤 테스트도 무관한 인프라 이유로 항상 실패한다
(`tests/scripts/test_fdc_skip.py`와 동일 원인). 따라서 새 회귀 테스트는
모듈을 import하지 않고 소스를 AST로 정적 파싱해 `_write_output()`의
dict literal에 `"compliance_output"` 키가 있는지 검증하는 방식으로
작성했다. `git stash`로 수정 전 코드에서 이 새 테스트가 실제로 실패함을
확인해(`AssertionError: ... 실제 키: {..., 'compliance_output' 없음}`)
진짜 회귀를 잡는 테스트임을 검증했다.

## 미검증 사항

- 실제 재배포 후 subprocess 경로를 통해 `agent_runs.ai_compliance.
  structured_output_json`에 `compliance_rule_set:deterministic_v1`
  마커가 실제로 기록되는지.
- `decision_json.compliance_opinion` 분포가 재배포 후 더 이상 100%
  `"allow"`로 고정되지 않는지.
- 이 수정이 `agent_runs`/`decision_json`에 반영하는 AC의 실제
  계산값이 이후 legacy LLM 제거(PR3) 판단에 어떤 근거를 추가로
  제공하는지.

## 배포 후 실측 항목

- `agent_runs.ai_compliance.structured_output_json`에서
  `compliance_rule_set:*` 마커 존재 여부와 비율.
- `decision_json.compliance_opinion`/`compliance_score`/
  `compliance_policy_flags` 분포가 실제 AC bot 계산값을 반영하는지
  (AR risk_opinion="reject"/"reduce" 케이스와의 상관관계 포함).
- `compliance_check_passed`가 여전히 어떤 gate에도 연결되지 않은
  채로 유지되는지(정책 변경 없음 재확인).
