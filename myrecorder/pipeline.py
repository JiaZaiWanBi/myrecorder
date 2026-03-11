from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from myrecorder.models import AppConfig, BaseTask, StreamTarget, TaskContext, WorkflowState
from myrecorder.registry import create_task, is_task_enabled


DEFAULT_WORKFLOW: tuple[str, ...] = ("yt_dlp", "webdav")


@dataclass
class PipelineResult:
    state: WorkflowState
    completed_tasks: list[str] = field(default_factory=list)


class TaskPipeline:
    def __init__(self, *tasks: BaseTask) -> None:
        self._tasks = list(tasks)

    @property
    def tasks(self) -> tuple[BaseTask, ...]:
        return tuple(self._tasks)

    def append(self, task: BaseTask) -> None:
        self._tasks.append(task)

    async def run(self, context: TaskContext, state: WorkflowState) -> PipelineResult:
        completed_tasks: list[str] = []
        for task in self._tasks:
            await task.run(context, state)
            task_name = getattr(task, "name", task.__class__.__name__)
            completed_tasks.append(task_name)
        return PipelineResult(state=state, completed_tasks=completed_tasks)


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
        if not is_task_enabled(task_name, config):
            continue
        tasks.append(create_task(task_name, config))
    return TaskPipeline(*tasks)
