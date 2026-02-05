from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


LogLevel = Literal["info", "success", "warning", "error"]


class PlanPayload(BaseModel):
    project: str = Field(..., min_length=1)
    steps: list[str] = Field(..., min_length=1)


class LogPayload(BaseModel):
    level: LogLevel
    message: str = Field(..., min_length=1)
    step_index: int | None = Field(default=None, ge=1)


class AskPayload(BaseModel):
    question: str = Field(..., min_length=1)
    options: list[str] = Field(default_factory=list)
    mode: Literal["sync", "async"] = "sync"


class McpRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
