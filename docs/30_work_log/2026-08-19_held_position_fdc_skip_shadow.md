# `held_position` FDC 호출 shadow-skip 관측 구조 추가(2026-08-19 KST)

## 1. 배경

`held_position` lane의 FDC 호출량을 줄이는 방법을 검토하는 이전 턴에서,
`deterministic_trigger.primary_candidate in {"NO_ACTION", "WATCH"}`인
구간(오늘 42.1%, 최근 5일 누적 45.2%의 held_position FDC 호출)에서
FDC가 실제로 REDUCE/EXIT로 뒤집은 사례가 5일 누적 **0/242건**이었음을
확인했다. 이 구간에서 HOLD와 WATCH는 둘 다 non-actionable로 주문
생성에 차이가 없어(`translation.py::actionable_types`에 둘 다 없음),
FDC를 생략해도 실행 결과는 같을 가능성이 매우 높다.

다만 이 0/242라는 결과는 **경험적 패턴**이지, C2(#298)처럼 downstream
코드가 보장하는 동치성이 아니다. 곧바로 skip을 넣으면 "이 패턴이
계속 유지되는지"를 검증할 방법 자체가 사라진다 — FDC를 안 부르면 그
시점에 FDC가 실제로 뭐라고 답했을지 영원히 알 수 없기 때문이다. 그래서
이번 턴은 skip을 적용하지 않고, **FDC 호출은 그대로 유지하면서 "지금
skip했다면 결과가 같았을까"를 계속 관측하는 구조**만 추가했다.

## 2. 설계 결정 — 왜 이 위치, 왜 이 스키마인가

**위치**: `DecisionOrchestratorService.assemble()`의 최말단, 기존 AR/EI
shadow bot 관측(PR #278) 및 loss-cut shadow 관측과 정확히 같은 지점.
이 지점 이후로는 `decision_type`/`side`/주문 수량을 mutate하는 코드가
전혀 없다는 것이 이미 두 개의 기존 shadow 관측으로 검증돼 있는
위치라, 세 번째 shadow 관측을 추가해도 동일한 안전성 보장이 그대로
적용된다.

**저장 위치**: `decision_json.shadow_held_position_fdc_skip` —
`sync_shadow_risk_bot_observation()`/`sync_shadow_event_bot_observation()`
과 완전히 동일한 `jsonb_set(decision_json, '{key}', $2::jsonb, true)`
append-only 패턴을 재사용했다. `guardrail_evaluations`는 고려했으나
채택하지 않았다 — 그 테이블은 "실제로 무언가를 차단/스킵했을 때"만
기록되는 반면, 이번 관측은 **차단하지 않고 매번(조건에 해당하는 모든
결정에 대해) 기록**해야 비교 표본이 쌓이므로 성격이 다르다.

**shadow 최종값 계산에 기존 override 함수를 재사용**: 단순히
"`primary_candidate`가 WATCH면 shadow=WATCH, 실제=WATCH면 일치"라고만
비교하면 불충분하다 — 실제 AR risk가 강해 `_check_held_position_sell_
override()`가 개입하는 경우까지 재현해야 "정말 skip해도 안전한가"를
제대로 검증할 수 있다. 그래서 shadow HOLD/WATCH 값을 가상 FDC 출력
으로 만들어 **같은 override 함수를 다시 호출**한다 — 이는 AR shadow
bot이 이미 쓰고 있는 "실제 판정 함수 재사용, 로직 복제 금지" 원칙을
그대로 따른 것이다.

## 3. 변경 파일

- `src/agent_trading/config/settings.py` — `_resolve_held_position_fdc_
  skip_shadow_enabled()` 함수, `AppSettings.held_position_fdc_skip_
  shadow_enabled` 필드 추가.
- `src/agent_trading/repositories/contracts.py` — `sync_shadow_held_
  position_fdc_skip_observation()` 프로토콜 선언 추가.
- `src/agent_trading/repositories/memory.py` — 위 메서드의 in-memory
  구현 추가.
- `src/agent_trading/repositories/postgres/trade_decisions.py` — 위
  메서드의 실제 Postgres 구현 추가(`jsonb_set` 패턴).
- `src/agent_trading/services/decision_orchestrator.py` —
  `_record_held_position_fdc_skip_shadow_observation()` 메서드 추가,
  `__init__`에 `held_position_fdc_skip_shadow_enabled` 파라미터 추가,
  override 적용 직전 FDC 원본 `decision_type`을 캡처하는 로컬 변수
  `_fdc_raw_decision_type` 추가, `assemble()` 최말단에 새 관측 호출
  추가.
- `scripts/run_decision_loop.py` — `DecisionOrchestratorService(...)`
  두 생성 지점에 새 플래그 전달.
- `docker-compose.yml` — `ops-scheduler` 서비스에
  `HELD_POSITION_FDC_SKIP_SHADOW_ENABLED` 환경변수 배선.
- `.env.example` — 새 환경변수 문서화.
- `tests/services/test_decision_orchestrator.py` — `TestHeldPositionFdcSkipShadowObservation` 9개 테스트 추가.

`translation.py`, `expected_value_gate.py`, `pre_ai_gate.py`,
`final_decision_composer.py`(FDC 호출 자체)는 전혀 건드리지 않았다.

## 4. 저장 스키마

```json
{
  "rule_set_version": "held_position_fdc_skip_shadow_v1",
  "primary_candidate": "WATCH",
  "shadow_skip_candidate": true,
  "shadow_decision_type": "WATCH",
  "shadow_final_decision_type": "WATCH",
  "actual_fdc_raw_decision_type": "WATCH",
  "actual_final_decision_type": "WATCH",
  "held_position_override_applied": false,
  "agreement": true,
  "provider_rate_limit_observed": false,
  "shadow_only": true,
  "decision_unaffected_by_shadow": true
}
```

- `primary_candidate`: `"NO_ACTION"` 또는 `"WATCH"`(이 값이 아니면
  애초에 관측 대상이 아니라 필드 자체가 기록되지 않음).
- `shadow_decision_type`: `primary_candidate=="WATCH"`면 `"WATCH"`,
  `"NO_ACTION"`이면 `"HOLD"` — FDC를 안 불렀다면 이 값을 썼을 것이라는
  가정.
- `shadow_final_decision_type`: 위 shadow 값을 가상 FDC 출력으로 삼아
  `_check_held_position_sell_override()`를 다시 통과시킨 최종값 — AR
  risk가 강하면 shadow도 EXIT/REDUCE로 바뀔 수 있다.
- `actual_fdc_raw_decision_type`: override 적용 **이전** FDC 실제 출력.
- `actual_final_decision_type`: override 적용 **이후** 실제로 저장된
  최종 `decision_type`.
- `held_position_override_applied`: shadow 세계에서 override가 개입
  했는지.
- `agreement`: `shadow_final_decision_type == actual_final_decision_type`
  — 이게 계속 `true`로 유지되는지가 향후 skip 전환 판단의 핵심 근거.
- `provider_rate_limit_observed`: 이 결정에서 실제로 429 fallback이
  있었는지(`composer_output.reason_codes`에 `provider_rate_limit`
  포함 여부) — 관측 대상 구간에서 429가 나더라도 shadow와 일치하면,
  그 429가 "불필요한 재시도였다"는 근거가 된다.

`실제 주문 생성 여부`는 의도적으로 저장하지 않았다 — HOLD/WATCH는
애초에 주문을 만들지 않고, `assemble()` 시점에는 `order_requests`가
아직 생성되기 전이라 이 관측 지점에서 알 수 없다. 필요하면
`decision_context_id` 기준 `order_requests` 조인으로 사후에 도출
가능하다(중복 저장 방지).

## 5. 왜 정책 변경이 아닌가

- FDC 호출 여부: 무변화(항상 호출됨, `_check_fdc_skip()`도 무수정).
- `decision_type`/`side`: 무변화(shadow 관측은 새 값을 계산만 하고
  절대 대입하지 않음 — 테스트 `test_*`에서 실제 저장된 `decision_type`이
  shadow 계산 전후로 동일함을 직접 확인).
- 주문 제출 경로: 무변화(`translation.py`/`execution_service.py` 전혀
  미수정).
- 기본값 `False` — 이 기능을 켜지 않으면 기존 동작과 100% 동일.

## 6. 테스트 결과

| 명령 | 결과 |
|------|------|
| `test-file tests/services/test_decision_orchestrator.py` | PASS (89/89, 신규 9건 포함) |
| `test-file tests/services/test_held_position_sell_override.py` | PASS (20/20, 회귀 없음) |
| `test-file tests/services/ai_agents/test_settings.py` | PASS (65/65, 회귀 없음) |
| `accept backend-file decision_orchestrator.py` | PASS |
| `accept script-file run_decision_loop.py` | PASS |
| `accept env` | PASS(새 env var는 advisory로만 표시, 하드 실패 아님) |
| `accept backend-runtime` | PASS |
| `accept architecture` | PASS |
| `accept no-bypass` | PASS(review만 — 기존 shadow 메서드와 동일한 broad exception 패턴) |
| `accept style` | PASS |
| `accept docs` | (본 문서 작성 후 실행) |

신규 테스트가 검증하는 것:

1. 비활성(`held_position_fdc_skip_shadow_enabled=False`) 시 완전
   no-op — `decision_json`에 아무 것도 추가되지 않음.
2. `primary_candidate="WATCH"` → `shadow_decision_type="WATCH"`로
   기록, 실제 저장된 `decision_type`은 관측 전후로 동일.
3. `primary_candidate="NO_ACTION"` → `shadow_decision_type="HOLD"`.
4. `primary_candidate="REDUCE_CANDIDATE"` → 관측 대상이 아니라 기록
   자체가 없음.
5. `source_type="core"` → held_position 전용이므로 기록 없음.
6. AR risk가 강해(`risk_opinion="reduce"`, `risk_score=0.8`,
   concentration 플래그) 실제로 override가 EXIT로 개입한 경우, shadow도
   같은 override 함수 재사용으로 EXIT를 재현함(`agreement=True`).
7. `trade_decision_id=None`이면 no-op.
8. repository 쓰기 실패 시 예외를 전파하지 않고 로그만 남김.

## 7. 미검증 사항

- 이 관측을 실제 운영에서 켠 뒤(`HELD_POSITION_FDC_SKIP_SHADOW_
  ENABLED=true`), `agreement`가 며칠~몇 주에 걸쳐 계속 100%에 가깝게
  유지되는지 — 이번 턴은 코드 구현까지만이고 실측 데이터 축적은 아직
  시작되지 않았다.
- `provider_rate_limit_observed=true`이면서 `agreement=true`인 사례의
  비중 — 이게 높으면 "429로 인한 재시도 자체가 애초에 불필요했다"는
  더 강한 근거가 될 것으로 예상되나, 실측 전에는 확인 불가.
- 이 관측이 활성화됐을 때 추가되는 계산 비용(AR override 함수 재호출
  1회)이 사이클 전체 latency에 미치는 영향 — 순수 in-memory 계산이라
  무시할 수준으로 예상되나 실측하지 않았다.

## 8. 다음 단계

`HELD_POSITION_FDC_SKIP_SHADOW_ENABLED=true`로 운영에서 활성화하고,
몇 주간 `shadow_held_position_fdc_skip.agreement` 분포를 축적한 뒤,
그 결과를 근거로 실제 skip 전환(이전 턴에서 검토한 "안 E") 여부를
별도 턴에서 재검토한다. 활성화 자체는 이번 PR의 범위가 아니며, 별도
운영 반영 결정이 필요하다.
