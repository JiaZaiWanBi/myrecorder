from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path, PurePosixPath

from myrecorder.log import get_logger
from myrecorder.models import TaskContext, UploaderTask, WebDAVConfig, WorkflowState


_VALIDATED_WEBDAV_CONFIGS: set[tuple[str, str, str, str, str, str]] = set()


def _webdav_config_key(config: WebDAVConfig) -> tuple[str, str, str, str, str, str]:
    return (
        config.url,
        config.user,
        config.password,
        config.root,
        config.mode,
        config.rclone_path,
    )


def _summarize_rclone_error(message: str) -> str:
    for line in reversed([line.strip() for line in message.splitlines() if line.strip()]):
        if "Method Not Allowed" in line:
            return "405 Method Not Allowed"
        if "authentication" in line.lower():
            return line
        if "connection refused" in line.lower():
            return line
        if "timed out" in line.lower() or "timeout" in line.lower():
            return line
        if "not found" in line.lower():
            return line
        if "failed" in line.lower():
            return line
    return message.splitlines()[-1].strip() if message.strip() else "未知错误"


class WebDavUploadTask(UploaderTask):
    name = "webdav"
    uploader_name = "webdav"

    def __init__(self, *, config: WebDAVConfig) -> None:
        self._uploader = _WebDAVClient(config)
        config_key = _webdav_config_key(config)
        if config_key not in _VALIDATED_WEBDAV_CONFIGS:
            self._uploader.validate_connection()
            _VALIDATED_WEBDAV_CONFIGS.add(config_key)

    async def run(self, context: TaskContext, state: WorkflowState) -> None:
        download = state.data.get("download")
        if not isinstance(download, dict):
            raise ValueError("webdav task requires download result in workflow state")

        uploaded_files: list[str] = []
        remote_paths: list[str] = []

        raw_files = download.get("files") or [value for value in (download.get("output"), download.get("infojson")) if value]
        file_paths = [str(path) for path in raw_files if path]
        for file_path in file_paths:
            path = Path(file_path)
            if not path.exists() or not path.is_file():
                context.logger.warning("上传前未找到文件，跳过: {}", path)
                continue
            context.logger.info("开始上传文件: {}", path)
            remote_path = await asyncio.to_thread(self._uploader.upload, str(path), context.target.provider, context.target.streamer)
            uploaded_files.append(str(path))
            remote_paths.append(remote_path)

        state.data["webdav"] = {
            "uploaded_files": uploaded_files,
            "remote_paths": remote_paths,
            "source_output": download.get("output", ""),
        }


class _WebDAVClient:
    def __init__(self, config: WebDAVConfig) -> None:
        self._config = config
        self._logger = get_logger(component="uploader")
        self._obscured_password = self._obscure_password(config.password)

    def validate_connection(self) -> None:
        command = self._build_ls_command()
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raw_message = (result.stderr or result.stdout or "rclone webdav 连通性测试失败").strip()
            summary = _summarize_rclone_error(raw_message)
            self._logger.error("webdav validation failed: {}", raw_message)
            raise RuntimeError(f"webdav 连通性测试失败: {summary}")

    def upload(self, file_path: str, provider: str, streamer: str) -> str:
        local_path = str(file_path)
        remote_path = self._build_remote_path(streamer, local_path)
        cmd = self._build_command(local_path, remote_path)
        self._logger.bind(provider=provider, streamer=streamer).info("开始上传到 WebDAV: {}", remote_path)
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "rclone 上传失败").strip()
            raise RuntimeError(message)
        self._logger.bind(provider=provider, streamer=streamer).info("上传完成: {}", remote_path)
        return remote_path

    def _build_remote_path(self, streamer: str, local_path: str) -> str:
        name = Path(local_path).name
        root = PurePosixPath(self._config.root or "/")
        return str(root / streamer / name)

    def _build_command(self, local_path: str, remote_path: str) -> list[str]:
        remote = remote_path if remote_path.startswith("/") else f"/{remote_path}"
        return [
            self._config.rclone_path,
            f"{self._config.mode}to",
            "--webdav-url",
            self._config.url,
            "--webdav-user",
            self._config.user,
            "--webdav-pass",
            self._obscured_password,
            local_path,
            f":webdav:{remote}",
        ]

    def _build_ls_command(self) -> list[str]:
        remote_root = self._config.root if self._config.root.startswith("/") else f"/{self._config.root}"
        return [
            self._config.rclone_path,
            "ls",
            "--webdav-url",
            self._config.url,
            "--webdav-user",
            self._config.user,
            "--webdav-pass",
            self._obscured_password,
            f":webdav:{remote_root}",
        ]

    def _obscure_password(self, password: str) -> str:
        result = subprocess.run(
            [self._config.rclone_path, "obscure", password],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "rclone obscure 失败").strip()
            raise RuntimeError(message)
        return result.stdout.strip()
