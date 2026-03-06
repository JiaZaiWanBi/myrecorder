from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import aiohttp


@dataclass(frozen=True)
class LiveStatus:
    is_live: bool
    channel_url: str
    live_url: str = ""
    title: str = ""
    started_at: str = ""


class StreamProvider(Protocol):
    async def check_live(self, channel_url: str) -> LiveStatus:
        ...


def _host_of(url: str) -> str:
    host = urlparse(url.strip()).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def detect_provider_from_url(channel_url: str) -> str:
    host = _host_of(channel_url)
    if host.endswith("nicochannel.jp"):
        return "nicochannel"
    if host.endswith("live.fc2.com"):
        return "fc2"
    raise ValueError(f"cannot infer provider from url: {channel_url}")


def resolve_provider(provider: str | None, channel_url: str) -> str:
    if provider is not None and provider.strip():
        return provider.strip().lower()
    return detect_provider_from_url(channel_url)


def create_provider(
    provider: str,
    *,
    session: aiohttp.ClientSession,
    timeout_seconds: int,
    retries: int,
) -> StreamProvider:
    name = provider.strip().lower()
    if name == "nicochannel":
        from myrecorder.providers.nicochannel import NicoChannelProvider

        return NicoChannelProvider(session=session, timeout_seconds=timeout_seconds, retries=retries)
    if name == "fc2":
        from myrecorder.providers.fc2 import FC2Provider

        return FC2Provider(
            session=session,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )
    raise ValueError(f"unsupported provider: {provider}")


def supported_providers() -> tuple[str, ...]:
    return ("nicochannel", "fc2")

