import logging
import os

from rich.console import Console
from rich.logging import RichHandler


DEFAULT_LOG_LEVEL = "INFO"
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _resolve_log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    level = getattr(logging, level_name, None)

    if isinstance(level, int):
        return level

    return logging.INFO


def configure_logging() -> None:
    level = _resolve_log_level()
    console = Console(stderr=True)
    handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        show_level=True,
        show_path=False,
        show_time=True,
        omit_repeated_times=False,
        log_time_format=LOG_TIME_FORMAT,
        markup=False,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
