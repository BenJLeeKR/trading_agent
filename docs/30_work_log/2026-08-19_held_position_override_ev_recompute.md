# `held_position` override 후 EV gate 재계산 구현(2026-08-19 KST)

## 1. 배경

`provider_rate_limit`(429) fallback이 `held_position` 매도 경로에 미치는
실질 영향을 실측하는 앞선 턴에서, AR risk가 강한 신호(risk_opinion=
`reduce`, risk_score=`0.8`)를 낼 때 `_check_held_position_sell_override()`가
`HOLD→EXIT/REDUCE`로 결정을 성공적으로 전환시켰음에도, 그 6건 전부
`order_request`가 0건이었음을 확인했다. 그 뒤 이어진 설계 검토 턴에서
코드를 정밀 추적해 원인을 다음과 같이 확정했다.

- `decision_agent_runner.py`가 `AgentExecutionBundle`을 만드는 시점(override
  *이전*)에 `evaluate_expected_value_gate()`를 딱 한 번 호출한다. 이때
  `decision_type`은 FDC의 원본 값(대개 `HOLD`, 429 fallback이든 진짜
  FDC 판단이든 동일)이다.
- `expected_value_gate.py`는 `decision_type`이 non-actionable(HOLD/WATCH)
  이면 EV 8개 필드를 전부 `None`으로 두고
  `reason_codes=("expected_value_not_required_non_actionable",)`로
  트리비얼 통과시킨다.
- `decision_orchestrator.py`의 held_position override는 `decision_type`/
  `side`/`composer_output.summary`만 갱신하고, 이 EV 8개 필드는 전혀
  다시 계산하지 않는다.
- `translation.py::_has_required_expected_value_anchor()`는 SELL/EXIT/
  REDUCE 경로에서 이 8개 필드 전부 non-None을 요구하므로, override로
  decision_type이 바뀌어도 8개 필드가 여전히 `None`인 이 상태에서는
  항상 `False`를 반환해 `build_submit_order_request_from_decision()`이
  `None`을 반환한다.

이 문제는 429와 직접적 인과관계가 없다 — `evaluate_expected_value_gate()`
호출 시점 자체가 override *이전*으로 고정돼 있어, FDC가 정상 성공해
진짜 `HOLD`를 냈어도 완전히 동일한 경로를 탄다(코드로 확정, 다만 오늘
운영 데이터에는 429 없이 override가 발동한 사례가 0건이라 실측 재현은
하지 못했다).

## 2. 왜 이 수정이 "EV gate 완화"가 아니라 "평가 시점 정합성 복구"인가

이번 수정은 `expected_value_gate.py`의 threshold(SELL/EXIT/REDUCE는
5bps)나 계산 로직을 전혀 건드리지 않는다. 대신, override로 decision_type이
바뀐 **직후** 같은 함수(`evaluate_expected_value_gate()`)를 **그 새
decision_type으로 다시 호출**할 뿐이다. 이는 FDC가 스스로 REDUCE/EXIT를
판단했을 때 이미 적용되는 것과 완전히 동일한 함수·동일한 threshold를
override 케이스에도 적용하는 것이며, 새로운 판단 기준을 만들지 않는다.
재계산 후에도 edge가 낮으면 여전히 차단되며(§5 테스트로 확인), "차단을
줄이는" 방향이 아니라 "평가가 일어나는 시점을 override 이후로 맞추는"
정합성 수정이다.

## 3. 변경 파일

- `src/agent_trading/services/decision_orchestrator.py`
  - 기존에 `assemble()` 내부에 인라인으로 있던 held_position override
    적용 블록을 `_apply_held_position_sell_override()` private 메서드로
    추출(동작 변화 없음, 테스트 가능성을 위한 리팩터링).
  - 그 메서드 안에서, override 적용 직후 `evaluate_expected_value_gate(
    decision_type=override_dt, confidence=..., conviction=..., risk_score=...,
    context=assembled_context)`를 재호출하고, 그 결과로 `agent_bundle.
    ai_inputs`의 `expected_return_bps`/`expected_downside_bps`/
    `net_expected_value_bps`/`final_trade_score`/`minimum_required_edge_bps`/
    `edge_after_cost_bps`/`estimated_round_trip_cost_bps`/
    `slippage_buffer_bps`/`expected_value_gate_passed`/
    `expected_value_gate_reason_codes`를 `object.__setattr__`로 갱신
    (기존 코드가 `decision_type`/`side`를 갱신할 때 쓰던 것과 동일한
    frozen dataclass mutation 패턴).
- `tests/services/test_held_position_sell_override.py`
  - `TestApplyHeldPositionSellOverrideEvRecompute` 클래스 6개 테스트 추가.
  - 관련 import(`AgentExecutionBundle`, `AIDecisionInputs`, `AssembledContext`,
    `OrderIntent`, `build_submit_order_request_from_decision`,
    `DeterministicTriggerAssessment`, `SubmitOrderRequest`, `OrderSide`)
    및 테스트 헬퍼(`_make_submit_request`, `_make_deterministic_trigger`)
    추가.

`translation.py`, `expected_value_gate.py`는 **전혀 수정하지 않았다** —
이번 턴의 명시적 제약(EV anchor 요구/threshold를 완화·우회하지 않음)을
그대로 지켰다.

## 4. 새 메서드 `_apply_held_position_sell_override()`

```python
def _apply_held_position_sell_override(
    self, *, agent_bundle, assembled_context, derivation, symbol,
) -> None:
    override = self._check_held_position_sell_override(
        source_type=derivation.source_type,
        ar_output=agent_bundle.risk_output,
        fdc_output=agent_bundle.composer_output,
    )
    if override is None:
        return
    override_dt, override_side, override_rationale = override
    object.__setattr__(agent_bundle.ai_inputs, "decision_type", override_dt)
    object.__setattr__(agent_bundle.ai_inputs, "side", override_side)

    recomputed_ev = evaluate_expected_value_gate(
        decision_type=override_dt,
        confidence=agent_bundle.ai_inputs.confidence,
        conviction=agent_bundle.ai_inputs.conviction,
        risk_score=agent_bundle.ai_inputs.risk_score,
        context=assembled_context,
    )
    # ... recomputed_ev의 8개 필드 + gate_passed + reason_codes를
    # agent_bundle.ai_inputs에 object.__setattr__로 반영 ...

    # (기존 decision_type/side/summary override 로직 그대로 이어짐)
```

`assemble()`에서의 호출부는 인라인 블록 전체가 다음 한 호출로 대체됐다:

```python
self._apply_held_position_sell_override(
    agent_bundle=agent_bundle,
    assembled_context=assembled_context,
    derivation=derivation,
    symbol=request.symbol,
)
```

## 5. SELL/EXIT/REDUCE 재계산이 FDC 성공/실패와 무관하게 유효한 이유

`expected_value_gate.py::_resolve_score_anchor()`는 `is_entry=False`
(SELL/EXIT/REDUCE)일 때 `deterministic_trigger.exit_score`를 우선
사용한다 — 이 값은 결정론적 트리거 엔진이 만든 값으로 FDC의 confidence/
conviction과 무관하다. `edge_after_cost_bps`(게이트 통과 여부를 결정하는
핵심 값)도 confidence/conviction을 전혀 참조하지 않는다(참조하는 것은
`final_trade_score`뿐이며, 이는 게이트 통과 여부와 무관). 따라서 FDC가
429로 confidence=0/conviction=0인 fallback을 냈어도, `deterministic_trigger`
와 AR의 실제 `risk_score`만 있으면 재계산이 유효하게 동작한다 —
`test_ev_recompute_works_with_fdc_fallback_shape` 테스트로 확인.

## 6. 테스트/검증 결과

| 명령 | 결과 |
|------|------|
| `test-file tests/services/test_held_position_sell_override.py` | PASS (20/20, 신규 6건 포함) |
| `test-file tests/services/test_decision_orchestrator.py` | PASS (81/81, 회귀 없음) |
| `test-file tests/services/test_submit_order_from_decision.py` | PASS (12/12, 회귀 없음) |
| `accept backend-file src/agent_trading/services/decision_orchestrator.py` | PASS |
| `accept backend-runtime` | PASS |
| `accept architecture` | PASS |
| `accept no-bypass` | PASS(review_bypass 1건, 기존 파일에 이미 있던 `repos=MagicMock()` 픽스처 패턴) |
| `accept style` | PASS |
| `accept docs` | (본 문서 작성 후 실행) |

신규 테스트가 검증하는 것:

1. override 발동 시 `decision_type`/`side`가 바뀌고 EV 8개 필드가 더
   이상 전부 `None`이 아님(트리비얼 통과 상태 탈출).
2. FDC fallback 형태(confidence=0/conviction=0)에서도 재계산이 유효한
   값을 만듦.
3. override 미발동(risk_opinion=allow, 낮은 risk_score) 시 EV 필드가
   전혀 바뀌지 않음(부작용 없음).
4. **재계산 후에도 edge가 낮으면 여전히 게이트가 차단함** — 이번 수정이
   차단을 줄이는 방향이 아님을 증명하는 핵심 회귀 테스트.
5. EV 게이트를 통과하는 좋은 edge 케이스에서
   `build_submit_order_request_from_decision()`이 실제로 주문을 생성함.
6. (대조) 재계산을 하지 않으면(수정 전 상태 재현) 여전히 anchor 결측으로
   차단됨 — 이번 수정의 필요성 자체를 확인.

## 7. 미검증 사항(운영 실측 필요)

- 오늘 운영 데이터에 429 없이 override가 발동한 사례가 없어, "FDC 정상
  성공 + HOLD → override" 조합에서도 동일 문제가 있었다는 것은 코드
  추적으로만 확정했고 실측 재현은 하지 못했다 — 이번 수정 배포 후
  그런 사례가 실제로도 정상 처리되는지 확인 필요.
- 재계산된 `edge_after_cost_bps`가 실제 운영 데이터에서 threshold(5bps)를
  넘는 비율 — 오늘 실제 FDC가 직접 REDUCE를 판단한 69건 대부분이
  threshold 미달로 차단됐던 패턴을 보면, override 케이스도 재계산 후
  여전히 상당수가 차단될 가능성이 있다. "복구 = 항상 매도 성사"가
  아님을 배포 후 실측으로 확인해야 한다.
- 이 수정이 실제 매도 실행 품질(과다매도/과소매도)에 미치는 영향은
  `AGENTS.md` 원칙에 따라 차단 빈도가 아니라 사후 성과(백테스트/운영
  결과)로 판단해야 하며, 이번 턴에서는 판단하지 않았다.

## 8. 정책 영향 없음 확인

- `translation.py::_has_required_expected_value_anchor()`의 요구사항(8개
  필드 non-None, SELL/EXIT/REDUCE anchor_payload 체크) — 무수정.
- `expected_value_gate.py`의 threshold(entry 10bps, non-entry 5bps 등)와
  계산식 — 무수정.
- EV gate/sizing/execution/held_position 매도 정책의 나머지 부분 — 무수정.
- 오직 "override로 바뀐 decision_type을 기준으로 EV gate가 언제
  평가되는가"만 수정했다.
