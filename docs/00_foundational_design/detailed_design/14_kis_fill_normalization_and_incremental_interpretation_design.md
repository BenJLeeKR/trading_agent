# 14. KIS 체결 응답 정규화 및 누적→증분 해석 설계 (설계안, 구현 미착수)

## 0. 문서 성격

이 문서는 **설계 문서**다. 코드 구현, migration, API 변경은 포함하지 않는다.
근거가 된 read-only 운영 조사는 별도 대화 세션에서 여러 턴에 걸쳐 수행됐으며,
이 문서는 그 관측 결과를 정리하고 **구현 방향을 결정하기 위한 설계**를 제공한다.
실행 계획은 [`docs/40_action_plans/kis_fill_normalization_action_plan.md`](../../40_action_plans/kis_fill_normalization_action_plan.md)를 따른다.

관련 선행 문서:
- [`12_realized_pnl_moving_average_ledger.md`](12_realized_pnl_moving_average_ledger.md) — `fill_events` → `RealizedPnlLedgerService` → `realized_pnl_events`/`position_cost_basis_state` 흐름의 원 설계. 이 문서는 그 설계의 **입력 경로(`fill_events` 적재 이전 단계)** 만을 다룬다. 12번 문서가 정의한 idempotency/replay 계약(5~8절)은 그대로 유지되며, 이 문서는 그 계약을 깨지 않는 범위에서 입력을 만드는 방법을 다룬다.
- [`05_koreainvestment_adapter_spec.md`](05_koreainvestment_adapter_spec.md) — KIS 어댑터 일반 책임.

## 1. 문제 재정의

### 1.1 확인된 사실 (read-only 운영 조사로 직접 확인)

- `trading.fill_events`는 전 기간(2026-05-13~) **0건**이다. 그 결과 `realized_pnl_events`/`realized_pnl_daily_aggregates`/`position_cost_basis_state`도 전부 0건이다.
- 이 계좌(paper 환경)에는 매도 체결완료 404건, 매수 체결완료 108건이 실제로 존재한다(`order_requests.status='filled'`) — 즉 **체결 자체는 일어나고 있다.**
- `order_sync_service._sync_fills()`는 실제로 30초 주기로 호출되고 있다(non-terminal 주문 대상, `broker_orders.last_synced_at`이 지속 갱신됨).
- `KISRestClient.get_fills()`(`rest_client.py:1559-1609`)는 다음 필드를 직접(대소문자 무관 처리 없이) 읽는다: `CCLD_QTY`, `CCLD_UNPR`, `ODNO`, `PDNO`, `SLL_BUY_DVSN_CD`.
- read-only 실사 조회(당일 체결완료 시장가 매도/매수 3건, `agent_trading-app-1` 컨테이너에서 운영과 동일한 `KISRestClient.inquire_daily_ccld()`를 재사용) 결과, 이 계좌의 paper 응답은:
  - 키가 **전부 소문자**(`odno`, `pdno`, `tot_ccld_qty`, `avg_prvs`, `sll_buy_dvsn_cd` 등)였다.
  - `ccld_qty`/`CCLD_QTY`, `ccld_unpr`/`CCLD_UNPR` 키는 **존재하지 않았다**(양쪽 대소문자 모두 부재).
  - 대신 `tot_ccld_qty`(총체결수량)와 `avg_prvs`(평균단가) 필드에 실제 값이 채워져 있었고, 3건 모두 `tot_ccld_qty == ord_qty`(요청수량과 동일 — 완전체결 1회성 케이스).
  - `broker_fill_snapshots`(별도 경로, `fill_history_sync.py`가 채움)의 `filled_quantity`/`fill_price`가 이 값과 정확히 일치했다.
- `fill_history_sync.py`는 이미 이 문제를 부분적으로 인지하고 대응하고 있다 — `_get_kis_value(item, "TOT_CCLD_QTY", "CCLD_QTY", default="0")`, `_get_kis_value(item, "AVG_PRVS", "CCLD_UNPR", default="0")` 같은 **다중 필드명 fallback + 대소문자 무관 조회**(`KISRestClient._get_kis_field` 재사용)를 이미 쓰고 있다. 다만 이 결과는 `broker_fill_snapshots`(대사 전용, replay 입력 아님)에만 쓰이고, `fill_events`(replay 입력, ledger 트리거)에는 전혀 연결되지 않는다.
- `RealizedPnlLedgerService.apply_fill(fill_event: FillEventEntity)`는 **호출당 하나의 fill_event를 "이번에 새로 발생한 체결 증분"으로 간주**하고 이동평균 원가/실현손익 상태를 갱신한다(`realized_pnl_ledger_service.py:226` 이하). 즉 `fill_events`에 들어가는 수량은 **반드시 증분(incremental)이어야** 하며, 누적값을 그대로 넣으면 안 된다.

### 1.2 강한 가설 (근거는 있으나 완전히 확정되지 않음)

- `tot_ccld_qty`는 필드명(총체결수량) 그대로 **"이 주문이 지금까지 누적으로 체결된 수량"**을 의미할 가능성이 높다. 완전체결 1회성 표본(관측된 모든 표본이 이 케이스)에서는 "누적값 == 이번 체결분"이 우연히 같아서, 이 표본만으로는 누적/증분을 구분할 수 없었다.
- 부분체결 주문이 실제로 여러 번에 걸쳐 체결될 때 `tot_ccld_qty`가 매 조회마다 그대로 누적 증가하는지는, 신선한(자연 발생) 부분체결 표본이 조사 시점에 존재하지 않아 **직접 확인하지 못했다**(기존에 남아있는 부분체결 3건은 전부 2개월 이상 정체된 주문이며, 조회 자체가 0 rows를 반환해 비교 대상이 되지 못했다).

### 1.3 미확정 영역 (이 설계가 반드시 보호장치로 다뤄야 하는 부분)

- `tot_ccld_qty`가 정말 누적값인지, 아니면 우연히 완전체결 케이스에서만 그렇게 보이는 다른 의미인지 — **미확정**.
- 지정가 주문에서 같은 필드셋이 나오는지 — 최근 지정가 표본이 전부 2개월 이상 정체돼 있어 **미확정**(시장가 3건만 확인).
- live(실전) 환경에서 같은 TR 계열(`TTTC0081R`)의 응답이 paper(`VTTC0081R`)와 같은 필드명/케이싱을 쓰는지 — **전혀 확인하지 않았다**. 이번 조사는 paper 계좌로만 진행됐다.
- 오래된(2개월 이상) 주문의 조회가 0 rows를 반환하는 현상의 정확한 원인(보존 기간 정책인지, 다른 이유인지) — **미확정**. 이건 이번 설계의 핵심 문제(누적/증분 해석)와는 별개 현상으로 분리해서 취급한다.

> **이 설계에서 명시적으로 강조할 점**: 지금 확인되지 않은 것은 "응답이 오는가"가 아니다 — 응답은 온다(row가 존재하고 실제 체결 정보를 담고 있음을 이미 확인했다). 확인되지 않은 것은 **"누적 체결량을 어떤 증분 규칙으로 안전하게 ledger/event에 반영할 것인가"**다.

### 1.4 핵심 리스크

`fill_events` → `RealizedPnlLedgerService.apply_fill()` → `realized_pnl_events`/`position_cost_basis_state` 경로는 append-only 지향 설계다(12번 문서 5~7절). 만약 누적값(`tot_ccld_qty`)을 매 폴링 주기마다 "새 체결"로 오인해 그대로 append하면:
- 같은 체결 수량이 폴링 주기(현재 5~30초)마다 반복 계상되어 실현손익이 기하급수적으로 부풀려진다.
- 이 오류는 append-only 구조상 **사후에 되돌리기 어렵다**(12번 문서 7.3절이 이미 "같은 fill_event_id로 두 번째 행을 만들 수 없어 별도 보정 행 append 방식이 불가능"함을 확인한 바 있다 — 즉 잘못 넣은 값을 안전하게 취소하는 표준 경로가 없다).

**따라서 이 설계의 최우선 목표는 새 필드를 "빨리 읽는 것"이 아니라, "누적값을 증분으로 안전하게 변환하지 못하면 아예 아무것도 append하지 않는 것"이다.**

## 2. 설계 원칙 — 왜 주문 유형별 분기가 아닌가

이 설계는 **시장가/지정가, 부분체결/전체체결을 별도 코드 경로로 분기하지 않는다.** 이유:

1. 실제 증권사 체결 데이터에서 "시장가라서 다르다"/"지정가라서 다르다"는 필드 스키마 차이가 아니다 — KIS `inquire-daily-ccld`는 주문 유형과 무관하게 **동일한 응답 스키마**를 쓴다(주문구분 필드 `ord_dvsn_cd`가 값으로 구분될 뿐, 응답 구조 자체가 달라지지 않는다).
2. "부분체결이라 특별하다"는 것도 사실은 착시다 — 완전체결은 "부분체결이 1번 만에 목표 수량에 도달한 특수 케이스"에 불과하다. 즉 **부분체결 처리 로직이 완전체결도 포함하는 일반형**이어야지, 그 반대(완전체결 로직에 부분체결을 나중에 끼워 넣는 것)여서는 안 된다.
3. 주문 유형별 분기는 새로운 주문 유형(예: IOC/FOK, 조건부주문)이 추가될 때마다 분기를 늘려야 하므로, 장기적으로 유지보수 비용이 커지고 "분기마다 같은 버그를 각각 따로 낳을" 위험이 있다.

대신 이 설계는 **"현재 이 주문의 누적 체결 상태를 관측하고, 직전 관측과의 차이를 계산한다"는 단일 원리**로 시장가/지정가/부분/전체 체결을 모두 같은 코드 경로에서 처리한다.

## 3. 제안 아키텍처 — 3계층 파이프라인

```
[KIS inquire-daily-ccld raw item]
        │
        ▼
① 정규화 계층 (Normalization)
   normalize_kis_fill_observation(raw_item)
   → NormalizedKisFillObservation
        │
        ▼
② 누적→증분 해석 계층 (Incremental Resolution)
   resolve_incremental_fill(normalized, persisted_state)
   → IncrementalFillDecision
     (no_new_fill | new_fill(delta_qty, inferred_price) | anomaly)
        │
        ▼ (new_fill 인 경우에만)
③ 기존 적재 경로 (변경 없음)
   FillEvent 생성 → order_sync_service._sync_fills()의 기존 dedup
   → fill_events.add() → _apply_realized_pnl_ledger_hook()
   → RealizedPnlLedgerService.apply_fill()
```

①, ②는 신규다. ③은 **기존 코드 그대로 재사용**한다 — `get_fills()`의 반환 타입(`Sequence[FillEvent]`)과 호출 계약은 바꾸지 않는다. 즉 `order_sync_service.py`/`_sync_fills()` 쪽 변경은 최소화되고, 변경은 `get_fills()` 내부 구현(그리고 그 구현이 호출하는 신규 정규화/해석 계층)에 국한된다.

### 3.1 ① 정규화 계층

```python
@dataclass(slots=True, frozen=True)
class NormalizedKisFillObservation:
    broker_native_order_id: str        # odno
    symbol: str                        # pdno
    side: OrderSide                    # sll_buy_dvsn_cd → OrderSide
    ordered_quantity: Decimal | None    # ord_qty
    cumulative_filled_quantity: Decimal | None   # tot_ccld_qty (fallback ccld_qty)
    average_fill_price: Decimal | None  # avg_prvs (fallback ccld_unpr)
    fill_time_candidate: str | None     # ccld_tmd → infm_tmd → ord_tmd (best-effort, 인과 시각 아님)
    order_status_raw: str | None       # ord_stat → ccld_cndt_name → ord_dvsn_name
    cancel_yn: str | None
    rvse_yn: str | None
    broker_fill_id_candidate: str | None  # ccld_num (best-effort, 없을 수 있음)
    raw_field_fingerprint: str          # 관측/디버깅용 해시(원문 미저장)
    is_parseable: bool                  # 필수 필드(odno/pdno/side) 확보 여부
```

핵심 규칙:
- 필드 조회는 **후보 키 목록 + 대소문자 무관** 방식으로 통일한다. 예: `cumulative_filled_quantity`는 `["TOT_CCLD_QTY", "CCLD_QTY"]` 순서로 시도, `average_fill_price`는 `["AVG_PRVS", "CCLD_UNPR"]` 순서로 시도. 이 후보 목록은 **환경별 `if paper/live` 분기가 아니라 데이터(순서가 있는 리스트)로 표현**한다 — paper/live 차이는 "어떤 후보가 먼저 매칭되는가"로 자연히 흡수되고, 코드 분기는 필요 없다.
- 이 후보 키 목록과 대소문자 무관 조회는 `fill_history_sync.py`의 `_get_kis_value()` + `KISRestClient._get_kis_field()`와 **완전히 동일한 로직**이어야 한다. 현재 이 로직이 두 곳(`get_fills()`가 써야 할 곳, `fill_history_sync.py`가 이미 쓰는 곳)에 각각 존재/부재하는 상태이므로, 공통 모듈로 추출한다(4절 참고).
- `raw_field_fingerprint`는 원문 그대로가 아니라 "정렬된 키 목록 + 각 값의 존재 여부"를 해시한 값이다 — 로그에 원문을 남기지 않으면서도 "이번 응답의 필드 구성이 이전과 달라졌는가"를 관측할 수 있게 한다.
- 필수 필드(`odno`, `pdno`, `side`) 중 하나라도 없으면 `is_parseable=False`로 표시하고, ②에서 즉시 `anomaly`로 처리한다(추측으로 채우지 않는다).

### 3.2 ② 누적→증분 해석 계층 — 설계의 핵심

#### 대안 비교

| 대안 | 설명 | 장점 | 단점 | 채택 여부 |
|---|---|---|---|---|
| **안 A** — 누적 스냅샷으로 간주 + 직전 관측과의 차이로 증분 계산 | 매 관측을 "지금까지의 누적 체결량"으로 보고, 직전에 영속적으로 저장해둔 값과의 차이(delta)만 증분 fill로 인정 | 폴링 주기·재시도·주문 유형과 무관하게 **하나의 원리**로 안전하게 동작. 같은 응답을 몇 번 다시 읽어도(delta=0) 안전(자연히 idempotent) | 직전 관측치를 어딘가에 **영속적으로** 보관해야 함(프로세스 재시작에도 살아남아야 함) → 신규 상태 저장소 필요 | **채택(기본 전략)** |
| **안 B** — 응답 row 자체를 fill event로 간주, 직전 최대 체결수량과 비교해 증분만 인정 | A와 유사하지만 "직전 최대치"를 별도 상태 없이 `fill_events` 자체에서 매번 재계산 시도 | 신규 테이블 불필요해 보임 | 실제로는 "직전 최대치를 어디서 구하는가" 문제가 그대로 남는다 — 결국 `fill_events`를 매번 전부 다시 읽어 최대 누적치를 추론해야 하므로, A와 동일한 상태 추적이 필요해지고 매번 전체 스캔 비용만 추가된다. **A로 수렴하는 열등한 변형**이라 단독으로는 기각 | 기각(A에 흡수) |
| **안 C** — 별도 "KIS fill observation state"를 둬서 안전하게 증분 변환 후 append | A의 "직전 관측치 영속 저장"을 명시적인 **상태 테이블**로 구현 | A의 전략을 프로세스 재시작·동시 폴러(post_submit_sync + fill_sync 등 복수 경로)에도 안전하게 만든다. 원장(`fill_events`)과 "브로커 원문 관측 상태"를 분리해 책임이 명확해진다(12번 문서의 "브로커 원장값 vs 우리 내부 계산값 대사" 철학과 일치) | 신규 테이블 1개 추가(스키마 변경) | **채택(A의 구현 메커니즘으로 채택)** |

**결론**: 안 A를 전략으로 채택하고, 안 C(전용 상태 테이블)를 그 구현 메커니즘으로 채택한다. 안 B는 안 A로 수렴하는 열등한 변형이므로 기본안에서 제외한다.

#### 신규 상태: `kis_fill_cumulative_state` (제안, 이번 턴 미구현)

```
kis_fill_cumulative_state
- account_id              (uuid, FK)
- broker_name             (varchar)
- broker_native_order_id  (varchar)
- last_cumulative_filled_quantity  (numeric)
- last_average_fill_price          (numeric)
- last_observed_at                 (timestamptz)   -- 우리가 관측한 시각(브로커 체결 시각 아님)
- last_raw_field_fingerprint       (varchar)
- created_at / updated_at
UNIQUE (account_id, broker_name, broker_native_order_id)
```

이 테이블은 `position_cost_basis_state`(12번 문서 4.1절)와 **역할이 다르다** — `position_cost_basis_state`는 "종목별 이동평균 원가" 상태이고, `kis_fill_cumulative_state`는 "이 주문번호에 대해 브로커가 마지막으로 보고한 누적 체결량"이라는, 훨씬 좁고 기술적인 상태다. 이 둘을 합치지 않는다 — 전자는 도메인(ledger) 상태이고 후자는 브로커 관측(observation) 상태로, 책임을 분리해야 12번 문서의 "브로커 원장값과 우리 내부 계산값 대사" 원칙(9.2절)에 맞다.

#### 해석 로직

```python
async def resolve_incremental_fill(
    normalized: NormalizedKisFillObservation,
    state_repo: KisFillCumulativeStateRepository,
    account_id: UUID,
) -> IncrementalFillDecision:
    if not normalized.is_parseable:
        return IncrementalFillDecision.anomaly("unparseable_fields")

    prior = await state_repo.get(account_id, normalized.broker_native_order_id)
    prior_qty = prior.last_cumulative_filled_quantity if prior else Decimal("0")
    prior_price = prior.last_average_fill_price if prior else None

    current_qty = normalized.cumulative_filled_quantity or Decimal("0")
    delta_qty = current_qty - prior_qty

    if delta_qty == 0:
        return IncrementalFillDecision.no_new_fill()

    if delta_qty < 0:
        # 누적 체결량이 줄어듦 — 취소/정정/재시작 등 예상 밖 상황.
        # 절대 음수 fill을 만들지 않는다. anomaly로 남기고 사람/추가 조사로 넘긴다.
        return IncrementalFillDecision.anomaly("negative_delta")

    # delta_qty > 0 — 신규 증분. 평균단가는 가중평균 분해로 추정한다.
    inferred_price = _infer_delta_price(
        current_qty=current_qty, current_avg=normalized.average_fill_price,
        prior_qty=prior_qty, prior_avg=prior_price,
    )
    return IncrementalFillDecision.new_fill(delta_qty=delta_qty, price=inferred_price)
```

`_infer_delta_price`는 가중평균 분해 공식을 쓴다:

```
delta_price = (current_avg * current_qty - prior_avg * prior_qty) / delta_qty
```

`prior_qty == 0`(첫 관측, 완전체결 1회성 포함)인 경우 `delta_price == current_avg`로 자연히 수렴한다 — **완전체결과 부분체결이 같은 공식으로 처리되는 지점이 바로 여기다.**

이 가격은 **KIS가 직접 준 "이번 체결의 가격"이 아니라 추정값**이라는 점을 반드시 로그와 문서에 남긴다(6절 참고). 정정(정정주문)이 섞이면 이 추정이 어긋날 수 있으므로, `rvse_yn='Y'`(정정여부) 관측 시에는 자동 증분 처리를 하지 않고 `anomaly("revision_flagged")`로 분리한다(7절 참고).

`state_repo.get()` → 계산 → `state_repo.upsert()`(새 누적치 저장) 전 과정은 **단일 DB 트랜잭션 + 해당 상태 행에 대한 row lock**으로 감싼다. 이유: `post_submit_sync`(30초 주기)와 향후 추가될 수 있는 다른 폴러가 동시에 같은 주문을 조회할 가능성을 배제할 수 없고, 이 계층의 정확성은 전적으로 "직전 관측치와의 비교"에 의존하므로 경쟁 조건(race condition)이 발생하면 증분이 중복 계산될 수 있다. `fill_events`의 기존 dedup(broker_fill_id/composite key)은 **2차 방어선**일 뿐, 이 락이 **1차 방어선**이다.

### 3.3 ③ 기존 적재 경로 (변경 없음)

`IncrementalFillDecision.new_fill(delta_qty, price)`인 경우에만 기존 `FillEvent` 생성 로직으로 넘긴다:

```python
FillEvent(
    broker_order_id=...,
    symbol=normalized.symbol,
    side=normalized.side,
    fill_quantity=decision.delta_qty,      # 증분값 — 절대 누적값 아님
    fill_price=decision.inferred_price,
    fill_timestamp=... ,                   # 아래 "시간 필드" 참고
    broker_fill_id=normalized.broker_fill_id_candidate,  # best-effort, None 가능
)
```

`order_sync_service._sync_fills()`의 기존 dedup(broker_fill_id 우선, 없으면 composite key)은 **그대로 둔다** — 삭제하지 않는다. `broker_fill_id_candidate`가 paper 응답에서 늘 채워지는지 확인되지 않았으므로(이번 조사 표본에는 `ccld_num` 필드가 `KisOrderFillRecord`에는 정의돼 있으나, 실제 응답에 채워졌는지 별도 재확인 필요 — 미확정 영역), composite key fallback이 계속 필요하다.

**시간 필드**: `fill_timestamp`는 KIS가 "이번 체결"에 대한 정확한 시각을 주지 않는다(이미 `get_fills()` 기존 코드 주석에 "KIS doesn't provide per-fill timestamp"로 명시돼 있다). 이 설계도 그 한계를 그대로 인정한다 — `fill_time_candidate`(ccld_tmd→infm_tmd→ord_tmd)가 있으면 그 날짜+시각을 쓰고, 없으면 관측 시각(now)을 쓴다. 이 값은 "체결이 실제로 일어난 시각"이 아니라 "우리가 그 사실을 알게 된 시각에 가까운 근사치"임을 코드 주석과 이 문서에 명시한다.

## 4. `fill_history_sync.py`와의 정합성

- `KISRestClient._get_kis_field()`(대소문자 무관 단일 필드 조회)와 `fill_history_sync._get_kis_value()`(다중 후보 키 + 대소문자 무관)를 **공통 모듈로 추출**한다. 제안 위치: `agent_trading/brokers/koreainvestment/kis_field_mapping.py`(신규, 이번 턴 미생성) — `rest_client.py`, `fill_history_sync.py`, 그리고 신규 정규화 계층(`get_fills()` 내부)이 모두 이 모듈을 import한다.
- 후보 키 목록(`TOT_CCLD_QTY`→`CCLD_QTY`, `AVG_PRVS`→`CCLD_UNPR`, `CCLD_TMD`→`INFM_TMD`)은 **`fill_history_sync.py`가 이미 쓰는 순서를 그대로 따른다** — 새로 순서를 정하지 않는다. 이미 운영에서 검증된(비록 다른 목적이지만) fallback 순서이므로, 여기서 다르게 정할 이유가 없다.
- `get_order_status()`(`inquire-daily-ccld`의 또 다른 소비자, 상태 해석용)도 같은 공통 모듈을 쓰도록 정리할 수 있는지는 **이번 설계 범위 밖**으로 남긴다 — `get_order_status()`는 이미 자체적으로 `_get_kis_field()`를 쓰고 있어(대소문자 문제는 없음) 이번 문제와 직접 관련이 적다. 다만 후속 정리 대상으로 언급만 해 둔다.
- **`fill_history_sync.py`와 신규 정규화/해석 계층은 서로 다른 저장소를 쓰며 합치지 않는다** — `fill_history_sync.py` → `broker_fill_snapshots`(대사 전용, 매번 새 스냅샷 행 insert, "지금까지 여러 번 관측한 이력"을 전부 보존)와, 신규 경로 → `fill_events`(도메인 원장, 증분만 append)는 **의도적으로 다른 저장 의미론**을 갖는다. 필드 해석 규칙만 공유하고, 저장 방식/목적은 그대로 분리 유지한다(12번 문서가 이미 이 경계를 "replay 입력 아님"으로 명시).

## 5. Idempotency / dedup / replay 관점

- **1차 방어선**: `kis_fill_cumulative_state`의 행 단위 트랜잭션 락 + delta 계산 — 같은 누적치를 두 번 읽으면 delta=0이 되어 안전하게 아무 것도 하지 않는다.
- **2차 방어선**: 기존 `fill_events` dedup(broker_fill_id 우선, 없으면 composite key `(broker_order_id, fill_timestamp, fill_price, fill_quantity)`) — 변경 없음.
- **replay(재계산) 관점**: `RealizedPnlLedgerService`/`realized_pnl_recompute_service.py`의 recompute 경로는 `fill_events`를 유일한 1차 입력으로 삼는다는 기존 계약(12번 문서, `realized_pnl_recompute_service.py` docstring)을 그대로 유지한다. `kis_fill_cumulative_state`는 recompute의 입력이 아니다 — 이 상태가 손상되거나 재구축이 필요해도(예: 수동 정정), `fill_events`에 이미 append된 사실 자체는 바뀌지 않는다. 즉 `kis_fill_cumulative_state`는 "다음 관측을 올바르게 해석하기 위한 캐시성 상태"이지 "진실의 원천"이 아니다 — 진실의 원천은 여전히 append된 `fill_events`다.
- **anomaly(음수 delta, 파싱 실패, 정정 플래그) 처리**: `fill_events`에 아무것도 append하지 않고, 별도 관측 로그(6절)로만 남긴다. 이 주문은 자동으로 "체결 없음"으로 취급되지 않는다 — 기존 `_infer_sell_order_fill_via_position()`/`_infer_buy_order_fill_via_position_safe()` 포지션 델타 기반 fallback이 이미 주문 **상태**(FILLED 등) 해소를 담당하고 있으므로, 이 설계는 그 fallback과 충돌하지 않고 "ledger 반영"만 보류한다. 이 주문은 향후 `realized_pnl_recompute_queue`에 수동/배치로 편입해 재처리할 수 있는 후보로 남긴다(자동 편입은 이번 설계 범위 밖 — 사람이 원인을 확인한 뒤 편입하는 것을 기본으로 한다).

## 6. 관측/로그/검증 전략

- 로그 레벨: 이전 조사에서 운영 로그가 `logging.basicConfig(level=logging.INFO)`로 고정돼 DEBUG 로그가 전혀 보이지 않는다는 사실이 확인됐다. 따라서 이 경로의 핵심 관측 로그는 **INFO 레벨**로 남긴다(디버깅 목적이라고 DEBUG에 묻지 않는다):
  - `kis_fill_observation: order=<mask> cumulative_qty=<n> prior_qty=<n> delta=<n> action=<no_new_fill|new_fill|anomaly:<reason>>`
- 원문 응답 본문은 로그에 남기지 않는다 — `raw_field_fingerprint`(정렬된 키 존재 여부 해시)만 남긴다.
- anomaly는 `logger.warning`으로 남기고 카운터를 집계한다(예: `anomaly_negative_delta_count`, `anomaly_unparseable_count`, `anomaly_revision_flagged_count`) — 향후 운영 점검(이번 세션에서 이미 구축한 loss-cut-shadow inspection API 패밀리와 같은 성격의) inspection 지표로 노출할 수 있는 형태로 설계하되, **이번 턴에서 API를 만들지는 않는다**.
- **live 전개 전 필수 검증**(구현 이후, 이 설계 문서가 요구하는 최소 조건):
  1. live(실전) 계좌로 최소 1건의 완전체결 read-only 조회를 실행해, paper와 같은 후보 키 순서로 필드가 해석되는지 확인.
  2. 자연 발생하는 부분체결 주문을 최소 1건 이상, 2회 이상의 서로 다른 누적치 관측으로 확보해 "delta_qty가 실제로 새 체결분과 일치하는지"(포지션 스냅샷 변화, `broker_fill_snapshots` 값과 대조)를 확인.
  3. 정정(정정주문, `rvse_yn='Y'`)이 섞인 표본을 최소 1건 확보해 anomaly 분기가 올바르게 동작하는지 확인.
  4. 위 1~3이 모두 확인되기 전까지는, **shadow 모드**(아래 참고)로만 운용한다.

### 6.1 Shadow 모드 선행 운용 (강력 권장)

이 저장소에는 이미 "정책을 바로 실전 반영하지 않고, 관측 전용 shadow로 먼저 켜서 운영 데이터를 충분히 모은 뒤 판단한다"는 선례(`loss_cut_shadow` — [`13_loss_cut_policy_specification_and_config_path_design.md`](13_loss_cut_policy_specification_and_config_path_design.md))가 있다. 이 설계도 같은 원칙을 따르는 것을 권장한다:

- 1단계(shadow): `resolve_incremental_fill()`의 판단 결과를 **로그로만** 남기고, 실제 `fill_events.add()`/`RealizedPnlLedgerService.apply_fill()` 호출은 하지 않는다(feature flag로 분리).
- 2단계(관측): 일정 기간(예: 며칠~1~2주, 실제 체결 빈도에 따라 조정) 동안 shadow 로그를 쌓아 "delta 계산이 실제 체결과 얼마나 잘 맞는지" 사람이 확인한다.
- 3단계(전환): 확신이 서면 flag를 켜서 실제 append를 시작한다.

이 3단계 접근은 이번 설계 문서의 필수 요구사항은 아니지만(실행 계획 문서에서 채택 여부를 별도 결정), append-only 경로의 되돌리기 어려움(1.4절)을 고려하면 강하게 권장한다.

## 7. 정정/취소 처리 (7.3절과의 연결)

12번 문서 7.3절은 "같은 fill_event_id로 두 번째 행을 만들 수 없어 정정은 upsert 방식으로만 처리한다"는 제약을 이미 확인했다. 이 설계는 그 제약을 그대로 존중한다:
- `cancel_yn='Y'` 또는 `rvse_yn='Y'`가 관측되면, 이 설계는 **자동으로 증분을 계산하지 않고 anomaly로 분리**한다.
- 정정/취소가 실제 이동평균 원가에 미치는 영향을 자동으로 역산하는 로직은 이번 설계에 포함하지 않는다 — 표본이 없어 안전하게 설계할 근거가 부족하다. 이 부분은 실제 정정/취소 표본을 확보한 뒤 별도 설계 턴에서 다룬다.

## 8. paper/live 차이 흡수 방식 (요약)

- 코드 구조상 `if env == "paper": ... else: ...` 같은 분기를 **정규화 계층에 두지 않는다.**
- 대신 후보 키 목록(순서가 있는 리스트)을 하나의 데이터 구조로 두고, 대소문자 무관 조회 헬퍼가 그 목록을 순서대로 시도한다 — paper가 `tot_ccld_qty`(소문자)를 주면 그것이 매칭되고, live가 `CCLD_QTY`(대문자, 종전 가정)를 준다면 그것이 매칭된다. **환경 차이는 "어떤 후보가 매칭됐는가"라는 관측 결과로 자연히 드러나고, 코드는 하나만 유지된다.**
- 다만 이건 "설계상 안전한 방식"이라는 것이지 "live에서도 반드시 이렇게 동작할 것"이라는 보장은 아니다 — 3.1절 후보 키 목록에 **live 전용 필드명이 이번 조사에서 직접 확인되지 않았다는 점**은 6절의 필수 사전 검증 항목으로 남긴다.

## 9. 이번 설계가 명시적으로 다루지 않는 것 (범위 밖)

- `get_order_status()` 쪽 필드 해석 통합(9절 언급 수준으로만 남김).
- 정정/취소의 자동 역산 로직(7절, 향후 별도 설계).
- `kis_fill_cumulative_state`의 실제 migration/스키마 확정 SQL(실행 계획 문서에서 별도 턴으로 진행).
- inspection API를 통한 anomaly 카운터 노출(6절에서 향후 후속으로만 언급).
- live 환경 실제 검증(6절의 사전 검증 항목으로 남김 — 이 설계 문서 자체는 이 검증을 수행하지 않는다).
