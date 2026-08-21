# held_position 기본 request.side를 SELL로 정합화(1단계)

## 배경

앞선 read-only 실측 조사(별도 세션, 코드 변경 없음)에서, held_position
`provider_queue_timeout` 건의 `trade_decisions.side='buy'`가 Gemini/FDC
의 매수 의견이 아니라, `run_decision_loop.py`의 파이프라인 초기
placeholder(`SubmitOrderRequest(side=OrderSide.BUY, ...)`, 모든
source_type에 무조건 적용)가 `decision_factory.py::resolve_order_
side(composer_output.side="", request.side)`의 fallback 경로를 통해
그대로 새어나온 표시 아티팩트임을 코드로 확정했다. 이번 작업은 그
조사에서 제시한 2단계 개선안 중 **1단계(held_position 기본
request.side를 SELL로 변경)** 만 구현한다.

## 사전 확인 결과

1. **request 생성 지점**: `scripts/run_decision_loop.py`의
   `_run_one_cycle()` 내부, 1989행 `SubmitOrderRequest(...)` 생성부
   (기존 1996행 `side=OrderSide.BUY`). 이 함수는 core/held_position/
   event_overlay/market_overlay 등 **모든 source_type의 심볼**이
   거치는 유일한 실제 결정 파이프라인 경로다(다른 `SubmitOrderRequest`
   생성 지점(1344행)은 `if item.source_type != "core": continue`로
   core 전용 사전 계산(prepass)이며 이번 변경과 무관).
2. **`source_type` 접근 가능 여부**: `_run_one_cycle(source_type:
   str = "core", ...)`는 함수 시그니처의 일반 매개변수로, request 생성
   시점에 이미 항상 값이 확정돼 있다(확인 완료).
3. **`decision_factory.py`의 두 소비 경로**: `build_trade_decision_
   entity()` 105행(`holding_profile_policy` 입력 `side=composer_
   output.side or request.side`)과 131행(최종
   `TradeDecisionEntity.side=resolve_order_side(composer_output.side,
   request.side)`) 양쪽 모두 `request.side` fallback을 그대로
   소비함을 코드로 재확인.
4. **held_position 기존 정책 유지**: `final_decision_composer.py`의
   held_position 전용 프롬프트 제약(`decision_type` 허용 목록을
   REDUCE/EXIT/HOLD/WATCH로 제한, APPROVE/BUY 명시적 금지)은 이번
   변경으로 전혀 건드리지 않았다 — 이번 수정은 FDC의 판단 자체가
   아니라 FDC가 판단하지 못했을 때(fallback)의 표시값만 다룬다.
5. **`request.side=SELL` 기본값이 공통 적용되는 범위**: HOLD/WATCH,
   outer/permit timeout fallback, parse/error fallback, 정상 FDC가
   빈 `side`를 반환하는 모든 경우에 공통 적용됨을 코드로 확인 —
   `resolve_order_side()`는 `composer_output.side`가 falsy(빈 문자열/
   None)인 모든 경우에 예외 없이 `request.side`로 폴백하며, 이 분기
   로직은 fallback의 "원인"(queue timeout/state_file_error/outer
   timeout/parse_error/정상 FDC의 HOLD 판단 등)을 구분하지 않는다.

## 구현 정책

`scripts/run_decision_loop.py`의 `_run_one_cycle()` 내부, request 생성
직전에 아래 한 줄을 추가하고 `side=OrderSide.BUY` 리터럴을
`side=default_side`로 교체했다:

```python
default_side = (
    OrderSide.SELL if source_type == "held_position" else OrderSide.BUY
)
```

`core`/`event_overlay`/`market_overlay`는 기존과 동일하게 `BUY`를
그대로 유지한다. `_resolve_order_type_and_price(side="buy", ...)`
호출(1985행 부근)은 건드리지 않았다 — 이 함수는 `side`/`decision_
type`/`default_price` 인자를 전부 향후 확장을 위해 예약(reserved)만
해두고 실제로는 사용하지 않는다(`_ = side, decision_type,
default_price`, 항상 `(OrderType.MARKET, None)` 반환)는 것을 코드로
확인했으므로 변경 범위에서 제외했다.

## source_type별 기본 side 전후 표

| source_type | 변경 전 | 변경 후 |
|---|---|---|
| `core` | BUY | BUY(변경 없음) |
| `held_position` | BUY | **SELL** |
| `event_overlay` | BUY | BUY(변경 없음) |
| `market_overlay` | BUY | BUY(변경 없음) |
| (core 전용 prepass, 1344행) | BUY | BUY(변경 없음, 애초에 core만 실행) |

## held_position fallback에서 side=SELL이 적용되는 범위

`composer_output.side`가 빈 값(`""`)인 **모든** 경우 — 원인과 무관하게
동일하게 적용된다:
- `provider_queue_timeout`(permit 거부, HTTP 미발생)
- `provider_limiter_unavailable`(상태 파일 오류, HTTP 미발생)
- `provider_timeout`(outer/FDC per-agent timeout)
- `provider_parse_error`/`provider_error`(HTTP는 발생했으나 파싱/기타
  오류)
- 정상 FDC 응답이지만 `decision_type=HOLD`/`WATCH`이고 `side`를 채우지
  않은 경우(모델이 non-actionable 판단 시 `side`를 비워두는 경우)

FDC가 명시적으로 `side="SELL"`을 반환하는 정상 REDUCE/EXIT 경로는
`resolve_order_side()`가 그 값을 그대로 우선 사용하므로 이번 변경과
무관하게 기존과 동일하다(`translation_test.py::
test_explicit_sell_from_fdc_wins_over_sell_fallback`로 검증).

## 주문 정책이 바뀌지 않았다는 코드 및 테스트 근거

- **EV gate/sell guard/sizing**: 이번 diff에 `expected_value_gate.py`,
  sell guard 관련 파일, `translation.py`(함수 자체), `decision_
  factory.py`의 `resolve_order_side()` 정의가 전혀 포함되지 않았다
  (변경 파일은 `run_decision_loop.py`와 테스트 파일뿐 — `git diff`로
  확인 가능).
- **`derive_holding_profile_policy()` 무영향**: `holding_profile_
  policy.py`의 `risk_reduction_only` 판정 조건은
  `normalized_side == SELL or normalized_decision_type in {SELL,EXIT,
  REDUCE} or normalized_source_type == "held_position"`의 **OR**
  조건이다 — `normalized_source_type == "held_position"` branch가
  이미 단독으로 `risk_reduction_only`를 강제하므로, `side`가
  `""`/`BUY`/`SELL` 무엇이든 held_position이면 결과가 항상 동일하다.
  이를 `test_held_position_hold_result_unaffected_by_default_side_
  change`(신규)로 side 3가지 값 모두 동일한 `holding_profile`/
  `earliest_reentry_at`/`reentry_cooldown_until`을 반환함을 직접
  검증했다.
- **HOLD/WATCH는 주문으로 이어지지 않음**: `decision_type=HOLD`는
  `execution_sizing`의 `non_actionable_decision` 스킵 경로로 빠져
  `resolved_quantity=0`이 되므로(기존 로직, 이번 변경 무관) `side`
  컬럼 값과 무관하게 주문이 생성되지 않는다 — 이전 read-only 조사에서
  이미 실측 32건 전부 `order_request` 미생성으로 확인된 사실과 부합.

## 변경 파일과 테스트 결과

| 파일 | 변경 내용 |
|---|---|
| `scripts/run_decision_loop.py` | held_position 기본 `request.side`를 `SELL`로 변경(1줄 조건문 + 1개 리터럴 교체) |
| `tests/scripts/test_run_decision_loop.py` | `test_held_position_default_request_side_is_sell`, `test_core_default_request_side_is_buy`, `test_held_position_fdc_fallback_empty_side_resolves_to_sell` 3건 신설 |
| `tests/services/translation_test.py` | `test_empty_string_fallback_to_sell`, `test_explicit_sell_from_fdc_wins_over_sell_fallback` 2건 신설 |
| `tests/services/test_holding_profile_policy.py` | `test_held_position_hold_result_unaffected_by_default_side_change` 1건 신설 |

검증 결과:
- `bash scripts/harness/run.sh test-file tests/scripts/test_run_decision_loop.py` — 139 passed(신규 3건 포함, 무관 회귀 없음)
- `bash scripts/harness/run.sh test-file tests/services/translation_test.py` — 28 passed(신규 2건 포함)
- `bash scripts/harness/run.sh test-file tests/services/test_holding_profile_policy.py` — 3 passed(신규 1건 포함)
- `bash scripts/harness/run.sh accept script-file scripts/run_decision_loop.py` — PASS
- `bash scripts/harness/run.sh accept backend-file src/agent_trading/services/decision_factory.py` — PASS(무수정 파일이지만 소비 경로 회귀 확인 차원에서 실행)
- `bash scripts/harness/run.sh accept backend-runtime` / `accept architecture`(violation=0) / `accept no-bypass`(hard_bypass_count=0) / `accept style` — 전부 PASS
- 명시적으로 실행하지 않음(요청에 따라 스코프 밖): 전체 pytest, smoke/integration/broker/KIS 테스트, 외부 API 호출, DB write, 컨테이너 재기동.

## 미검증 운영 가정

- 이번 변경은 **2단계(HOLD/WATCH에서 최종 side를 빈 값으로 만드는
  것, UI 비표시 처리)** 를 포함하지 않는다 — 즉 배포 후에도
  `decision_json.side`는 여전히 빈 값이고 `trade_decisions.side`
  컬럼만 BUY→SELL로 바뀐다. 두 값의 불일치 자체는 이번 변경으로
  해소되지 않으며, "실제로는 방향성이 없는 HOLD/WATCH 결정에 side
  컬럼이 채워져 있다"는 근본적인 표시 모호성은 남아있다(이번 변경은
  그 값을 최소한 실제 문맥(이미 보유 중 → 매도 방향)과 일치시키는
  선에서만 개선).
- `holding_profile_policy` 외에 `request.side`를 참조하는 다른 다운
  스트림 로직이 더 있을 가능성(이번 조사에서 `decision_factory.py`의
  두 지점만 확인했으며 grep 기반 전수 조사는 아니었음)은 완전히
  배제하지 않았다.
- 실제 운영 배포 후 held_position 사이클에서 REDUCE/EXIT/HOLD/WATCH
  각각의 `trade_decisions.side` 분포가 예상대로 나오는지는 배포 후
  실측이 필요하다.

## 배포 후 확인 항목

```sql
-- held_position + FDC fallback(HTTP 미발생 계열)의 trade_decisions.side 분포
SELECT
  ar.structured_output_json->'__provider_observability__'->>'provider_final_status' AS final_status,
  td.side,
  count(*) AS n
FROM trade_decisions td
JOIN agent_runs ar ON ar.agent_run_id = td.agent_run_id
WHERE td.created_at > now() - interval '2 hours'
  AND td.source_type = 'held_position'
  AND (td.decision_json->'ai_call_path'->>'fdc_skipped') = 'false'
GROUP BY 1, 2
ORDER BY n DESC;

-- decision_json.side와 최종 side 불일치 분포(2단계 필요성 재확인용)
SELECT
  td.side AS td_side,
  COALESCE(NULLIF(td.decision_json->>'side',''),'(empty)') AS dj_side,
  count(*) AS n
FROM trade_decisions td
WHERE td.created_at > now() - interval '2 hours'
  AND td.source_type = 'held_position'
GROUP BY 1, 2
ORDER BY n DESC;

-- HOLD/WATCH에서 order_request=0 유지 확인
SELECT td.decision_type, count(*) AS n,
       count(*) FILTER (WHERE orq.order_request_id IS NOT NULL) AS with_order_n
FROM trade_decisions td
LEFT JOIN order_requests orq ON orq.trade_decision_id = td.trade_decision_id
WHERE td.created_at > now() - interval '2 hours'
  AND td.source_type = 'held_position'
  AND td.decision_type IN ('hold', 'watch')
GROUP BY 1;

-- REDUCE/EXIT의 SELL 경로 변화 여부(회귀 확인)
SELECT td.decision_type, td.side, count(*) AS n
FROM trade_decisions td
WHERE td.created_at > now() - interval '2 hours'
  AND td.source_type = 'held_position'
  AND td.decision_type IN ('reduce', 'exit')
GROUP BY 1, 2;
```

확인할 항목(요청사항 그대로): (1) held_position + FDC fallback 건의
`trade_decisions.side`가 이제 `sell`로 저장되는지. (2) `decision_json.
side`와 최종 side 불일치 분포 — 여전히 `dj_side='(empty)'`이면서
`td_side='sell'`인 조합이 다수 나오는 것이 정상(2단계 미구현 상태의
기대값). (3) HOLD/WATCH에서 `order_request` 생성 건수가 계속 0인지
(회귀 없음 확인). (4) REDUCE/EXIT 건의 `side`가 여전히 `sell`로
일관되는지(회귀 없음 확인, FDC 명시값이 fallback보다 우선하므로
이번 변경과 무관하게 동일해야 함).
