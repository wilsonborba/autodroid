from __future__ import annotations

from lib.domain.models.mapper_types import MapperMode
from lib.domain.services.mapper_mode_service import MapperModeService


def test_mapper_mode_limits_are_ordered_by_depth_and_actions() -> None:
    service = MapperModeService()

    light = service.get_limits(MapperMode.LIGHT)
    medium = service.get_limits(MapperMode.MEDIUM)
    deep = service.get_limits(MapperMode.DEEP)

    assert light.max_depth < medium.max_depth < deep.max_depth
    assert light.max_actions < medium.max_actions < deep.max_actions
    assert light.max_scrolls <= medium.max_scrolls <= deep.max_scrolls
