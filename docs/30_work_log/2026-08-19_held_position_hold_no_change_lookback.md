# `held_position` pre-AI 스킵(HOLD_NO_CHANGE) lookback 불일치 수정(2026-08-19 KST)

## 1. 배경

`provider_rate_limit`(429)를 실질적으로 줄이는 방법을 검토하는 턴에서,
C2(#298) 이후 core-lane FDC 호출은 68.75% 스킵률까지 올라간 반면
held_position lane은 **오늘(2026-08-19) 실제 FDC 호출 306건 중
228건(74.5%)**, `provider_rate_limit` 29건 중 21건(72.4%)을 차지함을
확인했다. 레인별 호출당 실패율은 core/held_position 모두 ~9.2~9.3%로
거의 동일 — held_position이 유독 더 잘 실패하는 게 아니라 유독 더 많이
호출되고 있을 뿐이었다.

held_position 전용 pre-AI 스킵(`PipelineStopReason.HELD_POSITION_
RECENT_HOLD_NO_CHANGE`, `pre_ai_gate.py::evaluate_held_position_skip_
reason()`)이 이미 존재해 AI 파이프라인 전체(EI/AR/AC/FDC)를 사전에
스킵할 수 있는데도, `guardrail_evaluations`(스킵이 실제로 발동했을
때만 기록되는 테이블 — `run_decision_loop.py:1820` 확인)에 오늘 0건,
어제(2026-08-18)도 7건뿐이었다.

## 2. 최초 가설과 반증

이전 턴에서 세운 가설: `evaluate_held_position_skip_reason()`이
`list_by_symbol(..., include_seeded_news=True)`로 최근 이벤트를 조회할
때, 매 사이클 새로 생성되는 것처럼 보이는 시장 전반 뉴스(예:
`kis_disclosure` 소스의 코스피/코스닥 순매수·매도 상위 종목 뉴스)가
`HELD_POSITION_SKIP_EVENT_LOOKBACK`(30분) 안에 항상 걸려 "최근 이벤트
없음" 조건을 영구히 막고 있을 것이라 추정했다.

**이번 턴에서 직접 재현·반증**: 오늘 held_position 4개 종목(196170,
181710, 280360, 192820) 각각의 실제 decision 사이클 시각(합 12건×4=총
48개 시점)에서, 그 사이클 시작 시각을 기준으로 `published_at >= 사이클
시각 - 30분` 조건을 직접 재실행한 결과 — **196170의 12개 사이클 전부
`recent_events(30분)=0건`**이었다(다른 3개 종목도 동일 사이클 간격
패턴을 보여 결과는 같을 것으로 추정). 즉 "최근 이벤트 없음" 조건은
매 사이클 정상적으로 성립하고 있었다 — seeded news 가설은 **코드/DB
근거로 반증**됐다.

## 3. 확정된 실제 원인

`evaluate_held_position_skip_reason()` 안에서, "직전 판단이 hold였는가"를
조회하는 다음 코드가 문제였다(수정 전):

```python
cutoff = current_utc - HELD_POSITION_SKIP_HOLD_TTL   # 20분
latest_decision_type, latest_decision_created_at, _, _, _ = (
    await _get_latest_recent_held_decision(
        repos, symbol=symbol, cutoff=cutoff, db_conn=db_conn, side="buy",
    )
)
...
if latest_decision_type == "hold" and not recent_orders:
    return PipelineStopReason.HELD_POSITION_RECENT_HOLD_NO_CHANGE.value, details
```

`HELD_POSITION_SKIP_HOLD_TTL = 20분`이 "직전 판단을 찾는 lookback"으로
그대로 재사용됐다. 그런데 오늘 held_position 4개 종목의 실제
`trade_decisions.created_at` 간격을 전부 확인한 결과:

| symbol | 관측된 사이클 간격(전부) |
|---|---|
| 196170 | 31~35분(12개 간격 전부) |
| 181710 | 31~35분(11개 간격 전부) |
| 280360 | 31~35분(11개 간격 전부) |
| 192820 | 31~35분(11개 간격 전부) |

**예외 없이 전부 20분보다 길다.** 이는 운영 설정
`OPS_SCHEDULER_DECISION_INTERVAL_SECONDS=1800`(30분, `run_ops_scheduler.py`
로그 `Decision interval: 1800s`로 확인)에 사이클 실행 오버헤드(~1~5분)가
더해진 결과다. 20분 lookback으로는 직전 사이클의 판단을 원천적으로
절대 찾을 수 없으므로, `_get_latest_recent_held_decision()`이 항상
`(None, None, None, None, None)`을 반환했고, 그 결과
`latest_decision_type`이 항상 `None`이라 `if latest_decision_type ==
"hold"` 조건이 코드가 존재한 이래 사실상 단 한 번도 성립할 수 없었다.

## 4. 수정 내용

`pre_ai_gate.py`에 이 판정 **전용** 새 상수를 도입하고, 그 상수를 쓰는
호출 지점을 딱 하나만 바꿨다.

```python
HELD_POSITION_SKIP_HOLD_TTL = timedelta(minutes=20)              # 무변경
HELD_POSITION_SKIP_HOLD_NO_CHANGE_LOOKBACK = timedelta(minutes=40)  # 신규
```

```python
cutoff = current_utc - HELD_POSITION_SKIP_HOLD_TTL   # buy/sell reverse-trade용, 무변경
hold_no_change_cutoff = current_utc - HELD_POSITION_SKIP_HOLD_NO_CHANGE_LOOKBACK  # 신규
latest_decision_type, latest_decision_created_at, _, _, _ = (
    await _get_latest_recent_held_decision(
        repos, symbol=symbol, cutoff=hold_no_change_cutoff, db_conn=db_conn, side="buy",
    )
)
```

같은 함수 안의 나머지 두 `_get_latest_recent_held_decision()` 호출
(`latest_buy_decision_type`/`latest_sell_decision_type`, buy/sell
reverse-trade 쿨다운 판정용)은 여전히 기존 `cutoff`(20분,
`HELD_POSITION_SKIP_HOLD_TTL`)를 그대로 쓴다 — **한 함수 안에서 딱
하나의 조회에만 영향을 주도록 의도적으로 좁혔다.**

40분이라는 값은 오늘 실측된 최대 간격(34분 43초)에 여유를 둔 것이며,
`OPS_SCHEDULER_DECISION_INTERVAL_SECONDS`가 크게 바뀌면 재검토가
필요함을 코드 주석과 이 문서에 남겨 둔다.

## 5. 왜 정책 변경이 아닌가

- **이벤트 판정 로직(`HELD_POSITION_SKIP_EVENT_LOOKBACK`, seeded news
  포함 여부) 자체는 전혀 건드리지 않았다** — 애초에 이 부분은 문제가
  아니었음이 §2에서 반증됐다.
- 스킵의 조건식 자체("최근 이벤트/주문 없음 + 직전 판단이 hold")은
  무변화 — "직전 판단"을 찾는 시간 창만 실제 운영 사이클 간격에 맞게
  넓혔다. 이는 "차단을 완화"하는 것이 아니라 애초에 의도된 대로 작동
  하도록 만드는 정합성 수정이다.
- buy/sell reverse-trade 쿨다운(`HELD_POSITION_RECENT_BUY_SELL_
  COOLDOWN`, `HELD_POSITION_RECENT_RISK_SELL_COOLDOWN`)은 여전히 20분
  기준 그대로 — 이 두 정책은 이번 수정과 무관하다.
- `decision_type`이 hold가 아닌 경우(reduce/exit/watch)는 이 판정
  자체가 적용되지 않는다 — 테스트로 재확인.

## 6. 변경 파일

- `src/agent_trading/services/pre_ai_gate.py` — 신규 상수 1개, 호출
  지점 1곳 변경.
- `tests/services/test_pre_ai_gate.py` — 신규 파일, 5개 테스트.

`decision_orchestrator.py`, FDC 프롬프트, `translation.py`,
`expected_value_gate.py`는 전혀 건드리지 않았다.

## 7. 테스트 결과

| 명령 | 결과 |
|------|------|
| `test-file tests/services/test_pre_ai_gate.py` | PASS (5/5, 신규) |
| `test-file tests/scripts/test_run_decision_loop.py` | PASS (130/130, 회귀 없음) |
| `accept backend-file src/agent_trading/services/pre_ai_gate.py` | PASS |
| `accept backend-runtime` | PASS |
| `accept architecture` | PASS |
| `accept no-bypass` | PASS(review_bypass만, `AsyncMock`/`monkeypatch` 사용) |
| `accept style` | PASS |
| `accept docs` | (본 문서 작성 후 실행) |

신규 테스트가 검증하는 것:

1. 32분 전 hold 판단 + 최근 이벤트/주문 없음 → 새 lookback(40분)에서
   스킵이 실제로 발동함(이번 수정의 핵심 효과).
2. 같은 시나리오에서 lookback을 옛 20분으로 되돌리면(monkeypatch)
   스킵이 발동하지 않음 — 버그가 실제로 존재했음을 대조 증명.
3. 45분 전 판단은 새 lookback(40분)도 벗어나 여전히 스킵되지 않음 —
   TTL을 무한정 늘린 게 아님을 확인.
4. 최근 이벤트가 하나라도 있으면 lookback 확대와 무관하게 여전히
   스킵하지 않음 — 이벤트 판정 로직 무변경 확인.
5. decision_type이 reduce면 이 판정과 무관함(hold 전용 확인).

## 8. 미검증 사항(운영 실측 필요)

- 배포 후 `guardrail_evaluations`에 `held_position_recent_hold_no_
  change`가 실제로 기록되기 시작하는지.
- held_position lane의 실제 FDC 호출 수/`provider_rate_limit` 건수가
  이 수정만으로 얼마나 감소하는지 — 사이클 간격이 이미 30분+α이므로
  스킵 발동은 "직전 사이클도 hold였던 종목"에 한정된다. 오늘 held_
  position hold 비율(95/228=41.7%)의 일부만 해당될 것으로 예상되며,
  정확한 감소폭은 배포 후 실측이 필요하다.
- `OPS_SCHEDULER_DECISION_INTERVAL_SECONDS`가 향후 변경되면 40분
  lookback도 함께 재검토 필요(코드 주석에 명시).
- 다른 3개 held_position 종목(181710/280360/192820)에 대해서도
  196170과 동일하게 12개 전부 `recent_events=0`이었는지는 사이클
  간격 패턴(동일 30분+α)으로 미루어 추정했을 뿐, 196170만큼
  개별적으로 전수 재현하지는 않았다.
