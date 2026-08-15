from __future__ import annotations

from fastapi.testclient import TestClient

from lib.bootstrap import create_api_app


class _FakeSettings:
    def __init__(self, log_file) -> None:
        self.log_file = log_file


def test_stream_logs_sends_only_new_lines_written_after_connecting(tmp_path, monkeypatch) -> None:
    log_file = tmp_path / "autodroid.log"
    log_file.write_text("old line, already there before connecting\n")
    monkeypatch.setattr("lib.presentation.api.routes.logs_stream.get_settings", lambda: _FakeSettings(log_file))
    monkeypatch.setattr("lib.presentation.api.routes.logs_stream.POLL_INTERVAL_SECONDS", 0.01)

    client = TestClient(create_api_app())
    with client.websocket_connect("/logs/stream") as websocket:
        with log_file.open("a") as handle:
            handle.write("new line after connecting\n")
            handle.flush()
        received = websocket.receive_text()

    assert received == "new line after connecting"


def test_stream_logs_waits_for_the_file_to_exist_first(tmp_path, monkeypatch) -> None:
    log_file = tmp_path / "not-created-yet" / "autodroid.log"
    monkeypatch.setattr("lib.presentation.api.routes.logs_stream.get_settings", lambda: _FakeSettings(log_file))
    monkeypatch.setattr("lib.presentation.api.routes.logs_stream.POLL_INTERVAL_SECONDS", 0.01)

    client = TestClient(create_api_app())
    with client.websocket_connect("/logs/stream") as websocket:
        log_file.parent.mkdir()
        log_file.write_text("first line ever\n")
        received = websocket.receive_text()

    assert received == "first line ever"


def test_stream_logs_recovers_after_the_file_rotates(tmp_path, monkeypatch) -> None:
    # a rotation (issue #39's size cap) replaces the file with a fresh, smaller one mid-stream
    log_file = tmp_path / "autodroid.log"
    log_file.write_text("x" * 1000 + "\n")
    monkeypatch.setattr("lib.presentation.api.routes.logs_stream.get_settings", lambda: _FakeSettings(log_file))
    monkeypatch.setattr("lib.presentation.api.routes.logs_stream.POLL_INTERVAL_SECONDS", 0.01)

    client = TestClient(create_api_app())
    with client.websocket_connect("/logs/stream") as websocket:
        log_file.write_text("line after rotation\n")
        received = websocket.receive_text()

    assert received == "line after rotation"
