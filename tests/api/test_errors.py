from __future__ import annotations

import pytest

from agent_trading.api.errors import (
    build_error_detail,
    build_http_exception,
    invalid_date_detail,
    invalid_date_range_detail,
    invalid_uuid_detail,
)


def test_build_error_detail_includes_machine_readable_fields() -> None:
    detail = build_error_detail(
        error_code="invalid_account_id",
        message="Invalid account_id UUID",
        field="account_id",
        expected="UUID string",
        received="not-a-uuid",
        request_path="/performance/summary",
        next_action="check account_id format",
    )

    assert detail == {
        "error_code": "invalid_account_id",
        "message": "Invalid account_id UUID",
        "field": "account_id",
        "expected": "UUID string",
        "received": "not-a-uuid",
        "request_path": "/performance/summary",
        "next_action": "check account_id format",
    }


def test_build_error_detail_omits_none_optional_fields() -> None:
    detail = build_error_detail(
        error_code="broker_adapter_not_configured",
        message="Broker adapter not configured",
    )

    assert detail == {
        "error_code": "broker_adapter_not_configured",
        "message": "Broker adapter not configured",
    }


def test_build_error_detail_rejects_unstable_error_code() -> None:
    with pytest.raises(ValueError, match="invalid error_code"):
        build_error_detail(
            error_code="Invalid Account ID",
            message="Invalid account_id UUID",
        )


def test_build_error_detail_redacts_sensitive_received_value() -> None:
    detail = build_error_detail(
        error_code="invalid_authorization",
        message="Invalid authorization header",
        field="authorization",
        received="Bearer secret-token",
    )

    assert detail["received"] == "present-redacted"


def test_build_http_exception_preserves_string_detail_by_default() -> None:
    exc = build_http_exception(
        status_code=400,
        error_code="invalid_account_id",
        message="Invalid account_id UUID",
        field="account_id",
        expected="UUID string",
        received="not-a-uuid",
    )

    assert exc.status_code == 400
    assert exc.detail == "Invalid account_id UUID"


def test_build_http_exception_uses_structured_detail_only_when_opted_in() -> None:
    exc = build_http_exception(
        status_code=400,
        error_code="invalid_authorization",
        message="Invalid authorization header",
        structured_detail=True,
        field="authorization",
        expected="Bearer token",
        received="Bearer secret-token",
        request_path="/orders",
        next_action="check Authorization header",
    )

    assert exc.status_code == 400
    assert exc.detail == {
        "error_code": "invalid_authorization",
        "message": "Invalid authorization header",
        "field": "authorization",
        "expected": "Bearer token",
        "received": "present-redacted",
        "request_path": "/orders",
        "next_action": "check Authorization header",
    }


def test_invalid_uuid_detail_uses_standard_contract() -> None:
    detail = invalid_uuid_detail(
        field="account_id",
        received="not-a-uuid",
        request_path="/accounts/not-a-uuid",
    )

    assert detail["error_code"] == "invalid_account_id"
    assert detail["message"] == "Invalid account_id UUID"
    assert detail["field"] == "account_id"
    assert detail["expected"] == "UUID string"
    assert detail["received"] == "not-a-uuid"
    assert detail["request_path"] == "/accounts/not-a-uuid"
    assert detail["next_action"] == "check account_id format"


def test_invalid_date_detail_uses_standard_contract() -> None:
    detail = invalid_date_detail(field="start_date", received="2026/07/28")

    assert detail["error_code"] == "invalid_start_date"
    assert detail["message"] == "Invalid start_date"
    assert detail["field"] == "start_date"
    assert detail["expected"] == "YYYY-MM-DD"
    assert detail["received"] == "2026/07/28"
    assert detail["next_action"] == "check start_date format"


def test_invalid_date_range_detail_uses_standard_contract() -> None:
    detail = invalid_date_range_detail(request_path="/performance/benchmark-history")

    assert detail == {
        "error_code": "invalid_date_range",
        "message": "start_date must be on or before end_date",
        "field": "start_date,end_date",
        "expected": "start_date <= end_date",
        "request_path": "/performance/benchmark-history",
        "next_action": "check date range",
    }
