from __future__ import annotations

import logging
import os
import sys
from enum import Enum


class LogTarget(str, Enum):
    CLI = "cli"
    API = "api"


RESET = "\033[0m"
LEVEL_COLORS = {
    logging.DEBUG: "\033[38;5;244m",
    logging.INFO: "\033[38;5;39m",
    logging.WARNING: "\033[38;5;220m",
    logging.ERROR: "\033[38;5;196m",
    logging.CRITICAL: "\033[1;38;5;196m",
}
SOURCE_COLOR = "\033[38;5;45m"
TIMESTAMP_COLOR = "\033[38;5;250m"
MESSAGE_COLOR = "\033[38;5;255m"

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class StructuredFormatter(logging.Formatter):
    def __init__(self, *, use_color: bool) -> None:
        super().__init__(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt)
        level = f"{record.levelname:<8}"
        source = f"{record.name}"
        location = f"{record.funcName}:{record.lineno}"
        message = record.getMessage()

        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            message = f"{message}\n{exc_text}"

        if not self.use_color:
            return f"{timestamp} | {level} | {source} | {location} | {message}"

        timestamp = f"{TIMESTAMP_COLOR}{timestamp}{RESET}"
        level = f"{LEVEL_COLORS.get(record.levelno, '')}{level}{RESET}"
        source = f"{SOURCE_COLOR}{source}{RESET}"
        location = f"{SOURCE_COLOR}{location}{RESET}"
        message = f"{MESSAGE_COLOR}{message}{RESET}"
        return f"{timestamp} | {level} | {source} | {location} | {message}"


class CliFilter(logging.Filter):
    def __init__(self, verbose: bool) -> None:
        super().__init__()
        self.verbose = verbose

    def filter(self, record: logging.LogRecord) -> bool:
        if self.verbose:
            return True
        return record.levelno >= logging.WARNING


def _should_use_color(target: LogTarget) -> bool:
    if os.getenv("NO_COLOR"):
        return False
    stream = sys.stderr if target == LogTarget.CLI else sys.stdout
    return hasattr(stream, "isatty") and stream.isatty()


def _resolve_level(*, debug: bool, verbose: bool, target: LogTarget) -> int:
    if debug or verbose:
        return logging.DEBUG
    if target == LogTarget.API:
        return logging.INFO
    return logging.WARNING


def configure_logging(*, debug: bool, verbose: bool = False, target: LogTarget = LogTarget.CLI) -> None:
    level = _resolve_level(debug=debug, verbose=verbose, target=target)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    stream = sys.stderr if target == LogTarget.CLI else sys.stdout
    handler = logging.StreamHandler(stream)
    handler.setLevel(level)
    handler.setFormatter(StructuredFormatter(use_color=_should_use_color(target)))
    if target == LogTarget.CLI:
        handler.addFilter(CliFilter(verbose=verbose))
    root_logger.addHandler(handler)

    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access", "httpx"]:
        third_party = logging.getLogger(logger_name)
        third_party.setLevel(logging.INFO if target == LogTarget.API else logging.WARNING)
        third_party.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
