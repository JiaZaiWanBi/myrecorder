from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Literal, Protocol, TypeVar


@dataclass(frozen=True)
class StreamTarget:
    provider: str
    streamer: str
    channel_url: str
    interval_seconds: int
    downloader: str | None = None
    workflow: tuple[str, ...] | None = None


@dataclass(frozen=True)
class WebDAVConfig:
    url: str
    user: str
    password: str
    root: str = "/"
    rclone_path: str = "rclone"
    mode: Literal["copy", "move"] = "copy"


@dataclass(frozen=True)
class AppConfig:
    output_dir: Path
    interval_seconds: int
    request_timeout_seconds: int
    request_retries: int
    ytdlp_format: str | None
    live_from_start: bool
    write_info_json: bool
    ytdlp_extra_args: list[str]
    hls_use_mpegts: bool
    workflow: WorkflowConfig
    webdav: WebDAVConfig | None
    streams: list[StreamTarget]


@dataclass(frozen=True)
class WorkflowConfig:
    default: tuple[str, ...] | None = None
    providers: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveStatus:
    is_live: bool
    channel_url: str
    live_url: str = ""
    m3u8_url: str = ""
    title: str = ""
    description: str = ""
    started_at: str = ""
    info: dict[str, Any] = field(default_factory=dict)


LiveTaskOutput = LiveStatus


@dataclass(frozen=True)
class DownloadTaskOutput:
    code: int
    output: str
    infojson: str = ""
    files: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UploadTaskOutput:
    uploaded_files: tuple[str, ...] = ()
    remote_paths: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskContext:
    config: AppConfig
    target: StreamTarget
    logger: Any
    session: Any | None = None
    shared: dict[str, Any] = field(default_factory=dict)


TaskInput = TypeVar("TaskInput")
TaskOutput = TypeVar("TaskOutput")


class BaseTask(ABC, Generic[TaskInput, TaskOutput]):
    name = "task"

    @abstractmethod
    async def run(self, context: TaskContext, data: TaskInput) -> TaskOutput:
        raise NotImplementedError


class ProviderTask(BaseTask[None, LiveTaskOutput], ABC):
    provider_name = ""
    available_downloaders: tuple[str, ...] = ()
    default_downloader: str | None = None

    @abstractmethod
    async def check_live(self, channel_url: str) -> LiveTaskOutput:
        raise NotImplementedError

    async def run(self, context: TaskContext, data: None = None) -> LiveTaskOutput:
        return await self.check_live(context.target.channel_url)


class DownloaderTask(BaseTask[LiveTaskOutput, DownloadTaskOutput], ABC):
    downloader_name = ""


class UploaderTask(BaseTask[DownloadTaskOutput, UploadTaskOutput], ABC):
    uploader_name = ""


class StreamProvider(Protocol):
    async def check_live(self, channel_url: str) -> LiveStatus:
        ...


__all__ = [
    "AppConfig",
    "BaseTask",
    "DownloadTaskOutput",
    "DownloaderTask",
    "LiveStatus",
    "LiveTaskOutput",
    "ProviderTask",
    "StreamProvider",
    "StreamTarget",
    "TaskContext",
    "UploadTaskOutput",
    "UploaderTask",
    "WebDAVConfig",
    "WorkflowConfig",
]
