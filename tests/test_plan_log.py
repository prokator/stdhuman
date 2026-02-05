import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_plan_and_log_endpoints_work():
    transport = ASGITransport(app=app)
    with patch("app.main.send_bot_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        with patch("app.main.get_cached_user_id", return_value=123):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                plan_response = await client.post(
                    "/v1/plan",
                    json={"project": "Test Mission", "steps": ["step 1", "step 2"]},
                )
                assert plan_response.status_code == 202
                assert "mission_id" in plan_response.json()

                log_response = await client.post(
                    "/v1/log",
                    json={"level": "info", "message": "Working"},
                )
                assert log_response.status_code == 202
        assert mock_send.await_count == 2


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("app.main.send_bot_message", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_log_sends_message(mock_send):
    transport = ASGITransport(app=app)
    mock_send.return_value = True
    with patch("app.main.get_cached_user_id", return_value=123):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/log",
                json={"level": "info", "message": "Notify"},
            )
    assert response.status_code == 202
    mock_send.assert_awaited_once_with(123, "Notify")


@patch("app.main.send_bot_message", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_plan_includes_steps(mock_send):
    transport = ASGITransport(app=app)
    mock_send.return_value = True
    with patch("app.main.get_cached_user_id", return_value=123):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/plan",
                json={"project": "Test Mission", "steps": ["step 1", "step 2"]},
            )
    assert response.status_code == 202
    sent_message = mock_send.call_args[0][1]
    assert "Steps:" in sent_message
    assert "1) step 1" in sent_message
    assert "2) step 2" in sent_message


@patch("app.main.send_bot_message", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_log_step_index_appends_step_completion(mock_send):
    transport = ASGITransport(app=app)
    mock_send.return_value = True
    with patch("app.main.get_cached_user_id", return_value=123):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/v1/plan",
                json={"project": "Test Mission", "steps": ["step 1"]},
            )
            response = await client.post(
                "/v1/log",
                json={"level": "info", "message": "Done", "step_index": 1},
            )
    assert response.status_code == 202
    sent_message = mock_send.call_args_list[-1][0][1]
    assert "Step 1/1 complete: step 1" in sent_message
