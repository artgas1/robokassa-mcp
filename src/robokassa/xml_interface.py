"""Robokassa XML web-service interface (OpStateExt and friends).

Base URL: `https://auth.robokassa.ru/Merchant/WebService/Service.asmx/<method>`.

Responses are XML in the `http://merchant.roboxchange.com/WebService/`
namespace. All responses contain a top-level `<Result><Code>N</Code></Result>`
which signals whether the request itself was valid — see `OpStateResultCode`.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Final
from xml.etree import ElementTree as ET

import httpx

from robokassa.signatures import SignatureAlgorithm, op_state_signature
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
