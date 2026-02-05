from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.telegram import build_info_text, parse_answer


@patch("app.telegram.send_bot_message", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_telegram_webhook_start(mock_send):
    payload = {
        "message": {
            "chat": {"id": 123},
            "from": {"username": "dev-telegram-username"},
            "text": "/start CODE",
        }
    }
    transport = ASGITransport(app=app)
    with patch("app.telegram.get_start_code", return_value="CODE"), patch(
        "app.telegram.remember_user_id"
    ) as mock_remember, patch(
        "app.telegram.get_cached_user_id",
        return_value=None,
    ), patch("app.telegram.asyncio.sleep", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/telegram/webhook", json=payload)
    assert response.json() == {"ok": True}
    mock_remember.assert_called_once_with(123)
    mock_send.assert_awaited_once_with(123, build_info_text())


@pytest.mark.asyncio
async def test_telegram_webhook_rejects_unauthorized_chat():
    payload = {
        "message": {
            "chat": {"id": 321},
            "from": {"username": "dev-telegram-username"},
            "text": "hello",
        }
    }
    transport = ASGITransport(app=app)
    with patch("app.telegram.get_cached_user_id", return_value=123), patch(
        "app.main.send_bot_message", new_callable=AsyncMock
    ) as mock_send:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/telegram/webhook", json=payload)
    assert response.json()["error"] == "unauthorized"
    mock_send.assert_awaited()


@pytest.mark.asyncio
async def test_telegram_webhook_requires_start_code():
    payload = {"message": {"chat": {"id": 123}, "text": "/start"}}
    transport = ASGITransport(app=app)
    with patch("app.telegram.asyncio.sleep", new_callable=AsyncMock), patch(
        "app.telegram.send_bot_message",
        new_callable=AsyncMock,
    ) as mock_send:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/telegram/webhook", json=payload)
    assert response.json() == {"ok": True}
    mock_send.assert_awaited()


def test_parse_answer_accepts_short_command():
    options = ["Yes", "No"]
    assert parse_answer("Yes", options) == "Yes"
