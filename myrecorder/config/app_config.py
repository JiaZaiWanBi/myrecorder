from __future__ import annotations

from pathlib import Path
from typing import Any

from myrecorder.config.streams import load_stream_targets
from myrecorder.config.yaml import load_yaml_dict
from myrecorder.models import AppConfig, FC2LiveDlGoConfig, WebDAVConfig, WorkflowConfig


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


def parse_webdav_config(root: dict[str, Any], service: dict[str, Any]) -> WebDAVConfig | None:
    webdav_cfg = root.get("webdav")
    if webdav_cfg is None:
        webdav_cfg = service.get("webdav")
    if webdav_cfg is None:
        return None
    if not isinstance(webdav_cfg, dict):
        raise ValueError("config.yaml 中的 webdav 必须是对象")

    url = str(webdav_cfg.get("url") or "").strip()
    user = str(webdav_cfg.get("user") or "").strip()
    password = str(webdav_cfg.get("pass") or webdav_cfg.get("password") or "").strip()
    if not url or not user or not password:
        raise ValueError("webdav 需要提供 url、user、pass")

    mode = str(webdav_cfg.get("mode") or "copy").strip().lower() or "copy"
    if mode not in {"copy", "move"}:
        raise ValueError("webdav.mode 只能是 copy 或 move")

    return WebDAVConfig(
        url=url,
        user=user,
        password=password,
        root=str(webdav_cfg.get("root") or "/").strip() or "/",
        rclone_path=str(webdav_cfg.get("rclone_path") or "rclone").strip() or "rclone",
        mode=mode,
    )


def parse_fc2_live_dl_go_config(root: dict[str, Any], service: dict[str, Any]) -> FC2LiveDlGoConfig | None:
    fc2_cfg = root.get("fc2_live_dl_go")
    if fc2_cfg is None:
        fc2_cfg = service.get("fc2_live_dl_go")
    if fc2_cfg is None:
        return None
    if not isinstance(fc2_cfg, dict):
        raise ValueError("config.yaml 中的 fc2_live_dl_go 必须是对象")

    binary = str(fc2_cfg.get("binary") or "fc2-live-dl-go.exe").strip() or "fc2-live-dl-go.exe"
    remux_format = str(fc2_cfg.get("remux_format") or "mp4").strip().lower() or "mp4"
    return FC2LiveDlGoConfig(
        binary=binary,
        remux_format=remux_format,
        write_thumbnail=bool(fc2_cfg.get("write_thumbnail", True)),
        extract_audio=bool(fc2_cfg.get("extract_audio", False)),
        remux=bool(fc2_cfg.get("remux", True)),
    )


def load_app_config(config_path: str, streams_path: str) -> AppConfig:
    root = load_yaml_dict(config_path)
    service = root.get("service") or {}
    if not isinstance(service, dict):
        raise ValueError("config.yaml 中的 service 必须是对象")

    default_interval = max(int(service.get("interval_seconds", 60)), 20)
    streams = load_stream_targets(streams_path, default_interval, allow_empty=True)

    ytdlp_extra_args = service.get("ytdlp_extra_args") or []
    if not isinstance(ytdlp_extra_args, list):
        raise ValueError("config.yaml 中的 ytdlp_extra_args 必须是列表")
    if ytdlp_extra_args:
        raise ValueError("当前版本不支持 ytdlp_extra_args，请保持为空列表")

    return AppConfig(
        output_dir=Path(str(service.get("output_dir", "./recordings"))),
        interval_seconds=default_interval,
        request_timeout_seconds=max(int(service.get("request_timeout_seconds", 8)), 3),
        request_retries=max(int(service.get("request_retries", 3)), 0),
        ytdlp_format=(str(service.get("ytdlp_format")).strip() if service.get("ytdlp_format") is not None else None),
        live_from_start=bool(service.get("live_from_start", False)),
        write_info_json=bool(service.get("write_info_json", True)),
        ytdlp_extra_args=[str(x) for x in ytdlp_extra_args],
        hls_use_mpegts=bool(service.get("hls_use_mpegts", True)),
        workflow=parse_workflow_config(service),
        webdav=parse_webdav_config(root, service),
        fc2_live_dl_go=parse_fc2_live_dl_go_config(root, service),
        streams=streams,
    )
