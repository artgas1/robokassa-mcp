"""FastMCP server exposing Robokassa tools to AI agents."""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from robokassa import check_payment as _check_payment
from robokassa.signatures import SignatureAlgorithm

mcp: FastMCP = FastMCP("robokassa")


def _resolve_credential(explicit: str | None, env_var: str) -> str:
    value = explicit if explicit is not None else os.environ.get(env_var)
    if not value:
        raise ValueError(f"{env_var} is required — pass it explicitly or set the environment variable")
    return value


@mcp.tool()
async def check_payment(
    inv_id: int,
    merchant_login: str | None = None,
    password2: str | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Check the current state of a Robokassa payment by invoice ID.

    Uses the `OpStateExt` XML interface. Returns a structured summary including
    the state code (5/10/20/50/60/80/100), the OpKey (required later for
    initiating a refund via Refund/Create), sums, payment method, and any
    user-defined `Shp_*` parameters attached at checkout.

    State codes:
        5   — инициализирована, не оплачена
        10  — отменена (таймаут / пользователь)
        20  — HOLD (предавторизация)
        50  — средства получены, зачисление магазину
        60  — отказ в зачислении, средства возвращены покупателю
              (это НЕ пользовательский refund — для него используйте refund_status)
        80  — приостановлена (security check)
        100 — оплачена ✅

    Credentials may be passed explicitly or via ROBOKASSA_LOGIN / ROBOKASSA_PASSWORD2
    environment variables.

    Note:
        OpStateExt does NOT reflect post-payment refunds initiated through the
        Robokassa cabinet or Refund/Create. For that, store the requestId from
        Refund/Create and poll Refund/GetState.
    """
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    pw2 = _resolve_credential(password2, "ROBOKASSA_PASSWORD2")

    state = await _check_payment(login, inv_id, pw2, algorithm=algorithm)

    return {
        "result_code": int(state.result_code),
        "state_code": int(state.state_code) if state.state_code is not None else None,
        "is_paid": state.is_paid,
        "is_terminal": state.is_terminal,
        "request_date": state.request_date.isoformat() if state.request_date else None,
        "state_date": state.state_date.isoformat() if state.state_date else None,
        "info": {
            "op_key": state.info.op_key,
            "inc_curr_label": state.info.inc_curr_label,
            "inc_sum": str(state.info.inc_sum) if state.info.inc_sum is not None else None,
            "inc_account": state.info.inc_account,
            "payment_method_code": state.info.payment_method_code,
            "out_curr_label": state.info.out_curr_label,
            "out_sum": str(state.info.out_sum) if state.info.out_sum is not None else None,
            "bank_card_rrn": state.info.bank_card_rrn,
        },
        "user_fields": state.user_fields,
    }


def main() -> None:
    """Entry point for the `robokassa-mcp` console script."""
    mcp.run()


if __name__ == "__main__":
    main()
