"""``scripts/run_reconciliation_worker.py`` 진입 경로 최소 검증.

검증 범위는 DB, broker, network에 닿지 않는 entry 계약으로 한정한다.

1. ``_parse_args()`` — CLI 인자 기본값과 명시 지정값
2. ``main()`` — 파싱 결과를 ``_run_loop``에 정확히 1회 전달하는지
3. ``main()`` — 잘못된 UUID를 받으면 루프 진입 없이 실패 코드를 돌려주는지

``_run_loop``는 DB 풀 생성 직전 경계이므로 여기서 차단한다. 실제 reconciliation
처리 로직은 ``tests/services/`` 쪽 테스트가 담당하며 이 파일에서 다루지 않는다.
"""

from __future__ import annotations

from uuid import uuid4

import scripts.run_reconciliation_worker as module
from scripts.run_reconciliation_worker import _parse_args


def test_parse_args_defaults() -> None:
    args = _parse_args([])
    assert args.once is False
    assert args.count == 0
    assert args.account_id is None
    assert args.run_id is None
    assert args.dry_run is False
    assert args.limit == module.DEFAULT_BATCH_LIMIT
    assert args.interval is None
    assert args.verbose is False


def test_parse_args_explicit_values() -> None:
    run_id = str(uuid4())
    args = _parse_args(
        [
            "--once",
            "--dry-run",
            "--run-id",
            run_id,
            "--limit",
            "3",
            "--interval",
            "45",
        ]
    )
    assert args.once is True
    assert args.dry_run is True
    assert args.run_id == run_id
    assert args.limit == 3
    assert args.interval == 45


def test_main_once_invokes_run_loop_with_parsed_arguments(monkeypatch) -> None:
    """``--once``는 max_cycles=1로 정확히 1회 루프를 호출해야 한다."""
    account_id = uuid4()
    calls: list[dict[str, object]] = []

    async def fake_run_loop(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(module, "_run_loop", fake_run_loop)
    # 실제 시그널 핸들러를 테스트 프로세스에 설치하지 않는다.
    monkeypatch.setattr(module, "_install_signal_handlers", lambda: None)
    monkeypatch.delenv(module.ENV_INTERVAL, raising=False)

    exit_code = module.main(
        [
            "--once",
            "--dry-run",
            "--account-id",
            str(account_id),
            "--limit",
            "5",
            "--interval",
            "45",
        ]
    )

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0] == {
        "account_id": account_id,
        "run_id": None,
        "limit": 5,
        "dry_run": True,
        "max_cycles": 1,
    }
    # --interval은 환경변수 경유로 _read_interval에 전달된다.
    assert module.os.environ[module.ENV_INTERVAL] == "45"


def test_main_rejects_invalid_account_id(monkeypatch) -> None:
    """UUID 파싱 실패는 루프 진입 없이 실패 코드로 끝나야 한다."""
    calls: list[dict[str, object]] = []

    async def fake_run_loop(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(module, "_run_loop", fake_run_loop)
    monkeypatch.setattr(module, "_install_signal_handlers", lambda: None)

    exit_code = module.main(["--account-id", "not-a-uuid"])

    assert exit_code == 1
    assert calls == []
