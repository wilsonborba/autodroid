from __future__ import annotations

import logging

from lib.core.logs import LogTarget, StructuredFormatter, configure_logging


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
    assert logging.getLogger().level == logging.WARNING


def test_configure_logging_sets_api_info_by_default() -> None:
    configure_logging(debug=False, verbose=False, target=LogTarget.API)
    assert logging.getLogger().level == logging.INFO
