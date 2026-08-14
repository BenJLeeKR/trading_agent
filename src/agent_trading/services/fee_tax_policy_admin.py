"""운영자가 ``config_versions``의 ``execution.fee_tax`` 정책을

등록/활성화/조회하기 위한 관리 경로 — Admin API
(``api/routes/config_versions.py``)가 이 모듈을 호출한다.

설계 근거: docs/00_foundational_design/detailed_design/
12_realized_pnl_moving_average_ledger.md 13절.

``config_version_admin.py``(``risk.max_single_position_pct`` 관리 경로)와
같은 원칙을 그대로 따른다.

1. **immutable append-only** — 기존 ``config_versions`` row는 절대
   UPDATE하지 않는다. 활성 버전이 있으면 그 ``config_json``을 복제해
   ``execution.fee_tax``만 교체한 새 row를 추가한다. 활성 버전이 아직
   없으면(이 계좌×환경에 대한 최초 등록) 빈 ``config_json``에서 시작한다
   — ``risk.max_single_position_pct`` 경로와 달리 이 경로는 "이미 뭔가
   있어야 한다"는 전제를 두지 않는다(fee/tax 정책은 대부분의 client×
   environment에서 아직 한 번도 등록된 적이 없다).
2. **계산 로직은 건드리지 않는다** — ``kis_fee_tax_policy.py``의
   ``parse_fee_tax_policy()``/``preview_fee_tax_amounts()``만 재사용해
   등록 전 검증/미리보기에 쓴다. 계산 공식 자체(``_compute_amount``/
   ``_apply_rounding``/``compute_fee_tax()``)는 이 모듈이 전혀 수정하지
   않는다.
3. **activated_at 충돌/역행 방지** — ``trading.config_versions``에는
   ``(client_id, environment, activated_at)`` 유일 제약이 DB 레벨에
   없다(``config_version_admin.py``도 이 사실을 이미 전제로 삼는다).
   이 모듈은 새 버전의 ``activated_at``이 현재 활성 버전의
   ``activated_at``보다 **이후**여야 한다는 규칙을 강제한다 — 동일 시각
   재등록과 과거 시각으로의 역행 등록을 **모두** 거부한다(§ 아래
   ``publish_fee_tax_policy`` docstring 참고). 과거 시점 보정이 정말
   필요하면 이 경로가 아니라 별도 운영 판단(및 별도 도구)이 필요하다 —
   지금은 "단순함과 replay 일관성"을 "과거 보정 편의"보다 우선한다.
4. **reason 필수** — ``reason``이 비어 있으면 등록 자체를 거부한다.
5. **dry-run 필수 경유** — 실제 등록(``dry_run=False``)도 내부적으로
   dry-run과 동일한 검증/미리보기 함수(``validate_and_preview_fee_tax_policy``)
   를 반드시 먼저 통과한다 — 두 경로가 서로 다른 검증을 받는 일이
   없도록 단일 진입점으로 강제한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from agent_trading.domain.entities import AuditLogEntity, ConfigVersionEntity
from agent_trading.domain.enums import Environment
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.config_version_admin import validate_environment
from agent_trading.services.kis_fee_tax_policy import (
    FeeTaxPolicy,
    MalformedFeeTaxPolicyError,
    UnsupportedRoundingModeError,
    parse_fee_tax_policy,
    preview_fee_tax_amounts,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FeeTaxPolicyAdminError",
    "FeeTaxPolicyPreview",
    "FeeTaxPolicyPublishResult",
    "validate_and_preview_fee_tax_policy",
    "publish_fee_tax_policy",
    "get_active_fee_tax_policy",
    "get_fee_tax_policy_at",
]

# 미리보기/검산용 샘플 체결(재무 규칙 확정이 아니라 오입력 발견용).
_SAMPLE_PRICE = Decimal("100000")
_SAMPLE_QUANTITY = Decimal("10")

# 명백한 퍼센트 오입력 방지 임계값 — 최종 재무 규칙이 아니라 "이 값이
# 국내주식 수수료/세율이 통상 위치하는 범위(0~1% 안팎)를 크게 벗어나면
# 십중팔구 소수점/퍼센트 표기 실수"라는 안전장치다(예: 0.147을 14.7로
# 잘못 입력). 10%는 실제 관측된 어떤 공식 요율(최대 K-OTC 약 0.2999%)
# 보다도 33배 이상 여유를 둔 값이다.
_MAX_SANE_RATE_PCT = Decimal("10")

_RATE_FIELDS = (
    "buy_commission_rate_pct",
    "sell_commission_rate_pct",
    "sell_tax_rate_pct",
    "sell_agri_tax_rate_pct",
)


class FeeTaxPolicyAdminError(ValueError):
    """이 모듈이 던지는 도메인 검증 오류 — 호출자가 사용자向 오류로 매핑한다."""


@dataclass(slots=True, frozen=True)
class FeeTaxPolicyPreview:
    """등록 전(또는 dry-run) 검증을 통과한 정규화된 정책값 + 샘플 계산 결과."""

    normalized_fee_tax: dict[str, Any]
    sample_price: str
    sample_quantity: str
    sample_buy_fee: str
    sample_sell_fee: str
    sample_sell_tax: str


@dataclass(slots=True, frozen=True)
class FeeTaxPolicyPublishResult:
    """``publish_fee_tax_policy(dry_run=False)``의 반환값."""

    previous: ConfigVersionEntity | None
    """활성 버전이 이미 있었으면 그 버전, 최초 등록이면 ``None``."""
    new: ConfigVersionEntity
    preview: FeeTaxPolicyPreview


def _compute_checksum(config_json: dict[str, object]) -> str:
    """``config_json``의 정규화된 JSON에 대한 sha256 hex digest.

    ``config_version_admin._compute_checksum()``과 동일한 규칙
    (``sort_keys=True``, 무결성 확인용이지 서명이 아님)을 이 모듈에서
    독립적으로 유지한다 — 그 함수는 다른 모듈의 private 헬퍼라 직접
    import하지 않는다(모듈 경계를 명확히 유지).
    """
    canonical = json.dumps(config_json, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_rate_pct(name: str, value: Decimal) -> None:
    if value < 0:
        raise FeeTaxPolicyAdminError(f"{name}는 음수일 수 없다(입력값: {value})")
    if value > _MAX_SANE_RATE_PCT:
        raise FeeTaxPolicyAdminError(
            f"{name}={value}가 안전 임계값 {_MAX_SANE_RATE_PCT}(%)를 초과한다 — "
            "국내주식 수수료/세율은 보통 0~1% 안팎이다. 퍼센트 표기 실수"
            "(예: 0.147을 14.7로 입력)가 아닌지 다시 확인해라."
        )


def validate_and_preview_fee_tax_policy(fee_tax_input: dict[str, Any]) -> FeeTaxPolicyPreview:
    """등록 전 구조 검증 + 정규화 + 샘플 계산 미리보기.

    ``dry_run=True`` 요청과 실제 등록(``dry_run=False``) 요청이 모두 이
    함수를 거친다 — 두 경로가 항상 같은 검증을 받도록 강제한다(모듈
    docstring 원칙 5).

    Raises
    ------
    FeeTaxPolicyAdminError
        ``reason``이 비어 있거나, 정책 구조가 깨져 있거나(필수 필드
        누락/숫자 변환 실패), 요율이 안전 범위를 벗어나거나,
        ``rounding_mode``가 지원되지 않는 경우.
    """
    reason = fee_tax_input.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise FeeTaxPolicyAdminError("reason은 비어 있지 않은 문자열이어야 한다(필수)")

    # parse_fee_tax_policy()는 {"execution": {"fee_tax": {...}}} 형태를
    # 기대한다 — 계산 로직(kis_fee_tax_policy.py)을 그대로 재사용한다.
    try:
        policy = parse_fee_tax_policy({"execution": {"fee_tax": fee_tax_input}})
    except MalformedFeeTaxPolicyError as exc:
        raise FeeTaxPolicyAdminError(f"execution.fee_tax 구조가 유효하지 않다: {exc}") from exc
    if policy is None:
        raise FeeTaxPolicyAdminError("execution.fee_tax 네임스페이스가 비어 있다")

    for field_name in _RATE_FIELDS:
        _validate_rate_pct(field_name, getattr(policy, field_name))

    try:
        sample = preview_fee_tax_amounts(
            policy, sample_price=_SAMPLE_PRICE, sample_quantity=_SAMPLE_QUANTITY
        )
    except UnsupportedRoundingModeError as exc:
        raise FeeTaxPolicyAdminError(str(exc)) from exc

    normalized: dict[str, Any] = {
        "enabled": policy.enabled,
        "supported_asset_classes": list(policy.supported_asset_classes),
        "supported_market_segments": list(policy.supported_market_segments),
        "buy_commission_rate_pct": str(policy.buy_commission_rate_pct),
        "sell_commission_rate_pct": str(policy.sell_commission_rate_pct),
        "sell_tax_rate_pct": str(policy.sell_tax_rate_pct),
        "sell_agri_tax_rate_pct": str(policy.sell_agri_tax_rate_pct),
        "rounding_mode": policy.rounding_mode,
        "rounding_unit": str(policy.rounding_unit),
        "reason": reason,
        "operator_note": fee_tax_input.get("operator_note"),
        "source_note": fee_tax_input.get("source_note"),
    }
    return FeeTaxPolicyPreview(
        normalized_fee_tax=normalized,
        sample_price=str(_SAMPLE_PRICE),
        sample_quantity=str(_SAMPLE_QUANTITY),
        sample_buy_fee=str(sample["buy_fee"]),
        sample_sell_fee=str(sample["sell_fee"]),
        sample_sell_tax=str(sample["sell_tax"]),
    )


async def publish_fee_tax_policy(
    repos: RepositoryContainer,
    *,
    client_id: UUID,
    environment: Environment,
    fee_tax_input: dict[str, Any],
    activated_by: str,
    activated_at: datetime | None = None,
    dry_run: bool = False,
) -> FeeTaxPolicyPreview | FeeTaxPolicyPublishResult:
    """``execution.fee_tax`` 정책이 포함된 새 ``config_version``을 발행한다.

    Parameters
    ----------
    activated_at:
        생략하면 ``datetime.now(timezone.utc)``를 쓴다. 명시하면, 현재
        활성 버전이 있는 경우 그 ``activated_at``보다 **반드시 이후**여야
        한다 — 같지도, 이전이지도 않아야 한다. 이 규칙 하나로 "동일
        activated_at 충돌"과 "과거 시점 역행 등록"을 모두 막는다(모듈
        docstring 원칙 3). 활성 버전이 아직 없으면(최초 등록) 이 제약은
        적용되지 않는다.
    dry_run:
        ``True``면 검증/미리보기만 수행하고 **아무것도 저장하지 않는다**
        — 반환값은 :class:`FeeTaxPolicyPreview`. ``False``면 실제로
        새 ``config_version``을 append하고 :class:`FeeTaxPolicyPublishResult`
        를 반환한다.

    Raises
    ------
    ConfigVersionAdminError
        ``environment``가 ``paper``/``live``가 아닐 때.
    FeeTaxPolicyAdminError
        :func:`validate_and_preview_fee_tax_policy`가 던지는 모든 사유,
        또는 ``activated_at``이 현재 활성 버전과 같거나 이전일 때.
    """
    validate_environment(environment)
    preview = validate_and_preview_fee_tax_policy(fee_tax_input)

    if dry_run:
        return preview

    active = await repos.config_versions.get_active(client_id, environment)
    new_activated_at = activated_at or datetime.now(timezone.utc)

    if active is not None and active.activated_at is not None:
        if new_activated_at <= active.activated_at:
            raise FeeTaxPolicyAdminError(
                f"activated_at={new_activated_at.isoformat()}은 현재 활성 버전"
                f"(config_version_id={active.config_version_id}, "
                f"activated_at={active.activated_at.isoformat()})보다 이후여야 한다 "
                "— 동일 시각 재등록과 과거 시점 역행 등록은 허용하지 않는다."
            )

    base_config_json: dict[str, Any] = (
        json.loads(json.dumps(active.config_json, default=str))
        if active is not None and isinstance(active.config_json, dict)
        else {}
    )
    execution_section = dict(base_config_json.get("execution") or {})
    execution_section["fee_tax"] = preview.normalized_fee_tax
    base_config_json["execution"] = execution_section

    new_version_id = uuid4()
    new_version = ConfigVersionEntity(
        config_version_id=new_version_id,
        client_id=client_id,
        environment=environment,
        version_tag=(
            f"execution.fee_tax@{new_activated_at.strftime('%Y%m%dT%H%M%SZ')}"
        ),
        config_json=base_config_json,
        checksum=_compute_checksum(base_config_json),
        activated_at=new_activated_at,
        activated_by=activated_by,
    )
    saved = await repos.config_versions.add(new_version)

    await repos.audit_logs.add(
        AuditLogEntity(
            audit_log_id=uuid4(),
            actor_type="operator",
            actor_id=activated_by,
            action="config_version.execution.fee_tax.publish",
            target_entity_type="config_version",
            target_entity_id=str(saved.config_version_id),
            created_at=datetime.now(timezone.utc),
            before_json={
                "config_version_id": str(active.config_version_id) if active else None,
                "execution_fee_tax": (
                    active.config_json.get("execution", {}).get("fee_tax")
                    if active is not None and isinstance(active.config_json, dict)
                    else None
                ),
            },
            after_json={
                "config_version_id": str(saved.config_version_id),
                "execution_fee_tax": preview.normalized_fee_tax,
            },
            metadata={
                "client_id": str(client_id),
                "environment": environment.value,
                "reason": preview.normalized_fee_tax.get("reason"),
            },
        )
    )

    logger.info(
        "Published new config_version %s for client_id=%s environment=%s: "
        "execution.fee_tax published (previous config_version=%s)",
        saved.config_version_id, client_id, environment.value,
        active.config_version_id if active is not None else None,
    )

    return FeeTaxPolicyPublishResult(previous=active, new=saved, preview=preview)


async def get_active_fee_tax_policy(
    repos: RepositoryContainer, *, client_id: UUID, environment: Environment
) -> tuple[ConfigVersionEntity | None, FeeTaxPolicy | None]:
    """현재 활성 ``config_version``과 그 안의 ``execution.fee_tax`` 정책을 반환한다.

    활성 버전이 없거나, 있어도 ``execution.fee_tax`` 네임스페이스가
    없으면 두 번째 값은 ``None``이다(이건 오류가 아니다 — "아직 등록
    안 됨"이라는 정상 상태).
    """
    active = await repos.config_versions.get_active(client_id, environment)
    if active is None:
        return None, None
    policy = parse_fee_tax_policy(active.config_json)
    return active, policy


async def get_fee_tax_policy_at(
    repos: RepositoryContainer, *, client_id: UUID, environment: Environment, at: datetime
) -> tuple[ConfigVersionEntity | None, FeeTaxPolicy | None]:
    """``at`` 시점에 활성이던 ``config_version``과 ``execution.fee_tax`` 정책을 반환한다.

    ``compute_fee_tax()``가 실제로 쓰는 것과 동일한
    ``get_active_at()``을 그대로 재사용한다 — 계산 함수가 그 시점에
    무엇을 보게 되는지 운영자가 미리 확인할 수 있게 하기 위함이다.
    """
    config = await repos.config_versions.get_active_at(client_id, environment, at)
    if config is None:
        return None, None
    policy = parse_fee_tax_policy(config.config_json)
    return config, policy
