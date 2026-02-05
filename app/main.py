from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from contextlib import suppress
from fastapi import FastAPI, HTTPException, status

from app.config import settings
from app.decision import decision_coordinator
from app.mcp import mcp_connector
from app.mcp_server import handle_mcp_request
from app.schemas import AskPayload, LogPayload, McpConnectPayload, McpRpcRequest, PlanPayload
from app.state import mission_manager
from app.telegram import (
    build_question_text,
    handle_start,
    resolve_authorized_user_id,
    parse_answer,
    poll_updates,
    send_bot_message,
)
from app.user_store import get_cached_user_id

logger = logging.getLogger("stdhuman")
handler = logging.StreamHandler()
formatter = logging.Formatter("[StdHuman] %(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

LOG_LEVEL_MAP: Dict[str, int] = {
    "info": logging.INFO,
    "success": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

app = FastAPI(title=settings.project_name)


def resolve_delivery_user_id() -> int | None:
    return get_cached_user_id()


def normalize_question_options() -> list[str]:
    return ["Command", "Stop"]


def build_question_summary(question: str, options: list[str]) -> str:
    last_status = mission_manager.current.last_status if mission_manager.current else None
    status_text = last_status or "none"
    return f"Last status: {status_text} | Prompt: {question} | Timeout: {settings.timeout}s"


@app.on_event("startup")
async def start_telegram_poller() -> None:
    if settings.telegram_bot_token:
        task = asyncio.create_task(poll_updates())
        app.state.telegram_poller = task


@app.on_event("shutdown")
async def stop_telegram_poller() -> None:
    task = getattr(app.state, "telegram_poller", None)
    if not task:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@app.post("/v1/plan", status_code=status.HTTP_202_ACCEPTED)
async def define_mission(payload: PlanPayload) -> Dict[str, str]:
    mission = await mission_manager.create(payload.project, payload.steps)
    logger.info("Defined mission %s (%s steps)", mission.id, len(mission.steps))
    chat_id = resolve_delivery_user_id()
    if chat_id is None:
        raise HTTPException(
            status_code=400,
            detail="authorized user id missing; send /start <code>",
        )
    lines = [f"Plan started: {mission.project} ({len(mission.steps)} steps)"]
    lines.append("Steps:")
    for idx, step in enumerate(mission.steps, start=1):
        lines.append(f"{idx}) {step}")
    summary = "\n".join(lines)
    delivered = await send_bot_message(chat_id, summary)
    if not delivered:
        raise HTTPException(status_code=502, detail="telegram send failed")
    return {"mission_id": mission.id}


@app.get("/v1/health")
async def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/mcp/status")
async def mcp_status() -> Dict[str, str | None]:
    connection = mcp_connector.connection
    if connection is None:
        return {"status": "disconnected"}
    return connection.to_response()


@app.post("/v1/mcp/connect")
async def connect_mcp(payload: McpConnectPayload) -> Dict[str, str | None]:
    server_url = payload.server_url or settings.mcp_server_url
    if not server_url:
        raise HTTPException(status_code=400, detail="mcp server url missing")
    health_path = payload.health_path or settings.mcp_health_path
    try:
        connection = await mcp_connector.connect(
            server_url=server_url,
            health_path=health_path,
            timeout_seconds=settings.mcp_connect_timeout,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return connection.to_response()


@app.post("/v1/mcp/disconnect")
async def disconnect_mcp() -> Dict[str, str]:
    mcp_connector.disconnect()
    return {"status": "disconnected"}


@app.post("/v1/log", status_code=status.HTTP_202_ACCEPTED)
async def report_status(payload: LogPayload) -> None:
    log_level = LOG_LEVEL_MAP.get(payload.level, logging.INFO)
    message = payload.message
    step_text = None
    if payload.step_index is not None:
        step_text = await mission_manager.complete_step(payload.step_index)
        if step_text:
            message = f"{message}\n{step_text}"
    logger.log(log_level, message)
    await mission_manager.append_log(f"{payload.level.upper()}: {message}")
    chat_id = resolve_delivery_user_id()
    if chat_id is None:
        raise HTTPException(
            status_code=400,
            detail="authorized user id missing; send /start <code>",
        )
    delivered = await send_bot_message(chat_id, message)
    if not delivered:
        raise HTTPException(status_code=502, detail="telegram send failed")


@app.post("/v1/ask")
async def human_decision(payload: AskPayload) -> Dict[str, str]:
    logger.info("Awaiting human decision: %s", payload.question)
    options = normalize_question_options()
    summary = build_question_summary(payload.question, options)
    if payload.mode == "async":
        if decision_coordinator.has_pending():
            raise HTTPException(status_code=409, detail="pending decision already exists")
        request_id = await decision_coordinator.create_pending(payload.question, options)
        chat_id = resolve_delivery_user_id()
        if chat_id:
            prompt = build_question_text(summary, options)
            delivered = await send_bot_message(chat_id, prompt)
            if not delivered:
                await decision_coordinator.cancel_pending()
                raise HTTPException(status_code=502, detail="telegram send failed")
        return {"request_id": request_id, "status": "pending"}

    chat_id = resolve_delivery_user_id()
    if chat_id:
        prompt = build_question_text(summary, options)
        delivered = await send_bot_message(chat_id, prompt)
        if not delivered:
            await decision_coordinator.cancel_pending()
            raise HTTPException(status_code=502, detail="telegram send failed")
    try:
        answer = await decision_coordinator.request_decision(payload.question, options, settings.timeout)
        logger.info("Human decision received: %s", answer)
        return {"answer": answer}
    except asyncio.TimeoutError:
        logger.warning("Human decision timed out for question: %s", payload.question)
        await decision_coordinator.cancel_pending()
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="timeout waiting for human response",
        )


@app.get("/v1/ask/result/{request_id}")
async def human_decision_result(request_id: str) -> Dict[str, str]:
    answer = await decision_coordinator.get_result(request_id)
    if answer is None:
        if decision_coordinator.request_id != request_id:
            raise HTTPException(status_code=404, detail="request not found")
        return {"status": "pending"}
    return {"answer": answer}


@app.post("/telegram/webhook")
async def telegram_webhook(payload: dict) -> dict:
    message = payload.get("message") or payload.get("edited_message")
    if not message:
        return {"ok": True}

    text = (message.get("text") or "").strip()
    sender = message.get("from", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if chat_id is None:
        return {"ok": False, "error": "missing chat id"}
    username = sender.get("username") or chat.get("username")

    if text.startswith("/start"):
        await handle_start(chat_id, username, text)
        return {"ok": True}

    authorized = await resolve_authorized_user_id(chat_id, username)
    if not authorized:
        await send_bot_message(chat_id, "Authorization mismatch. Contact the operator.")
        return {"ok": False, "error": "unauthorized"}

    if decision_coordinator.has_pending():
        answer = parse_answer(text, decision_coordinator.pending_options)
        if answer:
            await decision_coordinator.resolve(answer)
            return {"ok": True}

    return {"ok": True}


@app.post("/mcp")
async def mcp_entry(payload: McpRpcRequest) -> Dict[str, Any]:
    return await handle_mcp_request(payload, define_mission, report_status, human_decision)
