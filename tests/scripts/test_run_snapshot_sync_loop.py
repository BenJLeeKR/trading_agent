"""``scripts/run_snapshot_sync_loop.py`` 진입 경로 최소 검증.

검증 범위는 DB, broker, network에 닿지 않는 entry 계약으로 한정한다.

1. ``_parse_args()`` — CLI 인자 기본값과 명시 지정값
2. ``main()`` — 파싱 결과를 ``_run_loop``에 정확히 1회 전달하는지
   (broker와 max_cycles는 위치 인자, 나머지 3개는 키워드 인자)

``_run_loop``는 DB 풀 생성과 브로커 호출 직전 경계이므로 여기서 차단한다.
실제 snapshot sync 처리 로직은 ``tests/services/`` 쪽 테스트가 담당하며
이 파일에서 다루지 않는다.
"""

from __future__ import annotations

import scripts.run_snapshot_sync_loop as module
from scripts.run_snapshot_sync_loop import _parse_args


def _install_run_loop_recorder(monkeypatch) -> list[tuple[tuple, dict]]:
    """``_run_loop`` 호출 인자를 기록하고 외부 접근을 차단한다."""
    calls: list[tuple[tuple, dict]] = []

    async def fake_run_loop(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(module, "_run_loop", fake_run_loop)
    # 실제 시그널 핸들러를 테스트 프로세스에 설치하지 않는다.
    monkeypatch.setattr(module, "_install_signal_handlers", lambda: None)
    return calls


def test_parse_args_defaults() -> None:
    args = _parse_args([])
    assert args.broker == "koreainvestment"
    assert args.max_cycles == 0
    assert args.after_hours is False
    assert args.fetch_positions is True
    assert args.allow_after_hours_positions is False


def test_parse_args_explicit_values() -> None:
    args = _parse_args(
        [
            "--broker",
            "paper",
            "--max-cycles",
            "2",
            "--after-hours",
            "--fetch-positions",
            "false",
            "--allow-after-hours-positions",
        ]
    )
    assert args.broker == "paper"
    assert args.max_cycles == 2
    assert args.after_hours is True
    assert args.fetch_positions is False
    assert args.allow_after_hours_positions is True


def test_main_passes_defaults_to_run_loop(monkeypatch) -> None:
    """인자가 없으면 기본 broker와 무한 루프(max_cycles=0)로 1회 호출해야 한다."""
    calls = _install_run_loop_recorder(monkeypatch)

    exit_code = module.main([])

    assert exit_code == 0
    assert len(calls) == 1
    positional, keyword = calls[0]
    assert positional == ("koreainvestment", 0)
    assert keyword == {
        "after_hours": False,
        "fetch_positions": True,
        "allow_after_hours_positions": False,
    }


def test_main_passes_parsed_arguments_to_run_loop(monkeypatch) -> None:
    """after-hours 조합 인자가 그대로 루프에 전달되는지 확인한다."""
    calls = _install_run_loop_recorder(monkeypatch)

    exit_code = module.main(
        [
            "--max-cycles",
            "2",
            "--after-hours",
            "--fetch-positions",
            "false",
            "--allow-after-hours-positions",
        ]
    )

    assert exit_code == 0
    assert len(calls) == 1
    positional, keyword = calls[0]
    assert positional == ("koreainvestment", 2)
    assert keyword == {
        "after_hours": True,
        "fetch_positions": False,
        "allow_after_hours_positions": True,
    }
