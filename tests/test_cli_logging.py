from __future__ import annotations

import sys

from typer.testing import CliRunner

from lib.presentation.cli.commands.root import app

runner = CliRunner()


def test_cli_invocation_is_logged_at_debug_level(caplog, monkeypatch) -> None:
    # CliRunner.invoke() calls the command programmatically, it never touches the real process
    # sys.argv the way an actual `autodroid ...` invocation does, so sys.argv is set directly
    # here to exercise exactly what production code reads
    caplog.set_level("DEBUG")
    monkeypatch.setattr(sys, "argv", ["autodroid", "worker", "status"])

    result = runner.invoke(app, ["worker", "status"])

    assert result.exit_code == 0
    messages = [record.message for record in caplog.records]
    assert any(message == "CLI invoked: worker status" for message in messages)
    assert any(message.startswith("CLI finished: worker status") for message in messages)
