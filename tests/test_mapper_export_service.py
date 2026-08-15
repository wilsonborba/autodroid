from __future__ import annotations

from pathlib import Path

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode
from lib.domain.services.local_mapper_export_service import LocalMapperExportService


def test_mapper_export_service_writes_index_and_screen_files(tmp_path: Path) -> None:
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
        screen = repository.create_screen(session_id=mapper_session.id, fingerprint="f1", screen_key="screen-1", depth=0, ordinal=0)
        node = repository.create_node(screen_id=screen.id, node_key="n1", text="Profile", clickable=True)
        action = repository.create_action(session_id=mapper_session.id, screen_id=screen.id, node_id=node.id, action_key="click:profile", action_type="click", label="Profile", safety=MapperActionSafety.SAFE)
        repository.create_transition(session_id=mapper_session.id, from_screen_id=screen.id, action_id=action.id, to_screen_id=None, result_type="clicked")
        session.commit()
        session_id = mapper_session.id

    export_dir = LocalMapperExportService().export_session(session_id, tmp_path)

    assert (export_dir / "index.json").exists()
    assert (export_dir / "screens" / "screen_1.json").exists()
