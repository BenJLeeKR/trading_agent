"""운영자가 `config_version.risk.max_single_position_pct`를 안전하게 조정하기 위한
관리 경로 — Admin API(``api/routes/config_versions.py``)와 CLI
(``scripts/publish_max_single_position_pct.py``)가 공유하는 단일 진입점.

설계 원칙
--------
1. **immutable append-only** — 기존 ``config_versions`` row는 절대 UPDATE하지
   않는다. 현재 활성 버전의 ``config_json``을 그대로 복제한 뒤 대상 키만
   바꿔 **새 row**를 ``repos.config_versions.add()``로 추가하고,
   ``activated_at``을 최신으로 설정해 ``get_active()``가 이 새 버전을
   가리키게 한다(``postgres/config_versions.py.get_active()`` 참고 —
   ``ORDER BY activated_at DESC NULLS LAST LIMIT 1``).
2. **replay 안전** — 과거 버전은 그대로 남아 있으므로
   ``get_active_at()``으로 과거 시점 재현(replay)이 계속 가능하다.
3. **audit trail** — 변경마다 ``audit_logs``에 before/after 값을 남긴다
   (``order_manager.py._record_audit()``와 동일한 패턴).
4. **좁은 범위** — 이번 버전은 ``risk.max_single_position_pct`` 단일 키만
   다룬다. 다른 risk/execution 키는 그대로 보존한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from agent_trading.domain.entities import AuditLogEntity, ConfigVersionEntity
from agent_trading.domain.enums import Environment
from agent_trading.repositories.container import RepositoryContainer

logger = logging.getLogger(__name__)

# sizing_engine.py._apply_concentration_constraint()의 실제 동작 근거:
# `max_single_position_pct <= 0`이면 concentration 제약 자체가 **적용되지
# 않는다**(스킵) — 즉 0을 "더 엄격하게"가 아니라 "안전장치 해제"로 해석한다.
# 그러므로 0과 음수는 반드시 거부해야 한다(추측이 아니라 코드 동작 근거).
MIN_MAX_SINGLE_POSITION_PCT = Decimal("0")
MAX_MAX_SINGLE_POSITION_PCT = Decimal("100")


class ConfigVersionAdminError(ValueError):
    """이 모듈이 던지는 도메인 검증 오류 — 호출자가 사용자向 오류로 매핑한다."""


@dataclass(slots=True, frozen=True)
class PublishResult:
    """``publish_max_single_position_pct()``의 반환값."""

    previous: ConfigVersionEntity
    """항상 존재한다 — 활성 버전이 없으면 이 결과가 만들어지기 전에
    ``ConfigVersionAdminError``가 발생한다."""
    new: ConfigVersionEntity
    previous_max_single_position_pct: str | None
    new_max_single_position_pct: str


def _compute_checksum(config_json: dict[str, object]) -> str:
    """``config_json``의 정규화된 JSON에 대한 sha256 hex digest.

    키 순서에 무관하게 동일 값이면 동일 checksum이 나오도록
    ``sort_keys=True``를 쓴다(무결성 확인용, 서명이 아니다).
    """
    canonical = json.dumps(config_json, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_max_single_position_pct(value: Decimal) -> None:
    """``0 < value <= 100`` 범위만 허용한다.

    - ``value <= 0``: sizing_engine이 이 값을 "제약 비활성화"로 해석하므로
      거부한다(위 모듈 docstring 참고) — 안전장치를 실수로 끄는 것을 막는다.
    - ``value > 100``: 설계 스키마 규칙("모든 퍼센트 값은 0 <= x <= 100",
      ``docs/00_foundational_design/detailed_design/06_config_schema.md``)
      을 그대로 따른다.
    """
    if value <= MIN_MAX_SINGLE_POSITION_PCT:
        raise ConfigVersionAdminError(
            f"max_single_position_pct must be > {MIN_MAX_SINGLE_POSITION_PCT} "
            f"(got {value}) — sizing_engine treats <= 0 as 'constraint disabled', "
            "not 'more restrictive'."
        )
    if value > MAX_MAX_SINGLE_POSITION_PCT:
        raise ConfigVersionAdminError(
            f"max_single_position_pct must be <= {MAX_MAX_SINGLE_POSITION_PCT} (got {value})"
        )


async def publish_max_single_position_pct(
    repos: RepositoryContainer,
    *,
    client_id: UUID,
    environment: Environment,
    max_single_position_pct: Decimal,
    activated_by: str,
    reason: str | None = None,
) -> PublishResult:
    """``risk.max_single_position_pct``만 바꾼 새 config_version을 발행한다.

    Parameters
    ----------
    client_id, environment:
        어떤 client×environment의 활성 설정을 바꿀지 명시적으로 지정한다
        (``get_active()``와 동일한 키).
    max_single_position_pct:
        새로 설정할 값(0 초과, 100 이하).
    activated_by:
        누가 이 변경을 발행했는지(운영자 식별자 또는 API principal role).
        ``config_versions.activated_by`` 컬럼과 audit log의 ``actor_id``에
        그대로 남는다.
    reason:
        선택적 변경 사유 — audit log의 ``metadata.reason``에 남는다.

    Raises
    ------
    ConfigVersionAdminError
        - 값이 유효 범위(0 < x <= 100) 밖일 때
        - 활성 config_version이 없을 때(이 경로는 기존 활성 버전을 복제하는
          것이 전제이므로, 아직 아무 버전도 없는 client×environment는
          이 경로로 새로 만들 수 없다 — ``scripts/run_orchestrator_once.py``
          같은 최초 시드가 먼저 필요하다)
        - 새 값이 현재 활성값과 동일할 때(중복 발행 방지 — 의미 없는
          새 version_tag가 계속 쌓이는 것을 막는다)
    """
    validate_max_single_position_pct(max_single_position_pct)

    active = await repos.config_versions.get_active(client_id, environment)
    if active is None:
        raise ConfigVersionAdminError(
            f"No active config_version found for client_id={client_id} "
            f"environment={environment.value} — this admin path only updates an "
            "existing active version; seed one first (see scripts/run_orchestrator_once.py)."
        )

    current_risk = active.config_json.get("risk", {}) if isinstance(active.config_json, dict) else {}
    current_value_raw = current_risk.get("max_single_position_pct") if isinstance(current_risk, dict) else None
    current_value = Decimal(str(current_value_raw)) if current_value_raw is not None else None

    new_value_str = str(max_single_position_pct)
    if current_value is not None and current_value == max_single_position_pct:
        raise ConfigVersionAdminError(
            f"max_single_position_pct is already {new_value_str} for "
            f"client_id={client_id} environment={environment.value} — refusing to "
            "publish a duplicate version with an unchanged value."
        )

    # ── 기존 config_json을 그대로 복제한 뒤 대상 키만 교체 ──
    new_config_json = json.loads(json.dumps(active.config_json, default=str))
    risk_section = dict(new_config_json.get("risk") or {})
    risk_section["max_single_position_pct"] = new_value_str
    new_config_json["risk"] = risk_section

    now = datetime.now(timezone.utc)
    new_version_id = uuid4()
    new_version = ConfigVersionEntity(
        config_version_id=new_version_id,
        client_id=client_id,
        environment=environment,
        version_tag=f"{active.version_tag}+risk.max_single_position_pct={new_value_str}@{now.strftime('%Y%m%dT%H%M%SZ')}",
        config_json=new_config_json,
        checksum=_compute_checksum(new_config_json),
        activated_at=now,
        activated_by=activated_by,
    )
    saved = await repos.config_versions.add(new_version)

    await repos.audit_logs.add(
        AuditLogEntity(
            audit_log_id=uuid4(),
            actor_type="operator",
            actor_id=activated_by,
            action="config_version.risk.max_single_position_pct.update",
            target_entity_type="config_version",
            target_entity_id=str(saved.config_version_id),
            created_at=now,
            before_json={
                "config_version_id": str(active.config_version_id),
                "max_single_position_pct": current_value_raw,
            },
            after_json={
                "config_version_id": str(saved.config_version_id),
                "max_single_position_pct": new_value_str,
            },
            metadata={
                "client_id": str(client_id),
                "environment": environment.value,
                "reason": reason,
            },
        )
    )

    logger.info(
        "Published new config_version %s for client_id=%s environment=%s: "
        "max_single_position_pct %s -> %s (previous config_version=%s)",
        saved.config_version_id, client_id, environment.value,
        current_value_raw, new_value_str, active.config_version_id,
    )

    return PublishResult(
        previous=active,
        new=saved,
        previous_max_single_position_pct=(
            str(current_value_raw) if current_value_raw is not None else None
        ),
        new_max_single_position_pct=new_value_str,
    )
