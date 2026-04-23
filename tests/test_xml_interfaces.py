"""Tests for additional XML interface endpoints (GetCurrencies, CalcOutSumm)."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from robokassa import (
    RobokassaApiError,
    calc_out_sum,
    list_currencies,
    parse_calc_out_sum_response,
    parse_currencies_response,
)

NS = 'xmlns="http://merchant.roboxchange.com/WebService/"'


CURRENCIES_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<CurrenciesList {NS}>
  <Result><Code>0</Code></Result>
  <Groups>
    <Group Code="BankCard" Description="Банковской картой">
      <Items>
        <Currency Label="BankCardPSR" Alias="BankCard" Name="Банковская карта"/>
        <Currency Label="SberPayPSR" Alias="SberPay" Name="SberPay" MinValue="1" MaxValue="20000000"/>
      </Items>
    </Group>
    <Group Code="SBP" Description="СБП">
      <Items>
        <Currency Label="SBPPSR" Alias="SBP" Name="Банковская карта" MaxValue="1000000"/>
      </Items>
    </Group>
  </Groups>
</CurrenciesList>
"""


CURRENCIES_ERROR_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<CurrenciesList {NS}>
  <Result><Code>2</Code></Result>
</CurrenciesList>
"""


CALCOUTSUM_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<CalcSummsResponse {NS}>
  <Result><Code>0</Code></Result>
  <OutSum>96.50</OutSum>
</CalcSummsResponse>
"""


CALCOUTSUM_ERROR_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<CalcSummsResponse {NS}>
  <Result><Code>1</Code></Result>
</CalcSummsResponse>
"""


# ---- parsers ------------------------------------------------------------


def test_parse_currencies_full_tree() -> None:
    listing = parse_currencies_response(CURRENCIES_XML)
    assert listing.result_code.value == 0
    assert [g.code for g in listing.groups] == ["BankCard", "SBP"]

    bank_card = listing.groups[0]
    assert bank_card.description == "Банковской картой"
    assert [c.label for c in bank_card.currencies] == ["BankCardPSR", "SberPayPSR"]
    sberpay = bank_card.currencies[1]
    assert sberpay.alias == "SberPay"
    assert sberpay.min_value == Decimal("1")
    assert sberpay.max_value == Decimal("20000000")

    sbp = listing.groups[1].currencies[0]
    assert sbp.label == "SBPPSR"
    assert sbp.max_value == Decimal("1000000")
    assert sbp.min_value is None


def test_parse_currencies_error_result_omits_groups() -> None:
    listing = parse_currencies_response(CURRENCIES_ERROR_XML)
    assert listing.result_code.value == 2
    assert listing.groups == []


def test_parse_calc_out_sum_success() -> None:
    result = parse_calc_out_sum_response(CALCOUTSUM_XML)
    assert result.result_code.value == 0
    assert result.out_sum == Decimal("96.50")


def test_parse_calc_out_sum_error_omits_amount() -> None:
    result = parse_calc_out_sum_response(CALCOUTSUM_ERROR_XML)
    assert result.result_code.value == 1
    assert result.out_sum is None


# ---- HTTP round-trips ---------------------------------------------------


@pytest.mark.asyncio
async def test_list_currencies_sends_expected_params() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        assert "/GetCurrencies" in str(request.url)
        return httpx.Response(200, text=CURRENCIES_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        listing = await list_currencies("demo", language="en", http_client=client)

    assert captured == {"MerchantLogin": "demo", "Language": "en"}
    assert len(listing.groups) == 2


@pytest.mark.asyncio
async def test_list_currencies_raises_on_api_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CURRENCIES_ERROR_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RobokassaApiError):
            await list_currencies("demo", http_client=client)


@pytest.mark.asyncio
async def test_calc_out_sum_signs_with_password1_and_incsum() -> None:
    import hashlib

    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        assert "/CalcOutSumm" in str(request.url)
        return httpx.Response(200, text=CALCOUTSUM_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await calc_out_sum("demo", Decimal("100.00"), "p1", inc_curr_label="BankCard", http_client=client)

    assert captured["MerchantLogin"] == "demo"
    assert captured["IncSum"] == "100.00"
    assert captured["IncCurrLabel"] == "BankCard"
    expected_sig = hashlib.md5(b"demo:100.00:p1").hexdigest()
    assert captured["Signature"] == expected_sig
    assert result.out_sum == Decimal("96.50")


@pytest.mark.asyncio
async def test_calc_out_sum_raises_on_api_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CALCOUTSUM_ERROR_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RobokassaApiError):
            await calc_out_sum("demo", 100, "p1", http_client=client)
