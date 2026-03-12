from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class StreamTarget:
    provider: str
    streamer: str
    channel_url: str
    interval_seconds: int
    workflow: tuple[str, ...] | None = None
    task_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(
            (
                self.provider,
                self.streamer,
                self.channel_url,
                self.interval_seconds,
                self.workflow,
            )
        )


@dataclass(frozen=True)
class WorkflowConfig:
    default: tuple[str, ...] | None = None
    providers: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    output_dir: Path
    interval_seconds: int
    request_timeout_seconds: int
    request_retries: int
    workflow: WorkflowConfig
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    streams: list[StreamTarget] = field(default_factory=list)


@dataclass(frozen=True)
class LiveStatus:
    is_live: bool
    channel_url: str
    live_url: str = ""
    m3u8_url: str = ""
    cover_url: str = ""
    title: str = ""
    description: str = ""
    started_at: str = ""
    info: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskContext:
    target: StreamTarget
    live_status: LiveStatus
    logger: Any
    session: Any | None = None
    shared: dict[str, Any] = field(default_factory=dict)


class BaseTask(ABC):
    name = "task"

    @abstractmethod
    async def run(self, context: TaskContext, payload: dict[str, Any]) -> None:
        raise NotImplementedError


class ProviderTask(ABC):
    provider_name = ""

    @abstractmethod
    async def check_live(self, channel_url: str) -> LiveStatus:
        raise NotImplementedError


class StreamProvider(Protocol):
    async def check_live(self, channel_url: str) -> LiveStatus:
        ...


__all__ = [
    "AppConfig",
    "BaseTask",
    "LiveStatus",
    "ProviderTask",
    "StreamProvider",
    "StreamTarget",
    "TaskContext",
    "WorkflowConfig",
]
