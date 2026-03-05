from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session_id() -> str:
    return uuid4().hex


@dataclass(slots=True)
class TargetConfig:
    id: str
    provider: str
    check_interval_seconds: int = 15
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LiveInfo:
    is_live: bool
    m3u8_url: str | None = None
    title: str | None = None
    streamer: str | None = None
    live_start_time: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TargetRuntimeState:
    inflight: bool = False
    is_recording: bool = False
    next_check_at: float = 0.0
    consecutive_failures: int = 0
