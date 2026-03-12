from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from streamlink import Streamlink

from myrecorder.models import TaskContext
from myrecorder.registry import Registry
from myrecorder.tasks.base import BaseTask


def _build_default_filename(title: str | None, stream_name: str) -> str:
    safe_title = (title or "stream").replace("/", "_").replace("\\", "_")
    return f"{safe_title}-{stream_name}.ts"


@Registry.register_task("streamlink")
class StreamlinkDownloadTask(BaseTask):
    name = "streamlink"

    async def run(self, context: TaskContext, payload: dict[str, Any]) -> None:
        download_url = context.live_status.m3u8_url or context.live_status.live_url
        if not download_url:
            raise ValueError("live_status does not contain live_url or m3u8_url")

        stop_flag = context.shared.get("stop_flag")
        if not isinstance(stop_flag, threading.Event):
            stop_flag = threading.Event()
            context.shared["stop_flag"] = stop_flag

        output_dir = Path(str(self.task_config.get("output_dir") or "./recordings")) / context.target.streamer
        output_dir.mkdir(parents=True, exist_ok=True)
        stream_name = str(self.task_config.get("stream_name") or "best")
        chunk_size = int(self.task_config.get("chunk_size") or 1024 * 64)

        result = await asyncio.to_thread(
            _download_m3u8,
            download_url,
            output_dir=output_dir,
            stream_name=stream_name,
            filename=_build_default_filename(context.live_status.title, stream_name),
            chunk_size=chunk_size,
            stop_flag=stop_flag,
        )

        payload["download"] = {
            "code": 0,
            "output": result["filepath"],
            "infojson": "",
            "files": [result["filepath"]],
            "download_url": download_url,
            "plugin": result["plugin"],
            "resolved_url": result["resolved_url"],
            "stream_name": result["stream_name"],
            "stream_type": result["stream_type"],
            "manifest_url": result["manifest_url"],
            "stream_url": result["stream_url"],
            "size": result["size"],
            "metadata": result["metadata"],
        }


def _download_m3u8(url: str, *, output_dir: Path, stream_name: str, filename: str | None, chunk_size: int, stop_flag: threading.Event) -> dict[str, Any]:
    session = Streamlink()
    plugin_name, plugin_class, resolved_url = session.resolve_url(url)
    plugin = plugin_class(session, resolved_url)
    streams = plugin.streams()
    if stream_name not in streams:
        raise ValueError(f"stream '{stream_name}' not found: {list(streams)}")
    stream = streams[stream_name]
    if filename is None:
        filename = _build_default_filename(None, stream_name)
    file_path = output_dir / filename
    total_bytes = 0
    with stream.open() as fd, file_path.open("wb") as out:
        while True:
            if stop_flag.is_set():
                raise RuntimeError("streamlink download cancelled")
            chunk = fd.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
            total_bytes += len(chunk)
    return {
        "filename": file_path.name,
        "filepath": str(file_path),
        "size": total_bytes,
        "plugin": plugin_name,
        "resolved_url": resolved_url,
        "stream_name": stream_name,
        "stream_type": type(stream).__name__,
        "manifest_url": stream.to_manifest_url() if hasattr(stream, "to_manifest_url") else None,
        "stream_url": getattr(stream, "url", None),
        "metadata": plugin.get_metadata(),
    }
