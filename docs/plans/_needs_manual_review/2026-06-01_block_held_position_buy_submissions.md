# held_position BUY 제출 차단

## 배경

`held_position` lane은 원래 보유 종목의 위험 축소 SELL을 submit까지 보내기 위해 완화한 경로다.

하지만 실제 AI 결정 결과를 보기 전에는 `source_type="held_position"`만으로 lane이 열리기 때문에, 보유 종목에 대해 AI가 `APPROVE/BUY`를 내리는 경우에도 submit 후보로 흘러갈 수 있었다.

이는 최근 과도한 BUY 주문과 직접 연결될 수 있는 위험한 경로다.

## 핵심 문제

현재 구조에서:

- `held_position`은 universe 출처일 뿐
- AI는 같은 보유 종목에 대해서도 `APPROVE/BUY`를 낼 수 있음
- scheduler 쪽 lane 분리만으로는 이 BUY를 완전히 막을 수 없음

즉, `held_position` 특례는 "위험 축소 SELL"에만 한정되어야 하고, BUY는 최종 번역 단계에서 차단하는 편이 가장 안전하다.

## 수정 내용

`src/agent_trading/services/translation.py`의
`build_submit_order_request_from_decision()`에 아래 규칙을 추가했다.

- `intent.request.metadata["source_type"] == "held_position"`
- 그리고 최종 `intent.request.side != SELL`

위 두 조건이 동시에 성립하면 `SubmitOrderRequest`를 만들지 않고 `None`을 반환한다.

즉:

- `held_position + BUY` → 제출 차단
- `held_position + SELL` → 기존대로 제출 가능

## 왜 translation 단계에서 막았나

translation은 실제 브로커 제출 request를 생성하는 마지막 순수 함수 경계다.

여기서 차단하면:

- scheduler lane 구조와 무관하게 최종 BUY submit을 봉쇄할 수 있고
- DB/브로커 호출 이전에 안전하게 종료되며
- HOLD/WATCH skip과 동일한 패턴으로 유지된다.

## 검증

실행:

`pytest -q tests/services/test_decision_submit_pipeline.py tests/services/test_submit_order_from_decision.py -k "held_position or build_submit_order_request_from_decision or approves"`

결과:

- `4 passed`

추가 검증:

- `held_position + BUY` → `build_submit_order_request_from_decision(...) is None`
- `held_position + SELL` → 정상 request 생성 유지

간단한 실행 확인에서도 `held_position + BUY` 입력은 실제로 `None`을 반환했다.
