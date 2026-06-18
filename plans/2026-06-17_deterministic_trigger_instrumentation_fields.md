# 2026-06-17 deterministic trigger 계측 필드 1차 추가

## 배경

- 다음 단계에서 `BUY candidate projection`을 `eligibility + ranking` 구조로 바꾸기 전에,
  먼저 현재 deterministic trigger가 어떤 이유로 후보를 만들거나 만들지 못했는지
  분해 관측할 수 있어야 한다.
- 특히 최근 이슈는
  - `WATCH` 급증
  - `BUY_CANDIDATE` 부족
  - AI override 이전의 deterministic 단계 병목
  을 구분해서 봐야 하는 상태다.

## 이번 단계의 원칙

1. candidate projection 동작은 바꾸지 않는다.
2. `deterministic_trigger` payload에
   `coverage / eligibility / ranking` 계측 필드만 추가한다.
3. 이후 실측 결과를 바탕으로
   실제 `BUY top-k projection` 변경 여부를 결정한다.

## 반영 내용

### 1. trigger assessment 확장

- [`src/agent_trading/services/deterministic_trigger_engine.py`](../src/agent_trading/services/deterministic_trigger_engine.py)
  의 `DeterministicTriggerAssessment`에 아래 필드 추가
  - `eligibility_passed`
  - `eligibility_reasons`
  - `coverage_score`
  - `ranking_score`
  - `ranking_percentile`
  - `ranking_bucket`
  - `candidate_mode`

### 2. coverage 계측

- `_build_feature_coverage_score()` 추가
- 현재는 아래 입력 존재 여부를 단순 coverage로 본다.
  - signal snapshot
  - overall score
  - fast score
  - slow score
  - market regime
  - strategy selection
  - portfolio allocation

### 3. eligibility 계측

- `_assess_buy_eligibility()` 추가
  - `held_position` BUY 차단
  - allocation budget 차단
  - coverage 부족 차단
  - `risk_off + bearish_trend` 차단
  - 음수 signal floor 차단
- `_assess_exit_eligibility()` 추가
  - 보유수량 부재 차단
  - coverage 부족 차단
  - exit score 바닥 미달 차단

중요:

- 이 단계에서 eligibility는 **계측용**이다.
- 현재 candidate projection 로직을 아직 직접 바꾸지는 않는다.

### 4. ranking 계측

- `_build_buy_ranking_score()` 추가
- `_build_exit_ranking_score()` 추가
- 현재는 단순 1차 근사치로
  `entry_score` 또는 `exit_score`를 중심으로
  coverage / regime / allocation / concentration 보정을 얹는다.

중요:

- 현재 `ranking_score`도 **계측용**이다.
- 아직 batch top-k selection에는 사용하지 않는다.

### 5. decision_json 저장

- [`src/agent_trading/services/decision_factory.py`](../src/agent_trading/services/decision_factory.py)
  에서 `decision_json.deterministic_trigger`에 새 필드 직렬화 추가
- 이후 운영 실측 시 `trade_decisions` read-path만으로도
  eligibility/ranking 분해 관측이 가능해진다.

## 검증

- `tests/services/test_deterministic_trigger_engine.py`
  - bullish core BUY 케이스에서 계측 필드 존재 확인
  - core WATCH 케이스에서 eligibility/ranking 존재 확인
  - bearish held_position SELL 케이스에서 exit eligibility 확인
  - allocation budget 0일 때 BUY eligibility 실패 reason 확인
- `tests/services/test_decision_factory.py`
  - `decision_json.deterministic_trigger`에 새 필드가 저장되는지 확인

실행 결과:

- `pytest -q tests/services/test_deterministic_trigger_engine.py tests/services/test_decision_factory.py`
- `6 passed`

## 다음 단계

1. 최근 실데이터에서
   - `eligibility_pass_rate`
   - `eligibility fail reason 분포`
   - `ranking_score 분포`
   - `WATCH 중 eligibility_passed=true 비율`
   를 먼저 측정
2. 그 다음
   `BUY = eligible set 내부 top-k`
   구조로 candidate projection 변경 여부 판단
