from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from lib.core.logs import LogTarget, StructuredFormatter, configure_logging


def _stream_handler(root_logger: logging.Logger) -> logging.Handler:
    # RotatingFileHandler subclasses StreamHandler too, this is how the two get told apart
    return next(h for h in root_logger.handlers if not isinstance(h, logging.FileHandler))


def test_plain_formatter_includes_source_and_line() -> None:
    formatter = StructuredFormatter(use_color=False)
    record = logging.LogRecord(
        name="lib.domain.services.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg="hello world",
        args=(),
        exc_info=None,
        func="run_test",
    )

    rendered = formatter.format(record)

    assert "INFO" in rendered
    assert "lib.domain.services.test" in rendered
    assert "run_test:42" in rendered
    assert "hello world" in rendered


def test_colored_formatter_adds_ansi_codes() -> None:
    formatter = StructuredFormatter(use_color=True)
    record = logging.LogRecord(
        name="lib.domain.services.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=84,
        msg="boom",
        args=(),
        exc_info=None,
        func="run_test",
    )

    rendered = formatter.format(record)

    assert "\033[" in rendered
    assert "boom" in rendered


def test_configure_logging_sets_cli_warning_by_default() -> None:
    configure_logging(debug=False, verbose=False, target=LogTarget.CLI)
    root_logger = logging.getLogger()
    # the root logger's own level stays at debug regardless (issue #39): the file handler
    # always captures full detail for /logs/stream, each handler's own level does the real
    # filtering, the terminal-facing one still defaults to warnings-only for a plain CLI run
    assert root_logger.level == logging.DEBUG
    assert _stream_handler(root_logger).level == logging.WARNING


def test_configure_logging_sets_api_info_by_default() -> None:
    configure_logging(debug=False, verbose=False, target=LogTarget.API)
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    assert _stream_handler(root_logger).level == logging.INFO


def test_configure_logging_without_a_log_file_adds_no_file_handler() -> None:
    configure_logging(debug=False, verbose=False, target=LogTarget.CLI, log_file=None)
    root_logger = logging.getLogger()
    assert not any(isinstance(h, logging.FileHandler) for h in root_logger.handlers)


def test_configure_logging_file_handler_always_captures_debug(tmp_path: Path) -> None:
    # a request made through the API always runs with verbose=False (issue #39): the file has to
    # stay fully detailed regardless, that's the whole point of a separate streaming channel
    log_file = tmp_path / "autodroid.log"
    configure_logging(debug=False, verbose=False, target=LogTarget.API, log_file=log_file)

    logging.getLogger("tests.test_logging").debug("a debug-level message")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "a debug-level message" in log_file.read_text()


def test_configure_logging_file_handler_rotates_instead_of_growing_forever(tmp_path: Path) -> None:
    log_file = tmp_path / "autodroid.log"
    configure_logging(debug=False, verbose=False, target=LogTarget.CLI, log_file=log_file)
    root_logger = logging.getLogger()
    file_handler = next(h for h in root_logger.handlers if isinstance(h, logging.FileHandler))
    assert isinstance(file_handler, logging.handlers.RotatingFileHandler)
    assert file_handler.maxBytes > 0
    assert file_handler.backupCount > 0
