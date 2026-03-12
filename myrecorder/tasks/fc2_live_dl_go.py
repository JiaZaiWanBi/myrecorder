from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from myrecorder.models import TaskContext
from myrecorder.registry import Registry
from myrecorder.tasks.base import BaseTask


@Registry.register_task("fc2_live_dl_go")
class FC2LiveDlGoDownloadTask(BaseTask):
    name = "fc2_live_dl_go"

    async def run(self, context: TaskContext, payload: dict[str, Any]) -> None:
        channel_id = _extract_fc2_channel_id(context.live_status.channel_url)
        output_dir = Path(str(self.task_config.get("output_dir") or "./recordings"))
        result = await asyncio.to_thread(
            _download_fc2,
            channel_id=channel_id,
            binary=str(self.task_config.get("binary") or "fc2-live-dl-go.exe"),
            out_root=output_dir,
            remux_format=str(self.task_config.get("remux_format") or "mp4"),
            write_thumbnail=bool(self.task_config.get("write_thumbnail", True)),
            extract_audio=bool(self.task_config.get("extract_audio", False)),
            remux=bool(self.task_config.get("remux", True)),
        )

        files = [path for path in [result.get("video"), result.get("audio"), result.get("thumbnail"), result.get("chat_json"), result.get("info_json")] if path]
        primary_output = result.get("video") or result.get("audio") or ""
        payload["download"] = {
            "code": 0,
            "output": primary_output,
            "infojson": result.get("info_json") or "",
            "files": files,
            "channel_id": result["channel_id"],
            "video": result.get("video"),
            "audio": result.get("audio"),
            "thumbnail": result.get("thumbnail"),
            "chat_json": result.get("chat_json"),
            "download_url": context.live_status.live_url,
            "meta": result.get("meta"),
        }


def _extract_fc2_channel_id(channel_url: str) -> str:
    cleaned = channel_url.rstrip("/")
    channel_id = cleaned.split("/")[-1]
    if not channel_id:
        raise ValueError(f"cannot parse fc2 channel id from url: {channel_url}")
    return channel_id


def _download_fc2(*, channel_id: str, binary: str, out_root: Path, remux_format: str, write_thumbnail: bool, extract_audio: bool, remux: bool) -> dict[str, object]:
    start_ts = time.time()
    out_dir = out_root / channel_id
    out_format = str(out_dir / "{{ .Date }} {{ .Time }} {{ .Title }}.{{ .Ext }}")
    cmd = [binary, "download", "--format", out_format, "--write-info-json"]
    if write_thumbnail:
        cmd.append("--write-thumbnail")
    if extract_audio:
        cmd.append("--extract-audio")
    if remux:
        cmd += ["--remux-format", remux_format]
    else:
        cmd.append("--no-remux")
    cmd.append(channel_id)
    subprocess.run(cmd, check=True)
    files = [p for p in out_dir.rglob("*") if p.is_file() and p.stat().st_mtime >= start_ts - 2]
    ordered = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)
    info_json = next((p for p in ordered if p.name.endswith(".info.json")), None)
    thumbnail = next((p for p in ordered if p.suffix.lower() == ".png"), None)
    chat_json = next((p for p in ordered if p.name.endswith(".fc2chat.json")), None)
    audio = next((p for p in ordered if p.suffix.lower() == ".m4a"), None)
    video = None
    if remux:
        candidates = [p for p in ordered if p.suffix.lower() == f".{remux_format.lower()}"]
        video = candidates[0] if candidates else None
    else:
        candidates = [p for p in ordered if p.suffix.lower() == ".ts"]
        video = candidates[0] if candidates else None
    meta = None
    if info_json and info_json.exists():
        meta = json.loads(info_json.read_text(encoding="utf-8"))
    return {
        "channel_id": channel_id,
        "video": str(video) if video else None,
        "audio": str(audio) if audio else None,
        "thumbnail": str(thumbnail) if thumbnail else None,
        "chat_json": str(chat_json) if chat_json else None,
        "info_json": str(info_json) if info_json else None,
        "meta": meta,
    }
