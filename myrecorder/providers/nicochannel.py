from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp

from myrecorder.providers import LiveStatus


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


class NicoChannelProvider:
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

    async def _request_text(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        last_error: Exception | None = None
        req_timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        for attempt in range(self._retries + 1):
            try:
                async with self._session.get(url, params=params, headers=headers, timeout=req_timeout) as resp:
                    resp.raise_for_status()
                    return await resp.text()
            except Exception as exc:
                last_error = exc
                if attempt >= self._retries:
                    break
                await asyncio.sleep(min(2 + attempt, 4))
        assert last_error is not None
        raise last_error

    async def _post_json(
        self,
        url: str,
        *,
        payload: dict[str, object],
        headers: dict[str, str] | None = None,
    ) -> dict:
        last_error: Exception | None = None
        req_timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        for attempt in range(self._retries + 1):
            try:
                async with self._session.post(url, json=payload, headers=headers, timeout=req_timeout) as resp:
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

    def _find_session_id(self, data: object) -> str | None:
        if isinstance(data, str) and re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            data,
        ):
            return data
        if isinstance(data, dict):
            for value in data.values():
                hit = self._find_session_id(value)
                if hit:
                    return hit
        if isinstance(data, list):
            for value in data:
                hit = self._find_session_id(value)
                if hit:
                    return hit
        return None

    async def _resolve_mediaplaylist(self, live_page_url: str) -> str:
        match = re.search(r"/(?:video|live)/([^/?#]+)", urlparse(live_page_url).path)
        if not match:
            raise ValueError(f"invalid nico live url: {live_page_url}")
        content_code = match.group(1)

        session_data: dict = {}
        errors: list[str] = []
        for session_api in (
            f"https://api.nicochannel.jp/fc/video_pages/{content_code}/session_ids",
            f"https://api.nicochannel.jp/fc/live_pages/{content_code}/session_ids",
        ):
            try:
                session_data = await self._post_json(
                    session_api,
                    payload={},
                    headers={
                        "content-type": "application/json",
                        "fc_use_device": "null",
                        "origin": "https://nicochannel.jp",
                    },
                )
                break
            except Exception as exc:
                errors.append(f"{session_api}: {exc}")
        if not session_data:
            raise RuntimeError("session_ids request failed: " + " | ".join(errors))

        session_id = self._find_session_id(session_data)
        if not session_id:
            raise RuntimeError(f"session_id not found in response: {session_data}")

        master_text = await self._request_text(
            f"https://hls-auth.cloud.stream.co.jp/auth/index.m3u8?session_id={session_id}"
        )
        lines = [line.strip() for line in master_text.splitlines()]
        variants: list[dict[str, object]] = []
        for idx, line in enumerate(lines):
            if not line.startswith("#EXT-X-STREAM-INF:") or idx + 1 >= len(lines):
                continue
            link = lines[idx + 1]
            if not link or link.startswith("#") or "/mediaplaylist/" not in link:
                continue
            bandwidth_match = re.search(r"BANDWIDTH=(\d+)", line)
            resolution_match = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
            height = int(resolution_match.group(2)) if resolution_match else 0
            variants.append(
                {
                    "url": link,
                    "bandwidth": int(bandwidth_match.group(1)) if bandwidth_match else 0,
                    "height": height,
                }
            )

        if variants:
            best = max(variants, key=lambda item: (int(item["bandwidth"]), int(item["height"])))
            return str(best["url"])

        for line in lines:
            if line and not line.startswith("#") and "/mediaplaylist/" in line:
                return line
        raise RuntimeError("mediaplaylist url not found")

    async def check_live(self, channel_url: str) -> LiveStatus:
        normalized_channel_url = _normalize_channel_url(channel_url)

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
            return LiveStatus(is_live=False, channel_url=normalized_channel_url)

        item = items[0] if isinstance(items[0], dict) else {}
        content_code = str(item.get("content_code") or "").strip()
        if not content_code:
            return LiveStatus(is_live=False, channel_url=normalized_channel_url)

        title = str(item.get("title") or "").strip()
        started_at = str(item.get("live_started_at") or _utc_now_iso())
        live_page_url = f"{normalized_channel_url}/live/{content_code}"
        m3u8_url = await self._resolve_mediaplaylist(live_page_url)
        return LiveStatus(
            is_live=True,
            channel_url=normalized_channel_url,
            live_url=m3u8_url,
            title=title,
            started_at=started_at,
        )


NicoChannelClient = NicoChannelProvider
