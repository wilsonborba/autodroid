from __future__ import annotations

import os
from pathlib import Path

# Must run before anything imports lib.dal.local.database (which resolves AUTODROID_DATABASE_URL
# once, at module import time): forcing an isolated default here, ahead of that first import,
# means nobody has to remember to export the variable by hand before running pytest. That's
# exactly the step that already got skipped twice in this project's history (issue #29, and the
# incident this file exists to close), and it happens by forgetting, not by choice, so removing
# the step is the only fix that actually holds. `setdefault` still lets a developer point tests at
# a different isolated database on purpose (e.g. to inspect it after a run), just never silently
# falls through to the real one.
_TEST_DB_PATH = Path(__file__).resolve().parent.parent / "lib" / "dal" / "var" / "test_autodroid.db"
os.environ.setdefault("AUTODROID_DATABASE_URL", f"sqlite:///{_TEST_DB_PATH}")

from alembic.command import upgrade  # noqa: E402 - import order matters, see above
from alembic.config import Config  # noqa: E402

from lib.dal.local.database import engine  # noqa: E402

ALEMBIC_INI_PATH = "lib/dal/alembic.ini"


def pytest_configure(config) -> None:
    db_url = str(engine.url)
    # same check reset_db() already did per test file (now redundant with it, kept as the last
    # line of defense): refuses instead of guessing whenever an explicit, hand-set
    # AUTODROID_DATABASE_URL still happens to point at the real database.
    if "lib/dal/var/autodroid.db" in db_url or "test" not in db_url.lower():
        raise RuntimeError(
            f"Refusing to run tests against {db_url!r}: it looks like the real database, not an "
            "isolated test one. AUTODROID_DATABASE_URL was set explicitly to something unsafe."
        )
    # fresh schema every session, not just "created once and reused": a stale isolated database
    # left over from an older schema version, or from a previous run's accumulated rows, is
    # exactly what made test_mapper_route_repository.py flaky (sample_count kept growing instead
    # of starting at 1). Migrating from scratch each time removes that class of flakiness too.
    if _TEST_DB_PATH.exists():
        _TEST_DB_PATH.unlink()
    upgrade(Config(ALEMBIC_INI_PATH), "head")
