from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from lib.dal.local.database import Base, engine
from lib.domain.models import job_model, worker_state_model

# imported for their side effect (registering their tables on Base.metadata before
# `db revision --autogenerate` diffs against it), not used directly; the `# noqa: F401` this
# used to carry only silences flake8, not pyflakes, so reference them explicitly instead
_imported_for_autogenerate = (job_model, worker_state_model)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# reuses the app's own engine (which already resolves AUTODROID_DATABASE_URL, see
# lib/dal/local/database.py) instead of the hardcoded sqlalchemy.url in alembic.ini, so a test
# run pointed at an isolated database also migrates that database, never the real one by mistake.


def run_migrations_offline() -> None:
    context.configure(url=str(engine.url), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
