from __future__ import annotations

import pytest

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.domain.models.mapper_types import MapperFlowFailureType
from lib.domain.services.mapper_remap_task import MapperRemapTask


class FakeJob:
    def __init__(self, payload_json: dict) -> None:
        self.payload_json = payload_json


class FakeUiMapperService:
    last_config = None

    def __init__(self, settings) -> None:
        pass

    def run(self, config):
        FakeUiMapperService.last_config = config
        return {"session_id": 1, "package_name": config.package_name, "status": "completed"}


def test_remap_task_runs_override_by_default(monkeypatch) -> None:
    monkeypatch.setattr("lib.domain.services.mapper_remap_task.UiMapperService", FakeUiMapperService)
    task = MapperRemapTask(settings=object())

    result = task.run(FakeJob({"package_name": "com.remaptask.testapp"}))

    assert FakeUiMapperService.last_config.package_name == "com.remaptask.testapp"
    assert FakeUiMapperService.last_config.override is True
    assert FakeUiMapperService.last_config.complement is False
    assert result["package_name"] == "com.remaptask.testapp"
    assert "resolved_failures" in result


def test_remap_task_supports_complement_strategy(monkeypatch) -> None:
    monkeypatch.setattr("lib.domain.services.mapper_remap_task.UiMapperService", FakeUiMapperService)
    task = MapperRemapTask(settings=object())

    task.run(FakeJob({"package_name": "com.remaptask2.testapp", "strategy": "complement", "mode": "deep"}))

    assert FakeUiMapperService.last_config.override is False
    assert FakeUiMapperService.last_config.complement is True
    assert FakeUiMapperService.last_config.mode.value == "deep"


def test_remap_task_rejects_invalid_strategy(monkeypatch) -> None:
    monkeypatch.setattr("lib.domain.services.mapper_remap_task.UiMapperService", FakeUiMapperService)
    task = MapperRemapTask(settings=object())

    with pytest.raises(ValueError):
        task.run(FakeJob({"package_name": "com.remaptask3.testapp", "strategy": "nonsense"}))


def test_remap_task_resolves_prior_failures(monkeypatch) -> None:
    monkeypatch.setattr("lib.domain.services.mapper_remap_task.UiMapperService", FakeUiMapperService)
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        repository.record_failure(package_name="com.remaptask4.testapp", failure_type=MapperFlowFailureType.CLICK_FAILED)
        repository.record_failure(package_name="com.remaptask4.testapp", failure_type=MapperFlowFailureType.CLICK_FAILED)
        session.commit()

    task = MapperRemapTask(settings=object())
    result = task.run(FakeJob({"package_name": "com.remaptask4.testapp"}))

    assert result["resolved_failures"] == 2

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        candidate_names = [name for name, _ in repository.list_remap_candidates(threshold=1)]
        assert "com.remaptask4.testapp" not in candidate_names
