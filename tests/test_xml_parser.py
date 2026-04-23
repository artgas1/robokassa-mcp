"""Test XML parser for OpStateExt responses."""

from __future__ import annotations

from decimal import Decimal

import pytest

from robokassa.types import (
    OperationStateCode,
    OpStateResultCode,
    RobokassaResponseError,
)
from robokassa.xml_interface import parse_op_state_response

NAMESPACE = 'xmlns="http://merchant.roboxchange.com/WebService/"'


def _successful_response(
    state_code: int = 100,
    op_key: str = "ABCDEF12-0000-0000-0000-000000000001-OVO",
    shp_field: tuple[str, str] | None = ("Shp_order_id", "42"),
) -> str:
    """Build a realistic OpStateExt response XML."""
    user_field = ""
    if shp_field is not None:
        user_field = f"""
  <UserField>
    <Field>
      <Name>{shp_field[0]}</Name>
      <Value>{shp_field[1]}</Value>
    </Field>
  </UserField>"""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<OperationStateResponse {NAMESPACE}>
  <Result>
    <Code>0</Code>
  </Result>
  <State>
    <Code>{state_code}</Code>
    <RequestDate>2026-04-24T00:30:00.1234567+03:00</RequestDate>
    <StateDate>2026-04-24T00:29:00.0000000+03:00</StateDate>
  </State>
  <Info>
    <IncCurrLabel>BankCard</IncCurrLabel>
    <IncSum>100.00</IncSum>
    <IncAccount>411111******1111</IncAccount>
    <PaymentMethod>
      <Code>BankCard</Code>
    </PaymentMethod>
    <OutCurrLabel>RUB</OutCurrLabel>
    <OutSum>97.00</OutSum>
    <OpKey>{op_key}</OpKey>
    <BankCardRRN>123456789012</BankCardRRN>
  </Info>{user_field}
</OperationStateResponse>
"""


def test_parses_happy_path_100() -> None:
    state = parse_op_state_response(_successful_response())

    assert state.result_code is OpStateResultCode.SUCCESS
    assert state.state_code is OperationStateCode.COMPLETED
    assert state.is_paid is True
    assert state.is_terminal is True

    assert state.info.op_key == "ABCDEF12-0000-0000-0000-000000000001-OVO"
    assert state.info.inc_curr_label == "BankCard"
    assert state.info.inc_sum == Decimal("100.00")
    assert state.info.out_sum == Decimal("97.00")
    assert state.info.payment_method_code == "BankCard"
    assert state.info.bank_card_rrn == "123456789012"

    assert state.user_fields == {"Shp_order_id": "42"}

    # 7-digit fractional seconds must be tolerated (truncated to 6).
    assert state.request_date is not None
    assert state.request_date.microsecond == 123456


def test_parses_non_terminal_state() -> None:
    state = parse_op_state_response(_successful_response(state_code=50, shp_field=None))
    assert state.state_code is OperationStateCode.RECEIVED
    assert state.is_paid is False
    assert state.is_terminal is False
    assert state.user_fields == {}


def test_parses_error_result_code_without_state_or_info() -> None:
    """On Result.Code != 0, Robokassa omits State/Info — we handle that."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<OperationStateResponse {NAMESPACE}>
  <Result>
    <Code>3</Code>
    <Description>Operation not found</Description>
  </Result>
</OperationStateResponse>
"""
    state = parse_op_state_response(xml)
    assert state.result_code is OpStateResultCode.OPERATION_NOT_FOUND
    assert state.state_code is None
    assert state.is_paid is False
    assert state.info.op_key is None


def test_rejects_malformed_xml() -> None:
    with pytest.raises(RobokassaResponseError):
        parse_op_state_response("not xml at all <<<")


def test_rejects_missing_result_code() -> None:
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<OperationStateResponse {NAMESPACE}>
  <Result></Result>
</OperationStateResponse>
"""
    with pytest.raises(RobokassaResponseError, match="Missing"):
        parse_op_state_response(xml)


def test_rejects_unknown_result_code() -> None:
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<OperationStateResponse {NAMESPACE}>
  <Result><Code>99999</Code></Result>
</OperationStateResponse>
"""
    with pytest.raises(RobokassaResponseError, match=r"Result\.Code"):
        parse_op_state_response(xml)


def test_parses_multiple_user_fields() -> None:
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<OperationStateResponse {NAMESPACE}>
  <Result><Code>0</Code></Result>
  <State><Code>100</Code></State>
  <Info><OpKey>K</OpKey></Info>
  <UserField>
    <Field><Name>Shp_a</Name><Value>1</Value></Field>
    <Field><Name>Shp_b</Name><Value>hello</Value></Field>
  </UserField>
</OperationStateResponse>
"""
    state = parse_op_state_response(xml)
    assert state.user_fields == {"Shp_a": "1", "Shp_b": "hello"}
