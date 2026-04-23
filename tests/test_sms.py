"""Tests for SMS sending."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from robokassa import SMS_URL, build_sms_signature, send_sms


def test_build_sms_signature_formula() -> None:
    """Formula: MD5(login:phone:message:password1)."""
    expected = hashlib.md5(b"demo:79991234567:hello:p1").hexdigest()
    assert build_sms_signature("demo", "79991234567", "hello", "p1") == expected


@pytest.mark.asyncio
async def test_send_sms_sends_expected_params() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(SMS_URL)
        captured.update(dict(request.url.params))
        return httpx.Response(200, text="OK")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_sms("demo", "79991234567", "hello", "p1", http_client=client)

    assert result.status_code == 200
    assert result.body == "OK"
    assert captured["login"] == "demo"
    assert captured["phone"] == "79991234567"
    assert captured["message"] == "hello"
    assert captured["signature"] == hashlib.md5(b"demo:79991234567:hello:p1").hexdigest()
