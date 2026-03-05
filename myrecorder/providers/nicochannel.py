from __future__ import annotations

import re
from urllib.parse import urlparse

from ..http_client import HttpClient
from ..models import LiveInfo, TargetConfig, utc_now_iso


def _normalize_nico_channel_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("invalid channel_url")
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    channel = parts[0]
    return f"{parsed.scheme}://{parsed.netloc}/{channel}".rstrip("/")


async def get_nico_live_status(
    http: HttpClient,
    channel_url: str,
    timeout: int = 5,
    retries: int = 3,
) -> dict:
    channel_root = _normalize_nico_channel_url(channel_url)

    domain_api = "https://api.nicochannel.jp/fc/content_providers/channel_domain"
    domain_resp = await http.get(
        domain_api,
        params={"current_site_domain": channel_root},
        timeout_seconds=timeout,
        retries=retries,
    )
    if domain_resp.status != 200:
        raise RuntimeError(f"nico domain api http={domain_resp.status}")
    domain_data = domain_resp.json()

    fanclub_site_id = (
        domain_data.get("data", {})
        .get("content_providers", {})
        .get("fanclub_site", {})
        .get("id")
    )
    if not fanclub_site_id:
        raise RuntimeError(f"fanclub_site_id not found: {domain_data}")

    live_api = f"https://api.nicochannel.jp/fc/fanclub_sites/{fanclub_site_id}/live_pages"
    headers = {
        "origin": "https://nicochannel.jp",
        "referer": channel_root + "/",
        "fc_use_device": "null",
    }

    async def fetch_live_type(live_type: int, per_page: int = 3) -> dict:
        resp = await http.get(
            live_api,
            params={"page": 1, "live_type": live_type, "per_page": per_page},
            headers=headers,
            timeout_seconds=timeout,
            retries=retries,
        )
        if resp.status != 200:
            raise RuntimeError(f"nico live_pages http={resp.status} live_type={live_type}")
        return resp.json().get("data", {}).get("video_pages", {})

    live_now = await fetch_live_type(1)
    try:
        scheduled = await fetch_live_type(2)
    except Exception:
        scheduled = {"list": [], "total": 0}

    live_now_list = live_now.get("list", []) or []
    scheduled_list = scheduled.get("list", []) or []

    site_base_url = (
        domain_data.get("data", {})
        .get("content_providers", {})
        .get("domain")
    ) or channel_root
    site_base_url = str(site_base_url).rstrip("/")

    def to_live_url(item: dict) -> str | None:
        code = item.get("content_code") if isinstance(item, dict) else None
        if not code:
            return None
        return f"{site_base_url}/live/{code}"

    live_now_urls = [u for u in (to_live_url(x) for x in live_now_list) if u]
    return {
        "channel_url": channel_root + "/",
        "fanclub_site_id": fanclub_site_id,
        "is_live_now": len(live_now_list) > 0,
        "live_now_count": int(live_now.get("total", len(live_now_list)) or 0),
        "scheduled_count": int(scheduled.get("total", len(scheduled_list)) or 0),
        "live_now": live_now_list,
        "live_now_urls": live_now_urls,
        "current_live_url": live_now_urls[0] if live_now_urls else None,
        "latest_scheduled": scheduled_list[0] if scheduled_list else None,
    }


async def resolve_nico_mediaplaylist(
    http: HttpClient,
    video_url: str,
    quality: str = "best",
    timeout: int = 5,
    retries: int = 3,
) -> str:
    m = re.search(r"/(?:video|live)/([^/?#]+)", urlparse(video_url).path)
    if not m:
        raise ValueError("invalid nico url: cannot find /(video|live)/{content_code}")
    content_code = m.group(1)

    sid_data = {}
    sid_endpoints = [
        f"https://api.nicochannel.jp/fc/video_pages/{content_code}/session_ids",
        f"https://api.nicochannel.jp/fc/live_pages/{content_code}/session_ids",
    ]
    sid_errors: list[str] = []
    for sid_api in sid_endpoints:
        try:
            sid_resp = await http.post_json(
                sid_api,
                payload={},
                headers={
                    "content-type": "application/json",
                    "fc_use_device": "null",
                    "origin": "https://nicochannel.jp",
                },
                timeout_seconds=timeout,
                retries=retries,
            )
            if sid_resp.status != 200:
                sid_errors.append(f"{sid_api}: http={sid_resp.status}")
                continue
            sid_data = sid_resp.json()
            break
        except Exception as exc:
            sid_errors.append(f"{sid_api}: {exc}")
    if not sid_data:
        raise RuntimeError("session_ids request failed: " + " | ".join(sid_errors))

    def find_uuid(obj):
        if isinstance(obj, str) and re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            obj,
        ):
            return obj
        if isinstance(obj, dict):
            for value in obj.values():
                hit = find_uuid(value)
                if hit:
                    return hit
        if isinstance(obj, list):
            for value in obj:
                hit = find_uuid(value)
                if hit:
                    return hit
        return None

    session_id = find_uuid(sid_data)
    if not session_id:
        raise RuntimeError(f"session_id not found in response: {sid_data}")

    auth_m3u8 = f"https://hls-auth.cloud.stream.co.jp/auth/index.m3u8?session_id={session_id}"
    master_resp = await http.get(auth_m3u8, timeout_seconds=timeout, retries=retries)
    if master_resp.status != 200:
        raise RuntimeError(f"auth m3u8 http={master_resp.status}")
    text = master_resp.text

    variants = []
    lines = [ln.strip() for ln in text.splitlines()]
    for idx, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:") and idx + 1 < len(lines):
            link = lines[idx + 1]
            if not link or link.startswith("#") or "/mediaplaylist/" not in link:
                continue
            bw_m = re.search(r"BANDWIDTH=(\d+)", line)
            res_m = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
            height = int(res_m.group(2)) if res_m else None
            p_m = re.search(r"_(\d{3,4})p\.m3u8", link)
            label = f"{p_m.group(1)}p" if p_m else (f"{height}p" if height else "unknown")
            variants.append(
                {
                    "label": label,
                    "bandwidth": int(bw_m.group(1)) if bw_m else 0,
                    "height": height or 0,
                    "url": link,
                }
            )

    if not variants:
        for line in lines:
            if line and not line.startswith("#") and "/mediaplaylist/" in line:
                return line
        raise RuntimeError("mediaplaylist url not found")

    q = (quality or "best").lower()
    if q == "best":
        return sorted(variants, key=lambda x: (x["bandwidth"], x["height"]), reverse=True)[0]["url"]
    if q == "worst":
        return sorted(variants, key=lambda x: (x["bandwidth"], x["height"]))[0]["url"]
    for variant in variants:
        if str(variant["label"]).lower() == q:
            return str(variant["url"])
    available = ", ".join(
        sorted(
            {str(v["label"]) for v in variants},
            key=lambda x: int(x[:-1]) if x[:-1].isdigit() else 0,
            reverse=True,
        )
    )
    raise ValueError(f"quality '{quality}' not found, available: {available}")


def _guess_streamer(channel_url: str, fallback: str) -> str:
    path = urlparse(channel_url).path.strip("/")
    if not path:
        return fallback
    return path.split("/")[0] or fallback


def _find_title(live_item: dict[str, object]) -> str | None:
    for key in ("title", "headline", "name"):
        value = live_item.get(key) if isinstance(live_item, dict) else None
        if value:
            return str(value)
    return None


class NicoChannelProvider:
    """Built-in NicoChannel provider. No external script paths required."""

    def __init__(self, name: str = "NicoChannel") -> None:
        self.name = name

    async def check_live(self, target: TargetConfig, http: HttpClient) -> LiveInfo:
        channel_url = str(target.extra.get("channel_url", "")).strip()
        if not channel_url:
            raise ValueError(f"target={target.id} missing extra.channel_url")

        quality = str(target.extra.get("quality", "best"))
        timeout = int(target.extra.get("timeout", 5))
        retries = int(target.extra.get("retries", 3))

        status_data = await get_nico_live_status(http, channel_url, timeout, retries)
        is_live = bool(status_data.get("is_live_now") or status_data.get("is_live"))
        streamer = str(target.extra.get("streamer") or _guess_streamer(channel_url, target.id))
        if not is_live:
            return LiveInfo(is_live=False, streamer=streamer, raw=status_data)

        live_page_url = status_data.get("current_live_url")
        if not live_page_url:
            urls = status_data.get("live_now_urls") or []
            if isinstance(urls, list) and urls:
                live_page_url = urls[0]
        if not live_page_url:
            raise RuntimeError(f"target={target.id} live detected but no current_live_url in status data")

        m3u8_url = await resolve_nico_mediaplaylist(
            http=http,
            video_url=str(live_page_url),
            quality=quality,
            timeout=timeout,
            retries=retries,
        )

        title = None
        live_now = status_data.get("live_now")
        if isinstance(live_now, list) and live_now and isinstance(live_now[0], dict):
            title = _find_title(live_now[0])

        return LiveInfo(
            is_live=True,
            m3u8_url=str(m3u8_url),
            title=title or f"nico_live_{streamer}",
            streamer=streamer,
            live_start_time=utc_now_iso(),
            raw={"channel_url": channel_url, "live_page_url": live_page_url, "status": status_data},
        )
