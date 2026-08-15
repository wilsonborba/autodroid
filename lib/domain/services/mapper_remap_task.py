from __future__ import annotations

from typing import Any

from lib.core.logs import get_logger
from lib.core.settings import Settings
from lib.dal.local.database import session_scope
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.domain.models.job_model import Job
from lib.domain.models.mapper_types import MapperMode, MapperRunConfig
from lib.domain.services.ui_mapper_service import UiMapperService

VALID_STRATEGIES = ("override", "complement")


class MapperRemapTask:
    """Job runner for `job_type="mapper.remap"` (issue #21): re-maps a package flagged as a
    remap candidate (too many interaction failures), then resolves those failures so they stop
    counting toward future thresholds. `strategy` picks between `override` (#19, remap from
    scratch) and `complement` (#20, deepen the existing session); `override` is the default."""

    def __init__(self, settings: Settings) -> None:
        self.logger = get_logger(__name__)
        self.settings = settings

    def run(self, job: Job) -> dict[str, Any]:
        payload = job.payload_json or {}
        package_name = payload["package_name"]
        strategy = payload.get("strategy", "override")
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"Invalid remap strategy: {strategy!r}, expected one of {VALID_STRATEGIES}")
        mode = MapperMode(payload.get("mode", "medium"))

        self.logger.info("Running mapper.remap for %s (strategy=%s, mode=%s)", package_name, strategy, mode.value)
        config = MapperRunConfig(
            package_name=package_name,
            mode=mode,
            override=(strategy == "override"),
            complement=(strategy == "complement"),
        )
        result = UiMapperService(self.settings).run(config)

        with session_scope() as session:
            resolved_count = SqlAlchemyMapperFlowRepository(session).resolve_failures_for_package(package_name)
        self.logger.info("Resolved %s prior failure(s) for %s after remap", resolved_count, package_name)

        result["resolved_failures"] = resolved_count
        return result
