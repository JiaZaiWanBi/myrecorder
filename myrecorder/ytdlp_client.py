from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp


class _YtdlpLogger:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def debug(self, msg: str) -> None:
        # yt_dlp debug output is too noisy for long-running live tasks.
        return

    def info(self, msg: str) -> None:
        # Keep app logs focused on recorder lifecycle events.
        return

    def warning(self, msg: str) -> None:
        self._logger.warning(msg)

    def error(self, msg: str) -> None:
        self._logger.error(msg)


@dataclass(frozen=True)
class DownloadOptions:
    output_template: str
    download_archive: str
    ytdlp_format: str | None
    live_from_start: bool
    write_info_json: bool
    wait_for_video: str | None
    hls_use_mpegts: bool
    timeout_seconds: int
    extra_args: list[str]


def probe_live_status(url: str, timeout_seconds: int) -> str | None:
    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": timeout_seconds,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        return None
    status = info.get("live_status")
    return str(status).strip() if status is not None else None


def download_live(
    url: str,
    *,
    opts: DownloadOptions,
    logger: logging.Logger,
    stop_flag: threading.Event,
) -> int:
    if opts.extra_args:
        raise ValueError("ytdlp_extra_args is not supported when using yt_dlp Python API")

    def _check_cancel(_: dict[str, Any]) -> None:
        if stop_flag.is_set():
            raise yt_dlp.utils.DownloadCancelled("stop requested")

    ydl_opts: dict[str, Any] = {
        "outtmpl": opts.output_template,
        "download_archive": opts.download_archive,
        "logger": _YtdlpLogger(logger),
        "progress_hooks": [_check_cancel],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "consoletitle": False,
        "verbose": False,
        "socket_timeout": opts.timeout_seconds,
        "hls_prefer_native": True,
        "hls_use_mpegts": opts.hls_use_mpegts,
        "external_downloader_args": {"ffmpeg": ["-loglevel", "error", "-nostats"]},
        "writeinfojson": opts.write_info_json,
        "wait_for_video": opts.wait_for_video,
        "live_from_start": opts.live_from_start,
    }
    if opts.ytdlp_format:
        ydl_opts["format"] = opts.ytdlp_format

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.download([url])


def build_output_template(output_dir: Path, streamer: str) -> str:
    out_dir = output_dir / streamer
    return str(out_dir / "%(upload_date>%Y%m%d)s_%(title).120B_%(id)s.%(ext)s")
