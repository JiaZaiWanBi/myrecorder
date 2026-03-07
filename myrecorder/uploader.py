from __future__ import annotations

import subprocess
from pathlib import PurePosixPath

from myrecorder.log import get_logger
from myrecorder.models import StreamTarget, WebDAVConfig


class WebDAVUploader:
    def __init__(self, config: WebDAVConfig | None) -> None:
        if config is None:
            raise ValueError("WebDAV 配置不能为空")
        self._config = config
        self._logger = get_logger(component="uploader")
        self._obscured_password = self._obscure_password(config.password)

    def upload(self, file_path: str, target: StreamTarget) -> None:
        local_path = str(file_path)
        remote_path = self._build_remote_path(target, local_path)
        cmd = self._build_command(local_path, remote_path)
        self._logger.bind(provider=target.provider, streamer=target.streamer).info("开始上传到 WebDAV: {}", remote_path)
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "rclone 上传失败").strip()
            raise RuntimeError(message)
        self._logger.bind(provider=target.provider, streamer=target.streamer).info("上传完成: {}", remote_path)

    def _build_remote_path(self, target: StreamTarget, local_path: str) -> str:
        name = PurePosixPath(local_path).name
        root = PurePosixPath(self._config.root or "/")
        return str(root / target.streamer / name)

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
