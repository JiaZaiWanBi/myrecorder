from __future__ import annotations

import asyncio
import contextlib
import os
import threading
from dataclasses import dataclass

import aiohttp
import yt_dlp

from myrecorder.log import get_logger
from myrecorder.models import AppConfig, LiveStatus, StreamTarget, TaskContext, WorkflowState
from myrecorder.pipeline import PipelineResult, build_pipeline, resolve_workflow_steps
from myrecorder.providers import create_provider, supported_providers


async def _execute_pipeline(
    config: AppConfig,
    target: StreamTarget,
    session: aiohttp.ClientSession,
    logger: object,
    live_status: LiveStatus,
    stop_flag: threading.Event,
) -> PipelineResult:
    pipeline = build_pipeline(config, target)
    context = TaskContext(
        target=target,
        logger=logger,
        session=session,
        shared={"stop_flag": stop_flag},
    )
    state = WorkflowState(live_status=live_status)
    return await pipeline.run(context, state)


@dataclass
class WatcherRuntime:
    config: AppConfig
    target: StreamTarget
    session: aiohttp.ClientSession
    stop_event: asyncio.Event

    def __post_init__(self) -> None:
        self.logger = get_logger(component="watcher", provider=self.target.provider, streamer=self.target.streamer)
        self.running_task: asyncio.Task[PipelineResult] | None = None
        self.running_stop_flag: threading.Event | None = None
        self.pipeline_ready = asyncio.Event()
        self.pipeline_ready.set()
        self.next_run_at = 0.0
        self.loop = asyncio.get_running_loop()

    def _log_pipeline_result(self, result: PipelineResult) -> None:
        live_status = result.state.live_status
        download = result.state.data.get("download")

        self.logger.info("检测到开播: {} | title={}", live_status.live_url, live_status.title or "无标题")

        if isinstance(download, dict):
            self.logger.info("下载任务结束，code={}", download.get("code"))

        self.logger.info(
            "任务流结束: {}",
            " -> ".join(result.completed_tasks) or "empty",
        )

    def _on_pipeline_done(self, task: asyncio.Task[PipelineResult]) -> None:
        try:
            result = task.result()
            self._log_pipeline_result(result)
        except asyncio.CancelledError:
            self.logger.info("任务流已取消")
        except yt_dlp.utils.DownloadCancelled:
            self.logger.info("下载任务已取消")
        except Exception:
            self.logger.exception("任务流出现未知错误")
        self.running_task = None
        self.running_stop_flag = None
        self.next_run_at = self.loop.time() + self.target.interval_seconds
        self.pipeline_ready.set()

    def start_pipeline(self, live_status: LiveStatus) -> None:
        self.running_stop_flag = threading.Event()
        self.pipeline_ready.clear()
        self.logger.info("启动任务流: {}", " -> ".join(resolve_workflow_steps(self.config, self.target)))
        self.running_task = asyncio.create_task(
            _execute_pipeline(
                self.config,
                self.target,
                self.session,
                self.logger,
                live_status,
                self.running_stop_flag,
            )
        )
        self.running_task.add_done_callback(self._on_pipeline_done)

    async def check_live(self) -> LiveStatus | None:
        provider = create_provider(
            self.target.provider,
            session=self.session,
            timeout_seconds=self.config.request_timeout_seconds,
            retries=self.config.request_retries,
        )
        try:
            return await provider.check_live(self.target.channel_url)
        except Exception as exc:
            self.logger.warning("开播检测失败: {}", exc)
            self.next_run_at = self.loop.time() + self.target.interval_seconds
            return None

    async def wait_until_ready(self) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.pipeline_ready.wait(), timeout=2)

    async def shutdown(self) -> None:
        active_pipeline = self.running_task
        if self.running_stop_flag is not None:
            self.running_stop_flag.set()
        if active_pipeline is not None:
            with contextlib.suppress(BaseException):
                await asyncio.shield(asyncio.wait_for(active_pipeline, timeout=10))
            with contextlib.suppress(BaseException):
                await asyncio.shield(asyncio.wait_for(self.pipeline_ready.wait(), timeout=10))

    async def run(self) -> None:
        try:
            while not self.stop_event.is_set():
                if self.running_task is not None:
                    await self.wait_until_ready()
                    continue

                delay = self.next_run_at - self.loop.time()
                if delay > 0:
                    await asyncio.sleep(min(delay, 2.0))
                    continue

                live_status = await self.check_live()
                if live_status is None:
                    continue
                if not live_status.is_live:
                    self.logger.debug("未开播，{} 秒后重试", self.target.interval_seconds)
                    self.next_run_at = self.loop.time() + self.target.interval_seconds
                    continue

                self.start_pipeline(live_status)
                await asyncio.sleep(0.2)
        finally:
            await self.shutdown()


async def _validate_target(config: AppConfig, target: StreamTarget, session: aiohttp.ClientSession) -> None:
    create_provider(
        target.provider,
        session=session,
        timeout_seconds=config.request_timeout_seconds,
        retries=config.request_retries,
    )
    build_pipeline(config, target)


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
                await _validate_target(config, target, session)
            except Exception as exc:
                if required:
                    supported = ", ".join(supported_providers())
                    raise ValueError(
                        f"目标初始化失败: {target.provider} / {target.streamer} ({exc}); 支持 provider: {supported}"
                    ) from exc
                app_logger.warning("跳过无效目标(初始化失败): {} / {} ({})", target.provider, target.streamer, exc)
                return

            stop_event = asyncio.Event()
            runtime = WatcherRuntime(config=config, target=target, session=session, stop_event=stop_event)
            task = asyncio.create_task(runtime.run())
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

                from myrecorder.config import load_stream_targets

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
