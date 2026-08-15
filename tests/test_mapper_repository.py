from __future__ import annotations

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperSessionStatus


def test_mapper_repository_creates_session_and_screen() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.create_session(
            package_name="com.linkedin.android",
            mode=MapperMode.LIGHT,
            skip_dangerous_actions=True,
            max_depth=1,
            max_actions=8,
            max_scrolls=0,
        )
        screen = repository.create_screen(
            session_id=mapper_session.id,
            fingerprint="abc123",
            screen_key="screen-1",
            depth=0,
            ordinal=0,
        )
        node = repository.create_node(screen_id=screen.id, node_key="node-1", text="Profile", clickable=True)
        repository.create_action(
            session_id=mapper_session.id,
            screen_id=screen.id,
            node_id=node.id,
            action_key="click:profile",
            action_type="click",
            label="Profile",
            safety=MapperActionSafety.SAFE,
        )
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        loaded = repository.get_session(mapper_session.id)
        assert loaded is not None
        assert loaded.package_name == "com.linkedin.android"
        assert len(loaded.screens) == 1
        assert len(loaded.actions) == 1


def test_get_latest_session_returns_most_recent_completed_session() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        older = repository.create_session(
            package_name="com.example.app",
            mode=MapperMode.LIGHT,
            skip_dangerous_actions=True,
            max_depth=1,
            max_actions=8,
            max_scrolls=0,
        )
        older.status = MapperSessionStatus.COMPLETED
        newer = repository.create_session(
            package_name="com.example.app",
            mode=MapperMode.LIGHT,
            skip_dangerous_actions=True,
            max_depth=1,
            max_actions=8,
            max_scrolls=0,
        )
        newer.status = MapperSessionStatus.COMPLETED
        session.commit()
        newer_id = newer.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        latest = repository.get_latest_session("com.example.app", status=MapperSessionStatus.COMPLETED)
        assert latest is not None
        assert latest.id == newer_id


def test_get_latest_session_returns_none_when_no_session_exists() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        assert repository.get_latest_session("com.unknown.app") is None


def _build_graph_fixture(repository: SqlAlchemyMapperRepository):
    mapper_session = repository.create_session(
        package_name="com.linkedin.android",
        mode=MapperMode.LIGHT,
        skip_dangerous_actions=True,
        max_depth=2,
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
        executed=True,
        success=True,
    )
    transition = repository.create_transition(
        session_id=mapper_session.id,
        from_screen_id=screen_a.id,
        action_id=action.id,
        to_screen_id=screen_b.id,
        result_type="clicked",
    )
    return mapper_session, screen_a, screen_b, node, action, transition


def test_list_screens_returns_screens_ordered_by_ordinal() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session, screen_a, screen_b, *_ = _build_graph_fixture(repository)
        session.commit()
        session_id = mapper_session.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        screens = repository.list_screens(session_id)
        assert [screen.screen_key for screen in screens] == ["screen-a", "screen-b"]
        assert len(screens[0].nodes) == 1


def test_get_screen_returns_screen_with_nodes() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        _, screen_a, *_ = _build_graph_fixture(repository)
        session.commit()
        screen_id = screen_a.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        screen = repository.get_screen(screen_id)
        assert screen is not None
        assert len(screen.nodes) == 1
        assert screen.nodes[0].text == "Profile"


def test_list_actions_filters_by_screen_safety_and_executed() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session, screen_a, screen_b, *_ = _build_graph_fixture(repository)
        repository.create_action(
            session_id=mapper_session.id,
            screen_id=screen_b.id,
            node_id=None,
            action_key="click:delete",
            action_type="click",
            label="Delete",
            safety=MapperActionSafety.DANGEROUS,
            executed=False,
        )
        session.commit()
        session_id, screen_a_id, screen_b_id = mapper_session.id, screen_a.id, screen_b.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        all_actions = repository.list_actions(session_id)
        assert len(all_actions) == 2

        screen_a_actions = repository.list_actions(session_id, screen_id=screen_a_id)
        assert len(screen_a_actions) == 1
        assert screen_a_actions[0].screen_id == screen_a_id

        dangerous_actions = repository.list_actions(session_id, safety=MapperActionSafety.DANGEROUS)
        assert len(dangerous_actions) == 1
        assert dangerous_actions[0].screen_id == screen_b_id

        executed_actions = repository.list_actions(session_id, executed=True)
        assert len(executed_actions) == 1


def test_list_transitions_returns_transitions_for_session() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session, *_ = _build_graph_fixture(repository)
        session.commit()
        session_id = mapper_session.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        transitions = repository.list_transitions(session_id)
        assert len(transitions) == 1
        assert transitions[0].result_type == "clicked"


def test_get_transition_action_and_node_lookup_helpers() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        _, screen_a, _, node, action, transition = _build_graph_fixture(repository)
        session.commit()
        transition_id, action_id, node_id = transition.id, action.id, node.id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        assert repository.get_transition(transition_id).id == transition_id
        assert repository.get_action(action_id).id == action_id
        assert repository.get_node(node_id).id == node_id
