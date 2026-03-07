from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp


class _FakeLogger:
    def debug(self, msg: str) -> None:
        return

    def info(self, msg: str) -> None:
        return

    def warning(self, msg: str) -> None:
        return

    def error(self, msg: str) -> None:
        return


@dataclass(frozen=True)
class DownloadOptions:
    output_template: str
    download_archive: str
    ytdlp_format: str | None
    live_from_start: bool
    write_info_json: bool
    hls_use_mpegts: bool
    timeout_seconds: int
    extra_args: list[str]


def probe_live_status(url: str, timeout_seconds: int) -> dict[str, Any] | None:
    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "logger": _FakeLogger(),
        "socket_timeout": timeout_seconds,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        return None
    return info


def download_live(
    url: str,
    *,
    opts: DownloadOptions,
    logger: Any,
    stop_flag: threading.Event,
    target: Any,
    uploader: Any = None,
) -> int:
    if opts.extra_args:
        raise ValueError("ytdlp_extra_args is not supported when using yt_dlp Python API")

    uploaded_files: set[str] = set()

    def _check_cancel(status: dict[str, Any]) -> None:
        if stop_flag.is_set():
            raise yt_dlp.utils.DownloadCancelled("stop requested")
        if uploader is None:
            return
        if status.get("status") != "finished":
            return
        filename = str(status.get("filename") or "").strip()
        if not filename or filename in uploaded_files:
            return
        uploader.upload(filename, target)
        uploaded_files.add(filename)

    external_downloader_args: dict[str, list[str]] = {
        "ffmpeg": ["-loglevel", "error", "-nostats"],
    }
    ydl_opts: dict[str, Any] = {
        "outtmpl": opts.output_template,
        "download_archive": opts.download_archive,
        "logger": logger.bind(component="yt_dlp"),
        "progress_hooks": [_check_cancel],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "consoletitle": False,
        "verbose": False,
        "socket_timeout": opts.timeout_seconds,
        "writeinfojson": opts.write_info_json,
        "live_from_start": opts.live_from_start,
        "external_downloader_args": external_downloader_args,
    }
    if opts.hls_use_mpegts:
        ydl_opts["hls_prefer_native"] = False
        ydl_opts["external_downloader"] = {"m3u8": "ffmpeg"}
        external_downloader_args["ffmpeg_o"] = ["-f", "mpegts"]
    else:
        ydl_opts["hls_prefer_native"] = True
    if opts.ytdlp_format:
        ydl_opts["format"] = opts.ytdlp_format

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.download([url])


def build_output_template(output_dir: Path, streamer: str, hls_use_mpegts: bool) -> str:
    out_dir = output_dir / streamer
    suffix = ".ts" if hls_use_mpegts else ".%(ext)s"
    return str(out_dir / f"%(title).120B{suffix}")
