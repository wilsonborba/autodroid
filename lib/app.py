from __future__ import annotations

from lib.bootstrap import create_api_app, create_dispatcher
from lib.presentation.cli.commands.root import app as cli_app

api_app = create_api_app()

def get_cli_app():
    return cli_app


def get_dispatcher():
    return create_dispatcher()
