"""``KISRestClient.get_fills()`` — 정규화 + 누적 관측 반환 검증.

이 메서드는 이제 **누적** 체결수량을 정규화해 돌려준다(증분이 아니다) —
설계 문서 14번 3.3절. 실제 fill/증분 append 여부 판단은 이 계층이 아니라
``order_sync_service._sync_fills()``의 몫이다(``test_kis_fill_incremental_
resolver.py`` 참고). 여기서는 브로커 계층의 정규화/필터링 책임만 검증한다.

``KISRestClient``는 ``@dataclass(slots=True, frozen=True)``이므로 인스턴스
속성을 직접 재할당할 수 없다 — ``test_rest_client_submit.py``와 동일하게
``patch.object(KISRestClient, "_request", ...)``로 클래스 메서드를 패치한다.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.domain.enums import OrderSide


@pytest.fixture
def client() -> KISRestClient:
    return KISRestClient(
        api_key="test-api-key",
        api_secret="test-api-secret",
        account_number="12345678",
        account_product_code="01",
        env="paper",
        budget_manager=None,
        dev_token_cache_enabled=False,
    )


def _paper_output_item(**overrides: str) -> dict[str, str]:
    item = {
        "odno": "0000008019",
        "pdno": "007070",
        "ord_qty": "70",
        "sll_buy_dvsn_cd": "01",
        "tot_ccld_qty": "70",
        "avg_prvs": "26650",
        "ord_tmd": "091551",
        "cncl_yn": "N",
    }
    item.update(overrides)
    return item


async def test_get_fills_returns_cumulative_quantity_from_paper_style_response(
    client: KISRestClient,
) -> None:
    with patch.object(
        KISRestClient, "_request",
        AsyncMock(return_value={"output": [_paper_output_item()]}),
    ):
        fills = await client.get_fills("test-account", "0000008019")

    assert len(fills) == 1
    fill = fills[0]
    assert fill.broker_order_id == "0000008019"
    assert fill.symbol == "007070"
    assert fill.side == OrderSide.SELL
    assert fill.fill_quantity == Decimal("70")
    assert fill.fill_price == Decimal("26650")


async def test_get_fills_filters_non_matching_broker_order_id(
    client: KISRestClient,
) -> None:
    with patch.object(
        KISRestClient, "_request",
        AsyncMock(return_value={"output": [_paper_output_item(odno="0000099999")]}),
    ):
        fills = await client.get_fills("test-account", "0000008019")

    assert fills == []


async def test_get_fills_skips_cancel_flagged_row(client: KISRestClient) -> None:
    with patch.object(
        KISRestClient, "_request",
        AsyncMock(return_value={"output": [_paper_output_item(cncl_yn="Y")]}),
    ):
        fills = await client.get_fills("test-account", "0000008019")

    assert fills == []


async def test_get_fills_skips_revision_flagged_row(client: KISRestClient) -> None:
    with patch.object(
        KISRestClient, "_request",
        AsyncMock(return_value={"output": [_paper_output_item(rvse_yn="Y")]}),
    ):
        fills = await client.get_fills("test-account", "0000008019")

    assert fills == []


async def test_get_fills_skips_unparseable_row_missing_odno(
    client: KISRestClient,
) -> None:
    item = _paper_output_item()
    del item["odno"]
    with patch.object(
        KISRestClient, "_request", AsyncMock(return_value={"output": [item]}),
    ):
        fills = await client.get_fills("test-account", "0000008019")

    assert fills == []


async def test_get_fills_handles_uppercase_legacy_field_names(
    client: KISRestClient,
) -> None:
    """live에서 가정하는 기존 대문자 필드명(CCLD_QTY/CCLD_UNPR)도 지원한다."""
    item = {
        "ODNO": "0000008019",
        "PDNO": "007070",
        "SLL_BUY_DVSN_CD": "01",
        "CCLD_QTY": "70",
        "CCLD_UNPR": "26650",
    }
    with patch.object(
        KISRestClient, "_request", AsyncMock(return_value={"output": [item]}),
    ):
        fills = await client.get_fills("test-account", "0000008019")

    assert len(fills) == 1
    assert fills[0].fill_quantity == Decimal("70")
    assert fills[0].fill_price == Decimal("26650")
