#!/usr/bin/env python3
"""Event ingestion loop — 외부 이벤트 수집 운영 데몬.

``_build_polling_workers()``가 생성하는 ``PollingWorker`` 인스턴스들을
주기적으로 실행하고 cycle summary를 제공한다.

역할 분리 (4-loop decomposition)
--------------------------------
* ``run_snapshot_sync_loop.py`` — Position/Cash 데이터 최신성 유지 (300s)
* ``run_post_submit_sync_loop.py`` — 미체결/부분체결 주문 상태 Broker 수렴 (30s)
* ``run_paper_decision_loop.py`` — AI Decision → Submit 반복 실행 (300s)
* ``run_event_ingestion_loop.py`` — 외부 이벤트 수집 (60s, 신규)

Decision loop와의 연결
-----------------------
* Event ingestion loop → ``ExternalEventRepository.add()`` → DB
* Decision orchestrator ``assemble()`` → ``external_events.list_by_symbol()``
  → ``AssembledContext.recent_events`` → AI agent
* 두 loop는 DB를 통해 데이터만 공유 (직접 의존성 없음)

Usage
-----
.. code-block:: bash

    # 기본 실행 (60초 간격, 무한 반복)
    python -m scripts.run_event_ingestion_loop

    # 1회 실행 후 종료
    python -m scripts.run_event_ingestion_loop --count 1

    # 30초 간격, 10회, JSON 출력
    python -m scripts.run_event_ingestion_loop --interval 30 --count 10 --output json

    # Dry-run (fetch + dedup 확인만, persist 없음)
    python -m scripts.run_event_ingestion_loop --count 1 --dry-run

환경 변수
---------
* ``EVENT_INGESTION_LOOP_INTERVAL_SECONDS`` — 기본 interval (기본 60)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

from agent_trading.brokers.polling_worker import PollingWorker
from agent_trading.config.settings import AppSettings
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.runtime.bootstrap import _build_polling_workers, postgres_runtime

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_INTERVAL_SECONDS = 60
ENV_INTERVAL = "EVENT_INGESTION_LOOP_INTERVAL_SECONDS"

# ── Signal handling ─────────────────────────────────────────────────────────

_shutdown_event = asyncio.Event()


def _handle_signal(signum: int, _frame: object) -> None:
    """Set shutdown event on SIGTERM/SIGINT."""
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — completing current cycle then exiting ...", sig_name)
    _shutdown_event.set()


def _install_signal_handlers() -> None:
    """Install signal handlers for graceful shutdown."""
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s, None))
        except NotImplementedError:
            signal.signal(sig, _handle_signal)


# ── Config helpers ──────────────────────────────────────────────────────────


def _read_interval() -> int:
    """Read the event ingestion loop interval from the environment (seconds)."""
    raw = os.getenv(ENV_INTERVAL)
    if raw is None:
        return DEFAULT_INTERVAL_SECONDS
    try:
        val = int(raw)
        if val < 5:
            logger.warning(
                "Interval %d is too short (< 5s), using %d instead.",
                val,
                DEFAULT_INTERVAL_SECONDS,
            )
            return DEFAULT_INTERVAL_SECONDS
        return val
    except (ValueError, TypeError):
        logger.warning(
            "Invalid %s=%r, using default %d.",
            ENV_INTERVAL,
            raw,
            DEFAULT_INTERVAL_SECONDS,
        )
        return DEFAULT_INTERVAL_SECONDS


# ── Source isolation ────────────────────────────────────────────────────────


async def _run_one_source(worker: PollingWorker) -> dict[str, object]:
    """Execute a single poll for one source adapter with error isolation.

    Returns a per-source result dict. One source failure does NOT affect
    other sources within the same cycle.
    """
    start = time.monotonic()
    source_name = worker.source_name

    try:
        count = await worker.poll_once()
        duration = time.monotonic() - start
        return {
            "source_name": source_name,
            "status": "ok",
            "new_events": count,
            "duration_seconds": round(duration, 3),
            "error_message": None,
        }
    except Exception as exc:
        duration = time.monotonic() - start
        logger.exception("Source '%s' poll failed: %s", source_name, exc)
        return {
            "source_name": source_name,
            "status": "error",
            "new_events": 0,
            "duration_seconds": round(duration, 3),
            "error_message": str(exc),
        }


# ── Result serialization ────────────────────────────────────────────────────


def _serialize_cycle_result(
    cycle: int,
    source_results: list[dict[str, object]],
    duration: float,
    *,
    error: str | None = None,
) -> dict[str, object]:
    """Serialize a single event ingestion cycle result."""
    started_at = datetime.now(timezone.utc).isoformat()
    completed_at = datetime.now(timezone.utc).isoformat()

    total_new = sum(
        r.get("new_events", 0) for r in source_results if r.get("status") == "ok"
    )
    total_errors = sum(1 for r in source_results if r.get("status") == "error")

    data: dict[str, object] = {
        "cycle": cycle,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(duration, 3),
        "sources": source_results,
        "total_new_events": total_new,
        "total_errors": total_errors,
    }

    if error:
        data["error"] = error

    return data


def _build_aggregate_summary(
    results: list[dict[str, object]],
    total_duration: float,
) -> dict[str, object]:
    """Build an aggregate summary from all cycle results."""
    total_cycles = len(results)
    total_new = sum(r.get("total_new_events", 0) for r in results)
    total_errors = sum(r.get("total_errors", 0) for r in results)

    # Per-source aggregation
    source_totals: dict[str, dict[str, object]] = {}
    for cycle_result in results:
        sources = cycle_result.get("sources", [])
        if not isinstance(sources, list):
            continue
        for src in sources:
            if not isinstance(src, dict):
                continue
            name = src.get("source_name", "unknown")
            if name not in source_totals:
                source_totals[name] = {
                    "source_name": name,
                    "cycles": 0,
                    "total_new": 0,
                    "total_errors": 0,
                }
            source_totals[name]["cycles"] += 1  # type: ignore[operator]
            source_totals[name]["total_new"] += src.get("new_events", 0)  # type: ignore[operator]
            if src.get("status") == "error":
                source_totals[name]["total_errors"] += 1  # type: ignore[operator]

    return {
        "mode": "summary",
        "total_cycles": total_cycles,
        "total_new_events": total_new,
        "total_errors": total_errors,
        "source_totals": list(source_totals.values()),
        "total_duration_seconds": round(total_duration, 3),
    }


# ── Core cycle ──────────────────────────────────────────────────────────────


async def _run_one_cycle(
    cycle: int,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    """Execute a single event ingestion cycle.

    1. Open a fresh DB connection (``postgres_runtime``).
    2. Build polling workers via ``_build_polling_workers()``.
    3. Poll each source adapter with error isolation.
    4. Serialize and return the cycle result.
    """
    start = time.monotonic()

    try:
        async with postgres_runtime(run_migrations=False) as runtime:
            repos: RepositoryContainer = runtime["repositories"]
            settings: AppSettings = runtime["settings"]

            workers = _build_polling_workers(repos, settings)
            if not workers:
                logger.info("Cycle %d: no polling workers configured.", cycle)
                duration = time.monotonic() - start
                return _serialize_cycle_result(
                    cycle,
                    source_results=[],
                    duration=duration,
                )

            source_results: list[dict[str, object]] = []
            for worker in workers:
                result = await _run_one_source(worker)
                source_results.append(result)

                if result["status"] == "ok" and result["new_events"] > 0:
                    logger.info(
                        "Source '%s': %d new event(s) ingested.",
                        result["source_name"],
                        result["new_events"],
                    )
                elif result["status"] == "ok":
                    logger.debug("Source '%s': no new events.", result["source_name"])
                else:
                    logger.warning(
                        "Source '%s': poll failed: %s",
                        result["source_name"],
                        result.get("error_message"),
                    )

            duration = time.monotonic() - start
            return _serialize_cycle_result(
                cycle,
                source_results=source_results,
                duration=duration,
            )

    except Exception as exc:
        duration = time.monotonic() - start
        logger.exception("Cycle %d failed: %s", cycle, exc)
        return _serialize_cycle_result(
            cycle,
            source_results=[],
            duration=duration,
            error=str(exc),
        )


# ── Main loop ───────────────────────────────────────────────────────────────


async def _run_loop(
    *,
    interval: int,
    max_cycles: int,
    output: str,
) -> int:
    """Main loop: run event ingestion cycles until shutdown or count limit.

    Returns an exit code (0 = all cycles successful, 1 = any error).
    """
    logger.info(
        "Starting event ingestion loop "
        "(interval=%ds, max_cycles=%s, output=%s) ...",
        interval,
        "infinite" if max_cycles <= 0 else str(max_cycles),
        output,
    )
    logger.info("Set %s to change interval (default=%d).", ENV_INTERVAL, DEFAULT_INTERVAL_SECONDS)

    _install_signal_handlers()

    cycle_count = 0
    results: list[dict[str, object]] = []
    loop_start = time.monotonic()

    while not _shutdown_event.is_set():
        # Check cycle limit
        if max_cycles > 0 and cycle_count >= max_cycles:
            logger.info("Reached requested cycle count (%d).", max_cycles)
            break

        cycle_count += 1
        logger.info("=== Event Ingestion Cycle %d ===", cycle_count)

        # Run ingestion cycle
        result = await _run_one_cycle(cycle=cycle_count)
        results.append(result)

        total_new = result.get("total_new_events", 0)
        total_errors = result.get("total_errors", 0)

        # Output per-cycle result
        if output == "json":
            print(json.dumps(result, ensure_ascii=False))
        else:
            source_summaries = "; ".join(
                f"{s['source_name']}={s['new_events']}new"
                if s["status"] == "ok"
                else f"{s['source_name']}=ERR"
                for s in result.get("sources", [])
                if isinstance(s, dict)
            )
            logger.info(
                "Cycle %d/%s complete — new=%d errors=%d duration=%.2fs [%s]",
                cycle_count,
                "∞" if max_cycles == 0 else str(max_cycles),
                total_new,
                total_errors,
                result.get("duration_seconds", 0),
                source_summaries or "no sources",
            )

        # Wait for next cycle (or shutdown)
        if max_cycles > 0 and cycle_count >= max_cycles:
            break

        logger.debug(
            "Waiting %d seconds before next cycle …",
            interval,
        )
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(),
                timeout=interval,
            )
            # Shutdown event was set during sleep
            break
        except asyncio.TimeoutError:
            pass

    # ── Final summary ──
    total_duration = time.monotonic() - loop_start
    summary = _build_aggregate_summary(results, total_duration)

    if output == "json":
        print(json.dumps(summary, ensure_ascii=False))
    else:
        logger.info("=" * 60)
        logger.info("Event ingestion loop complete.")
        logger.info("  total cycles   : %d", summary["total_cycles"])
        logger.info("  total new events : %d", summary["total_new_events"])
        logger.info("  total errors   : %d", summary["total_errors"])
        source_totals = summary.get("source_totals", [])
        if source_totals:
            logger.info("  per-source:")
            for st in source_totals:
                logger.info(
                    "    %s: cycles=%d new=%d errors=%d",
                    st.get("source_name", "?"),
                    st.get("cycles", 0),
                    st.get("total_new", 0),
                    st.get("total_errors", 0),
                )
        logger.info("  total time     : %.1fs", summary["total_duration_seconds"])
        logger.info("=" * 60)

    return 0 if total_errors == 0 else 1


# ── CLI ─────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Event ingestion loop — poll external event sources "
                    "and persist normalised events for the decision loop.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help=f"Seconds between ingestion cycles (default: {DEFAULT_INTERVAL_SECONDS}s, "
             f"overridable via {ENV_INTERVAL}).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of cycles to run (0 = infinite, default).",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format: ``text`` (human-readable) or ``json`` (machine-readable).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Dry-run mode — not currently supported at per-source level. "
             "PollingWorker internally persists; this flag is reserved.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the event ingestion loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] event-ingestion-loop: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = _parse_args(argv)

    interval = args.interval or _read_interval()
    max_cycles = args.count

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        exit_code = loop.run_until_complete(
            _run_loop(
                interval=interval,
                max_cycles=max_cycles,
                output=args.output,
            )
        )
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — exiting.")
        exit_code = 0
    finally:
        try:
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
