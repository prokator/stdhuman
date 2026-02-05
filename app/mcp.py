from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from httpx import AsyncClient


@dataclass
class McpConnection:
    server_url: str
    health_url: str
    status: str
    last_checked: str
    last_error: str | None = None

    def to_response(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "server_url": self.server_url,
            "health_url": self.health_url,
            "last_checked": self.last_checked,
            "last_error": self.last_error,
        }


class McpConnector:
    def __init__(self) -> None:
        self._connection: McpConnection | None = None

    @property
    def connection(self) -> McpConnection | None:
        return self._connection

    async def connect(self, server_url: str, health_path: str, timeout_seconds: float) -> McpConnection:
        normalized = server_url.strip()
        self._validate_server_url(normalized)
        health_url = self._build_health_url(normalized, health_path)
        status = "connected"
        last_error = None
        try:
            async with AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(health_url)
                response.raise_for_status()
        except Exception as exc:
            status = "failed"
            last_error = str(exc)
        connection = McpConnection(
            server_url=normalized,
            health_url=health_url,
            status=status,
            last_checked=self._timestamp(),
            last_error=last_error,
        )
        self._connection = connection
        return connection

    def disconnect(self) -> None:
        self._connection = None

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _build_health_url(server_url: str, health_path: str) -> str:
        path = (health_path or "/health").strip()
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{server_url.rstrip('/')}{path}"

    @staticmethod
    def _validate_server_url(server_url: str) -> None:
        parsed = urlparse(server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("mcp server url must be http(s) with a host")


mcp_connector = McpConnector()
