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
    result = subprocess.run(cmd, check=False, text=True, encoding="utf-8", errors="replace", capture_output=True)
    # if result.returncode != 0:
    #     message = (result.stderr or result.stdout or "fc2-live-dl-go 下载失败").strip()
    #     raise RuntimeError(message)

    files = [p for p in out_root.rglob("*") if p.is_file()]

    groups: dict[tuple[str, str], list[Path]] = {}

    def _group_key(path: Path) -> tuple[str, str]:
        name = path.name
        for suffix in (".info.json", ".fc2chat.json"):
            if name.endswith(suffix):
                return (str(path.parent), name[: -len(suffix)])
        return (str(path.parent), path.stem)

    for file_path in files:
        groups.setdefault(_group_key(file_path), []).append(file_path)

    if not groups:
        raise RuntimeError(f"fc2-live-dl-go 未在输出目录中生成任何文件: {out_root}")

    def _group_score(group_files: list[Path]) -> tuple[int, float]:
        video_suffix = f".{remux_format.lower()}" if remux else ".ts"
        has_video = any(path.suffix.lower() == video_suffix for path in group_files)
        latest_mtime = max(path.stat().st_mtime for path in group_files)
        return (1 if has_video else 0, latest_mtime)

    selected_group = max(groups.values(), key=_group_score)
    ordered = sorted(selected_group, key=lambda x: x.stat().st_mtime, reverse=True)

    video = None
    if remux:
        candidates = [p for p in ordered if p.suffix.lower() == f".{remux_format.lower()}"]
        video = candidates[0] if candidates else None
    else:
        candidates = [p for p in ordered if p.suffix.lower() == ".ts"]
        video = candidates[0] if candidates else None

    info_json = next((p for p in ordered if p.name.endswith(".info.json")), None)
    thumbnail = next((p for p in ordered if p.suffix.lower() == ".png"), None)
    chat_json = next((p for p in ordered if p.name.endswith(".fc2chat.json")), None)
    audio = next((p for p in ordered if p.suffix.lower() == ".m4a"), None)

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
