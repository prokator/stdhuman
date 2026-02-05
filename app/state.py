from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from uuid import uuid4


@dataclass
class Mission:
    id: str
    project: str
    steps: List[str]
    started_at: datetime
    last_status: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    completed_steps: List[int] = field(default_factory=list)


class MissionManager:
    """Tracks the latest mission context in memory."""

    def __init__(self) -> None:
        self._missions: Dict[str, Mission] = {}
        self._lock = asyncio.Lock()
        self._current_id: Optional[str] = None

    async def create(self, project: str, steps: List[str]) -> Mission:
        mission_id = str(uuid4())
        mission = Mission(id=mission_id, project=project, steps=steps.copy(), started_at=datetime.now(timezone.utc))
        async with self._lock:
            self._missions[mission_id] = mission
            self._current_id = mission_id
        return mission

    async def append_log(self, text: str) -> None:
        async with self._lock:
            current = self.current
            if current:
                current.logs.append(text)
                current.last_status = text

    async def complete_step(self, step_index: int) -> Optional[str]:
        async with self._lock:
            current = self.current
            if not current:
                return None
            if step_index < 1 or step_index > len(current.steps):
                return None
            if step_index not in current.completed_steps:
                current.completed_steps.append(step_index)
            step_text = current.steps[step_index - 1]
            return f"Step {step_index}/{len(current.steps)} complete: {step_text}"

    @property
    def current(self) -> Optional[Mission]:
        if self._current_id:
            return self._missions.get(self._current_id)
        return None


mission_manager = MissionManager()
