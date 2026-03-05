from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from .config import load_config
from .logging_utils import setup_logging
from .service import RecorderService


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="我的录播器.")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件位置.")
    parser.add_argument("-s", "--streams", default="streams.yaml", help="直播主页配置文件位置.")
    parser.add_argument("--log-level", default="INFO", help="日志等级.")
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> int:
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    config = load_config(args.config, streams_path=args.streams)
    service = RecorderService(config)
    await service.start()

    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        logger.info("接收到停止指令")
        asyncio.create_task(service.stop())

    for signame in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signame, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass

    try:
        await service.run_until_stopped()
        return 0
    finally:
        await service.stop()


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"出现错误: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
