from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import aiohttp

from myrecorder.models import AppConfig, BaseTask, ProviderTask


ProviderFactory = Callable[..., ProviderTask]
TaskFactory = Callable[[AppConfig], BaseTask]


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    factory: ProviderFactory


@dataclass(frozen=True)
class TaskDefinition:
    name: str
    factory: TaskFactory
    enabled: Callable[[AppConfig], bool] | None = None


def _build_fc2_provider(*, session: aiohttp.ClientSession, timeout_seconds: int, retries: int) -> ProviderTask:
    from myrecorder.providers.fc2 import FC2Provider

    return FC2Provider(session=session, timeout_seconds=timeout_seconds, retries=retries)


def _build_nicochannel_provider(*, session: aiohttp.ClientSession, timeout_seconds: int, retries: int) -> ProviderTask:
    from myrecorder.providers.nicochannel import NicoChannelProvider

    return NicoChannelProvider(session=session, timeout_seconds=timeout_seconds, retries=retries)


def _build_ytdlp_task(config: AppConfig) -> BaseTask:
    from myrecorder.tasks.downloaders.ytdlp import YtDlpDownloadTask

    return YtDlpDownloadTask(config=config)


def _build_webdav_task(config: AppConfig) -> BaseTask:
    from myrecorder.tasks.uploaders.webdav import WebDavUploadTask

    return WebDavUploadTask(config=config.webdav)


PROVIDER_REGISTRY: dict[str, ProviderDefinition] = {
    "fc2": ProviderDefinition(
        name="fc2",
        factory=_build_fc2_provider,
    ),
    "nicochannel": ProviderDefinition(
        name="nicochannel",
        factory=_build_nicochannel_provider,
    ),
}


TASK_REGISTRY: dict[str, TaskDefinition] = {
    "yt_dlp": TaskDefinition(name="yt_dlp", factory=_build_ytdlp_task),
    "webdav": TaskDefinition(
        name="webdav",
        factory=_build_webdav_task,
        enabled=lambda config: config.webdav is not None,
    ),
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


def is_task_enabled(name: str, config: AppConfig) -> bool:
    normalized_name = name.strip().lower()
    try:
        definition = TASK_REGISTRY[normalized_name]
    except KeyError as exc:
        raise ValueError(f"unsupported task: {name}") from exc
    if definition.enabled is None:
        return True
    return definition.enabled(config)


def create_task(name: str, config: AppConfig) -> BaseTask:
    normalized_name = name.strip().lower()
    try:
        definition = TASK_REGISTRY[normalized_name]
    except KeyError as exc:
        raise ValueError(f"unsupported task: {name}") from exc
    return definition.factory(config)


def supported_providers() -> tuple[str, ...]:
    return tuple(PROVIDER_REGISTRY.keys())


def supported_tasks() -> tuple[str, ...]:
    return tuple(TASK_REGISTRY.keys())
