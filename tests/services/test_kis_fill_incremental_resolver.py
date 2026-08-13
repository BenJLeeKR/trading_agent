from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.kis_fill_incremental_resolver import (
    IncrementalFillDecisionKind,
    resolve_incremental_fill,
)

_NOW = datetime.now(timezone.utc)


async def _resolve(repos, account_id, order_id, qty: str, price: str | None):
    return await resolve_incremental_fill(
        state_repo=repos.kis_fill_cumulative_state,
        account_id=account_id,
        broker_name="koreainvestment",
        broker_native_order_id=order_id,
        current_cumulative_quantity=Decimal(qty),
        current_average_price=Decimal(price) if price is not None else None,
        observed_at=_NOW,
    )


async def test_first_observation_full_fill_is_new_fill_with_delta_equal_to_quantity() -> None:
    """완전체결 1회성 표본 — prior_qty=0인 특수 케이스로, delta==현재 누적치."""
    repos = build_in_memory_repositories()
    decision = await _resolve(repos, uuid4(), "0000008019", "70", "26650")

    assert decision.kind == IncrementalFillDecisionKind.NEW_FILL
    assert decision.delta_quantity == Decimal("70")
    assert decision.inferred_price == Decimal("26650")


async def test_repeat_observation_of_same_cumulative_is_no_new_fill() -> None:
    """같은 누적치를 다시 조회 → delta=0, no_new_fill(멱등)."""
    repos = build_in_memory_repositories()
    account_id = uuid4()

    first = await _resolve(repos, account_id, "0000008019", "70", "26650")
    assert first.kind == IncrementalFillDecisionKind.NEW_FILL

    second = await _resolve(repos, account_id, "0000008019", "70", "26650")
    assert second.kind == IncrementalFillDecisionKind.NO_NEW_FILL
    assert second.delta_quantity is None


async def test_staircase_partial_then_full_produces_two_new_fill_deltas() -> None:
    """000227/2026-06-23 KST 자연 발생 부분체결 표본과 동일한 staircase(0→11→259).

    read-only 운영 조사로 확인된 실제 관측 패턴을 재현한다(설계 문서
    14번 1.2절). 두 번째 관측(11→259)에서 delta=248이 나와야 한다.
    """
    repos = build_in_memory_repositories()
    account_id = uuid4()

    partial = await _resolve(repos, account_id, "0000017158", "11", "10390")
    assert partial.kind == IncrementalFillDecisionKind.NEW_FILL
    assert partial.delta_quantity == Decimal("11")

    full = await _resolve(repos, account_id, "0000017158", "259", "10390")
    assert full.kind == IncrementalFillDecisionKind.NEW_FILL
    assert full.delta_quantity == Decimal("248")
    assert full.inferred_price == Decimal("10390")


async def test_negative_delta_is_anomaly_and_does_not_update_state() -> None:
    """누적 체결량이 줄어드는 것은 정상적으로 발생할 수 없다 — anomaly.

    상태를 갱신하지 않아야 한다 — 다음 관측에서 원인이 해소됐는지 다시
    판단할 여지를 남긴다(설계 문서 14번 3.2절).
    """
    repos = build_in_memory_repositories()
    account_id = uuid4()

    first = await _resolve(repos, account_id, "0000017158", "100", "10390")
    assert first.kind == IncrementalFillDecisionKind.NEW_FILL

    anomaly = await _resolve(repos, account_id, "0000017158", "50", "10390")
    assert anomaly.kind == IncrementalFillDecisionKind.ANOMALY
    assert anomaly.anomaly_reason == "negative_delta"

    state = await repos.kis_fill_cumulative_state.get(
        account_id=account_id,
        broker_name="koreainvestment",
        broker_native_order_id="0000017158",
    )
    assert state is not None
    assert state.last_cumulative_filled_quantity == Decimal("100"), (
        "anomaly 이후에도 직전 정상 관측치(100)가 그대로 유지돼야 한다"
    )


async def test_missing_average_price_on_new_fill_is_anomaly() -> None:
    """`AVG_PRVS`/`CCLD_UNPR` 둘 다 없어 가격을 역산할 수 없으면 anomaly —
    불확실하면 append하지 않는다는 원칙."""
    repos = build_in_memory_repositories()
    decision = await _resolve(repos, uuid4(), "0000099999", "10", None)

    assert decision.kind == IncrementalFillDecisionKind.ANOMALY
    assert decision.anomaly_reason == "unpriceable_delta"


async def test_different_orders_do_not_interfere_with_each_other() -> None:
    """계좌×주문번호 단위로 상태가 분리된다 — 다른 주문의 누적치와 섞이지 않는다."""
    repos = build_in_memory_repositories()
    account_id = uuid4()

    order_a = await _resolve(repos, account_id, "ORDER-A", "30", "1000")
    order_b = await _resolve(repos, account_id, "ORDER-B", "5", "2000")

    assert order_a.delta_quantity == Decimal("30")
    assert order_b.delta_quantity == Decimal("5")
