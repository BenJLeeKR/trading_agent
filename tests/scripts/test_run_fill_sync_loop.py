"""``scripts/run_fill_sync_loop.py`` 진입 경로 최소 검증.

검증 범위는 DB, broker, network에 닿지 않는 entry 계약으로 한정한다.

1. ``_parse_args()`` — CLI 인자 기본값과 명시 지정값
2. ``main()`` — ``--once`` / ``--count`` / 기본값 세 분기가 ``_run_loop``를
   각각 올바른 인자로 정확히 1회 호출하는지

``_run_loop``는 ``AppSettings`` 생성과 브로커 호출 직전 경계이므로 여기서
차단한다. 실제 fill sync 처리 로직은 ``tests/services/`` 쪽 테스트가 담당하며
이 파일에서 다루지 않는다.
"""

from __future__ import annotations

import scripts.run_fill_sync_loop as module
from scripts.run_fill_sync_loop import _parse_args


def _install_run_loop_recorder(monkeypatch) -> list[dict[str, object]]:
    """``_run_loop`` 호출 인자를 기록하고 외부 접근을 차단한다."""
    calls: list[dict[str, object]] = []

    async def fake_run_loop(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(module, "_run_loop", fake_run_loop)
    # 실제 시그널 핸들러를 테스트 프로세스에 설치하지 않는다.
    monkeypatch.setattr(module, "_install_signal_handlers", lambda: None)
    return calls


def test_parse_args_defaults() -> None:
    args = _parse_args([])
    assert args.once is False
    assert args.count == 0
    assert args.after_hours is False


def test_parse_args_explicit_values() -> None:
    args = _parse_args(["--once", "--count", "5", "--after-hours"])
    assert args.once is True
    assert args.count == 5
    assert args.after_hours is True


def test_main_once_runs_single_cycle(monkeypatch) -> None:
    """``--once``는 max_cycles=1로 정확히 1회 루프를 호출해야 한다."""
    calls = _install_run_loop_recorder(monkeypatch)

    exit_code = module.main(["--once"])

    assert exit_code == 0
    assert calls == [{"max_cycles": 1, "after_hours": False}]


def test_main_count_runs_bounded_cycles(monkeypatch) -> None:
    """``--count N``은 max_cycles=N으로 전달되고 after-hours 플래그도 함께 간다."""
    calls = _install_run_loop_recorder(monkeypatch)

    exit_code = module.main(["--count", "3", "--after-hours"])

    assert exit_code == 0
    assert calls == [{"max_cycles": 3, "after_hours": True}]


def test_main_without_bound_runs_infinite_loop(monkeypatch) -> None:
    """인자가 없으면 max_cycles를 넘기지 않아 무한 루프 기본값이 쓰인다."""
    calls = _install_run_loop_recorder(monkeypatch)

    exit_code = module.main([])

    assert exit_code == 0
    assert calls == [{"after_hours": False}]
