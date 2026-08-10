"""Config version admin endpoints (write, admin-only).

``POST /config-versions/risk/max-single-position-pct`` — ``risk.max_single_position_pct``
값을 안전하게 조정하기 위한 유일한 관리 경로다. 이 route는 순수하게
얇은 계층이며, 실제 immutable-append 로직/검증/audit trail은
``agent_trading.services.config_version_admin.publish_max_single_position_pct()``
에 있다(API와 CLI가 이 함수를 공유한다).

이 파일은 다른 ``api/routes/*.py``와 달리 **쓰기** endpoint다 — 그래서
``orders.py``의 ``PUT /orders/{id}/status``와 동일한 패턴(router 레벨
``require_viewer`` + 이 route에만 추가로 ``require_admin``)을 그대로
따른다.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Depends

from agent_trading.api.deps import get_repos
from agent_trading.api.errors import build_http_exception
from agent_trading.api.schemas import (
    UpdateMaxSinglePositionPctRequest,
    UpdateMaxSinglePositionPctResponse,
)
from agent_trading.api.security import Principal, require_admin
from agent_trading.domain.enums import Environment
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.config_version_admin import (
    ConfigVersionAdminError,
    publish_max_single_position_pct,
)

router = APIRouter(tags=["config-versions"])

_REQUEST_PATH = "/config-versions/risk/max-single-position-pct"


@router.post(
    _REQUEST_PATH,
    response_model=UpdateMaxSinglePositionPctResponse,
)
async def update_max_single_position_pct(
    body: UpdateMaxSinglePositionPctRequest,
    repos: RepositoryContainer = Depends(get_repos),
    principal: Principal = Depends(require_admin),
) -> UpdateMaxSinglePositionPctResponse:
    """활성 config_version을 복제해 ``risk.max_single_position_pct``만 바꾼

    새 버전을 발행한다(기존 row는 UPDATE하지 않는다 — immutable append-only,
    ``docs/00_foundational_design/detailed_design/06_config_schema.md`` §5).
    ``activated_by``는 이 요청을 승인한 principal의 role로 채운다(현재
    Inspection API의 RBAC는 토큰당 단일 role만 구분하므로, 실제 운영자
    식별은 ``reason`` 필드와 별도 접근 로그로 보완한다).

    ``environment``는 ``'paper'`` | ``'live'``만 허용한다. ``Environment``
    enum에는 ``'real'``도 있지만, ``trading.config_versions.environment``의
    DB CHECK 제약이 ``'real'``을 받지 않아(운영 Postgres에서 직접 확인)
    ``config_version_admin.validate_environment()``가 그 값을 명시적으로
    거부한다 — 애플리케이션 레벨에서 막지 않으면 DB INSERT에서야 크래시가
    나기 때문이다.
    """
    try:
        client_uuid = UUID(body.client_id)
    except ValueError:
        raise build_http_exception(
            status_code=400,
            error_code="invalid_client_id",
            message="Invalid client_id UUID",
            field="client_id",
            expected="UUID string",
            received=body.client_id,
            request_path=_REQUEST_PATH,
            next_action="check client_id format",
        )

    try:
        environment = Environment(body.environment)
    except ValueError:
        raise build_http_exception(
            status_code=400,
            error_code="invalid_environment",
            message="Invalid environment",
            field="environment",
            expected="'paper' | 'live'",
            received=body.environment,
            request_path=_REQUEST_PATH,
            next_action="check environment value",
        )

    try:
        max_single_position_pct = Decimal(str(body.max_single_position_pct))
    except InvalidOperation:
        raise build_http_exception(
            status_code=400,
            error_code="invalid_max_single_position_pct",
            message="max_single_position_pct must be a decimal number",
            field="max_single_position_pct",
            expected="0 < x <= 100",
            received=str(body.max_single_position_pct),
            request_path=_REQUEST_PATH,
            next_action="check max_single_position_pct value",
        )

    try:
        result = await publish_max_single_position_pct(
            repos,
            client_id=client_uuid,
            environment=environment,
            max_single_position_pct=max_single_position_pct,
            activated_by=f"admin_api:{principal.role}",
            reason=body.reason,
        )
    except ConfigVersionAdminError as exc:
        raise build_http_exception(
            status_code=400,
            error_code="config_version_publish_rejected",
            message=str(exc),
            field="max_single_position_pct,environment",
            expected=(
                "max_single_position_pct: 0 < x <= 100 and different from the current "
                "active value; environment: 'paper' | 'live' (not 'real'); "
                "an active config_version must already exist for the target client_id/environment"
            ),
            received=f"max_single_position_pct={body.max_single_position_pct}, environment={body.environment}",
            request_path=_REQUEST_PATH,
            next_action="check current active config_version and the exact error message, then retry with valid values",
        )

    return UpdateMaxSinglePositionPctResponse(
        config_version_id=str(result.new.config_version_id),
        previous_config_version_id=str(result.previous.config_version_id),
        client_id=str(client_uuid),
        environment=environment.value,
        version_tag=result.new.version_tag,
        previous_max_single_position_pct=result.previous_max_single_position_pct,
        new_max_single_position_pct=result.new_max_single_position_pct,
        activated_at=result.new.activated_at,
        activated_by=result.new.activated_by or "",
    )
