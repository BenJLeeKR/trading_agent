# `held_position` REDUCE/SELL_CANDIDATE shadow-skip 관측 확장(2026-08-20 KST)

## 1. 배경

`held_position`의 `provider_rate_limit`가 주로 발생하는 구간을 좁혀가는
이전 턴들에서, 실제 429는 `NO_ACTION/WATCH`가 아니라 `REDUCE_CANDIDATE`/
`SELL_CANDIDATE`(매도 후보군)에서 대부분 발생함을 확인했다(2026-08-20
실측: held_position 429 22건 전부 이 두 primary_candidate).

다만 이 구간 전체를 skip 후보로 보기엔 위험하다 — 오늘 실측:

| primary_candidate | 총 건수 | FDC가 HOLD로 되돌린 비율 |
|---|---|---|
| `REDUCE_CANDIDATE` | 184 | 22건(12.0%) |
| `SELL_CANDIDATE` | 34 | 2건(5.9%) |

그런데 `risk_opinion`별로 더 세분화하면 뚜렷한 패턴이 나타났다:

| `risk_opinion`(REDUCE_CANDIDATE 내) | 건수 | hold 비율 |
|---|---|---|
| `allow` | 17 | 29.4% |
| **`reduce`** | 72 | **0.0%** |
| `review` | 95 | 17.9% |

`risk_opinion in ("reject","reduce")`인 72건에서 FDC가 HOLD로 되돌린
사례가 0건이었다. 이 조건은 `_check_held_position_sell_override()`의
무조건 발동(FDC 출력과 무관하게 개입) 분기와 정확히 일치한다. 이번
턴은 이 좁은 하위 구간에 대해, **아직 실제 skip을 적용하지 않고**
NO_ACTION/WATCH shadow와 동일한 방식으로 관측만 확장한다.

## 2. 왜 별도 key로 분리했는가(설계 결정)

기존 `shadow_held_position_fdc_skip`(NO_ACTION/WATCH 전용)에 조건만
추가하는 안(§backlog "안 A")도 검토했으나, 다음 이유로 **별도 메서드·
별도 저장 key**(`shadow_held_position_reduce_skip`)로 분리했다.

- **위험 프로파일이 다르다**: NO_ACTION/WATCH는 HOLD/WATCH 둘 다
  non-actionable이라 라벨이 달라도 실행 결과가 항상 같다. REDUCE_
  CANDIDATE/SELL_CANDIDATE는 실제 매도 판단과 직결되고, REDUCE vs
  EXIT처럼 세부 라벨이 갈리면 sizing(수량)에도 실제 영향을 줄 수
  있다(PR #300에서 확인된 EV anchor 문제와 연결되는 영역).
- **필요한 관측 필드 자체가 다르다**: 이 구간은 `risk_opinion`/
  `risk_score`를 별도로 기록해야 하고, "라벨 일치"와 "실행 의미 일치"를
  분리해서 봐야 한다(§4) — 기존 payload 스키마에 없던 필드다.
- **해석 시 혼동 방지**: 하나의 key에 서로 다른 위험 수준의 관측을
  섞으면, 집계 시 "관측 전체의 agreement 비율"이 실제로는 서로 다른
  성격의 두 그룹이 섞인 숫자가 되어 오독 위험이 커진다.

## 3. shadow 계산 방식

기존 NO_ACTION/WATCH shadow와 동일한 "실제 판정 함수 재사용" 원칙을
그대로 따른다 — 새 계산 로직을 만들지 않는다.

```python
shadow_decision_type = "HOLD"  # FDC를 생략했다면 non-actionable로 시작했을 것이라는 가정
shadow_fdc_output = FinalDecisionComposerOutput(decision_type="HOLD", side="", confidence=0.0)
shadow_override = self._check_held_position_sell_override(
    source_type=source_type, ar_output=ar_output, fdc_output=shadow_fdc_output,
)
shadow_final_decision_type, shadow_final_side = (
    (shadow_override[0], shadow_override[1]) if shadow_override is not None
    else (shadow_decision_type, "")
)
```

`ar_output`은 실제 AR(ai_risk) 출력을 그대로 쓴다 — FDC 호출과 무관하게
이미 계산돼 있는 값이다. `risk_opinion in ("reject","reduce")` 조건
자체가 override의 첫 분기와 겹치므로, 이 하위 구간에서는 shadow
override가 (risk_flags에 따라) REDUCE 또는 EXIT를 반환할 것이다.

## 4. 실행 의미 필드 설계

REDUCE와 EXIT는 라벨은 다르지만 둘 다 "실제 매도 시도"라는 점에서
같다. 이를 구분해서 보기 위해 헬퍼를 추가했다.

```python
def _held_position_action_class(decision_type: str) -> str:
    return "SELL_ACTIONABLE" if decision_type in {"REDUCE", "EXIT"} else "NON_ACTIONABLE"
```

- `agreement`/`agreement_decision_only`: `shadow_final_decision_type ==
  actual_final_decision_type`(엄격한 라벨 일치).
- `agreement_execution_meaning`: `_held_position_action_class(shadow) ==
  _held_position_action_class(actual)`(REDUCE/EXIT 세부 라벨이 달라도
  둘 다 매도 시도면 일치로 봄).

두 필드를 분리해서 기록하면, 향후 "라벨은 자주 갈리지만 실행 의미는
거의 항상 같다"인지 "실행 의미 자체가 갈린다(한쪽은 매도, 한쪽은
비매도)"인지를 구분해서 판단할 수 있다 — 후자가 실제로 위험한
경우다.

## 5. 저장 스키마

```json
{
  "rule_set_version": "held_position_reduce_skip_shadow_v1",
  "primary_candidate": "REDUCE_CANDIDATE",
  "risk_opinion": "reduce",
  "risk_score": 0.72,
  "shadow_skip_candidate": true,
  "shadow_decision_type": "HOLD",
  "shadow_final_decision_type": "REDUCE",
  "shadow_final_side": "SELL",
  "actual_fdc_raw_decision_type": "REDUCE",
  "actual_final_decision_type": "REDUCE",
  "actual_final_side": "SELL",
  "held_position_override_applied": true,
  "agreement": true,
  "agreement_decision_only": true,
  "agreement_execution_meaning": true,
  "provider_rate_limit_observed": false,
  "shadow_only": true,
  "decision_unaffected_by_shadow": true
}
```

## 6. 변경 파일

- `src/agent_trading/config/settings.py` — `_resolve_held_position_
  reduce_skip_shadow_enabled()`, `AppSettings.held_position_reduce_
  skip_shadow_enabled` 필드 추가.
- `src/agent_trading/repositories/contracts.py`/`memory.py`/
  `postgres/trade_decisions.py` — `sync_shadow_held_position_reduce_
  skip_observation()` 추가(append-only `jsonb_set` 패턴 재사용).
- `src/agent_trading/services/decision_orchestrator.py` —
  `_held_position_action_class()` 헬퍼, `_record_held_position_reduce_
  skip_shadow_observation()` 메서드, `__init__` 플래그, `assemble()`
  최말단 호출 추가(기존 NO_ACTION/WATCH shadow 호출 바로 다음).
- `scripts/run_decision_loop.py` — 두 생성 지점에 새 플래그 전달.
- `docker-compose.yml`/`.env.example` — 새 환경변수 배선.
- `tests/services/test_decision_orchestrator.py` —
  `TestHeldPositionReduceSkipShadowObservation` 9개 테스트 추가.

`translation.py`, `expected_value_gate.py`, `pre_ai_gate.py`,
`final_decision_composer.py`(FDC 호출 자체)는 전혀 건드리지 않았다.

## 7. 왜 정책 변경이 아닌가

- FDC 호출 여부: 무변화(항상 호출됨).
- `decision_type`/`side`: 무변화(shadow 관측은 새 값을 계산만 하고
  절대 대입하지 않음 — 테스트로 확인).
- 주문 제출 경로: 무변화.
- 기본값 `False` — 켜지 않으면 기존 동작과 100% 동일.

## 8. 테스트 결과

| 명령 | 결과 |
|------|------|
| `test-file tests/services/test_decision_orchestrator.py` | PASS (98/98, 신규 9건 포함) |
| `test-file tests/services/test_held_position_sell_override.py` | PASS (20/20, 회귀 없음) |
| `test-file tests/services/ai_agents/test_settings.py` | PASS (65/65, 회귀 없음) |
| `accept backend-file decision_orchestrator.py` | PASS |
| `accept script-file run_decision_loop.py` | PASS |
| `accept env` | PASS |
| `accept backend-runtime` | PASS |
| `accept architecture` | PASS |
| `accept no-bypass` | PASS(review만) |
| `accept style` | PASS |
| `accept docs` | (본 문서 작성 후 실행) |

신규 테스트가 검증하는 것:

1. 비활성 시 완전 no-op.
2. `risk_opinion="reduce"` + 실제 FDC도 reduce → 라벨·실행의미 모두
   일치.
3. FDC가 EXIT를 냈지만 override 시뮬레이션은 REDUCE(concentration
   flag 없음) → `agreement_decision_only=False`,
   `agreement_execution_meaning=True`(둘 다 매도 시도).
4. `risk_opinion="review"`는 관측 대상 아님.
5. `primary_candidate="WATCH"`는 이 관측(REDUCE/SELL 전용)의 대상
   아님(기존 key가 담당).
6. `source_type="core"`는 대상 아님.
7. `SELL_CANDIDATE` + `risk_opinion="reject"`도 관측됨.
8. `trade_decision_id=None` → no-op.
9. repo 쓰기 실패 → 예외 미전파.

## 9. 미검증 사항

- 이 관측을 실제 운영에서 켠 뒤(`HELD_POSITION_REDUCE_SKIP_SHADOW_
  ENABLED=true`), `agreement`/`agreement_execution_meaning`이 며칠~몇
  주에 걸쳐 계속 높게 유지되는지 — 이번 턴은 코드 구현까지만.
- 라벨 불일치(EXIT vs REDUCE)가 실제 운영에서 얼마나 자주 나는지, 그
  불일치가 sizing에 실질적으로 어떤 영향을 주는지 — 실측 전에는 확인
  불가.
- `risk_opinion="reduce"`의 0% disagreement가 오늘 하루(72건) 표본
  기준이라, 여러 날에 걸쳐서도 유지되는지 추가 확인 필요.

## 10. 다음 단계

`HELD_POSITION_REDUCE_SKIP_SHADOW_ENABLED=true`로 운영에서 활성화하고,
몇 주간 `shadow_held_position_reduce_skip`의 `agreement`/`agreement_
execution_meaning` 분포를 축적한 뒤, 그 결과를 근거로 이 하위 구간의
실제 skip 전환 여부를 별도 턴에서 재검토한다. 활성화 자체는 이번 PR의
범위가 아니며, 별도 운영 반영 결정이 필요하다.
