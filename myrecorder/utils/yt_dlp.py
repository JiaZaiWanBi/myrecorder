from __future__ import annotations

from typing import Any

import yt_dlp


class _FakeLogger:
    def debug(self, msg: str) -> None:
        return

    def info(self, msg: str) -> None:
        return

    def warning(self, msg: str) -> None:
        return

    def error(self, msg: str) -> None:
        return


def probe_live_status_with_ytdlp(url: str, timeout_seconds: int) -> dict[str, Any] | None:
    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "logger": _FakeLogger(),
        "socket_timeout": timeout_seconds,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        return None
    return info
