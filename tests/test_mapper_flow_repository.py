from __future__ import annotations

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.domain.models.mapper_types import MapperActionSafety


def test_create_flow_and_add_steps() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        flow = repository.create_flow(name="extract_profile", package_name="com.linkedin.android", description="basic profile extraction")
        repository.add_step(flow.id, action_type="click", selector_json={"candidates": ["Profile"]}, safety=MapperActionSafety.SAFE)
        repository.add_step(flow.id, action_type="scroll_up", selector_json={})
        session.commit()
        flow_id = flow.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        loaded = repository.get_flow(flow_id)
        assert loaded is not None
        assert loaded.name == "extract_profile"
        assert [step.ordinal for step in loaded.steps] == [0, 1]
        assert loaded.steps[0].action_type == "click"


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


def test_delete_flow_cascades_to_steps() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        flow = repository.create_flow(name="to_delete", package_name="com.delete.testapp")
        repository.add_step(flow.id, action_type="click", selector_json={})
        session.commit()
        flow_id = flow.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        repository.delete_flow(flow_id)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        assert repository.get_flow(flow_id) is None


def test_delete_step_reorders_remaining_steps() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        flow = repository.create_flow(name="reorder_flow", package_name="com.reorder.testapp")
        repository.add_step(flow.id, action_type="click", selector_json={})
        step_1 = repository.add_step(flow.id, action_type="scroll_up", selector_json={})
        repository.add_step(flow.id, action_type="back", selector_json={})
        session.commit()
        flow_id, middle_step_id = flow.id, step_1.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        repository.delete_step(middle_step_id)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        loaded = repository.get_flow(flow_id)
        assert [step.ordinal for step in loaded.steps] == [0, 1]
        assert [step.action_type for step in loaded.steps] == ["click", "back"]


def test_add_step_at_explicit_ordinal_shifts_later_steps() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        flow = repository.create_flow(name="insert_flow", package_name="com.insert.testapp")
        repository.add_step(flow.id, action_type="click", selector_json={})
        repository.add_step(flow.id, action_type="back", selector_json={})
        session.commit()
        flow_id = flow.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        repository.add_step(flow_id, action_type="scroll_up", selector_json={}, ordinal=1)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        loaded = repository.get_flow(flow_id)
        assert [step.action_type for step in loaded.steps] == ["click", "scroll_up", "back"]
        assert [step.ordinal for step in loaded.steps] == [0, 1, 2]
