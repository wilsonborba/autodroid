from __future__ import annotations

from lib.domain.models.job_model import Job


class JobFormatter:
    @staticmethod
    def format(job: Job) -> str:
        return f"#{job.id} {job.job_type} [{job.status.value}] priority={job.priority}"
