from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from enum import Enum
from pathlib import Path


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

# bounds how big the log file (and /logs/stream's history) can get: 5MB active + 3 rotated
# backups, 20MB total ceiling, debug-level detail across a whole process adds up fast otherwise
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 3


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


def configure_logging(*, debug: bool, verbose: bool = False, target: LogTarget = LogTarget.CLI, log_file: Path | None = None) -> None:
    level = _resolve_level(debug=debug, verbose=verbose, target=target)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    # the root logger's own level has to stay at the lowest anything might want: the file
    # handler below always captures full debug detail for /logs/stream to tail (issue #39),
    # regardless of --verbose or of the CLI/API target, a record filtered out here never even
    # reaches a handler to decide about individually. Each handler's own level is what actually
    # controls what it emits.
    root_logger.setLevel(logging.DEBUG)

    stream = sys.stderr if target == LogTarget.CLI else sys.stdout
    stream_handler = logging.StreamHandler(stream)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(StructuredFormatter(use_color=_should_use_color(target)))
    if target == LogTarget.CLI:
        stream_handler.addFilter(CliFilter(verbose=verbose))
    root_logger.addHandler(stream_handler)

    if log_file is not None:
        # rotates instead of growing forever (issue #39 follow-up): debug-level detail across
        # the whole process adds up fast, a handful of bounded files stay easy to open/tail,
        # an unbounded one eventually doesn't
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=LOG_FILE_MAX_BYTES, backupCount=LOG_FILE_BACKUP_COUNT)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(StructuredFormatter(use_color=False))
        root_logger.addHandler(file_handler)

    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access", "httpx"]:
        third_party = logging.getLogger(logger_name)
        third_party.setLevel(logging.INFO if target == LogTarget.API else logging.WARNING)
        third_party.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
