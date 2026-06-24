#!/usr/bin/env python3
"""index membership 외부 원천 패키지 반영 파이프라인 실행기."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class PipelineStep:
    name: str
    command: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class PipelineResult:
    step_name: str
    return_code: int
    command: tuple[str, ...]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="외부 index membership source package를 검증/반영한다.",
    )
    parser.add_argument(
        "--manifest",
        default="data/instrument_master/source/index_membership_source_manifest.json",
        help="source package manifest 경로",
    )
    parser.add_argument(
        "--seed-csv",
        default="data/instrument_master/source/index_membership_seed.csv",
        help="정규화 seed CSV 출력/입력 경로",
    )
    parser.add_argument(
        "--catalog",
        default="logs/kis_index_category_catalog.json",
        help="KIS 카탈로그 dump 경로",
    )
    parser.add_argument(
        "--source-tag",
        default="index_membership_seed_csv",
        help="membership import source_tag",
    )
    parser.add_argument(
        "--replace-listed-symbols",
        action="store_true",
        help="seed CSV에 나온 symbol은 authoritative overwrite로 import한다.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="최종 membership import를 실제 커밋한다. 미지정 시 검증 전용이다.",
    )
    parser.add_argument(
        "--skip-catalog-validation",
        action="store_true",
        help="catalog alias 검증 단계를 생략한다.",
    )
    parser.add_argument(
        "--allow-placeholder",
        action="store_true",
        help="placeholder instrument 해상도도 허용한다.",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="실행 결과 출력 형식",
    )
    return parser.parse_args()


def _build_steps(args: argparse.Namespace) -> list[PipelineStep]:
    python_bin = sys.executable or "python3"
    steps: list[PipelineStep] = [
        PipelineStep(
            name="build_seed_csv",
            command=(
                python_bin,
                "scripts/build_index_membership_seed_from_source_package.py",
                "--manifest",
                args.manifest,
                "--output",
                args.seed_csv,
                "--output-format",
                "json",
            ),
        ),
    ]
    if not args.skip_catalog_validation:
        steps.append(
            PipelineStep(
                name="validate_catalog_alias",
                command=(
                    python_bin,
                    "scripts/validate_kis_index_membership_catalog.py",
                    "--catalog",
                    args.catalog,
                    "--seed-csv",
                    args.seed_csv,
                    "--fail-on-missing",
                    "--output",
                    "json",
                ),
            )
        )
    resolution_command = [
        python_bin,
        "scripts/validate_index_membership_seed_resolution.py",
        "--csv",
        args.seed_csv,
        "--fail-on-unresolved",
        "--output",
        "json",
    ]
    if not args.allow_placeholder:
        resolution_command.append("--fail-on-placeholder")
    steps.append(
        PipelineStep(
            name="validate_resolution",
            command=tuple(resolution_command),
        )
    )
    import_command = [
        python_bin,
        "scripts/import_instrument_index_membership_seed.py",
        "--csv",
        args.seed_csv,
        "--source-tag",
        args.source_tag,
        "--output",
        "json",
    ]
    if args.replace_listed_symbols:
        import_command.append("--replace-listed-symbols")
    if args.apply:
        import_command.append("--apply")
    steps.append(
        PipelineStep(
            name="import_memberships",
            command=tuple(import_command),
        )
    )
    return steps


def _run_step(step: PipelineStep) -> PipelineResult:
    completed = subprocess.run(step.command, check=False)
    return PipelineResult(
        step_name=step.name,
        return_code=completed.returncode,
        command=step.command,
    )


def _print_result(output: str, *, apply: bool, results: list[PipelineResult]) -> None:
    payload = {
        "apply": apply,
        "results": [
            {
                **asdict(item),
                "command": list(item.command),
            }
            for item in results
        ],
    }
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False))
        return
    print("=== Index Membership Source Package Pipeline ===")
    print(f"apply: {apply}")
    for item in results:
        print(
            f"{item.step_name}: return_code={item.return_code} "
            f"command={' '.join(item.command)}"
        )


def main() -> int:
    args = _parse_args()
    results: list[PipelineResult] = []
    for step in _build_steps(args):
        result = _run_step(step)
        results.append(result)
        if result.return_code != 0:
            _print_result(args.output, apply=args.apply, results=results)
            return result.return_code
    _print_result(args.output, apply=args.apply, results=results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
