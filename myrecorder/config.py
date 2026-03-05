from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .models import TargetConfig


@dataclass(slots=True)
class ServiceConfig:
    poller_concurrency: int = 200
    recorder_concurrency: int = 40
    scheduler_tick_seconds: float = 1.0
    failure_backoff_base_seconds: int = 5
    failure_backoff_max_seconds: int = 300
    output_dir: str = "./recordings"
    metadata_db: str = "./data/metadata.db"
    output_format: str = "ts"
    streamlink_path: str = "streamlink"
    streamlink_quality: str = "best"
    streamlink_log_dir: str = "./logs/streamlink"
    http_timeout_seconds: int = 5
    http_max_retries: int = 3
    user_agent: str = "myrecorder/0.1"
    streamlink_extra_args: list[str] = field(default_factory=list)
    default_check_interval_seconds: int = 15

    @property
    def output_dir_path(self) -> Path:
        return Path(self.output_dir).resolve()

    @property
    def metadata_db_path(self) -> Path:
        return Path(self.metadata_db).resolve()

    @property
    def streamlink_log_dir_path(self) -> Path:
        return Path(self.streamlink_log_dir).resolve()


@dataclass(slots=True)
class AppConfig:
    service: ServiceConfig
    targets: list[TargetConfig]


@dataclass(slots=True)
class ProvidersDefaults:
    check_interval_seconds: int | None = None
    base_quality: str = "best"
    base_timeout: int = 5
    base_retries: int = 3
    direct_m3u8_always_live: bool = True
    provider_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge_service(service_data: dict[str, Any] | None) -> ServiceConfig:
    service_data = service_data or {}
    recorder_concurrency = service_data.get("recorder_concurrency", service_data.get("ffmpeg_concurrency", 40))
    return ServiceConfig(
        poller_concurrency=int(service_data.get("poller_concurrency", 200)),
        recorder_concurrency=int(recorder_concurrency),
        scheduler_tick_seconds=float(service_data.get("scheduler_tick_seconds", 1.0)),
        failure_backoff_base_seconds=int(service_data.get("failure_backoff_base_seconds", 5)),
        failure_backoff_max_seconds=int(service_data.get("failure_backoff_max_seconds", 300)),
        output_dir=str(service_data.get("output_dir", "./recordings")),
        metadata_db=str(service_data.get("metadata_db", "./data/metadata.db")),
        output_format=str(service_data.get("output_format", "ts")).lower(),
        streamlink_path=str(service_data.get("streamlink_path", "streamlink")),
        streamlink_quality=str(service_data.get("streamlink_quality", "best")),
        streamlink_log_dir=str(service_data.get("streamlink_log_dir", "./logs/streamlink")),
        http_timeout_seconds=int(service_data.get("http_timeout_seconds", 5)),
        http_max_retries=int(service_data.get("http_max_retries", 3)),
        user_agent=str(service_data.get("user_agent", "myrecorder/0.1")),
        streamlink_extra_args=[str(x) for x in service_data.get("streamlink_extra_args", [])],
        default_check_interval_seconds=int(service_data.get("default_check_interval_seconds", 15)),
    )


def _parse_providers_defaults(data: dict[str, Any] | None) -> ProvidersDefaults:
    data = data or {}
    base = dict(data.get("base", {}) or {})
    provider_overrides = dict(data.get("providers", {}) or {})
    direct = dict(provider_overrides.get("direct_m3u8", {}) or {})
    return ProvidersDefaults(
        check_interval_seconds=(
            int(data["check_interval_seconds"]) if "check_interval_seconds" in data else None
        ),
        base_quality=str(base.get("quality", "best")),
        base_timeout=int(base.get("timeout", 5)),
        base_retries=int(base.get("retries", 3)),
        direct_m3u8_always_live=bool(direct.get("always_live", True)),
        provider_overrides=provider_overrides,
    )


def _provider_setting(defaults: ProvidersDefaults, provider: str, key: str, fallback: Any) -> Any:
    provider_cfg = defaults.provider_overrides.get(provider)
    if isinstance(provider_cfg, dict) and key in provider_cfg:
        return provider_cfg[key]
    return fallback


def _parse_targets(targets_data: list[dict[str, Any]] | None) -> list[TargetConfig]:
    targets: list[TargetConfig] = []
    for item in targets_data or []:
        provider = item.get("providers", item.get("provider"))
        if not provider:
            raise ValueError(f"target missing 'providers'/'provider': {item}")
        targets.append(
            TargetConfig(
                id=str(item["id"]),
                provider=str(provider),
                check_interval_seconds=int(item.get("check_interval_seconds", 15)),
                extra=dict(item.get("extra", {})),
            )
        )
    return targets


def _streamer_from_url(url: str, fallback: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if path:
        token = path.split("/")[-1]
        if token:
            return token
    if parsed.netloc:
        return parsed.netloc.split(":")[0].replace(".", "_")
    return fallback


def _auto_id(url: str, provider: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    streamer = _streamer_from_url(url, "stream")
    streamer = re.sub(r"[^a-zA-Z0-9_]+", "_", streamer).strip("_") or "stream"
    return f"{provider}_{streamer}_{digest}"


def _detect_provider(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "nicochannel.jp" in host:
        return "nicochannel"
    if ".m3u8" in path:
        return "direct_m3u8"
    raise ValueError(f"cannot auto-detect providers for url={url}")


def _parse_stream_urls(streams_data: dict[str, Any], path: Path) -> list[str]:
    raw = streams_data.get("streams")
    if raw is None:
        raise ValueError(f"streams file missing 'streams' key: {path}")
    if not isinstance(raw, list):
        raise ValueError(f"'streams' must be a list in {path}")
    urls: list[str] = []
    for item in raw:
        if isinstance(item, str):
            url = item.strip()
        elif isinstance(item, dict):
            url = str(item.get("url", "")).strip()
        else:
            url = ""
        if url:
            urls.append(url)
    return urls


def _build_auto_target(url: str, defaults: ProvidersDefaults, service: ServiceConfig) -> TargetConfig:
    provider = _detect_provider(url)
    target_id = _auto_id(url, provider=provider)
    interval = int(defaults.check_interval_seconds or service.default_check_interval_seconds)
    interval = max(interval, 1)

    if provider == "direct_m3u8":
        return TargetConfig(
            id=target_id,
            provider=provider,
            check_interval_seconds=interval,
            extra={
                "m3u8_url": url,
                "always_live": defaults.direct_m3u8_always_live,
                "streamer": _streamer_from_url(url, target_id),
                "title": target_id,
            },
        )

    if provider == "nicochannel":
        return TargetConfig(
            id=target_id,
            provider=provider,
            check_interval_seconds=interval,
            extra={
                "channel_url": url,
                "quality": str(_provider_setting(defaults, "nicochannel", "quality", defaults.base_quality)),
                "timeout": int(_provider_setting(defaults, "nicochannel", "timeout", defaults.base_timeout)),
                "retries": int(_provider_setting(defaults, "nicochannel", "retries", defaults.base_retries)),
                "streamer": _streamer_from_url(url, target_id),
            },
        )

    raise ValueError(f"unsupported providers '{provider}'")


def load_config(path: str | Path, streams_path: str | Path | None = None) -> AppConfig:
    config_path = Path(path).resolve()
    data = _load_yaml(config_path)

    service = _merge_service(data.get("service"))
    defaults_data = data.get("providers_defaults") or data.get("provider_defaults")
    defaults = _parse_providers_defaults(defaults_data)
    manual_targets = _parse_targets(data.get("targets"))

    stream_file = Path(streams_path) if streams_path else Path("./streams.yaml")
    if not stream_file.is_absolute():
        stream_file = (config_path.parent / stream_file).resolve()

    auto_targets: list[TargetConfig] = []
    if stream_file.exists():
        streams_data = _load_yaml(stream_file)
        urls = _parse_stream_urls(streams_data, stream_file)
        for url in urls:
            auto_targets.append(_build_auto_target(url, defaults=defaults, service=service))

    targets = manual_targets + auto_targets
    if not targets:
        raise ValueError("no targets configured. add targets in config.yaml or streams in streams.yaml")
    if service.output_format != "ts":
        raise ValueError("service.output_format must be 'ts' when using streamlink recorder.")
    return AppConfig(service=service, targets=targets)
