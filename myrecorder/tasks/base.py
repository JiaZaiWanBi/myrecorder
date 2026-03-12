from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from myrecorder.models import TaskContext


class BaseTask(ABC):
    name = "task"

    def __init__(self, *, task_config: dict[str, Any] | None = None) -> None:
        self.task_config = task_config or {}

    @abstractmethod
    async def run(self, context: TaskContext, payload: dict[str, Any]) -> None:
        raise NotImplementedError
