from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.mcp import mcp_connector


@pytest.mark.asyncio
async def test_mcp_connect_success():
    mcp_connector.disconnect()
    response = httpx.Response(200, request=httpx.Request("GET", "http://mcp.test/health"))
    with patch("app.mcp.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            result = await client.post("/v1/mcp/connect", json={"server_url": "http://mcp.test"})
            assert result.status_code == 200
            payload = result.json()
            assert payload["status"] == "connected"
            assert payload["server_url"] == "http://mcp.test"
            assert payload["health_url"] == "http://mcp.test/health"

            status = await client.get("/v1/mcp/status")
            assert status.status_code == 200
            assert status.json()["status"] == "connected"
    mcp_connector.disconnect()


@pytest.mark.asyncio
async def test_mcp_connect_failure():
    mcp_connector.disconnect()
    request = httpx.Request("GET", "http://mcp.test/health")
    error = httpx.RequestError("boom", request=request)
    with patch("app.mcp.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=error)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            result = await client.post("/v1/mcp/connect", json={"server_url": "http://mcp.test"})
            assert result.status_code == 200
            payload = result.json()
            assert payload["status"] == "failed"
            assert payload["last_error"]
    mcp_connector.disconnect()


@pytest.mark.asyncio
async def test_mcp_disconnect_clears_state():
    mcp_connector.disconnect()
    response = httpx.Response(200, request=httpx.Request("GET", "http://mcp.test/health"))
    with patch("app.mcp.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/v1/mcp/connect", json={"server_url": "http://mcp.test"})
            disconnect = await client.post("/v1/mcp/disconnect")
            assert disconnect.status_code == 200
            status = await client.get("/v1/mcp/status")
            assert status.status_code == 200
            assert status.json() == {"status": "disconnected"}
    mcp_connector.disconnect()


@pytest.mark.asyncio
async def test_mcp_connect_requires_url():
    mcp_connector.disconnect()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        result = await client.post("/v1/mcp/connect", json={})
        assert result.status_code == 400
