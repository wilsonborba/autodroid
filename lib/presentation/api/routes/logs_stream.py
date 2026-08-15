from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from lib.presentation.api.dependencies import get_settings

# deliberately not under /mapper or /device: this tails whatever the process is logging right
# now, mapping, a flow run, a job, an on-demand action, all of it, not one specific phase (#39)
router = APIRouter(tags=["logs"])

POLL_INTERVAL_SECONDS = 0.3


async def _tail(path: Path, *, poll_interval: float = POLL_INTERVAL_SECONDS) -> AsyncIterator[str]:
    # only skip to the end when the file was already there: if it didn't exist yet, this call
    # was watching from before the very first byte, there's no history to skip past. Skipping
    # unconditionally after the wait loop below would also skip whatever got written the moment
    # the file first appeared, exactly the content that ended the wait.
    already_had_content = path.exists()
    while not path.exists():
        await asyncio.sleep(poll_interval)
    handle = path.open("r", errors="replace")
    try:
        if already_had_content:
            handle.seek(0, 2)  # start at the end: only what's written from now on, not the whole history
        position = handle.tell()
        while True:
            line = handle.readline()
            if line:
                position = handle.tell()
                yield line.rstrip("\n")
                continue
            # a rotation (issue #39's size cap) replaces the file with a fresh, smaller one: the
            # size shrinking under us is the signal to reopen from the start, a rotated-out
            # backup isn't "happening right now" anyway, nothing worth replaying from it
            if path.exists() and path.stat().st_size < position:
                handle.close()
                handle = path.open("r", errors="replace")
                position = 0
            await asyncio.sleep(poll_interval)
    finally:
        handle.close()


@router.websocket("/logs/stream")
async def stream_logs(websocket: WebSocket) -> None:
    """Streams the log file live, line by line, exactly as it's being written (the same content
    --verbose shows in a CLI terminal, issue #39). Useful to fire a request against /mapper or
    /device/actions and watch, in a separate connection, what the backend is actually doing
    while it runs, instead of only seeing the final response.

    Connects, then starts at the end of the current log file (no history replay), and pushes
    each new line as a text frame as soon as it's written, from any part of the process, CLI or
    API, mapping, a Flow run, a job, an on-demand action. The file rotates once it gets large
    (issue #39), that's handled transparently, nothing to do on the client side.

    WebSocket routes aren't part of the OpenAPI schema FastAPI generates (no summary/description
    parameter exists for them, this docstring is the documentation for anyone reading the code).
    """
    await websocket.accept()
    settings = get_settings()
    try:
        async for line in _tail(settings.log_file):
            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
