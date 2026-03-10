from __future__ import annotations

import asyncio
from pathlib import Path

from myrecorder.models import DownloadTaskOutput, TaskContext, UploadTaskOutput, UploaderTask
from myrecorder.uploader import WebDAVUploader


class WebDavUploadTask(UploaderTask):
    name = "webdav"
    uploader_name = "webdav"

    async def run(self, context: TaskContext, data: DownloadTaskOutput) -> UploadTaskOutput:
        if context.config.webdav is None:
            raise ValueError("webdav task requires webdav config")

        uploader = WebDAVUploader(context.config.webdav)
        uploaded_files: list[str] = []
        remote_paths: list[str] = []

        file_paths = data.files or tuple(path for path in (data.output, data.infojson) if path)
        for file_path in file_paths:
            path = Path(file_path)
            if not path.exists() or not path.is_file():
                context.logger.warning("上传前未找到文件，跳过: {}", path)
                continue
            context.logger.info("开始上传文件: {}", path)
            remote_path = await asyncio.to_thread(uploader.upload, str(path), context.target)
            uploaded_files.append(str(path))
            remote_paths.append(remote_path)

        return UploadTaskOutput(
            uploaded_files=tuple(uploaded_files),
            remote_paths=tuple(remote_paths),
            metadata={"source_output": data.output},
        )
