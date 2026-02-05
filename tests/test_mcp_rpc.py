import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.decision import decision_coordinator
from app.main import app


@pytest.mark.asyncio
async def test_mcp_tools_list():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {"plan", "log", "ask"}.issubset(names)


@patch("app.main.send_bot_message", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_mcp_tool_call_plan(mock_send):
    transport = ASGITransport(app=app)
    mock_send.return_value = True
    with patch("app.main.get_cached_user_id", return_value=123):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
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
            )
    assert response.status_code == 200
    payload = response.json()["result"]["output"]
    assert "mission_id" in payload


@patch("app.main.send_bot_message", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_mcp_tool_call_log(mock_send):
    transport = ASGITransport(app=app)
    mock_send.return_value = True
    with patch("app.main.get_cached_user_id", return_value=123):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
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
            )
    assert response.status_code == 200
    payload = response.json()["result"]["output"]
    assert payload["status"] == "logged"


@patch("app.main.send_bot_message", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_mcp_tool_call_ask(mock_send):
    transport = ASGITransport(app=app)
    mock_send.return_value = True
    with patch("app.main.get_cached_user_id", return_value=123):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
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
                )
            )
            await asyncio.sleep(0)
            resolved = await decision_coordinator.resolve("Yes")
            assert resolved is True
            response = await task
    assert response.status_code == 200
    payload = response.json()["result"]["output"]
    assert payload["answer"] == "Yes"
