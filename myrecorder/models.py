from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from pathlib import Path


@dataclass(frozen=True)
class StreamTarget:
    provider: str
    streamer: str
    channel_url: str
    interval_seconds: int


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
    webdav: WebDAVConfig | None
    streams: list[StreamTarget]


@dataclass(frozen=True)
class WebDAVConfig:
    url: str
    user: str
    password: str
    root: str = "/"
    rclone_path: str = "rclone"
    mode: Literal["copy", "move"] = "copy"
