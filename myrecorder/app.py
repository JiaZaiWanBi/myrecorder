from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import yaml

from myrecorder.log import configure_logging, get_logger
from myrecorder.models import AppConfig, StreamTarget, WebDAVConfig
from myrecorder.providers import resolve_provider
from myrecorder.services import run_watchers


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NicoChannel/FC2 直播录制器")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("-s", "--streams", default="streams.yaml", help="直播目标文件路径")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    return parser.parse_args(argv)


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是有效的 YAML 对象")
    return data


def _guess_streamer_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or "unknown_streamer"


def _normalize_stream_item(item: Any, default_interval: int) -> StreamTarget:
    if isinstance(item, str):
        url = item.strip()
        provider = resolve_provider(None, url)
        return StreamTarget(
            provider=provider,
            streamer=_guess_streamer_from_url(url),
            channel_url=url,
            interval_seconds=default_interval,
        )

    if not isinstance(item, dict):
        raise ValueError(f"streams 项必须是字符串或对象: {item!r}")

    url = str(item.get("channel_url") or item.get("url") or "").strip()
    if not url:
        raise ValueError(f"stream 缺少 channel_url/url: {item!r}")

    provider_input = item.get("provider")
    provider = resolve_provider(str(provider_input) if provider_input is not None else None, url)
    streamer = str(item.get("streamer") or _guess_streamer_from_url(url)).strip()
    interval = max(int(item.get("interval_seconds") or default_interval), 3)

    return StreamTarget(
        provider=provider,
        streamer=streamer,
        channel_url=url,
        interval_seconds=interval,
    )


def _parse_webdav_config(cfg: dict[str, Any], service: dict[str, Any]) -> WebDAVConfig | None:
    webdav_cfg = cfg.get("webdav")
    if webdav_cfg is None:
        webdav_cfg = service.get("webdav")
    if webdav_cfg is None:
        return None
    if not isinstance(webdav_cfg, dict):
        raise ValueError("config.yaml 中的 webdav 必须是对象")

    url = str(webdav_cfg.get("url") or "").strip()
    user = str(webdav_cfg.get("user") or "").strip()
    password = str(webdav_cfg.get("pass") or webdav_cfg.get("password") or "").strip()
    if not url or not user or not password:
        raise ValueError("webdav 需要提供 url、user、pass")

    return WebDAVConfig(
        url=url,
        user=user,
        password=password,
        root=str(webdav_cfg.get("root") or "/").strip() or "/",
        rclone_path=str(webdav_cfg.get("rclone_path") or "rclone").strip() or "rclone",
    )


def load_config(config_path: str, streams_path: str) -> AppConfig:
    cfg = _load_yaml(config_path)
    stream_cfg = _load_yaml(streams_path)

    service = cfg.get("service") or {}
    if not isinstance(service, dict):
        raise ValueError("config.yaml 中的 service 必须是对象")

    default_interval = max(int(service.get("interval_seconds", 20)), 3)
    streams_raw = stream_cfg.get("streams") or []
    if not isinstance(streams_raw, list) or not streams_raw:
        raise ValueError("streams.yaml 必须包含非空的 streams 列表")
    streams = [_normalize_stream_item(item, default_interval) for item in streams_raw]

    return AppConfig(
        output_dir=Path(str(service.get("output_dir", "./recordings"))),
        interval_seconds=default_interval,
        request_timeout_seconds=max(int(service.get("request_timeout_seconds", 8)), 3),
        request_retries=max(int(service.get("request_retries", 3)), 0),
        ytdlp_format=(str(service.get("ytdlp_format")).strip() if service.get("ytdlp_format") is not None else None),
        live_from_start=bool(service.get("live_from_start", False)),
        write_info_json=bool(service.get("write_info_json", True)),
        ytdlp_extra_args=[str(x) for x in (service.get("ytdlp_extra_args") or [])],
        hls_use_mpegts=bool(service.get("hls_use_mpegts", True)),
        webdav=_parse_webdav_config(cfg, service),
        streams=streams,
    )


async def _async_main(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)
    config = load_config(args.config, args.streams)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    get_logger(component="app").info(
        "已从 {} 加载 {} 个直播目标",
        args.streams,
        len(config.streams),
    )
    return await run_watchers(config)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        return 0
    except Exception:
        get_logger(component="app").exception("程序运行失败")
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
