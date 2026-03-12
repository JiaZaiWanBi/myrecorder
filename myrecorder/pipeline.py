from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from myrecorder.models import AppConfig, BaseTask, StreamTarget, TaskContext
from myrecorder.registry import create_task, resolve_task_config

import myrecorder.tasks.fc2_live_dl_go  # noqa: F401
import myrecorder.tasks.streamlink  # noqa: F401
import myrecorder.tasks.webdav  # noqa: F401
import myrecorder.tasks.ytdlp  # noqa: F401


DEFAULT_WORKFLOW: tuple[str, ...] = ("yt_dlp", "webdav")


@dataclass
class PipelineResult:
    payload: dict[str, Any]
    completed_tasks: list[str] = field(default_factory=list)


class TaskPipeline:
    def __init__(self, *tasks: BaseTask) -> None:
        self._tasks = list(tasks)

    @property
    def tasks(self) -> tuple[BaseTask, ...]:
        return tuple(self._tasks)

    async def run(self, context: TaskContext, payload: dict[str, Any] | None = None) -> PipelineResult:
        payload = payload if payload is not None else {}
        completed_tasks: list[str] = []
        for task in self._tasks:
            await task.run(context, payload)
            task_name = getattr(task, "name", task.__class__.__name__)
            completed_tasks.append(task_name)
        return PipelineResult(payload=payload, completed_tasks=completed_tasks)


def resolve_workflow_steps(config: AppConfig, target: StreamTarget) -> tuple[str, ...]:
    if target.workflow is not None:
        return target.workflow
    provider_steps = config.workflow.providers.get(target.provider)
    if provider_steps is not None:
        return provider_steps
    if config.workflow.default is not None:
        return config.workflow.default
    return DEFAULT_WORKFLOW


def build_pipeline(config: AppConfig, target: StreamTarget) -> TaskPipeline:
    tasks: list[BaseTask] = []
    for task_name in resolve_workflow_steps(config, target):
        merged_config = resolve_task_config(config.tasks, target.task_overrides, task_name)
        tasks.append(create_task(task_name, merged_config))
    return TaskPipeline(*tasks)
