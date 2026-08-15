from __future__ import annotations

import uvicorn

from lib.app import api_app, get_cli_app


def cli_entrypoint() -> None:
    get_cli_app()()


def api_entrypoint() -> None:
    uvicorn.run(api_app, host="127.0.0.1", port=8000)
