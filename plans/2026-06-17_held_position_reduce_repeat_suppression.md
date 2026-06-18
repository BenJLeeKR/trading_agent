# 2026-06-17 held_position 반복 REDUCE/EXIT 판단 suppression 1차

## 배경

- 2026-06-17 장중 동일 종목에 대해 `REDUCE` 판단과 매도 주문이 짧은 간격으로 반복 생성되었다.
- 앞선 수정으로 `1주 매도` 왜곡과 `trade_decisions.quantity` placeholder 문제는 줄였지만,
  같은 held-position 종목에 대해 동일 근거로 새 cycle마다 다시 `REDUCE/EXIT`를 생성하는 경로는 남아 있었다.
- 이 상태는 불필요한 AI 호출, 분석 노이즈, 중복 주문 시도 가능성을 만든다.

## 문제 정의

- 현재 pre-AI gate는 `held_position_recent_hold_no_change`만 막고,
  최근 위험축소 SELL 이후의 반복 판단은 막지 않는다.
- execution 단계에도 같은 cycle 내 symbol 중복 submit 차단은 있지만,
  다음 cycle에서 같은 종목이 다시 들어오면 새 판단과 새 execution 시도가 재발생할 수 있다.

## 이번 수정 원칙

1. suppression은 AI 이전 deterministic gate에서 수행한다.
2. `held_position` 경로에만 적용한다.
3. 최근 이벤트가 있으면 suppression하지 않는다.
4. 최근 같은 종목의 SELL order가 있었고,
   최근 held-position `REDUCE/EXIT/SELL` 판단이 있었으며,
   현재 보유수량이 그 판단 시점 anchor 수량보다 증가하지 않았다면
   새 AI 판단을 생략한다.
5. 장 마감 임박(`14:30 KST` 이후)에는 기존 held-position skip과 동일하게 suppression을 끈다.

## 구현 요약

- [`src/agent_trading/domain/enums.py`](../src/agent_trading/domain/enums.py)
  - 새 canonical stop reason 추가:
    - `held_position_recent_risk_sell_cooldown`
- [`src/agent_trading/services/pre_ai_gate.py`](../src/agent_trading/services/pre_ai_gate.py)
  - 최근 held-position 판단 조회 helper 추가
  - 최근 same-symbol SELL order 상태를 함께 점검
  - 최근 `REDUCE/EXIT/SELL` 판단의 `decision_context.position_snapshot_id` anchor를 읽어
    현재 보유수량과 비교
  - 조건 충족 시 pre-AI 단계에서 `held_position_recent_risk_sell_cooldown` 반환

## 기대 효과

- 같은 종목의 위험축소 판단이 동일 근거로 매 cycle 반복 생성되는 현상을 완화한다.
- 장중 동일 symbol의 `trade_decisions` / `execution_attempts` 노이즈를 줄인다.
- unknown order state는 기존 reconciliation / active order 경로가 우선하고,
  이 suppression은 그 위에서 불필요한 새 판단 생성을 줄이는 보조 장치로 동작한다.

## 후속 작업

- 같은 suppression 결과를 `guardrail_evaluations` 분포에서 실측해 실제 차단 빈도를 확인
- 필요 시 `signal_feature_snapshot_id` 동일 여부까지 포함한 stricter duplicate policy 검토
- 이후 장중 데이터로 반복 매도 감소 효과 재검증

## 장중 모니터링 후 진행할 작업

- 우선 `2거래일` 정도 장중 운영 데이터를 모니터링한 뒤 다음 단계로 진행한다.
- 확인 대상:
  - `held_position_recent_risk_sell_cooldown` stop reason 발생 빈도
  - 동일 종목의 반복 `REDUCE/EXIT` 판단 감소율
  - suppression 적용 후에도 실제 필요한 위험축소 SELL이 지연되거나 누락되지 않는지
  - 같은 종목에서 `recent event` 유입 시 suppression 해제가 정상 동작하는지
- 위 패턴이 안정적으로 확인되면 다음 작업으로 진행:
  - `signal_feature_snapshot_id` 동일 여부까지 포함한 stricter duplicate policy 검토
  - suppression window / 조건식의 추가 정교화 여부 결정
