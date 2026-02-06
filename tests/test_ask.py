import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.decision import decision_coordinator
from app.main import app


@pytest.mark.asyncio
async def test_ask_endpoint_receives_answer():
    question = "Should we proceed?"
    options = ["Yes", "No"]
    transport = ASGITransport(app=app)
    with patch("app.main.get_cached_user_id", return_value=123), patch(
        "app.main.send_bot_message",
        new_callable=AsyncMock,
    ) as mock_send:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            ask_task = asyncio.create_task(
                client.post("/v1/ask", json={"question": question, "options": options})
            )
            await asyncio.sleep(0)
            resolved = await decision_coordinator.resolve("Yes")
            assert resolved is True
            response = await ask_task
            assert response.status_code == 200
            assert response.json()["answer"] == "Yes"
        mock_send.assert_awaited_once()
        sent_prompt = mock_send.call_args[0][1]
        assert "Summary:" in sent_prompt
        assert "Timeout:" in sent_prompt
        assert "1) Command" in sent_prompt
        assert "2) Stop" in sent_prompt


@pytest.mark.asyncio
async def test_ask_endpoint_uses_configured_chat_id():
    question = "Share update?"
    options = ["Yes", "No"]
    transport = ASGITransport(app=app)
    with patch("app.main.get_cached_user_id", return_value=123), patch(
        "app.main.send_bot_message", new_callable=AsyncMock
    ) as mock_send:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            ask_task = asyncio.create_task(
                client.post("/v1/ask", json={"question": question, "options": options})
            )
            await asyncio.sleep(0)
            resolved = await decision_coordinator.resolve("Yes")
            assert resolved is True
            response = await ask_task
            assert response.status_code == 200
            assert response.json()["answer"] == "Yes"
        mock_send.assert_awaited_once()
        args, _ = mock_send.call_args
        assert args[0] == 123


@pytest.mark.asyncio
async def test_ask_endpoint_allows_free_text():
    transport = ASGITransport(app=app)
    with patch("app.main.get_cached_user_id", return_value=123), patch(
        "app.main.send_bot_message",
        new_callable=AsyncMock,
    ) as mock_send:
        mock_send.return_value = True
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            ask_task = asyncio.create_task(
                client.post("/v1/ask", json={"question": "Share a note", "options": []})
            )
            await asyncio.sleep(0)
            resolved = await decision_coordinator.resolve("free text")
            assert resolved is True
            response = await ask_task
            assert response.status_code == 200
            assert response.json()["answer"] == "free text"
        mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_ask_endpoint_async_flow():
    transport = ASGITransport(app=app)
    with patch("app.main.get_cached_user_id", return_value=123), patch(
        "app.main.send_bot_message",
        new_callable=AsyncMock,
    ) as mock_send:
        mock_send.return_value = True
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/ask",
                json={"question": "Ping", "options": [], "mode": "async"},
            )
            assert response.status_code == 200
            request_id = response.json()["request_id"]
            resolved = await decision_coordinator.resolve("pong")
            assert resolved is True
            result = await client.get(f"/v1/ask/result/{request_id}")
            assert result.status_code == 200
            assert result.json()["answer"] == "pong"
        mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_ask_endpoint_cancels_pending_async_requests():
    transport = ASGITransport(app=app)
    with patch("app.main.get_cached_user_id", return_value=123), patch(
        "app.main.send_bot_message",
        new_callable=AsyncMock,
    ) as mock_send:
        mock_send.return_value = True
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first_response = await client.post(
                "/v1/ask",
                json={"question": "First", "options": [], "mode": "async"},
            )
            first_id = first_response.json()["request_id"]
            second_response = await client.post(
                "/v1/ask",
                json={"question": "Second", "options": [], "mode": "async"},
            )
            second_id = second_response.json()["request_id"]
            assert first_id != second_id
            first_result = await client.get(f"/v1/ask/result/{first_id}")
            assert first_result.status_code == 404
            resolved = await decision_coordinator.resolve("ok")
            assert resolved is True
            second_result = await client.get(f"/v1/ask/result/{second_id}")
            assert second_result.status_code == 200
            assert second_result.json()["answer"] == "ok"
        assert mock_send.await_count == 2
        await decision_coordinator.cancel_pending()


@pytest.mark.asyncio
async def test_ask_endpoint_timeouts_when_no_answer():
    question = "Timeout check?"
    options = ["Do", "Don't"]
    transport = ASGITransport(app=app)
    with patch("app.main.send_bot_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        with patch("app.main.get_cached_user_id", return_value=123):
            async with AsyncClient(transport=transport, base_url="http://test", timeout=5.0) as client:
                response = await client.post(
                    "/v1/ask",
                    json={"question": question, "options": options, "timeout": 0.05},
                )
                assert response.status_code == 408
                assert response.json()["detail"] == "timeout waiting for human response"
