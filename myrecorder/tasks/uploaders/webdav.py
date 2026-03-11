from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path, PurePosixPath

from myrecorder.log import get_logger
from myrecorder.models import DownloadTaskOutput, TaskContext, UploadTaskOutput, UploaderTask, WebDAVConfig


class WebDavUploadTask(UploaderTask):
    name = "webdav"
    uploader_name = "webdav"

    def __init__(self, *, config: WebDAVConfig) -> None:
        self._uploader = _WebDAVClient(config)

    async def run(self, context: TaskContext, data: DownloadTaskOutput) -> UploadTaskOutput:
        uploaded_files: list[str] = []
        remote_paths: list[str] = []

        file_paths = data.files or tuple(path for path in (data.output, data.infojson) if path)
        for file_path in file_paths:
            path = Path(file_path)
            if not path.exists() or not path.is_file():
                context.logger.warning("上传前未找到文件，跳过: {}", path)
                continue
            context.logger.info("开始上传文件: {}", path)
            remote_path = await asyncio.to_thread(self._uploader.upload, str(path), context.target.provider, context.target.streamer)
            uploaded_files.append(str(path))
            remote_paths.append(remote_path)

        return UploadTaskOutput(
            uploaded_files=tuple(uploaded_files),
            remote_paths=tuple(remote_paths),
            metadata={"source_output": data.output},
        )


class _WebDAVClient:
    def __init__(self, config: WebDAVConfig) -> None:
        self._config = config
        self._logger = get_logger(component="uploader")
        self._obscured_password = self._obscure_password(config.password)

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
