from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import object_session

from lib.core.logs import get_logger
from lib.domain.models.job_model import Job

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTODROID_BIN = Path(sys.executable).with_name("autodroid")

logger = get_logger(__name__)


def run_job_in_subprocess(job: Job) -> dict[str, Any]:
    """Registered as the runner for every real job type in the dispatcher-facing registry
    (lib/bootstrap.py's get_dispatch_registry): actual job logic runs in this subprocess
    (`autodroid worker run-claimed-job <id>`, resolved against the *real* registry there),
    never in the dispatcher's own process. That's what lets force_stop_job() kill just this one
    job (SIGKILL to job.pid) without touching the dispatcher/worker service itself.

    job is a live ORM instance bound to the dispatcher's open session (DispatcherService.run_once
    commits the claim before calling this); recording pid onto it directly, on that same session,
    is what makes it visible to a force-stop call running in a different process as soon as this
    commits.
    """
    session = object_session(job)
    proc = subprocess.Popen(
        [str(AUTODROID_BIN), "worker", "run-claimed-job", str(job.id)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    job.pid = proc.pid
    session.commit()
    try:
        stdout, stderr = proc.communicate()
    finally:
        job.pid = None
        session.commit()
        # a force-stop happening in a different process may have set cancel_requested on this
        # same row between the commit above and now; refresh so mark_failed() sees it and
        # records CANCELLED instead of FAILED/retry-scheduled
        session.refresh(job)

    if proc.returncode != 0:
        raise RuntimeError(stderr.strip() or f"job subprocess exited with code {proc.returncode}")
    return json.loads(stdout) if stdout.strip() else {}
