from __future__ import annotations

import asyncio
from typing import Iterable, List, Optional

from uuid import uuid4


class DecisionCoordinator:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._future: Optional[asyncio.Future[str]] = None
        self._question: Optional[str] = None
        self._options: List[str] = []
        self._request_id: Optional[str] = None
        self._answer: Optional[str] = None

    @property
    def pending_question(self) -> Optional[str]:
        return self._question

    @property
    def pending_options(self) -> List[str]:
        return self._options.copy()

    def has_pending(self) -> bool:
        return self._future is not None and not self._future.done()

    @property
    def request_id(self) -> Optional[str]:
        return self._request_id

    async def create_pending(self, question: str, options: Iterable[str]) -> str:
        async with self._lock:
            if self._future and not self._future.done():
                raise RuntimeError("pending decision already exists")
            self._question = question
            self._options = list(options)
            self._future = asyncio.get_running_loop().create_future()
            self._request_id = str(uuid4())
            self._answer = None
            return self._request_id

    async def request_decision(self, question: str, options: Iterable[str], timeout: int) -> str:
        request_id = await self.create_pending(question, options)
        async with self._lock:
            future = self._future
        if future is None:
            raise RuntimeError("decision future missing")

        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            async with self._lock:
                if self._future is future:
                    self._future = None
                    self._question = None
                    self._options = []
                    self._request_id = None
                    self._answer = None

    async def resolve(self, answer: str) -> bool:
        async with self._lock:
            if self._future and not self._future.done():
                self._answer = answer
                self._future.set_result(answer)
                return True
        return False

    async def get_result(self, request_id: str) -> Optional[str]:
        async with self._lock:
            if request_id != self._request_id:
                return None
            return self._answer

    async def cancel_pending(self) -> None:
        async with self._lock:
            if self._future and not self._future.done():
                self._future.cancel()
            self._future = None
            self._question = None
            self._options = []
            self._request_id = None
            self._answer = None


decision_coordinator = DecisionCoordinator()
