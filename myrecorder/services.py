from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from pathlib import Path
from typing import Protocol

import aiohttp
import yt_dlp

try:
    from .providers import StreamProvider, create_provider, supported_providers
    from .ytdlp_client import DownloadOptions, build_output_template, download_live
except ImportError:
    from providers import StreamProvider, create_provider, supported_providers
    from ytdlp_client import DownloadOptions, build_output_template, download_live


class StreamTargetLike(Protocol):
    provider: str
    streamer: str
    channel_url: str
    poll_interval_seconds: int
    wait_for_video: str | None


class AppConfigLike(Protocol):
    output_dir: Path
    request_timeout_seconds: int
    request_retries: int
    ytdlp_format: str | None
    live_from_start: bool
    write_info_json: bool
    ytdlp_extra_args: list[str]
    hls_use_mpegts: bool
    streams: list[StreamTargetLike]


def _build_download_options(config: AppConfigLike, target: StreamTargetLike) -> DownloadOptions:
    if target.provider == "fc2":
        live_from_start = False
    elif config.live_from_start:
        live_from_start = True
    else:
        live_from_start = False

    return DownloadOptions(
        output_template=build_output_template(config.output_dir, target.streamer),
        download_archive=str(config.output_dir / ".download-archive.txt"),
        ytdlp_format=config.ytdlp_format,
        live_from_start=live_from_start,
        write_info_json=config.write_info_json,
        wait_for_video=target.wait_for_video,
        hls_use_mpegts=config.hls_use_mpegts,
        timeout_seconds=config.request_timeout_seconds,
        extra_args=config.ytdlp_extra_args,
    )


async def _monitor_target(
    config: AppConfigLike,
    target: StreamTargetLike,
    provider_client: StreamProvider,
    stop_event: asyncio.Event,
) -> None:
    logger = logging.getLogger(f"myrecorder.{target.provider}.{target.streamer}")
    running_task: asyncio.Task[int] | None = None
    running_stop_flag: threading.Event | None = None

    while not stop_event.is_set():
        if running_task is not None:
            if not running_task.done():
                await asyncio.sleep(2)
                continue
            try:
                code = running_task.result()
                logger.info("yt-dlp 已结束，code=%s", code)
            except yt_dlp.utils.DownloadCancelled:
                logger.info("yt-dlp 已取消")
            except Exception as exc:
                logger.warning("yt-dlp 下载失败: %s", exc)
            running_task = None
            running_stop_flag = None

        try:
            status = await provider_client.check_live(target.channel_url)
        except Exception as exc:
            logger.warning("开播检测失败: %s", exc)
            await asyncio.sleep(target.poll_interval_seconds)
            continue

        if not status.is_live:
            logger.info("未开播，%ss 后重试", target.poll_interval_seconds)
            await asyncio.sleep(target.poll_interval_seconds)
            continue

        if not status.live_url:
            logger.warning(
                "provider=%s 返回 is_live=true 但 live_url 为空，%ss 后重试",
                target.provider,
                target.poll_interval_seconds,
            )
            await asyncio.sleep(target.poll_interval_seconds)
            continue

        options = _build_download_options(config, target)
        logger.info("检测到开播: %s | title=%s", status.live_url, status.title or "N/A")
        logger.info("启动 yt-dlp下载")
        (config.output_dir / target.streamer).mkdir(parents=True, exist_ok=True)
        running_stop_flag = threading.Event()
        running_task = asyncio.create_task(
            asyncio.to_thread(
                download_live,
                status.live_url,
                opts=options,
                logger=logger,
                stop_flag=running_stop_flag,
            )
        )
        await asyncio.sleep(2)

    if running_stop_flag is not None:
        running_stop_flag.set()
    if running_task and not running_task.done():
        with contextlib.suppress(Exception):
            await asyncio.wait_for(running_task, timeout=10)


async def run_watchers(config: AppConfigLike) -> int:
    timeout = aiohttp.ClientTimeout(
        total=None,
        connect=config.request_timeout_seconds,
        sock_read=config.request_timeout_seconds,
    )
    connector = aiohttp.TCPConnector(limit=max(len(config.streams) * 4, 20))
    stop_event = asyncio.Event()

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        tasks: list[asyncio.Task[None]] = []
        for target in config.streams:
            try:
                provider_client = create_provider(
                    target.provider,
                    session=session,
                    timeout_seconds=config.request_timeout_seconds,
                    retries=config.request_retries,
                )
            except Exception as exc:
                supported = ", ".join(supported_providers())
                raise ValueError(f"provider 初始化失败: {target.provider} ({exc}); 支持: {supported}") from exc

            tasks.append(asyncio.create_task(_monitor_target(config, target, provider_client, stop_event)))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            stop_event.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    return 0
