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
from myrecorder.ytdlp_client import (
    DownloadOptions,
    DownloadResult,
    _upload_outputs,
    build_output_template,
    download_live,
)


def _build_download_options(config: AppConfig, target: StreamTarget) -> DownloadOptions:
    live_from_start = config.live_from_start and target.provider != "fc2"
    return DownloadOptions(
        output_template=build_output_template(config.output_dir, target.streamer, config.hls_use_mpegts),
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
    running_task: asyncio.Task[DownloadResult] | None = None
    running_stop_flag: threading.Event | None = None
    upload_tasks: set[asyncio.Task[None]] = set()
    uploader: WebDAVUploader | None = None
    download_ready = asyncio.Event()
    download_ready.set()

    def _get_uploader() -> WebDAVUploader | None:
        nonlocal uploader
        if config.webdav is None:
            return None
        if uploader is None:
            uploader = WebDAVUploader(config.webdav)
        return uploader

    def _on_upload_done(task: asyncio.Task[None]) -> None:
        upload_tasks.discard(task)
        try:
            task.result()
        except Exception:
            logger.exception("上传任务失败")

    def _schedule_upload(result: DownloadResult) -> None:
        current_uploader = _get_uploader()
        if current_uploader is None:
            return
        logger.info("开始上传。")
        upload_task = asyncio.create_task(
            asyncio.to_thread(
                _upload_outputs,
                result.output,
                result.write_info_json,
                current_uploader,
                target,
                logger,
            )
        )
        upload_tasks.add(upload_task)
        upload_task.add_done_callback(_on_upload_done)

    def _on_download_done(task: asyncio.Task[DownloadResult]) -> None:
        nonlocal running_task, running_stop_flag
        try:
            result = task.result()
            logger.info("下载任务结束，code={}", result.code)
            _schedule_upload(result)
        except asyncio.CancelledError:
            logger.info("下载任务已取消")
        except yt_dlp.utils.DownloadCancelled:
            logger.info("下载任务已取消")
        except Exception:
            logger.exception("出现未知错误")
        running_task = None
        running_stop_flag = None
        download_ready.set()

    def _start_download(live_url: str, options: DownloadOptions) -> None:
        nonlocal running_task, running_stop_flag
        running_stop_flag = threading.Event()
        download_ready.clear()
        running_task = asyncio.create_task(
            asyncio.to_thread(
                download_live,
                live_url,
                opts=options,
                logger=logger,
                stop_flag=running_stop_flag,
            )
        )
        running_task.add_done_callback(_on_download_done)

    async def _wait_for_download_finish() -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(download_ready.wait(), timeout=2)

    try:
        while not stop_event.is_set():
            if running_task is not None:
                await _wait_for_download_finish()
                continue

            try:
                status = await provider_client.check_live(target.channel_url)
            except Exception as exc:
                logger.warning("开播检测失败: {}", exc)
                await asyncio.sleep(target.interval_seconds)
                continue

            if not status.is_live:
                logger.debug("未开播，{} 秒后重试", target.interval_seconds)
                await asyncio.sleep(target.interval_seconds)
                continue

            if not status.live_url:
                logger.warning("检测结果缺少 live_url，{} 秒后重试", target.interval_seconds)
                await asyncio.sleep(target.interval_seconds)
                continue

            options = _build_download_options(config, target)
            logger.info("检测到开播: {} | title={}", status.live_url, status.title or "无标题")
            logger.info("启动 yt_dlp 下载")
            (config.output_dir / target.streamer).mkdir(parents=True, exist_ok=True)
            _start_download(status.live_url, options)
            await asyncio.sleep(2)
    finally:
        active_download = running_task
        if running_stop_flag is not None:
            running_stop_flag.set()
        if active_download is not None:
            with contextlib.suppress(BaseException):
                await asyncio.shield(asyncio.wait_for(active_download, timeout=10))
            with contextlib.suppress(BaseException):
                await asyncio.shield(asyncio.wait_for(download_ready.wait(), timeout=10))
        if upload_tasks:
            with contextlib.suppress(BaseException):
                await asyncio.shield(asyncio.gather(*tuple(upload_tasks), return_exceptions=True))


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
