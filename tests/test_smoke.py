"""Smoke tests: packages import and version matches."""

import robokassa
import robokassa_mcp


def test_robokassa_imports() -> None:
    assert robokassa.__version__ == "0.1.0"


def test_robokassa_mcp_imports() -> None:
    assert robokassa_mcp.__version__ == "0.1.0"


def test_fastmcp_server_constructs() -> None:
    from robokassa_mcp.server import mcp

    assert mcp.name == "robokassa"
