from __future__ import annotations

import asyncio

import yt_dlp

from . import LiveStatus

try:
    from ..ytdlp_client import probe_live_status
except ImportError:
    from ytdlp_client import probe_live_status


class FC2Provider:
    def __init__(
        self,
        *,
        timeout_seconds: int = 8,
        **_: object,
    ) -> None:
        self._timeout_seconds = timeout_seconds

    async def check_live(self, channel_url: str) -> LiveStatus:
        url = channel_url.strip()
        if not url:
            raise ValueError("fc2 channel_url is empty")

        try:
            status = await asyncio.wait_for(
                asyncio.to_thread(probe_live_status, url, self._timeout_seconds),
                timeout=self._timeout_seconds + 2,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"fc2 live check timeout after {self._timeout_seconds}s")
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).lower()
            if "not currently live" in msg:
                return LiveStatus(is_live=False, channel_url=url, live_url="", title="")
            raise RuntimeError(f"fc2 live check failed: {exc}") from exc

        if status == "is_live":
            return LiveStatus(is_live=True, channel_url=url, live_url=url, title="")

        if status in {"not_live", "was_live", "post_live", None, ""}:
            return LiveStatus(is_live=False, channel_url=url, live_url="", title="")

        raise RuntimeError(f"fc2 live check failed: unexpected live_status={status!r}")


FC2Client = FC2Provider
