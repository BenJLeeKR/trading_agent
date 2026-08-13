"""KIS 누적 체결량(``TOT_CCLD_QTY``) → 증분 fill 해석 계층.

설계 근거: docs/00_foundational_design/detailed_design/14_kis_fill_
normalization_and_incremental_interpretation_design.md 3.2절(안 A + 안 C).

이 모듈은 ``services/`` 계층이다 — ``repositories/``를 통해 영속 상태
(``kis_fill_cumulative_state``)에 접근한다. ``brokers/`` 계층(``rest_
client.get_fills()``)은 이 모듈을 import하지 않는다 — 반대로 이 모듈이
브로커가 정규화해서 돌려준 "현재 누적 관측치"를 입력으로 받는다.

시장가/지정가, 부분체결/전체체결을 구분하는 분기는 없다 — 어떤 주문이든
"직전 관측치와의 차이를 계산한다"는 같은 원리로 처리한다. 완전체결은
``prior_qty=0``인 특수 케이스일 뿐이다.

핵심 안전 원칙: **불확실하면 append하지 않는다.** delta를 안전하게
증분으로 확정할 수 없는 모든 경우(음수 delta, 가격 역산 불가)는
``anomaly``로 분류되고, 상태도 갱신하지 않는다 — 다음 관측에서 다시
판단할 기회를 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from agent_trading.domain.entities import KisFillCumulativeStateEntity

if TYPE_CHECKING:
    from agent_trading.repositories.contracts import KisFillCumulativeStateRepository


class IncrementalFillDecisionKind(str, Enum):
    NO_NEW_FILL = "no_new_fill"
    NEW_FILL = "new_fill"
    ANOMALY = "anomaly"


@dataclass(slots=True, frozen=True)
class IncrementalFillDecision:
    kind: IncrementalFillDecisionKind
    delta_quantity: Decimal | None = None
    inferred_price: Decimal | None = None
    anomaly_reason: str | None = None

    @classmethod
    def no_new_fill(cls) -> IncrementalFillDecision:
        return cls(kind=IncrementalFillDecisionKind.NO_NEW_FILL)

    @classmethod
    def new_fill(cls, delta_quantity: Decimal, inferred_price: Decimal) -> IncrementalFillDecision:
        return cls(
            kind=IncrementalFillDecisionKind.NEW_FILL,
            delta_quantity=delta_quantity,
            inferred_price=inferred_price,
        )

    @classmethod
    def anomaly(cls, reason: str) -> IncrementalFillDecision:
        return cls(kind=IncrementalFillDecisionKind.ANOMALY, anomaly_reason=reason)


def _infer_delta_price(
    *,
    current_qty: Decimal,
    current_avg: Decimal | None,
    prior_qty: Decimal,
    prior_avg: Decimal | None,
) -> Decimal | None:
    """가중평균 분해로 이번 증분분의 가격을 역산한다.

    ``delta_price = (current_avg*current_qty - prior_avg*prior_qty) / delta_qty``

    ``prior_qty == 0``(첫 관측, 완전체결 1회성 포함)이면
    ``delta_price == current_avg``로 자연히 수렴한다 — 완전체결과
    부분체결이 같은 공식으로 처리되는 지점이다.

    KIS가 이번 관측에 평균단가를 주지 않았거나(``current_avg is None``),
    계산 결과가 음수/발산하면 ``None``을 반환해 호출자가 anomaly로
    분류하게 한다 — 추측으로 채우지 않는다.
    """
    if current_avg is None:
        return None
    delta_qty = current_qty - prior_qty
    if delta_qty <= 0:
        return None
    if prior_qty == 0 or prior_avg is None:
        return current_avg
    numerator = current_avg * current_qty - prior_avg * prior_qty
    if numerator < 0:
        return None
    return numerator / delta_qty


async def resolve_incremental_fill(
    *,
    state_repo: "KisFillCumulativeStateRepository",
    account_id: UUID,
    broker_name: str,
    broker_native_order_id: str,
    current_cumulative_quantity: Decimal,
    current_average_price: Decimal | None,
    raw_field_fingerprint: str | None = None,
    observed_at: datetime | None = None,
) -> IncrementalFillDecision:
    """직전 관측치와 비교해 이번 관측이 신규 증분인지 판정한다.

    Returns
    -------
    IncrementalFillDecision
        ``no_new_fill``(delta==0), ``new_fill``(delta>0, 가격 역산 성공),
        ``anomaly``(delta<0, 가격 역산 실패) 중 하나.

    Side effect
    -----------
    ``no_new_fill``/``new_fill``인 경우에만 ``kis_fill_cumulative_state``를
    이번 관측치로 upsert한다. ``anomaly``인 경우 상태를 갱신하지 않는다
    — 다음 관측에서 원인이 해소됐는지 다시 판단할 여지를 남긴다.
    """
    now = observed_at or datetime.now(timezone.utc)

    prior = await state_repo.get(
        account_id=account_id,
        broker_name=broker_name,
        broker_native_order_id=broker_native_order_id,
    )
    prior_qty = prior.last_cumulative_filled_quantity if prior is not None else Decimal("0")
    prior_price = prior.last_average_fill_price if prior is not None else None

    delta_qty = current_cumulative_quantity - prior_qty

    if delta_qty == 0:
        await state_repo.upsert(
            KisFillCumulativeStateEntity(
                kis_fill_cumulative_state_id=prior.kis_fill_cumulative_state_id
                if prior is not None
                else uuid4(),
                account_id=account_id,
                broker_name=broker_name,
                broker_native_order_id=broker_native_order_id,
                last_cumulative_filled_quantity=current_cumulative_quantity,
                last_average_fill_price=current_average_price or prior_price,
                last_observed_at=now,
                last_raw_field_fingerprint=raw_field_fingerprint,
            ),
        )
        return IncrementalFillDecision.no_new_fill()

    if delta_qty < 0:
        # 누적 체결량이 줄어듦 — 취소/정정/재시작 등 예상 밖 상황.
        # 절대 음수 fill을 만들지 않는다. 상태도 갱신하지 않는다.
        return IncrementalFillDecision.anomaly("negative_delta")

    inferred_price = _infer_delta_price(
        current_qty=current_cumulative_quantity,
        current_avg=current_average_price,
        prior_qty=prior_qty,
        prior_avg=prior_price,
    )
    if inferred_price is None:
        return IncrementalFillDecision.anomaly("unpriceable_delta")

    await state_repo.upsert(
        KisFillCumulativeStateEntity(
            kis_fill_cumulative_state_id=prior.kis_fill_cumulative_state_id
            if prior is not None
            else uuid4(),
            account_id=account_id,
            broker_name=broker_name,
            broker_native_order_id=broker_native_order_id,
            last_cumulative_filled_quantity=current_cumulative_quantity,
            last_average_fill_price=current_average_price,
            last_observed_at=now,
            last_raw_field_fingerprint=raw_field_fingerprint,
        ),
    )
    return IncrementalFillDecision.new_fill(delta_qty, inferred_price)
