from __future__ import annotations

import enum
import json
import typing
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

import asyncpg

T = TypeVar("T")

# Cache: {entity_class: {field_name: enum_type_or_None}}
_enum_field_cache: dict[type, dict[str, type[enum.Enum] | None]] = {}


def _get_enum_field_types(entity_class: type) -> dict[str, type[enum.Enum] | None]:
    """Return a mapping of field name → Enum subclass (or None) for a dataclass.

    Inspects the type annotation of each dataclass field.  If the annotation
    is a subclass of ``enum.Enum``, the enum type is cached and returned.
    Otherwise ``None`` is cached so that repeated lookups are O(1).

    Uses ``typing.get_type_hints()`` to resolve string annotations (which
    arise from ``from __future__ import annotations``) into actual types.
    """
    if entity_class not in _enum_field_cache:
        # get_type_hints() resolves string annotations to real types
        hints = typing.get_type_hints(entity_class)
        fields = entity_class.__dataclass_fields__
        mapping: dict[str, type[enum.Enum] | None] = {}
        for fname, fdesc in fields.items():
            raw_type = hints.get(fname)
            if raw_type is None:
                mapping[fname] = None
                continue
            # Resolve ``Optional[X]``, ``X | None``, ``Union[X, None]`` to X
            origin = typing.get_origin(raw_type)
            args = typing.get_args(raw_type)
            if origin is not None:
                # e.g. Optional[OrderStatus] → Union[OrderStatus, None] → OrderStatus
                for arg in args:
                    if arg is not type(None) and isinstance(arg, type) and issubclass(arg, enum.Enum):
                        mapping[fname] = arg
                        break
                else:
                    mapping[fname] = None
            elif isinstance(raw_type, type) and issubclass(raw_type, enum.Enum):
                mapping[fname] = raw_type
            else:
                mapping[fname] = None
        _enum_field_cache[entity_class] = mapping
    return _enum_field_cache[entity_class]


def row_to_entity(row: asyncpg.Record, entity_class: type[T]) -> T:
    """Convert an asyncpg Record to a dataclass entity.

    Only fields that exist on the target entity class are extracted.
    Fields present in the DB row but absent from the entity are silently
    dropped.  Fields absent from the row but present on the entity keep
    their dataclass default (or raise if no default).

    Type conversions applied automatically:
      - ``datetime`` → timezone-aware (UTC)
      - ``Decimal`` → kept as-is (already Decimal from asyncpg)
      - ``dict`` → kept as-is (JSONB columns arrive as dict)
      - ``UUID`` → kept as-is (already UUID from asyncpg)
      - ``date`` → kept as-is
      - ``int``, ``str``, ``bool`` → kept as-is
      - ``Enum`` subclasses → ``str`` values from DB are auto-converted
        to the corresponding enum member (e.g. ``"draft"`` → ``OrderStatus.DRAFT``)
    """
    raw = dict(row)
    field_names = set(entity_class.__dataclass_fields__)
    enum_types = _get_enum_field_types(entity_class)
    kwargs: dict[str, Any] = {}

    for name, value in raw.items():
        if name not in field_names:
            continue
        value = _convert_value(value)
        # Auto-convert str → Enum if the field type is an Enum subclass
        enum_type = enum_types.get(name)
        if enum_type is not None and isinstance(value, str):
            try:
                value = enum_type(value)
            except ValueError:
                pass  # leave as str if the value doesn't match any member
        kwargs[name] = value

    return entity_class(**kwargs)


def _convert_value(value: Any) -> Any:
    """Apply idempotent type conversions to a raw DB value."""
    if isinstance(value, datetime):
        # Ensure timezone-aware (UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=None)  # keep naive; app handles
        return value
    if isinstance(value, (Decimal, UUID, date, int, str, bool, float)):
        # JSONB columns may be returned as JSON strings by asyncpg
        # when the server-side JSONB codec is not available; attempt
        # to parse them back to Python dicts/lists.
        if isinstance(value, str) and len(value) > 0 and value[0] in ("{", "["):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
        return value
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    if value is None:
        return None
    # Fallback: try JSON serialisation for complex types
    if isinstance(value, (bytes, bytearray)):
        return value
    return value


def entity_to_insert_kwargs(entity: Any) -> dict[str, Any]:
    """Convert a dataclass entity to a dict suitable for INSERT.

    - Removes ``None`` values so DB defaults are used.
    - Keeps ``dict`` values for JSONB columns (asyncpg handles serialisation).
    - Keeps ``Decimal``, ``UUID``, ``datetime`` as-is.
    """
    kwargs = {}
    for field_name, field_value in entity.__dataclass_fields__.items():
        value = getattr(entity, field_name, None)
        if value is None:
            continue
        kwargs[field_name] = value
    return kwargs
