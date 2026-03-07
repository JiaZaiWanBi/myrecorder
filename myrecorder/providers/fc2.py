from __future__ import annotations

import asyncio

import yt_dlp

from myrecorder.providers import LiveStatus
from myrecorder.ytdlp_client import probe_live_status


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
            info = await asyncio.wait_for(
                asyncio.to_thread(probe_live_status, url, self._timeout_seconds),
                timeout=self._timeout_seconds + 2,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"fc2 live check timeout after {self._timeout_seconds}s")
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).lower()
            if "not currently live" in msg or "4502" in msg:
                return LiveStatus(is_live=False, channel_url=url, live_url="", title="")
            raise RuntimeError(f"fc2 live check failed: {exc}") from exc

        live_status = str((info or {}).get("live_status") or "").strip()
        title = str((info or {}).get("title") or "").strip()
        description = str((info or {}).get("description") or "").strip()
        live_url = str((info or {}).get("webpage_url") or url).strip() or url

        if live_status == "is_live":
            return LiveStatus(
                is_live=True,
                channel_url=url,
                live_url=live_url,
                title=title,
                description=description,
                info=info or {},
            )

        if live_status in {"not_live", "was_live", "post_live", "", None}:
            return LiveStatus(
                is_live=False,
                channel_url=url,
                live_url="",
                title=title,
                description=description,
                info=info or {},
            )

        raise RuntimeError(f"fc2 live check failed: unexpected live_status={live_status!r}")


FC2Client = FC2Provider
