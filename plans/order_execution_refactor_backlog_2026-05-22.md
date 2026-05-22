# 주문 실행 파이프라인 리팩토링 백로그

작성일: 2026-05-22  
목적: 최근 며칠간 반복된 주문 누락, `trade_decision`만 생성되고 `order_request`가 없는 현상, `BUDGET_EXHAUSTED`/`BLOCKED`/`reconcile_required` 적체, snapshot/quote hang 문제와 KIS sync 불안정을 **패치 누적이 아니라 구조 개선 관점**에서 정리한다.

## 1. 현재 판단

지금 상태는 단일 버그 몇 개를 더 패치한다고 안정화될 단계가 아니다.

반복적으로 드러난 문제는 공통적으로 아래 구조 결함에 연결된다.

1. `trade_decision` 생성과 주문 실행이 너무 강하게 결합되어 있다.
2. `assemble_and_submit()`가 quote, sizing, guard, create, submit, reconcile까지 너무 많은 책임을 가진다.
3. 상태값(`pending_submit`, `reconcile_required`, `expired`, `rejected`, `blocked`)과 원인코드가 뒤섞여 있다.
4. held_position 위험 축소 매도가 신규 BUY와 동일/유사 budget, timeout, scheduler 정책에 영향을 받는다.
5. 주문이 왜 안 나갔는지 바로 알 수 있는 execution trace가 부족하다.

따라서 아래 2개 축을 정식 백로그로 올린다.

1. **주문 실행 파이프라인 리팩토링**
2. **KIS Sync 신뢰성 리팩토링**

## 2. 우선순위 원칙

- `P0`: 지금 장중 운영 장애를 직접 줄이는 작업
- `P1`: 주문 실행 구조를 분리하고 상태/흐름을 안정화하는 작업
- `P2`: 관측성, 운영 도구, 후속 정리

## 3. 백로그

| ID | 우선순위 | 작업 | 이유 / 기대효과 |
|---|---|---|---|
| EXE-001 | P0 | **held_position sell quote 단계 hang 직접 복구** | 최근 12:56 batch에서 `000150`/`000810` 모두 AI는 끝났지만 `order_request`가 생성되지 않음. 현재 가장 유력한 병목은 `Phase 1.5 quote_resolution`. 이 경로를 timeout/fallback/isolation으로 먼저 안정화해야 함. |
| EXE-002 | P0 | **held_position sell 전용 phase trace / audit 추가** | `trade_decision`만 남고 끝나는 케이스에서 현재는 최종 reason이 없음. symbol별 `decision_saved → quote_started → quote_fallback → sizing → guard → order_created → submitted / skipped / failed`를 남겨야 함. |
| EXE-003 | P0 | **현재 submit batch 미완료/장기 실행 감시 추가** | `decision_submit_gate`가 살아 있는데 심볼별로 일부만 진행되는 현상이 반복됨. batch start/end뿐 아니라 symbol별 진행 상태를 운영에서 바로 볼 수 있어야 함. |
| EXE-004 | P0 | **held_position sell 경로에서 quote 실패 시 주문 실행 지속 정책 확정** | risk-reducing sell은 quote를 sizing 참고용으로만 쓰므로 quote 실패가 주문 자체 차단으로 이어지면 안 됨. fallback 정책을 명문화해야 함. |
| EXE-005 | P0 | **로그 파일 경로 표준화** | 추적용 로그 파일이 필요하면 `/tmp` 금지, 반드시 `/workspace/agent_trading/logs` 사용. 운영 재현성과 권한 안정성을 확보해야 함. |
| EXE-005A | P0 | **`decision_submit_gate` batch hang / partial progress 직접 제어** | 현재는 batch가 살아 있는데 일부 symbol만 `trade_decision`까지 가고 `order_request` 없이 잔류하는 현상이 반복됨. symbol-level timeout, batch-level timeout, 잔류 coroutine 정리, partial progress 기록을 분리 설계해야 함. |
| EXE-005B | P0 | **`quote_resolution` C-level I/O block 대응** | `broker.get_quote()`가 `asyncio.wait_for()` 바깥처럼 동작하거나 C-level read block으로 오래 물릴 가능성이 큼. timeout만이 아니라 isolation, 강제 fallback, per-symbol degrade, 진단 로그를 함께 넣어야 함. |
| EXE-006 | P1 | **Decision Pipeline / Execution Pipeline 분리 설계** | `trade_decision` 생성과 실제 주문 실행을 분리해야 `decision only` 상태를 제어 가능. `execution_attempt` 같은 별도 실행 단위를 도입하는 것이 핵심. |
| EXE-007 | P1 | **`execution_attempt` 엔티티/상태 도입** | `trade_decision` 이후 실행 상태를 따로 관리. 예: `pending`, `quote_timeout`, `guard_blocked`, `order_created`, `submitted`, `failed`, `reconcile_required`. |
| EXE-008 | P1 | **`assemble_and_submit()` 분해 리팩토링** | 현재 함수가 AI 판단, quote, sizing, guard, create, submit, stale bypass까지 모두 담당함. phase별 함수 분리와 명시적 반환 구조가 필요. |
| EXE-009 | P1 | **held_position sell 전용 execution lane 정식화** | 신규 BUY와 분리된 budget/timeout/skip policy를 가져야 함. risk-reducing sell은 별도 execution class로 승격하는 것이 맞음. |
| EXE-010 | P1 | **scheduler 정책과 주문 도메인 정책 분리** | dry-run 전환, daily cap, submit gate, held_position sell 우선순위가 scheduler에 과도하게 들어가 있음. 주문 도메인 정책과 스케줄러 pacing을 분리해야 함. |
| EXE-011 | P1 | **상태 모델 재정의** | 도메인 상태와 원인 코드를 분리. 예: decision 상태 / execution 상태 / broker 상태 / reconciliation 상태를 나눠야 함. |
| EXE-012 | P1 | **`trade_decision.quantity` 의미 재정의 및 기본 1주 흔적 제거** | 현재 `trade_decision.quantity`가 초기 request 기본값(1주)을 그대로 들고 있어 BUY/HOLD 판단 근거와 SELL/REDUCE 판단 모두를 왜곡함. 판단 수량과 실행 수량을 분리하고, HOLD/WATCH에는 기본 1주가 남지 않게 해야 함. |
| EXE-013 | P1 | **order creation 이전 skip/timeout 사유의 영속화** | 현재 `order_request`가 없으면 DB에 이유가 남지 않음. 최소한 execution/audit 테이블에 terminal reason을 남겨야 함. |
| EXE-014 | P1 | **quote/snapshot/guard 의존성 축소** | held_position sell은 일부 입력 실패에도 degrade 가능해야 함. 특히 snapshot stale, quote unavailable 상황에서 위험 축소 주문은 지나치게 차단되지 않아야 함. |
| EXE-015 | P2 | **reconciliation lock / run / order 관계 관측성 개선** | lock owner, active/inactive, release failure, run 상태를 한 화면/쿼리로 볼 수 있어야 함. |
| EXE-016 | P2 | **post-submit / reconcile convergence 대시보드 보강** | `reconcile_required` 적체와 convergence 실패를 운영자가 바로 구분 가능해야 함. |
| EXE-017 | P2 | **기존 `stale_pending_submit_expired` 과거 row 재분류 백필 검토** | 이 항목은 다음 우선순위 메모로 이미 분리됨. 현재보다 시급한 운영 장애가 먼저라서 후순위 유지. |

## 3A. KIS Sync 백로그

| ID | 우선순위 | 작업 | 이유 / 기대효과 |
|---|---|---|---|
| SYNC-001 | P0 | **KIS 조회 실패 시 position zero-out 금지** | timeout, auth, network, budget exhaustion 같은 조회 실패를 `포지션 없음`으로 해석하면 안 됨. broker 성공 응답이 없는 경우에는 기존 양수 포지션을 유지하거나 stale/unknown으로 남겨야 함. |
| SYNC-002 | P0 | **snapshot 상태 모델 도입 (`success` / `partial` / `failed` / `stale`)** | 지금은 partial failure와 실제 0 포지션이 같은 의미처럼 취급됨. 조회 성공 여부와 데이터 의미를 분리해야 함. |
| SYNC-003 | P0 | **cash / positions / orderable_amount fetch 결과를 분리 저장** | `cash=0`, `positions=0`, `orderable_amount=None`가 한 덩어리로 흔들리지 않게 해야 함. 필드별 fetch 결과와 fallback 사용 여부를 따로 남겨야 함. |
| SYNC-004 | P0 | **position sync partial failure 시 UI/guard가 stale truth를 안전하게 사용하도록 보정** | 최신 snapshot 한 번 실패했다고 현재 포지션이 0으로 보이면 안 됨. stale latest-positive snapshot fallback 또는 explicit stale state를 화면/주문 guard가 읽을 수 있어야 함. |
| SYNC-005 | P1 | **positions / cash / orderable_amount sync cadence 분리** | 장중 submit에 중요한 `cash + orderable_amount`와 positions를 같은 cycle에 강하게 결합하지 말 것. 중요도와 실패 허용도를 분리해야 함. |
| SYNC-006 | P1 | **snapshot sync를 scheduler cadence로부터 더 독립적으로 운영** | 설정은 5분이어도 실제로는 상위 scheduler 한 바퀴에 종속되어 8~10분처럼 보이는 문제가 있었음. 실질 cadence 보장이 필요함. |
| SYNC-007 | P1 | **KIS Sync audit / trace 표준화** | account별로 `positions_fetch_started`, `positions_fetch_failed`, `cash_fetch_failed`, `orderable_amount_fallback_used`, `zero_out_skipped` 같은 구조화 이벤트가 남아야 원인 파악이 쉬움. |
| SYNC-008 | P1 | **timeout / budget exhaustion / auth failure를 broker truth와 분리** | transport failure를 broker truth처럼 저장하지 말고, 별도 failure class로 다뤄야 함. |
| SYNC-009 | P2 | **KIS Sync 상태 대시보드 보강** | 계좌별 최신 snapshot 상태, partial/stale 여부, 마지막 성공 fetch 시각, 필드별 실패 원인을 한 화면/쿼리로 볼 수 있어야 함. |

## 4. 즉시 착수 순서

### 4.1 이번 세션 기준 바로 해야 할 순서

1. `EXE-001` held_position sell quote hang 직접 복구
2. `EXE-002` symbol별 phase trace / audit 추가
3. `EXE-003` submit batch 장기 실행 감시 추가
4. `EXE-004` quote fallback 정책 확정 및 코드 반영
5. `EXE-005A` batch hang / partial progress 직접 제어
6. `EXE-005B` `quote_resolution` C-level block 대응

### 4.2 그 다음 구조 리팩토링 착수 순서

1. `EXE-006` Decision / Execution 분리 설계 문서 작성
2. `EXE-007` `execution_attempt` 엔티티/상태 모델 설계
3. `EXE-008` `assemble_and_submit()` 분해
4. `EXE-009` held_position sell 전용 execution lane 도입
5. `EXE-011` 상태 모델 재정의
6. `EXE-012` `trade_decision.quantity` 재정의 및 기본 1주 제거

### 4.2A KIS Sync 즉시 착수 순서

1. `SYNC-001` KIS 조회 실패 시 position zero-out 금지
2. `SYNC-002` snapshot 상태 모델 도입
3. `SYNC-003` cash / positions / orderable_amount fetch 결과 분리 저장
4. `SYNC-004` partial failure 시 stale truth 안전 사용 보정
5. `SYNC-005` positions / cash / orderable_amount sync cadence 분리
6. `SYNC-006` snapshot sync cadence 독립성 강화

## 4.3 `trade_decision.quantity` 리팩토링 원칙

이 항목은 단순 표시 수정이 아니라 데이터 모델 정합성 문제로 다룬다.

### 현재 문제

1. BUY/HOLD 판단 근거에 기본 1주가 남아 실제 의사결정 수량처럼 보인다.
2. SELL/REDUCE에서도 기본 1주가 남아 실제 포지션 축소 의도와 다르게 읽힌다.
3. `trade_decision.quantity`가
   - AI 판단 수량인지
   - 초기 request 수량인지
   - sizing 이후 실행 수량인지
   의미가 불명확하다.

### 리팩토링 목표

1. `trade_decision`에는 **판단 의미**만 남긴다.
2. 실제 실행 관련 수량은 `execution_attempt` / `order_request` 계층으로 내린다.
3. HOLD/WATCH 같은 비실행 판단에는 기본 1주가 보이지 않게 한다.
4. SELL/REDUCE/EXIT에서도 “초기 기본값 1주”와 “실제 실행 수량”을 혼동하지 않게 한다.

### 권장 모델

- `trade_decision`
  - `decision_type`
  - `target_quantity` 또는 `suggested_quantity` (필요 시)
  - 없으면 수량 nullable 허용
- `execution_attempt`
  - `requested_quantity`
  - `sized_quantity`
  - `submit_quantity`
- `order_request`
  - 실제 브로커 제출 수량

### 구현 시 주의점

1. 기존 UI가 `trade_decision.quantity`를 바로 읽는 화면은 함께 정리
2. BUY/HOLD 화면과 held_position SELL 화면을 같이 검증
3. 과거 데이터와의 호환 방식(backfill 또는 nullable 허용)도 설계에 포함

## 4.4 batch hang / partial progress 리팩토링 원칙

이 항목은 단순 timeout 증설이 아니라, **batch 전체와 symbol 개별 진행 상태를 분리 제어**하는 문제로 본다.

### 현재 문제

1. `decision_submit_gate` 프로세스는 살아 있는데 일부 symbol만 `trade_decision`까지 생성되고 이후 멈춘다.
2. 같은 batch 안에서 어떤 symbol은 제출되고, 어떤 symbol은 `order_request` 없이 남는다.
3. batch timeout이 나도 어떤 symbol이 어느 단계까지 갔는지 명확히 남지 않는다.

### 리팩토링 목표

1. batch-level timeout과 symbol-level timeout을 분리
2. symbol별 phase progress를 독립적으로 수집
3. 한 symbol hang이 나머지 symbol 제출을 과도하게 지연시키지 않게 할 것
4. batch 중간 종료 시에도 각 symbol의 마지막 단계와 이유를 남길 것

### 권장 방향

- symbol별 execution attempt 단위로 진행 단계 저장
- batch supervisor는 symbol task timeout과 전체 timeout을 별도로 관리
- partial progress를 DB/event/log에 모두 남길 것

## 4.5 `quote_resolution` 대응 원칙

현재 운영상 가장 강한 의심 병목은 `Phase 1.5 quote_resolution`이다.

### 현재 문제

1. AI 판단은 완료됐는데 `order_request`가 없는 케이스가 반복된다.
2. `broker.get_quote()`가 timeout/fallback에도 불구하고 오래 물리는 정황이 있다.
3. quote 실패가 held_position sell 주문 자체를 멈추는 방향으로 작동하면 위험 축소 목적과 충돌한다.

### 리팩토링 목표

1. quote 실패/지연이 held_position sell 주문 생성 자체를 막지 않게 할 것
2. `quote_started`, `quote_done`, `quote_timeout`, `quote_fallback`을 모두 남길 것
3. 필요하면 quote 조회를 별도 isolation 경로로 분리

### 권장 방향

- held_position sell은 quote를 sizing 참고용 입력으로만 취급
- quote 실패 시 즉시 fallback 후 submit path 지속
- `/workspace/agent_trading/logs`에 심볼별 quote trace 기록

## 4.6 KIS Sync 리팩토링 원칙

KIS Sync는 단순 데이터 수집이 아니라, 주문 실행과 UI truth의 기반이 되는 **snapshot truth pipeline**으로 다뤄야 한다.

### 현재 문제

1. 조회 실패(timeout, auth, network, budget exhaustion)가 실제 broker truth처럼 저장되는 경로가 있다.
2. positions / cash / orderable_amount가 한 cycle 안에서 강하게 결합되어 하나 실패하면 나머지 의미도 흔들린다.
3. partial success 모델이 약해서 `cash=0`, `positions=0`, `orderable_amount=None`가 모두 “실제 값”처럼 보일 수 있다.
4. 최신 snapshot 한 번 실패하면 UI와 guard가 잘못된 현재 truth를 읽을 수 있다.

### 리팩토링 목표

1. transport failure와 broker truth를 절대 같은 의미로 저장하지 않는다.
2. zero-out은 **브로커 성공 응답에서 포지션 부재가 확인된 경우에만** 허용한다.
3. snapshot은 필드별 fetch 성공/실패와 전체 state를 함께 가진다.
4. 장중 주문 보호 관점에서 stale truth를 더 안전하게 소비하도록 만든다.

### 권장 방향

- position snapshot은 `success/partial/failed/stale` 상태를 명시
- positions / cash / orderable_amount fetch 결과를 분리 저장
- timeout/auth/budget exhaustion은 별도 reason code로 남기기
- `/workspace/agent_trading/logs`에 account별 KIS sync trace를 구조화해서 남기기
- UI와 guard는 “최신 row”만 보지 말고 “최신 성공 truth + 현재 sync 상태”를 같이 보게 만들기

## 5. 닫지 말아야 할 기준

아래 조건 중 하나라도 남아 있으면 “근본 해결 완료”로 닫지 않는다.

1. held_position sell에서 `trade_decision`만 있고 `order_request`가 없는 케이스가 다시 발생
2. 심볼별로 왜 주문이 안 나갔는지 DB/로그에서 5분 안에 판별 불가
3. `decision_submit_gate` 장기 실행 중 심볼별 진행 상태를 알 수 없음
4. 위험 축소 매도가 신규 BUY와 같은 budget/timeout 정책에 의해 계속 영향을 받음
5. KIS timeout/auth/network 실패 한 번으로 최신 포지션 truth가 0으로 뒤집힘
6. `positions=0`, `cash=0`, `orderable_amount=None`가 실제 부재와 조회 실패를 구분 없이 의미함

## 6. 관련 문서

- [next_priority_backfill_stale_pending_submit_reclassification_note_2026-05-22.md](/workspace/agent_trading/plans/next_priority_backfill_stale_pending_submit_reclassification_note_2026-05-22.md)
- [trace_trade_decision_without_order_request_for_recent_held_position_sell_2026-05-22.md](/workspace/agent_trading/plans/trace_trade_decision_without_order_request_for_recent_held_position_sell_2026-05-22.md)
- [remove_daily_submit_cap_blocking_held_position_sell_from_entering_submit_path_2026-05-22.md](/workspace/agent_trading/plans/remove_daily_submit_cap_blocking_held_position_sell_from_entering_submit_path_2026-05-22.md)
- [trace_real_budget_source_and_lock_owner_for_1017_held_position_sell_blocking_2026-05-22.md](/workspace/agent_trading/plans/trace_real_budget_source_and_lock_owner_for_1017_held_position_sell_blocking_2026-05-22.md)
