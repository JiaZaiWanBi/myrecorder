from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class KnownLogEvent:
    logger_name: str
    message_substring: str
    rewritten_message: str
    level: str = "WARNING"


KNOWN_LOG_EVENTS: tuple[KnownLogEvent, ...] = (
    KnownLogEvent(
        logger_name="websockets.client",
        message_substring="keepalive ping failed",
        rewritten_message="录制过程出现波动！",
    ),
)


class KnownWebsocketsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        known_event = _match_known_log_event(record)
        if known_event is None:
            return True
        logger.bind(component=record.name).log(known_event.level, known_event.rewritten_message)
        return False


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:

        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.bind(component=record.name).opt(
            depth=depth,
            exception=record.exc_info,
        ).log(level, record.getMessage())


def _match_known_log_event(record: logging.LogRecord) -> KnownLogEvent | None:
    message = record.getMessage().lower()
    for event in KNOWN_LOG_EVENTS:
        if record.name == event.logger_name and event.message_substring in message:
            return event
    return None


def _patch_record(record: dict[str, Any]) -> None:
    extra = record["extra"]
    extra.setdefault("component", "app")
    extra.setdefault("provider", "-")
    extra.setdefault("streamer", "-")


def configure_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.configure(
        patcher=_patch_record,
        handlers=[
            {
                "sink": sys.stderr,
                "level": level.upper(),
                "backtrace": False,
                "diagnose": False,
                "enqueue": True,
                "format": (
                    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
                    "<level>{level: <8}</level> "
                    "<cyan>{extra[component]}</cyan> "
                    "<magenta>{extra[provider]}</magenta>/"
                    "<magenta>{extra[streamer]}</magenta>: "
                    "<level>{message}</level>"
                ),
            }
        ],
    )

    intercept = InterceptHandler()
    known_websockets_filter = KnownWebsocketsFilter()
    logging.root.handlers = [intercept]
    logging.root.setLevel(logging.NOTSET)

    redirected_loggers = (
        "websockets",
        "websockets.client",
        "websockets.server",
        "yt_dlp",
        "urllib3",
        "aiohttp",
    )
    for name in redirected_loggers:
        std_logger = logging.getLogger(name)
        std_logger.handlers = [intercept]
        std_logger.filters.clear()
        if name.startswith("websockets"):
            std_logger.addFilter(known_websockets_filter)
        std_logger.propagate = False
        std_logger.disabled = False
        std_logger.setLevel(logging.WARNING)


def get_logger(*, component: str, provider: str = "-", streamer: str = "-"):
    return logger.bind(component=component, provider=provider, streamer=streamer)
