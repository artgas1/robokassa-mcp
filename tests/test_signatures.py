"""Test signature computation against Robokassa documentation examples."""

from __future__ import annotations

import hashlib

import pytest

from robokassa.signatures import compute_signature, op_state_signature


def test_md5_matches_manual_computation() -> None:
    """Our helper joins with ':' and MD5's — verify against manual hash."""
    expected = hashlib.md5(b"demo:5.12:5:securepass1").hexdigest()
    assert compute_signature("demo", "5.12", 5, "securepass1") == expected


def test_sha256_produces_64_hex_chars() -> None:
    sig = compute_signature("demo", 1, "secret", algorithm="sha256")
    assert len(sig) == 64
    assert all(c in "0123456789abcdef" for c in sig)


def test_sha512_produces_128_hex_chars() -> None:
    sig = compute_signature("demo", 1, "secret", algorithm="sha512")
    assert len(sig) == 128


def test_op_state_signature_shape() -> None:
    """OpStateExt signature = MD5(MerchantLogin:InvoiceID:Password2)."""
    expected = hashlib.md5(b"demo:1932809606:secret_p2").hexdigest()
    assert op_state_signature("demo", 1932809606, "secret_p2") == expected


def test_op_state_signature_int_is_stringified() -> None:
    """`inv_id` as int should produce the same result as its str form."""
    assert op_state_signature("demo", 42, "p2") == op_state_signature("demo", "42", "p2")  # type: ignore[arg-type]


@pytest.mark.parametrize("algorithm", ["md5", "sha256", "sha384", "sha512"])
def test_op_state_signature_honors_algorithm(algorithm: str) -> None:
    sig = op_state_signature("demo", 1, "p2", algorithm=algorithm)  # type: ignore[arg-type]
    expected_len = {"md5": 32, "sha256": 64, "sha384": 96, "sha512": 128}[algorithm]
    assert len(sig) == expected_len
