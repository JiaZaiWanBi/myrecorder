from __future__ import annotations

from typing import Any

from myrecorder.models import StreamTarget
from myrecorder.providers import resolve_provider
from myrecorder.config.yaml import load_yaml


def _guess_streamer_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or "unknown_streamer"


def _normalize_workflow_steps(raw: Any) -> tuple[str, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(f"workflow 必须是字符串列表: {raw!r}")
    steps: list[str] = []
    for item in raw:
        value = str(item).strip().lower()
        if value:
            steps.append(value)
    if not steps:
        raise ValueError("workflow 不能为空列表")
    return tuple(steps)


def _normalize_task_map(raw: Any) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"tasks 必须是对象: {raw!r}")
    result: dict[str, dict[str, Any]] = {}
    for task_name, task_cfg in raw.items():
        normalized_name = str(task_name).strip().lower()
        if not normalized_name:
            continue
        if task_cfg is None:
            result[normalized_name] = {}
            continue
        if not isinstance(task_cfg, dict):
            raise ValueError(f"tasks.{normalized_name} 必须是对象")
        result[normalized_name] = dict(task_cfg)
    return result


def _normalize_stream_item(item: Any, default_interval: int) -> StreamTarget:
    if isinstance(item, str):
        url = item.strip()
        provider = resolve_provider(None, url)
        return StreamTarget(
            provider=provider,
            streamer=_guess_streamer_from_url(url),
            channel_url=url,
            interval_seconds=default_interval,
        )

    if not isinstance(item, dict):
        raise ValueError(f"streams 项必须是字符串或对象: {item!r}")

    url = str(item.get("channel_url") or item.get("url") or "").strip()
    if not url:
        raise ValueError(f"stream 缺少 channel_url/url: {item!r}")

    provider_input = item.get("provider")
    provider = resolve_provider(str(provider_input) if provider_input is not None else None, url)

    streamer_value = item.get("streamer")
    streamer = str(streamer_value).strip() if streamer_value is not None else ""
    if not streamer:
        streamer = _guess_streamer_from_url(url)

    interval = max(int(item.get("interval_seconds") or default_interval), 3)
    return StreamTarget(
        provider=provider,
        streamer=streamer,
        channel_url=url,
        interval_seconds=interval,
        workflow=_normalize_workflow_steps(item.get("workflow")),
        task_overrides=_normalize_task_map(item.get("tasks")),
    )


def load_stream_targets(streams_path: str, default_interval: int, *, allow_empty: bool = False) -> list[StreamTarget]:
    stream_cfg = load_yaml(streams_path)

    if isinstance(stream_cfg, list):
        streams_raw = stream_cfg
    elif isinstance(stream_cfg, dict):
        streams_raw = stream_cfg.get("streams") or []
    else:
        raise ValueError("streams.yaml 必须是列表，或包含 streams 列表的对象")

    if not isinstance(streams_raw, list):
        raise ValueError("streams.yaml 必须包含直播目标列表")
    if not allow_empty and not streams_raw:
        raise ValueError("streams.yaml 必须包含非空的直播目标列表")
    return [_normalize_stream_item(item, default_interval) for item in streams_raw]
