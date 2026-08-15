from __future__ import annotations

import pytest

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode
from lib.domain.services.mapper_flow_service import MapperFlowService


def _seed_session_with_transition(session):
    repository = SqlAlchemyMapperRepository(session)
    mapper_session = repository.create_session(
        package_name="com.linkedin.android",
        mode=MapperMode.LIGHT,
        skip_dangerous_actions=True,
        max_depth=1,
        max_actions=8,
        max_scrolls=0,
    )
    screen_a = repository.create_screen(session_id=mapper_session.id, fingerprint="a", screen_key="screen-a", depth=0, ordinal=0)
    screen_b = repository.create_screen(session_id=mapper_session.id, fingerprint="b", screen_key="screen-b", depth=1, ordinal=1)
    node = repository.create_node(screen_id=screen_a.id, node_key="node-1", text="Profile", clickable=True)
    action = repository.create_action(
        session_id=mapper_session.id,
        screen_id=screen_a.id,
        node_id=node.id,
        action_key="click:profile",
        action_type="click",
        label="Profile",
        safety=MapperActionSafety.SAFE,
    )
    transition = repository.create_transition(session_id=mapper_session.id, from_screen_id=screen_a.id, action_id=action.id, to_screen_id=screen_b.id, result_type="clicked")
    return mapper_session, transition


def test_create_flow_from_manual_steps() -> None:
    with SessionLocal() as session:
        flow = MapperFlowService(session).create_flow(
            name="manual_flow",
            package_name="com.manual.testapp",
            steps=[
                {"action_type": "click", "selector": {"candidates": ["Profile"]}},
                {"action_type": "scroll_up", "selector": {}},
            ],
        )
        session.commit()

    with SessionLocal() as session:
        loaded = MapperFlowService(session).get_flow(flow.id)
        assert loaded is not None
        assert len(loaded.steps) == 2
        assert loaded.steps[0].action_type == "click"


def test_create_flow_promoted_from_session_transitions() -> None:
    with SessionLocal() as session:
        mapper_session, transition = _seed_session_with_transition(session)
        session.commit()
        session_id, transition_id = mapper_session.id, transition.id

    with SessionLocal() as session:
        flow = MapperFlowService(session).create_flow(
            name="promoted_flow",
            package_name="com.linkedin.android",
            source_session_id=session_id,
            transition_ids=[transition_id],
        )
        session.commit()
        flow_id = flow.id

    with SessionLocal() as session:
        loaded = MapperFlowService(session).get_flow(flow_id)
        assert len(loaded.steps) == 1
        step = loaded.steps[0]
        assert step.action_type == "click"
        assert step.selector_json == {"candidates": ["Profile"]}
        assert step.source_screen_id is not None
        assert step.source_action_id is not None


def test_create_flow_requires_steps_or_transitions() -> None:
    with SessionLocal() as session:
        with pytest.raises(ValueError):
            MapperFlowService(session).create_flow(name="invalid_flow", package_name="com.invalid.testapp")


def test_add_update_and_delete_step_via_service() -> None:
    with SessionLocal() as session:
        flow = MapperFlowService(session).create_flow(
            name="editable_flow",
            package_name="com.editable.testapp",
            steps=[{"action_type": "click", "selector": {"candidates": ["Profile"]}}],
        )
        session.commit()
        flow_id, step_id = flow.id, flow.steps[0].id

    with SessionLocal() as session:
        service = MapperFlowService(session)
        service.add_step(flow_id, {"action_type": "back", "selector": {}})
        session.commit()

    with SessionLocal() as session:
        service = MapperFlowService(session)
        service.update_step(step_id, action_type="click", selector={"candidates": ["Updated"]})
        session.commit()

    with SessionLocal() as session:
        loaded = MapperFlowService(session).get_flow(flow_id)
        assert len(loaded.steps) == 2
        assert loaded.steps[0].selector_json == {"candidates": ["Updated"]}

    with SessionLocal() as session:
        service = MapperFlowService(session)
        service.delete_step(step_id)
        session.commit()

    with SessionLocal() as session:
        loaded = MapperFlowService(session).get_flow(flow_id)
        assert len(loaded.steps) == 1
