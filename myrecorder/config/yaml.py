from __future__ import annotations

from typing import Any

import yaml


def load_yaml(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as file:
        return yaml.safe_load(file) or {}


def load_yaml_dict(path: str) -> dict[str, Any]:
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是有效的 YAML 对象")
    return data
