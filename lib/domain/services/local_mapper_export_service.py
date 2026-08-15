from __future__ import annotations

from pathlib import Path

from lib.core.logs import get_logger
from lib.core.utils.json_utils import write_json
from lib.dal.local.database import session_scope
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_model import MapperScreen
from lib.domain.services.mapper_export_service import MapperExportService


class LocalMapperExportService(MapperExportService):
    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def export_session(self, session_id: int, output_dir: Path) -> Path:
        with session_scope() as session:
            repository = SqlAlchemyMapperRepository(session)
            mapper_session = repository.get_session(session_id)
            if mapper_session is None:
                raise ValueError(f"Mapper session {session_id} not found")

            base_dir = output_dir / f"mapper_session_{session_id}"
            screens_dir = base_dir / "screens"
            base_dir.mkdir(parents=True, exist_ok=True)
            screens_dir.mkdir(parents=True, exist_ok=True)

            for screen in mapper_session.screens:
                write_json(screens_dir / f"screen_{screen.id}.json", self._screen_payload(screen))

            self.logger.info("Exporting mapper session %s to %s", session_id, base_dir)
            write_json(
                base_dir / "index.json",
                {
                    "session": {
                        "id": mapper_session.id,
                        "package_name": mapper_session.package_name,
                        "mode": mapper_session.mode.value,
                        "status": mapper_session.status.value,
                        "skip_dangerous_actions": mapper_session.skip_dangerous_actions,
                        "max_depth": mapper_session.max_depth,
                        "max_actions": mapper_session.max_actions,
                        "max_scrolls": mapper_session.max_scrolls,
                        "created_at": mapper_session.created_at.isoformat(),
                    },
                    "screens": [self._screen_summary(screen) for screen in mapper_session.screens],
                    "actions": [
                        {
                            "id": action.id,
                            "screen_id": action.screen_id,
                            "action_key": action.action_key,
                            "action_type": action.action_type,
                            "label": action.label,
                            "safety": action.safety.value,
                            "skipped_reason": action.skipped_reason,
                            "executed": action.executed,
                            "success": action.success,
                        }
                        for action in mapper_session.actions
                    ],
                    "transitions": [
                        {
                            "id": transition.id,
                            "from_screen_id": transition.from_screen_id,
                            "action_id": transition.action_id,
                            "to_screen_id": transition.to_screen_id,
                            "result_type": transition.result_type,
                        }
                        for transition in mapper_session.transitions
                    ],
                },
            )
            return base_dir

    @staticmethod
    def _screen_summary(screen: MapperScreen) -> dict:
        return {
            "id": screen.id,
            "screen_key": screen.screen_key,
            "fingerprint": screen.fingerprint,
            "depth": screen.depth,
            "ordinal": screen.ordinal,
            "visit_count": screen.visit_count,
            "node_count": len(screen.nodes),
        }

    def _screen_payload(self, screen: MapperScreen) -> dict:
        return {
            **self._screen_summary(screen),
            "nodes": [
                {
                    "id": node.id,
                    "node_key": node.node_key,
                    "text": node.text,
                    "content_desc": node.content_desc,
                    "resource_id": node.resource_id,
                    "class_name": node.class_name,
                    "bounds": node.bounds,
                    "clickable": node.clickable,
                    "enabled": node.enabled,
                    "scrollable": node.scrollable,
                }
                for node in screen.nodes
            ],
        }
