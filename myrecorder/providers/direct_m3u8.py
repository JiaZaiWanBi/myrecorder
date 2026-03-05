from __future__ import annotations

from ..http_client import HttpClient
from ..models import LiveInfo, TargetConfig, utc_now_iso


class DirectM3U8Provider:
    name = "direct_m3u8"

    async def check_live(self, target: TargetConfig, http: HttpClient) -> LiveInfo:
        m3u8_url = target.extra.get("m3u8_url")
        if not m3u8_url:
            raise ValueError(f"target={target.id} missing extra.m3u8_url")

        always_live = bool(target.extra.get("always_live", True))
        if always_live:
            return LiveInfo(
                is_live=True,
                m3u8_url=str(m3u8_url),
                title=str(target.extra.get("title", f"Live {target.id}")),
                streamer=str(target.extra.get("streamer", target.id)),
                live_start_time=utc_now_iso(),
            )

        resp = await http.get(str(m3u8_url))
        if resp.status != 200:
            return LiveInfo(is_live=False, raw={"http_status": resp.status})
        is_live = "#EXTM3U" in resp.text
        if not is_live:
            return LiveInfo(is_live=False, raw={"http_status": resp.status})
        return LiveInfo(
            is_live=True,
            m3u8_url=str(m3u8_url),
            title=str(target.extra.get("title", f"Live {target.id}")),
            streamer=str(target.extra.get("streamer", target.id)),
            live_start_time=utc_now_iso(),
        )
