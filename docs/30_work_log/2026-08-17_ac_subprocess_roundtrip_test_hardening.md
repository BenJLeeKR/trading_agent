# AC subprocess 출력 round-trip 검증 보강

## 왜 AST 테스트만으로 부족했는가

PR #283은 `scripts/run_agent_subprocess.py::_write_output()`의 stdout
JSON payload에 `compliance_output` 키를 추가해, subprocess 경로에서
AC deterministic bot의 실제 계산 결과가 부모 프로세스로 전달되지 않던
버그를 수정했다. 하지만 그 PR의 회귀 테스트(`TestWriteOutputIncludes
ComplianceOutput`)는 모듈 소스를 AST로 정적 파싱해 "`_write_output()`
의 dict literal에 `compliance_output` 키가 있다"만 확인했다 — 실제로
그 값이 JSON으로 직렬화되고, 부모 프로세스의 `deserialize_agent_
output()`을 거쳐 `AgentExecutionBundle.compliance_output`과
`AIDecisionInputs.compliance_*`까지 온전히 보존되는지는 증명하지
못했다. AST 검사는 "키가 존재한다"만 볼 뿐, 값의 왕복 자체를
실행하지 않기 때문이다.

이 정적 검사가 필요했던 이유는 `scripts/run_agent_subprocess.py`가
모듈 최상단에서 `_os.makedirs("/workspace/agent_trading/logs",
exist_ok=True)`를 무조건 실행해, 이 harness의 dev-validation
컨테이너(`/workspace` read-only)에서 이 모듈을 직접 import하면 항상
`OSError`로 실패하기 때문이었다(`tests/scripts/test_fdc_skip.py`와
동일 이슈). 이번 PR의 목표는 이 제약을 우회하면서도 실제 값 왕복까지
검증하는 것이다.

## helper 분리 방식

`_write_output()`의 payload 생성/직렬화 로직을 신규 모듈
`src/agent_trading/services/ai_agents/subprocess_io.py`로 분리했다.

- `build_agent_subprocess_output_payload(output) -> dict`: JSON payload
  dict를 만든다. 어떤 키를 포함하는지에 대한 단일 진실 공급원(single
  source of truth)이다.
- `write_agent_subprocess_output(output, stream)`: 위 payload를
  `stream`에 JSON으로 쓰고 flush한다. 기존 `_write_output()`과 동일한
  직렬화 옵션(`default=str`, `ensure_ascii=False`)을 유지한다.
- `output` 파라미터는 `AgentSubprocessOutputLike`(`Protocol`)로
  구조적 타이핑돼 있다 — `scripts.run_agent_subprocess.
  AgentSubprocessOutput`을 이 모듈이 직접 import하지 않으므로, 이
  모듈 자체는 **import-time 부작용이 전혀 없다**(파일시스템 접근,
  env 접근, subprocess 실행 없음). 덕분에 테스트가 이 모듈을 직접
  import해서 실제 함수를 호출할 수 있다.

`scripts/run_agent_subprocess.py::_write_output()`은 이제
`write_agent_subprocess_output(output, sys.stdout)`을 호출하는 얇은
wrapper다. `_DIAG_LOG_DIR` 생성 위치나 운영 스크립트 초기화 의미는
전혀 바꾸지 않았다.

## round-trip 테스트가 검증하는 경로

```text
AgentSubprocessOutput(compliance_output 포함) 형태의 duck-typed 객체
-> write_agent_subprocess_output() -> StringIO -> JSON 문자열
-> deserialize_agent_output()
-> AgentExecutionBundle.compliance_output / ai_inputs.compliance_* 보존 확인
```

`tests/services/ai_agents/test_agent_subprocess.py`에
`TestWriteAgentSubprocessOutputRoundTrip` 클래스로 3건 추가:

1. `test_round_trip_preserves_compliance_output_default_marker` —
   기존 `sample_compliance_output` fixture(`compliance_opinion="warn"`)
   로 최소 왕복 확인 + payload 자체에 `compliance_output` 키가 있는지
   직접 확인(회귀의 정확한 지점).
2. `test_round_trip_preserves_all_compliance_fields_and_ai_inputs` —
   default와 뚜렷이 구분되는 값(`compliance_opinion="review"`,
   `compliance_score=0.7`, `confidence=1.0`, `reason_codes=(
   "compliance_rule_set:deterministic_v1", "risk_reject_review")`,
   `policy_flags=("eligibility_xxx",)`, `decision_context_id`,
   `symbol="005930"`)으로 다음 13개 필드를 전부 assert:
   - `bundle.compliance_output.compliance_opinion/compliance_score/
     confidence/reason_codes/policy_flags/decision_context_id/symbol`
   - `bundle.ai_inputs.compliance_opinion/compliance_score/
     compliance_confidence/compliance_reason_codes/
     compliance_policy_flags/compliance_check_passed`
3. `test_allow_and_warn_opinions_pass_compliance_check` —
   `compliance_check_passed`가 allow/warn=True, review/reject=False로
   정확히 나뉘는지 4개 opinion 전부 확인.

이 3건 모두 `write_agent_subprocess_output()`을 실제로 호출하고 그
출력을 `deserialize_agent_output()`(실제 함수, mock 아님)에 넣어
검증한다 — subprocess를 스폰하지 않고도 payload 생성부터 부모 측
역직렬화까지 실제 경로를 통과시킨다.

## 제거한 AST 테스트

PR #283의 `TestWriteOutputIncludesComplianceOutput`(AST 정적 파싱)은
제거했다. 위 round-trip 테스트가 실제 값 보존까지 증명하는 더 강한
검증이라 중복이었기 때문이다 — AST 테스트는 소스 코드에 키 리터럴이
있는지만 볼 뿐 값이 실제로 전달되는지는 보지 못했다. 게다가 `_write_
output()`이 이제 dict literal을 직접 갖지 않고 helper를 호출하는
wrapper가 되어, 기존 AST 테스트는 이 리팩터링 후 그대로 두면 "dict
literal을 찾지 못해 실패"하는 형태로 깨지게 되므로 유지할 이유가
없었다.

**검증**: `src/agent_trading/services/ai_agents/subprocess_io.py`의
`compliance_output` 키를 임시로 제거한 뒤 harness로 재실행해, 새
round-trip 테스트 3건이 모두 실제로 실패함을 확인했다(회귀를 정확히
잡아냄). 이후 키를 원위치로 복구해 23건 전체 재통과를 확인했다.

## 수정하지 않은 경로

- `AC`/`AR`/`EI`/`FDC`의 판단 로직(정책 의미) — 미변경.
- `translation.py`/`execution_service.py` 주문 gate — 미변경.
- EV gate — 미변경.
- DB schema/migration — 미변경.
- `scripts/run_agent_subprocess.py`의 `_DIAG_LOG_DIR` 생성 위치/운영
  스크립트 초기화 의미 — 미변경(이번 PR 범위 밖으로 명시적으로 제외).
- `_write_error_output()` — 미변경(이번 범위에서 다루지 않음).

## 실행한 검증 명령과 결과

| 명령 | 결과 |
|---|---|
| `test-file tests/services/ai_agents/test_agent_subprocess.py` | 23 passed(신규 round-trip 3건 포함) |
| `test-file tests/services/ai_agents/test_ai_compliance_deterministic.py` | 10 passed |
| `test-file tests/services/ai_agents/test_orchestrator_agents.py` | 22 passed |
| `test-file tests/services/test_decision_orchestrator.py` | 81 passed |
| `accept backend-runtime` | PASS |
| `accept architecture` | PASS |
| `accept no-bypass` | PASS(hard_bypass_count=0) |
| `accept style` | PASS |
| `accept docs` | PASS |
| `accept backend-file src/agent_trading/services/ai_agents/subprocess_io.py`(신규 파일) | PASS — 자동 매칭된 `tests/services/ai_agents/test_agent_subprocess.py` 1건 실행, 0 실패 |
| `lint-path scripts/run_agent_subprocess.py src/agent_trading/services/ai_agents/subprocess_io.py tests/services/ai_agents/test_agent_subprocess.py` | All checks passed |
| `accept script-file scripts/run_agent_subprocess.py`(선택) | FAIL — `tests/scripts/test_fdc_skip.py`가 `/workspace` read-only 인프라 이슈로 실패. PR #277/#281/#282/#283과 동일한 사전 존재 인프라 이슈(이번 PR과 무관, PASS로 포장하지 않음) |

## 미검증 사항

- 실제 재배포 후 subprocess 경로를 통해 `agent_runs.ai_compliance.
  structured_output_json`에 `compliance_rule_set:*` 마커가 실제로
  기록되는지(PR #283과 동일 항목, 아직 재배포 전).
- `run_agent_subprocess.py`의 `/workspace` read-only import-time
  이슈 자체는 이번 PR 범위 밖이라 해결하지 않았다 — 별도 이슈로
  남아 있다.
