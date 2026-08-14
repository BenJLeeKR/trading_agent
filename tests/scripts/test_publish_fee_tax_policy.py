"""``scripts/publish_fee_tax_policy.py`` CLI 파싱 테스트.

DB 접속이 필요한 ``_run()``의 실제 실행(dry-run/apply)은 다루지 않는다 —
여기서는 ``--environment`` 선택지, ``--fee-tax-json`` 파싱(인라인/JSON
오류)만 argparse/유틸리티 레벨에서 확인한다.
"""

from __future__ import annotations

import pytest

from scripts.publish_fee_tax_policy import _load_fee_tax_input, parse_args

_VALID_FEE_TAX_JSON = (
    '{"enabled": true, "supported_asset_classes": ["kr_stock"], '
    '"supported_market_segments": ["KOSPI", "KOSDAQ"], '
    '"buy_commission_rate_pct": "0.0140527", '
    '"sell_commission_rate_pct": "0.0140527", '
    '"sell_tax_rate_pct": "0.20", "sell_agri_tax_rate_pct": "0.00", '
    '"rounding_mode": "round_half_up", "rounding_unit": "1", '
    '"reason": "test"}'
)


def _base_args(environment: str) -> list[str]:
    return [
        "--client-id", "00000000-0000-0000-0000-000000000001",
        "--environment", environment,
        "--fee-tax-json", _VALID_FEE_TAX_JSON,
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
        with pytest.raises(SystemExit):
            parse_args(_base_args("real"))

    def test_rejects_unknown_environment_at_parse_time(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(_base_args("not-a-real-environment"))


class TestLoadFeeTaxInput:
    def test_parses_inline_json(self) -> None:
        parsed = _load_fee_tax_input(_VALID_FEE_TAX_JSON)
        assert parsed["enabled"] is True
        assert parsed["supported_asset_classes"] == ["kr_stock"]

    def test_rejects_malformed_json(self) -> None:
        with pytest.raises(ValueError):
            _load_fee_tax_input("{not valid json")
