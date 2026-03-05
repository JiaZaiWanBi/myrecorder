from __future__ import annotations

import asyncio
import logging
import random
import time

from .providers.base import StreamProvider
from .config import ServiceConfig
from .http_client import HttpClient
from .models import TargetConfig, TargetRuntimeState
from .recorder import RecorderManager, SessionResult
from .storage import MetadataStore

logger = logging.getLogger(__name__)


class PollingScheduler:
    def __init__(
        self,
        cfg: ServiceConfig,
        targets: list[TargetConfig],
        providers: dict[str, StreamProvider],
        http: HttpClient,
        store: MetadataStore,
        recorder: RecorderManager,
    ) -> None:
        self.cfg = cfg
        self.targets = targets
        self.providers = providers
        self.http = http
        self.store = store
        self.recorder = recorder

        self._state_lock = asyncio.Lock()
        self._states = {t.id: TargetRuntimeState() for t in targets}
        self._target_by_id = {t.id: t for t in targets}
        self._check_sem = asyncio.Semaphore(cfg.poller_concurrency)
        self._running = False
        self._loop_task: asyncio.Task[None] | None = None
        self._check_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self._running = True
        self._loop_task = asyncio.create_task(self._loop(), name="polling-scheduler")

    async def stop(self) -> None:
        self._running = False
        if self._loop_task is not None:
            await self._loop_task
            self._loop_task = None
        if self._check_tasks:
            for task in list(self._check_tasks):
                task.cancel()
            await asyncio.gather(*self._check_tasks, return_exceptions=True)
            self._check_tasks.clear()

    async def handle_session_end(self, result: SessionResult) -> None:
        target = self._target_by_id.get(result.target_id)
        if target is None:
            return
        async with self._state_lock:
            state = self._states[result.target_id]
            state.is_recording = False
            state.inflight = False
            state.next_check_at = time.monotonic() + min(5, target.check_interval_seconds)

    async def _loop(self) -> None:
        while self._running:
            now = time.monotonic()
            due_targets: list[TargetConfig] = []
            async with self._state_lock:
                for target in self.targets:
                    state = self._states[target.id]
                    if state.inflight or state.is_recording:
                        continue
                    if state.next_check_at <= now:
                        state.inflight = True
                        due_targets.append(target)

            for target in due_targets:
                task = asyncio.create_task(self._run_single_check(target), name=f"check-{target.id}")
                self._check_tasks.add(task)
                task.add_done_callback(self._check_tasks.discard)

            await asyncio.sleep(self.cfg.scheduler_tick_seconds)

    async def _run_single_check(self, target: TargetConfig) -> None:
        async with self._check_sem:
            provider_impl = self.providers.get(target.provider)
            if provider_impl is None:
                await self._mark_check_error(target, RuntimeError(f"providers not found: {target.provider}"))
                return

            logger.debug(
                "check start target=%s providers=%s interval=%ss",
                target.id,
                target.provider,
                target.check_interval_seconds,
            )
            try:
                info = await provider_impl.check_live(target, self.http)
            except Exception as exc:
                await self._mark_check_error(target, exc)
                return

            if not info.is_live:
                async with self._state_lock:
                    st = self._states[target.id]
                    st.consecutive_failures = 0
                    st.inflight = False
                    delay = target.check_interval_seconds + random.uniform(0.1, 1.5)
                    st.next_check_at = time.monotonic() + delay
                logger.debug(
                    "check result target=%s status=offline next_check_in=%.2fs",
                    target.id,
                    delay,
                )
                return

            started = await self.recorder.start_recording(target, info)
            async with self._state_lock:
                st = self._states[target.id]
                st.inflight = False
                st.consecutive_failures = 0
                if started:
                    st.is_recording = True
                    st.next_check_at = time.monotonic() + target.check_interval_seconds
                else:
                    st.next_check_at = time.monotonic() + target.check_interval_seconds + random.uniform(0.1, 1.5)

            logger.debug(
                "check result target=%s status=live started=%s streamer=%s title=%s m3u8=%s",
                target.id,
                started,
                info.streamer,
                info.title,
                info.m3u8_url,
            )

    async def _mark_check_error(self, target: TargetConfig, exc: Exception) -> None:
        async with self._state_lock:
            st = self._states[target.id]
            st.inflight = False
            st.consecutive_failures += 1
            backoff = min(
                self.cfg.failure_backoff_base_seconds * (2 ** max(st.consecutive_failures - 1, 0)),
                self.cfg.failure_backoff_max_seconds,
            )
            st.next_check_at = time.monotonic() + backoff + random.uniform(0.1, 1.5)
        logger.warning("check error target=%s: %s", target.id, exc)
        logger.debug("check error detail target=%s", target.id, exc_info=True)
