from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from .config import ServiceConfig
from .models import LiveInfo, TargetConfig, new_session_id
from .storage import MetadataStore

logger = logging.getLogger(__name__)


def _safe_filename(value: str, max_len: int = 80) -> str:
    value = value.strip()
    if not value:
        return "unknown"
    value = re.sub(r"[^\w\-\.]+", "_", value)
    return value[:max_len].strip("_") or "unknown"


@dataclass(slots=True)
class SessionResult:
    target_id: str
    session_id: str
    exit_code: int


class RecorderManager:
    def __init__(
        self,
        cfg: ServiceConfig,
        store: MetadataStore,
        on_session_end: Callable[[SessionResult], Awaitable[None]],
    ) -> None:
        self.cfg = cfg
        self.store = store
        self.on_session_end = on_session_end
        self._record_sem = asyncio.Semaphore(cfg.recorder_concurrency)
        self._task_lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[int]] = {}
        self._session_ids: dict[str, str] = {}
        self._procs: dict[str, asyncio.subprocess.Process] = {}

    async def start_recording(self, target: TargetConfig, info: LiveInfo) -> bool:
        async with self._task_lock:
            if target.id in self._tasks:
                return False
            session_id = new_session_id()
            await self.store.create_session(session_id=session_id, target=target, info=info, output_format=self.cfg.output_format)
            task = asyncio.create_task(
                self._record_task(target=target, info=info, session_id=session_id),
                name=f"record-{target.id}",
            )
            self._tasks[target.id] = task
            self._session_ids[target.id] = session_id
            task.add_done_callback(
                lambda t, target_id=target.id, sid=session_id: asyncio.create_task(
                    self._on_task_done(target_id, sid, t)
                )
            )
            return True

    async def stop_all(self) -> None:
        for target_id, proc in list(self._procs.items()):
            if proc.returncode is None:
                logger.info("terminating recorder process target=%s", target_id)
                proc.terminate()

        tasks = list(self._tasks.values())
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=10)
            if pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        for target_id, proc in list(self._procs.items()):
            if proc.returncode is None:
                proc.kill()

    async def _record_task(self, target: TargetConfig, info: LiveInfo, session_id: str) -> int:
        output_path = self._build_output_path(target, info, session_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path = self._build_recorder_log_path(target, session_id)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)

        await self.store.mark_session_recording(session_id=session_id, output_path=str(output_path))

        async with self._record_sem:
            if not info.m3u8_url:
                return 2

            cmd = self._build_streamlink_cmd(info.m3u8_url, output_path)
            logger.info("start streamlink target=%s session=%s", target.id, session_id)
            stderr_fp = stderr_path.open("ab")
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=stderr_fp,
                )
            except FileNotFoundError:
                stderr_fp.close()
                return 127
            except Exception as exc:
                stderr_fp.close()
                logger.exception("spawn streamlink failed target=%s session=%s: %s", target.id, session_id, exc)
                return 3

            self._procs[target.id] = proc
            try:
                rc = await proc.wait()
            finally:
                stderr_fp.close()
                self._procs.pop(target.id, None)
            return int(rc)

    async def _on_task_done(self, target_id: str, session_id: str, task: asyncio.Task[int]) -> None:
        self._tasks.pop(target_id, None)
        self._session_ids.pop(target_id, None)

        try:
            exit_code = task.result()
        except asyncio.CancelledError:
            exit_code = -2
        except Exception as exc:
            exit_code = -1
            logger.exception("record task crashed target=%s: %s", target_id, exc)

        status = "finished" if exit_code == 0 else "error"
        await self.store.finish_session(session_id=session_id, exit_code=exit_code, status=status)
        await self.on_session_end(SessionResult(target_id=target_id, session_id=session_id, exit_code=exit_code))

    def _build_output_path(self, target: TargetConfig, info: LiveInfo, session_id: str) -> Path:
        now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        streamer = _safe_filename(info.streamer or target.id)
        title = _safe_filename(info.title or "live")
        suffix = ".ts" if self.cfg.output_format == "ts" else ".mp4"

        return (
            self.cfg.output_dir_path
            / target.provider
            / streamer
            / f"{now}_{title}_{session_id[:8]}{suffix}"
        )

    def _build_streamlink_cmd(self, stream_url: str, output_path: Path) -> list[str]:
        quality = str(self.cfg.streamlink_quality or "best")
        cmd = [
            self.cfg.streamlink_path,
            *self.cfg.streamlink_extra_args,
            stream_url,
            quality,
            "-o",
            str(output_path),
            "--force",
        ]
        return cmd

    def _build_recorder_log_path(self, target: TargetConfig, session_id: str) -> Path:
        return self.cfg.streamlink_log_dir_path / target.provider / f"{target.id}_{session_id[:8]}.log"
