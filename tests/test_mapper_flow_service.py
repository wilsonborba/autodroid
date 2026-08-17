from __future__ import annotations

import pytest
from sqlalchemy import text

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode
from lib.domain.services.mapper_flow_service import MapperFlowService


@pytest.fixture(autouse=True)
def _clean_flows():
    # this project's tests share the real dev DB (no per-test isolation), and MapperFlow has a
    # unique (package_name, name) constraint, so re-running these tests would otherwise collide
    # with rows left behind by a previous run.
    with SessionLocal() as session:
        session.execute(text("DELETE FROM mapper_flow_step_usages"))
        session.execute(text("DELETE FROM mapper_flow_steps"))
        session.execute(text("DELETE FROM mapper_flows"))
        session.commit()
    yield


def _seed_two_screen_session(session, package_name="com.linkedin.android"):
    repository = SqlAlchemyMapperRepository(session)
    mapper_session = repository.create_session(
        package_name=package_name,
        mode=MapperMode.LIGHT,
        skip_dangerous_actions=True,
        max_depth=2,
        max_actions=8,
        max_scrolls=0,
    )
    screen_root = repository.create_screen(session_id=mapper_session.id, fingerprint="root", screen_key="root", depth=0, ordinal=0)
    screen_a = repository.create_screen(session_id=mapper_session.id, fingerprint="a", screen_key="screen-a", depth=1, ordinal=1)
    screen_b = repository.create_screen(session_id=mapper_session.id, fingerprint="b", screen_key="screen-b", depth=2, ordinal=2)

    node_open_profile = repository.create_node(screen_id=screen_root.id, node_key="node-open-profile", text="Profile", clickable=True)
    action_open_profile = repository.create_action(
        session_id=mapper_session.id, screen_id=screen_root.id, node_id=node_open_profile.id,
        action_key="click:profile", action_type="click", label="Profile", safety=MapperActionSafety.SAFE,
    )
    transition_root_to_a = repository.create_transition(session_id=mapper_session.id, from_screen_id=screen_root.id, action_id=action_open_profile.id, to_screen_id=screen_a.id, result_type="clicked")

    node_details = repository.create_node(screen_id=screen_a.id, node_key="node-details", text="Details", clickable=True)
    action_details = repository.create_action(
        session_id=mapper_session.id, screen_id=screen_a.id, node_id=node_details.id,
        action_key="click:details", action_type="click", label="Details", safety=MapperActionSafety.SAFE,
    )
    transition_a_to_b = repository.create_transition(session_id=mapper_session.id, from_screen_id=screen_a.id, action_id=action_details.id, to_screen_id=screen_b.id, result_type="clicked")

    return {
        "session": mapper_session,
        "screen_root": screen_root,
        "screen_a": screen_a,
        "screen_b": screen_b,
        "transition_root_to_a": transition_root_to_a,
        "transition_a_to_b": transition_a_to_b,
    }


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
        flow_id = flow.id

    with SessionLocal() as session:
        flow_repository = SqlAlchemyMapperFlowRepository(session)
        loaded = MapperFlowService(session).get_flow(flow_id)
        assert loaded is not None
        steps = flow_repository.ordered_steps(loaded)
        assert len(steps) == 2
        assert steps[0].action_type == "click"


def test_create_flow_promoted_from_session_transition_pulls_its_ancestors() -> None:
    with SessionLocal() as session:
        fixture = _seed_two_screen_session(session)
        session.commit()
        session_id = fixture["session"].id
        transition_a_to_b_id = fixture["transition_a_to_b"].id

    with SessionLocal() as session:
        flow = MapperFlowService(session).create_flow(
            name="promoted_flow",
            package_name="com.linkedin.android",
            source_session_id=session_id,
            transition_ids=[transition_a_to_b_id],
        )
        session.commit()
        flow_id = flow.id

    with SessionLocal() as session:
        flow_repository = SqlAlchemyMapperFlowRepository(session)
        loaded = MapperFlowService(session).get_flow(flow_id)
        steps = flow_repository.ordered_steps(loaded)
        # the target step (click Details) plus its one ancestor (click Profile, to reach screen A)
        assert [step.action_type for step in steps] == ["click", "click"]
        assert steps[0].selector_json == {"candidates": ["Profile"]}
        assert steps[1].selector_json == {"candidates": ["Details"]}


def test_add_step_auto_includes_ancestor_chain_and_reports_it() -> None:
    with SessionLocal() as session:
        fixture = _seed_two_screen_session(session)
        session.commit()
        screen_b_id = fixture["screen_b"].id

    with SessionLocal() as session:
        service = MapperFlowService(session)
        flow = service.create_flow(name="deep_flow", package_name="com.linkedin.android", steps=[{"action_type": "back", "selector": {}}])
        session.commit()
        flow_id = flow.id

    with SessionLocal() as session:
        service = MapperFlowService(session)
        outcome = service.add_step(flow_id, {"action_type": "screenshot", "selector": {}, "source_screen_id": screen_b_id})
        session.commit()
        assert len(outcome["ancestors"]) == 2  # click Profile, click Details
        assert outcome["step"].action_type == "screenshot"

    with SessionLocal() as session:
        flow_repository = SqlAlchemyMapperFlowRepository(session)
        loaded = MapperFlowService(session).get_flow(flow_id)
        steps = flow_repository.ordered_steps(loaded)
        # back (manual, first) + 2 ancestors + screenshot itself
        assert [step.action_type for step in steps] == ["back", "click", "click", "screenshot"]


def test_reusing_the_same_source_action_does_not_duplicate_the_step() -> None:
    with SessionLocal() as session:
        fixture = _seed_two_screen_session(session, package_name="com.dedupe.testapp")
        session.commit()
        screen_a_id = fixture["screen_a"].id

    with SessionLocal() as session:
        service = MapperFlowService(session)
        flow_1 = service.create_flow(name="flow_1", package_name="com.dedupe.testapp", steps=[{"action_type": "back", "selector": {}}])
        flow_2 = service.create_flow(name="flow_2", package_name="com.dedupe.testapp", steps=[{"action_type": "wait", "selector": {}}])
        session.commit()
        flow_1_id, flow_2_id = flow_1.id, flow_2.id

    with SessionLocal() as session:
        service = MapperFlowService(session)
        outcome_1 = service.add_step(flow_1_id, {"action_type": "click", "selector": {}, "source_screen_id": screen_a_id})
        session.commit()
        ancestor_step_id = outcome_1["ancestors"][0].id

    with SessionLocal() as session:
        service = MapperFlowService(session)
        outcome_2 = service.add_step(flow_2_id, {"action_type": "back", "selector": {}, "source_screen_id": screen_a_id})
        session.commit()
        assert outcome_2["ancestors"][0].id == ancestor_step_id  # same step definition reused, not duplicated


def test_create_flow_requires_steps_or_transitions() -> None:
    with SessionLocal() as session:
        with pytest.raises(ValueError):
            MapperFlowService(session).create_flow(name="invalid_flow", package_name="com.invalid.testapp")


def test_add_step_requires_step_id_or_action_type() -> None:
    with SessionLocal() as session:
        flow = MapperFlowService(session).create_flow(name="strict_flow", package_name="com.strict.testapp", steps=[{"action_type": "back", "selector": {}}])
        session.commit()
        flow_id = flow.id

    with SessionLocal() as session:
        with pytest.raises(ValueError):
            MapperFlowService(session).add_step(flow_id, {})


def test_update_and_remove_step_via_service() -> None:
    with SessionLocal() as session:
        flow = MapperFlowService(session).create_flow(
            name="editable_flow",
            package_name="com.editable.testapp",
            steps=[{"action_type": "click", "selector": {"candidates": ["Profile"]}}],
        )
        session.commit()
        flow_id = flow.id
        flow_repository = SqlAlchemyMapperFlowRepository(session)
        step_id = flow_repository.ordered_steps(flow)[0].id

    with SessionLocal() as session:
        service = MapperFlowService(session)
        service.add_step(flow_id, {"action_type": "back", "selector": {}})
        session.commit()

    with SessionLocal() as session:
        service = MapperFlowService(session)
        service.update_step(step_id, action_type="click", selector={"candidates": ["Updated"]})
        session.commit()

    with SessionLocal() as session:
        flow_repository = SqlAlchemyMapperFlowRepository(session)
        loaded = MapperFlowService(session).get_flow(flow_id)
        steps = flow_repository.ordered_steps(loaded)
        assert len(steps) == 2
        assert steps[0].selector_json == {"candidates": ["Updated"]}

    with SessionLocal() as session:
        service = MapperFlowService(session)
        service.remove_step(flow_id, step_id)
        session.commit()

    with SessionLocal() as session:
        flow_repository = SqlAlchemyMapperFlowRepository(session)
        loaded = MapperFlowService(session).get_flow(flow_id)
        steps = flow_repository.ordered_steps(loaded)
        assert len(steps) == 1
        # the step definition itself still exists (removed from this flow only, not deleted)
        assert flow_repository.get_step(step_id) is not None


def test_get_or_create_step_prefers_resource_id_with_text_fallback() -> None:
    # issue #60: a node's resource_id is stable across targets whose visible text is dynamic (a
    # DM reply bar showing "Reply to <contact>"), the generated step selector must carry both,
    # not just the text that was visible at mapping time
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.create_session(package_name="com.instagram.android", mode=MapperMode.LIGHT, skip_dangerous_actions=True, max_depth=1, max_actions=8, max_scrolls=0)
        screen_root = repository.create_screen(session_id=mapper_session.id, fingerprint="root", screen_key="root", depth=0, ordinal=0)
        screen_thread = repository.create_screen(session_id=mapper_session.id, fingerprint="thread", screen_key="thread", depth=1, ordinal=1)
        node = repository.create_node(
            screen_id=screen_root.id, node_key="node-reply", text="Reply to Rafael Alexandre ....",
            resource_id="com.instagram.android:id/reply_bar_edittext", clickable=True,
        )
        action = repository.create_action(
            session_id=mapper_session.id, screen_id=screen_root.id, node_id=node.id,
            action_key="click:reply", action_type="click", label="Reply to Rafael Alexandre ....", safety=MapperActionSafety.SAFE,
        )
        repository.create_transition(session_id=mapper_session.id, from_screen_id=screen_root.id, action_id=action.id, to_screen_id=screen_thread.id, result_type="clicked")
        session.commit()
        action_id = action.id

    with SessionLocal() as session:
        step = MapperFlowService(session).get_or_create_step_for_action("com.instagram.android", action_id)

        assert step.selector_json == {
            "resource_id": "com.instagram.android:id/reply_bar_edittext",
            "candidates": ["Reply to Rafael Alexandre ...."],
        }
