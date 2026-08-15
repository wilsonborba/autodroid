from __future__ import annotations

import pytest
from sqlalchemy import text

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.domain.models.mapper_types import MapperActionSafety


@pytest.fixture(autouse=True)
def _clean_flows():
    # this project's tests share the real dev DB (no per-test isolation), and MapperFlow has a
    # unique (package_name, name) constraint, so re-running these tests would otherwise collide
    # with rows left behind by a previous run.
    with SessionLocal() as session:
        session.execute(text("DELETE FROM mapper_flow_failures"))
        session.execute(text("DELETE FROM mapper_flow_step_usages"))
        session.execute(text("DELETE FROM mapper_flow_steps"))
        session.execute(text("DELETE FROM mapper_flows"))
        session.commit()
    yield


def test_create_flow_and_attach_steps() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        flow = repository.create_flow(name="extract_profile", package_name="com.linkedin.android", description="basic profile extraction")
        step_a = repository.create_step(package_name="com.linkedin.android", action_type="click", selector_json={"candidates": ["Profile"]}, safety=MapperActionSafety.SAFE)
        step_b = repository.create_step(package_name="com.linkedin.android", action_type="scroll_up", selector_json={})
        repository.attach_step(flow.id, step_a.id)
        repository.attach_step(flow.id, step_b.id)
        session.commit()
        flow_id = flow.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        loaded = repository.get_flow(flow_id)
        assert loaded is not None
        assert loaded.name == "extract_profile"
        steps = repository.ordered_steps(loaded)
        assert [step.action_type for step in steps] == ["click", "scroll_up"]


def test_step_can_be_reused_by_two_flows_without_duplicating() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        shared_step = repository.create_step(package_name="com.shared.testapp", action_type="click", selector_json={"candidates": ["Home"]})
        flow_a = repository.create_flow(name="flow_a", package_name="com.shared.testapp")
        flow_b = repository.create_flow(name="flow_b", package_name="com.shared.testapp")
        repository.attach_step(flow_a.id, shared_step.id)
        repository.attach_step(flow_b.id, shared_step.id)
        session.commit()
        step_id, flow_a_id, flow_b_id = shared_step.id, flow_a.id, flow_b.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        steps_a = repository.ordered_steps(repository.get_flow(flow_a_id))
        steps_b = repository.ordered_steps(repository.get_flow(flow_b_id))
        assert steps_a[0].id == step_id
        assert steps_b[0].id == step_id
        # only one step definition exists, referenced twice
        assert repository.get_step(step_id) is not None


def test_list_flows_filters_by_package_name() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        repository.create_flow(name="flow_a", package_name="com.filter.testapp")
        repository.create_flow(name="flow_b", package_name="com.other.testapp")
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        flows = repository.list_flows("com.filter.testapp")
        assert len(flows) == 1
        assert flows[0].name == "flow_a"


def test_update_flow_changes_name_and_description() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        flow = repository.create_flow(name="old_name", package_name="com.update.testapp")
        session.commit()
        flow_id = flow.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        repository.update_flow(flow_id, name="new_name", description="updated")
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        loaded = repository.get_flow(flow_id)
        assert loaded.name == "new_name"
        assert loaded.description == "updated"


def test_delete_flow_removes_usages_but_keeps_step_definition() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        flow = repository.create_flow(name="to_delete", package_name="com.delete.testapp")
        step = repository.create_step(package_name="com.delete.testapp", action_type="click", selector_json={})
        repository.attach_step(flow.id, step.id)
        session.commit()
        flow_id, step_id = flow.id, step.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        repository.delete_flow(flow_id)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        assert repository.get_flow(flow_id) is None
        assert repository.get_step(step_id) is not None  # step definition survives


def test_detach_step_reorders_remaining_usages() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        flow = repository.create_flow(name="reorder_flow", package_name="com.reorder.testapp")
        step_0 = repository.create_step(package_name="com.reorder.testapp", action_type="click", selector_json={})
        step_1 = repository.create_step(package_name="com.reorder.testapp", action_type="scroll_up", selector_json={})
        step_2 = repository.create_step(package_name="com.reorder.testapp", action_type="back", selector_json={})
        repository.attach_step(flow.id, step_0.id)
        repository.attach_step(flow.id, step_1.id)
        repository.attach_step(flow.id, step_2.id)
        session.commit()
        flow_id, middle_step_id = flow.id, step_1.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        repository.detach_step(flow_id, middle_step_id)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        steps = repository.ordered_steps(repository.get_flow(flow_id))
        assert [step.action_type for step in steps] == ["click", "back"]


def test_attach_step_at_explicit_ordinal_shifts_later_usages() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        flow = repository.create_flow(name="insert_flow", package_name="com.insert.testapp")
        step_click = repository.create_step(package_name="com.insert.testapp", action_type="click", selector_json={})
        step_back = repository.create_step(package_name="com.insert.testapp", action_type="back", selector_json={})
        step_scroll = repository.create_step(package_name="com.insert.testapp", action_type="scroll_up", selector_json={})
        repository.attach_step(flow.id, step_click.id)
        repository.attach_step(flow.id, step_back.id)
        session.commit()
        flow_id, scroll_step_id = flow.id, step_scroll.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        repository.attach_step(flow_id, scroll_step_id, ordinal=1)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        steps = repository.ordered_steps(repository.get_flow(flow_id))
        assert [step.action_type for step in steps] == ["click", "scroll_up", "back"]


def test_find_step_by_source_action_dedupes() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        step = repository.create_step(package_name="com.dedupe.testapp", action_type="click", selector_json={}, source_action_id=42)
        session.commit()
        step_id = step.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        found = repository.find_step_by_source_action("com.dedupe.testapp", 42)
        assert found is not None
        assert found.id == step_id
        assert repository.find_step_by_source_action("com.other.testapp", 42) is None


def test_record_failure_and_list_remap_candidates_respects_threshold() -> None:
    from lib.domain.models.mapper_types import MapperFlowFailureType

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        for _ in range(3):
            repository.record_failure(package_name="com.threshold.testapp", failure_type=MapperFlowFailureType.SELECTOR_NOT_FOUND)
        repository.record_failure(package_name="com.below.testapp", failure_type=MapperFlowFailureType.SELECTOR_NOT_FOUND)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        candidates = repository.list_remap_candidates(threshold=3)
        package_names = [name for name, _ in candidates]
        assert "com.threshold.testapp" in package_names
        assert "com.below.testapp" not in package_names
        count = dict(candidates)["com.threshold.testapp"]
        assert count == 3


def test_resolve_failures_for_package_excludes_them_from_future_candidates() -> None:
    from lib.domain.models.mapper_types import MapperFlowFailureType

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        for _ in range(3):
            repository.record_failure(package_name="com.resolve.testapp", failure_type=MapperFlowFailureType.CLICK_FAILED)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        resolved_count = repository.resolve_failures_for_package("com.resolve.testapp")
        session.commit()
        assert resolved_count == 3

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        candidates = repository.list_remap_candidates(threshold=1)
        assert "com.resolve.testapp" not in [name for name, _ in candidates]
