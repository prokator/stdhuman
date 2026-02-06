from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict
from urllib.parse import urlparse

from contextlib import suppress
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.config import settings
from app.decision import decision_coordinator
from app.mcp_server import SUPPORTED_PROTOCOL_VERSIONS, handle_mcp_request, mcp_lifecycle
from app.schemas import AskPayload, LogPayload, McpRpcRequest, PlanPayload
from app.start_code import ensure_start_code_present
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

MCP_SSE_KEEPALIVE_SECONDS = 15


def resolve_delivery_user_id() -> int | None:
    return get_cached_user_id()


def normalize_question_options() -> list[str]:
    return ["Command", "Stop"]


def build_question_summary(question: str, options: list[str], timeout_seconds: float) -> str:
    last_status = mission_manager.current.last_status if mission_manager.current else None
    status_text = last_status or "none"
    return f"Last status: {status_text} | Prompt: {question} | Timeout: {timeout_seconds}s"


@app.on_event("startup")
async def start_telegram_poller() -> None:
    ensure_start_code_present()
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
    if decision_coordinator.has_pending():
        await decision_coordinator.cancel_pending()
    options = normalize_question_options()
    timeout = payload.timeout if payload.timeout is not None else settings.timeout
    summary = build_question_summary(payload.question, options, timeout)
    chat_id = resolve_delivery_user_id()
    if chat_id:
        prompt = build_question_text(summary, options)
        delivered = await send_bot_message(chat_id, prompt)
        if not delivered:
            await decision_coordinator.cancel_pending()
            raise HTTPException(status_code=502, detail="telegram send failed")
    try:
        answer = await decision_coordinator.request_decision(payload.question, options, timeout)
        logger.info("Human decision received: %s", answer)
        return {"answer": answer}
    except asyncio.TimeoutError:
        logger.warning("Human decision timed out for question: %s", payload.question)
        await decision_coordinator.cancel_pending()
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="timeout waiting for human response",
        )


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


@app.post("/mcp", response_model=None)
async def mcp_entry(request: Request) -> Response | Dict[str, Any] | StreamingResponse:
    _validate_mcp_headers(request)
    payload = await _load_mcp_payload(request)
    if _is_jsonrpc_response(payload) or _is_jsonrpc_notification(payload):
        if payload.get("method") == "notifications/initialized":
            await mcp_lifecycle.mark_ready()
        return Response(status_code=status.HTTP_202_ACCEPTED)
    mcp_request = McpRpcRequest.model_validate(payload)
    if _wants_mcp_sse(request) and _should_stream_mcp(mcp_request):
        task = asyncio.create_task(
            handle_mcp_request(mcp_request, define_mission, report_status, human_decision)
        )

        async def event_stream() -> AsyncGenerator[str, None]:
            try:
                while True:
                    done, _ = await asyncio.wait({task}, timeout=MCP_SSE_KEEPALIVE_SECONDS)
                    if done:
                        break
                    yield ": keep-alive\n\n"
                response_payload = await task
                data = json.dumps(response_payload, ensure_ascii=True)
                yield f"data: {data}\n\n"
            except asyncio.CancelledError:
                task.cancel()
                raise

        headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)

    response_payload = await handle_mcp_request(
        mcp_request,
        define_mission,
        report_status,
        human_decision,
    )
    return response_payload


@app.get("/mcp", response_model=None)
async def mcp_stream(request: Request) -> Response:
    _validate_mcp_headers(request)
    accept = request.headers.get("accept", "")
    if "text/event-stream" not in accept.lower():
        return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED)
    once_flag = request.query_params.get("once")
    if once_flag and once_flag.lower() in {"1", "true", "yes"}:
        async def event_stream() -> AsyncGenerator[str, None]:
            yield ": keep-alive\n\n"
        headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)
    async def event_stream() -> AsyncGenerator[str, None]:
        while True:
            yield ": keep-alive\n\n"
            await asyncio.sleep(15)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


def _wants_mcp_sse(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept.lower():
        return True
    transport = request.query_params.get("transport")
    if transport and transport.lower() == "sse":
        return True
    sse_flag = request.query_params.get("sse")
    if sse_flag and sse_flag.lower() in {"1", "true", "yes"}:
        return True
    return False


def _should_stream_mcp(request: McpRpcRequest) -> bool:
    if request.method != "tools/call":
        return True
    tool_name = request.params.get("name")
    return tool_name != "stdhuman.ask"


def _validate_mcp_headers(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and not _is_allowed_origin(origin):
        raise HTTPException(status_code=403, detail="origin not allowed")
    protocol_version = request.headers.get("mcp-protocol-version")
    if protocol_version and protocol_version not in set(SUPPORTED_PROTOCOL_VERSIONS):
        raise HTTPException(status_code=400, detail="unsupported MCP protocol version")


def _is_allowed_origin(origin: str) -> bool:
    if origin.strip().lower() == "null":
        return True
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1"}


async def _load_mcp_payload(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="invalid JSON-RPC payload")
    return payload


def _is_jsonrpc_notification(payload: dict[str, Any]) -> bool:
    return "method" in payload and payload.get("id") is None


def _is_jsonrpc_response(payload: dict[str, Any]) -> bool:
    if "method" in payload:
        return False
    if "id" not in payload:
        return False
    return "result" in payload or "error" in payload
