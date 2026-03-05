from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
import yaml

try:
    from .providers.nicochannel import NicoChannelClient, NicoLiveStatus
except ImportError:
    # Allow direct execution: `python myrecorder/app.py`
    from providers.nicochannel import NicoChannelClient, NicoLiveStatus


@dataclass(frozen=True)
class StreamTarget:
    streamer: str
    channel_url: str
    poll_interval_seconds: int


@dataclass(frozen=True)
class AppConfig:
    ytdlp_path: str
    output_dir: Path
    poll_interval_seconds: int
    request_timeout_seconds: int
    request_retries: int
    ytdlp_format: str
    live_from_start: bool
    write_info_json: bool
    ytdlp_extra_args: list[str]
    streams: list[StreamTarget]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NicoChannel 直播监听下载器")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件")
    parser.add_argument("-s", "--streams", default="streams.yaml", help="主播列表")
    parser.add_argument("--log-level", default="INFO", help="日志等级")
    return parser.parse_args(argv)


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须是 YAML 对象")
    return data


def _normalize_stream_item(item: Any, default_poll: int) -> StreamTarget:
    if isinstance(item, str):
        url = item.strip()
        streamer = url.rstrip("/").split("/")[-1] or "unknown_streamer"
        return StreamTarget(streamer=streamer, channel_url=url, poll_interval_seconds=default_poll)
    if not isinstance(item, dict):
        raise ValueError(f"streams 项必须是字符串或对象，收到: {item!r}")
    url = str(item.get("channel_url") or item.get("url") or "").strip()
    if not url:
        raise ValueError(f"stream 项缺少 channel_url/url: {item!r}")
    streamer = str(item.get("streamer") or url.rstrip("/").split("/")[-1] or "unknown_streamer").strip()
    poll = int(item.get("poll_interval_seconds") or default_poll)
    return StreamTarget(streamer=streamer, channel_url=url, poll_interval_seconds=max(poll, 3))


def load_config(config_path: str, streams_path: str) -> AppConfig:
    cfg = _load_yaml(config_path)
    stream_cfg = _load_yaml(streams_path)

    service = cfg.get("service") or {}
    if not isinstance(service, dict):
        raise ValueError("config.yaml 的 service 必须是对象")

    default_poll = int(service.get("poll_interval_seconds", 20))
    streams_raw = stream_cfg.get("streams") or []
    if not isinstance(streams_raw, list) or not streams_raw:
        raise ValueError("streams.yaml 需要至少一个 streams 项")
    streams = [_normalize_stream_item(item, default_poll) for item in streams_raw]

    return AppConfig(
        ytdlp_path=str(service.get("ytdlp_path", "yt-dlp")),
        output_dir=Path(str(service.get("output_dir", "./recordings"))),
        poll_interval_seconds=max(default_poll, 3),
        request_timeout_seconds=max(int(service.get("request_timeout_seconds", 8)), 3),
        request_retries=max(int(service.get("request_retries", 3)), 0),
        ytdlp_format=str(service.get("ytdlp_format", "best")),
        live_from_start=bool(service.get("live_from_start", True)),
        write_info_json=bool(service.get("write_info_json", True)),
        ytdlp_extra_args=[str(x) for x in (service.get("ytdlp_extra_args") or [])],
        streams=streams,
    )


def _build_ytdlp_command(config: AppConfig, target: StreamTarget, status: NicoLiveStatus) -> list[str]:
    out_dir = config.output_dir / target.streamer
    out_template = str(out_dir / "%(upload_date>%Y%m%d)s_%(title).120B_%(id)s.%(ext)s")
    archive_file = str(config.output_dir / ".download-archive.txt")

    cmd = [
        config.ytdlp_path,
        status.live_url,
        "-f",
        config.ytdlp_format,
        "--download-archive",
        archive_file,
        "-o",
        out_template,
    ]
    if config.live_from_start:
        cmd.append("--live-from-start")
    if config.write_info_json:
        cmd.append("--write-info-json")
    cmd.extend(config.ytdlp_extra_args)
    return cmd


async def _monitor_one(
    config: AppConfig,
    target: StreamTarget,
    session: aiohttp.ClientSession,
    stop_event: asyncio.Event,
) -> None:
    logger = logging.getLogger(f"myrecorder.{target.streamer}")
    client = NicoChannelClient(
        session=session,
        timeout_seconds=config.request_timeout_seconds,
        retries=config.request_retries,
    )
    process: asyncio.subprocess.Process | None = None

    while not stop_event.is_set():
        if process is not None:
            code = process.returncode
            if code is None:
                await asyncio.sleep(2)
                continue
            logger.info("yt-dlp 已结束，code=%s", code)
            process = None

        try:
            status = await client.check_live(target.channel_url)
        except Exception as exc:
            logger.warning("开播检测失败: %s", exc)
            await asyncio.sleep(target.poll_interval_seconds)
            continue

        if not status.is_live:
            logger.info("未开播，%ss 后重试", target.poll_interval_seconds)
            await asyncio.sleep(target.poll_interval_seconds)
            continue

        cmd = _build_ytdlp_command(config, target, status)
        logger.info("检测到开播: %s | title=%s", status.live_url, status.title or "N/A")
        logger.info("启动 yt-dlp: %s", shlex.join(cmd))
        (config.output_dir / target.streamer).mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(*cmd)
        await asyncio.sleep(2)

    if process and process.returncode is None:
        process.terminate()
        with contextlib.suppress(ProcessLookupError):
            await asyncio.wait_for(process.wait(), timeout=10)


async def _async_main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config, args.streams)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    timeout = aiohttp.ClientTimeout(total=None, connect=config.request_timeout_seconds, sock_read=config.request_timeout_seconds)
    connector = aiohttp.TCPConnector(limit=max(len(config.streams) * 4, 20))
    stop_event = asyncio.Event()

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        tasks = [asyncio.create_task(_monitor_one(config, target, session, stop_event)) for target in config.streams]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            stop_event.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    return 0


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
