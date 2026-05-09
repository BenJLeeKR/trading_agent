"""Tests for ``scripts.run_event_ingestion_loop`` — event ingestion loop runner.

Test coverage
-------------
* ``_serialize_cycle_result()`` — 순수 함수 직렬화 정확성 (3 tests)
* ``_build_aggregate_summary()`` — 집계 요약 정확성 (2 tests)
* ``_run_one_source()`` — source isolation + 정상/오류 (3 tests)
* ``_run_one_cycle()`` — mocked runtime으로 cycle 실행 검증 (3 tests)
* ``_parse_args()`` — CLI 인자 파싱 (4 tests)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from scripts.run_event_ingestion_loop import (
    _build_aggregate_summary,
    _parse_args,
    _run_one_cycle,
    _run_one_source,
    _serialize_cycle_result,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class _StubPollingWorker:
    """Stub ``PollingWorker`` that returns a canned ``poll_once()`` result."""

    def __init__(
        self,
        source_name: str,
        *,
        poll_once_result: int = 0,
        poll_once_error: Exception | None = None,
    ) -> None:
        self._source_name = source_name
        self._poll_once_result = poll_once_result
        self._poll_once_error = poll_once_error

    @property
    def source_name(self) -> str:
        return self._source_name

    async def poll_once(self) -> int:
        if self._poll_once_error is not None:
            raise self._poll_once_error
        await asyncio.sleep(0)  # Force context switch so time.monotonic() advances
        return self._poll_once_result


@asynccontextmanager
async def _mock_runtime() -> AsyncIterator[dict[str, Any]]:
    """Build a mock runtime with in-memory repositories.

    Yields a runtime dict that can be used as ``postgres_runtime`` mock return.
    """
    from agent_trading.config.settings import AppSettings
    from agent_trading.repositories.bootstrap import build_in_memory_repositories

    repos = build_in_memory_repositories()
    settings = AppSettings()  # opendart_api_key="" → no workers by default
    yield {
        "repositories": repos,
        "settings": settings,
    }


# ---------------------------------------------------------------------------
# TestSerializeCycleResult
# ---------------------------------------------------------------------------


class TestSerializeCycleResult:
    """``_serialize_cycle_result()`` — 순수 함수 직렬화 정확성."""

    def test_all_sources_ok(self) -> None:
        """모든 source 정상 → total_new_events 합계, total_errors=0."""
        sources = [
            {
                "source_name": "opendart",
                "status": "ok",
                "new_events": 5,
                "duration_seconds": 0.5,
                "error_message": None,
            },
            {
                "source_name": "krx",
                "status": "ok",
                "new_events": 3,
                "duration_seconds": 0.3,
                "error_message": None,
            },
        ]
        result = _serialize_cycle_result(1, sources, duration=1.0)

        assert result["cycle"] == 1
        assert result["total_new_events"] == 8
        assert result["total_errors"] == 0
        assert len(result["sources"]) == 2
        assert result["duration_seconds"] == 1.0
        assert result.get("error") is None

    def test_some_sources_error(self) -> None:
        """일부 source 오류 → total_errors 집계, new_events는 정상 source만."""
        sources = [
            {
                "source_name": "opendart",
                "status": "ok",
                "new_events": 5,
                "duration_seconds": 0.5,
                "error_message": None,
            },
            {
                "source_name": "krx",
                "status": "error",
                "new_events": 0,
                "duration_seconds": 0.3,
                "error_message": "Connection timeout",
            },
        ]
        result = _serialize_cycle_result(2, sources, duration=0.8)

        assert result["cycle"] == 2
        assert result["total_new_events"] == 5  # Only from opendart
        assert result["total_errors"] == 1
        assert result.get("error") is None

    def test_with_top_level_error(self) -> None:
        """최상위 error 포함 → data["error"] 설정."""
        result = _serialize_cycle_result(
            3,
            source_results=[],
            duration=0.1,
            error="Runtime error",
        )
        assert result["error"] == "Runtime error"
        assert result["total_new_events"] == 0
        assert result["total_errors"] == 0


# ---------------------------------------------------------------------------
# TestBuildAggregateSummary
# ---------------------------------------------------------------------------


class TestBuildAggregateSummary:
    """``_build_aggregate_summary()`` — 집계 요약 정확성."""

    def test_single_source_multiple_cycles(self) -> None:
        """단일 source, 여러 cycle → per-source total 집계."""
        results = [
            {
                "cycle": 1,
                "total_new_events": 5,
                "total_errors": 0,
                "sources": [
                    {
                        "source_name": "opendart",
                        "status": "ok",
                        "new_events": 5,
                        "duration_seconds": 0.5,
                    },
                ],
            },
            {
                "cycle": 2,
                "total_new_events": 3,
                "total_errors": 0,
                "sources": [
                    {
                        "source_name": "opendart",
                        "status": "ok",
                        "new_events": 3,
                        "duration_seconds": 0.4,
                    },
                ],
            },
        ]
        summary = _build_aggregate_summary(results, total_duration=60.0)

        assert summary["mode"] == "summary"
        assert summary["total_cycles"] == 2
        assert summary["total_new_events"] == 8
        assert summary["total_errors"] == 0

        source_totals = summary["source_totals"]
        assert len(source_totals) == 1
        assert source_totals[0]["source_name"] == "opendart"
        assert source_totals[0]["cycles"] == 2
        assert source_totals[0]["total_new"] == 8
        assert source_totals[0]["total_errors"] == 0

    def test_mixed_sources_some_errors(self) -> None:
        """다중 source, 일부 오류 포함 → 각 source별 총계."""
        results = [
            {
                "cycle": 1,
                "total_new_events": 5,
                "total_errors": 1,
                "sources": [
                    {
                        "source_name": "opendart",
                        "status": "ok",
                        "new_events": 5,
                        "duration_seconds": 0.5,
                    },
                    {
                        "source_name": "krx",
                        "status": "error",
                        "new_events": 0,
                        "duration_seconds": 0.3,
                        "error_message": "Timeout",
                    },
                ],
            },
        ]
        summary = _build_aggregate_summary(results, total_duration=30.0)

        assert summary["total_new_events"] == 5
        assert summary["total_errors"] == 1

        source_totals = summary["source_totals"]
        assert len(source_totals) == 2

        opendart = [s for s in source_totals if s["source_name"] == "opendart"][0]
        assert opendart["total_new"] == 5
        assert opendart["total_errors"] == 0

        krx = [s for s in source_totals if s["source_name"] == "krx"][0]
        assert krx["total_new"] == 0
        assert krx["total_errors"] == 1


# ---------------------------------------------------------------------------
# TestRunOneSource
# ---------------------------------------------------------------------------


class TestRunOneSource:
    """``_run_one_source()`` — source isolation + 정상/오류 처리."""

    @pytest.mark.asyncio
    async def test_normal_poll(self) -> None:
        """정상 poll → status=ok, new_events=5."""
        worker = _StubPollingWorker("opendart", poll_once_result=5)
        result = await _run_one_source(worker)  # type: ignore[arg-type]

        assert result["source_name"] == "opendart"
        assert result["status"] == "ok"
        assert result["new_events"] == 5
        assert result["error_message"] is None
        assert result["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_zero_events(self) -> None:
        """새 이벤트 없음 → status=ok, new_events=0."""
        worker = _StubPollingWorker("opendart", poll_once_result=0)
        result = await _run_one_source(worker)  # type: ignore[arg-type]

        assert result["status"] == "ok"
        assert result["new_events"] == 0

    @pytest.mark.asyncio
    async def test_poll_error(self) -> None:
        """poll_once() 예외 → status=error, error_message 설정."""
        worker = _StubPollingWorker(
            "opendart",
            poll_once_error=RuntimeError("API unavailable"),
        )
        result = await _run_one_source(worker)  # type: ignore[arg-type]

        assert result["source_name"] == "opendart"
        assert result["status"] == "error"
        assert result["new_events"] == 0
        assert "API unavailable" in (result["error_message"] or "")


# ---------------------------------------------------------------------------
# TestRunOneCycle
# ---------------------------------------------------------------------------


class TestRunOneCycle:
    """``_run_one_cycle()`` — mocked runtime으로 cycle 실행 검증."""

    @pytest.mark.asyncio
    async def test_no_workers(self) -> None:
        """polling worker 미설치 → 빈 source_results, total_new_events=0."""
        with patch(
            "scripts.run_event_ingestion_loop.postgres_runtime",
            return_value=_mock_runtime(),
        ):
            result = await _run_one_cycle(cycle=1)

        assert result["cycle"] == 1
        assert result["total_new_events"] == 0
        assert result["total_errors"] == 0
        assert len(result["sources"]) == 0

    @pytest.mark.asyncio
    async def test_with_workers(self) -> None:
        """2개 source 정상 → total_new_events=8, errors=0."""
        workers = [
            _StubPollingWorker("opendart", poll_once_result=5),
            _StubPollingWorker("krx", poll_once_result=3),
        ]

        with patch(
            "scripts.run_event_ingestion_loop.postgres_runtime",
            return_value=_mock_runtime(),
        ):
            with patch(
                "scripts.run_event_ingestion_loop._build_polling_workers",
                return_value=workers,
            ):
                result = await _run_one_cycle(cycle=1)

        assert result["total_new_events"] == 8
        assert result["total_errors"] == 0
        assert len(result["sources"]) == 2

        src_names = [s["source_name"] for s in result["sources"]]
        assert "opendart" in src_names
        assert "krx" in src_names

    @pytest.mark.asyncio
    async def test_source_error_isolation(self) -> None:
        """하나의 source 오류 → 다른 source는 정상 처리, total_errors=1."""
        workers = [
            _StubPollingWorker("opendart", poll_once_result=5),
            _StubPollingWorker(
                "krx",
                poll_once_error=RuntimeError("Connection failed"),
            ),
            _StubPollingWorker("news", poll_once_result=2),
        ]

        with patch(
            "scripts.run_event_ingestion_loop.postgres_runtime",
            return_value=_mock_runtime(),
        ):
            with patch(
                "scripts.run_event_ingestion_loop._build_polling_workers",
                return_value=workers,
            ):
                result = await _run_one_cycle(cycle=1)

        assert result["total_new_events"] == 7  # 5 + 0 + 2
        assert result["total_errors"] == 1  # krx failed

        # Verify per-source statuses
        statuses = {
            s["source_name"]: s["status"]
            for s in result["sources"]
        }
        assert statuses["opendart"] == "ok"
        assert statuses["krx"] == "error"
        assert statuses["news"] == "ok"


# ---------------------------------------------------------------------------
# TestParseArgs
# ---------------------------------------------------------------------------


class TestParseArgs:
    """``_parse_args()`` — CLI 인자 파싱."""

    def test_defaults(self) -> None:
        """기본 인자 → interval=0(count는 env), count=0(infinite), output=text."""
        args = _parse_args([])
        assert args.interval == 0
        assert args.count == 0
        assert args.output == "text"
        assert args.dry_run is False

    def test_count_one(self) -> None:
        """--count 1 → count=1."""
        args = _parse_args(["--count", "1"])
        assert args.count == 1
        assert args.interval == 0

    def test_interval(self) -> None:
        """--interval 30 → interval=30."""
        args = _parse_args(["--interval", "30"])
        assert args.interval == 30

    def test_json_output(self) -> None:
        """--output json → output=json."""
        args = _parse_args(["--output", "json"])
        assert args.output == "json"

    def test_dry_run(self) -> None:
        """--dry-run → dry_run=True."""
        args = _parse_args(["--dry-run"])
        assert args.dry_run is True
