#!/usr/bin/env python3
"""Seeded News EI Quality Comparison Observer (Phase P-5)

Read-only 관측 스크립트 — DB/API 쓰기 없음, 외부 Provider 호출 없음.

Seeded News ON/OFF 상태에서 각각 ``run_decision_loop``를 1회 실행하고,
EI Agent output (event_bias, event_conflict, event_reason_codes)을 수집하여
ON/OFF 비교 결과를 JSON 파일 + Markdown table로 출력한다.

Usage
-----
    # ON/OFF 비교 실행 (기본)
    python3 -m scripts.observe_seeded_news_comparison

    # 특정 종목만
    python3 -m scripts.observe_seeded_news_comparison --symbols 005930,000660

    # OFF만 실행
    python3 -m scripts.observe_seeded_news_comparison --mode off

    # ON만 실행
    python3 -m scripts.observe_seeded_news_comparison --mode on

    # 둘 다 실행 (비교)
    python3 -m scripts.observe_seeded_news_comparison --mode both

    # 출력 디렉토리 지정
    python3 -m scripts.observe_seeded_news_comparison --output-dir /tmp/observations

Exit code
---------
    0 — observation completed
    1 — unexpected error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_SYMBOLS = "005930,000660,035420,005380"
DEFAULT_OUTPUT_DIR = "data/observations"
PAPER_LOOP_MODULE = "scripts.run_decision_loop"

SEP = "=" * 78
DASH = "-" * 78


# ── Core comparison logic ────────────────────────────────────────────────────


async def run_comparison(
    symbols: list[str],
    mode: str,       # "on", "off", "both"
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Run seeded news ON/OFF comparison and collect EI output per symbol.

    Parameters
    ----------
    symbols:
        List of ticker symbols to evaluate (e.g. ``["005930", "000660"]``).
    mode:
        Comparison mode: ``"on"``, ``"off"``, or ``"both"``.
    output_dir:
        Directory to write the JSON result file.

    Returns
    -------
    dict
        Structured results keyed by symbol, with ``"on"`` / ``"off"`` sub-dicts
        containing EI output fields and metadata.
    """
    os.makedirs(output_dir, exist_ok=True)

    results: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "mode": mode,
    }

    for symbol in symbols:
        logger.info("%s\nSymbol: %s\n%s", SEP, symbol, DASH)
        symbol_results: dict[str, Any] = {}

        if mode in ("on", "both"):
            logger.info("Running with SEEDED_NEWS_ENABLED=1 (ON) ...")
            output_on = await _run_one_cycle_and_collect(
                symbol=symbol,
                seeded_enabled=True,
            )
            symbol_results["on"] = output_on
            _log_ei_output(output_on, mode_label="ON")

        if mode in ("off", "both"):
            logger.info("Running with SEEDED_NEWS_ENABLED=0 (OFF) ...")
            output_off = await _run_one_cycle_and_collect(
                symbol=symbol,
                seeded_enabled=False,
            )
            symbol_results["off"] = output_off
            _log_ei_output(output_off, mode_label="OFF")

        results[symbol] = symbol_results

    # ── Save to JSON file ─────────────────────────────────────────────────
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"comparison_{timestamp_str}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    logger.info("Results saved to: %s", output_path)
    results["_output_path"] = output_path

    return results


async def _run_one_cycle_and_collect(
    symbol: str,
    seeded_enabled: bool,  # kept for API compatibility; always treated as False
) -> dict[str, Any]:
    """Run ``run_decision_loop`` as subprocess and collect EI output.

    The script is invoked in ``--dry-run`` mode (no broker submit) with
    a single cycle (``--count 1``) and JSON output (``--output json``).

    Parameters
    ----------
    symbol:
        Ticker symbol (e.g. ``"005930"``).
    seeded_enabled:
        Kept only for API compatibility; **internally always treated as False**
        to prevent accidental NAVER quota consumption.

    Returns
    -------
    dict
        Parsed JSON output from the decision cycle, including ``ei_output``
        if available.  Falls back to an error dict if the subprocess fails.
    """
    env = os.environ.copy()
    # ★ Safety: always disable SEEDED_NEWS_ENABLED to prevent accidental NAVER quota consumption
    env["SEEDED_NEWS_ENABLED"] = "0"
    env["TRADING_UNIVERSE_SYMBOLS"] = symbol

    cmd = [
        sys.executable,
        "-m",
        PAPER_LOOP_MODULE,
        "--count", "1",
        "--output", "json",
        "--dry-run",
    ]

    logger.debug("Running: %s", " ".join(cmd))
    logger.debug("  SEEDED_NEWS_ENABLED=%s", env["SEEDED_NEWS_ENABLED"])
    logger.debug("  TRADING_UNIVERSE_SYMBOLS=%s", symbol)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    # ── Parse JSON output lines ──────────────────────────────────────────
    output: dict[str, Any] = {
        "seeded_enabled": seeded_enabled,
        "symbol": symbol,
        "returncode": proc.returncode,
    }

    stdout_decoded = stdout.decode("utf-8", errors="replace")
    stderr_decoded = stderr.decode("utf-8", errors="replace")

    for line in stdout_decoded.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                # Merge cycle-level fields into output
                output.update(parsed)
        except json.JSONDecodeError:
            # Skip non-JSON lines (e.g. logging output)
            pass

    if proc.returncode != 0:
        logger.warning(
            "Subprocess exited with code %d for symbol=%s seeded=%s",
            proc.returncode,
            symbol,
            seeded_enabled,
        )

    if stderr_decoded:
        # Truncate stderr to avoid bloating the result
        output["stderr_preview"] = stderr_decoded[:500]

    return output


def _log_ei_output(output: dict[str, Any], mode_label: str) -> None:
    """Log EI output fields for human-readable console output."""
    ei = output.get("ei_output")
    if ei is not None and isinstance(ei, dict):
        logger.info(
            "[%s] event_bias=%s event_conflict=%s event_reason_codes=%s",
            mode_label,
            ei.get("event_bias", "N/A"),
            ei.get("event_conflict", "N/A"),
            ei.get("event_reason_codes", "N/A"),
        )
    else:
        logger.info("[%s] ei_output not available (status=%s)", mode_label, output.get("status", "N/A"))


# ── Table formatting ─────────────────────────────────────────────────────────


def _format_comparison_table(results: dict[str, Any]) -> str:
    """Format results as a Markdown comparison table.

    Parameters
    ----------
    results:
        The structured results dict from ``run_comparison()``.

    Returns
    -------
    str
        Markdown-formatted table string.
    """
    lines: list[str] = []
    lines.append("## Seeded News ON/OFF EI Quality Comparison")
    lines.append("")
    lines.append(f"- **Timestamp**: {results.get('timestamp', 'N/A')}")
    lines.append(f"- **Symbols**: {', '.join(results.get('symbols', []))}")
    lines.append(f"- **Mode**: {results.get('mode', 'N/A')}")
    output_path = results.get("_output_path")
    if output_path:
        lines.append(f"- **Output file**: `{output_path}`")
    lines.append("")

    # Table header
    lines.append("| Symbol | Mode | Status | Decision Type | Event Bias | Event Conflict | Event Reason Codes |")
    lines.append("|--------|------|--------|---------------|------------|----------------|--------------------|")

    for symbol in results.get("symbols", []):
        symbol_data = results.get(symbol, {})
        for mode_key in ("on", "off"):
            data = symbol_data.get(mode_key, {})
            status = data.get("status", "N/A")
            decision_type = data.get("decision_type", "N/A")

            ei = data.get("ei_output")
            if isinstance(ei, dict):
                event_bias = str(ei.get("event_bias", "N/A"))
                event_conflict = str(ei.get("event_conflict", "N/A"))
                event_reason_codes = str(ei.get("event_reason_codes", "N/A"))
            else:
                event_bias = "N/A"
                event_conflict = "N/A"
                event_reason_codes = "N/A"

            lines.append(
                f"| {symbol} | {mode_key} | {status} | {decision_type} | "
                f"{event_bias} | {event_conflict} | {event_reason_codes} |"
            )

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Seeded News EI Quality Comparison Observer (Phase P-5)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=DEFAULT_SYMBOLS,
        help=f"Comma-separated symbol list (default: {DEFAULT_SYMBOLS})",
    )
    parser.add_argument(
        "--mode",
        choices=["on", "off", "both"],
        default="both",
        help="Comparison mode: on, off, or both (default: both)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for JSON result file (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args(argv)


# ── Entrypoint ───────────────────────────────────────────────────────────────


async def main(argv: list[str] | None = None) -> int:
    """Entry point for the Seeded News EI Quality comparison.

    Returns exit code 0 on success, 1 on error.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] observe-seeded-news: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = _parse_args(argv)
    symbols = args.symbols.split(",")
    mode = args.mode
    output_dir = args.output_dir

    logger.info("Seeded News EI Quality Comparison Observer (Phase P-5)")
    logger.info("Symbols: %s", symbols)
    logger.info("Mode: %s", mode)
    logger.info("Output dir: %s", output_dir)

    results = await run_comparison(
        symbols=symbols,
        mode=mode,
        output_dir=output_dir,
    )

    # Print comparison table
    table = _format_comparison_table(results)
    print()
    print(table)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
