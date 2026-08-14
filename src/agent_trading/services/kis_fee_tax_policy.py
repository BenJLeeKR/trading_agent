"""정책 기반 fee/tax 계산 — paper/live 공통 진입점.

설계 근거: docs/00_foundational_design/detailed_design/
12_realized_pnl_moving_average_ledger.md 13절.

이 모듈은 실시간 경로(``order_sync_service._sync_fills()``)와 historical
backfill 경로(``historical_fill_backfill.py``)가 **공유하는 단일 계산
함수**(:func:`compute_fee_tax`)를 제공한다. paper/live로 코드를 분기하지
않는다 — 정책값(수수료율/세율/라운딩 규칙)은 ``config_versions``의
``execution.fee_tax`` 네임스페이스에서 ``environment``별로 다르게
조회될 뿐, 계산 로직 자체는 하나다. 시장가/지정가, 부분체결/전체체결
분기도 없다 — 이 함수는 이미 확정된 체결 1건(가격×수량)만 본다.

책임 분리
--------
1. :func:`parse_fee_tax_policy` — ``config_json`` → :class:`FeeTaxPolicy`
   파싱(순수 함수, repository 접근 없음).
2. ``_is_asset_supported`` — 자산군/시장군 지원 여부 판단.
3. ``_apply_rounding``/``_compute_amount`` — 수치 계산 + 라운딩.
4. :func:`compute_fee_tax` — 위 3단계를 조합하는 유일한 async 진입점
   (``config_versions.get_active_at()`` 조회만 수행).

판정 순서(설계 문서 13.1/13.2절과 동일, 절대 뒤집지 않는다)
-----------------------------------------------------------
1. 활성 정책 자체가 없으면(``get_active_at()`` → ``None``) 자산군 지원
   여부를 판단할 근거(``supported_asset_classes`` 목록)조차 없다 —
   ``ASSUMED_ZERO``.
2. 활성 정책은 있는데 ``config_json``의 ``execution.fee_tax`` 네임스페이스
   자체가 없으면 "이 계좌/환경에는 아직 fee/tax 정책이 설정되지 않았다"는
   뜻으로 ``ASSUMED_ZERO``.
3. 네임스페이스는 있는데 정책 구조가 깨져 있으면(필수 필드 누락/숫자 변환
   실패) :class:`MalformedFeeTaxPolicyError`를 던진다 — 조용히
   ``ASSUMED_ZERO``로 숨기지 않는다. "정책이 없다"와 "정책이 있는데
   깨졌다"는 서로 다른 상황이다.
4. 정책 구조가 온전하면, 자산군/시장군이 ``supported_asset_classes``/
   ``supported_market_segments``에 있는지 **먼저** 확인한다 — 아니면
   ``POLICY_NOT_APPLICABLE``(자산군 지원 여부 확인이 항상 먼저다).
5. 지원 대상인데 ``enabled=false``면 ``ASSUMED_ZERO``.
6. 지원 대상이고 활성화돼 있으면 실제로 계산해 ``CALCULATED_FROM_POLICY``.

이 모듈은 ``REPORTED``를 절대 만들지 않는다 — 그건 브로커가 직접 fee/tax를
보고하는 별개 경로의 몫이다(이번 설계 범위 밖).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agent_trading.domain.enums import Environment, OrderSide, RealizedPnlFeeTaxSource

if TYPE_CHECKING:
    from agent_trading.repositories.container import RepositoryContainer

__all__ = [
    "KisFeeTaxPolicyError",
    "MalformedFeeTaxPolicyError",
    "UnsupportedRoundingModeError",
    "FeeTaxPolicy",
    "FeeTaxResult",
    "parse_fee_tax_policy",
    "compute_fee_tax",
]


class KisFeeTaxPolicyError(ValueError):
    """fee/tax 정책 조회/계산 관련 오류의 공통 베이스."""


class MalformedFeeTaxPolicyError(KisFeeTaxPolicyError):
    """활성 정책의 ``execution.fee_tax`` 구조가 깨져 있는 경우.

    "정책 자체가 없는 경우"(``ASSUMED_ZERO``로 처리, 예외 아님)와 구분한다
    — 이건 "정책이 있는데 필수 필드가 없거나 숫자로 변환할 수 없다"는
    뜻이라 조용히 넘기지 않고 예외로 드러낸다.
    """


class UnsupportedRoundingModeError(KisFeeTaxPolicyError):
    """정책의 ``rounding_mode``가 이 계산 함수가 지원하는 값이 아닌 경우.

    현재 지원: ``round_half_up``, ``round_down``.
    """


_SUPPORTED_ROUNDING_MODES: dict[str, str] = {
    "round_half_up": ROUND_HALF_UP,
    "round_down": ROUND_DOWN,
}


@dataclass(slots=True, frozen=True)
class FeeTaxPolicy:
    """``config_json["execution"]["fee_tax"]``를 파싱한 값(순수 데이터)."""

    enabled: bool
    supported_asset_classes: tuple[str, ...]
    supported_market_segments: tuple[str, ...]
    buy_commission_rate_pct: Decimal
    sell_commission_rate_pct: Decimal
    sell_tax_rate_pct: Decimal
    sell_agri_tax_rate_pct: Decimal
    rounding_mode: str
    rounding_unit: Decimal


@dataclass(slots=True, frozen=True)
class FeeTaxResult:
    """:func:`compute_fee_tax`의 반환값."""

    fee: Decimal
    tax: Decimal
    fee_tax_source: RealizedPnlFeeTaxSource


def _decimal_field(namespace: dict[str, Any], key: str) -> Decimal:
    raw = namespace.get(key)
    if raw is None:
        raise MalformedFeeTaxPolicyError(
            f"execution.fee_tax.{key} 필드가 없다 — 정책 구조가 깨져 있다"
        )
    try:
        return Decimal(str(raw))
    except Exception as exc:
        raise MalformedFeeTaxPolicyError(
            f"execution.fee_tax.{key} 값을 Decimal로 변환할 수 없다: {raw!r}"
        ) from exc


def parse_fee_tax_policy(config_json: dict[str, Any]) -> FeeTaxPolicy | None:
    """``config_json``에서 ``execution.fee_tax`` 정책을 파싱한다.

    ``execution``/``fee_tax`` 네임스페이스 자체가 없으면 "정책 없음"으로
    보고 ``None``을 반환한다(호출자가 ``ASSUMED_ZERO``로 처리) — 이건
    정상 상태다. 네임스페이스는 있는데 필수 필드가 없거나 숫자로 변환할
    수 없으면 :class:`MalformedFeeTaxPolicyError`를 던진다.
    """
    execution = config_json.get("execution")
    if not isinstance(execution, dict):
        return None
    fee_tax = execution.get("fee_tax")
    if not isinstance(fee_tax, dict):
        return None

    supported_asset_classes = fee_tax.get("supported_asset_classes")
    supported_market_segments = fee_tax.get("supported_market_segments")
    if not isinstance(supported_asset_classes, list) or not all(
        isinstance(v, str) for v in supported_asset_classes
    ):
        raise MalformedFeeTaxPolicyError(
            "execution.fee_tax.supported_asset_classes가 문자열 리스트가 아니다"
        )
    if not isinstance(supported_market_segments, list) or not all(
        isinstance(v, str) for v in supported_market_segments
    ):
        raise MalformedFeeTaxPolicyError(
            "execution.fee_tax.supported_market_segments가 문자열 리스트가 아니다"
        )

    rounding_mode = fee_tax.get("rounding_mode")
    if not isinstance(rounding_mode, str):
        raise MalformedFeeTaxPolicyError(
            "execution.fee_tax.rounding_mode 필드가 없거나 문자열이 아니다"
        )

    return FeeTaxPolicy(
        enabled=bool(fee_tax.get("enabled", False)),
        supported_asset_classes=tuple(supported_asset_classes),
        supported_market_segments=tuple(supported_market_segments),
        buy_commission_rate_pct=_decimal_field(fee_tax, "buy_commission_rate_pct"),
        sell_commission_rate_pct=_decimal_field(fee_tax, "sell_commission_rate_pct"),
        sell_tax_rate_pct=_decimal_field(fee_tax, "sell_tax_rate_pct"),
        sell_agri_tax_rate_pct=_decimal_field(fee_tax, "sell_agri_tax_rate_pct"),
        rounding_mode=rounding_mode,
        rounding_unit=_decimal_field(fee_tax, "rounding_unit"),
    )


def _is_asset_supported(
    policy: FeeTaxPolicy, *, asset_class: str, market_segment: str | None
) -> bool:
    if asset_class not in policy.supported_asset_classes:
        return False
    if market_segment is None:
        return False
    return market_segment in policy.supported_market_segments


def _apply_rounding(value: Decimal, *, policy: FeeTaxPolicy) -> Decimal:
    rounding = _SUPPORTED_ROUNDING_MODES.get(policy.rounding_mode)
    if rounding is None:
        raise UnsupportedRoundingModeError(
            f"지원하지 않는 rounding_mode: {policy.rounding_mode!r} "
            f"(지원: {sorted(_SUPPORTED_ROUNDING_MODES)})"
        )
    if policy.rounding_unit <= 0:
        raise MalformedFeeTaxPolicyError(
            f"rounding_unit은 양수여야 한다: {policy.rounding_unit!r}"
        )
    quotient = (value / policy.rounding_unit).to_integral_value(rounding=rounding)
    return quotient * policy.rounding_unit


def _compute_amount(
    fill_price: Decimal, fill_quantity: Decimal, rate_pct: Decimal, *, policy: FeeTaxPolicy
) -> Decimal:
    raw = fill_price * fill_quantity * (rate_pct / Decimal("100"))
    return _apply_rounding(raw, policy=policy)


async def compute_fee_tax(
    repos: "RepositoryContainer",
    *,
    client_id: UUID,
    environment: Environment,
    asset_class: str,
    market_segment: str | None,
    side: OrderSide,
    fill_price: Decimal,
    fill_quantity: Decimal,
    fill_timestamp: datetime,
) -> FeeTaxResult:
    """fill 1건의 fee/tax를 계산한다 — 실시간/backfill 공통 진입점.

    ``config_versions.get_active_at(client_id, environment, fill_timestamp)``
    로 그 시점에 활성이던 정책을 복원한다(replay-critical 메서드 재사용,
    새 조회 경로를 만들지 않는다). 판정 순서는 모듈 docstring 참고.
    """
    config = await repos.config_versions.get_active_at(client_id, environment, fill_timestamp)
    if config is None:
        return FeeTaxResult(Decimal("0"), Decimal("0"), RealizedPnlFeeTaxSource.ASSUMED_ZERO)

    policy = parse_fee_tax_policy(config.config_json)
    if policy is None:
        return FeeTaxResult(Decimal("0"), Decimal("0"), RealizedPnlFeeTaxSource.ASSUMED_ZERO)

    if not _is_asset_supported(policy, asset_class=asset_class, market_segment=market_segment):
        return FeeTaxResult(
            Decimal("0"), Decimal("0"), RealizedPnlFeeTaxSource.POLICY_NOT_APPLICABLE
        )

    if not policy.enabled:
        return FeeTaxResult(Decimal("0"), Decimal("0"), RealizedPnlFeeTaxSource.ASSUMED_ZERO)

    if side == OrderSide.BUY:
        fee = _compute_amount(
            fill_price, fill_quantity, policy.buy_commission_rate_pct, policy=policy
        )
        tax = Decimal("0")
    else:
        fee = _compute_amount(
            fill_price, fill_quantity, policy.sell_commission_rate_pct, policy=policy
        )
        combined_tax_rate_pct = policy.sell_tax_rate_pct + policy.sell_agri_tax_rate_pct
        tax = _compute_amount(fill_price, fill_quantity, combined_tax_rate_pct, policy=policy)

    return FeeTaxResult(fee, tax, RealizedPnlFeeTaxSource.CALCULATED_FROM_POLICY)
