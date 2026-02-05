from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from httpx import AsyncClient

from app.start_code import get_start_code
from app.user_store import get_cached_user_id, remember_user_id
from app.config import settings
from app.decision import decision_coordinator

logger = logging.getLogger("stdhuman.telegram")
AUTH_MISMATCH_MESSAGE = "Authorization mismatch. Contact the operator."
AUTH_FAILED_MESSAGE = "Authorization failed. Contact the operator."
AUTH_CODE_REQUIRED = "Authorization code required. Send /start <code>."
AUTH_USERNAME_REQUIRED = "Authorization requires a Telegram username."
START_DELAY_SECONDS = 2.5

def build_info_text() -> str:
    return (
        "StdHuman Agent is a local helper that keeps the /v1/plan, /v1/log, and /v1/ask endpoints ready.\n"
        f"Base URL: http://localhost:{settings.port}\n"
        "Plan missions, report progress, and request human input when ambiguity pops up."
    )


def build_question_text(question: str, options: list[str]) -> str:
    lines = [f"Summary: {question}"]
    if options:
        lines.append("Options:")
        for idx, option in enumerate(options, start=1):
            lines.append(f"{idx}) {option}")
    lines.append("Reply with plain text.")
    return "\n".join(lines)


def parse_answer(text: str, options: list[str]) -> str | None:
    cleaned = text.strip()
    lowered = cleaned.lower()
    if lowered.startswith("/answer"):
        cleaned = cleaned[len("/answer"):].strip()
    elif lowered == "/a" or lowered.startswith("/a "):
        cleaned = cleaned[len("/a"):].strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        index = int(cleaned) - 1
        if 0 <= index < len(options):
            return options[index]
    return cleaned


def is_numeric(value: int | str) -> bool:
    try:
        return str(value).isdigit()
    except Exception:
        return False


def _is_allowed_chat(chat_id: int | str, allowed: int | None) -> bool:
    if allowed is None:
        return False
    if is_numeric(chat_id):
        return int(chat_id) == int(allowed)
    return False


def _normalize_username(username: str | None) -> str | None:
    if not username:
        return None
    return username.lstrip("@").lower()


def _configured_username() -> str:
    return settings.dev_telegram_username.lstrip("@").lower()


def is_authorized_username(username: str | None) -> bool:
    normalized = _normalize_username(username)
    if not normalized:
        return False
    return normalized == _configured_username()


async def resolve_authorized_user_id(chat_id: int | str, username: str | None) -> bool:
    stored = get_cached_user_id()
    if stored is None:
        logger.warning("Authorization denied: missing stored user id")
        return False
    if not is_authorized_username(username):
        if username:
            logger.warning("Authorization denied: username mismatch")
        else:
            logger.warning("Authorization denied: missing username")
        return False
    if not _is_allowed_chat(chat_id, stored):
        logger.warning("Authorization denied: chat id mismatch")
        return False
    return True


def _extract_start_code(text: str) -> str | None:
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


async def handle_start(chat_id: int | str, username: str | None, text: str) -> None:
    start_code = _extract_start_code(text)
    if not start_code:
        logger.warning("Start denied: missing code")
        await asyncio.sleep(START_DELAY_SECONDS)
        await send_bot_message(chat_id, AUTH_CODE_REQUIRED)
        return

    expected = get_start_code()
    if start_code != expected:
        logger.warning("Start denied: invalid code")
        await asyncio.sleep(START_DELAY_SECONDS)
        await send_bot_message(chat_id, AUTH_FAILED_MESSAGE)
        return

    if not is_authorized_username(username):
        logger.warning("Start denied: username mismatch")
        await asyncio.sleep(START_DELAY_SECONDS)
        await send_bot_message(chat_id, AUTH_USERNAME_REQUIRED)
        return

    stored = get_cached_user_id()
    if stored is not None and not _is_allowed_chat(chat_id, stored):
        logger.warning("Start denied: stored user id desync")
        await asyncio.sleep(START_DELAY_SECONDS)
        await send_bot_message(chat_id, AUTH_MISMATCH_MESSAGE)
        return

    logger.info("Start authorized")
    remember_user_id(int(chat_id))
    await asyncio.sleep(START_DELAY_SECONDS)
    await send_bot_message(chat_id, build_info_text())


async def send_bot_message(chat_id: int | str, text: str) -> bool:
    if not is_numeric(chat_id):
        raise ValueError("chat id must be numeric")
    send_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    resolved_chat_id = int(chat_id)
    async with AsyncClient(timeout=5) as client:
        payload = {"chat_id": resolved_chat_id, "text": text}
        try:
            response = await client.post(send_url, json=payload)
            response.raise_for_status()
            logger.info("Telegram message sent to chat %s", resolved_chat_id)
            return True
        except Exception as exc:
            body = getattr(exc, "response", None)
            detail = None
            if body is not None:
                with suppress(Exception):
                    detail = body.text
            logger.error(
                "Failed to send Telegram message to chat %s: %s %s",
                resolved_chat_id,
                exc,
                detail or "",
            )
            return False


async def poll_updates() -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
    last_id: int | None = None
    async with AsyncClient(timeout=30) as client:
        while True:
            payload: dict[str, int | float] = {"timeout": 20}
            if last_id is not None:
                payload["offset"] = last_id
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                logger.warning("Telegram polling failed: %s", exc)
                await asyncio.sleep(settings.telegram_poll_interval)
                continue

            for update in data.get("result", []):
                last_id = update.get("update_id", last_id) + 1
                message = update.get("message") or update.get("edited_message")
                if not message:
                    continue
                text = (message.get("text") or "").strip()
                sender = message.get("from", {})
                chat = message.get("chat", {})
                chat_id = chat.get("id")
                if chat_id is None:
                    continue
                username = sender.get("username") or chat.get("username")
                logger.info("Telegram message from chat %s: %s", chat_id, text)
                if text.startswith("/start"):
                    await handle_start(chat_id, username, text)
                else:
                    authorized = await resolve_authorized_user_id(chat_id, username)
                    if not authorized:
                        await send_bot_message(chat_id, AUTH_MISMATCH_MESSAGE)
                        continue
                    if decision_coordinator.has_pending():
                        answer = parse_answer(text, decision_coordinator.pending_options)
                        if answer:
                            await decision_coordinator.resolve(answer)
            await asyncio.sleep(settings.telegram_poll_interval)
