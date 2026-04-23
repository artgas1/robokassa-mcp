"""Signature computation for Robokassa API.

Robokassa signs requests with a hex digest of `:`-joined parts, using one of
four algorithms selectable in the merchant cabinet: MD5, SHA-256, SHA-384,
SHA-512. MD5 is the historical default; newer deployments use SHA-256.

Case of the hex output does not matter — Robokassa accepts both.
"""

from __future__ import annotations

import hashlib
from typing import Literal

SignatureAlgorithm = Literal["md5", "sha256", "sha384", "sha512"]

_HASHLIB_BY_NAME: dict[SignatureAlgorithm, str] = {
    "md5": "md5",
    "sha256": "sha256",
    "sha384": "sha384",
    "sha512": "sha512",
}


def compute_signature(
    *parts: str | int,
    algorithm: SignatureAlgorithm = "md5",
) -> str:
    """Join parts with `:` and return the lowercase hex digest.

    Example:
        >>> compute_signature("demo", 1932809606, "secret_p2")
        '9e2bf657364d25acf5905b4ac4f50e39'
    """
    source = ":".join(str(p) for p in parts)
    hasher = hashlib.new(_HASHLIB_BY_NAME[algorithm])
    hasher.update(source.encode("utf-8"))
    return hasher.hexdigest()


def op_state_signature(
    merchant_login: str,
    inv_id: int,
    password2: str,
    *,
    algorithm: SignatureAlgorithm = "md5",
) -> str:
    """Signature for the OpStateExt XML interface.

    Formula: `<algorithm>(MerchantLogin:InvoiceID:Password#2)`.
    """
    return compute_signature(merchant_login, inv_id, password2, algorithm=algorithm)
