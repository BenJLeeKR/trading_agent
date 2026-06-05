# 최초 시작부터 KIS 주문 제출·재조회까지 전체 경로 설명서

## 문서 목적

이 문서는 **운영 스케줄러가 시작된 뒤, AI 의사결정이 어떻게 주문으로 이어지고, KIS에 제출된 뒤 어떤 후속 정리 과정을 거치는지**를 한 번에 이해할 수 있도록 만든 안내서다.

대상 독자:

- 개발자가 아닌 운영 담당자
- 주문이 왜 나갔는지 / 왜 안 나갔는지 흐름을 파악해야 하는 업무 담당자
- 장애가 났을 때 “어느 단계에서 멈췄는지”를 빠르게 알고 싶은 사람

주의:

- 여기서 말하는 “재문 제출”은 보통 현업에서 말하는 **주문 제출 이후 상태 재확인(재조회·재수렴)** 까지를 포함해서 설명한다.
- 즉, “AI가 판단했다 → 주문 생성 → KIS 제출 → 제출 후 체결/거절 상태를 다시 맞춰 나감”까지의 전체 흐름이다.

---

## 1. 한눈에 보는 전체 구조

```text
[운영 스케줄러 시작]
        |
        v
[장 상태 확인]
        |
        +--> [스냅샷 동기화]
        |         └─ 계좌/현금/포지션 최신화
        |
        +--> [이벤트 수집]
        |         └─ 공시/뉴스/이벤트 입력
        |
        +--> [의사결정 루프]
        |         └─ AI 판단 → 수량 산정 → 주문 생성 → KIS 제출
        |
        +--> [제출 후 동기화]
                  └─ KIS에 다시 물어봐서
                     제출/체결/부분체결/거절 상태를 내부 DB와 맞춤
```

이 구조를 더 쉽게 비유하면:

- **운영 스케줄러** = 전체 공정을 관리하는 “현장 반장”
- **스냅샷 동기화** = 현재 잔고/보유종목/주문가능금액 확인
- **의사결정 루프** = “지금 사야 하나 / 팔아야 하나” 판단 + 주문서 작성
- **KIS 제출** = 실제 증권사에 주문 전송
- **제출 후 동기화** = 주문이 진짜 접수됐는지, 체결됐는지 다시 확인

---

## 2. 가장 먼저 시작되는 곳

### 2-1. 운영 스케줄러 진입점

실제 시작 파일:

- [scripts/run_ops_scheduler.py](/workspace/agent_trading/scripts/run_ops_scheduler.py)
- 진입 함수: `main()`

역할:

- 장 시작 전/장중/장마감/장후를 구분한다.
- 필요한 보조 프로세스를 정해진 순서로 호출한다.
- 하루 동안 몇 번 돌았는지, 어떤 단계가 성공/실패했는지를 `operations_day_runs`에 기록한다.

### 2-2. 스케줄러가 실제로 호출하는 하위 작업

[scripts/run_ops_scheduler.py](/workspace/agent_trading/scripts/run_ops_scheduler.py) 안의 대표 함수:

- `_snapshot_command()`
  - `scripts/run_snapshot_sync_loop.py` 호출
- `_event_command()`
  - `scripts/run_event_ingestion_loop.py` 호출
- `_decision_command()`
  - `scripts/run_decision_loop.py` 호출
- `_post_submit_command()`
  - `scripts/run_post_submit_sync_loop.py` 호출
- `_fill_sync_command()`
  - `scripts/run_fill_sync_loop.py` 호출

즉 스케줄러는 **직접 판단하거나 직접 주문하지 않고**, 필요한 전용 프로세스를 호출해 전체 순서를 관리한다.

---

## 3. 주문 전에 반드시 하는 준비 작업

## 3-1. 계좌/현금/포지션 스냅샷 동기화

실행 파일:

- [scripts/run_snapshot_sync_loop.py](/workspace/agent_trading/scripts/run_snapshot_sync_loop.py)

핵심 역할:

- 계좌의 현금
- 주문가능금액
- 보유 종목
- 리스크 한도

를 최신 상태로 맞춘다.

왜 중요하나:

- 현금이 부족한데 매수 주문을 내면 안 된다.
- 보유 종목이 없는데 매도 판단을 계속 AI에게 물어보는 것도 낭비다.
- 최신 스냅샷이 없으면 주문을 막는 guard가 작동한다.

관련 핵심 파일/함수:

- [src/agent_trading/services/snapshot_sync.py](/workspace/agent_trading/src/agent_trading/services/snapshot_sync.py)
  - `sync_account_snapshots()`
- [src/agent_trading/brokers/koreainvestment/snapshot.py](/workspace/agent_trading/src/agent_trading/brokers/koreainvestment/snapshot.py)
  - KIS에서 계좌/현금/주문가능금액/포지션을 받아 내부 스냅샷으로 변환

---

## 3-2. 이벤트 수집

실행 파일:

- [scripts/run_event_ingestion_loop.py](/workspace/agent_trading/scripts/run_event_ingestion_loop.py)

역할:

- 공시, 뉴스, 외부 이벤트 등 의사결정에 참고할 재료를 모은다.

업무 관점 설명:

- 이 단계는 “AI가 시장 상황을 읽을 수 있게 재료를 공급하는 단계”다.
- 단, 이벤트가 없어도 모든 종목이 주문되는 것은 아니다.

---

## 4. 실제 ‘의사결정’이 시작되는 지점

## 4-1. 의사결정 루프 시작점

실행 파일:

- [scripts/run_decision_loop.py](/workspace/agent_trading/scripts/run_decision_loop.py)
- 진입 함수: `main()`
- 실제 루프 함수: `_run_loop()`
- 종목별 처리 함수: `_run_one_cycle()`

업무 관점 설명:

- 이 단계는 “한 종목씩 검토해서, 실제 주문 후보가 되는지 판단하는 단계”다.

---

## 4-2. 의사결정 전에 먼저 거르는 단계 (토큰 절감용 사전 차단)

현재는 AI 호출 전에 다음을 먼저 본다.

구현 파일:

- [scripts/run_decision_loop.py](/workspace/agent_trading/scripts/run_decision_loop.py)
- 함수: `_evaluate_pre_ai_skip_reason()`

적용 로직:

### A. 매도 판단 후보(`held_position` 경로)

- 해당 종목을 실제로 들고 있지 않으면
- AI에게 물어보지 않고 바로 `SKIPPED`

즉:

```text
보유 포지션 없음
-> "이 종목 팔까?"를 AI에 묻지 않음
-> 토큰 절감
```

### B. 매수 판단 후보(`core`, `market_overlay` 등)

- `orderable_amount < 0`
- 또는 `orderable_amount <= 500,000원`

이면 AI 호출 전 바로 `SKIPPED`

즉:

```text
주문가능금액이 사실상 부족함
-> "이 종목 살까?"를 AI에 묻지 않음
-> 어차피 주문이 안 될 가능성이 높으므로 미리 차단
```

---

## 4-3. 종목별 처리 흐름

`run_decision_loop.py`의 `_run_one_cycle()` 안에서 종목 1개는 대략 아래 순서로 처리된다.

```text
1) 사전 차단(pre-AI gate)
2) 의사결정 요청 객체 생성
3) T3 뉴스/공시 보조 데이터 점검
4) AI 의사결정 호출
5) 수량 산정
6) 매도 가드 / 중복 매수 가드 / stale snapshot 가드
7) 주문 요청 생성
8) 주문 생성(DRAFT -> VALIDATED -> PENDING_SUBMIT)
9) KIS 제출
10) 제출 후 즉시 1차 재조회(sync)
```

---

## 5. AI가 실제로 판단하는 구간

## 5-1. 메인 진입점

핵심 파일:

- [src/agent_trading/services/decision_orchestrator.py](/workspace/agent_trading/src/agent_trading/services/decision_orchestrator.py)
- 핵심 함수: `DecisionOrchestratorService.assemble_and_submit()`

이 함수가 하는 일:

1. `assemble()`
   - AI 에이전트들(EI, AR, FDC)을 돌린다.
   - `TradeDecision`를 저장한다.
   - `OrderIntent`를 만든다.
2. 그 결과를 실행 파이프라인으로 넘긴다.

### 업무 용어로 풀어쓰기

- `assemble()` = “AI가 읽고 판단해서 내부 판단서 작성”
- `OrderIntent` = “아직 증권사에 보내기 전, 내부 주문 의도서”

---

## 5-2. AI 내부 판단 흐름

업무적으로 이해하면 AI는 대략 이런 질문을 순서대로 받는다.

```text
이벤트/뉴스를 보면 좋은가?
-> 리스크는 큰가?
-> 최종적으로 BUY / SELL / HOLD / WATCH 중 무엇인가?
```

관련 구조:

- [src/agent_trading/services/decision_orchestrator.py](/workspace/agent_trading/src/agent_trading/services/decision_orchestrator.py)
  - `_run_decision_pipeline()`
- [src/agent_trading/services/ai_agents/](/workspace/agent_trading/src/agent_trading/services/ai_agents)
  - EI: 이벤트 해석
  - AR: 리스크 판단
  - FDC: 최종 의사결정

이 단계 결과:

- `APPROVE` / `BUY`
- `REDUCE` / `EXIT` / `SELL`
- `HOLD`
- `WATCH`

---

## 6. AI 판단이 바로 주문이 되지 않는 이유

AI가 “좋아 보인다”고 말해도, 바로 KIS로 보내지지 않는다.

중간에 여러 **결정론적(규칙형) 안전장치**가 있다.

주요 파일:

- [src/agent_trading/services/execution_service.py](/workspace/agent_trading/src/agent_trading/services/execution_service.py)
- 핵심 함수: `run_execution_pipeline()`

이 함수는 아래 순서로 움직인다.

```text
Phase 1.5  수량 산정(sizing)
Phase 1.5+ 매도 가능 수량 확인(sell guard)
Phase 2    HOLD/WATCH 여부 확인 + 주문 번역
Phase 2.5  최근 중복 매수 차단
Phase 3    주문 생성
Phase 4a   VALIDATED 전이
Phase 4b   PENDING_SUBMIT 전이
Phase 4c   스냅샷 stale guard
Phase 5    브로커(KIS) 제출
Phase 5.5  제출 직후 post-submit sync
```

---

## 6-1. 수량 산정(sizing)

파일:

- [src/agent_trading/services/execution_service.py](/workspace/agent_trading/src/agent_trading/services/execution_service.py)
  - `_build_sizing_inputs()`
- [src/agent_trading/services/sizing_engine.py](/workspace/agent_trading/src/agent_trading/services/sizing_engine.py)
  - `calculate_sizing()`

쉽게 말하면:

- “몇 주 살지/팔지”를 계산하는 단계
- 주문가능금액, 기존 보유수량, 포지션 집중도, 최소 진입금액 등을 반영한다

주요 차단 예:

- `orderable_amount_zero`
- `position_concentration`
- `min_entry_threshold`
- `below_min_qty`

업무 관점:

- AI가 “매수”라고 해도, 계좌 사정상 0주가 나오면 실제 주문은 안 나간다.

---

## 6-2. HOLD / WATCH는 주문으로 번역되지 않음

파일:

- [src/agent_trading/services/translation.py](/workspace/agent_trading/src/agent_trading/services/translation.py)
- 함수: `build_submit_order_request_from_decision()`

중요 규칙:

- `WATCH` → 주문 생성 안 함
- `HOLD` → 주문 생성 안 함
- `held_position + BUY` → 주문 생성 안 함

즉:

```text
AI가 "관찰만 하자(WATCH)"
-> 기록은 남김
-> 증권사에는 안 보냄
```

---

## 6-3. 중복 매수 차단

파일:

- [src/agent_trading/services/execution_service.py](/workspace/agent_trading/src/agent_trading/services/execution_service.py)

역할:

- 방금 같은 종목에 BUY 주문을 냈다면
- 일정 시간 안에는 다시 같은 방향 주문을 내지 않도록 막는다.

업무 관점:

- “같은 종목을 너무 짧은 시간 안에 연속 매수하는 실수”를 막는 장치

---

## 6-4. 스냅샷 stale guard

파일:

- [src/agent_trading/services/execution_service.py](/workspace/agent_trading/src/agent_trading/services/execution_service.py)

역할:

- 포지션/현금 스냅샷이 너무 오래됐으면 주문을 막는다.

업무 관점:

- 오래된 계좌 정보로 주문하면 위험하므로
- “정보가 신선하지 않다”고 판단되면 제출 전 차단한다.

예외:

- `held_position` 위험축소 SELL은 stale이어도 일부 우회 가능

---

## 7. 내부 주문 생성 단계

AI가 통과하고 규칙형 가드도 통과하면, 이제 내부 주문이 만들어진다.

파일:

- [src/agent_trading/services/order_manager.py](/workspace/agent_trading/src/agent_trading/services/order_manager.py)

관련 함수:

- `create_order()`
- `transition_to()`

상태 흐름:

```text
DRAFT
  -> VALIDATED
  -> PENDING_SUBMIT
```

쉽게 설명하면:

- `DRAFT` = 초안 주문
- `VALIDATED` = 형식 검사 완료
- `PENDING_SUBMIT` = 이제 증권사에 보내도 되는 상태

---

## 8. KIS에 실제로 주문 보내는 단계

## 8-1. 내부 주문 제출 orchestrator

파일:

- [src/agent_trading/services/order_manager.py](/workspace/agent_trading/src/agent_trading/services/order_manager.py)
- 함수: `submit_order_to_broker()`

이 함수가 하는 일:

1. 현재 reconciliation lock이 있는지 확인
2. broker adapter에 실제 제출 요청
3. 결과에 따라 상태 전이
   - `SUBMITTED`
   - `RECONCILE_REQUIRED`
   - `REJECTED`

업무 관점:

- “내부 주문을 증권사에 넘기고, 증권사 반응에 맞춰 내부 상태를 바꾸는 단계”

---

## 8-2. KIS adapter

파일:

- [src/agent_trading/brokers/koreainvestment/adapter.py](/workspace/agent_trading/src/agent_trading/brokers/koreainvestment/adapter.py)
- 함수: `submit_order()`

adapter 역할:

- 내부 주문 형식과 KIS API 형식의 차이를 맞춰주는 번역기
- 예산 소진(`BUDGET_EXHAUSTED`) 같은 시스템 사유도 여기서 표준화한다.

주요 처리:

- 요청 사전검사
- `BudgetExhaustedError` 처리
- held-position SELL reserve lane 재시도
- KIS REST client 호출

---

## 8-3. KIS REST 실제 호출

파일:

- [src/agent_trading/brokers/koreainvestment/rest_client.py](/workspace/agent_trading/src/agent_trading/brokers/koreainvestment/rest_client.py)
- 함수: `submit_order()`

실제 KIS body 구성 예:

```text
CANO             계좌번호
ACNT_PRDT_CD     계좌상품코드
PDNO             종목코드
ORD_DVSN         주문구분
ORD_QTY          주문수량
ORD_UNPR         주문가격
```

업무 관점:

- 이 단계가 “정말로 증권사에 전송되는 단계”다.
- 여기서 KIS가 `ODNO(주문번호)`를 주면 내부적으로는 “제출 성공”으로 본다.

---

## 9. KIS 제출 결과에 따른 내부 상태

정상 제출:

```text
PENDING_SUBMIT -> SUBMITTED
```

애매한 제출:

```text
PENDING_SUBMIT -> RECONCILE_REQUIRED
```

명시적 거절:

```text
PENDING_SUBMIT -> REJECTED
```

관련 파일:

- [src/agent_trading/services/order_manager.py](/workspace/agent_trading/src/agent_trading/services/order_manager.py)
- 함수: `submit_order_to_broker()`

---

## 10. 제출 직후 1차 재확인(즉시 후속 정리)

파일:

- [src/agent_trading/services/execution_service.py](/workspace/agent_trading/src/agent_trading/services/execution_service.py)

KIS에 성공 제출된 직후, 가능하면 즉시:

- broker order 조회
- 체결 여부 확인
- 상태 반영

을 한 번 더 시도한다.

코드상 위치:

- `run_execution_pipeline()` 안의 `Phase 5.5`
- 여기서 `self._sync_service.sync_order_post_submit(...)` 호출

업무 관점:

- “보냈다”로 끝나는 것이 아니라,
- “정말 접수됐는지 / 벌써 체결됐는지”를 바로 1차 확인하는 단계

---

## 11. 제출 후 별도 루프가 계속 상태를 다시 맞춤

## 11-1. post-submit sync 전용 프로세스

실행 파일:

- [scripts/run_post_submit_sync_loop.py](/workspace/agent_trading/scripts/run_post_submit_sync_loop.py)
- 진입 함수: `main()`

역할:

- 이미 제출된 주문을 주기적으로 다시 조회한다.
- KIS에서 상태가 바뀌었으면 내부 DB 상태도 그에 맞게 바꾼다.

즉:

```text
이미 낸 주문을 계속 추적하는 별도 담당 프로세스
```

---

## 11-2. 핵심 함수: sync_order_post_submit

파일:

- [src/agent_trading/services/order_sync_service.py](/workspace/agent_trading/src/agent_trading/services/order_sync_service.py)
- 함수: `sync_order_post_submit()`

이 함수의 핵심 순서:

1. `BrokerOrderEntity` 조회
2. `OrderRequestEntity` 조회
3. `broker.get_order_status()` 호출
4. 내부 상태로 매핑
5. 필요 시 `OrderManager.transition_to()` 호출
6. `broker.get_fills()` 호출
7. fill event 저장
8. terminal fill이면 snapshot refresh callback 호출

업무 관점:

- 제출 후에 체결, 부분체결, 거절, 만료 여부를 계속 맞춰 나가는 “후속 정리 담당자”

---

## 12. 체결 확인 근거는 무엇을 쓰나

현재는 체결 판단에 여러 근거를 쓴다.

대표 근거:

1. KIS 직접 주문 상태 조회
2. KIS 체결내역(`VTTC0081R`) 스냅샷
3. fill event
4. 포지션 변화량(position delta)

관련 파일:

- [src/agent_trading/services/order_sync_service.py](/workspace/agent_trading/src/agent_trading/services/order_sync_service.py)
- [scripts/run_fill_sync_loop.py](/workspace/agent_trading/scripts/run_fill_sync_loop.py)
- [src/agent_trading/api/routes/fill_history.py](/workspace/agent_trading/src/agent_trading/api/routes/fill_history.py)

업무 관점:

- “체결됐다”를 한 가지 증거만으로 보지 않고,
- 가능한 경우 직접적인 체결 근거를 우선 사용한다.

---

## 13. 체결되면 왜 다시 스냅샷을 갱신하나

체결이 발생하면:

- 현금이 줄거나 늘고
- 보유 수량이 바뀌고
- 주문가능금액이 변한다

그래서 제출 후 동기화 과정에서:

- [scripts/run_post_submit_sync_loop.py](/workspace/agent_trading/scripts/run_post_submit_sync_loop.py)
- `_build_refresh_callback()`

를 통해 snapshot refresh를 다시 호출한다.

업무 관점:

- 주문 체결 직후 계좌 상태를 가능한 빨리 최신으로 맞춰
- 다음 주문 판단이 오래된 금액으로 이뤄지지 않게 한다.

---

## 14. 전체 호출 경로를 코드 기준으로 다시 요약

## 14-1. 운영 스케줄러 기준

```text
scripts/run_ops_scheduler.py
  main()
    -> _run_pre_market() / intraday loop / _run_end_of_day()
    -> _snapshot_command()
    -> _event_command()
    -> _decision_command()
    -> _post_submit_command()
```

## 14-2. 의사결정 ~ 제출 기준

```text
scripts/run_decision_loop.py
  main()
    -> _run_loop()
      -> _process_one()
        -> _run_one_cycle()
          -> _evaluate_pre_ai_skip_reason()
          -> DecisionOrchestratorService.assemble_and_submit()
             -> _run_decision_pipeline()
             -> ExecutionService.run_execution_pipeline()
                -> calculate_sizing()
                -> build_submit_order_request_from_decision()
                -> OrderManager.create_order()
                -> OrderManager.transition_to(VALIDATED)
                -> OrderManager.transition_to(PENDING_SUBMIT)
                -> OrderManager.submit_order_to_broker()
                   -> KISAdapter.submit_order()
                      -> KISRestClient.submit_order()
                -> OrderSyncService.sync_order_post_submit()   (즉시 1차)
```

## 14-3. 제출 후 별도 수렴 기준

```text
scripts/run_post_submit_sync_loop.py
  main()
    -> _run_loop()
      -> PostSubmitSyncRunner
        -> OrderSyncService.sync_order_post_submit()
           -> broker.get_order_status()
           -> broker.get_fills()
           -> OrderManager.transition_to()
           -> snapshot_refresh_cb()
```

---

## 15. 업무자가 보면 좋은 핵심 체크 포인트

### 15-1. 주문이 아예 안 나간 경우

확인할 곳:

1. `run_decision_loop.py` pre-AI gate에서 스킵됐는가
2. AI 결과가 `HOLD/WATCH`였는가
3. sizing에서 0주가 나왔는가
4. stale snapshot guard에 막혔는가
5. scheduler gate에 막혔는가

### 15-2. 주문은 생성됐는데 KIS에 안 간 경우

확인할 곳:

1. `DRAFT -> VALIDATED -> PENDING_SUBMIT`까지 갔는가
2. `OrderManager.submit_order_to_broker()`에서 예산/락/오류가 났는가
3. `BUDGET_EXHAUSTED`, `BLOCKED`, `RECONCILE_REQUIRED`였는가

### 15-3. KIS에는 간 것 같은데 체결이 이상한 경우

확인할 곳:

1. `order_submission_attempts`
2. `broker_orders`
3. `fill_history`
4. `order_sync_service.sync_order_post_submit()`
5. `truth_probe_fill_snapshot_incomplete` 같은 보류성 reason

---

## 16. 실무적으로 기억해야 할 가장 중요한 포인트 5개

1. **AI가 좋다고 해도 바로 주문되지 않는다.**
   - 수량, 현금, stale snapshot, 중복 guard를 다 통과해야 한다.

2. **운영 스케줄러가 직접 주문하는 것이 아니다.**
   - 스케줄러는 각 전용 프로세스를 호출하는 관리자다.

3. **KIS 제출 성공과 체결 성공은 다르다.**
   - 제출 후에도 별도 재조회와 수렴 과정이 이어진다.

4. **주문가능금액/보유포지션 스냅샷은 주문 품질에 직접 영향을 준다.**
   - 오래되거나 잘못되면 주문이 과도하거나 보수적으로 막힐 수 있다.

5. **제출 후 동기화(post-submit sync)는 주문 라이프사이클의 일부다.**
   - 제출에서 끝이 아니라, 체결까지 상태를 맞춰야 진짜 완료다.

---

## 17. 관련 핵심 파일 빠른 참조표

| 구분 | 파일 | 핵심 함수 | 역할 |
|------|------|-----------|------|
| 운영 스케줄러 | `scripts/run_ops_scheduler.py` | `main()`, `_decision_command()` | 장중 전체 작업 순서 관리 |
| 스냅샷 동기화 | `scripts/run_snapshot_sync_loop.py` | `main()` | 계좌/포지션/현금 최신화 |
| 의사결정 루프 | `scripts/run_decision_loop.py` | `_run_loop()`, `_run_one_cycle()` | 종목별 AI 판단 진입 |
| 사전 토큰 절감 | `scripts/run_decision_loop.py` | `_evaluate_pre_ai_skip_reason()` | AI 호출 전 불필요 대상 차단 |
| AI 오케스트레이션 | `src/agent_trading/services/decision_orchestrator.py` | `assemble_and_submit()` | AI 판단 + 실행 파이프라인 연결 |
| 실행 파이프라인 | `src/agent_trading/services/execution_service.py` | `run_execution_pipeline()` | sizing, guard, 주문 생성, 제출 |
| 주문 번역 | `src/agent_trading/services/translation.py` | `build_submit_order_request_from_decision()` | HOLD/WATCH는 주문 미생성 |
| 주문 상태 관리 | `src/agent_trading/services/order_manager.py` | `create_order()`, `transition_to()`, `submit_order_to_broker()` | 내부 주문 생성과 상태 전이 |
| KIS adapter | `src/agent_trading/brokers/koreainvestment/adapter.py` | `submit_order()` | 내부 요청을 KIS 호출로 연결 |
| KIS REST | `src/agent_trading/brokers/koreainvestment/rest_client.py` | `submit_order()` | 실제 HTTP 요청 전송 |
| 제출 후 동기화 루프 | `scripts/run_post_submit_sync_loop.py` | `main()` | 제출 후 주기적 재조회 |
| 주문 수렴 서비스 | `src/agent_trading/services/order_sync_service.py` | `sync_order_post_submit()` | 체결/부분체결/거절/만료 수렴 |
| 체결내역 동기화 | `scripts/run_fill_sync_loop.py` | `main()` | VTTC0081R 기반 체결내역 수집 |

---

## 18. 문서 한 줄 요약

**운영 스케줄러가 시작되면, 먼저 계좌 상태를 맞추고, 그 다음 AI가 판단하고, 규칙형 가드가 이를 걸러낸 뒤, 통과한 주문만 KIS에 제출되며, 제출 뒤에도 별도 동기화가 계속 상태를 체결 기준으로 맞춰 간다.**
