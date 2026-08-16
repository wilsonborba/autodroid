from __future__ import annotations

import sys
import os

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


def test_serve_api_flag_enables_dangerous_actions(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.delenv("AUTODROID_ALLOW_DANGEROUS_ACTIONS", raising=False)
    monkeypatch.setattr("lib.presentation.cli.commands.root.is_port_available", lambda host, port: True)
    monkeypatch.setattr("lib.presentation.cli.commands.root.write_api_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("lib.presentation.cli.commands.root.clear_api_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("lib.presentation.cli.commands.root.get_settings", __import__("lib.bootstrap", fromlist=["get_settings"]).get_settings)

    def fake_run(app_obj, host, port):
        calls["host"] = host
        calls["port"] = port
        calls["allow_dangerous_actions"] = os.getenv("AUTODROID_ALLOW_DANGEROUS_ACTIONS")

    monkeypatch.setattr("uvicorn.run", fake_run)

    result = runner.invoke(app, ["serve-api", "--host", "127.0.0.1", "--port", "7777", "--allow-dangerous-actions"])

    assert result.exit_code == 0
    assert calls == {"host": "127.0.0.1", "port": 7777, "allow_dangerous_actions": "true"}
    assert "Dangerous action blocker disabled" in result.output
