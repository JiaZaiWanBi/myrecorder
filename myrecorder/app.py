from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from .providers import resolve_provider
    from .services import run_watchers
except ImportError:
    from providers import resolve_provider
    from services import run_watchers


@dataclass(frozen=True)
class StreamTarget:
    provider: str
    streamer: str
    channel_url: str
    poll_interval_seconds: int
    wait_for_video: str | None


@dataclass(frozen=True)
class AppConfig:
    output_dir: Path
    poll_interval_seconds: int
    request_timeout_seconds: int
    request_retries: int
    ytdlp_format: str | None
    live_from_start: bool
    write_info_json: bool
    ytdlp_extra_args: list[str]
    hls_use_mpegts: bool
    default_wait_for_video: str | None
    streams: list[StreamTarget]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NicoChannel/FC2 直播监听下载器")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件")
    parser.add_argument("-s", "--streams", default="streams.yaml", help="主播列表")
    parser.add_argument("--log-level", default="INFO", help="日志等级")
    return parser.parse_args(argv)


def _configure_third_party_logging() -> None:
    # Avoid debug spam from yt_dlp internals and transport stacks.
    noisy_loggers = (
        "websockets",
        "websockets.client",
        "yt_dlp",
        "urllib3",
        "aiohttp",
    )
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须是 YAML 对象")
    return data


def _guess_streamer_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or "unknown_streamer"


def _normalize_stream_item(item: Any, default_poll: int, default_wait: str | None) -> StreamTarget:
    if isinstance(item, str):
        url = item.strip()
        provider = resolve_provider(None, url)
        return StreamTarget(
            provider=provider,
            streamer=_guess_streamer_from_url(url),
            channel_url=url,
            poll_interval_seconds=default_poll,
            wait_for_video=default_wait,
        )

    if not isinstance(item, dict):
        raise ValueError(f"streams 项必须是字符串或对象，收到: {item!r}")

    url = str(item.get("channel_url") or item.get("url") or "").strip()
    if not url:
        raise ValueError(f"stream 项缺少 channel_url/url: {item!r}")

    provider_input = item.get("provider")
    provider = resolve_provider(str(provider_input) if provider_input is not None else None, url)

    streamer = str(item.get("streamer") or _guess_streamer_from_url(url)).strip()
    poll = max(int(item.get("poll_interval_seconds") or default_poll), 3)

    wait_for_video = item.get("wait_for_video", default_wait)
    wait_for_video = str(wait_for_video).strip() if wait_for_video is not None else None
    if wait_for_video == "":
        wait_for_video = None

    return StreamTarget(
        provider=provider,
        streamer=streamer,
        channel_url=url,
        poll_interval_seconds=poll,
        wait_for_video=wait_for_video,
    )


def load_config(config_path: str, streams_path: str) -> AppConfig:
    cfg = _load_yaml(config_path)
    stream_cfg = _load_yaml(streams_path)

    service = cfg.get("service") or {}
    if not isinstance(service, dict):
        raise ValueError("config.yaml 的 service 必须是对象")

    default_poll = max(int(service.get("poll_interval_seconds", 20)), 3)
    default_wait = service.get("wait_for_video")
    default_wait = str(default_wait).strip() if default_wait is not None else None
    if default_wait == "":
        default_wait = None

    streams_raw = stream_cfg.get("streams") or []
    if not isinstance(streams_raw, list) or not streams_raw:
        raise ValueError("streams.yaml 需要至少一个 streams 项")
    streams = [_normalize_stream_item(item, default_poll, default_wait) for item in streams_raw]

    return AppConfig(
        output_dir=Path(str(service.get("output_dir", "./recordings"))),
        poll_interval_seconds=default_poll,
        request_timeout_seconds=max(int(service.get("request_timeout_seconds", 8)), 3),
        request_retries=max(int(service.get("request_retries", 3)), 0),
        ytdlp_format=(str(service.get("ytdlp_format")).strip() if service.get("ytdlp_format") is not None else None),
        live_from_start=bool(service.get("live_from_start", True)),
        write_info_json=bool(service.get("write_info_json", True)),
        ytdlp_extra_args=[str(x) for x in (service.get("ytdlp_extra_args") or [])],
        hls_use_mpegts=bool(service.get("hls_use_mpegts", True)),
        default_wait_for_video=default_wait,
        streams=streams,
    )


async def _async_main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _configure_third_party_logging()
    config = load_config(args.config, args.streams)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    return await run_watchers(config)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"错误: {exc}")
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
