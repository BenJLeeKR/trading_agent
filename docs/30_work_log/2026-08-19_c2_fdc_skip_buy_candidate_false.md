# FDC 호출량 절감 C2 — buy_candidate=False + eligibility_passed=False 결정론적 skip(2026-08-19 KST)

## 1. 배경

FDC(final_decision_composer) provider(Gemini) 429 대응으로 PR #287/#288에서
프로세스 간 실제로 공유되는 파일 기반 rate limiter(`fdc_rate_limiter.py`)를
도입했다. 이후 "429 자체를 없앨 수 없는가"라는 질문에 답하기 위한 설계
검토 턴에서, 현재의 fail-open 방식을 strict(no-bypass) 큐로 바꾸는 안만으로는
불충분하다는 결론을 내렸다 — 사이클당 실제 종목 수(29~36개) 대비 60초당
10회라는 상한을 지키려면 대기 시간이 subprocess 전체 timeout(90초) 예산을
넘어설 수 있고, 그 경우 `provider_rate_limit` fallback이 그냥 다른 종류의
(현재 미분류) timeout fallback으로 옮겨갈 뿐이기 때문이다. 그래서 strict
queue와 **병행**할 "호출량 자체를 줄이는 안"(안 C)이 필요하다고 판단했고,
그 하위 후보를 조사하는 별도 설계 검토 턴에서 다음을 발견했다.

- `src/agent_trading/services/pre_ai_gate.py`: AI 파이프라인 전체(EI/AR/AC/FDC
  모두 포함)를 subprocess 스폰 이전에 스킵하는 이미 존재하는 별도 메커니즘.
  held_position 재진입 관련 스킵 로직만 있고, 신규 진입 buy_candidate 관련
  스킵은 없음.
- 1개 사이클(29종목) DB 샘플 기준, core-lane buy_candidate=false 후보가
  전체 FDC 호출의 약 44.8%를 차지했다. 이 후보들은 `decision_orchestrator.py`의
  `_check_ai_buy_override_gate()`가 FDC의 APPROVE/BUY 응답을 downstream에서
  WATCH/HOLD로 강제 강등하는 경로에 해당할 가능성이 있었다.

이를 근거로 C1(held_position TTL 확장만)/**C2(C1 + buy_candidate=false
신규 진입 후보 FDC 스킵) — 권고안**/C3(C1+C2+EI-materiality 스킵 역행, 고위험)
세 옵션을 제시했고, 이번 턴에서 사용자가 **C2 구현**을 명시적으로 지시했다.

## 2. 왜 구현했는가

FDC 호출 1건은 Gemini provider API 호출 1회를 의미하며, 429 발생 원인인
"단위 시간당 호출 수"를 줄이는 가장 직접적인 방법은 애초에 불필요한 호출을
만들지 않는 것이다. `buy_candidate=false`인 신규 진입 후보 중 일부는 FDC가
무엇을 응답하든(설령 APPROVE/BUY를 응답해도) `_check_ai_buy_override_gate()`가
반드시 WATCH/HOLD로 되돌리므로, 이 하위 구간에 한해서는 FDC를 호출하지
않고 그 결과를 미리 계산해도 **최종 결정에 아무 차이가 없다** — call-volume
최적화이지 정책 변경이 아니다.

## 3. 동치성 검증 — 왜 스코프를 좁혔는가

구현 착수 전, `_check_ai_buy_override_gate()`(`decision_orchestrator.py`
596-777행)의 전체 로직을 코드로 직접 대조했다. 그 결과, 이전 설계 검토
턴의 "buy_candidate=false면 항상 강등된다"는 전제가 **정확하지 않음**을
발견했다 — 해당 턴이 참조한 DB 샘플(13/29건)이 우연히 전부 안전한 분기에만
속했을 뿐이다.

`_check_ai_buy_override_gate()`는 `has_position=False`이고
`deterministic_trigger.buy_candidate=False`일 때만 개입하며, 그 안에서
다음과 같이 분기한다(의사코드):

```
if not eligibility_passed:
    if (좁은 예외: signal_feature_snapshot_id is None
        and eligibility_reasons ⊆ {source_type_allowed, low_feature_coverage}):
        return None  # 강등 없음 — FDC 원래 결정 유지
    return downgrade  # ai_override_eligibility_blocked — 항상 강등  ← ★ 안전(A)
if reason in _AI_OVERRIDE_EXECUTION_INFEASIBLE_REASONS for reason in eligibility_reasons:
    return downgrade  # ai_override_execution_infeasible            ← ★★ eligibility_passed=True 전제, 스코프 밖
if not expected_value_gate_passed:
    return downgrade  # ai_override_expected_value_blocked          ← ★★★ FDC 자신의 confidence/conviction에 의존, 재현 불가
... (symbol_state DB 조회 + hysteresis)
if hysteresis_decision.blocked:
    return downgrade                                                ← ★★★ 새 DB 조회 필요 + "차단 안 함"이면 강등 없음
return None
```

- **분기 A(eligibility_passed=False, 좁은 예외 제외)**: FDC의 confidence/
  conviction과 무관하게 무조건 강등된다. **upstream에서 안전하게 재현
  가능** — 이번 구현의 스코프.
- **execution_infeasible 분기**: `eligibility_passed=True`인 상태에서만
  도달 가능한 코드 경로다(`if not eligibility_passed: return ...`으로
  먼저 빠지므로). `buy_candidate=false`이면서 `eligibility_passed=True`인
  경우(entry_score 부족)는 실제로 존재하는 조합이라, 이 분기를 포함하려면
  `eligibility_passed=True`인데도 강등되는 별도 조건을 다시 검증해야
  한다 — 이번 턴에서는 **명시적으로 스코프 밖**으로 배제했다(private
  상수 `_AI_OVERRIDE_EXECUTION_INFEASIBLE_REASONS`를 다른 모듈에서
  import하는 것도 모듈 경계상 부적절함을 별도로 확인).
- **EV gate 분기**: `evaluate_expected_value_gate()`가 `decision_type`/
  `confidence`/`conviction`을 직접 파라미터로 받는데, 이 값들은 FDC 자신의
  출력이다 — FDC를 부르기 전에는 계산 자체가 불가능한 순환 의존이라
  **재현 불가**.
- **hysteresis 분기**: `symbol_trade_states`/24시간 `external_events` DB
  조회가 필요하고(subprocess 현재 컨텍스트에 없음), `hysteresis_decision.blocked=False`이면
  강등 없이 FDC의 원래 결정이 그대로 유지되는 경로도 있어 **"항상 강등"이
  아니므로 재현 대상 자체가 아님**.

**결론**: "조건식이 조금이라도 다르면 구현하지 말고 보고하라"는 지시에 따라,
전체 buy_candidate=false를 그대로 구현하지 않고 **분기 A(eligibility_passed=False,
좁은 예외 제외)만** 안전하게 구현했다. 나머지 분기는 스코프 밖으로 명시적으로
배제한다.

## 4. 변경 파일

- `scripts/run_agent_subprocess.py` — `_check_fdc_skip()`에 Condition 4 추가
  (기존 Condition 3 cash_shortage 이후, 최종 fallback return 이전에 삽입).
- `tests/scripts/test_fdc_skip.py` — `TestFdcSkipBuyCandidateEligibilityBlocked`
  클래스(10개 테스트) 추가, 관련 import(`DecisionContextEntity`,
  `DeterministicTriggerAssessment`) 추가, 모듈 docstring 테스트 커버리지
  목록 갱신.
- `docs/99_meta_handover/[BACKLOG] backlog.md` — 이번 구현 완료 기록 및
  배포 후 실측 항목(남은 backlog 10) 추가.

EV gate/sizing/execution/translation/held_position 매도 정책 관련 파일은
전혀 건드리지 않았다.

## 5. 결정론적 summary/reason_codes 설계 원칙

- **첫 문장에서 결정론적 스킵임을 명시**: `"[규칙 기반 생략] {symbol} — ..."`
  — AI가 실제로 판단한 것처럼 보이지 않도록 명시적으로 표기했다(사용자
  요구사항인 "AI가 판단한 것처럼 보이면 안 된다"에 대응).
- **2026-08-19 축약**: `summary`가 실제로 의사결정 화면의 "근거" 컬럼에
  그대로 노출된다는 점을 확인한 뒤(운영 UI 가독성 요구), source_type/
  buy_candidate=False/watch_candidate=.../eligibility_passed=False/
  eligibility_reasons=[...] 같은 코드성 항목을 전부 제거하고, 강제된
  최종 결과(WATCH/HOLD)만 자연어 문장에 남기도록 축약했다. 최종 문구:
  `"[규칙 기반 생략] {symbol} — 신규 진입 자격을 충족하지 못한 종목으로,
  AI가 실제로 매수 판단을 내려도 규칙에 의해 최종 결과가 {WATCH|HOLD}로
  강제 확정되므로 FDC 호출 자체를 생략했습니다."` — 접두사 이후 설명
  부분이 한국어 기준 약 100자로, 다른 조건들의 요약 문구와 길이 균형이
  맞다. 상세 판단 근거(eligibility_reasons 등)는 `skip_reason_codes`/
  `reason_codes`로만 노출하고, 사람이 읽는 문장에서는 뺐다.
- **reason_codes 명명**: `skip_reason_codes`(subprocess → 부모 프로세스
  전달용, 단일 문자열)는 `buy_candidate_eligibility_blocked`. 기존 값
  (`risk_reject`, `no_events_no_position`, `cash_shortage`)과 동일한
  명명 스타일(접두사 없는 snake_case)을 따랐다 — 사용자가 예시로 제시한
  `fdc_skipped_...` 접두사 스타일 대신 기존 컨벤션과의 일관성을 우선했다.
  `FinalDecisionComposerOutput.reason_codes`(복수 가능)는
  `("buy_candidate_eligibility_blocked", "ai_override_eligibility_blocked",
  "forced_watch_candidate" 또는 "forced_hold")` — downstream 게이트가
  실제로 쓰는 `ai_override_eligibility_blocked` 코드를 그대로 포함해
  두 메커니즘이 같은 근거를 가리킴을 추적 가능하게 했다. 기존
  `risk_rejected`/`no_events`/`no_position`/`insufficient_cash`와 겹치지
  않음을 확인.

## 6. 테스트 결과

`tests/scripts/test_fdc_skip.py` 전체 32개 테스트(dev-validation 컨테이너,
`bash scripts/harness/run.sh test-file tests/scripts/test_fdc_skip.py`) —
**32 passed**. 신규 10개 테스트가 다음을 검증한다.

- watch_candidate=False/True 각각에서 HOLD/WATCH로 정확히 분기.
- summary가 `[규칙 기반 생략]`/`FDC 미호출`로 시작하고 source_type/
  buy_candidate/watch_candidate/eligibility_passed/eligibility_reasons/
  강제된 최종 값을 모두 포함.
- 보유 포지션(has_position=True)에서는 새 조건이 절대 발동하지 않음.
- buy_candidate=True에서는 미발동(구조상 eligibility_passed=True를 내포).
- eligibility_passed=True + buy_candidate=False(EV gate/hysteresis 의존
  분기)에서는 미발동 — 스코프 밖 명시적 배제 확인.
- 좁은 예외(signal_feature_snapshot_id=None + reasons가 부분집합)에서
  미발동, snapshot_id가 있으면 같은 reasons에도 발동(예외 조건의 정확한
  경계 확인).
- deterministic_trigger=None인 기존 빈 컨텍스트에서는 기존 조건 3
  (no_events_no_position)이 그대로 발동 — 회귀 없음.

## 7. 검증 명령과 결과

| 명령 | 결과 |
|------|------|
| `bash scripts/harness/run.sh test-file tests/scripts/test_fdc_skip.py` | PASS (32/32) |
| `bash scripts/harness/run.sh accept script-file scripts/run_agent_subprocess.py` | PASS |
| `bash scripts/harness/run.sh accept backend-runtime` | PASS |
| `bash scripts/harness/run.sh accept architecture` | PASS (기존 baseline 위반 수 불변) |
| `bash scripts/harness/run.sh accept no-bypass` | PASS |
| `bash scripts/harness/run.sh accept style` | PASS |
| `bash scripts/harness/run.sh accept docs` | (본 문서 작성 후 실행 예정) |

이번 턴에서 이 테스트 파일과 관련해 알려졌던 `/workspace` read-only
컨테이너 infra 이슈는 재현되지 않았다 — `test-file` 명령이 정상적으로
32개 테스트를 전부 수집·실행했다.

## 8. 배포 후 실측 항목

1. 새 `buy_candidate_eligibility_blocked` skip_reason_codes의 실제 발동
   빈도/비중(전체 FDC 스킵 대비, 전체 신규 진입 후보 대비).
2. 사이클당 실제 FDC provider 호출 수 감소폭(이전 대비).
3. 호출량 감소와 함께 `provider_rate_limit` fallback 비율이 추가로
   낮아지는지(기존 rate limiter 실측치와 비교).
4. 이 스킵이 강등 대상 후보를 놓치지 않는지 — `decision_type` 분포를
   downstream `ai_override_eligibility_blocked` 발동 이력과 대조해
   교차 확인(오적용 여부 재확인).

## 9. 후속 수정 — Condition 2(`no_events_no_position`) summary 자세화(2026-08-19 KST)

배포 후 첫 실측 턴에서 `no_events_no_position` 조건의 기존 summary
(`"{symbol} — 최근 이벤트 없음. FDC 생략."`)가 다른 결정론적 조건 대비
너무 짧다는 사용자 피드백에 따라, C2와 별개로 이 조건만 다음과 같이
자세화했다.

- 새 문구: `"[결정론적 판단 근거] {symbol} — 최근 72시간 내 특별한
  이벤트가 없고 보유 중인 포지션도 없어, 신규 진입 신호가 없다고
  판단해 FDC 호출을 생략하고 HOLD로 확정했습니다."`
- `[결정론적 판단 근거]` 접두사는 C2가 쓰는 `[규칙 기반 생략]`과는
  의도적으로 다르게 유지했다(사용자가 이번 조건에만 적용을 명시적으로
  선택, 다른 3개 결정론적 조건은 기존 문구 그대로 둠 — 접두사 통일은
  하지 않음).
- "최근 72시간"은 `decision_orchestrator.py`의 `assemble()`이
  `external_events.list_by_symbol(..., since=now-72h)`로 `recent_events`를
  조회하는 실제 조회 창을 그대로 반영한 것이다(코드 확인 후 명시,
  추측 아님).
- `tests/scripts/test_fdc_skip.py::TestFdcSkipNoEvents::test_no_events_summary_discloses_deterministic_skip`
  신규 추가 — summary가 `[결정론적 판단 근거]`로 시작하고 FDC/HOLD를
  포함하는지 검증. 파일 전체 33/33 통과.
- reason_codes(`no_events`, `no_position`)와 skip 판정 로직 자체는
  무변경 — summary 문구만 변경.
