from __future__ import annotations

import asyncio
import threading

from myrecorder.models import DownloadTaskOutput, DownloaderTask, LiveTaskOutput, TaskContext
from myrecorder.ytdlp_client import DownloadOptions, build_output_template, download_live


def _build_download_options(context: TaskContext) -> DownloadOptions:
    live_from_start = context.config.live_from_start and context.target.provider != "fc2"
    return DownloadOptions(
        output_template=build_output_template(
            context.config.output_dir,
            context.target.streamer,
            context.config.hls_use_mpegts,
        ),
        ytdlp_format=context.config.ytdlp_format,
        live_from_start=live_from_start,
        write_info_json=context.config.write_info_json,
        hls_use_mpegts=context.config.hls_use_mpegts,
        timeout_seconds=context.config.request_timeout_seconds,
        extra_args=context.config.ytdlp_extra_args,
    )


class YtDlpDownloadTask(DownloaderTask):
    name = "yt_dlp"
    downloader_name = "yt_dlp"

    async def run(self, context: TaskContext, data: LiveTaskOutput) -> DownloadTaskOutput:
        download_url = data.m3u8_url or data.live_url
        if not download_url:
            raise ValueError("live task result does not contain live_url or m3u8_url")

        (context.config.output_dir / context.target.streamer).mkdir(parents=True, exist_ok=True)

        stop_flag = context.shared.get("stop_flag")
        if not isinstance(stop_flag, threading.Event):
            stop_flag = threading.Event()
            context.shared["stop_flag"] = stop_flag

        options = _build_download_options(context)
        result = await asyncio.to_thread(
            download_live,
            download_url,
            opts=options,
            logger=context.logger,
            stop_flag=stop_flag,
        )

        files = [result.output]
        if result.infojson:
            files.append(result.infojson)

        return DownloadTaskOutput(
            code=result.code,
            output=result.output,
            infojson=result.infojson,
            files=tuple(files),
            metadata={
                "title": data.title,
                "started_at": data.started_at,
                "live_url": data.live_url,
                "m3u8_url": data.m3u8_url,
                "download_url": download_url,
            },
        )
