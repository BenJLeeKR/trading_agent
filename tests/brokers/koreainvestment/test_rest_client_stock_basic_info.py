from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient


@pytest.fixture
def live_client() -> KISRestClient:
    return KISRestClient(
        api_key="test-api-key",
        api_secret="test-api-secret",
        account_number="12345678",
        account_product_code="01",
        env="live",
        budget_manager=None,
        dev_token_cache_enabled=False,
    )


@pytest.fixture
def paper_client() -> KISRestClient:
    return KISRestClient(
        api_key="test-api-key",
        api_secret="test-api-secret",
        account_number="12345678",
        account_product_code="01",
        env="paper",
        budget_manager=None,
        dev_token_cache_enabled=False,
    )


class TestGetStockBasicInfo:
    @pytest.mark.asyncio
    async def test_returns_output_dict(self, live_client: KISRestClient) -> None:
        mock_response = {
            "output": {
                "pdno": "000660",
                "prdt_type_cd": "300",
                "tr_stop_yn": "N",
                "admn_item_yn": "N",
                "mket_id_cd": "STK",
                "scty_grp_id_cd": "ST",
            }
        }

        with patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request:
            row = await live_client.get_stock_basic_info("000660")

        assert row == mock_response["output"]
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["endpoint_key"] == "search_stock_info"
        assert call_kwargs["tr_id_key"] == "search_stock_info"
        assert call_kwargs["params"]["PDNO"] == "000660"
        assert call_kwargs["params"]["PRDT_TYPE_CD"] == "300"

    @pytest.mark.asyncio
    async def test_returns_empty_dict_in_paper_env(self, paper_client: KISRestClient) -> None:
        with patch.object(KISRestClient, "_request", AsyncMock()) as mock_request:
            row = await paper_client.get_stock_basic_info("000660")

        assert row == {}
        mock_request.assert_not_called()
