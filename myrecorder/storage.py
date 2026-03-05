from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from .models import LiveInfo, TargetConfig, utc_now_iso


@dataclass(slots=True)
class PendingSession:
    provider: str
    title: str | None
    detected_at: str


class MetadataStore:
    """
    Minimal metadata storage.
    One live session -> one row in live_records.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._pending: dict[str, PendingSession] = {}

    async def start(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._create_schema()
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def create_session(
        self,
        session_id: str,
        target: TargetConfig,
        info: LiveInfo,
        output_format: str,
    ) -> None:
        del output_format
        async with self._lock:
            self._pending[session_id] = PendingSession(
                provider=target.provider,
                title=info.title,
                detected_at=utc_now_iso(),
            )

    async def mark_session_recording(self, session_id: str, output_path: str) -> None:
        if self._conn is None:
            raise RuntimeError("MetadataStore not started")

        async with self._lock:
            pending = self._pending.get(session_id)
            if pending is None:
                return
            await self._conn.execute(
                """
                INSERT INTO live_records(recorded_at, title, provider, output_path)
                VALUES (?, ?, ?, ?);
                """,
                (
                    pending.detected_at,
                    pending.title,
                    pending.provider,
                    output_path,
                ),
            )
            await self._conn.commit()

    async def finish_session(self, session_id: str, exit_code: int, status: str) -> None:
        del exit_code, status
        async with self._lock:
            self._pending.pop(session_id, None)

    async def _create_schema(self) -> None:
        assert self._conn is not None
        await self._conn.executescript(
            """
            DROP TABLE IF EXISTS events;
            DROP TABLE IF EXISTS sessions;
            DROP TABLE IF EXISTS targets;

            CREATE TABLE IF NOT EXISTS live_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                title TEXT,
                provider TEXT NOT NULL,
                output_path TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_live_records_recorded_at ON live_records(recorded_at);
            CREATE INDEX IF NOT EXISTS idx_live_records_provider ON live_records(provider);
            """
        )
