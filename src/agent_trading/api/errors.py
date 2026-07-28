"""Inspection API 오류 응답 helper."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_SENSITIVE_FIELD_TOKENS = (
    "authorization",
    "token",
    "secret",
    "password",
    "api_key",
    "app_key",
    "app_secret",
    "account_no",
    "account_number",
    "account_ref",
    "kis_account",
)


def build_error_detail(
    *,
    error_code: str,
    message: str,
    field: str | None = None,
    expected: str | None = None,
    received: object | None = None,
    request_path: str | None = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    """AI가 파싱 가능한 API 오류 ``detail`` 객체를 만든다.

    기존 endpoint에는 아직 연결하지 않는다. 신규 또는 전환 대상 endpoint에서
    ``HTTPException(detail=build_error_detail(...))`` 형태로 사용한다.
    """

    _validate_error_code(error_code)

    detail: dict[str, Any] = {
        "error_code": error_code,
        "message": message,
    }
    optional_values = {
        "field": field,
        "expected": expected,
        "received": _redact_received(field, received),
        "request_path": request_path,
        "next_action": next_action,
    }
    for key, value in optional_values.items():
        if value is not None:
            detail[key] = value
    return detail


def build_http_exception(
    *,
    status_code: int,
    error_code: str,
    message: str,
    structured_detail: bool = False,
    field: str | None = None,
    expected: str | None = None,
    received: object | None = None,
    request_path: str | None = None,
    next_action: str | None = None,
) -> HTTPException:
    """호환성을 유지하는 ``HTTPException``을 만든다.

    기본값은 기존 API와 같은 문자열 ``detail``이다. 구조화 응답은
    ``structured_detail=True``를 명시한 신규 또는 전환 endpoint에서만
    opt-in으로 사용한다.
    """

    _validate_error_code(error_code)
    if not structured_detail:
        return HTTPException(status_code=status_code, detail=message)
    return HTTPException(
        status_code=status_code,
        detail=build_error_detail(
            error_code=error_code,
            message=message,
            field=field,
            expected=expected,
            received=received,
            request_path=request_path,
            next_action=next_action,
        ),
    )


def invalid_uuid_detail(
    *,
    field: str,
    received: object | None = None,
    request_path: str | None = None,
) -> dict[str, Any]:
    """UUID 입력 검증 실패용 표준 detail 객체를 만든다."""

    return build_error_detail(
        error_code=f"invalid_{field}",
        message=f"Invalid {field} UUID",
        field=field,
        expected="UUID string",
        received=received,
        request_path=request_path,
        next_action=f"check {field} format",
    )


def invalid_date_detail(
    *,
    field: str,
    received: object | None = None,
    request_path: str | None = None,
) -> dict[str, Any]:
    """YYYY-MM-DD 날짜 입력 검증 실패용 표준 detail 객체를 만든다."""

    return build_error_detail(
        error_code=f"invalid_{field}",
        message=f"Invalid {field}",
        field=field,
        expected="YYYY-MM-DD",
        received=received,
        request_path=request_path,
        next_action=f"check {field} format",
    )


def invalid_date_range_detail(
    *,
    start_field: str = "start_date",
    end_field: str = "end_date",
    request_path: str | None = None,
) -> dict[str, Any]:
    """시작일이 종료일보다 늦은 날짜 범위 오류 detail 객체를 만든다."""

    return build_error_detail(
        error_code="invalid_date_range",
        message=f"{start_field} must be on or before {end_field}",
        field=f"{start_field},{end_field}",
        expected=f"{start_field} <= {end_field}",
        request_path=request_path,
        next_action="check date range",
    )


def _validate_error_code(error_code: str) -> None:
    if not _ERROR_CODE_PATTERN.fullmatch(error_code):
        raise ValueError(f"invalid error_code: {error_code!r}")


def _redact_received(field: str | None, received: object | None) -> object | None:
    if received is None:
        return None
    if field is None:
        return received
    normalized = field.lower()
    if any(token in normalized for token in _SENSITIVE_FIELD_TOKENS):
        return "present-redacted"
    return received
