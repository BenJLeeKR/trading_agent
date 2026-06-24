from __future__ import annotations

from scripts.run_index_membership_source_package_pipeline import _build_steps, _parse_args


def test_parse_args_defaults() -> None:
    args = _parse_args([])
    assert args.manifest == "data/instrument_master/source/index_membership_source_manifest.json"
    assert args.seed_csv == "data/instrument_master/source/index_membership_seed.csv"
    assert args.catalog == "logs/kis_index_category_catalog.json"
    assert args.apply is False
    assert args.skip_catalog_validation is False
    assert args.allow_placeholder is False


def test_build_steps_includes_all_validation_steps_by_default() -> None:
    args = _parse_args([])
    steps = _build_steps(args)
    assert [step.name for step in steps] == [
        "build_seed_csv",
        "validate_catalog_alias",
        "validate_resolution",
        "import_memberships",
    ]
    assert "--fail-on-missing" in steps[1].command
    assert "--fail-on-unresolved" in steps[2].command
    assert "--fail-on-placeholder" in steps[2].command
    assert "--apply" not in steps[3].command


def test_build_steps_respects_runtime_options() -> None:
    args = _parse_args(
        [
            "--apply",
            "--replace-listed-symbols",
            "--skip-catalog-validation",
            "--allow-placeholder",
        ]
    )
    steps = _build_steps(args)
    assert [step.name for step in steps] == [
        "build_seed_csv",
        "validate_resolution",
        "import_memberships",
    ]
    assert "--fail-on-placeholder" not in steps[1].command
    assert "--replace-listed-symbols" in steps[2].command
    assert "--apply" in steps[2].command
