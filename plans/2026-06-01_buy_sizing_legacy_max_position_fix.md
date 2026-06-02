# 2026-06-01 매수 수량 1주 고정 재발 원인 및 수정

## 배경

운영 중 `004990` MARKET BUY 주문이 계속 1주로 제출되는 현상이 확인되었다.
직전 수정으로 MARKET BUY의 현재가 조회 실패 시 1주 fallback은 금지했지만,
이번 건은 현재가 조회 실패가 아니었다.

## 확인 결과

- 대상 주문: `004990` BUY MARKET 1주
- 주문 시각: 2026-06-01 10:07 KST 부근
- KIS 현재가 조회: 성공
- sizing reference price: 25,400원
- 주문가능금액: 9,014,583원
- 총자산/NAV fallback: 29,880,403원
- 적용 제약: `position_concentration`

계산상 20% 현금 배분 기준 수량은 다음과 같다.

```text
9,014,583원 * 20% / 25,400원 = 70주
```

그런데 기존 코드는 `config_json.max_position_size = "0.1"`을 그대로
`max_single_position_pct = 0.1`로 전달했다. sizing engine은 이 값을
퍼센트로 해석하므로 실제 제한은 10%가 아니라 0.1%가 된다.

```text
잘못된 기존 해석: 29,880,403원 * 0.1% / 25,400원 = 1주
정상 의도 해석: 29,880,403원 * 10% / 25,400원 = 117주
```

따라서 1주 주문의 직접 원인은 quote 실패가 아니라 legacy 설정값
`max_position_size=0.1`의 단위 해석 오류였다.

## 수정 내용

`ExecutionService._build_sizing_inputs()`에서 설정 해석을 다음과 같이 변경했다.

- `risk.max_single_position_pct`가 있으면 기존처럼 명시적 퍼센트로 사용한다.
- `risk.max_single_position_pct`가 없고 legacy `max_position_size`만 있으면 fallback으로 사용한다.
- legacy `max_position_size`가 `0 < value <= 1`이면 비율로 간주해 `value * 100`으로 퍼센트 변환한다.
- 예: `0.1 -> 10.0`, `0.05 -> 5.0`
- legacy 값이 `10`처럼 1보다 크면 기존처럼 10%로 유지한다.

## 변경 파일

- `src/agent_trading/services/execution_service.py`
- `tests/services/test_decision_orchestrator.py`

## 회귀 테스트

추가한 테스트:

- `test_legacy_max_position_size_ratio_is_normalized_to_percent`
  - 운영에서 관측된 004990 조건을 재현한다.
  - `max_position_size="0.1"`을 10%로 정규화한다.
  - 최종 수량이 1주가 아니라 70주인지 검증한다.
- `test_nested_max_single_position_pct_keeps_percent_semantics`
  - 명시적 `risk.max_single_position_pct`는 기존처럼 퍼센트 의미를 유지하는지 검증한다.

실행한 테스트:

```bash
pytest -q tests/services/test_decision_orchestrator.py::TestBuildSizingInputs -q
pytest -q tests/services/test_sizing_engine.py tests/services/test_decision_submit_pipeline.py -q
```

결과:

- `TestBuildSizingInputs`: 4개 통과
- sizing/decision submit 관련 테스트: 통과

## 운영 반영

이 변경은 앱 프로세스 코드 변경이므로 운영 루프에 반영하려면 `app` 컨테이너 재빌드 및 재시작이 필요하다.
아래 명령으로 반영을 완료했다.

```bash
docker compose build app
docker compose up -d app
docker compose restart ops-scheduler
```

컨테이너 내부 검증 결과:

```text
max_single_position_pct=10.0
sizing_qty=70
applied_constraints=()
```

`ops-scheduler` 재시작 후 확인:

- 컨테이너 상태: healthy
- `ExecutionService._build_sizing_inputs()`에 `legacy ratio` 정규화 코드 로드 확인
- scheduler advisory lock 재획득 확인

## 기대 효과

- MARKET BUY 현재가 조회가 성공한 경우 `max_position_size=0.1` 때문에 1주로 잘리는 현상이 제거된다.
- 현재 004990과 동일한 조건에서는 약 70주 수준으로 sizing 된다.
- 명시적 `risk.max_single_position_pct` 설정의 기존 의미는 유지된다.

## 남은 확인

- 재시작 후 다음 BUY 주문의 `sizing_qty` 로그가 1주로 고정되지 않는지 확인한다.
- 실제 주문 수량은 현금, 보유 포지션, `max_order_value`, 최소 현금 버퍼, lot size 등 다른 제약으로 다시 줄어들 수 있으므로 다음 체결 전후 로그를 추가 확인한다.
