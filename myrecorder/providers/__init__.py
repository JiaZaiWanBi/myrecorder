from __future__ import annotations

"""Provider identification and lightweight factory entrypoints."""

from typing import Any
from urllib.parse import urlparse

import aiohttp

from myrecorder.models import LiveStatus, StreamProvider
from myrecorder.registry import create_provider_task, get_provider_definition, supported_providers as registry_supported_providers


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
    return create_provider_task(
        provider,
        session=session,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )


def get_provider_downloaders(provider: str) -> tuple[str, ...]:
    return get_provider_definition(provider).available_downloaders


def supported_providers() -> tuple[str, ...]:
    return registry_supported_providers()

