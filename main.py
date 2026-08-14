from __future__ import annotations

from lib.app import api_app, get_cli_app


def cli_entrypoint() -> None:
    get_cli_app()()


def api_entrypoint() -> None:
    return api_app


if __name__ == "__main__":
    cli_entrypoint()
