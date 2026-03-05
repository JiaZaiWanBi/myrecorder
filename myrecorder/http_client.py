from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Mapping

import aiohttp


@dataclass(slots=True)
class HttpResponse:
    status: int
    url: str
    headers: Mapping[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class HttpClient:
    def __init__(
        self,
        *,
        timeout_seconds: int = 5,
        max_retries: int = 3,
        backoff_seconds: float = 0.4,
        user_agent: str = "myrecorder/0.1",
        connection_limit: int = 100,
        dns_ttl_seconds: int = 300,
    ) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_retries = max(1, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.user_agent = user_agent
        self.connection_limit = max(1, int(connection_limit))
        self.dns_ttl_seconds = max(1, int(dns_ttl_seconds))
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is not None:
            return
        connector = aiohttp.TCPConnector(
            limit=self.connection_limit,
            ttl_dns_cache=self.dns_ttl_seconds,
            enable_cleanup_closed=True,
        )
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": self.user_agent},
        )

    async def close(self) -> None:
        if self._session is None:
            return
        await self._session.close()
        self._session = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_data: Any = None,
        data: Any = None,
        timeout_seconds: int | None = None,
        retries: int | None = None,
        retry_for_statuses: set[int] | None = None,
    ) -> HttpResponse:
        if self._session is None:
            raise RuntimeError("HttpClient not started")

        request_timeout = aiohttp.ClientTimeout(total=max(1, int(timeout_seconds or self.timeout_seconds)))
        request_retries = max(1, int(retries or self.max_retries))
        retry_statuses = retry_for_statuses or {429, 500, 502, 503, 504}
        last_exc: Exception | None = None

        for attempt in range(1, request_retries + 1):
            try:
                async with self._session.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    data=data,
                    timeout=request_timeout,
                ) as resp:
                    body = await resp.read()
                    if resp.status in retry_statuses and attempt < request_retries:
                        await asyncio.sleep(self.backoff_seconds * attempt)
                        continue
                    return HttpResponse(
                        status=int(resp.status),
                        url=str(resp.url),
                        headers=dict(resp.headers),
                        body=body,
                    )
            except (
                asyncio.TimeoutError,
                aiohttp.ServerTimeoutError,
                aiohttp.ClientConnectionError,
                aiohttp.ClientPayloadError,
            ) as exc:
                last_exc = exc
                if attempt >= request_retries:
                    break
                await asyncio.sleep(self.backoff_seconds * attempt)

        raise RuntimeError(f"request failed after {request_retries} attempts: {method} {url}") from last_exc

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        timeout_seconds: int | None = None,
        retries: int | None = None,
    ) -> HttpResponse:
        return await self.request(
            "GET",
            url,
            headers=headers,
            params=params,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )

    async def post_json(
        self,
        url: str,
        payload: Any,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        timeout_seconds: int | None = None,
        retries: int | None = None,
    ) -> HttpResponse:
        return await self.request(
            "POST",
            url,
            headers=headers,
            params=params,
            json_data=payload,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )
