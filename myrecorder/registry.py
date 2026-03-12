from __future__ import annotations

from copy import deepcopy
from typing import Any, Type


class Registry:
    _providers: dict[str, Type] = {}
    _tasks: dict[str, Type] = {}

    @classmethod
    def register_provider(cls, name: str):
        def wrapper(provider_cls: Type) -> Type:
            cls._providers[name] = provider_cls
            return provider_cls
        return wrapper

    @classmethod
    def register_task(cls, name: str):
        def wrapper(task_cls: Type) -> Type:
            cls._tasks[name] = task_cls
            return task_cls
        return wrapper

    @classmethod
    def get_provider(cls, name: str) -> Type:
        try:
            return cls._providers[name]
        except KeyError as exc:
            raise ValueError(f"Provider '{name}' not found. Did you import it?") from exc

    @classmethod
    def get_task(cls, name: str) -> Type:
        try:
            return cls._tasks[name]
        except KeyError as exc:
            raise ValueError(f"Task '{name}' not found.") from exc

    @classmethod
    def supported_providers(cls) -> tuple[str, ...]:
        return tuple(cls._providers.keys())

    @classmethod
    def supported_tasks(cls) -> tuple[str, ...]:
        return tuple(cls._tasks.keys())


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def resolve_task_config(global_config: dict[str, dict[str, Any]], target_overrides: dict[str, dict[str, Any]], task_name: str) -> dict[str, Any]:
    base = global_config.get(task_name, {})
    override = target_overrides.get(task_name, {})
    return deep_merge(base, override)


def create_provider_task(
    name: str,
    *,
    session: Any,
    timeout_seconds: int,
    retries: int,
):
    provider_cls = Registry.get_provider(name.strip().lower())
    return provider_cls(session=session, timeout_seconds=timeout_seconds, retries=retries)


def create_task(name: str, task_config: dict[str, Any]):
    task_cls = Registry.get_task(name.strip().lower())
    return task_cls(task_config=task_config)


def supported_providers() -> tuple[str, ...]:
    return Registry.supported_providers()


def supported_tasks() -> tuple[str, ...]:
    return Registry.supported_tasks()
