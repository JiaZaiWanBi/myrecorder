from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from myrecorder.config import load_app_config
from myrecorder.log import configure_logging, get_logger
from myrecorder.models import AppConfig
from myrecorder.services import run_watchers


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NicoChannel/FC2 直播录制器")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("-s", "--streams", default="streams.yaml", help="直播目标文件路径")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    return parser.parse_args(argv)


def load_config(config_path: str, streams_path: str) -> AppConfig:
    return load_app_config(config_path, streams_path)


async def _async_main(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)
    config = load_config(args.config, args.streams)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    get_logger(component="app").info(
        "已从 {} 加载 {} 个直播目标",
        args.streams,
        len(config.streams),
    )
    return await run_watchers(config, streams_path=args.streams)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        return 0
    except Exception:
        get_logger(component="app").exception("程序运行失败")
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
