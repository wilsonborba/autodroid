from __future__ import annotations

from typer.testing import CliRunner

from lib.presentation.cli.commands.root import app

runner = CliRunner()


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
