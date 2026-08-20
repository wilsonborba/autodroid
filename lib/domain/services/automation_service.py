from __future__ import annotations

from collections.abc import Callable
from typing import Any

from lib.domain.models.job_model import Job

JobRunner = Callable[[Job], dict[str, Any]]


class AutomationRegistryService:
    def __init__(self) -> None:
        self._registry: dict[str, JobRunner] = {}

    def register(self, job_type: str, runner: JobRunner) -> None:
        self._registry[job_type] = runner

    def get_runner(self, job_type: str) -> JobRunner:
        try:
            return self._registry[job_type]
        except KeyError as exc:
            raise ValueError(f"No runner registered for job type {job_type}") from exc

    def job_types(self) -> list[str]:
        return list(self._registry)
