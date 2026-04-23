"""Robokassa XML web-service interface (OpStateExt and friends).

Base URL: `https://auth.robokassa.ru/Merchant/WebService/Service.asmx/<method>`.

Responses are XML in the `http://merchant.roboxchange.com/WebService/`
namespace. All responses contain a top-level `<Result><Code>N</Code></Result>`
which signals whether the request itself was valid — see `OpStateResultCode`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Final
from xml.etree import ElementTree as ET

import httpx

from robokassa.signatures import SignatureAlgorithm, compute_signature, op_state_signature
from robokassa.types import (
    OperationInfo,
    OperationState,
    OperationStateCode,
    OpStateResultCode,
    RobokassaApiError,
    RobokassaResponseError,
)

XML_NAMESPACE: Final[str] = "http://merchant.roboxchange.com/WebService/"
DEFAULT_BASE_URL: Final[str] = "https://auth.robokassa.ru/Merchant/WebService/Service.asmx"

# Robokassa emits ISO 8601 with up to 7 fractional-second digits, which exceeds
# Python's `datetime.fromisoformat` cap of 6. Truncate the fraction in-place.
_TOO_PRECISE_FRACTION = re.compile(r"(\.\d{6})\d+")


def _parse_robokassa_datetime(text: str | None) -> datetime | None:
    """Parse Robokassa's ISO-8601 datetime strings, tolerating 7-digit fractions."""
    if not text:
        return None
    normalized = _TOO_PRECISE_FRACTION.sub(r"\1", text.strip())
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RobokassaResponseError(f"Unparseable datetime: {text!r}") from exc


def _parse_optional_decimal(text: str | None) -> Decimal | None:
    if text is None or not text.strip():
        return None
    try:
        return Decimal(text.strip().replace(",", "."))
    except InvalidOperation as exc:
        raise RobokassaResponseError(f"Unparseable decimal: {text!r}") from exc


def _find_text(element: ET.Element | None, tag: str) -> str | None:
    """Find an element by local tag name, ignoring the default namespace."""
    if element is None:
        return None
    child = element.find(f"{{{XML_NAMESPACE}}}{tag}")
    if child is None:
        # Tolerate responses that happen to come without the default namespace.
        child = element.find(tag)
    return child.text if child is not None else None


def _find_child(element: ET.Element | None, tag: str) -> ET.Element | None:
    if element is None:
        return None
    child = element.find(f"{{{XML_NAMESPACE}}}{tag}")
    if child is None:
        child = element.find(tag)
    return child


def parse_op_state_response(xml_text: str) -> OperationState:
    """Parse the XML returned by OpStateExt into an `OperationState`.

    Raises:
        RobokassaResponseError: if the XML is malformed or missing required parts.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RobokassaResponseError(f"Invalid XML: {exc}") from exc

    result_elem = _find_child(root, "Result")
    code_text = _find_text(result_elem, "Code")
    if code_text is None:
        raise RobokassaResponseError("Missing <Result><Code> in response")
    try:
        result_code = OpStateResultCode(int(code_text))
    except ValueError as exc:
        raise RobokassaResponseError(f"Unknown Result.Code: {code_text!r}") from exc

    # On error, Robokassa omits State/Info/UserField — return early.
    if result_code is not OpStateResultCode.SUCCESS:
        return OperationState(result_code=result_code)

    state_elem = _find_child(root, "State")
    state_code_text = _find_text(state_elem, "Code")
    state_code: OperationStateCode | None = None
    if state_code_text is not None and state_code_text.strip():
        try:
            state_code = OperationStateCode(int(state_code_text))
        except ValueError as exc:
            raise RobokassaResponseError(f"Unknown State.Code: {state_code_text!r}") from exc

    info_elem = _find_child(root, "Info")
    payment_method_elem = _find_child(info_elem, "PaymentMethod")
    info = OperationInfo(
        inc_curr_label=_find_text(info_elem, "IncCurrLabel"),
        inc_sum=_parse_optional_decimal(_find_text(info_elem, "IncSum")),
        inc_account=_find_text(info_elem, "IncAccount"),
        payment_method_code=_find_text(payment_method_elem, "Code"),
        out_curr_label=_find_text(info_elem, "OutCurrLabel"),
        out_sum=_parse_optional_decimal(_find_text(info_elem, "OutSum")),
        op_key=_find_text(info_elem, "OpKey"),
        bank_card_rrn=_find_text(info_elem, "BankCardRRN"),
    )

    user_fields: dict[str, str] = {}
    user_field_root = _find_child(root, "UserField")
    if user_field_root is not None:
        field_tag = f"{{{XML_NAMESPACE}}}Field"
        for field in user_field_root.findall(field_tag) or user_field_root.findall("Field"):
            name = _find_text(field, "Name")
            value = _find_text(field, "Value") or ""
            if name:
                user_fields[name] = value

    return OperationState(
        result_code=result_code,
        state_code=state_code,
        request_date=_parse_robokassa_datetime(_find_text(state_elem, "RequestDate")),
        state_date=_parse_robokassa_datetime(_find_text(state_elem, "StateDate")),
        info=info,
        user_fields=user_fields,
    )


async def check_payment(
    merchant_login: str,
    inv_id: int,
    password2: str,
    *,
    algorithm: SignatureAlgorithm = "md5",
    base_url: str = DEFAULT_BASE_URL,
    http_client: httpx.AsyncClient | None = None,
    raise_on_api_error: bool = True,
) -> OperationState:
    """Query Robokassa's OpStateExt endpoint for the current state of a payment.

    Args:
        merchant_login: Shop identifier (ROBOKASSA_LOGIN).
        inv_id: Invoice number the shop assigned to the operation.
        password2: Shop's Password #2 (technical settings).
        algorithm: Signature algorithm configured in the cabinet.
        base_url: Override for the XML service root (useful for testing).
        http_client: Optional pre-configured `httpx.AsyncClient` to reuse.
        raise_on_api_error: If True (default), raise `RobokassaApiError` when
            Robokassa returns a non-zero `Result.Code`. Set False to inspect
            the error on the returned `OperationState`.

    Returns:
        `OperationState` parsed from the XML response.

    Raises:
        RobokassaApiError: On non-zero Result.Code when `raise_on_api_error=True`.
        RobokassaResponseError: On malformed XML / missing fields.
        httpx.HTTPError: On network / HTTP-level failures.
    """
    signature = op_state_signature(merchant_login, inv_id, password2, algorithm=algorithm)
    params: dict[str, str | int] = {
        "MerchantLogin": merchant_login,
        "InvoiceID": inv_id,
        "Signature": signature,
    }
    url = f"{base_url}/OpStateExt"

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        state = parse_op_state_response(response.text)
    finally:
        if owns_client:
            await client.aclose()

    if raise_on_api_error and state.result_code is not OpStateResultCode.SUCCESS:
        raise RobokassaApiError(state.result_code)
    return state


# ---------------------------------------------------------------------------
# GetCurrencies — list payment method groups available to the shop
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Currency:
    """One payment method / currency offered by Robokassa.

    `label` is the value to pass as `IncCurrLabel` at checkout.
    """

    label: str
    alias: str | None = None
    name: str | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CurrencyGroup:
    """A logical grouping of currencies (e.g. `BankCard`, `SBP`, `YandexPay`)."""

    code: str
    description: str | None = None
    currencies: list[Currency] = field(default_factory=lambda: [])


@dataclass(frozen=True, slots=True)
class CurrenciesListing:
    """Result of GetCurrencies."""

    result_code: OpStateResultCode
    groups: list[CurrencyGroup] = field(default_factory=lambda: [])


def _parse_currency(element: ET.Element) -> Currency:
    return Currency(
        label=element.attrib.get("Label", ""),
        alias=element.attrib.get("Alias") or None,
        name=element.attrib.get("Name") or None,
        min_value=_parse_optional_decimal(element.attrib.get("MinValue")),
        max_value=_parse_optional_decimal(element.attrib.get("MaxValue")),
    )


def _iter_children(element: ET.Element | None, tag: str) -> list[ET.Element]:
    if element is None:
        return []
    namespaced = element.findall(f"{{{XML_NAMESPACE}}}{tag}")
    return namespaced or element.findall(tag)


def parse_currencies_response(xml_text: str) -> CurrenciesListing:
    """Parse the XML returned by GetCurrencies."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RobokassaResponseError(f"Invalid XML: {exc}") from exc

    result_elem = _find_child(root, "Result")
    code_text = _find_text(result_elem, "Code")
    if code_text is None:
        raise RobokassaResponseError("Missing <Result><Code> in GetCurrencies response")
    try:
        result_code = OpStateResultCode(int(code_text))
    except ValueError as exc:
        raise RobokassaResponseError(f"Unknown Result.Code: {code_text!r}") from exc

    if result_code is not OpStateResultCode.SUCCESS:
        return CurrenciesListing(result_code=result_code)

    groups: list[CurrencyGroup] = []
    groups_root = _find_child(root, "Groups")
    for group_elem in _iter_children(groups_root, "Group"):
        items_elem = _find_child(group_elem, "Items")
        currencies = [_parse_currency(c) for c in _iter_children(items_elem, "Currency")]
        groups.append(
            CurrencyGroup(
                code=group_elem.attrib.get("Code", ""),
                description=group_elem.attrib.get("Description") or None,
                currencies=currencies,
            )
        )

    return CurrenciesListing(result_code=result_code, groups=groups)


async def list_currencies(
    merchant_login: str,
    *,
    language: str = "ru",
    base_url: str = DEFAULT_BASE_URL,
    http_client: httpx.AsyncClient | None = None,
    raise_on_api_error: bool = True,
) -> CurrenciesListing:
    """Query Robokassa's GetCurrencies endpoint for available payment methods.

    GetCurrencies is a public method — no password / signature required.

    Args:
        merchant_login: Shop identifier.
        language: UI language for Name fields (`ru` or `en`).
        base_url / http_client: Same as `check_payment`.
        raise_on_api_error: If True, raise on non-zero Result.Code.
    """
    url = f"{base_url}/GetCurrencies"
    params = {"MerchantLogin": merchant_login, "Language": language}

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        listing = parse_currencies_response(response.text)
    finally:
        if owns_client:
            await client.aclose()

    if raise_on_api_error and listing.result_code is not OpStateResultCode.SUCCESS:
        raise RobokassaApiError(listing.result_code)
    return listing


# ---------------------------------------------------------------------------
# CalcOutSumm — calculate how much the shop receives for a given payment
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalcOutSumResult:
    """Result of CalcOutSumm — the amount credited to the shop."""

    result_code: OpStateResultCode
    out_sum: Decimal | None = None


def parse_calc_out_sum_response(xml_text: str) -> CalcOutSumResult:
    """Parse the XML returned by CalcOutSumm."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RobokassaResponseError(f"Invalid XML: {exc}") from exc

    result_elem = _find_child(root, "Result")
    code_text = _find_text(result_elem, "Code")
    if code_text is None:
        raise RobokassaResponseError("Missing <Result><Code> in CalcOutSumm response")
    try:
        result_code = OpStateResultCode(int(code_text))
    except ValueError as exc:
        raise RobokassaResponseError(f"Unknown Result.Code: {code_text!r}") from exc

    if result_code is not OpStateResultCode.SUCCESS:
        return CalcOutSumResult(result_code=result_code)

    out_sum = _parse_optional_decimal(_find_text(root, "OutSum"))
    return CalcOutSumResult(result_code=result_code, out_sum=out_sum)


async def calc_out_sum(
    merchant_login: str,
    inc_sum: Decimal | float | int | str,
    password1: str,
    *,
    inc_curr_label: str | None = None,
    algorithm: SignatureAlgorithm = "md5",
    base_url: str = DEFAULT_BASE_URL,
    http_client: httpx.AsyncClient | None = None,
    raise_on_api_error: bool = True,
) -> CalcOutSumResult:
    """Calculate how much will be credited to the shop for a given IncSum.

    Useful for showing the payment-method fee in the checkout UI.

    Signature: `<algorithm>(MerchantLogin:IncSum:Password#1)`.
    """
    inc_sum_str = str(inc_sum)
    signature = compute_signature(merchant_login, inc_sum_str, password1, algorithm=algorithm)
    params: dict[str, str | int] = {
        "MerchantLogin": merchant_login,
        "IncSum": inc_sum_str,
        "Signature": signature,
    }
    if inc_curr_label is not None:
        params["IncCurrLabel"] = inc_curr_label
    url = f"{base_url}/CalcOutSumm"

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        result = parse_calc_out_sum_response(response.text)
    finally:
        if owns_client:
            await client.aclose()

    if raise_on_api_error and result.result_code is not OpStateResultCode.SUCCESS:
        raise RobokassaApiError(result.result_code)
    return result
