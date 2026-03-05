from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from .models import LiveInfo, TargetConfig, utc_now_iso

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WriteOp:
    sql: str
    params: tuple[Any, ...]


class MetadataStore:
    def __init__(self, db_path: Path, batch_size: int = 200) -> None:
        self.db_path = db_path
        self.batch_size = batch_size
        self._conn: aiosqlite.Connection | None = None
        self._queue: asyncio.Queue[WriteOp | None] = asyncio.Queue(maxsize=20_000)
        self._writer_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._conn.execute("PRAGMA temp_store=MEMORY;")
        await self._create_schema()
        self._writer_task = asyncio.create_task(self._writer_loop(), name="metadata-writer")

    async def close(self) -> None:
        if self._writer_task is None:
            return
        await self._queue.put(None)
        await self._writer_task
        self._writer_task = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def upsert_target(self, target: TargetConfig) -> None:
        await self._enqueue(
            """
            INSERT INTO targets(target_id, provider, check_interval_seconds, extra_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(target_id) DO UPDATE SET
                provider=excluded.provider,
                check_interval_seconds=excluded.check_interval_seconds,
                extra_json=excluded.extra_json,
                updated_at=excluded.updated_at;
            """,
            (
                target.id,
                target.provider,
                target.check_interval_seconds,
                json.dumps(target.extra, ensure_ascii=False),
                utc_now_iso(),
            ),
        )

    async def create_session(
        self,
        session_id: str,
        target: TargetConfig,
        info: LiveInfo,
        output_format: str,
    ) -> None:
        await self._enqueue(
            """
            INSERT INTO sessions(
                session_id, target_id, provider, streamer, title, m3u8_url,
                output_path, output_format, live_start_time, started_at,
                ended_at, exit_code, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                session_id,
                target.id,
                target.provider,
                info.streamer,
                info.title,
                info.m3u8_url,
                None,
                output_format,
                info.live_start_time,
                utc_now_iso(),
                None,
                None,
                "queued",
            ),
        )

    async def mark_session_recording(self, session_id: str, output_path: str) -> None:
        await self._enqueue(
            """
            UPDATE sessions
            SET status='recording', output_path=?, started_at=?
            WHERE session_id=?;
            """,
            (output_path, utc_now_iso(), session_id),
        )

    async def finish_session(self, session_id: str, exit_code: int, status: str) -> None:
        await self._enqueue(
            """
            UPDATE sessions
            SET status=?, ended_at=?, exit_code=?
            WHERE session_id=?;
            """,
            (status, utc_now_iso(), exit_code, session_id),
        )

    async def add_event(
        self,
        target_id: str,
        event_type: str,
        payload: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        await self._enqueue(
            """
            INSERT INTO events(created_at, target_id, session_id, event_type, payload_json)
            VALUES (?, ?, ?, ?, ?);
            """,
            (utc_now_iso(), target_id, session_id, event_type, json.dumps(payload, ensure_ascii=False)),
        )

    async def _enqueue(self, sql: str, params: tuple[Any, ...]) -> None:
        await self._queue.put(WriteOp(sql=sql, params=params))

    async def _writer_loop(self) -> None:
        assert self._conn is not None
        pending: list[WriteOp] = []
        while True:
            op = await self._queue.get()
            if op is None:
                if pending:
                    await self._flush(pending)
                    pending.clear()
                break
            pending.append(op)
            while len(pending) < self.batch_size:
                try:
                    op2 = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if op2 is None:
                    await self._flush(pending)
                    pending.clear()
                    return
                pending.append(op2)
            await self._flush(pending)
            pending.clear()

    async def _flush(self, ops: list[WriteOp]) -> None:
        if not ops:
            return
        assert self._conn is not None
        try:
            await self._conn.execute("BEGIN;")
            for op in ops:
                await self._conn.execute(op.sql, op.params)
            await self._conn.commit()
        except Exception:
            logger.exception("metadata flush failed with %d ops", len(ops))
            await self._conn.rollback()

    async def _create_schema(self) -> None:
        assert self._conn is not None
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS targets (
                target_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                check_interval_seconds INTEGER NOT NULL,
                extra_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                target_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                streamer TEXT,
                title TEXT,
                m3u8_url TEXT,
                output_path TEXT,
                output_format TEXT NOT NULL,
                live_start_time TEXT,
                started_at TEXT,
                ended_at TEXT,
                exit_code INTEGER,
                status TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_target ON sessions(target_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                target_id TEXT NOT NULL,
                session_id TEXT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_target ON events(target_id);
            CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
            """
        )
        await self._normalize_schema()
        await self._conn.commit()

    async def _normalize_schema(self) -> None:
        assert self._conn is not None
        await self._ensure_provider_schema_targets()
        await self._ensure_provider_schema_sessions()

    async def _table_has_column(self, table: str, column: str) -> bool:
        assert self._conn is not None
        cur = await self._conn.execute(f"PRAGMA table_info({table});")
        rows = await cur.fetchall()
        await cur.close()
        columns = {str(r[1]) for r in rows}
        return column in columns

    async def _table_columns(self, table: str) -> set[str]:
        assert self._conn is not None
        cur = await self._conn.execute(f"PRAGMA table_info({table});")
        rows = await cur.fetchall()
        await cur.close()
        return {str(r[1]) for r in rows}

    async def _ensure_provider_schema_targets(self) -> None:
        assert self._conn is not None
        columns = await self._table_columns("targets")
        legacy_col = "ad" + "apter"
        if "provider" in columns and legacy_col not in columns:
            return
        await self._conn.execute("DROP TABLE IF EXISTS targets;")
        await self._conn.execute(
            """
            CREATE TABLE targets (
                target_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                check_interval_seconds INTEGER NOT NULL,
                extra_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

    async def _ensure_provider_schema_sessions(self) -> None:
        assert self._conn is not None
        columns = await self._table_columns("sessions")
        legacy_col = "ad" + "apter"
        if "provider" in columns and legacy_col not in columns:
            return
        await self._conn.execute("DROP TABLE IF EXISTS sessions;")
        await self._conn.execute(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                target_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                streamer TEXT,
                title TEXT,
                m3u8_url TEXT,
                output_path TEXT,
                output_format TEXT NOT NULL,
                live_start_time TEXT,
                started_at TEXT,
                ended_at TEXT,
                exit_code INTEGER,
                status TEXT NOT NULL
            );
            """
        )
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_target ON sessions(target_id);")
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);")
