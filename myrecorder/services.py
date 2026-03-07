from __future__ import annotations

import asyncio
import contextlib
import threading

import aiohttp
import yt_dlp

from myrecorder.log import get_logger
from myrecorder.models import AppConfig, StreamTarget
from myrecorder.providers import StreamProvider, create_provider, supported_providers
from myrecorder.uploader import WebDAVUploader
from myrecorder.ytdlp_client import DownloadOptions, build_output_template, download_live


def _build_download_options(config: AppConfig, target: StreamTarget) -> DownloadOptions:
    live_from_start = config.live_from_start and target.provider != "fc2"
    return DownloadOptions(
        output_template=build_output_template(config.output_dir, target.streamer, config.hls_use_mpegts),
        download_archive=str(config.output_dir / ".download-archive.txt"),
        ytdlp_format=config.ytdlp_format,
        live_from_start=live_from_start,
        write_info_json=config.write_info_json,
        hls_use_mpegts=config.hls_use_mpegts,
        timeout_seconds=config.request_timeout_seconds,
        extra_args=config.ytdlp_extra_args,
    )


async def _monitor_target(
    config: AppConfig,
    target: StreamTarget,
    provider_client: StreamProvider,
    stop_event: asyncio.Event,
) -> None:
    logger = get_logger(component="watcher", provider=target.provider, streamer=target.streamer)
    running_task: asyncio.Task[int] | None = None
    running_stop_flag: threading.Event | None = None

    while not stop_event.is_set():
        if running_task is not None:
            if not running_task.done():
                await asyncio.sleep(2)
                continue
            try:
                code = running_task.result()
                logger.info("下载任务结束，code={}", code)
            except yt_dlp.utils.DownloadCancelled:
                logger.info("下载任务已取消")
            except Exception:
                logger.exception("出现未知错误")
            running_task = None
            running_stop_flag = None

        try:
            status = await provider_client.check_live(target.channel_url)
        except Exception as exc:
            logger.warning("开播检测失败: {}", exc)
            await asyncio.sleep(target.interval_seconds)
            continue

        if not status.is_live:
            logger.info("未开播，{} 秒后重试", target.interval_seconds)
            await asyncio.sleep(target.interval_seconds)
            continue

        if not status.live_url:
            logger.warning("检测结果缺少 live_url，{} 秒后重试", target.interval_seconds)
            await asyncio.sleep(target.interval_seconds)
            continue

        options = _build_download_options(config, target)
        logger.info("检测到开播: {} | title={}", status.live_url, status.title or "N/A")
        logger.info("启动 yt_dlp 下载")
        (config.output_dir / target.streamer).mkdir(parents=True, exist_ok=True)
        running_stop_flag = threading.Event()
        uploader = WebDAVUploader(config.webdav) if config.webdav is not None else None
        running_task = asyncio.create_task(
            asyncio.to_thread(
                download_live,
                status.live_url,
                opts=options,
                logger=logger,
                stop_flag=running_stop_flag,
                target=target,
                uploader=uploader,
            )
        )
        await asyncio.sleep(2)

    if running_stop_flag is not None:
        running_stop_flag.set()
    if running_task and not running_task.done():
        with contextlib.suppress(Exception):
            await asyncio.wait_for(running_task, timeout=10)


async def run_watchers(config: AppConfig) -> int:
    app_logger = get_logger(component="scheduler")
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

            app_logger.info("注册监听目标: {} / {}", target.provider, target.streamer)
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
