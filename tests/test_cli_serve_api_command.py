from __future__ import annotations

import json
import socket

from typer.testing import CliRunner

import lib.presentation.cli.commands.root as root
from lib.core.settings import Settings
from lib.presentation.cli.commands.root import app

runner = CliRunner()


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _fake_settings(state_file) -> Settings:
    return Settings(
        app_name="autodroid", debug=False, database_url="sqlite:///:memory:", worker_name="main",
        queue_poll_interval_seconds=2.0, output_dir=state_file.parent, log_file=state_file.parent / "log",
        api_state_file=state_file, app_timezone="UTC", android_serial="127.0.0.1:5555",
        linkedin_package_name="com.linkedin.android", ocr_language="en",
        mapper_auto_remap_enabled=False, mapper_auto_remap_threshold=3,
        mapper_churn_mode="recommend", mapper_churn_window_size=8,
        mapper_churn_min_confidence=0.55, mapper_churn_aggressiveness=0.35,
    )


def test_serve_api_is_a_top_level_command() -> None:
    # never actually invoke serve-api (it blocks forever running uvicorn), --help exercises
    # command resolution without running the body
    result = runner.invoke(app, ["serve-api", "--help"])

    assert result.exit_code == 0
    assert "serve-api" in result.output.lower() or "Usage: root serve-api" in result.output


def test_serve_api_is_not_nested_under_worker() -> None:
    # the API server and the worker/dispatcher are two separate processes the user runs side
    # by side (issue #43): serve-api never touches the dispatcher, so "worker serve-api"
    # shouldn't exist anymore, only the top-level "serve-api"
    result = runner.invoke(app, ["worker", "serve-api", "--help"])

    assert result.exit_code != 0


def test_worker_group_still_has_run_and_status() -> None:
    assert runner.invoke(app, ["worker", "run", "--help"]).exit_code == 0
    assert runner.invoke(app, ["worker", "status", "--help"]).exit_code == 0


def test_serve_api_verifies_the_port_and_writes_then_clears_local_state(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "run" / "api.json"
    requested_port = _free_port()
    seen_run_args: dict = {}
    captured_state_while_running: dict = {}

    def fake_run(_app, *, host, port):  # stand-in for uvicorn.run: never actually binds/blocks
        captured_state_while_running.update(json.loads(state_file.read_text()))
        seen_run_args["host"] = host
        seen_run_args["port"] = port

    monkeypatch.setattr(root, "get_settings", lambda: _fake_settings(state_file))
    monkeypatch.setattr("uvicorn.run", fake_run)

    result = runner.invoke(app, ["serve-api", "--host", "127.0.0.1", "--port", str(requested_port)])

    assert result.exit_code == 0, result.output
    assert seen_run_args == {"host": "127.0.0.1", "port": requested_port}
    assert captured_state_while_running["host"] == "127.0.0.1"
    assert captured_state_while_running["port"] == requested_port
    assert not state_file.exists()  # cleaned up once the (fake) server returns


def test_serve_api_fails_loudly_when_the_explicit_port_is_taken(tmp_path, monkeypatch) -> None:
    # an explicit --port is a deliberate, fixed value (other tooling may already point at it),
    # so it's used as-is or the command fails clearly, it never silently swaps in another port
    # behind the user's back (issue #45, a correction to #44's first pass)
    state_file = tmp_path / "run" / "api.json"
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    taken_port = held.getsockname()[1]
    run_calls: list[int] = []

    def fake_run(_app, *, host, port):
        run_calls.append(port)

    monkeypatch.setattr(root, "get_settings", lambda: _fake_settings(state_file))
    monkeypatch.setattr("uvicorn.run", fake_run)

    try:
        result = runner.invoke(app, ["serve-api", "--host", "127.0.0.1", "--port", str(taken_port)])
    finally:
        held.close()

    assert result.exit_code != 0
    assert f"Port {taken_port} is already in use." in result.output
    assert run_calls == []  # never even tried to start
    assert not state_file.exists()  # nothing written for a port that was never actually used


def test_serve_api_auto_discovers_a_port_when_none_is_given(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "run" / "api.json"
    seen_run_args: dict = {}

    def fake_run(_app, *, host, port):
        seen_run_args["host"] = host
        seen_run_args["port"] = port

    monkeypatch.setattr(root, "get_settings", lambda: _fake_settings(state_file))
    monkeypatch.setattr(root, "DEFAULT_API_PORT", _free_port())
    monkeypatch.setattr("uvicorn.run", fake_run)

    result = runner.invoke(app, ["serve-api", "--host", "127.0.0.1"])

    assert result.exit_code == 0, result.output
    assert seen_run_args["host"] == "127.0.0.1"
    assert seen_run_args["port"] == root.DEFAULT_API_PORT
    assert f"No port specified, using {root.DEFAULT_API_PORT}" in result.output
