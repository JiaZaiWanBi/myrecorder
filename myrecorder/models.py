from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class StreamTarget:
    provider: str
    streamer: str
    channel_url: str
    interval_seconds: int
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
class FC2LiveDlGoConfig:
    binary: str = "fc2-live-dl-go.exe"
    remux_format: str = "mp4"
    write_thumbnail: bool = True
    extract_audio: bool = False
    remux: bool = True


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
    ytdlp_format: str | None
    live_from_start: bool
    write_info_json: bool
    ytdlp_extra_args: list[str]
    hls_use_mpegts: bool
    workflow: WorkflowConfig
    webdav: WebDAVConfig | None
    fc2_live_dl_go: FC2LiveDlGoConfig | None
    streams: list[StreamTarget]


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
class WorkflowState:
    live_status: LiveStatus
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskContext:
    target: StreamTarget
    logger: Any
    session: Any | None = None
    shared: dict[str, Any] = field(default_factory=dict)


class BaseTask(ABC):
    name = "task"

    @abstractmethod
    async def run(self, context: TaskContext, state: WorkflowState) -> None:
        raise NotImplementedError


class ProviderTask(ABC):
    provider_name = ""

    @abstractmethod
    async def check_live(self, channel_url: str) -> LiveStatus:
        raise NotImplementedError


class DownloaderTask(BaseTask, ABC):
    downloader_name = ""


class UploaderTask(BaseTask, ABC):
    uploader_name = ""


class StreamProvider(Protocol):
    async def check_live(self, channel_url: str) -> LiveStatus:
        ...


__all__ = [
    "AppConfig",
    "BaseTask",
    "DownloaderTask",
    "FC2LiveDlGoConfig",
    "LiveStatus",
    "ProviderTask",
    "StreamProvider",
    "StreamTarget",
    "TaskContext",
    "UploaderTask",
    "WebDAVConfig",
    "WorkflowConfig",
    "WorkflowState",
]
