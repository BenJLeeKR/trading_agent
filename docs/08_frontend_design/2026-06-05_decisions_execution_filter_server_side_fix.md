# 의사결정 실행 필터 서버 정합화

## 문제
- `의사결정` 화면의 `실행` 콤보박스가 현재 페이지 20건에만 클라이언트 필터로 적용되고 있었다.
- 따라서 실제 DB에 `submitted` 행이 있어도 현재 페이지에 없으면 `0건`처럼 보였다.
- 추가로 `HOLD/WATCH`는 `DecisionType` enum 값이 소문자인데 일부 파생 로직이 대문자 문자열만 비교하여 `non_trade` 분류가 일관되지 않았다.

## 수정
1. `GET /trade-decisions`에 `execution_status` 서버 필터 추가
2. Postgres / InMemory read path 모두 `execution_status` 기준 필터 반영
3. 프런트 `DecisionsView`가 `execution_status`를 서버 요청에 포함하도록 수정
4. `TradeDecisionDetail.execution_status`의 `HOLD/WATCH` 판정을 소문자 enum 값까지 허용하도록 수정

## 검증
- 백엔드 테스트: `11 passed`
- 프런트 테스트: `28 passed`
- `tsc --noEmit`, `vite build` 통과

## 2026-06-05 실제 분포 (KST)
- `submitted`: 11
- `pipeline_stopped`: 217
- `non_trade`: 166
- `order_created`: 0
- `rejected`: 0
- `reconcile_required`: 0
- `trade_decision_only`: 0

## 결론
- `주문 제출(=submitted)` 필터가 0건으로 보이던 문제는 수정됨
- 다른 옵션 중 실제로 건수가 있는 것은 현재 날짜 기준 `submitted`, `pipeline_stopped`, `non_trade` 세 가지
- 나머지 옵션은 오늘 데이터 기준 실제 0건이므로 0건 표시가 정상
