"""``broker_fill_snapshots`` 기반 과거 체결 synthetic ``fill_events`` backfill.

설계 근거: docs/00_foundational_design/detailed_design/16_broker_fill_
snapshot_historical_backfill_design.md (§3 모집단 제한, §4 변환 규칙,
§5 저장 경로, §6 idempotency/감사, §7 recompute 연결).

이 모듈은 **과거 복원(backfill) 전용**이다. 14번/15번 문서가 다루는
실시간 ``get_fills()``/``_sync_fills()``/truth-probe 경로는 이 모듈이
전혀 건드리지 않는다 — 이 모듈은 ``broker_fill_snapshots``(대사 전용
관측 테이블)만 입력으로 읽는다.

두 단계로 나뉜다.

1. :func:`build_backfill_plan` — read-only. 계좌×종목 하나에 대해 16번
   문서 §3.3의 원가 완결성 기준을 실제로 판정하고, 통과하면 snapshot
   시계열로부터 synthetic fill 후보 목록을 계산한다. DB에 아무것도
   쓰지 않는다 — dry-run 리포트와 실제 apply가 **정확히 같은 이 함수의
   출력**을 공유하게 하기 위한 설계다(16번 문서 §5.2, "dry-run 결과와
   실제 append 결과가 같은 코드 경로를 타야 한다").
2. :func:`apply_backfill_plan` — :func:`build_backfill_plan`이 만든
   계획을 실제로 ``fill_events``에 append하고(idempotent),
   ``realized_pnl_recompute_queue``에 등록한다. ``plan.eligible``이
   ``False``이면 아무것도 쓰지 않는다.

원가 완결성 판정에 쓰는 "완전 청산 시작점"은 ``position_snapshots``에서
``quantity == 0``인 가장 최근 관측을 찾는 방식으로 구현한다(브로커가
보고하는 잔량은 이 시스템의 ``order_requests``/``fill_events`` 상태와
독립적인 관측이므로, 원가 시작점 판정에 쓰기에 적합한 별도 소스다).

시장가/지정가, 부분체결/전체체결 분기는 없다 — snapshot 1건(완전체결
1회성)과 다건(부분체결 staircase)이 §4.2와 동일하게 "직전 관측치와의
차이" 하나의 공식으로 처리된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from agent_trading.domain.entities import (
    FillEventEntity,
    PositionCostBasisStateEntity,
    RealizedPnlRecomputeQueueEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, RealizedPnlFeeTaxSource
from agent_trading.repositories.filters import OrderQuery
from agent_trading.services.kis_fee_tax_policy import compute_fee_tax
from agent_trading.services.kis_fill_incremental_resolver import _infer_delta_price

if TYPE_CHECKING:
    from agent_trading.domain.entities import BrokerFillSnapshotEntity
    from agent_trading.repositories.container import RepositoryContainer

_KST = timezone(timedelta(hours=9))

# ``OrderQuery``에는 ``instrument_id`` 필터가 없다(기존 한계,
# ``realized_pnl_recompute_service.py`` 모듈 docstring과 동일) — 계좌 전체
# 주문을 가져온 뒤 애플리케이션에서 종목으로 거른다. 실무상 도달하기
# 어려운 큰 값을 명시한다.
_ORDER_LOOKUP_LIMIT = 100_000

__all__ = [
    "BackfillExclusionReason",
    "BackfillAnchorType",
    "SyntheticFillCandidate",
    "OrderBackfillDetail",
    "BackfillPlan",
    "BackfillApplyResult",
    "build_backfill_plan",
    "apply_backfill_plan",
]


class BackfillExclusionReason:
    """16번 문서 §3.3/§3.4/§4.3의 제외 사유 상수.

    ``str`` 상수로 유지한다 — ``realized_pnl_recompute_queue.reason_code``
    등 이 저장소의 기존 reason 계열 필드와 같은 관례(str, 향후 값이 늘어날
    수 있는 계열)를 따른다.
    """

    NO_FILLED_ORDERS_IN_WINDOW = "no_filled_orders_in_window"
    ZERO_CROSSING_NOT_FOUND = "zero_crossing_not_found"
    GAP_ORDER_BEFORE_WINDOW = "gap_order_before_window"
    SNAPSHOT_MISSING = "snapshot_missing"
    CANCEL_FLAG_PRESENT = "cancel_flag_present"
    NEGATIVE_DELTA = "negative_delta"
    UNPRICEABLE_DELTA = "unpriceable_delta"
    FINAL_QUANTITY_MISMATCH = "final_quantity_mismatch"
    LINEAGE_INCONSISTENT = "lineage_inconsistent"


class BackfillAnchorType:
    """원가 완결성 판정에 실제로 쓰인 anchor 종류(설계 근거: 16번 문서 §8.12).

    ``BackfillPlan.eligible=True``일 때만 의미가 있다(``False``면 ``None``).

    - ``ZERO_CROSSING``: 첫 주문 이전 ``position_snapshots``에서
      ``quantity == 0``인 관측이 발견된 경우(기존 §3.3-1 방식).
    - ``INITIAL_ENTRY``: 이 계좌×종목에 대해 ``window_start``(``--start-date``)
      이전 filled 주문 자체가 전혀 없는 경우. "잔고가 0이었다는 관측"이
      아니라 "그 수량을 바꿀 방법(주문 체결) 자체가 존재하지 않았다"는
      논리적으로 더 강한 사실이다 — zero-crossing 스냅샷의 대체재가
      아니라 별도의, 오히려 더 강한 anchor로 취급한다. ``001450``/`004370`
      과 달리 이 anchor는 스냅샷이 아니라 주문 이력 부재로 판정되므로
      ``zero_crossing_at``은 ``None``이다.
    """

    ZERO_CROSSING = "zero_crossing"
    INITIAL_ENTRY = "initial_entry"


@dataclass(slots=True, frozen=True)
class SyntheticFillCandidate:
    """snapshot 시계열에서 계산된 증분 fill 1건.

    ``fill_quantity``는 반드시 증분값이다(누적값 아님) — 14번 문서
    3.2절과 동일한 의미론.
    """

    order_request_id: UUID
    broker_order_id: UUID
    broker_native_order_id: str
    symbol: str
    side: OrderSide
    fill_quantity: Decimal
    fill_price: Decimal
    fill_timestamp: datetime
    broker_fill_id: str | None
    source_broker_fill_snapshot_id: UUID
    fee: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    fee_tax_source: RealizedPnlFeeTaxSource = RealizedPnlFeeTaxSource.ASSUMED_ZERO


@dataclass(slots=True, frozen=True)
class OrderBackfillDetail:
    """계획 안의 개별 주문 처리 결과(진단/리포트용)."""

    order_request_id: UUID
    side: OrderSide
    requested_quantity: Decimal
    snapshot_count: int
    final_cumulative_quantity: Decimal | None
    candidates: tuple[SyntheticFillCandidate, ...] = field(default_factory=tuple)


@dataclass(slots=True, frozen=True)
class BackfillPlan:
    """:func:`build_backfill_plan`의 결과 — dry-run 리포트와 apply가 공유한다."""

    account_id: UUID
    instrument_id: UUID
    start_date: date
    eligible: bool
    exclusion_reason: str | None
    zero_crossing_at: datetime | None
    order_details: tuple[OrderBackfillDetail, ...]
    synthetic_fills: tuple[SyntheticFillCandidate, ...]
    expected_final_quantity: Decimal
    broker_reported_quantity: Decimal | None
    broker_reported_quantity_matches: bool | None
    anchor_type: str | None = None
    """어느 anchor로 원가 완결성을 인정받았는지 — ``BackfillAnchorType``의
    값 중 하나(``eligible=False``면 ``None``). ``ZERO_CROSSING``이면
    ``zero_crossing_at``에 그 스냅샷 시각이 채워지고, ``INITIAL_ENTRY``면
    ``zero_crossing_at``은 ``None``이다."""


@dataclass(slots=True, frozen=True)
class BackfillApplyResult:
    """:func:`apply_backfill_plan`의 결과."""

    account_id: UUID
    instrument_id: UUID
    applied: bool
    fills_appended: int
    fills_skipped_duplicate: int
    recompute_queue_item_id: UUID | None


def _kst_midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time(0, 0, 0), tzinfo=_KST).astimezone(timezone.utc)


async def _list_filled_orders_for_instrument(
    repos: "RepositoryContainer",
    *,
    account_id: UUID,
    instrument_id: UUID,
) -> list:
    """이 계좌×종목의 **전체 기간** filled 주문을 시간순으로 반환한다.

    원가 완결성 판정(§3.3)은 backfill 기간(``start_date``)보다 앞선
    시점의 주문까지 봐야 하므로, 여기서는 기간을 제한하지 않는다 —
    기간 필터는 호출자가 적용한다.
    """
    orders = await repos.orders.list(
        OrderQuery(account_id=account_id, limit=_ORDER_LOOKUP_LIMIT)
    )
    matching = [
        o
        for o in orders
        if o.instrument_id == instrument_id and o.status == OrderStatus.FILLED
    ]
    matching.sort(key=lambda o: o.created_at or datetime.min.replace(tzinfo=timezone.utc))
    return matching


def _snapshot_sort_key(snapshot: "BrokerFillSnapshotEntity"):
    updated_at = snapshot.updated_at or datetime.min.replace(tzinfo=timezone.utc)
    return (updated_at, snapshot.filled_quantity)


async def _maybe_override_with_historical_policy_estimate(
    repos: "RepositoryContainer",
    *,
    client_id: UUID,
    environment,
    asset_class: str,
    market_segment: str | None,
    side: OrderSide,
    fill_price: Decimal,
    fill_quantity: Decimal,
    base_fee: Decimal,
    base_tax: Decimal,
    base_fee_tax_source: RealizedPnlFeeTaxSource,
) -> tuple[Decimal, Decimal, RealizedPnlFeeTaxSource]:
    """initial backfill 전용 historical BUY fee estimate override.

    ``compute_fee_tax()``의 시간 의미론(``get_active_at(fill_timestamp)``)은
    건드리지 않는다 — 이 함수는 그 결과(``base_*``)가 이미 ``ASSUMED_ZERO``
    로 나온 **BUY** fill에 대해서만, **현재 시각**을 넘겨 ``compute_fee_tax()``
    를 한 번 더 호출해 "지금 활성 정책을 적용하면 어떻게 계산되는지"를
    재조회한다. 이 두 번째 호출이 ``CALCULATED_FROM_POLICY``로 성립해야만
    (= 실제로 활성 정책이 있고 이 자산군/시장군이 지원 대상이어야만)
    override한다 — 그렇지 않으면(정책이 아직 없거나 비지원 자산군) 원래
    결과를 그대로 둔다. SELL은 무조건 원래 결과를 그대로 둔다(이번
    파일럿 범위 밖 — 설계 문서 16번 §8).
    """
    if side != OrderSide.BUY or base_fee_tax_source != RealizedPnlFeeTaxSource.ASSUMED_ZERO:
        return base_fee, base_tax, base_fee_tax_source

    estimate_result = await compute_fee_tax(
        repos,
        client_id=client_id,
        environment=environment,
        asset_class=asset_class,
        market_segment=market_segment,
        side=side,
        fill_price=fill_price,
        fill_quantity=fill_quantity,
        fill_timestamp=datetime.now(timezone.utc),
    )
    if estimate_result.fee_tax_source != RealizedPnlFeeTaxSource.CALCULATED_FROM_POLICY:
        return base_fee, base_tax, base_fee_tax_source

    return estimate_result.fee, Decimal("0"), RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE


async def build_backfill_plan(
    repos: "RepositoryContainer",
    *,
    account_id: UUID,
    instrument_id: UUID,
    start_date: date,
    use_historical_policy_estimate_for_buy_fee: bool = False,
) -> BackfillPlan:
    """16번 문서 §3.3 원가 완결성 기준을 판정하고, 통과하면 synthetic fill
    후보를 계산한다. **DB에 아무것도 쓰지 않는다.**

    ``use_historical_policy_estimate_for_buy_fee``:
        기본값 ``False`` — 꺼져 있으면 기존 동작과 100% 동일하다(모든
        BUY/SELL fee/tax는 그 체결 시각 기준 ``compute_fee_tax()`` 결과
        그대로).

        ``True``면, **BUY fill이고** 그 계산 결과가 ``ASSUMED_ZERO``일
        때(= 그 체결 당시엔 활성 정책이 없었던 경우)에 한해,
        :func:`_maybe_override_with_historical_policy_estimate`가 **현재
        활성 정책**으로 다시 계산을 시도한다. 그 재계산이
        ``CALCULATED_FROM_POLICY``로 성립하면(활성 정책이 실제로 있고
        자산군/시장군이 지원 대상이면) ``HISTORICAL_POLICY_ESTIMATE``로
        override하고, 그렇지 않으면(여전히 정책이 없거나 비대상 자산군)
        원래 결과를 그대로 둔다. SELL에는 이 옵션이 전혀 개입하지 않는다
        — ``compute_fee_tax()`` 자체의 시간 의미론(``get_active_at
        (fill_timestamp)``)은 이 옵션과 무관하게 절대 바뀌지 않는다;
        이 옵션은 그 위에 얹는 initial backfill 전용 선택적 후처리다
        (설계 근거: 16번 문서 §8, `001450`/`004370` 파일럿 — 둘 다
        SELL이 없는 BUY-only 종목이라 이 파일럿 범위에서는 SELL 분기가
        실측되지 않는다).
    """
    window_start = _kst_midnight_utc(start_date)

    all_filled_orders = await _list_filled_orders_for_instrument(
        repos, account_id=account_id, instrument_id=instrument_id
    )
    window_orders = [
        o for o in all_filled_orders if (o.created_at or window_start) >= window_start
    ]

    def _empty_plan(reason: str, zero_crossing_at: datetime | None = None) -> BackfillPlan:
        return BackfillPlan(
            account_id=account_id,
            instrument_id=instrument_id,
            start_date=start_date,
            eligible=False,
            exclusion_reason=reason,
            zero_crossing_at=zero_crossing_at,
            order_details=(),
            synthetic_fills=(),
            expected_final_quantity=Decimal("0"),
            broker_reported_quantity=None,
            broker_reported_quantity_matches=None,
        )

    if not window_orders:
        return _empty_plan(BackfillExclusionReason.NO_FILLED_ORDERS_IN_WINDOW)

    first_order_time = window_orders[0].created_at or window_start

    # §3.3-1: 완전 청산 시작점 — position_snapshots에서 quantity==0인
    # 가장 최근 관측을 첫 주문 이전에서 찾는다(ZERO_CROSSING anchor).
    # start_date로 하한을 제한하지 않는다 — 실제 zero-crossing이 backfill
    # 기간보다 앞설 수 있다(이번 조사에서 확인된 사례가 정확히 이 형태).
    zero_crossing_snapshot = await repos.position_snapshots.get_latest_by_account_and_instrument_before(
        account_id, instrument_id, before=first_order_time
    )

    anchor_type: str
    anchor_at: datetime | None

    if zero_crossing_snapshot is not None and zero_crossing_snapshot.quantity == Decimal("0"):
        anchor_type = BackfillAnchorType.ZERO_CROSSING
        anchor_at = zero_crossing_snapshot.snapshot_at

        # §3.3-2 보강: anchor와 첫 주문 사이에 "누락된" filled 주문이 있으면
        # (즉 anchor 이후 window_start 이전에 이미 filled된 주문이 있으면)
        # 원가가 이미 anchor 시점 이후 변했을 수 있으므로 제외한다 — 부분
        # 반영 금지 원칙(16번 문서 §2, §4.3)의 적용.
        gap_orders = [
            o
            for o in all_filled_orders
            if anchor_at < (o.created_at or anchor_at) < first_order_time
        ]
        if gap_orders:
            return _empty_plan(
                BackfillExclusionReason.GAP_ORDER_BEFORE_WINDOW, anchor_at
            )
    else:
        # §8.12(16번 문서): INITIAL_ENTRY anchor — window_start 이전에 이
        # 계좌×종목에 대한 filled 주문 자체가 전혀 없으면, zero-crossing
        # 스냅샷("잔고가 0이었다는 관측") 없이도 원가 완결성을 인정한다.
        # "주문 이력 전무"는 "잔고 0 관측"보다 논리적으로 더 강한 사실이다
        # — 수량이 바뀔 수 있는 유일한 경로(주문 체결) 자체가 없었으므로,
        # 그 이전 잔고가 0이 아니었을 가능성 자체가 없다. gap_orders 개념은
        # 이 경로에 적용되지 않는다 — anchor 정의 자체가 "window_start
        # 이전 filled 주문 전무"라 그 정의상 gap이 있을 수 없다.
        has_orders_before_window = any(
            (o.created_at or window_start) < window_start for o in all_filled_orders
        )
        # "매수가 그 종목의 첫 진입"이라는 전제(16번 문서 §8.12) 그대로
        # — window 안 첫 주문이 SELL이면 "주문 이력 전무"인 종목을 처음부터
        # 공매도한다는 뜻이라 논리적으로 성립하지 않는다. 이 경우는
        # INITIAL_ENTRY anchor로 인정하지 않고 기존과 동일하게 제외한다.
        if has_orders_before_window or window_orders[0].side != OrderSide.BUY:
            return _empty_plan(BackfillExclusionReason.ZERO_CROSSING_NOT_FOUND)
        anchor_type = BackfillAnchorType.INITIAL_ENTRY
        anchor_at = None

    # 이 시점부터 population은 anchor 이후 ~ 지금까지의 filled 주문
    # 전체다(ZERO_CROSSING이면 anchor~window_start 사이에는 gap_orders
    # 체크로, INITIAL_ENTRY면 정의 자체로 이미 없음을 확인했으므로
    # window_orders와 동일하다).
    population_orders = window_orders

    # 정책 기반 fee/tax 계산에 필요한 계좌/종목 정보를 이 호출당 한 번만
    # 조회한다(설계 문서 12번 13절) — order/snapshot마다 반복 조회하지
    # 않는다. account/instrument가 없으면(FK 무결성상 사실상 발생하지
    # 않아야 하지만) fee/tax 계산은 생략하고 assumed_zero로 남긴다 —
    # synthetic fill 복원 자체를 막지 않는다.
    account = await repos.accounts.get(account_id)
    instrument = await repos.instruments.get(instrument_id)

    order_request_ids = [o.order_request_id for o in population_orders]
    snapshots_by_order = await repos.broker_fill_snapshots.list_recent_by_order_ids(
        order_request_ids, limit_per_order=200
    )

    order_details: list[OrderBackfillDetail] = []
    all_candidates: list[SyntheticFillCandidate] = []
    running_quantity = Decimal("0")

    for order in population_orders:
        raw_snapshots = list(snapshots_by_order.get(order.order_request_id, []))
        if not raw_snapshots:
            return _empty_plan(BackfillExclusionReason.SNAPSHOT_MISSING, anchor_at)

        ordered_snapshots = sorted(raw_snapshots, key=_snapshot_sort_key)

        broker_native_order_ids = {s.broker_native_order_id for s in ordered_snapshots}
        if len(broker_native_order_ids) != 1:
            return _empty_plan(
                BackfillExclusionReason.LINEAGE_INCONSISTENT, anchor_at
            )
        broker_native_order_id = next(iter(broker_native_order_ids))

        broker_orders = await repos.broker_orders.list_by_order_request(
            order.order_request_id
        )
        matching_broker_orders = [
            bo for bo in broker_orders if bo.broker_native_order_id == broker_native_order_id
        ]
        if len(matching_broker_orders) != 1:
            return _empty_plan(
                BackfillExclusionReason.LINEAGE_INCONSISTENT, anchor_at
            )
        broker_order_id = matching_broker_orders[0].broker_order_id

        prior_qty = Decimal("0")
        prior_price: Decimal | None = None
        order_candidates: list[SyntheticFillCandidate] = []

        for snap in ordered_snapshots:
            if (snap.cancel_yn or "").strip().upper() == "Y":
                return _empty_plan(
                    BackfillExclusionReason.CANCEL_FLAG_PRESENT, anchor_at
                )

            current_qty = snap.filled_quantity
            delta_qty = current_qty - prior_qty
            if delta_qty < 0:
                return _empty_plan(
                    BackfillExclusionReason.NEGATIVE_DELTA, anchor_at
                )
            if delta_qty == 0:
                continue

            inferred_price = _infer_delta_price(
                current_qty=current_qty,
                current_avg=snap.fill_price,
                prior_qty=prior_qty,
                prior_avg=prior_price,
            )
            if inferred_price is None:
                return _empty_plan(
                    BackfillExclusionReason.UNPRICEABLE_DELTA, anchor_at
                )

            fill_ts = snap.fill_timestamp or snap.updated_at or datetime.now(timezone.utc)

            if account is not None and instrument is not None:
                fee_tax_result = await compute_fee_tax(
                    repos,
                    client_id=account.client_id,
                    environment=account.environment,
                    asset_class=instrument.asset_class,
                    market_segment=instrument.market_segment,
                    side=order.side,
                    fill_price=inferred_price,
                    fill_quantity=delta_qty,
                    fill_timestamp=fill_ts,
                )
                candidate_fee = fee_tax_result.fee
                candidate_tax = fee_tax_result.tax
                candidate_fee_tax_source = fee_tax_result.fee_tax_source
                if use_historical_policy_estimate_for_buy_fee:
                    candidate_fee, candidate_tax, candidate_fee_tax_source = (
                        await _maybe_override_with_historical_policy_estimate(
                            repos,
                            client_id=account.client_id,
                            environment=account.environment,
                            asset_class=instrument.asset_class,
                            market_segment=instrument.market_segment,
                            side=order.side,
                            fill_price=inferred_price,
                            fill_quantity=delta_qty,
                            base_fee=candidate_fee,
                            base_tax=candidate_tax,
                            base_fee_tax_source=candidate_fee_tax_source,
                        )
                    )
            else:
                candidate_fee = Decimal("0")
                candidate_tax = Decimal("0")
                candidate_fee_tax_source = RealizedPnlFeeTaxSource.ASSUMED_ZERO

            order_candidates.append(
                SyntheticFillCandidate(
                    order_request_id=order.order_request_id,
                    broker_order_id=broker_order_id,
                    broker_native_order_id=broker_native_order_id,
                    symbol=snap.symbol,
                    side=order.side,
                    fill_quantity=delta_qty,
                    fill_price=inferred_price,
                    fill_timestamp=fill_ts,
                    broker_fill_id=snap.broker_fill_id,
                    source_broker_fill_snapshot_id=snap.broker_fill_snapshot_id,
                    fee=candidate_fee,
                    tax=candidate_tax,
                    fee_tax_source=candidate_fee_tax_source,
                )
            )
            prior_qty = current_qty
            prior_price = snap.fill_price

        if prior_qty != order.requested_quantity:
            return _empty_plan(
                BackfillExclusionReason.FINAL_QUANTITY_MISMATCH, anchor_at
            )

        signed_delta = prior_qty if order.side == OrderSide.BUY else -prior_qty
        running_quantity += signed_delta

        order_details.append(
            OrderBackfillDetail(
                order_request_id=order.order_request_id,
                side=order.side,
                requested_quantity=order.requested_quantity,
                snapshot_count=len(ordered_snapshots),
                final_cumulative_quantity=prior_qty,
                candidates=tuple(order_candidates),
            )
        )
        all_candidates.extend(order_candidates)

    broker_latest = await repos.position_snapshots.list_latest_by_account(account_id)
    broker_reported_quantity: Decimal | None = None
    for snap in broker_latest:
        if snap.instrument_id == instrument_id:
            broker_reported_quantity = snap.quantity
            break

    matches = (
        broker_reported_quantity == running_quantity
        if broker_reported_quantity is not None
        else None
    )

    return BackfillPlan(
        account_id=account_id,
        instrument_id=instrument_id,
        start_date=start_date,
        eligible=True,
        exclusion_reason=None,
        zero_crossing_at=anchor_at,
        anchor_type=anchor_type,
        order_details=tuple(order_details),
        synthetic_fills=tuple(all_candidates),
        expected_final_quantity=running_quantity,
        broker_reported_quantity=broker_reported_quantity,
        broker_reported_quantity_matches=matches,
    )


def _composite_dedup_matches(
    existing: FillEventEntity, candidate: SyntheticFillCandidate
) -> bool:
    return (
        existing.fill_timestamp == candidate.fill_timestamp
        and existing.fill_price == candidate.fill_price
        and existing.fill_quantity == candidate.fill_quantity
    )


async def apply_backfill_plan(
    repos: "RepositoryContainer",
    plan: BackfillPlan,
    *,
    run_id: UUID | None = None,
) -> BackfillApplyResult:
    """:func:`build_backfill_plan`이 만든 계획을 실제로 반영한다.

    ``plan.eligible``이 ``False``이면 즉시 아무것도 쓰지 않고 반환한다
    (호출자가 이 안전장치를 우회할 방법이 없다 — 16번 문서 §2 "불확실하면
    복원하지 않는다"의 코드 레벨 강제).

    idempotency: ``broker_fill_id``가 있으면 기존 ``fill_events`` UNIQUE
    제약(``uq_fill_events_native``)에 의존하는 :meth:`FillEventRepository.
    get_by_broker_fill_id`로 선판별한다. 없으면 같은 ``broker_order_id``의
    기존 fill과 ``(fill_timestamp, fill_price, fill_quantity)`` composite
    key를 비교한다(``order_sync_service._sync_fills()``의 기존 dedup과
    같은 원리, 코드는 독립적으로 유지 — 16번 문서 §6.1).
    """
    if not plan.eligible:
        return BackfillApplyResult(
            account_id=plan.account_id,
            instrument_id=plan.instrument_id,
            applied=False,
            fills_appended=0,
            fills_skipped_duplicate=0,
            recompute_queue_item_id=None,
        )

    effective_run_id = run_id or uuid4()

    fills_appended = 0
    fills_skipped_duplicate = 0
    last_appended_fill_event_id: UUID | None = None

    # broker_order_id 단위로 기존 fill을 미리 모아 composite-key dedup에 쓴다.
    existing_by_broker_order: dict[UUID, list[FillEventEntity]] = {}

    for candidate in plan.synthetic_fills:
        if candidate.broker_fill_id:
            existing = await repos.fill_events.get_by_broker_fill_id(
                candidate.broker_fill_id
            )
            if (
                existing is not None
                and existing.broker_order_id == candidate.broker_order_id
            ):
                fills_skipped_duplicate += 1
                continue

        if candidate.broker_order_id not in existing_by_broker_order:
            existing_by_broker_order[candidate.broker_order_id] = list(
                await repos.fill_events.list_by_broker_order(candidate.broker_order_id)
            )

        if not candidate.broker_fill_id:
            duplicate = any(
                _composite_dedup_matches(existing, candidate)
                for existing in existing_by_broker_order[candidate.broker_order_id]
            )
            if duplicate:
                fills_skipped_duplicate += 1
                continue

        raw_payload_uri = (
            f"backfill:{effective_run_id}:"
            f"snapshot:{candidate.source_broker_fill_snapshot_id}"
        )
        new_fill = FillEventEntity(
            fill_event_id=uuid4(),
            broker_order_id=candidate.broker_order_id,
            fill_timestamp=candidate.fill_timestamp,
            fill_price=candidate.fill_price,
            fill_quantity=candidate.fill_quantity,
            source_channel="backfill",
            broker_fill_id=candidate.broker_fill_id,
            fill_fee=candidate.fee,
            fill_tax=candidate.tax,
            fee_tax_source=candidate.fee_tax_source.value,
            raw_payload_uri=raw_payload_uri,
        )
        saved = await repos.fill_events.add(new_fill)
        existing_by_broker_order[candidate.broker_order_id].append(saved)
        fills_appended += 1
        last_appended_fill_event_id = saved.fill_event_id

    recompute_queue_item_id: UUID | None = None
    if fills_appended > 0:
        existing_state = await repos.position_cost_basis_states.get(
            plan.account_id, plan.instrument_id
        )
        base_state = existing_state or PositionCostBasisStateEntity(
            account_id=plan.account_id,
            instrument_id=plan.instrument_id,
            quantity=Decimal("0"),
            average_cost=Decimal("0"),
        )
        await repos.position_cost_basis_states.upsert(
            replace(
                base_state,
                recompute_required=True,
                recompute_reason="manual_request",
            )
        )
        queue_item = await repos.realized_pnl_recompute_queue.add(
            RealizedPnlRecomputeQueueEntity(
                recompute_queue_id=uuid4(),
                account_id=plan.account_id,
                instrument_id=plan.instrument_id,
                reason_code="manual_request",
                triggering_fill_event_id=last_appended_fill_event_id,
            )
        )
        recompute_queue_item_id = queue_item.recompute_queue_id

    return BackfillApplyResult(
        account_id=plan.account_id,
        instrument_id=plan.instrument_id,
        applied=fills_appended > 0,
        fills_appended=fills_appended,
        fills_skipped_duplicate=fills_skipped_duplicate,
        recompute_queue_item_id=recompute_queue_item_id,
    )
