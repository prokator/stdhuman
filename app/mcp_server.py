from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas import AskPayload, LogPayload, McpRpcRequest, PlanPayload

MCP_PROTOCOL_VERSION = "2024-11-05"

PlanHandler = Callable[[PlanPayload], Awaitable[dict[str, str]]]
LogHandler = Callable[[LogPayload], Awaitable[None]]
AskHandler = Callable[[AskPayload], Awaitable[dict[str, str]]]


def build_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "plan",
            "description": "Create a mission plan and notify Telegram.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["project", "steps"],
            },
        },
        {
            "name": "log",
            "description": "Send a status update and optional step completion.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "level": {"type": "string"},
                    "message": {"type": "string"},
                    "step_index": {"type": "integer"},
                },
                "required": ["level", "message"],
            },
        },
        {
            "name": "ask",
            "description": "Request a human decision via Telegram.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "mode": {"type": "string"},
                },
                "required": ["question"],
            },
        },
    ]


def _response(request_id: str | int | None, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: str | int | None, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _tool_success(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=True)
    return {
        "content": [{"type": "text", "text": text}],
        "output": payload,
        "isError": False,
    }


async def handle_mcp_request(
    payload: McpRpcRequest,
    plan_handler: PlanHandler,
    log_handler: LogHandler,
    ask_handler: AskHandler,
) -> dict[str, Any]:
    if payload.method == "initialize":
        result = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
        }
        return _response(payload.id, result)

    if payload.method == "tools/list":
        return _response(payload.id, {"tools": build_tool_definitions()})

    if payload.method != "tools/call":
        return _error(payload.id, -32601, "Method not found")

    tool_name = payload.params.get("name")
    arguments = payload.params.get("arguments") or {}
    if tool_name not in {"plan", "log", "ask"}:
        return _error(payload.id, -32602, "Unknown tool")

    try:
        if tool_name == "plan":
            result = await plan_handler(PlanPayload(**arguments))
            return _response(payload.id, _tool_success({"mission_id": result.get("mission_id")}))

        if tool_name == "log":
            await log_handler(LogPayload(**arguments))
            return _response(payload.id, _tool_success({"status": "logged"}))

        result = await ask_handler(AskPayload(**arguments))
        return _response(payload.id, _tool_success(result))
    except ValidationError as exc:
        return _error(payload.id, -32602, "Invalid params", exc.errors())
    except HTTPException as exc:
        return _error(payload.id, -32000, str(exc.detail))
    except Exception as exc:
        return _error(payload.id, -32603, str(exc))
