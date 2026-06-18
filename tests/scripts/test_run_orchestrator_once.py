from __future__ import annotations

from pathlib import Path

from scripts import run_orchestrator_once as module


def test_load_local_dotenv_loads_project_env(monkeypatch) -> None:
    calls: list[Path] = []

    def _fake_load_dotenv(path: Path) -> bool:
        calls.append(path)
        return True

    monkeypatch.setattr(module, "load_dotenv", _fake_load_dotenv)
    monkeypatch.setattr(Path, "exists", lambda self: True)

    loaded = module._load_local_dotenv()

    assert loaded is True
    assert len(calls) == 1
    assert calls[0].name == ".env"


def test_load_local_dotenv_skips_when_file_missing(monkeypatch) -> None:
    def _unexpected_load(path: Path) -> bool:
        raise AssertionError("load_dotenv should not be called when .env is missing")

    monkeypatch.setattr(module, "load_dotenv", _unexpected_load)
    monkeypatch.setattr(Path, "exists", lambda self: False)

    loaded = module._load_local_dotenv()

    assert loaded is False


def test_load_local_dotenv_skips_when_python_dotenv_missing(monkeypatch) -> None:
    monkeypatch.setattr(module, "load_dotenv", None)

    loaded = module._load_local_dotenv()

    assert loaded is False
