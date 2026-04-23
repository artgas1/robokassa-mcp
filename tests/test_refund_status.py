"""Tests for refund_status: Refund/GetState round-trip and error handling."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from robokassa import (
    RefundNotFoundError,
    RefundState,
    RobokassaClient,
    RobokassaResponseError,
    parse_refund_status_response,
    refund_status,
)

REQUEST_ID = "cf15fd52-d2d1-4fc4-b9c0-25310e3bdded"


def test_parse_success_finished() -> None:
    result = parse_refund_status_response(
        {"requestId": REQUEST_ID, "amount": 1.0, "label": "finished"},
        REQUEST_ID,
    )
    assert result.request_id == REQUEST_ID
    assert result.amount == Decimal("1.0")
    assert result.state is RefundState.FINISHED
    assert result.is_finished is True
    assert result.is_terminal is True


def test_parse_success_processing() -> None:
    result = parse_refund_status_response(
        {"requestId": REQUEST_ID, "amount": 10.5, "label": "processing"},
        REQUEST_ID,
    )
    assert result.state is RefundState.PROCESSING
    assert result.is_finished is False
    assert result.is_terminal is False


def test_parse_success_canceled() -> None:
    result = parse_refund_status_response(
        {"requestId": REQUEST_ID, "amount": 0, "label": "canceled"},
        REQUEST_ID,
    )
    assert result.state is RefundState.CANCELED
    assert result.is_terminal is True


def test_parse_high_precision_amount() -> None:
    result = parse_refund_status_response(
        {"requestId": REQUEST_ID, "amount": "1.234567", "label": "finished"},
        REQUEST_ID,
    )
    assert result.amount == Decimal("1.234567")


def test_parse_not_found_raises_refund_not_found_error() -> None:
    with pytest.raises(RefundNotFoundError, match=REQUEST_ID):
        parse_refund_status_response(
            {"message": "Id is invalid or request id does not exist"},
            REQUEST_ID,
        )


def test_parse_unknown_state_raises_response_error() -> None:
    with pytest.raises(RobokassaResponseError, match="Unknown refund state"):
        parse_refund_status_response(
            {"requestId": REQUEST_ID, "amount": 1.0, "label": "mystery"},
            REQUEST_ID,
        )


def test_parse_unknown_shape_raises_response_error() -> None:
    with pytest.raises(RobokassaResponseError, match="Unexpected"):
        parse_refund_status_response({"garbage": True}, REQUEST_ID)


def test_parse_unparseable_amount_raises_response_error() -> None:
    with pytest.raises(RobokassaResponseError, match="Unparseable"):
        parse_refund_status_response(
            {"requestId": REQUEST_ID, "amount": "not-a-number", "label": "finished"},
            REQUEST_ID,
        )


@pytest.mark.asyncio
async def test_refund_status_passes_request_id_as_query_param() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"requestId": REQUEST_ID, "amount": 1.0, "label": "finished"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await refund_status(REQUEST_ID, http_client=client)

    assert captured["id"] == REQUEST_ID
    assert result.state is RefundState.FINISHED


@pytest.mark.asyncio
async def test_refund_status_uses_refund_endpoint_path() -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json={"requestId": REQUEST_ID, "amount": 1.0, "label": "finished"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await refund_status(REQUEST_ID, http_client=client)

    assert any("/Refund/GetState" in u for u in urls)


@pytest.mark.asyncio
async def test_refund_status_raises_not_found_on_invalid_id() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "Id is invalid or request id does not exist"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RefundNotFoundError, match=REQUEST_ID):
            await refund_status(REQUEST_ID, http_client=client)


@pytest.mark.asyncio
async def test_client_refund_status_delegates() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"requestId": REQUEST_ID, "amount": 5.0, "label": "finished"})

    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        client = RobokassaClient("demo", http_client=transport_client)
        result = await client.refund_status(REQUEST_ID)
        assert result.amount == Decimal("5.0")
    finally:
        await transport_client.aclose()
