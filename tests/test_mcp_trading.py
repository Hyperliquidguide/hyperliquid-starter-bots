"""Offline tests for the opt-in MCP order tools. No network, no keys."""

import importlib

from hlmcp import trading


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("HL_MCP_TRADING", raising=False)
    assert not trading.enabled()
    monkeypatch.setenv("HL_MCP_TRADING", "on")
    assert trading.enabled()


def test_server_registers_order_tools_only_when_enabled(monkeypatch):
    import hlmcp.server as srv

    monkeypatch.delenv("HL_MCP_TRADING", raising=False)
    names = {t.name for t in importlib.reload(srv).mcp._tool_manager.list_tools()}
    assert "place_order" not in names and "market_specs" in names
    monkeypatch.setenv("HL_MCP_TRADING", "on")
    names = {t.name for t in importlib.reload(srv).mcp._tool_manager.list_tools()}
    assert {"prepare_order", "place_order", "cancel_orders", "trading_status"} <= names
    assert not any("withdraw" in n or "transfer" in n for n in names)


def test_status_parsing():
    ok = {"response": {"data": {"statuses": [{"resting": {"oid": 7}}]}}}
    filled = {"response": {"data": {"statuses": [{"filled": {"totalSz": "0.1", "avgPx": "100", "oid": 8}}]}}}
    bad = {"response": {"data": {"statuses": [{"error": "Order must have minimum value of $10."}]}}}
    assert trading._status(ok) == "resting (oid 7)"
    assert trading._status(filled).startswith("filled 0.1 @ 100")
    assert trading._status(bad).startswith("REJECTED")
    assert trading._status(None).startswith("unexpected")


def test_unknown_token_is_refused(monkeypatch):
    import hlmcp.server as srv
    import asyncio

    monkeypatch.setenv("HL_MCP_TRADING", "on")
    s = importlib.reload(srv)
    out = asyncio.run(s.mcp.call_tool("place_order", {"confirm_token": "nope"}))
    content = out[0] if isinstance(out, tuple) else out
    assert "Unknown or already used token" in content[0].text
