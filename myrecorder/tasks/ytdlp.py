from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

from myrecorder.models import TaskContext
from myrecorder.registry import Registry
from myrecorder.tasks.base import BaseTask


@dataclass(frozen=True)
class DownloadOptions:
    output_template: str
    ytdlp_format: str | None
    live_from_start: bool
    write_info_json: bool
    hls_use_mpegts: bool
    timeout_seconds: int
    extra_args: list[str]


@dataclass(frozen=True)
class DownloadResult:
    code: int
    output: str
    infojson: str = ""


def _build_download_options(task_config: dict[str, Any], output_dir: Path, streamer: str, provider: str) -> DownloadOptions:
    hls_use_mpegts = bool(task_config.get("hls_use_mpegts", True))
    live_from_start = bool(task_config.get("live_from_start", False)) and provider != "fc2"
    return DownloadOptions(
        output_template=_build_output_template(output_dir, streamer, hls_use_mpegts),
        ytdlp_format=str(task_config["format"]).strip() if task_config.get("format") is not None else None,
        live_from_start=live_from_start,
        write_info_json=bool(task_config.get("write_info_json", True)),
        hls_use_mpegts=hls_use_mpegts,
        timeout_seconds=int(task_config.get("timeout_seconds", 8)),
        extra_args=list(task_config.get("extra_args") or []),
    )


def _build_infojson_outtmpl(output_template: str) -> str:
    template = output_template.strip()
    stem, dot, _ext = template.rpartition(".")
    return stem if dot else template


def _build_output_template(output_dir: Path, streamer: str, hls_use_mpegts: bool) -> str:
    out_dir = output_dir / streamer
    suffix = ".ts" if hls_use_mpegts else ".%(ext)s"
    return str(out_dir / f"%(title).120B_%(id)s{suffix}")


def _download_live(
    url: str,
    *,
    opts: DownloadOptions,
    logger: Any,
    stop_flag: threading.Event,
) -> DownloadResult:
    if opts.extra_args:
        raise ValueError("ytdlp extra_args is not supported when using yt_dlp Python API")

    Path(opts.output_template).parent.mkdir(parents=True, exist_ok=True)

    def _check_cancel(_: dict[str, Any]) -> None:
        if stop_flag.is_set():
            raise yt_dlp.utils.DownloadCancelled("stop requested")

    external_downloader_args: dict[str, list[str]] = {"ffmpeg": ["-loglevel", "error", "-nostats"]}
    outtmpl: str | dict[str, str] = opts.output_template
    if opts.write_info_json:
        outtmpl = {"default": opts.output_template, "infojson": _build_infojson_outtmpl(opts.output_template)}
    ydl_opts: dict[str, Any] = {
        "outtmpl": outtmpl,
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
        info = ydl.extract_info(url, download=False)
        filename = ydl.prepare_filename(info)
        infojson_filename = ydl.prepare_filename(info, "infojson") if opts.write_info_json else ""
        code = ydl.download([url])

    return DownloadResult(code=code, output=filename, infojson=infojson_filename)


@Registry.register_task("yt_dlp")
class YtDlpDownloadTask(BaseTask):
    name = "yt_dlp"

    async def run(self, context: TaskContext, payload: dict[str, Any]) -> None:
        download_url = context.live_status.m3u8_url or context.live_status.live_url
        if not download_url:
            raise ValueError("live_status does not contain live_url or m3u8_url")

        output_dir = Path(str(self.task_config.get("output_dir") or "./recordings"))
        output_dir.mkdir(parents=True, exist_ok=True)

        stop_flag = context.shared.get("stop_flag")
        if not isinstance(stop_flag, threading.Event):
            stop_flag = threading.Event()
            context.shared["stop_flag"] = stop_flag

        options = _build_download_options(self.task_config, output_dir, context.target.streamer, context.target.provider)
        result = await asyncio.to_thread(_download_live, download_url, opts=options, logger=context.logger, stop_flag=stop_flag)

        files = [result.output]
        if result.infojson:
            files.append(result.infojson)

        payload["download"] = {
            "code": result.code,
            "output": result.output,
            "infojson": result.infojson,
            "files": files,
            "download_url": download_url,
        }
