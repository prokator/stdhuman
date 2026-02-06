from __future__ import annotations

import json
import asyncio
from typing import Any, Awaitable, Callable

from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas import AskPayload, LogPayload, McpRpcRequest, PlanPayload

SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

PlanHandler = Callable[[PlanPayload], Awaitable[dict[str, str]]]
LogHandler = Callable[[LogPayload], Awaitable[None]]
AskHandler = Callable[[AskPayload], Awaitable[dict[str, str]]]


class McpLifecycleState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._initialized = False
        self._ready = False
        self._protocol_version: str | None = None

    async def mark_initialized(self, protocol_version: str) -> None:
        async with self._lock:
            self._initialized = True
            self._ready = False
            self._protocol_version = protocol_version

    async def mark_ready(self) -> None:
        async with self._lock:
            if self._initialized:
                self._ready = True

    async def is_ready(self) -> bool:
        async with self._lock:
            return self._ready


mcp_lifecycle = McpLifecycleState()


def build_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "stdhuman.plan",
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
            "name": "stdhuman.log",
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
            "name": "stdhuman.ask",
            "description": "Request a human decision via Telegram (blocking).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "timeout": {"type": "number"},
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
        "structuredContent": payload,
        "isError": False,
    }


async def handle_mcp_request(
    payload: McpRpcRequest,
    plan_handler: PlanHandler,
    log_handler: LogHandler,
    ask_handler: AskHandler,
) -> dict[str, Any]:
    if payload.method == "initialize":
        params = payload.params or {}
        requested_version = params.get("protocolVersion")
        if not isinstance(requested_version, str) or not requested_version:
            return _error(payload.id, -32602, "Invalid params", [{"field": "protocolVersion"}])
        if requested_version in SUPPORTED_PROTOCOL_VERSIONS:
            selected_version = requested_version
        else:
            selected_version = DEFAULT_PROTOCOL_VERSION
        await mcp_lifecycle.mark_initialized(selected_version)
        result = {
            "protocolVersion": selected_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "stdhuman",
                "title": "StdHuman MCP Server",
                "version": "0.1.0",
            },
            "instructions": "Use tools/list and tools/call after notifications/initialized.",
        }
        return _response(payload.id, result)

    if payload.method == "tools/list":
        if not await mcp_lifecycle.is_ready():
            return _error(payload.id, -32000, "Server not initialized")
        return _response(payload.id, {"tools": build_tool_definitions()})

    if payload.method != "tools/call":
        return _error(payload.id, -32601, "Method not found")

    tool_name = payload.params.get("name")
    arguments = payload.params.get("arguments") or {}
    if tool_name not in {
        "stdhuman.plan",
        "stdhuman.log",
        "stdhuman.ask",
    }:
        return _error(payload.id, -32602, "Unknown tool")

    try:
        if tool_name == "stdhuman.plan":
            result = await plan_handler(PlanPayload(**arguments))
            return _response(payload.id, _tool_success({"mission_id": result.get("mission_id")}))

        if tool_name == "stdhuman.log":
            await log_handler(LogPayload(**arguments))
            return _response(payload.id, _tool_success({"status": "logged"}))

        result = await ask_handler(AskPayload(**arguments))
        if "answer" in result and "status" not in result:
            result = {"status": "done", "answer": result["answer"]}
        return _response(payload.id, _tool_success(result))
    except ValidationError as exc:
        return _error(payload.id, -32602, "Invalid params", exc.errors())
    except HTTPException as exc:
        return _error(payload.id, -32000, str(exc.detail))
    except Exception as exc:
        return _error(payload.id, -32603, str(exc))
