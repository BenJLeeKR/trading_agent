"""Enum metadata inspection endpoints: ``GET /metadata/enums``,
``GET /metadata/enums/{field}``.

These endpoints expose machine-readable metadata for enum fields so that
consumers (Admin UI, inspection scripts) can resolve canonical values to
human-readable labels without hardcoding.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent_trading.api.enum_metadata import ENUM_METADATA, get_enum_field
from agent_trading.api.schemas import (
    EnumFieldMetadataSchema,
    EnumMetadataListResponse,
    EnumValueMetadataSchema,
)

router = APIRouter(prefix="/metadata", tags=["metadata"])


def _serialize_field(meta: object) -> EnumFieldMetadataSchema:
    """Convert an ``EnumFieldMetadata`` dataclass to a Pydantic schema."""
    from agent_trading.api.enum_metadata import EnumFieldMetadata

    assert isinstance(meta, EnumFieldMetadata)
    return EnumFieldMetadataSchema(
        field=meta.field,
        type=meta.type,
        values=[
            EnumValueMetadataSchema(
                value=v.value,
                label=v.label,
                description=v.description,
                broker_code=v.broker_code,
                supported=v.supported,
            )
            for v in meta.values
        ],
    )


@router.get("/enums", response_model=EnumMetadataListResponse)
async def list_enum_metadata() -> EnumMetadataListResponse:
    """List metadata for all registered enum fields.

    Returns a list of ``EnumFieldMetadataSchema`` entries, one per
    registered enum field.  Currently registered fields:

    * ``order_type`` — 주문 유형 (지정가/시장가/조건부지정가)
    """
    return EnumMetadataListResponse(
        fields=[_serialize_field(meta) for meta in ENUM_METADATA.values()]
    )


@router.get("/enums/{field}", response_model=EnumFieldMetadataSchema)
async def get_enum_field_metadata(field: str) -> EnumFieldMetadataSchema:
    """Get metadata for a single enum field by name.

    Returns 404 with ``detail="Enum metadata not found: {field}"`` when
    the field is not registered.
    """
    meta = get_enum_field(field)
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"Enum metadata not found: {field}",
        )
    return _serialize_field(meta)
