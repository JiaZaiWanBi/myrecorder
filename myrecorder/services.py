from __future__ import annotations

import asyncio
import contextlib
import os
import threading
from pathlib import Path
from typing import Any

import aiohttp
import yt_dlp

from myrecorder.log import get_logger
from myrecorder.models import AppConfig, StreamTarget
from myrecorder.providers import StreamProvider, create_provider, supported_providers
from myrecorder.uploader import WebDAVUploader
from myrecorder.ytdlp_client import (
    DownloadOptions,
    DownloadResult,
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


def _upload_recording_outputs(
    output: str,
    infojson: str,
    uploader: WebDAVUploader,
    target: StreamTarget,
    logger: Any,
) -> None:
    upload_paths = [Path(output)]
    if infojson:
        upload_paths.append(Path(infojson))

    for path in upload_paths:
        if not path.exists() or not path.is_file():
            logger.warning("上传前未找到文件，跳过: {}", path)
            continue
        logger.info("开始上传文件: {}", path)
        uploader.upload(str(path), target)


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
        upload_task = asyncio.create_task(
            asyncio.to_thread(
                _upload_recording_outputs,
                result.output,
                result.infojson,
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


async def run_watchers(config: AppConfig, *, streams_path: str) -> int:
    app_logger = get_logger(component="scheduler")
    timeout = aiohttp.ClientTimeout(
        total=None,
        connect=config.request_timeout_seconds,
        sock_read=config.request_timeout_seconds,
    )
    connector = aiohttp.TCPConnector(limit=max(len(config.streams) * 4, 64))

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        watchers: dict[StreamTarget, tuple[asyncio.Event, asyncio.Task[None]]] = {}
        current_targets = set(config.streams)

        def _on_watcher_done(target: StreamTarget, task: asyncio.Task[None]) -> None:
            watchers.pop(target, None)
            if task.cancelled():
                return
            try:
                task.result()
            except Exception:
                app_logger.bind(provider=target.provider, streamer=target.streamer).exception("watcher 异常退出")

        async def _start_watcher(target: StreamTarget, *, required: bool) -> None:
            try:
                provider_client = create_provider(
                    target.provider,
                    session=session,
                    timeout_seconds=config.request_timeout_seconds,
                    retries=config.request_retries,
                )
            except Exception as exc:
                if required:
                    supported = ", ".join(supported_providers())
                    raise ValueError(
                        f"provider 初始化失败: {target.provider} ({exc}); 支持: {supported}"
                    ) from exc
                app_logger.warning("跳过无效目标(初始化失败): {} / {} ({})", target.provider, target.streamer, exc)
                return

            stop_event = asyncio.Event()
            task = asyncio.create_task(_monitor_target(config, target, provider_client, stop_event))
            task.add_done_callback(lambda t, _target=target: _on_watcher_done(_target, t))
            watchers[target] = (stop_event, task)
            app_logger.info("注册监听目标: {} / {}", target.provider, target.streamer)

        async def _stop_watcher(target: StreamTarget) -> None:
            item = watchers.pop(target, None)
            if item is None:
                return
            stop_event, task = item
            stop_event.set()
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
            app_logger.info("取消监听目标: {} / {}", target.provider, target.streamer)

        for target in config.streams:
            await _start_watcher(target, required=True)

        last_mtime: float | None = None
        if os.path.exists(streams_path):
            with contextlib.suppress(OSError):
                last_mtime = os.path.getmtime(streams_path)

        async def _reload_loop() -> None:
            nonlocal current_targets, last_mtime
            poll_seconds = 2.0
            while True:
                await asyncio.sleep(poll_seconds)
                try:
                    mtime = os.path.getmtime(streams_path)
                except OSError:
                    continue
                if last_mtime is not None and mtime == last_mtime:
                    continue
                last_mtime = mtime

                from myrecorder.config_loader import load_stream_targets

                try:
                    updated_list = load_stream_targets(
                        streams_path,
                        config.interval_seconds,
                        allow_empty=True,
                    )
                    updated_targets = set(updated_list)
                    if not updated_targets and current_targets:
                        await asyncio.sleep(0.5)
                        updated_list = load_stream_targets(
                            streams_path,
                            config.interval_seconds,
                            allow_empty=True,
                        )
                        updated_targets = set(updated_list)
                except Exception as exc:
                    app_logger.warning("streams.yaml 热加载失败: {}", exc)
                    continue

                to_remove = current_targets - updated_targets
                to_add = updated_targets - current_targets
                if not to_remove and not to_add:
                    continue

                app_logger.info("streams.yaml 更新: +{} -{}", len(to_add), len(to_remove))
                for target in to_remove:
                    await _stop_watcher(target)
                for target in to_add:
                    await _start_watcher(target, required=False)
                current_targets = updated_targets

        reload_task = asyncio.create_task(_reload_loop())
        try:
            await reload_task
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            reload_task.cancel()
            with contextlib.suppress(BaseException):
                await reload_task
            for target in list(watchers.keys()):
                await _stop_watcher(target)
    return 0
