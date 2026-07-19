# 2026-06-01 paper 주문 안정화 효과 실측

## 검증 목적
- live 시세 전환과 paper REST pacing 적용 이후 주문 흐름이 실제로 개선됐는지 확인
- `BUDGET_EXHAUSTED(global)`가 계속 주문 제출을 막는지 확인
- 현재 남은 병목이 submit인지, sizing/skip인지, post-submit sync인지 구분

## 최근 6시간 주문 상태
- `BUDGET_EXHAUSTED` rejected: 21건
- submitted: 4건

## 시간대별 변화
- 2026-05-31 23시 UTC 구간:
  - `BUDGET_EXHAUSTED`: 8건
- 2026-06-01 00시 UTC 구간:
  - `BUDGET_EXHAUSTED`: 13건
  - submitted: 3건
- 2026-06-01 01시 UTC 구간:
  - submitted: 1건

## 안정화 이후 제출 성공 사례
2026-06-01 00:35:00 UTC 이후:
- `000150` sell 1주: submitted
- `001740` buy 2주: submitted
- `001740` buy 2주: submitted
- `004990` buy 1주: submitted

## 현재 판단
- 주문 제출 자체는 다시 살아났음
- 최근 구간에서는 `BUDGET_EXHAUSTED`가 계속 누적되는 상태는 아님
- 다만 다음 문제는 남아 있음
  - BUY 중 일부가 여전히 1주로 제출됨
  - 많은 후보가 `non_actionable_decision`, `zero_after_constraints`, `missing_reference_price_for_market_buy`로 SKIPPED
  - post-submit sync에서 paper `inquire-daily-ccld` 호출이 `EGW00201`을 한 번 발생시킴

## 남은 리스크
- submit 경로는 개선됐지만, post-submit sync의 paper 조회가 여전히 1RPS를 초과할 수 있음
- subprocess마다 pacing 상태가 분리될 수 있어, scheduler가 여러 KIS subprocess를 연속 실행할 때 paper 조회 호출이 겹칠 수 있음
- `004990` 매수 1주가 정상 sizing 결과인지 별도 확인 필요

## 다음 작업
1. BUY skip 및 1주 매수 원인 분석
2. post-submit sync paper 조회 pacing 보강 여부 판단
3. 최근 1~2시간 기준 `BUDGET_EXHAUSTED`가 재발하는지 재측정
