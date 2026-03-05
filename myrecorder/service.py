from __future__ import annotations

import asyncio
import logging

from .provider_registry import build_provider_registry
from .config import AppConfig
from .http_client import HttpClient
from .recorder import RecorderManager, SessionResult
from .scheduler import PollingScheduler
from .storage import MetadataStore

logger = logging.getLogger(__name__)


class RecorderService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._stop_event = asyncio.Event()

        self.store = MetadataStore(config.service.metadata_db_path)
        self.http: HttpClient | None = None
        self.scheduler: PollingScheduler | None = None
        self.recorder: RecorderManager | None = None

    async def start(self) -> None:
        await self.store.start()
        self.http = HttpClient(
            timeout_seconds=self.config.service.http_timeout_seconds,
            max_retries=self.config.service.http_max_retries,
            user_agent=self.config.service.user_agent,
            connection_limit=max(self.config.service.poller_concurrency * 2, 100),
        )
        await self.http.start()

        providers = build_provider_registry()
        for target in self.config.targets:
            if target.provider not in providers:
                raise ValueError(f"target={target.id} uses unknown providers '{target.provider}'")

        async def on_session_end(result: SessionResult) -> None:
            if self.scheduler is not None:
                await self.scheduler.handle_session_end(result)

        self.recorder = RecorderManager(
            cfg=self.config.service,
            store=self.store,
            on_session_end=on_session_end,
        )
        self.scheduler = PollingScheduler(
            cfg=self.config.service,
            targets=self.config.targets,
            providers=providers,
            http=self.http,
            store=self.store,
            recorder=self.recorder,
        )

        await self.scheduler.start()
        logger.info(
            "service started: targets=%d poller_concurrency=%d recorder_concurrency=%d",
            len(self.config.targets),
            self.config.service.poller_concurrency,
            self.config.service.recorder_concurrency,
        )

    async def run_until_stopped(self) -> None:
        await self._stop_event.wait()

    async def stop(self) -> None:
        self._stop_event.set()
        if self.scheduler is not None:
            await self.scheduler.stop()
            self.scheduler = None
        if self.recorder is not None:
            await self.recorder.stop_all()
            self.recorder = None
        if self.http is not None:
            await self.http.close()
            self.http = None
        await self.store.close()
        logger.info("service stopped")
