"""Tests for webhook signature verification helpers."""

from __future__ import annotations

import hashlib

import pytest

from robokassa import (
    build_ok_response,
    compute_result_signature,
    compute_success_signature,
    verify_result_signature,
    verify_success_signature,
)


def test_result_signature_matches_manual_md5() -> None:
    expected = hashlib.md5(b"100.00:42:password2").hexdigest()
    assert compute_result_signature(out_sum="100.00", inv_id=42, password2="password2") == expected


def test_success_signature_matches_manual_md5() -> None:
    expected = hashlib.md5(b"100.00:42:password1").hexdigest()
    assert compute_success_signature(out_sum="100.00", inv_id=42, password1="password1") == expected


def test_result_signature_includes_shp_params_alphabetical() -> None:
    """Shp_ params must be appended in alphabetical (case-insensitive) order."""
    sig = compute_result_signature(
        out_sum="100.00",
        inv_id=42,
        password2="p2",
        shp_params={"Shp_b": "second", "Shp_a": "first"},
    )
    expected = hashlib.md5(b"100.00:42:p2:Shp_a=first:Shp_b=second").hexdigest()
    assert sig == expected


def test_signature_respects_algorithm() -> None:
    sig_md5 = compute_result_signature(out_sum="10", inv_id=1, password2="p2", algorithm="md5")
    sig_sha256 = compute_result_signature(out_sum="10", inv_id=1, password2="p2", algorithm="sha256")
    assert len(sig_md5) == 32
    assert len(sig_sha256) == 64
    assert sig_md5 != sig_sha256


def test_verify_result_accepts_correct_signature() -> None:
    sig = compute_result_signature(out_sum="100.00", inv_id=42, password2="p2")
    assert verify_result_signature({"OutSum": "100.00", "InvId": "42", "SignatureValue": sig}, "p2") is True


def test_verify_result_rejects_wrong_signature() -> None:
    assert verify_result_signature({"OutSum": "100.00", "InvId": "42", "SignatureValue": "a" * 32}, "p2") is False


def test_verify_result_is_case_insensitive_on_hex_digest() -> None:
    sig = compute_result_signature(out_sum="100", inv_id=1, password2="p2")
    assert verify_result_signature({"OutSum": "100", "InvId": "1", "SignatureValue": sig.upper()}, "p2") is True


def test_verify_result_accepts_lowercase_keys() -> None:
    """Some frameworks normalize to lower-case — we should still work."""
    sig = compute_result_signature(out_sum="100", inv_id=1, password2="p2")
    assert verify_result_signature({"outsum": "100", "invid": "1", "signaturevalue": sig}, "p2") is True


def test_verify_result_handles_shp_params() -> None:
    sig = compute_result_signature(
        out_sum="100",
        inv_id=1,
        password2="p2",
        shp_params={"Shp_order": "42"},
    )
    assert (
        verify_result_signature(
            {
                "OutSum": "100",
                "InvId": "1",
                "SignatureValue": sig,
                "Shp_order": "42",
            },
            "p2",
        )
        is True
    )


def test_verify_result_fails_when_shp_param_tampered() -> None:
    sig = compute_result_signature(out_sum="100", inv_id=1, password2="p2", shp_params={"Shp_order": "42"})
    assert (
        verify_result_signature(
            {
                "OutSum": "100",
                "InvId": "1",
                "SignatureValue": sig,
                "Shp_order": "99",  # attacker changed the order id
            },
            "p2",
        )
        is False
    )


def test_verify_result_raises_on_missing_params() -> None:
    with pytest.raises(ValueError, match="Missing"):
        verify_result_signature({"OutSum": "100"}, "p2")


def test_verify_success_signature_uses_password1() -> None:
    sig = compute_success_signature(out_sum="100", inv_id=1, password1="p1")
    assert verify_success_signature({"OutSum": "100", "InvId": "1", "SignatureValue": sig}, "p1") is True
    # Password mismatch should fail.
    assert verify_success_signature({"OutSum": "100", "InvId": "1", "SignatureValue": sig}, "wrong-password") is False


def test_build_ok_response() -> None:
    assert build_ok_response(42) == "OK42"
    assert build_ok_response("42") == "OK42"
