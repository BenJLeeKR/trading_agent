# FDC skip 관측성 버그 수정 — subprocess 경로의 `decision_json.ai_call_path` 오기록

## 문제

전체 매수 경로 read-only 검토 턴에서 발견한 관측성 결함이다. 운영 기본
경로인 subprocess 격리(`AGENT_SUBPROCESS_ISOLATION` 기본값 `"1"`)에서:

1. `scripts/run_agent_subprocess.py::_check_fdc_skip()`은 AR `reject`/
   `risk_score>=0.85`(source_type=core, 미보유) 등 조건을 만족하면
   FDC 호출을 실제로 생략하고, 합성 `FinalDecisionComposerOutput`
   (HOLD/WATCH)을 반환한다 — 이 skip 판정 자체는 이미 정상 동작한다.
2. 하지만 이 `skip_fdc`/`skip_reason`을 `AgentSubprocessOutput`에
   실어 부모 프로세스로 넘기지 않았다.
3. 부모 프로세스의 `subprocess_helpers.py::deserialize_agent_output()`
   도 이 필드를 읽지 않으므로, subprocess 경로로 조립된
   `AIDecisionInputs.ei_skipped`/`ar_skipped`/`fdc_skipped`/
   `skip_reason_codes`는 항상 dataclass default(`False`/`()`)로
   남는다.
4. `decision_factory.py:219-222`가 이 값을 그대로
   `decision_json.ai_call_path`에 저장하므로, **subprocess 경로로
   처리된 모든 결정은 실제로 FDC를 생략했더라도
   `ai_call_path.fdc_skipped=false`로 기록된다.**

반면 in-process 경로(`decision_agent_runner.py:609-612`)는 이 4개
필드를 정확히 채운다 — 두 경로 간 관측 데이터 정합성이 깨져 있었다.

이 문제는 **주문 gate/정책 문제가 아니다** — `_check_fdc_skip()`이
반환하는 합성 `FinalDecisionComposerOutput`(decision_type=HOLD/WATCH)
자체는 정상적으로 다운스트림(`decision_orchestrator.py`의 가드 체인,
`translation.py`)에 전달되므로, 실제 주문 판단은 전혀 영향받지 않았다.
오직 "FDC가 호출됐는지 생략됐는지"를 기록하는 관측 메타데이터만 부정확
했다.

## 수정 내용

1. **`scripts/run_agent_subprocess.py::AgentSubprocessOutput`**에
   4개 필드 추가: `ei_skipped: bool = False`, `ar_skipped: bool =
   False`, `fdc_skipped: bool = False`, `skip_reason_codes:
   tuple[str, ...] = ()`.
2. **`main()`의 출력 조립 지점**에서 실제 값을 채움: `ei_skipped=False`
   (이 스크립트에는 EI를 생략하는 로직이 없음 — `_should_skip_event_
   interpretation()`은 in-process 전용), `ar_skipped=False`(AR은
   subprocess에서 항상 실행됨), `fdc_skipped=skip_fdc`,
   `skip_reason_codes=(skip_reason,) if skip_fdc and skip_reason else
   ()`(이미 계산된 `_check_fdc_skip()`의 실제 반환값을 그대로 사용).
3. **`src/agent_trading/services/ai_agents/subprocess_io.py`**의
   `AgentSubprocessOutputLike` Protocol과 `build_agent_subprocess_
   output_payload()`에 4개 키 추가 — PR #283/#284에서 확립한
   "import-time 부작용 없는 helper" 구조를 그대로 따랐다.
4. **`src/agent_trading/services/subprocess_helpers.py::
   deserialize_agent_output()`**가 stdout JSON에서 이 4개 키를 읽어
   `AIDecisionInputs`에 채우도록 수정. 키가 없으면(구버전 payload와의
   하위 호환) `False`/`()`로 안전하게 기본값 처리한다.
   `skip_reason_codes`가 list/tuple이 아닌 단일 문자열로 잘못 전달된
   경우도 방어적으로 1-tuple로 감싸도록 처리했다.

## reason code 명명 불일치 — 확인했으나 통일하지 않음

subprocess `_check_fdc_skip()`의 reason 값은 `"risk_reject"`,
`"no_events_no_position"`, `"cash_shortage"` 3가지인 반면, in-process
`_should_skip_final_decision_composer()`의 reason은 `"skip_fdc_
high_risk"` 하나뿐이다. 이는 두 함수의 skip 판정 조건 자체가 다르기
때문이다(subprocess가 더 넓은 3개 조건을 검사, in-process는 AR
고위험 1개 조건만 검사) — 각각 별도로 설계된 로직이라 문자열이 원래
부터 달랐다.

이 두 문자열을 통일하려면 skip 판정 로직 자체(조건 집합)를 재설계해야
하는데, 이는 이번 PR의 명시적 금지 사항(정책/skip 로직 변경 금지)에
해당한다. 게다가 각 문자열은 이미 `tests/scripts/test_fdc_skip.py`
(subprocess 쪽)와 `tests/scripts/test_run_decision_loop.py`/
`tests/services/test_decision_factory.py`/`tests/services/
test_decision_orchestrator.py`(in-process 쪽)에 정확한 리터럴로
고정된 채 테스트되고 있어, 임의로 바꾸면 기존 테스트가 깨진다. 따라서
이번 PR에서는 **실제 reason 값을 있는 그대로 전달하는 것**에만
집중했고, 명명 통일은 별도 논의 대상으로 남겨둔다.

## 정책/주문 영향 여부

없음. `translation.py`/`execution_service.py`/`sizing_engine.py`/
EV gate 관련 코드는 전혀 건드리지 않았다. `_check_fdc_skip()`이
반환하는 합성 `FinalDecisionComposerOutput`(HOLD/WATCH)의 값 자체도
변경하지 않았다 — 오직 그 사실을 부모 프로세스에 정확히 알리는
배관만 수정했다.

## 저장값 변화

- **변경 전**: subprocess 경로에서 `decision_json.ai_call_path.
  fdc_skipped`는 실제 FDC 생략 여부와 무관하게 항상 `false`,
  `skip_reason_codes`는 항상 `[]`.
- **변경 후**: subprocess 경로에서도 in-process와 동일하게, FDC가
  실제로 생략된 결정에 한해 `fdc_skipped=true`,
  `skip_reason_codes=["risk_reject"]` 또는 `["no_events_no_position"]`
  또는 `["cash_shortage"]`가 정확히 기록된다. `ei_skipped`/
  `ar_skipped`는 subprocess 경로에서 이 스크립트의 실제 동작(EI/AR은
  항상 실행됨)에 맞춰 계속 `false`로 남는다(정확한 값 — 조작 아님).
- **과거 데이터는 자동 보정되지 않는다.** 이미 기록된 `trade_decisions.
  decision_json.ai_call_path.fdc_skipped=false` row 중 실제로는 FDC가
  생략됐던 것들은 소급 수정되지 않는다 — 이 수정은 재배포 이후 새로
  기록되는 결정부터만 정확해진다.

## 테스트/검증 결과

| 명령 | 결과 |
|---|---|
| `test-file tests/services/ai_agents/test_agent_subprocess.py` | **25 passed**(신규 2건: `test_round_trip_preserves_fdc_skipped_metadata`, `test_deserialize_missing_skip_fields_defaults_to_false`) |
| `test-file tests/services/test_decision_factory.py` | 10 passed(기존 `test_build_trade_decision_entity_stores_ai_call_path_skip_metadata`가 저장 projection을 이미 커버 — decision_factory.py 미변경이라 별도 확장 불필요) |
| `test-file tests/services/test_decision_orchestrator.py` | 81 passed |
| `accept backend-file src/agent_trading/services/ai_agents/subprocess_io.py` | PASS — 자동 매칭된 `test_agent_subprocess.py` 실행, 0 실패 |
| `accept backend-runtime` / `architecture` / `no-bypass` / `style` / `docs` | 전부 PASS |
| `accept script-file scripts/run_agent_subprocess.py`(선택) | FAIL — `tests/scripts/test_fdc_skip.py`가 `/workspace` read-only 인프라 이슈로 실패. PR #277/#281/#282/#283/#284와 동일한 사전 존재 인프라 이슈(이번 PR과 무관) |

**회귀 테스트 유효성 검증**: `subprocess_io.py`에서 `fdc_skipped`/
`skip_reason_codes` 키를 임시로 제거한 뒤 harness로 재실행해,
`test_round_trip_preserves_fdc_skipped_metadata`가 실제로
`KeyError: 'fdc_skipped'`로 실패함을 확인했다. 키를 복구해 25건 전체
재통과를 확인했다.

## 미검증 사항

- 재배포 후 실제 subprocess 경로를 통해 `decision_json.ai_call_path.
  fdc_skipped`가 실제 FDC 생략 발생과 정확히 일치하는지 실측.
- reason code 명명 불일치(§위)를 통일할지 여부는 별도 논의 필요 —
  이번 PR 범위 밖.
- 과거(재배포 이전) 데이터의 `fdc_skipped=false` 오기록을 소급
  정정할지 여부(예: 배치 재계산) — 이번 PR 범위 밖, 별도 결정 필요.
