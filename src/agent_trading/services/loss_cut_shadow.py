"""손실률 기반 Loss-cut **shadow 관측** 전용 순수 계산.

설계 근거: ``docs/00_foundational_design/detailed_design/13_loss_cut_
policy_specification_and_config_path_design.md`` §3.6.

**이 모듈은 어떤 실행 경로에도 개입하지 않는다.** 계산만 하고 값을
반환할 뿐, DB 쓰기·주문 제출·decision_type 변경은 전혀 하지 않는다
(그건 호출자인 ``decision_orchestrator.py``의 몫이며, 거기서도
``object.__setattr__``로 ``agent_bundle``을 바꾸는 어떤 guard 함수
목록에도 들어가지 않고, 그 목록이 전부 끝난 뒤 관측 전용으로만
호출된다).

``reverse_trade_hysteresis.py``의 순수 함수 스타일(입력 → 결과
dataclass, side effect 없음)을 그대로 따른다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

LOSS_CUT_SHADOW_TIER_SOFT = "soft"
LOSS_CUT_SHADOW_TIER_HARD = "hard"


@dataclass(slots=True, frozen=True)
class LossCutShadowVerdict:
    """loss-cut이 실제 정책이었다면 어떻게 판정됐을지의 가상 결과.

    ``triggered``/``tier``는 어디까지나 **가상** 판정이다 — 이 값이
    ``True``라고 해서 실제 decision_type/side/주문이 바뀌지 않는다.
    """

    triggered: bool
    """soft 또는 hard 임계치 중 하나라도 넘었으면 True."""

    tier: str | None
    """``"soft"`` | ``"hard"`` | ``None``(미발동). 둘 다 넘으면 더 심각한
    ``"hard"``를 우선한다."""

    loss_pct: Decimal | None
    """``(average_price - market_price) / average_price * 100``.
    양수 = 손실, 음수 = 이익. 계산 불가 시 ``None``."""

    skipped_reason: str | None
    """계산 자체를 못 한 이유(``"no_average_price"`` 등). 정상 계산됐으면
    ``None`` — ``triggered=False``와 구분하기 위한 필드(발동 안 함 vs
    계산 자체가 안 됨은 다른 의미)."""


def evaluate_loss_cut_shadow(
    *,
    average_price: Decimal | None,
    market_price: Decimal | None,
    soft_threshold_pct: Decimal,
    hard_threshold_pct: Decimal,
) -> LossCutShadowVerdict:
    """``average_price`` 대비 ``market_price``의 손실률을 계산해

    soft/hard 임계치와 비교한다. 순수 함수 — 아무것도 저장/변경하지
    않는다.

    기준 가격 정책(설계 문서 §3.4): ``average_price``는
    ``position_snapshot.average_price``(브로커 보고 평균단가)를 그대로
    쓴다. 이동평균 원가(``position_cost_basis_state.average_cost``)는
    쓰지 않는다 — 두 값을 섞으면 "기준에 따라 손실률이 달라지는" 혼란이
    생기기 때문이다(설계 문서에서 이미 확정한 원칙).
    """
    if average_price is None or average_price <= 0:
        return LossCutShadowVerdict(
            triggered=False, tier=None, loss_pct=None, skipped_reason="no_average_price"
        )
    if market_price is None or market_price <= 0:
        return LossCutShadowVerdict(
            triggered=False, tier=None, loss_pct=None, skipped_reason="no_market_price"
        )

    loss_pct = (average_price - market_price) / average_price * Decimal("100")

    if loss_pct >= hard_threshold_pct:
        return LossCutShadowVerdict(
            triggered=True, tier=LOSS_CUT_SHADOW_TIER_HARD, loss_pct=loss_pct, skipped_reason=None
        )
    if loss_pct >= soft_threshold_pct:
        return LossCutShadowVerdict(
            triggered=True, tier=LOSS_CUT_SHADOW_TIER_SOFT, loss_pct=loss_pct, skipped_reason=None
        )
    return LossCutShadowVerdict(
        triggered=False, tier=None, loss_pct=loss_pct, skipped_reason=None
    )
