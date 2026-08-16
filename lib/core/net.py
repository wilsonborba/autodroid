from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path


def is_port_available(host: str, port: int) -> bool:
    """True if a socket can actually bind to (host, port) right now, not just an assumption."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
        return True


def find_available_port(host: str, preferred_port: int, *, max_attempts: int = 50) -> int:
    """Verifies `preferred_port` is actually free before the server tries to bind to it; if it's
    taken, scans forward for the next free one instead of letting uvicorn just crash on bind
    (issue #44)."""
    for offset in range(max_attempts):
        candidate = preferred_port + offset
        if is_port_available(host, candidate):
            return candidate
    raise RuntimeError(f"No available port found starting from {preferred_port} (tried {max_attempts} port(s))")


def write_api_state(path: Path, *, host: str, port: int) -> None:
    """Persists the API's actually-resolved host/port locally (issue #44), so anything that
    needs to reach it later (another local process, a helper script, ...) can read this file
    instead of guessing or scanning ports blind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": host,
        "port": port,
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload))


def clear_api_state(path: Path) -> None:
    """Removes the state file on shutdown, so a stale file never claims the API is still up."""
    path.unlink(missing_ok=True)
