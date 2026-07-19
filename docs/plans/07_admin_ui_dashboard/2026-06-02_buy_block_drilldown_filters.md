# 2026-06-02 BUY 차단 드릴다운 필터 추가

## 배경
`오늘 BUY 차단` 카드에서 숫자 집계는 볼 수 있었지만, 운영자가 바로 어떤 의사결정/종목이 해당 사유였는지 내려가 볼 수 있는 경로가 부족했다.

특히 아래 범주는 상세 목록으로 바로 이동할 수 있어야 한다.

- core dry-run
- market overlay dry-run
- general submit disabled
- submit budget consumed
- sizing rejected

## 목표
- `GET /trade-decisions`에 날짜/사유 기반 필터 추가
- 운영 대시보드 BUY 차단 카드에 드릴다운 링크 추가
- 링크 클릭 시 `의사결정` 화면에서 오늘 데이터만 정확히 필터링된 상태로 열리게 만들기

## 구현

### 백엔드
- `src/agent_trading/api/routes/decisions.py`
  - 신규 query params 추가
    - `date`
    - `side`
    - `source_type`
    - `decision_type`
    - `latest_stop_reason`
    - `latest_stop_reason_prefix`
    - `has_order`
  - in-memory 저장소에서는 route 레벨에서 보정 필터 수행
    - `latest_stop_reason` / `prefix`
    - `has_order`

- `src/agent_trading/repositories/contracts.py`
  - `TradeDecisionRepository.list_all_paginated()` 시그니처 확장

- `src/agent_trading/repositories/postgres/trade_decisions.py`
  - KST 날짜 / side / source_type / decision_type / stop_reason / has_order 필터 SQL 추가

- `src/agent_trading/repositories/memory.py`
  - entity 기반 필터(side/source_type/decision_type/date) 추가

### 프런트엔드
- `admin_ui/src/api/client.ts`
  - `getTradeDecisions()`에 임의 필터 파라미터 전달 지원 추가

- `admin_ui/src/components/DecisionsView.tsx`
  - URL search params를 읽어 서버 필터로 전달
  - 현재 적용 중인 드릴다운 필터를 상단 배너로 표시
  - `드릴다운 필터 해제` 버튼 추가

- `admin_ui/src/components/OperationsDashboardView.tsx`
  - BUY 차단 카드 하단에 링크 추가
    - `core 보기`
    - `overlay 보기`
    - `gate 보기`
    - `budget 보기`
    - `sizing 보기`

## 테스트
- `tests/api/test_inspection.py`
  - `GET /trade-decisions`가 `date/side/source_type/decision_type/latest_stop_reason_prefix/has_order` 조합을 처리하는지 검증

- `admin_ui/src/__tests__/dashboard.test.tsx`
  - BUY 차단 카드의 드릴다운 링크 href 검증

## 기대 효과
- 대시보드 숫자에서 바로 상세 원인 목록으로 이동 가능
- 운영자가 “왜 BUY가 안 나갔는지”를 카드 → 상세 목록 한 번에 추적 가능
- 신규 scheduler gate stop_reason 영속화와 결합되어, 내일부터는 `gate` / `budget` 원인을 사실 기반으로 바로 조회할 수 있음
