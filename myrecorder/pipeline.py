from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from myrecorder.models import AppConfig, BaseTask, LiveStatus, ProviderTask, StreamTarget, TaskContext
from myrecorder.registry import (
    DOWNLOADER_REGISTRY,
    UPLOADER_REGISTRY,
    create_downloader_task,
    create_uploader_task,
    get_provider_definition,
    resolve_downloader_name,
)


DEFAULT_WORKFLOW: tuple[str, ...] = ("download", "upload")


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
            if isinstance(data, LiveStatus) and not data.is_live and not isinstance(task, ProviderTask):
                break
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
    provider_definition = get_provider_definition(target.provider)
    if provider_definition.default_workflow:
        return provider_definition.default_workflow
    if config.workflow.default is not None:
        return config.workflow.default
    return DEFAULT_WORKFLOW


def build_pipeline(config: AppConfig, target: StreamTarget, provider_task: ProviderTask | None = None) -> TaskPipeline:
    tasks: list[BaseTask[Any, Any]] = []
    if provider_task is not None:
        tasks.append(provider_task)
    for step in resolve_workflow_steps(config, target):
        normalized_step = step.strip().lower()
        if normalized_step == "download":
            tasks.append(create_downloader_task(resolve_downloader_name(target, target.provider)))
            continue
        if normalized_step == "upload":
            if config.webdav is None:
                continue
            tasks.append(create_uploader_task("webdav"))
            continue
        if normalized_step in DOWNLOADER_REGISTRY:
            tasks.append(create_downloader_task(normalized_step))
            continue
        if normalized_step in UPLOADER_REGISTRY:
            tasks.append(create_uploader_task(normalized_step))
            continue
        raise ValueError(f"unsupported workflow step: {step}")
    return TaskPipeline(*tasks)
