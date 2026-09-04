from __future__ import annotations

import json
import socket

import pytest

from lib.core.net import clear_api_state, find_available_port, is_port_available, write_api_state


def _bind_and_hold(host: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen(1)
    return sock


def test_is_port_available_true_for_a_free_port() -> None:
    probe = _bind_and_hold("127.0.0.1")
    free_port = probe.getsockname()[1]
    probe.close()  # released, should be free again (small race window, acceptable in tests)

    assert is_port_available("127.0.0.1", free_port) is True


def test_is_port_available_false_while_a_socket_holds_it() -> None:
    held = _bind_and_hold("127.0.0.1")
    taken_port = held.getsockname()[1]
    try:
        assert is_port_available("127.0.0.1", taken_port) is False
    finally:
        held.close()


def test_find_available_port_returns_the_preferred_port_when_free() -> None:
    probe = _bind_and_hold("127.0.0.1")
    free_port = probe.getsockname()[1]
    probe.close()

    assert find_available_port("127.0.0.1", free_port) == free_port


def test_find_available_port_scans_forward_when_the_preferred_one_is_taken() -> None:
    held = _bind_and_hold("127.0.0.1")
    taken_port = held.getsockname()[1]
    try:
        resolved = find_available_port("127.0.0.1", taken_port)
        assert resolved != taken_port
        assert is_port_available("127.0.0.1", resolved)
    finally:
        held.close()


def test_find_available_port_raises_when_nothing_free_within_max_attempts() -> None:
    held = _bind_and_hold("127.0.0.1")
    taken_port = held.getsockname()[1]
    try:
        with pytest.raises(RuntimeError):
            find_available_port("127.0.0.1", taken_port, max_attempts=1)
    finally:
        held.close()


def test_write_and_clear_api_state(tmp_path) -> None:
    state_file = tmp_path / "run" / "api.json"

    write_api_state(state_file, host="0.0.0.0", port=7777)

    assert state_file.exists()
    payload = json.loads(state_file.read_text())
    assert payload["host"] == "0.0.0.0"
    assert payload["port"] == 7777
    assert "pid" in payload
    assert "started_at" in payload

    clear_api_state(state_file)

    assert not state_file.exists()


def test_clear_api_state_is_a_no_op_when_nothing_to_clear(tmp_path) -> None:
    clear_api_state(tmp_path / "never-written.json")
