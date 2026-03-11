from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from myrecorder.models import AppConfig, BaseTask, StreamTarget, TaskContext
from myrecorder.registry import create_task, is_task_enabled


DEFAULT_WORKFLOW: tuple[str, ...] = ("yt_dlp", "webdav")


@dataclass
class PipelineResult:
    final_data: Any
    step_results: list[tuple[str, Any]] = field(default_factory=list)


class TaskPipeline:
    def __init__(self, *tasks: BaseTask[Any, Any]) -> None:
        self._tasks = list(tasks)

    @property
    def tasks(self) -> tuple[BaseTask[Any, Any], ...]:
        return tuple(self._tasks)

    def append(self, task: BaseTask[Any, Any]) -> None:
        self._tasks.append(task)

    async def run(self, context: TaskContext, initial_data: Any = None) -> PipelineResult:
        data = initial_data
        step_results: list[tuple[str, Any]] = []
        for task in self._tasks:
            data = await task.run(context, data)
            task_name = getattr(task, "name", task.__class__.__name__)
            step_results.append((task_name, data))
        return PipelineResult(final_data=data, step_results=step_results)


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
    tasks: list[BaseTask[Any, Any]] = []
    for task_name in resolve_workflow_steps(config, target):
        if not is_task_enabled(task_name, config):
            continue
        tasks.append(create_task(task_name, config))
    return TaskPipeline(*tasks)
