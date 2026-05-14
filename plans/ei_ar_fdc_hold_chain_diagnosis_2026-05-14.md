# EI/AR/FDC HOLD 판단 체인 진단 (2026-05-14)

## 1. 결론

2026-05-14 near-real 운영에서 주문이 발생하지 않은 직접 원인은 FDC가 일관되게 `HOLD`를 반환했기 때문이다. DB에 저장된 최근 decision cycle을 확인한 결과, 이는 임의 실패가 아니라 아래 두 가지 입력 결핍의 조합이다.

1. `external_events`에 `symbol='005930'`로 매핑된 최근 이벤트가 0건이다.
2. AI agent request에 대상 `symbol/market`이 명시되지 않아, 이벤트가 없는 cycle에서 EI/AR/FDC prompt와 structured output이 `UNKNOWN`으로 흐른다.

따라서 AR이 `allow`를 반환해도 FDC는 `no_events`, `neutral_bias`, `conviction=0` 근거로 `HOLD`를 선택하는 것이 현재 입력 기준에서는 정상적인 보수 판단이다.

## 2. DB 관찰 결과

최근 `trade_decisions` 10건은 모두 아래 패턴을 보였다.

| 항목 | 관찰 |
|---|---|
| `symbol` | `005930` |
| `decision_type` | `hold` |
| `risk_opinion` | `allow` |
| `event_bias` | `neutral` |
| 주요 reason_codes | `no_events`, `neutral_bias`, 일부 `low_risk_score` |
| FDC confidence | 대체로 `0.5` |
| FDC conviction | `0` |

최근 `agent_runs`에서 EI output은 반복적으로 다음 구조였다.

```json
{
  "symbol": "UNKNOWN",
  "issuer_code": "UNKNOWN",
  "events": [],
  "aggregate_view": {
    "overall_bias": "neutral",
    "event_conflict": false,
    "top_reason_codes": []
  }
}
```

`external_events` 상태는 다음과 같다.

| 항목 | 값 |
|---|---:|
| 전체 external_events | 802건 |
| `symbol IS NOT NULL` | 518건 |
| `symbol='005930'` | 0건 |
| 최근 72시간 events | 702건 |
| 최근 72시간 `symbol='005930'` | 0건 |

즉 삼성전자 단일 종목으로만 판단하는 현재 loop에서는 EI가 판단 근거를 찾을 수 없다.

## 3. 수정한 코드

### 3.1 AgentExecutionRequest에 대상 symbol/market 추가

`AgentExecutionRequest`에 `symbol`, `market` 필드를 추가했다. 이벤트가 없는 경우에도 EI/AR/FDC prompt가 평가 대상 종목을 명확히 알 수 있게 하기 위한 변경이다.

적용 파일:

- `src/agent_trading/services/ai_agents/base.py`
- `src/agent_trading/services/ai_agents/event_interpretation.py`
- `src/agent_trading/services/ai_agents/ai_risk.py`
- `src/agent_trading/services/ai_agents/final_decision_composer.py`
- `src/agent_trading/services/decision_orchestrator.py`

### 3.2 Agent output symbol fallback

Agent가 `UNKNOWN`, 빈 문자열, `N/A` 등을 반환하면 orchestrator가 request의 실제 symbol로 보정한다. 이 보정은 저장되는 `agent_runs.structured_output_json`에도 반영된다.

### 3.3 DecisionContext snapshot anchoring

Decision context 생성 시 최신 position/cash snapshot ID를 best-effort로 저장하도록 했다. 기존 assemble 경로는 최신 snapshot fallback을 수행했지만, DB에 생성된 `decision_contexts`에는 snapshot ID가 비어 있어 사후 감사가 어렵다.

## 4. 남은 구조적 문제

이번 수정은 `UNKNOWN` 및 snapshot auditability 문제를 해결하지만, `005930`에 이벤트가 없는 문제 자체를 해결하지는 않는다.

남은 P0 작업은 Trading Universe 기반 decision loop 전환이다. `external_events`에는 최근 72시간 기준으로 이벤트가 있는 다른 KRX symbol이 다수 존재하므로, 단일 005930 판단이 아니라 이벤트가 존재하는 watchlist/universe를 순회해야 EI가 유의미하게 동작한다.

## 5. 다음 작업

1. `TRADING_UNIVERSE_SYMBOLS` 또는 설정 기반 KRX watchlist를 도입한다.
2. `run_paper_decision_loop.py`가 universe symbol을 순회하도록 변경한다.
3. 전체 계좌 기준 daily submit budget 1회 제한은 유지한다.
4. KRX instrument master가 부족하므로, submit 가능한 종목은 `instruments`에 존재하는 symbol로 제한하거나 instrument master 적재 P0/P1과 연결한다.

