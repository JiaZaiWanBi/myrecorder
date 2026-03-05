from __future__ import annotations

from typing import Protocol

from ..http_client import HttpClient
from ..models import LiveInfo, TargetConfig


class StreamProvider(Protocol):
    name: str

    async def check_live(self, target: TargetConfig, http: HttpClient) -> LiveInfo:
        """Check live status and return m3u8 + metadata if live."""
