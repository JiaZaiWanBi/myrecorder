from __future__ import annotations

from pathlib import Path
from typing import Any

from myrecorder.config.streams import load_stream_targets
from myrecorder.config.yaml import load_yaml_dict
from myrecorder.models import AppConfig, WorkflowConfig


def _normalize_workflow_steps(raw: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{field_name} 必须是字符串列表")
    steps: list[str] = []
    for item in raw:
        value = str(item).strip().lower()
        if value:
            steps.append(value)
    if not steps:
        raise ValueError(f"{field_name} 不能为空列表")
    return tuple(steps)


def _normalize_task_map(raw: Any, *, field_name: str) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{field_name} 必须是对象")
    result: dict[str, dict[str, Any]] = {}
    for task_name, task_cfg in raw.items():
        normalized_name = str(task_name).strip().lower()
        if not normalized_name:
            continue
        if task_cfg is None:
            result[normalized_name] = {}
            continue
        if not isinstance(task_cfg, dict):
            raise ValueError(f"{field_name}.{normalized_name} 必须是对象")
        result[normalized_name] = dict(task_cfg)
    return result


def parse_workflow_config(service: dict[str, Any]) -> WorkflowConfig:
    workflow_cfg = service.get("workflow") or {}
    if workflow_cfg and not isinstance(workflow_cfg, dict):
        raise ValueError("config.yaml 中的 service.workflow 必须是对象")

    default_raw = workflow_cfg.get("default")
    default_steps = _normalize_workflow_steps(default_raw, field_name="service.workflow.default") if default_raw is not None else None

    providers_raw = workflow_cfg.get("providers") or {}
    if providers_raw and not isinstance(providers_raw, dict):
        raise ValueError("config.yaml 中的 service.workflow.providers 必须是对象")

    provider_steps: dict[str, tuple[str, ...]] = {}
    for provider_name, raw_steps in providers_raw.items():
        normalized_provider = str(provider_name).strip().lower()
        if not normalized_provider:
            continue
        provider_steps[normalized_provider] = _normalize_workflow_steps(
            raw_steps,
            field_name=f"service.workflow.providers.{normalized_provider}",
        )

    return WorkflowConfig(default=default_steps, providers=provider_steps)


def load_app_config(config_path: str, streams_path: str) -> AppConfig:
    root = load_yaml_dict(config_path)
    service = root.get("service") or {}
    if not isinstance(service, dict):
        raise ValueError("config.yaml 中的 service 必须是对象")

    default_interval = max(int(service.get("interval_seconds", 60)), 20)
    streams = load_stream_targets(streams_path, default_interval, allow_empty=True)

    return AppConfig(
        output_dir=Path(str(service.get("output_dir", "./recordings"))),
        interval_seconds=default_interval,
        request_timeout_seconds=max(int(service.get("request_timeout_seconds", 8)), 3),
        request_retries=max(int(service.get("request_retries", 3)), 0),
        workflow=parse_workflow_config(service),
        tasks=_normalize_task_map(root.get("tasks"), field_name="tasks"),
        streams=streams,
    )
