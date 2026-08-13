# 15. truth-probe와 KIS fill 누적→증분 해석 경로 병행 설계 (설계안, 구현 미착수)

## 0. 문서 성격

이 문서는 **설계 문서**다. 코드 구현, migration, API/env/compose 변경은 포함하지 않는다.
근거가 된 read-only 운영 조사는 별도 대화 세션에서 수행됐으며, 이 문서는 그 관측
결과를 정리하고 **구현 방향을 결정하기 위한 설계**를 제공한다. 실행 계획은
[`docs/40_action_plans/truth_probe_kis_fill_sync_coexistence_action_plan.md`](../../40_action_plans/truth_probe_kis_fill_sync_coexistence_action_plan.md)를 따른다.

관련 선행 문서(표현 충돌 없이 아래를 그대로 존중한다):
- [`12_realized_pnl_moving_average_ledger.md`](12_realized_pnl_moving_average_ledger.md) — `fill_events`가 append-only이고, recompute의 1차 입력이 `fill_events`뿐이라는 계약. 이 문서는 그 계약을 바꾸지 않는다.
- [`14_kis_fill_normalization_and_incremental_interpretation_design.md`](14_kis_fill_normalization_and_incremental_interpretation_design.md) — `get_fills()` 정규화, `kis_fill_cumulative_state`, `resolve_incremental_fill()`, shadow 모드 설계. 이 문서는 그 구현이 **실제로 호출될 기회를 얻도록** 앞단 흐름을 조정하는 것이 목적이며, 14번 문서가 정의한 누적→증분 계산 로직 자체는 건드리지 않는다.

**이 설계는 미래 체결 경로 정상화용이다.** `broker_fill_snapshots`를 근거로 과거
(2026-08-01 KST 이후) 매도 실현손익을 되살리는 backfill 문제는 별도 조사(직전
턴, read-only 조사만 수행, 문서화되지 않음)에서 다룬 **별개 축**이며, 이 설계
문서의 범위가 아니다. 4.3절에서 선후관계만 짧게 명시한다.

## 1. 문제 재정의

### 1.1 확인된 사실 (read-only 운영 조사로 직접 확인)

- `sync_order_post_submit()`의 3a단계(`_try_truth_probe()`)가 `probe_status`를
  반환하면(즉 `None`이 아니면), `order_sync_service.py:719`에서 **그 즉시
  `return`**한다 — 3b단계(`get_order_status()`)와 6단계(`_sync_fills()`)에는
  코드 구조상 도달할 수 없다.
- `_try_truth_probe()` 내부의 **linked fill snapshot 기반 추론**
  (`_infer_linked_fill_snapshot_truth()`)은 이 주문에 연결된
  `broker_fill_snapshots` row 중 하나라도 `filled_quantity > 0`이면
  `FILLED` 또는 `PARTIALLY_FILLED`를 반환한다 — **매수/매도 구분 없이** 작동한다.
- 운영 관측(2026-08-13 14:07:39 KST 컨테이너 재시작 이후 약 47분, `post_submit_sync`
  38회 cycle) 결과, 현재 유일하게 존재하는 non-terminal 주문 3건(전부 매도,
  linked snapshot에 이미 양수 체결량 존재)이 **매 cycle 예외 없이** 이
  linked-snapshot 경로에서 조기 반환됐다. 같은 구간 동안 `kis_fill_incremental`/
  `shadow_skip`/`get_fills failed` 로그는 **0건**이었다.
- 이 차단은 `KIS_FILL_INCREMENTAL_APPEND_ENABLED`(shadow) 값과 **무관**하다 —
  shadow가 `true`였어도 이 3건은 여전히 3a에서 걸려 6단계 자체에 도달하지
  못했을 것이다.
- `_infer_sell_order_fill_via_position()`(SELL 포지션-델타 기반 추론)은
  `_try_truth_probe()` 내부에 있지 않다 — EXPIRED 복구, RECONCILE_REQUIRED
  처리 등 **별도 경로**에서만 쓰인다. 매수만 `_try_truth_probe()` 내부에
  `_infer_buy_order_fill_via_position_safe()` fallback을 갖고 있다.

### 1.2 아직 미확정인 점

- **신규 주문이 linked snapshot이 아직 없는 초기 구간에서 `_sync_fills()`까지
  실제로 도달하는 사례** — 코드상 가능성은 확인했으나(§3.2 표), 관측 기간(47분)
  동안 그런 신규 주문이 없어 실측하지 못했다.
- **truth-probe 완화(병행 호출) 시 실제로 중복 반영이 발생하는지** — 이론적
  근거(§3.3)는 있지만, 실제 병행 실행 결과를 관측한 적은 없다.
- **live 환경에서 동일한 truth-probe 구조/병목이 재현되는지** — 이번 조사는
  전부 paper 계좌 기준이다.
- **`broker_fill_snapshots`(별도 폴링, `fill_history_sync.py`)와 `get_fills()`
  (`_sync_fills()` 내부, 별도 실시간 조회)가 같은 주문에 대해 서로 다른
  시점에 관측한 값이 정확히 얼마나 자주/크게 어긋나는지** — 둘 다 같은
  KIS `inquire-daily-ccld` 엔드포인트를 쓰지만 호출 시점이 다르므로,
  일시적 불일치 가능성은 이론적으로만 인지하고 있다.

### 1.3 핵심 리스크 (유지해야 할 원칙)

- `fill_events`는 append-only다 — 잘못된 중복/과잉 적재는 표준 정정 경로가
  없다(12번 문서 7.3절). 이번 설계도 이 제약을 그대로 존중한다.
- `realized_pnl_recompute_service`의 1차 입력은 계속 `fill_events`만이다 —
  이번 설계로 `broker_fill_snapshots`를 recompute 입력으로 승격하지 않는다.
- truth-probe는 "나쁜 코드"가 아니다 — 문제는 **두 기능(상태 확정 vs 체결
  원장 적재)이 하나의 조기 반환으로 뒤엉켜 있다는 상호작용**이다. 이 설계는
  truth-probe의 상태 확정 능력을 그대로 유지하면서, 그것이 fill 원장 적재
  기회를 영구히 없애지 않도록 **분리**하는 데 집중한다.

## 2. 책임 분리 — truth-probe vs `_sync_fills()`

| | truth-probe(`_try_truth_probe`) | `_sync_fills()` |
|---|---|---|
| 목적 | **주문 상태(status) 확정** — FILLED/PARTIALLY_FILLED/EXPIRED 등 | **체결 원장(fill ledger) 적재** — `fill_events` append, `RealizedPnlLedgerService.apply_fill()` 호출 |
| 데이터 소스 | `broker_fill_snapshots`(캐시성 재확인) 또는 `resolve_unknown_state()`(실시간) 또는 position-delta(매수) | `broker.get_fills()`(실시간, 누적 관측치 반환 — 14번 문서) |
| 부작용 | `order_requests.status` 전이, `broker_orders.broker_status` 갱신 | `fill_events` append, `kis_fill_cumulative_state` upsert, ledger 반영 |
| 현재 관계 | 성공하면 아래를 **전혀 실행하지 못하게 조기 반환** | — |

**두 기능은 원래 같은 목적이 아니다.** truth-probe는 "이 주문이 지금 어떤
상태인가"를 빠르게(가능하면 실시간 조회 없이) 확정하려는 최적화이고,
`_sync_fills()`는 "이 주문에 대해 지금까지 실제로 얼마나 체결됐는지를
증분 단위로 원장에 남기는" 별개의 책임이다. 지금까지는 `_sync_fills()`가
"주문 상태가 아직 확정 안 됐을 때만" 실행되도록 우연히 결합돼 있었을
뿐이며, 이는 14번 문서의 신규 코드가 추가되기 전에는 큰 문제가 아니었다
(어차피 `get_fills()` 필드 매핑 자체가 깨져 있어 `_sync_fills()`가 실행돼도
`fill_events`에 아무것도 안 쌓였으므로, "실행 기회를 잃는 것"의 비용이
드러나지 않았다). 14번 문서로 `get_fills()`가 고쳐진 지금은, 이 결합이
**신규 경로가 영구적으로 실행 기회를 잃는 형태**로 드러난다.

## 3. truth-probe 성공 유형별 병행 가능성 판단

| truth source | 데이터 소스 | 조기 반환 유지? | `_sync_fills()` 병행 검토? | 근거 |
|---|---|---|---|---|
| **linked fill snapshot**(`FILL_SNAPSHOT`) | `broker_fill_snapshots`(캐시, 별도 폴링 주기) | 상태 확정은 유지 | **병행 검토 대상(1순위)** | 현재 운영 병목의 원인. 이 경로가 성공했다는 것 자체가 "실제 체결이 진행 중/완료됐다"는 뜻이므로, 오히려 이때가 fill 원장 적재가 가장 필요한 시점이다. |
| **`resolve_unknown_state()` 명확한 terminal**(reason=None/QTY_MISMATCH) | 실시간 KIS 조회(RECONCILIATION budget) | 유지 | 검토 보류 | 이미 실시간 조회를 한 번 했고 명확히 terminal — `_sync_fills()`가 또 다른 실시간 조회(`get_fills()`, INQUIRY budget)를 하는 것의 실익이 낮고, 이 경로가 병목이라는 증거도 없다. |
| **buy position delta**(`BUY_POSITION_FILL`) | 포지션 스냅샷 델타(매수 전용) | 유지 | 검토 보류 | 매수 전용이며, "paper 필드 불완전"이라는 예외적 상황에서만 발동한다. 병목 증거 없음. |
| **기타(미해결, `None` 반환)** | — | 해당 없음(원래 3b로 통과) | 해당 없음 | 이미 `_sync_fills()`에 도달 가능. |

**결론**: 병행 호출은 **`FILL_SNAPSHOT` reason 한정**으로 좁혀야 한다.
다른 truth source는 (a) 병목 증거가 없고, (b) 이미 실시간 조회를 한 번
수행했으므로 추가 조회의 실익이 낮으며, (c) 안정적으로 동작 중인 기존
경로를 불필요하게 넓히지 않는다는 `src/AGENTS.md` 원칙("실패한 실제
경로를 먼저 고치고, 그 경로가 요구하지 않는 동작을 넓히지 않는다")에도
맞는다.

## 4. 설계 대안 비교

### 안 A. truth-probe 성공 후에도 `_sync_fills()` 병행 호출(모든 truth source)

- **장점**: 가장 일반적인 해법 — 어떤 truth source든 fill 원장 적재 기회를 놓치지 않는다.
- **위험**: `resolve_unknown_state()`/position-delta 경로는 병목이라는 증거가 없는데도 매 cycle 추가 실시간 조회(INQUIRY budget 소비)가 발생 — 불필요한 범위 확장. 검증 범위도 커진다.
- **기존 코드 영향**: `sync_order_post_submit()`의 조기 반환 지점 전체를 건드려야 함 — 영향 범위 큼.
- **검증 난이도**: 높음 — 4개 truth source × 병행 여부를 전부 검증해야 함.

### 안 B. `FILL_SNAPSHOT` truth일 때만 조기 반환 완화 (병행 호출을 이 reason에만 한정)

- **장점**: 실제 관측된 병목(운영 non-terminal 3건 전부 이 경로)만 정확히 겨냥한다. 다른 truth source는 손대지 않아 회귀 위험이 최소화된다. `src/AGENTS.md`의 "실패한 경로만 고친다" 원칙과 정확히 부합.
- **위험**: `resolve_unknown_state()`/position-delta 경로에서도 잠재적으로 같은 문제가 있을 수 있는데(증거는 없음), 이번 설계가 그 부분은 다루지 않는다 — 범위를 의도적으로 좁힌 결과이며, 향후 그쪽에서도 병목이 발견되면 별도 설계가 필요하다.
- **기존 코드 영향**: `sync_order_post_submit()`의 `FILL_SNAPSHOT` 분기(`order_sync_service.py:619` 부근) 한 곳만 조정 — 영향 범위 작음.
- **검증 난이도**: 낮음~중간 — 기존 truth-probe 테스트(`test_truth_probe_conflict.py`)와 신규 incremental resolver 테스트가 이미 있어, 이 둘의 "병행 실행" 시나리오만 추가하면 됨.

### 안 C. `_sync_fills()`를 건드리지 않고 `broker_fill_snapshots` 기반 synthetic fill 별도 경로 신설

- **장점**: 기존 `sync_order_post_submit()`/`_sync_fills()` 흐름을 전혀 건드리지 않는다 — truth-probe 회귀 위험이 이론상 0.
- **위험**: `broker_fill_snapshots`의 `filled_quantity`(→ synthetic fill 수량)와 `get_fills()`의 실시간 누적값을 **별도로** 증분 해석해야 하므로, 14번 문서의 `resolve_incremental_fill()` 로직을 사실상 다시 구현하거나(중복 로직) 억지로 재사용해야 한다. 또한 이 경로는 이번 설계의 목적(**미래** 체결 경로 정상화)이 아니라 **과거** backfill 문제(별도 조사, 별도 축)와 사실상 동일한 문제라서, 두 문제를 뒤섞을 위험이 있다.
- **기존 코드 영향**: 신규 경로 하나가 통째로 늘어난다 — 장기 유지보수 비용 증가.
- **검증 난이도**: 중간 — 새 경로 자체는 격리돼 있어 테스트하기 쉽지만, "두 개의 독립적인 누적→증분 해석 로직이 같은 `fill_events`에 각각 append하려 할 때의 dedup"이라는 새로운 문제가 생긴다.
- **참고**: 이 안은 **"미래 체결 정상화"가 아니라 "과거 backfill"의 정식 구현안**에 더 가깝다. 채택하더라도 이번 설계 문서가 아니라 과거 backfill 설계 문서(§4.3 참고, 아직 미작성)에서 다뤄야 한다.

### 안 D. truth-probe와 fill 적재를 완전히 다른 worker/시점으로 분리

- **개요**: `post_submit_sync`(상태 확정 전용, 빠른 cycle)와 별개로, "fill 원장 동기화 전용 worker"를 새로 두어 truth-probe 결과와 무관하게 non-terminal(및 최근 terminal 전환) 주문 전체에 대해 주기적으로 `get_fills()`/`resolve_incremental_fill()`을 실행한다.
- **장점**: 책임 분리가 가장 깨끗하다 — truth-probe의 최적화 의도를 전혀 훼손하지 않는다.
- **위험/비용**: 신규 worker/스케줄 추가, "이미 terminal이 된 주문의 마지막 체결분을 언제까지 추적할 것인가"(무한정 추적할 수 없음 — 종료 조건 필요) 같은 새로운 설계 질문이 따라온다. 구현/검증 범위가 4안 중 가장 크다.
- **검증 난이도**: 높음 — 새 worker의 스케줄링, 종료 조건, 기존 `fill_sync`(대사 전용, `fill_history_sync.py`)와의 역할 중복 여부까지 정리해야 한다.

## 5. 추천안: 안 B (`FILL_SNAPSHOT` reason 한정 병행 호출)

### 5.1 왜 이 안이 안정성과 신규 목적을 가장 잘 양립시키는가

- 실제로 관측된 병목(운영 non-terminal 주문 전부가 `FILL_SNAPSHOT`에 걸림)을
  **정확히 그 지점만** 겨냥한다 — 병목 증거가 없는 다른 truth source
  (`resolve_unknown_state` 명확한 terminal, buy position delta)는 손대지
  않아, 안정적으로 동작 중인 기존 경로의 회귀 위험이 구조적으로 낮다.
- `src/AGENTS.md`의 "실패한 실제 경로를 먼저 고치고, 그 경로가 요구하지
  않는 인증·재시도·브로커·DB 동작을 넓히지 않는다"는 원칙과 정확히 일치한다.

### 5.2 왜 다른 안보다 중복 적재 위험이 낮은가

- 안 A(전체 병행) 대비: `resolve_unknown_state`/position-delta 경로에 대한
  병행 실행 리스크를 아예 만들지 않는다(그 경로들은 건드리지 않으므로).
- 안 C(별도 synthetic 경로) 대비: **하나의 누적→증분 해석 로직
  (`resolve_incremental_fill()`)만 계속 사용**한다 — `broker_fill_snapshots`
  기반 별도 해석 로직을 새로 만들지 않으므로, "두 로직이 같은 주문을
  서로 다르게 해석해 `fill_events`에 이중으로 쌓일" 위험 자체가 생기지
  않는다.
- 실제 중복 방지는 기존에 이미 구현된 **2단계 방어선**이 그대로 작동한다:
  1. `kis_fill_cumulative_state`의 delta 계산(같은 누적치를 다시 보면
     delta=0 → no-op) — truth-probe가 상태를 먼저 확정한 뒤 `_sync_fills()`가
     "뒤늦게" 실행되더라도, 이 delta 계산 자체가 "이미 반영된 부분은
     다시 세지 않는" 멱등성을 보장한다.
  2. `_sync_fills()`의 기존 `broker_fill_id`/composite key dedup(변경 없음).
  이 2단계 방어선은 원래 "같은 주문을 반복 폴링해도 안전하게" 만들기
  위해 설계된 것인데, 그 설계 의도가 "truth-probe가 먼저 상태를 확정한
  뒤 `_sync_fills()`가 병행 실행되는" 이번 시나리오에도 **동일하게
  적용된다** — 이미 만들어둔 안전장치가 이번 문제에도 그대로 유효하다는
  것이 안 B를 특히 안전하게 만드는 핵심 근거다.

### 5.3 왜 시장가/지정가 분기 없이 유지할 수 있는가

- 병행 여부의 조건은 **truth source(`FILL_SNAPSHOT`인지 아닌지)**이지
  주문 유형이 아니다. `FILL_SNAPSHOT`은 시장가/지정가 구분 없이 동일한
  조건(`broker_fill_snapshots`에 양수 체결량 존재)으로 발동하므로, 이
  설계는 처음부터 주문 유형과 무관하다.

### 5.4 왜 partial/full을 별도 경로로 나누지 않아도 되는가

- `_infer_linked_fill_snapshot_truth()`는 `PARTIALLY_FILLED`/`FILLED` 둘 다
  같은 함수, 같은 조건(`filled_quantity` vs `requested_quantity` 비교)으로
  판단한다 — 이미 partial/full이 하나의 판정 로직 안에 있다. 병행 호출도
  이 판정 결과(terminal이든 아니든)와 무관하게 **`FILL_SNAPSHOT`이라는
  reason 하나만 보고** 발동시키면 되므로, partial/full을 갈라서 처리할
  필요가 없다. 다만 5.5절에서 terminal 전환 순간의 처리는 별도로 명시한다.

### 5.5 terminal 전환 순간의 처리(중요, 이번 설계의 핵심 세부사항)

`FILL_SNAPSHOT`이 `FILLED`(terminal)를 반환하는 경우에도 병행 호출은
**반드시 유지**해야 한다 — 그렇지 않으면 "마지막 증분분"이 영원히
`kis_fill_cumulative_state`/`fill_events`에 반영되지 못한 채 그 주문은
terminal로 넘어가 버린다(다음 cycle부터는 최상단 terminal-skip에 걸려
아예 재시도 기회조차 없다). 즉 병행 호출 조건은 **"이번 truth-probe
reason이 `FILL_SNAPSHOT`인가"**여야 하고, "그 결과가 non-terminal인가"를
추가 조건으로 걸면 안 된다.

### 5.6 shadow 모드와의 관계

- 이 설계는 shadow 모드(`KIS_FILL_INCREMENTAL_APPEND_ENABLED`)를 **그대로
  유지**한다 — 이번 설계는 "코드 경로가 실행될 기회를 주는 것"이지
  "shadow를 끄고 바로 실적재하는 것"이 아니다. 병행 호출이 도입된 뒤에도
  기본값은 계속 `false`(shadow)여야 한다.
- 병행 호출이 도입되면, 처음으로 `kis_fill_incremental summary`/
  `shadow_skip`/anomaly 로그와 `kis_fill_cumulative_state` row 증가를
  **실제로 관측할 기회**가 생긴다 — 이게 바로 14번 문서 6.1절이 요구한
  "shadow 관측 기간"의 전제조건이었다(지금까지는 이 전제조건 자체가
  충족되지 못했다).
- 관측 포인트: 병행 호출이 실행됐다는 것 자체를 나타내는 로그(예:
  `truth_probe_fill_snapshot: parallel _sync_fills invoked` 같은 신규
  로그 — 이름은 구현 턴에서 확정)를 추가해, "truth-probe가 걸렸지만
  이번엔 병행 실행됐다"를 기존 "Truth probe resolved order ..." 로그와
  구분해서 볼 수 있어야 한다.

### 5.7 과거 backfill 문제와의 관계

- 이 설계는 **미래 체결 경로 정상화용**이다 — 앞으로 발생하는 체결이
  정상적으로 `fill_events`/ledger에 반영되도록 만드는 것이 목적이다.
- `broker_fill_snapshots`를 근거로 **과거**(2026-08-01 KST 이후 등) 매도
  실현손익을 복원하는 backfill은 **별도 축**이며, 이 설계로 자동으로
  해결되지 않는다 — 과거 주문은 이 병행 호출이 도입된 시점 이후에도
  `_sync_fills()`가 다시 호출될 일이 없다(이미 대부분 terminal이므로
  최상단에서 스킵됨).
- **선후관계**: 이번 설계(미래 정상화)가 먼저 안정적으로 동작하는 것을
  확인한 뒤, 과거 backfill 설계(별도 문서, 아직 미작성)로 넘어가는 것을
  권장한다 — 미래 경로가 검증되지 않은 상태에서 과거 데이터까지 동시에
  건드리면, 문제가 생겼을 때 원인을 구분하기 어려워진다.

## 6. 병행 조건을 어디에 둘 것인가 (구현 개념, 이번 턴 미착수)

`sync_order_post_submit()`의 `FILL_SNAPSHOT` 분기(현재 `order_sync_service.py`
약 615~730행) 안에서, 조기 `return` 직전에 다음을 삽입하는 개념(코드는
작성하지 않는다 — 구현 턴을 위한 개념 설명):

1. 기존 로직대로 상태 전이/`broker_orders` 갱신을 그대로 수행한다(변경 없음).
2. **추가로**, `_sync_fills(broker_order, broker, account_ref, since=broker_order.last_synced_at, account_id=order.account_id)`를 호출한다 — 기존 6단계와 동일한 호출 형태, 동일한 pacing(`asyncio.sleep(1.0)`)을 유지한다.
3. 그 결과(`fills_synced`, `fills_skipped`)를 `SyncOrderResult`에 반영한다(현재는 이 분기에서 항상 `0, 0`으로 고정돼 있음 — 이것도 이번 병목의 부수적 증상이다).
4. 이 추가 호출이 실패(예외)해도 **기존 상태 전이 결과 자체는 되돌리지 않는다** — `_apply_realized_pnl_ledger_hook()`이 이미 갖고 있는 "ledger 반영 실패가 fill 저장 성공에 영향을 주지 않는다"는 격리 원칙과 같은 원칙을 여기서도 적용한다.

## 7. 리스크 상세 (4C절 대응)

| 리스크 | 이 설계에서의 평가 |
|---|---|
| 상태 전이와 fill 적재가 서로 모순 | `_sync_fills()`는 order status를 전이하지 않는다(fill 적재만) — truth-probe가 이미 확정한 상태와 충돌할 지점이 없다. |
| 같은 체결이 양쪽에서 중복 반영 | §5.2의 2단계 방어선(delta 계산 + 기존 dedup)이 그대로 적용됨 — 다만 **실제 병행 실행 결과로 검증된 적은 없다**(§1.2 미확정). |
| snapshot 기반 partial truth와 `get_fills()` 누적값의 중복 소비 | 두 값은 **서로 다른 테이블**(`broker_fill_snapshots` vs `kis_fill_cumulative_state`)에 독립적으로 저장되므로 저장 계층에서는 충돌하지 않는다. 다만 두 값이 일시적으로 다를 가능성(폴링 시점 차이)은 이론적으로만 인지하고 있으며 실측되지 않았다. |
| terminal 상태 직전/직후 레이스 | 병행 호출을 `FILL_SNAPSHOT` reason 발생 시 항상(=terminal 결과 포함) 실행하도록 해 "마지막 증분 누락"을 방지한다(§5.5). 다만 동시 다발 폴러(다른 컨테이너/프로세스)가 있는 경우의 레이스는 `kis_fill_cumulative_state`의 행 단위 잠금(14번 문서)에 이미 위임돼 있다. |
| append-only `fill_events`에 잘못된 과잉 적재 | 불확실하면 append하지 않는다는 14번 문서의 최우선 원칙을 그대로 유지 — anomaly(negative delta, 가격 역산 불가)는 이번 설계에서도 append를 차단한다. |
| `kis_fill_cumulative_state`와 `broker_fill_snapshots` 간 의미 충돌 | 전자는 "누적→증분 해석의 기준점"(도메인), 후자는 "브로커 원문 대사 기록"(대사) — 역할이 다르며 이번 설계로 합치지 않는다(14번 문서 4절 원칙 유지). |

## 8. 검증 계획

- **구현 전** read-only 확인이 더 필요한 것: 없음(이번 조사로 병목 지점과
  조건은 코드 레벨로 특정됨). 다만 구현 착수 직전에 운영 non-terminal
  주문군이 바뀌었는지(같은 3건인지) 재확인하는 것을 권장.
- **구현 후 필요한 좁은 테스트**(이번 턴 작성하지 않음, 구현 턴 대상):
  1. `FILL_SNAPSHOT` truth-probe 성공 + `_sync_fills()` 병행 호출 시
     `fill_events`에 정확히 1건만 append되는지(중복 없음).
  2. 같은 시나리오를 반복 호출했을 때(=truth-probe가 매번 같은
     snapshot으로 성공) `_sync_fills()`가 매번 delta=0으로 no-op 처리되는지.
  3. `FILL_SNAPSHOT`이 `FILLED`(terminal)를 반환하는 마지막 cycle에서도
     병행 호출이 실행되고 마지막 증분이 반영되는지.
  4. `resolve_unknown_state`/`BUY_POSITION_FILL` 경로는 **이번 변경으로
     영향받지 않는지**(회귀 없음) — 기존 `test_truth_probe_conflict.py`가
     그대로 통과해야 한다.
- **운영에서 확인해야 할 로그/테이블**(구현 후):
  - `kis_fill_incremental summary`/`shadow_skip`/anomaly 로그가 처음으로
    나타나는지.
  - `kis_fill_cumulative_state` row 수가 0에서 늘어나는지.
  - `fill_events`/`realized_pnl_events`는 shadow 기본값(`false`) 상태이므로
    여전히 0건이어야 정상이다(§5.6) — 만약 이 상태에서 값이 늘어난다면
    shadow 스위치가 의도와 다르게 동작하는 것이므로 즉시 조사 대상.

## 9. 이번 설계가 명시적으로 다루지 않는 것 (범위 밖)

- 실제 코드 구현(§6은 개념 설명일 뿐 구현 아님).
- `resolve_unknown_state`/`BUY_POSITION_FILL` 경로의 병행 여부(§3 표에서
  "검토 보류"로만 남김).
- 과거(2026-08-01 KST 이후 등) 매도 실현손익 backfill의 정식 설계(§5.7,
  별도 문서 대상).
- live 환경에서의 검증(§1.2).
- inspection API를 통한 이번 병행 호출의 anomaly/성공률 노출(향후 후속 고려 대상).
