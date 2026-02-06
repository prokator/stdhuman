import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.decision import decision_coordinator
from app.main import app


def _parse_sse_payload(response_text: str) -> dict:
    data_lines = [line for line in response_text.splitlines() if line.startswith("data:")]
    assert data_lines
    raw = data_lines[-1][len("data:"):].strip()
    return json.loads(raw)


def _parse_mcp_response(response) -> dict:
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        return _parse_sse_payload(response.text)
    return response.json()


async def _mcp_initialize(client: AsyncClient) -> None:
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0.1.0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200
    payload = _parse_mcp_response(response)
    assert payload["result"]["protocolVersion"] == "2025-06-18"
    initialized = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert initialized.status_code == 202


async def _wait_for_pending() -> None:
    for _ in range(10):
        if decision_coordinator.has_pending():
            return
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_mcp_tools_list():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _mcp_initialize(client)
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payload = _parse_mcp_response(response)
    tools = payload["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {"plan", "log", "ask"}.issubset(names)


@pytest.mark.asyncio
async def test_mcp_allows_null_origin_and_legacy_protocol():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _mcp_initialize(client)
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "Accept": "application/json, text/event-stream",
                "Origin": "null",
                "Mcp-Protocol-Version": "2024-11-05",
            },
        )
    assert response.status_code == 200


@patch("app.main.send_bot_message", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_mcp_tool_call_plan(mock_send):
    transport = ASGITransport(app=app)
    mock_send.return_value = True
    with patch("app.main.get_cached_user_id", return_value=123):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _mcp_initialize(client)
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "plan",
                        "arguments": {"project": "Test Mission", "steps": ["step 1"]},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
    assert response.status_code == 200
    payload = _parse_mcp_response(response)["result"]
    assert "structuredContent" in payload


@patch("app.main.send_bot_message", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_mcp_tool_call_log(mock_send):
    transport = ASGITransport(app=app)
    mock_send.return_value = True
    with patch("app.main.get_cached_user_id", return_value=123):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _mcp_initialize(client)
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "log",
                        "arguments": {"level": "info", "message": "Update"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
    assert response.status_code == 200
    payload = _parse_mcp_response(response)["result"]["structuredContent"]
    assert payload["status"] == "logged"


@patch("app.main.send_bot_message", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_mcp_tool_call_ask(mock_send):
    transport = ASGITransport(app=app)
    mock_send.return_value = True
    with patch("app.main.get_cached_user_id", return_value=123):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _mcp_initialize(client)
            task = asyncio.create_task(
                client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {
                            "name": "ask",
                            "arguments": {"question": "Proceed?", "options": ["Yes", "No"]},
                        },
                    },
                    headers={"Accept": "application/json, text/event-stream"},
                )
            )
            await _wait_for_pending()
            resolved = await decision_coordinator.resolve("Yes")
            assert resolved is True
            response = await task
    assert response.status_code == 200
    payload = _parse_mcp_response(response)["result"]["structuredContent"]
    assert payload["answer"] == "Yes"


@pytest.mark.asyncio
async def test_mcp_notification_returns_202():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/ping",
                "params": {"hello": "world"},
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_mcp_get_stream_returns_sse():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _mcp_initialize(client)
        async with client.stream(
            "GET",
            "/mcp?once=1",
            headers={"Accept": "text/event-stream"},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            first_line = await asyncio.wait_for(response.aiter_lines().__anext__(), timeout=1)
            assert first_line.startswith(":")
