from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp


@dataclass(frozen=True)
class NicoLiveStatus:
    is_live: bool
    channel_url: str
    live_url: str = ""
    title: str = ""
    started_at: str = ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_channel_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"invalid channel url: {url}")
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        raise ValueError(f"cannot parse channel id from url: {url}")
    return f"{parsed.scheme}://{parsed.netloc}/{parts[0]}"


class NicoChannelClient:
    def __init__(self, session: aiohttp.ClientSession, timeout_seconds: int = 8, retries: int = 3) -> None:
        self._session = session
        self._timeout_seconds = timeout_seconds
        self._retries = retries

    async def _request_json(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        last_error: Exception | None = None
        req_timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        for attempt in range(self._retries + 1):
            try:
                async with self._session.get(url, params=params, headers=headers, timeout=req_timeout) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    if not isinstance(data, dict):
                        raise RuntimeError(f"response is not a JSON object: {url}")
                    return data
            except Exception as exc:
                last_error = exc
                if attempt >= self._retries:
                    break
                await asyncio.sleep(min(2 + attempt, 4))
        assert last_error is not None
        raise last_error

    async def check_live(self, channel_url: str) -> NicoLiveStatus:
        normalized_channel_url = _normalize_channel_url(channel_url)

        # Stable route used by previous implementation:
        # resolve fanclub site id from channel domain first.
        domain_data = await self._request_json(
            "https://api.nicochannel.jp/fc/content_providers/channel_domain",
            params={"current_site_domain": normalized_channel_url},
        )
        fanclub_site_id = (
            domain_data.get("data", {})
            .get("content_providers", {})
            .get("fanclub_site", {})
            .get("id")
        )
        if not fanclub_site_id:
            raise RuntimeError(f"fanclub_site_id not found for {normalized_channel_url}")

        live_data = await self._request_json(
            f"https://api.nicochannel.jp/fc/fanclub_sites/{fanclub_site_id}/live_pages",
            params={"page": 1, "per_page": 5, "live_type": 1},
            headers={
                "origin": "https://nicochannel.jp",
                "referer": normalized_channel_url + "/",
                "fc_use_device": "null",
            },
        )

        items = live_data.get("data", {}).get("video_pages", {}).get("list", [])
        if not isinstance(items, list) or not items:
            return NicoLiveStatus(is_live=False, channel_url=normalized_channel_url)

        item = items[0] if isinstance(items[0], dict) else {}
        content_code = str(item.get("content_code") or "").strip()
        if not content_code:
            return NicoLiveStatus(is_live=False, channel_url=normalized_channel_url)

        title = str(item.get("title") or "").strip()
        started_at = str(item.get("live_started_at") or _utc_now_iso())
        return NicoLiveStatus(
            is_live=True,
            channel_url=normalized_channel_url,
            live_url=f"{normalized_channel_url}/live/{content_code}",
            title=title,
            started_at=started_at,
        )
