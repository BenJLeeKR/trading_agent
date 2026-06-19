from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent_trading.brokers.errors import BrokerError, BrokerErrorType
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.domain.enums import BrokerName


@pytest.fixture
def client() -> KISRestClient:
    return KISRestClient(
        api_key="test-api-key",
        api_secret="test-api-secret",
        account_number="12345678",
        account_product_code="01",
        env="live",
        budget_manager=None,
        dev_token_cache_enabled=False,
    )


class TestGetIndexCategoryQuotes:
    @pytest.mark.asyncio
    async def test_returns_output2_rows(self, client: KISRestClient) -> None:
        mock_response = {
            "output2": [
                {"bstp_cls_code": "2001", "hts_kor_isnm": "KOSPI200"},
                {"bstp_cls_code": "2007", "hts_kor_isnm": "KOSPI100"},
            ]
        }

        with patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request:
            rows = await client.get_index_category_quotes()

        assert rows == mock_response["output2"]
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["endpoint_key"] == "inquire_index_category_price"
        assert call_kwargs["tr_id_key"] == "inquire_index_category_price"
        assert call_kwargs["params"]["FID_COND_MRKT_DIV_CODE"] == "U"
        assert call_kwargs["params"]["FID_COND_SCR_DIV_CODE"] == "20214"
        assert call_kwargs["params"]["FID_MRKT_CLS_CODE"] == "K2"

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_broker_error(self, client: KISRestClient) -> None:
        async def _raise(*args, **kwargs):
            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.API_ERROR,
                retryable=False,
                raw_message="unavailable",
            )

        with patch.object(KISRestClient, "_request", _raise):
            rows = await client.get_index_category_quotes()

        assert rows == []
