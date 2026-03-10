from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import aiohttp

from myrecorder.models import DownloaderTask, ProviderTask, StreamTarget, UploaderTask


ProviderFactory = Callable[..., ProviderTask]
DownloaderFactory = Callable[..., DownloaderTask]
UploaderFactory = Callable[..., UploaderTask]


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    factory: ProviderFactory
    available_downloaders: tuple[str, ...]
    default_downloader: str | None
    default_workflow: tuple[str, ...]


@dataclass(frozen=True)
class DownloaderDefinition:
    name: str
    factory: DownloaderFactory


@dataclass(frozen=True)
class UploaderDefinition:
    name: str
    factory: UploaderFactory


def _build_fc2_provider(*, session: aiohttp.ClientSession, timeout_seconds: int, retries: int) -> ProviderTask:
    from myrecorder.providers.fc2 import FC2Provider

    return FC2Provider(session=session, timeout_seconds=timeout_seconds, retries=retries)


def _build_nicochannel_provider(*, session: aiohttp.ClientSession, timeout_seconds: int, retries: int) -> ProviderTask:
    from myrecorder.providers.nicochannel import NicoChannelProvider

    return NicoChannelProvider(session=session, timeout_seconds=timeout_seconds, retries=retries)


def _build_ytdlp_downloader() -> DownloaderTask:
    from myrecorder.tasks.downloaders.ytdlp import YtDlpDownloadTask

    return YtDlpDownloadTask()


def _build_webdav_uploader() -> UploaderTask:
    from myrecorder.tasks.uploaders.webdav import WebDavUploadTask

    return WebDavUploadTask()


PROVIDER_REGISTRY: dict[str, ProviderDefinition] = {
    "fc2": ProviderDefinition(
        name="fc2",
        factory=_build_fc2_provider,
        available_downloaders=("yt_dlp",),
        default_downloader="yt_dlp",
        default_workflow=("download", "upload"),
    ),
    "nicochannel": ProviderDefinition(
        name="nicochannel",
        factory=_build_nicochannel_provider,
        available_downloaders=("yt_dlp",),
        default_downloader="yt_dlp",
        default_workflow=("download", "upload"),
    ),
}


DOWNLOADER_REGISTRY: dict[str, DownloaderDefinition] = {
    "yt_dlp": DownloaderDefinition(name="yt_dlp", factory=_build_ytdlp_downloader),
}


UPLOADER_REGISTRY: dict[str, UploaderDefinition] = {
    "webdav": UploaderDefinition(name="webdav", factory=_build_webdav_uploader),
}


def get_provider_definition(name: str) -> ProviderDefinition:
    normalized_name = name.strip().lower()
    try:
        return PROVIDER_REGISTRY[normalized_name]
    except KeyError as exc:
        raise ValueError(f"unsupported provider: {name}") from exc


def create_provider_task(
    name: str,
    *,
    session: aiohttp.ClientSession,
    timeout_seconds: int,
    retries: int,
) -> ProviderTask:
    definition = get_provider_definition(name)
    return definition.factory(
        session=session,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )


def create_downloader_task(name: str) -> DownloaderTask:
    normalized_name = name.strip().lower()
    try:
        definition = DOWNLOADER_REGISTRY[normalized_name]
    except KeyError as exc:
        raise ValueError(f"unsupported downloader: {name}") from exc
    return definition.factory()


def create_uploader_task(name: str) -> UploaderTask:
    normalized_name = name.strip().lower()
    try:
        definition = UPLOADER_REGISTRY[normalized_name]
    except KeyError as exc:
        raise ValueError(f"unsupported uploader: {name}") from exc
    return definition.factory()


def supported_providers() -> tuple[str, ...]:
    return tuple(PROVIDER_REGISTRY.keys())


def supported_downloaders() -> tuple[str, ...]:
    return tuple(DOWNLOADER_REGISTRY.keys())


def supported_uploaders() -> tuple[str, ...]:
    return tuple(UPLOADER_REGISTRY.keys())


def resolve_downloader_name(target: StreamTarget, provider_name: str) -> str:
    definition = get_provider_definition(provider_name)
    if target.downloader:
        downloader_name = target.downloader.strip().lower()
        if downloader_name not in definition.available_downloaders:
            allowed = ", ".join(definition.available_downloaders)
            raise ValueError(f"provider {provider_name} does not support downloader {downloader_name}; allowed: {allowed}")
        return downloader_name
    if definition.default_downloader is None:
        raise ValueError(f"provider {provider_name} has no default downloader")
    return definition.default_downloader
