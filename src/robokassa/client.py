"""High-level client that bundles credentials with Robokassa API calls.

Library users can either call module-level functions (`robokassa.check_payment`)
passing credentials each time, or construct a `RobokassaClient` once and call
instance methods.
"""

from __future__ import annotations

from typing import Self

import httpx

from robokassa.signatures import SignatureAlgorithm
from robokassa.types import OperationState
from robokassa.xml_interface import DEFAULT_BASE_URL, check_payment


class RobokassaClient:
    """Convenience wrapper holding credentials + HTTP client for Robokassa API calls.

    Passwords are optional — only those needed for the specific methods you
    call must be provided. For `check_payment` you need at least
    `merchant_login` and `password2`.
    """

    def __init__(
        self,
        merchant_login: str,
        *,
        password1: str | None = None,
        password2: str | None = None,
        password3: str | None = None,
        algorithm: SignatureAlgorithm = "md5",
        xml_base_url: str = DEFAULT_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.merchant_login = merchant_login
        self.password1 = password1
        self.password2 = password2
        self.password3 = password3
        self.algorithm: SignatureAlgorithm = algorithm
        self.xml_base_url = xml_base_url
        self._http_client = http_client
        self._owns_http_client = http_client is None

    async def __aenter__(self) -> Self:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
            self._owns_http_client = True
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _require(self, value: str | None, name: str) -> str:
        if value is None:
            raise ValueError(f"{name} is required for this operation but was not provided")
        return value

    async def check_payment(self, inv_id: int, *, raise_on_api_error: bool = True) -> OperationState:
        """Fetch the current state of a payment via OpStateExt.

        Requires `password2` on the client.
        """
        return await check_payment(
            self.merchant_login,
            inv_id,
            self._require(self.password2, "password2"),
            algorithm=self.algorithm,
            base_url=self.xml_base_url,
            http_client=self._http_client,
            raise_on_api_error=raise_on_api_error,
        )
