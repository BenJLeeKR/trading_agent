"""``scripts/publish_max_single_position_pct.py`` CLI 파싱/정책 테스트.

DB 접속이 필요한 ``_run()``의 실제 실행(dry-run/apply)은 다루지 않는다 —
여기서는 ``--environment`` 선택지가 실제 DB CHECK 제약(``paper``/``live``만
허용)과 일치하는지, ``argparse`` 레벨에서 ``real``을 거부하는지만 확인한다.
"""

from __future__ import annotations

import pytest

from scripts.publish_max_single_position_pct import parse_args


def _base_args(environment: str) -> list[str]:
    return [
        "--client-id", "00000000-0000-0000-0000-000000000001",
        "--environment", environment,
        "--max-single-position-pct", "15",
        "--activated-by", "test-operator",
    ]


class TestParseArgsEnvironmentChoices:
    def test_accepts_paper(self) -> None:
        args = parse_args(_base_args("paper"))
        assert args.environment == "paper"

    def test_accepts_live(self) -> None:
        args = parse_args(_base_args("live"))
        assert args.environment == "live"

    def test_rejects_real_at_parse_time(self) -> None:
        """``--environment real``은 ``argparse``의 ``choices``에서 바로

        걸러진다(``SystemExit`` — argparse 표준 동작) — DB까지 갈 필요 없이
        가장 이른 시점에서 막힌다.
        """
        with pytest.raises(SystemExit):
            parse_args(_base_args("real"))

    def test_rejects_unknown_environment_at_parse_time(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(_base_args("not-a-real-environment"))
