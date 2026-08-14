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

from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.errors import build_http_exception
from agent_trading.api.schemas import (
    ActiveFeeTaxPolicyResponse,
    FeeTaxPolicyPreviewView,
    PublishFeeTaxPolicyRequest,
    PublishFeeTaxPolicyResponse,
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
from agent_trading.services.fee_tax_policy_admin import (
    FeeTaxPolicyAdminError,
    FeeTaxPolicyPreview,
    get_active_fee_tax_policy,
    get_fee_tax_policy_at,
    publish_fee_tax_policy,
)

router = APIRouter(tags=["config-versions"])

_REQUEST_PATH = "/config-versions/risk/max-single-position-pct"
_FEE_TAX_PUBLISH_PATH = "/config-versions/execution-fee-tax"
_FEE_TAX_ACTIVE_PATH = "/config-versions/execution-fee-tax/active"
_FEE_TAX_AT_PATH = "/config-versions/execution-fee-tax/at"


def _parse_client_id(value: str, *, request_path: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise build_http_exception(
            status_code=400,
            error_code="invalid_client_id",
            message="Invalid client_id UUID",
            field="client_id",
            expected="UUID string",
            received=value,
            request_path=request_path,
            next_action="check client_id format",
        )


def _parse_environment(value: str, *, request_path: str) -> Environment:
    try:
        return Environment(value)
    except ValueError:
        raise build_http_exception(
            status_code=400,
            error_code="invalid_environment",
            message="Invalid environment",
            field="environment",
            expected="'paper' | 'live'",
            received=value,
            request_path=request_path,
            next_action="check environment value",
        )


def _preview_to_view(preview: FeeTaxPolicyPreview) -> FeeTaxPolicyPreviewView:
    return FeeTaxPolicyPreviewView(
        normalized_fee_tax=preview.normalized_fee_tax,
        sample_price=preview.sample_price,
        sample_quantity=preview.sample_quantity,
        sample_buy_fee=preview.sample_buy_fee,
        sample_sell_fee=preview.sample_sell_fee,
        sample_sell_tax=preview.sample_sell_tax,
    )


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


@router.post(
    _FEE_TAX_PUBLISH_PATH,
    response_model=PublishFeeTaxPolicyResponse,
)
async def publish_execution_fee_tax_policy(
    body: PublishFeeTaxPolicyRequest,
    repos: RepositoryContainer = Depends(get_repos),
    principal: Principal = Depends(require_admin),
) -> PublishFeeTaxPolicyResponse:
    """``execution.fee_tax`` 정책을 등록/활성화한다(``dry_run=true``면 미리보기만).

    설계 근거: docs/00_foundational_design/detailed_design/
    12_realized_pnl_moving_average_ledger.md 13절. 실제 저장/발행 로직은
    ``services.fee_tax_policy_admin.publish_fee_tax_policy()``에 있다 —
    이 route는 얇은 계층이다(``update_max_single_position_pct``와 동일한
    관례).

    ``dry_run=true``와 ``dry_run=false``는 항상 같은 검증
    (``validate_and_preview_fee_tax_policy``)을 거친다 — dry-run만 통과하고
    실제 등록은 다르게 실패하는 일이 없다. ``activated_at``을 생략하면
    현재 시각을 쓰고, 지정하면 현재 활성 버전보다 이후여야 한다(동일
    시각/과거 시각 등록 거부).
    """
    client_uuid = _parse_client_id(body.client_id, request_path=_FEE_TAX_PUBLISH_PATH)
    environment = _parse_environment(body.environment, request_path=_FEE_TAX_PUBLISH_PATH)

    fee_tax_input = body.execution_fee_tax.model_dump()

    try:
        result = await publish_fee_tax_policy(
            repos,
            client_id=client_uuid,
            environment=environment,
            fee_tax_input=fee_tax_input,
            activated_by=f"admin_api:{principal.role}",
            activated_at=body.activated_at,
            dry_run=body.dry_run,
        )
    except (FeeTaxPolicyAdminError, ConfigVersionAdminError) as exc:
        raise build_http_exception(
            status_code=400,
            error_code="fee_tax_policy_publish_rejected",
            message=str(exc),
            field="execution_fee_tax,activated_at,environment",
            expected=(
                "reason 필수, 요율은 0 이상 10(%) 이하, rounding_mode는 "
                "round_half_up|round_down, environment는 paper|live, "
                "activated_at은 현재 활성 버전보다 이후"
            ),
            received=f"environment={body.environment}, dry_run={body.dry_run}",
            request_path=_FEE_TAX_PUBLISH_PATH,
            next_action="check the exact error message and retry with valid values",
        )

    if isinstance(result, FeeTaxPolicyPreview):
        # dry_run=True인 경우 publish_fee_tax_policy()는 FeeTaxPolicyPreview만 반환한다.
        return PublishFeeTaxPolicyResponse(
            dry_run=True,
            client_id=str(client_uuid),
            environment=environment.value,
            preview=_preview_to_view(result),
        )

    return PublishFeeTaxPolicyResponse(
        dry_run=False,
        config_version_id=str(result.new.config_version_id),
        previous_config_version_id=(
            str(result.previous.config_version_id) if result.previous is not None else None
        ),
        client_id=str(client_uuid),
        environment=environment.value,
        version_tag=result.new.version_tag,
        activated_at=result.new.activated_at,
        activated_by=result.new.activated_by or "",
        preview=_preview_to_view(result.preview),
    )


@router.get(
    _FEE_TAX_ACTIVE_PATH,
    response_model=ActiveFeeTaxPolicyResponse,
)
async def get_active_execution_fee_tax_policy(
    client_id: str = Query(..., description="Client UUID"),
    environment: str = Query(..., description="'paper' | 'live'"),
    repos: RepositoryContainer = Depends(get_repos),
    _principal: Principal = Depends(require_admin),
) -> ActiveFeeTaxPolicyResponse:
    """현재 활성 ``execution.fee_tax`` 정책을 조회한다.

    아직 등록된 적이 없으면(``compute_fee_tax()``가 ``assumed_zero``로
    처리하는 것과 동일한 상태) ``config_version_id``/``execution_fee_tax``
    가 ``None``인 200 응답을 반환한다 — 오류가 아니다.
    """
    client_uuid = _parse_client_id(client_id, request_path=_FEE_TAX_ACTIVE_PATH)
    env = _parse_environment(environment, request_path=_FEE_TAX_ACTIVE_PATH)

    config, _policy = await get_active_fee_tax_policy(
        repos, client_id=client_uuid, environment=env
    )
    execution_fee_tax = None
    if config is not None and isinstance(config.config_json, dict):
        execution = config.config_json.get("execution")
        if isinstance(execution, dict):
            execution_fee_tax = execution.get("fee_tax")

    return ActiveFeeTaxPolicyResponse(
        client_id=str(client_uuid),
        environment=env.value,
        config_version_id=str(config.config_version_id) if config is not None else None,
        activated_at=config.activated_at if config is not None else None,
        execution_fee_tax=execution_fee_tax,
    )


@router.get(
    _FEE_TAX_AT_PATH,
    response_model=ActiveFeeTaxPolicyResponse,
)
async def get_execution_fee_tax_policy_at(
    client_id: str = Query(..., description="Client UUID"),
    environment: str = Query(..., description="'paper' | 'live'"),
    at: datetime = Query(..., description="조회 시점(ISO 8601, 예: 2026-08-14T09:00:00Z)"),
    repos: RepositoryContainer = Depends(get_repos),
    _principal: Principal = Depends(require_admin),
) -> ActiveFeeTaxPolicyResponse:
    """``at`` 시점에 활성이었던 ``execution.fee_tax`` 정책을 조회한다.

    ``compute_fee_tax()``가 실제 fill 계산 시 참조하는 것과 동일한
    ``get_active_at()``을 그대로 쓴다 — 운영자가 "이 시점의 체결은
    어떤 정책으로 계산됐는지/될지"를 미리 확인할 수 있다.
    """
    client_uuid = _parse_client_id(client_id, request_path=_FEE_TAX_AT_PATH)
    env = _parse_environment(environment, request_path=_FEE_TAX_AT_PATH)

    config, _policy = await get_fee_tax_policy_at(
        repos, client_id=client_uuid, environment=env, at=at
    )
    execution_fee_tax = None
    if config is not None and isinstance(config.config_json, dict):
        execution = config.config_json.get("execution")
        if isinstance(execution, dict):
            execution_fee_tax = execution.get("fee_tax")

    return ActiveFeeTaxPolicyResponse(
        client_id=str(client_uuid),
        environment=env.value,
        config_version_id=str(config.config_version_id) if config is not None else None,
        activated_at=config.activated_at if config is not None else None,
        execution_fee_tax=execution_fee_tax,
    )
