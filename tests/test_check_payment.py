"""Integration-shaped tests for check_payment using a mocked HTTP transport."""

from __future__ import annotations

import httpx
import pytest

from robokassa import RobokassaApiError, RobokassaClient, check_payment
from robokassa.types import OperationStateCode, OpStateResultCode

SUCCESS_XML = """<?xml version="1.0" encoding="utf-8"?>
<OperationStateResponse xmlns="http://merchant.roboxchange.com/WebService/">
  <Result><Code>0</Code></Result>
  <State>
    <Code>100</Code>
    <RequestDate>2026-04-24T00:30:00.123456+03:00</RequestDate>
    <StateDate>2026-04-24T00:29:00+03:00</StateDate>
  </State>
  <Info>
    <IncCurrLabel>BankCard</IncCurrLabel>
    <IncSum>100.00</IncSum>
    <OpKey>OP-KEY-TEST-1</OpKey>
  </Info>
</OperationStateResponse>
"""

ERROR_XML = """<?xml version="1.0" encoding="utf-8"?>
<OperationStateResponse xmlns="http://merchant.roboxchange.com/WebService/">
  <Result><Code>3</Code></Result>
</OperationStateResponse>
"""


def _make_client(xml: str, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=xml)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_check_payment_returns_parsed_state() -> None:
    async with _make_client(SUCCESS_XML) as client:
        state = await check_payment(
            "demo",
            inv_id=1932809606,
            password2="p2",
            http_client=client,
        )
    assert state.result_code is OpStateResultCode.SUCCESS
    assert state.state_code is OperationStateCode.COMPLETED
    assert state.info.op_key == "OP-KEY-TEST-1"
    assert state.is_paid is True


@pytest.mark.asyncio
async def test_check_payment_sends_signature_in_query_string() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, text=SUCCESS_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await check_payment("demo", 42, "p2", http_client=client)

    assert captured["MerchantLogin"] == "demo"
    assert captured["InvoiceID"] == "42"
    # MD5 of "demo:42:p2" = deterministic, just confirm it's 32 hex chars.
    assert len(captured["Signature"]) == 32


@pytest.mark.asyncio
async def test_check_payment_raises_on_api_error_by_default() -> None:
    async with _make_client(ERROR_XML) as client:
        with pytest.raises(RobokassaApiError) as exc_info:
            await check_payment("demo", 1, "p2", http_client=client)
    assert exc_info.value.code is OpStateResultCode.OPERATION_NOT_FOUND


@pytest.mark.asyncio
async def test_check_payment_suppresses_api_error_when_requested() -> None:
    async with _make_client(ERROR_XML) as client:
        state = await check_payment("demo", 1, "p2", http_client=client, raise_on_api_error=False)
    assert state.result_code is OpStateResultCode.OPERATION_NOT_FOUND
    assert state.state_code is None


@pytest.mark.asyncio
async def test_client_check_payment_requires_password2() -> None:
    async with RobokassaClient("demo") as client:
        with pytest.raises(ValueError, match="password2"):
            await client.check_payment(1)


@pytest.mark.asyncio
async def test_client_check_payment_delegates() -> None:
    transport_client = _make_client(SUCCESS_XML)
    try:
        client = RobokassaClient("demo", password2="p2", http_client=transport_client)
        state = await client.check_payment(1)
        assert state.is_paid is True
    finally:
        await transport_client.aclose()
