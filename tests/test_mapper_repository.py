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
