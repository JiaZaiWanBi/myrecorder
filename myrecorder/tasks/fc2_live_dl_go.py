from __future__ import annotations

import asyncio
import json
import subprocess
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
            out_root=output_dir / context.target.streamer,
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
    out_format = str(out_root / "{{ .Date }} {{ .Time }} {{ .Title }}.{{ .Ext }}")
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
    subprocess.run(cmd, check=False, text=True, encoding="utf-8", errors="replace",capture_output=True)
    files = [p for p in out_root.rglob("*") if p.is_file()]
    ordered = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)

    video = None
    if remux:
        candidates = [p for p in ordered if p.suffix.lower() == f".{remux_format.lower()}"]
        video = candidates[0] if candidates else None
    else:
        candidates = [p for p in ordered if p.suffix.lower() == ".ts"]
        video = candidates[0] if candidates else None

    primary_stem = video.stem if video else ""
    primary_parent = video.parent if video else None

    def _match_sidecar(path: Path, suffix: str) -> bool:
        if primary_parent is not None and path.parent != primary_parent:
            return False
        if not path.name.endswith(suffix):
            return False
        if not primary_stem:
            return True
        sidecar_stem = path.name[: -len(suffix)]
        return sidecar_stem == primary_stem

    def _find_sidecar(suffix: str) -> Path | None:
        matched = [p for p in ordered if _match_sidecar(p, suffix)]
        if matched:
            return matched[0]
        fallback = [p for p in ordered if p.name.endswith(suffix)]
        return fallback[0] if fallback else None

    info_json = _find_sidecar(".info.json")
    thumbnail = _find_sidecar(".png")
    chat_json = _find_sidecar(".fc2chat.json")
    audio = _find_sidecar(".m4a")

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
